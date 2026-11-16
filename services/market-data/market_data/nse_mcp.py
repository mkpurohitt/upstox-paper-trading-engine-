"""NSE MCP client.

Connects to an NSE MCP server (`NSE_MCP_URL`) using the official MCP Python SDK
and exposes its tools (indices, corporate actions, FII/DII flows, bulk/block
deals, announcements, ...) to the backend and the LLM agent.

When no server is configured the `MockNseTools` implementation serves the same
tool names with deterministic sample data, so the UI and agent work offline.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import date, timedelta
from typing import Any

from algo_common.logging import get_logger
from algo_common.settings import get_settings
from algo_common.timeutils import now_ist, previous_trading_day
from market_data.universe import EQUITIES

log = get_logger("nse_mcp")


class McpTool(dict[str, Any]):
    """{name, description, input_schema}"""


class NseMcpClient:
    def __init__(self, url: str, transport: str = "streamable_http", api_key: str | None = None) -> None:
        self.url = url
        self.transport = transport
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._tools: list[McpTool] | None = None

    @contextlib.asynccontextmanager
    async def _session(self):  # type: ignore[no-untyped-def]
        from mcp import ClientSession

        if self.transport == "sse":
            from mcp.client.sse import sse_client

            ctx = sse_client(self.url, headers=self.headers)
        else:
            import mcp.client.streamable_http as sh

            if hasattr(sh, "streamable_http_client"):  # mcp >= 2
                http_client = sh.create_mcp_http_client(headers=self.headers)
                ctx = sh.streamable_http_client(self.url, http_client=http_client)
            else:  # mcp 1.x
                ctx = sh.streamablehttp_client(self.url, headers=self.headers)  # type: ignore[attr-defined]
        async with ctx as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def list_tools(self) -> list[McpTool]:
        if self._tools is None:
            async with self._session() as s:
                res = await s.list_tools()
            self._tools = [
                McpTool(
                    name=t.name, description=t.description or "",
                    input_schema=(getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {"type": "object"}),
                )
                for t in res.tools
            ]
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        async with self._session() as s:
            res = await s.call_tool(name, arguments or {})
        structured = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
        if structured:
            return structured
        texts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
        joined = "\n".join(texts)
        with contextlib.suppress(ValueError):
            return json.loads(joined)
        is_error = getattr(res, "is_error", None) or getattr(res, "isError", False)
        return {"text": joined, "is_error": bool(is_error)}


def _h(*parts: object) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)  # noqa: S324


class MockNseTools:
    """Offline stand-in exposing the same tool surface as the NSE MCP server."""

    TOOLS: list[McpTool] = [
        McpTool(name="get_index_quotes", description="Live quotes for NSE indices (NIFTY 50, BANK NIFTY, sectoral)",
                input_schema={"type": "object", "properties": {"indices": {"type": "array", "items": {"type": "string"}}}}),
        McpTool(name="get_fii_dii_activity", description="Daily FII/FPI and DII cash-market buy/sell/net (₹ crore)",
                input_schema={"type": "object", "properties": {"days": {"type": "integer", "default": 10}}}),
        McpTool(name="get_corporate_actions", description="Upcoming corporate actions (dividends, splits, bonus, buybacks)",
                input_schema={"type": "object", "properties": {"symbol": {"type": "string"}}}),
        McpTool(name="get_corporate_announcements", description="Latest corporate announcements / exchange filings",
                input_schema={"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer"}}}),
        McpTool(name="get_bulk_block_deals", description="Bulk and block deals for the latest session",
                input_schema={"type": "object", "properties": {"kind": {"type": "string", "enum": ["bulk", "block"]}}}),
        McpTool(name="get_results_calendar", description="Upcoming board meetings for quarterly results",
                input_schema={"type": "object", "properties": {"days": {"type": "integer", "default": 14}}}),
        McpTool(name="get_market_breadth", description="Advance / decline / unchanged counts on NSE",
                input_schema={"type": "object", "properties": {}}),
        McpTool(name="get_shareholding_pattern", description="Promoter/FII/DII/public holding % for a company",
                input_schema={"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}),
    ]

    async def list_tools(self) -> list[McpTool]:
        return self.TOOLS

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        fn = getattr(self, f"_{name}", None)
        if fn is None:
            return {"is_error": True, "text": f"unknown tool {name}"}
        return fn(**args)

    # ---- mock tool implementations ----------------------------------------------------
    def _get_index_quotes(self, indices: list[str] | None = None) -> dict[str, Any]:
        return {"note": "use /api/market/quotes for live index prices", "indices": indices or ["NIFTY 50", "NIFTY BANK"]}

    def _get_fii_dii_activity(self, days: int = 10) -> dict[str, Any]:
        out = []
        d = now_ist().date()
        for _ in range(max(1, min(days, 60))):
            d = previous_trading_day(d)
            fb, fs = 9000 + _h("fb", d) % 9000, 9000 + _h("fs", d) % 9500
            db, ds = 8000 + _h("db", d) % 8000, 7000 + _h("ds", d) % 7500
            out.append({"date": d.isoformat(), "fii_buy": fb, "fii_sell": fs, "fii_net": fb - fs,
                        "dii_buy": db, "dii_sell": ds, "dii_net": db - ds})
        return {"unit": "INR crore", "segment": "cash", "rows": out, "source": "mock"}

    def _get_corporate_actions(self, symbol: str | None = None) -> dict[str, Any]:
        kinds = ["Interim Dividend - Rs {x} per share", "Final Dividend - Rs {x} per share", "Bonus 1:1",
                 "Stock split from Rs 10 to Rs 2", "Buyback"]
        rows = []
        base = now_ist().date()
        for i, a in enumerate(EQUITIES):
            if symbol and a.tradingsymbol != symbol.upper().split(":")[-1]:
                continue
            if _h("ca", a.symbol) % 3 and not symbol:
                continue
            k = kinds[_h("cak", a.symbol) % len(kinds)].format(x=round(1 + _h("x", a.symbol) % 30, 1))
            ex = base + timedelta(days=3 + (i * 5) % 40)
            rows.append({"symbol": a.tradingsymbol, "company": a.name, "purpose": k, "ex_date": ex.isoformat(),
                         "record_date": (ex + timedelta(days=1)).isoformat()})
        return {"rows": rows[:30], "source": "mock"}

    def _get_corporate_announcements(self, symbol: str | None = None, limit: int = 20) -> dict[str, Any]:
        subjects = ["Outcome of Board Meeting", "Press Release - Quarterly results", "Analyst / Investor Meet intimation",
                    "Credit rating reaffirmed", "Acquisition of stake in subsidiary", "Order win worth Rs {x} crore",
                    "Change in Key Managerial Personnel", "Investor presentation"]
        rows = []
        now = now_ist()
        for i, a in enumerate(EQUITIES):
            if symbol and a.tradingsymbol != symbol.upper().split(":")[-1]:
                continue
            subj = subjects[_h("ann", a.symbol, now.date()) % len(subjects)].format(x=100 + _h("o", a.symbol) % 4000)
            rows.append({"symbol": a.tradingsymbol, "company": a.name, "subject": subj,
                         "ts": (now - timedelta(minutes=17 * i + _h("t", a.symbol) % 50)).isoformat(),
                         "attachment": None})
        rows.sort(key=lambda r: r["ts"], reverse=True)
        return {"rows": rows[: max(1, min(limit, 100))], "source": "mock"}

    def _get_bulk_block_deals(self, kind: str = "bulk") -> dict[str, Any]:
        clients = ["Morgan Stanley Asia (Singapore)", "Goldman Sachs Fund", "SBI Mutual Fund", "Societe Generale",
                   "Nomura Singapore", "HDFC Mutual Fund", "Plutus Wealth Management", "Graviton Research Capital"]
        d = previous_trading_day(now_ist().date() + timedelta(days=1))
        rows = []
        for a in EQUITIES[:: 3 if kind == "bulk" else 5]:
            qty = (50_000 + _h("q", a.symbol, d) % 2_000_000)
            rows.append({"date": d.isoformat(), "symbol": a.tradingsymbol, "client": clients[_h("c", a.symbol, d) % len(clients)],
                         "side": "BUY" if _h("s", a.symbol, d) % 2 else "SELL", "quantity": qty,
                         "price": round(a.price * (0.98 + (_h("p", a.symbol) % 40) / 1000), 2)})
        return {"kind": kind, "rows": rows, "source": "mock"}

    def _get_results_calendar(self, days: int = 14) -> dict[str, Any]:
        base = now_ist().date()
        rows = []
        for a in EQUITIES:
            off = _h("res", a.symbol, base.month) % 45
            if off <= days:
                rows.append({"symbol": a.tradingsymbol, "company": a.name, "date": (base + timedelta(days=off)).isoformat(),
                             "purpose": "Quarterly financial results"})
        rows.sort(key=lambda r: r["date"])
        return {"rows": rows, "source": "mock"}

    def _get_market_breadth(self) -> dict[str, Any]:
        d = now_ist().date()
        adv = 900 + _h("adv", d) % 1400
        dec = 2900 - adv
        return {"advances": adv, "declines": dec, "unchanged": 80 + _h("unc", d) % 60, "source": "mock"}

    def _get_shareholding_pattern(self, symbol: str) -> dict[str, Any]:
        t = symbol.upper().split(":")[-1]
        promoter = 30 + _h("pr", t) % 45
        fii = 8 + _h("fii", t) % 25
        dii = 5 + _h("dii", t) % 20
        public = max(2, 100 - promoter - fii - dii)
        q = date(now_ist().year, ((now_ist().month - 1) // 3) * 3 + 1, 1) - timedelta(days=1)
        return {"symbol": t, "as_of": q.isoformat(), "promoter": promoter, "fii": fii, "dii": dii, "public": public,
                "pledged_pct_of_promoter": (_h("pl", t) % 8) * 0.5, "source": "mock"}


_client: NseMcpClient | MockNseTools | None = None


def get_nse_tools() -> NseMcpClient | MockNseTools:
    global _client
    if _client is None:
        s = get_settings()
        if s.nse_mcp_url:
            _client = NseMcpClient(
                s.nse_mcp_url, s.nse_mcp_transport, s.nse_mcp_api_key.get_secret_value() if s.nse_mcp_api_key else None
            )
        else:
            _client = MockNseTools()
    return _client


async def call_nse_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Call a tool on the configured NSE MCP server, falling back to the mock on failure."""
    client = get_nse_tools()
    try:
        return await client.call_tool(name, arguments)
    except Exception as exc:
        if isinstance(client, MockNseTools):
            raise
        log.warning("nse_mcp.call_failed_fallback_mock", tool=name, error=str(exc))
        return await MockNseTools().call_tool(name, arguments)
