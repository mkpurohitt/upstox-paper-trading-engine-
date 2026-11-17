"""Tool registry: typed arguments (Pydantic), JSON-schema specs for the LLM, UI cards, timeouts and error capture."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from ai_agent.llm.base import ToolSpec
from algo_common.logging import get_logger

log = get_logger("ai.tools")
MAX_LLM_CHARS = 12_000
QuotaCheck = Callable[[str], Awaitable[None]]


@dataclass
class ToolContext:
    user_id: int
    role: str = "user"
    session_id: int | None = None
    quota: QuotaCheck | None = None  # injected by the API layer (plan limits for backtests etc.)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    data: dict[str, Any]
    card: dict[str, Any] | None = None
    ok: bool = True

    def llm_payload(self) -> str:
        s = json.dumps(self.data, default=str, separators=(",", ":"))
        if len(s) > MAX_LLM_CHARS:
            s = json.dumps({"truncated": True, "preview": s[:MAX_LLM_CHARS]}, default=str)
        return s


Handler = Callable[[ToolContext, Any], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    handler: Handler
    params: type[BaseModel] | None = None
    schema: dict[str, Any] | None = None
    category: str = "data"
    timeout_s: float = 45.0

    def spec(self) -> ToolSpec:
        if self.params is not None:
            schema = _clean(self.params.model_json_schema())
        else:
            schema = self.schema or {"type": "object", "properties": {}}
        return ToolSpec(self.name, self.description, schema)


def _clean(schema: dict[str, Any]) -> dict[str, Any]:
    """Drop titles (noise for the model) recursively; keep $defs/refs intact."""
    if isinstance(schema, dict):
        return {k: _clean(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [_clean(v) for v in schema]  # type: ignore[return-value]
    return schema


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, params: type[BaseModel], *, category: str = "data", timeout_s: float = 45.0) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        TOOLS[name] = Tool(name, description, fn, params=params, category=category, timeout_s=timeout_s)
        return fn
    return deco


_dynamic: dict[str, Tool] = {}


async def all_tools() -> list[Tool]:
    from ai_agent.tools import load_all
    from ai_agent.tools.nse import nse_tools

    load_all()
    if not _dynamic:
        try:
            for t in await nse_tools():
                _dynamic[t.name] = t
        except Exception as exc:
            log.warning("tools.nse_list_failed", error=str(exc))
    return [*TOOLS.values(), *_dynamic.values()]


async def execute(name: str, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
    tools = {t.name: t for t in await all_tools()}
    t = tools.get(name)
    if t is None:
        return ToolResult({"error": f"unknown tool {name!r}"}, ok=False)
    if "_invalid_json" in arguments:
        return ToolResult({"error": "arguments were not valid JSON; retry with a JSON object"}, ok=False)
    try:
        args: Any = t.params.model_validate(arguments) if t.params is not None else arguments
    except ValidationError as exc:
        msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
        return ToolResult({"error": f"invalid arguments: {msg}"}, ok=False)
    try:
        res = await asyncio.wait_for(t.handler(ctx, args), timeout=t.timeout_s)
    except TimeoutError:
        return ToolResult({"error": f"{name} timed out"}, ok=False)
    except Exception as exc:  # tool errors are reported to the model, never crash the turn
        detail = getattr(exc, "detail", None) or str(exc) or exc.__class__.__name__
        log.warning("tools.failed", tool=name, error=str(detail))
        return ToolResult({"error": str(detail)[:400]}, ok=False)
    # guarantee JSON-serialisable payloads
    res.data = json.loads(json.dumps(res.data, default=str))
    if res.card is not None:
        res.card = json.loads(json.dumps(res.card, default=str))
    return res
