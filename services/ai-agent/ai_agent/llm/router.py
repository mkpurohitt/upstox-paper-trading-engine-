"""LLM gateway: provider chain with fallback, cheap/strong routing, circuit breaker and cost tracking."""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache

from ai_agent.llm.base import (
    ChatMsg,
    Finish,
    LLMError,
    LLMEvent,
    LLMProvider,
    TextDelta,
    Tier,
    ToolCallsEvent,
    ToolSpec,
)
from algo_common.logging import get_logger
from algo_common.settings import Settings, get_settings

log = get_logger("ai.router")

_STRONG = re.compile(
    r"strateg|backtest|build|design|portfolio|analy[sz]|compare|optimi|risk|why|explain|walk.?forward|hedge|"
    r"iron condor|straddle|strangle|spread|pair|deploy|review|plan", re.I)
COOLDOWN_S = 60.0


def choose_tier(text: str, has_context: bool = False) -> Tier:
    """Cheap model for short lookups; strong model for research, strategy building and multi-step work."""
    if has_context or len(text) > 280 or _STRONG.search(text):
        return "strong"
    return "cheap"


@dataclass
class Served:
    provider: str
    model: str
    fallback_from: list[str]


def build_providers(s: Settings) -> list[LLMProvider]:
    from ai_agent.llm.anthropic_provider import AnthropicProvider
    from ai_agent.llm.mock import MockProvider
    from ai_agent.llm.openai_compat import OllamaProvider, OpenAICompatProvider

    def make(kind: str) -> LLMProvider | None:
        if kind == "openai_compat" and s.llm_primary_api_key and s.llm_primary_base_url:
            primary = s.llm_primary_model
            return OpenAICompatProvider(
                name="openai_compat", base_url=s.llm_primary_base_url, api_key=s.llm_primary_api_key.get_secret_value(),
                cheap_model=s.llm_cheap_model or primary, strong_model=s.llm_strong_model or primary, timeout_s=s.llm_request_timeout_s)
        if kind == "anthropic" and s.anthropic_api_key:
            return AnthropicProvider(api_key=s.anthropic_api_key.get_secret_value(), cheap_model=s.anthropic_model_cheap,
                                     strong_model=s.anthropic_model_strong, timeout_s=s.llm_request_timeout_s)
        if kind == "ollama" and (s.ollama_enabled or s.llm_primary_provider == "ollama"):
            return OllamaProvider(base_url=s.ollama_base_url, model=s.ollama_model)
        if kind == "mock":
            return MockProvider()
        return None

    order = [s.llm_primary_provider] + [k.strip() for k in s.llm_fallbacks.split(",") if k.strip()]
    if s.llm_mock_fallback or s.llm_primary_provider == "mock":
        order.append("mock")
    out: list[LLMProvider] = []
    for kind in dict.fromkeys(order):
        p = make(kind)
        if p is not None:
            out.append(p)
    if not out:
        out.append(MockProvider())
    return out


class LLMRouter:
    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers
        self._down_until: dict[str, float] = {}

    @property
    def primary(self) -> LLMProvider:
        return self.providers[0]

    def status(self) -> list[dict[str, object]]:
        now = time.monotonic()
        return [{"provider": p.name, "cheap_model": p.model_for("cheap"), "strong_model": p.model_for("strong"),
                 "healthy": self._down_until.get(p.name, 0) <= now} for p in self.providers]

    async def stream(self, messages: list[ChatMsg], tools: list[ToolSpec], *, tier: Tier = "cheap",
                     max_tokens: int = 1500, served: list[Served] | None = None) -> AsyncIterator[LLMEvent]:
        """Stream from the first healthy provider; fall back on retryable errors raised before any output."""
        tried: list[str] = []
        last_exc: LLMError | None = None
        now = time.monotonic()
        candidates = [p for p in self.providers if self._down_until.get(p.name, 0) <= now] or self.providers[-1:]
        for p in candidates:
            model = p.model_for(tier)
            emitted = False
            try:
                async for ev in p.stream(messages, tools, model=model, max_tokens=max_tokens):
                    if isinstance(ev, TextDelta | ToolCallsEvent):
                        emitted = True
                    if isinstance(ev, Finish) and served is not None:
                        served.append(Served(p.name, model, tried))
                    yield ev
                self._down_until.pop(p.name, None)
                return
            except LLMError as exc:
                last_exc = exc
                log.warning("llm.provider_failed", provider=p.name, model=model, error=str(exc), emitted=emitted)
                if emitted:
                    raise
                if exc.retryable:
                    self._down_until[p.name] = time.monotonic() + COOLDOWN_S
                tried.append(p.name)
                continue
        raise last_exc or LLMError("no LLM provider available", provider="router")


@lru_cache(maxsize=1)
def get_router() -> LLMRouter:
    return LLMRouter(build_providers(get_settings()))


def reset_router() -> None:
    get_router.cache_clear()


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    """Cost from LLM_PRICING_JSON ({"model": [usd_per_1M_in, usd_per_1M_out]}); unknown models cost 0."""
    try:
        table = json.loads(get_settings().llm_pricing_json or "{}")
    except json.JSONDecodeError:
        table = {}
    price = table.get(model)
    if not price:
        return 0.0
    return round(tokens_in / 1e6 * float(price[0]) + tokens_out / 1e6 * float(price[1]), 6)
