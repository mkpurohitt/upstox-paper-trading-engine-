"""NSE MCP tools, exposed dynamically as `nse_<tool>` from the server's tool list (official MCP SDK client)."""

from __future__ import annotations

from typing import Any

from ai_agent.guardrails import neutralise
from ai_agent.tools.registry import Tool, ToolContext, ToolResult
from market_data.nse_mcp import call_nse_tool, get_nse_tools


def _first_list(d: Any) -> tuple[str | None, list[Any]]:
    if isinstance(d, list):
        return None, d
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return k, v
    return None, []


def _defang(v: Any) -> Any:
    if isinstance(v, str):
        return neutralise(v)
    if isinstance(v, list):
        return [_defang(x) for x in v]
    if isinstance(v, dict):
        return {k: _defang(x) for k, x in v.items()}
    return v


def _make(name: str, description: str, schema: dict[str, Any]) -> Tool:
    async def handler(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        missing = [r for r in schema.get("required", []) if r not in args]
        if missing:
            return ToolResult({"error": f"missing required arguments {missing}"}, ok=False)
        res = await call_nse_tool(name, args)
        if isinstance(res, dict) and res.get("is_error"):
            return ToolResult({"error": res.get("text", "NSE tool error")}, ok=False)
        if not isinstance(res, dict | list):
            res = {"text": str(res)}
        res = _defang(res)
        _key, rows = _first_list(res)
        title = name.removeprefix("get_").replace("_", " ").title()
        card: dict[str, Any] = {"type": "table", "title": f"NSE · {title}", "rows": rows[:25], "source": "nse_mcp"}
        if not rows:
            card = {"type": "kv", "title": f"NSE · {title}", "data": res if isinstance(res, dict) else {"items": res}}
        return ToolResult(res if isinstance(res, dict) else {"items": res}, card)

    return Tool(name=f"nse_{name}", description=f"[NSE] {description}", handler=handler, schema=schema or {"type": "object", "properties": {}},
                category="nse", timeout_s=30.0)


async def nse_tools() -> list[Tool]:
    client = get_nse_tools()
    out = []
    for t in await client.list_tools():
        schema = t.get("input_schema") or t.get("inputSchema") or {"type": "object", "properties": {}}
        out.append(_make(t["name"], t.get("description") or t["name"], schema))
    return out
