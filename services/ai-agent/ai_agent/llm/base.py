"""Provider-neutral chat types for the LLM gateway."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]
Tier = Literal["cheap", "strong"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def arguments_json(self) -> str:
        return json.dumps(self.arguments, default=str)


@dataclass
class ChatMsg:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None  # tool name for role=tool


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0

    def __iadd__(self, other: Usage) -> Usage:
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out
        return self


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallsEvent:
    calls: list[ToolCall]


@dataclass
class Finish:
    usage: Usage
    model: str
    provider: str
    stop_reason: str = "stop"


LLMEvent = TextDelta | ToolCallsEvent | Finish


class LLMError(Exception):
    """Provider failure. `retryable` errors trigger fallback to the next provider."""

    def __init__(self, message: str, *, provider: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def model_for(self, tier: Tier) -> str: ...

    @abstractmethod
    def stream(
        self, messages: list[ChatMsg], tools: list[ToolSpec], *, model: str, max_tokens: int = 1500, temperature: float = 0.2
    ) -> AsyncIterator[LLMEvent]: ...

    async def complete(self, messages: list[ChatMsg], *, model: str, max_tokens: int = 600) -> tuple[str, Usage]:
        """Non-streaming helper (summaries, sentiment): concatenates the stream."""
        text, usage = [], Usage()
        async for ev in self.stream(messages, [], model=model, max_tokens=max_tokens):
            if isinstance(ev, TextDelta):
                text.append(ev.text)
            elif isinstance(ev, Finish):
                usage = ev.usage
        return "".join(text), usage


def estimate_tokens(text: str) -> int:
    """~4 chars/token heuristic (used for the offline provider and budget checks)."""
    return max(1, len(text) // 4)
