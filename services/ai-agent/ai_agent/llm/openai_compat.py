"""OpenAI-compatible chat provider ("GPT-6 Luna" primary, also used for Ollama's /v1 endpoint)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from ai_agent.llm.base import (
    ChatMsg,
    Finish,
    LLMError,
    LLMEvent,
    LLMProvider,
    TextDelta,
    Tier,
    ToolCall,
    ToolCallsEvent,
    ToolSpec,
    Usage,
)


def to_openai_messages(messages: list[ChatMsg]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.role == "assistant" and m.tool_calls:
            out.append({
                "role": "assistant", "content": m.content or None,
                "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments_json()}}
                               for c in m.tool_calls],
            })
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def to_openai_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]


class OpenAICompatProvider(LLMProvider):
    def __init__(self, *, name: str, base_url: str, api_key: str, cheap_model: str, strong_model: str,
                 timeout_s: float = 60.0, connect_timeout_s: float = 5.0, token_param: str = "max_completion_tokens") -> None:  # noqa: S107 (a parameter name, not a secret)
        self.name = name
        self.cheap_model, self.strong_model = cheap_model, strong_model
        self.token_param = token_param
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=1,
                                  timeout=httpx.Timeout(timeout_s, connect=connect_timeout_s))

    def model_for(self, tier: Tier) -> str:
        return self.strong_model if tier == "strong" else self.cheap_model

    async def stream(
        self, messages: list[ChatMsg], tools: list[ToolSpec], *, model: str, max_tokens: int = 1500, temperature: float = 0.2
    ) -> AsyncIterator[LLMEvent]:
        kwargs: dict[str, Any] = {
            "model": model, "messages": to_openai_messages(messages), "stream": True, "temperature": temperature,
            self.token_param: max_tokens, "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = to_openai_tools(tools)
        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except openai.BadRequestError as exc:
            if self.token_param == "max_completion_tokens" and "max_completion_tokens" in str(exc):
                # older OpenAI-compatible servers only know max_tokens
                self.token_param = "max_tokens"
                async for ev in self.stream(messages, tools, model=model, max_tokens=max_tokens, temperature=temperature):
                    yield ev
                return
            raise LLMError(f"{self.name}: {exc}", provider=self.name, retryable=False) from exc
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.InternalServerError) as exc:
            raise LLMError(f"{self.name}: {exc.__class__.__name__}", provider=self.name) from exc
        except openai.APIError as exc:
            raise LLMError(f"{self.name}: {exc}", provider=self.name) from exc

        slots: dict[int, dict[str, str]] = {}
        usage = Usage()
        stop = "stop"
        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = Usage(chunk.usage.prompt_tokens or 0, chunk.usage.completion_tokens or 0)
                for choice in chunk.choices:
                    d = choice.delta
                    if d is not None and d.content:
                        yield TextDelta(d.content)
                    for tc in (d.tool_calls if d is not None and d.tool_calls else []):
                        slot = slots.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function is not None:
                            slot["name"] += tc.function.name or ""
                            slot["args"] += tc.function.arguments or ""
                    if choice.finish_reason:
                        stop = choice.finish_reason
        except (openai.APIError, httpx.HTTPError) as exc:
            raise LLMError(f"{self.name}: stream interrupted ({exc.__class__.__name__})", provider=self.name) from exc
        if slots:
            calls = []
            for i, s in sorted(slots.items()):
                try:
                    args = json.loads(s["args"]) if s["args"].strip() else {}
                except json.JSONDecodeError:
                    args = {"_invalid_json": s["args"][:500]}
                calls.append(ToolCall(id=s["id"] or f"call_{i}", name=s["name"], arguments=args if isinstance(args, dict) else {}))
            yield ToolCallsEvent(calls)
        yield Finish(usage, model, self.name, stop)


class OllamaProvider(OpenAICompatProvider):
    """Ollama serves an OpenAI-compatible API under /v1 (tool calling supported by recent models)."""

    def __init__(self, *, base_url: str, model: str, timeout_s: float = 120.0) -> None:
        super().__init__(name="ollama", base_url=base_url.rstrip("/") + "/v1", api_key="ollama", cheap_model=model,
                         strong_model=model, timeout_s=timeout_s, connect_timeout_s=2.0, token_param="max_tokens")
