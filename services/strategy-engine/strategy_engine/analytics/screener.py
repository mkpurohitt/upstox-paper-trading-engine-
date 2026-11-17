"""Stock screener over technical + fundamental fields."""

from __future__ import annotations

import asyncio
import math
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from market_data.base import MarketDataProvider
from market_data.universe import BY_SYMBOL, UNIVERSES
from strategy_engine import indicators as ind
from strategy_engine.analytics.fundamentals import fundamentals_for
from strategy_engine.analytics.technical import frame_for

FIELDS: dict[str, dict[str, str]] = {
    # technical
    "close": {"label": "Last price", "group": "technical", "unit": "₹"},
    "change_pct": {"label": "Day change %", "group": "technical", "unit": "%"},
    "ret_1m_pct": {"label": "1M return %", "group": "technical", "unit": "%"},
    "ret_3m_pct": {"label": "3M return %", "group": "technical", "unit": "%"},
    "ret_1y_pct": {"label": "1Y return %", "group": "technical", "unit": "%"},
    "rsi14": {"label": "RSI(14)", "group": "technical", "unit": ""},
    "dist_sma20_pct": {"label": "% from SMA20", "group": "technical", "unit": "%"},
    "dist_sma50_pct": {"label": "% from SMA50", "group": "technical", "unit": "%"},
    "dist_sma200_pct": {"label": "% from SMA200", "group": "technical", "unit": "%"},
    "dist_52w_high_pct": {"label": "% below 52W high", "group": "technical", "unit": "%"},
    "dist_52w_low_pct": {"label": "% above 52W low", "group": "technical", "unit": "%"},
    "volume_ratio": {"label": "Volume / 20D avg", "group": "technical", "unit": "x"},
    "atr_pct": {"label": "ATR(14) % of price", "group": "technical", "unit": "%"},
    "adx14": {"label": "ADX(14)", "group": "technical", "unit": ""},
    "supertrend_up": {"label": "Supertrend up (1/0)", "group": "technical", "unit": ""},
    # fundamental
    "market_cap_cr": {"label": "Market cap (₹ Cr)", "group": "fundamental", "unit": "₹Cr"},
    "pe": {"label": "P/E", "group": "fundamental", "unit": ""},
    "pb": {"label": "P/B", "group": "fundamental", "unit": ""},
    "roe_pct": {"label": "ROE %", "group": "fundamental", "unit": "%"},
    "roce_pct": {"label": "ROCE %", "group": "fundamental", "unit": "%"},
    "debt_to_equity": {"label": "Debt / equity", "group": "fundamental", "unit": ""},
    "dividend_yield_pct": {"label": "Dividend yield %", "group": "fundamental", "unit": "%"},
    "net_margin_pct": {"label": "Net margin %", "group": "fundamental", "unit": "%"},
    "revenue_growth_3y_pct": {"label": "Revenue CAGR 3Y %", "group": "fundamental", "unit": "%"},
}


class ScreenCondition(BaseModel):
    field: str
    op: Literal[">", "<", ">=", "<=", "==", "between"]
    value: float
    value2: float | None = None


class ScreenQuery(BaseModel):
    universe: str = "NIFTY100"
    logic: Literal["all", "any"] = "all"
    conditions: list[ScreenCondition] = Field(default_factory=list, max_length=20)
    sectors: list[str] = Field(default_factory=list)
    sort_by: str = "market_cap_cr"
    descending: bool = True
    limit: int = Field(default=50, ge=1, le=200)


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else float("nan")


async def features(provider: MarketDataProvider, symbol: str) -> dict[str, Any] | None:
    df = await frame_for(provider, symbol, "1d", 420)
    if len(df) < 60:
        return None
    c = df["close"]
    last = float(c.iloc[-1])
    sma = {n: float(c.rolling(n).mean().iloc[-1]) if len(c) >= n else float("nan") for n in (20, 50, 200)}
    year = c.tail(252)
    a = BY_SYMBOL.get(symbol)
    f = {
        "symbol": symbol, "name": a.name if a else symbol, "sector": a.sector if a else None, "close": round(last, 2),
        "change_pct": round(_pct(last, float(c.iloc[-2])), 2), "ret_1m_pct": round(_pct(last, float(c.iloc[-22])), 2),
        "ret_3m_pct": round(_pct(last, float(c.iloc[-64])), 2), "ret_1y_pct": round(_pct(last, float(c.iloc[0])), 2),
        "rsi14": round(float(ind.rsi(df).iloc[-1]), 1),
        "dist_sma20_pct": round(_pct(last, sma[20]), 2), "dist_sma50_pct": round(_pct(last, sma[50]), 2),
        "dist_sma200_pct": round(_pct(last, sma[200]), 2),
        "dist_52w_high_pct": round(-_pct(last, float(year.max())), 2), "dist_52w_low_pct": round(_pct(last, float(year.min())), 2),
        "volume_ratio": round(float(df["volume"].iloc[-1] / max(1.0, df["volume"].tail(20).mean())), 2),
        "atr_pct": round(float(ind.atr(df).iloc[-1]) / last * 100, 2), "adx14": round(float(ind.adx(df)["adx"].iloc[-1]), 1),
        "supertrend_up": 1 if ind.supertrend(df)["direction"].iloc[-1] == 1 else 0,
    }
    try:
        f.update(fundamentals_for(symbol, last)["ratios"])
    except KeyError:
        pass
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in f.items()}


def matches(row: dict[str, Any], q: ScreenQuery) -> bool:
    if q.sectors and row.get("sector") not in q.sectors:
        return False
    results = []
    for c in q.conditions:
        v = row.get(c.field)
        if v is None:
            results.append(False)
            continue
        ok = {">": v > c.value, "<": v < c.value, ">=": v >= c.value, "<=": v <= c.value, "==": math.isclose(v, c.value),
              "between": c.value <= v <= (c.value2 if c.value2 is not None else c.value)}[c.op]
        results.append(bool(ok))
    if not results:
        return True
    return all(results) if q.logic == "all" else any(results)


async def run_screen(provider: MarketDataProvider, q: ScreenQuery) -> dict[str, Any]:
    syms = UNIVERSES.get(q.universe, UNIVERSES["NIFTY100"])
    rows = [r for r in await asyncio.gather(*(features(provider, s) for s in syms)) if r]
    hits = [r for r in rows if matches(r, q)]
    hits.sort(key=lambda r: (r.get(q.sort_by) is None, r.get(q.sort_by) or 0), reverse=False)
    if q.descending:
        hits = [r for r in hits if r.get(q.sort_by) is not None][::-1] + [r for r in hits if r.get(q.sort_by) is None]
    return {"universe": q.universe, "scanned": len(rows), "matched": len(hits), "rows": hits[: q.limit],
            "fields": FIELDS, "summary": {"median_rsi": float(np.median([r["rsi14"] for r in rows])) if rows else None}}
