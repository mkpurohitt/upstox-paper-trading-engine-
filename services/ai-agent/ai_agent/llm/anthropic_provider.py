"""Anthropic Messages API provider (secondary / fallback)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic
import httpx
from anthropic import AsyncAnthropic

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


def to_anthropic(messages: list[ChatMsg]) -> tuple[str, list[dict[str, Any]]]:
    """Split out the system prompt; tool results become user turns of tool_result blocks."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif m.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in m.tool_calls]
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        else:
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], str):
                out[-1]["content"] += "\n\n" + m.content
            else:
                out.append({"role": "user", "content": m.content})
    return system, out


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, *, api_key: str, cheap_model: str, strong_model: str, timeout_s: float = 60.0) -> None:
        self.cheap_model, self.strong_model = cheap_model, strong_model
        self.client = AsyncAnthropic(api_key=api_key, max_retries=1, timeout=httpx.Timeout(timeout_s, connect=5.0))

    def model_for(self, tier: Tier) -> str:
        return self.strong_model if tier == "strong" else self.cheap_model

    async def stream(
        self, messages: list[ChatMsg], tools: list[ToolSpec], *, model: str, max_tokens: int = 1500, temperature: float = 0.2
    ) -> AsyncIterator[LLMEvent]:
        system, conv = to_anthropic(messages)
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": conv}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        try:
            async with self.client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield TextDelta(event.text)
                final = await stream.get_final_message()
        except anthropic.BadRequestError as exc:
            raise LLMError(f"anthropic: {exc}", provider=self.name, retryable=False) from exc
        except (anthropic.APIError, httpx.HTTPError) as exc:
            raise LLMError(f"anthropic: {exc.__class__.__name__}", provider=self.name) from exc
        calls = [ToolCall(id=b.id, name=b.name, arguments=dict(b.input) if isinstance(b.input, dict) else {})
                 for b in final.content if b.type == "tool_use"]
        if calls:
            yield ToolCallsEvent(calls)
        yield Finish(Usage(final.usage.input_tokens, final.usage.output_tokens), model, self.name, final.stop_reason or "stop")
