"""Screener and scanner tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ai_agent.tools.registry import ToolContext, ToolResult, tool
from market_data.registry import get_provider
from strategy_engine.analytics import options as opt
from strategy_engine.analytics import pairs, screener

_FIELD_LIST = ", ".join(screener.FIELDS)


class Cond(BaseModel):
    field: str = Field(description=f"one of: {_FIELD_LIST}")
    op: Literal[">", "<", ">=", "<=", "==", "between"]
    value: float
    value2: float | None = None


class ScreenArgs(BaseModel):
    universe: Literal["NIFTY50", "NIFTY100", "BANKNIFTY", "FNO"] = "NIFTY100"
    conditions: list[Cond] = Field(min_length=1, max_length=10)
    logic: Literal["all", "any"] = "all"
    sort_by: str = "market_cap_cr"
    descending: bool = True
    limit: int = Field(default=15, ge=1, le=50)


@tool("run_screener", "Screen stocks on technical and fundamental fields (RSI, returns, distance from moving averages / 52-week "
      "high, volume ratio, ADX, P/E, P/B, ROE, ROCE, debt/equity, dividend yield, margins, growth, market cap).", ScreenArgs)
async def run_screener(ctx: ToolContext, a: ScreenArgs) -> ToolResult:
    bad = [c.field for c in a.conditions if c.field not in screener.FIELDS]
    if bad:
        return ToolResult({"error": f"unknown fields {bad}; valid: {_FIELD_LIST}"}, ok=False)
    sort_by = a.sort_by if a.sort_by in screener.FIELDS else a.conditions[0].field
    q = screener.ScreenQuery(universe=a.universe, logic=a.logic, conditions=[screener.ScreenCondition(**c.model_dump()) for c in a.conditions],
                             sort_by=sort_by, descending=a.descending, limit=a.limit)
    res = await screener.run_screen(get_provider(), q)
    cols = list(dict.fromkeys(["close", "change_pct", *(c.field for c in a.conditions), "market_cap_cr"]))
    rows = [{"symbol": r["symbol"], "name": r["name"], "sector": r["sector"], **{c: r.get(c) for c in cols}} for r in res["rows"]]
    data = {"universe": a.universe, "scanned": res["scanned"], "matched": res["matched"], "conditions": [c.model_dump() for c in a.conditions],
            "rows": rows}
    return ToolResult(data, {"type": "screener", **data, "columns": cols, "query": q.model_dump(),
                             "fields": {c: screener.FIELDS[c] for c in cols if c in screener.FIELDS}})


class ScanArgs(BaseModel):
    kind: Literal["arbitrage", "ratio_spreads", "pairs"]
    underlying: str = Field(default="NIFTY", description="for ratio_spreads")
    sector: str | None = Field(default=None, description="for pairs, e.g. 'Financial Services'")
    cost_bps: float = Field(default=6.0, ge=0, le=100, description="round-trip cost assumption for arbitrage")


@tool("run_scanner", "Run a market scanner: cash-futures/calendar/NSE-BSE/put-call-parity arbitrage, ratio-spread finder, or "
      "cointegrated pairs.", ScanArgs)
async def run_scanner(ctx: ToolContext, a: ScanArgs) -> ToolResult:
    p = get_provider()
    if a.kind == "pairs":
        rows = await pairs.scan_pairs(p, a.sector)
        cols = ["a", "b", "p_value", "correlation"]
        data = {"kind": "pairs", "sector": a.sector, "rows": rows[:10]}
        title, link = f"Cointegrated pairs{' · ' + a.sector if a.sector else ''}", "/analysis/pairs"
    elif a.kind == "ratio_spreads":
        res = await opt.ratio_spreads(p, a.underlying.upper(), None, max_debit=0.0, limit=10)
        rows = [{k: v for k, v in r.items() if k != "legs"} for r in res["candidates"]]
        cols = ["type", "buy_strike", "sell_strike", "ratio", "net_credit_per_lot", "breakeven", "short_delta"]
        data = {"kind": "ratio_spreads", "underlying": res["underlying"], "spot": res["spot"], "expiry": res["expiry"], "rows": rows}
        title, link = f"{res['underlying']} ratio spreads · {res['expiry']}", "/analysis/ratio-spreads"
    else:
        res = await opt.arbitrage_scan(p, a.cost_bps)
        rows = sorted(res["cash_futures"], key=lambda r: -r["net_annualised_pct"])[:10]
        cols = ["symbol", "spot", "future", "basis_pct", "annualised_pct", "net_annualised_pct", "days", "signal"]
        data = {"kind": "arbitrage", "cost_bps": a.cost_bps, "rows": rows,
                "pcp_violations": [r for r in res["put_call_parity"] if r["violation"]][:5],
                "nse_bse_actionable": [r for r in res["nse_bse"] if r["actionable"]][:5], "note": res["note"]}
        title, link = "Cash-and-carry arbitrage", "/analysis/arbitrage"
    return ToolResult(data, {"type": "table", "title": title, "columns": cols, "rows": data["rows"], "link": link})
