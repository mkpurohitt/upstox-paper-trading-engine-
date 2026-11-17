"""Fundamentals. Live mode should plug a fundamentals vendor (Upstox does not
provide financials); mock mode generates deterministic, sector-consistent data.
Every payload carries `source` so the UI can label synthetic numbers."""

from __future__ import annotations

import hashlib
from typing import Any

from market_data.nse_mcp import call_nse_tool
from market_data.universe import BY_SYMBOL, EQUITIES

SECTOR_PROFILE = {
    "Financial Services": {"margin": 0.28, "roe": 0.15, "de": 6.0, "pe": 18, "growth": 0.14},
    "Information Technology": {"margin": 0.22, "roe": 0.28, "de": 0.1, "pe": 26, "growth": 0.09},
    "FMCG": {"margin": 0.2, "roe": 0.3, "de": 0.2, "pe": 45, "growth": 0.08},
    "Healthcare": {"margin": 0.2, "roe": 0.17, "de": 0.3, "pe": 32, "growth": 0.11},
    "Automobile": {"margin": 0.12, "roe": 0.18, "de": 0.4, "pe": 24, "growth": 0.12},
    "Metals & Mining": {"margin": 0.13, "roe": 0.14, "de": 0.8, "pe": 11, "growth": 0.07},
    "Energy": {"margin": 0.12, "roe": 0.1, "de": 0.5, "pe": 22, "growth": 0.08},
}


def _r(*parts: object) -> float:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF  # noqa: S324


def fundamentals_for(symbol: str, price: float | None = None) -> dict[str, Any]:
    a = BY_SYMBOL.get(symbol)
    if a is None or a.kind != "equity":
        raise KeyError(f"no fundamentals for {symbol}")
    prof = SECTOR_PROFILE.get(a.sector or "", {"margin": 0.15, "roe": 0.16, "de": 0.6, "pe": 25, "growth": 0.1})
    price = price or a.price
    mcap = a.mcap_cr or 50_000
    pe = prof["pe"] * (0.7 + 0.6 * _r("pe", symbol))
    pat_ttm = mcap / pe
    margin = prof["margin"] * (0.75 + 0.5 * _r("m", symbol))
    revenue_ttm = pat_ttm / margin
    growth = prof["growth"] * (0.5 + _r("g", symbol))
    years = []
    for i, fy in enumerate(range(2022, 2027)):
        k = (1 + growth) ** (i - 4) * (0.97 + 0.06 * _r("y", symbol, fy))
        rev = revenue_ttm * k
        pat = rev * margin * (0.9 + 0.2 * _r("p", symbol, fy))
        years.append({"fy": f"FY{fy % 100}", "revenue_cr": round(rev, 0), "ebitda_cr": round(rev * margin * 1.45, 0),
                      "pat_cr": round(pat, 0), "eps": round(pat * 1e7 / (mcap * 1e7 / price), 2)})
    equity = pat_ttm / (prof["roe"] * (0.8 + 0.4 * _r("roe", symbol)))
    ratios = {
        "pe": round(pe, 1), "pb": round(mcap / equity, 2), "roe_pct": round(pat_ttm / equity * 100, 1),
        "roce_pct": round(pat_ttm / equity * 100 * (1.1 + 0.2 * _r("roce", symbol)), 1),
        "debt_to_equity": round(prof["de"] * (0.5 + _r("de", symbol)), 2), "dividend_yield_pct": round(0.2 + 2.8 * _r("dy", symbol), 2),
        "net_margin_pct": round(margin * 100, 1), "revenue_growth_3y_pct": round(growth * 100, 1),
        "eps_ttm": years[-1]["eps"], "book_value": round(equity * 1e7 / (mcap * 1e7 / price), 2),
        "market_cap_cr": mcap, "face_value": 1 if _r("fv", symbol) > 0.5 else 10,
    }
    quarters = []
    for q in range(8):
        rev = revenue_ttm / 4 * (1 + growth) ** ((q - 7) / 4) * (0.95 + 0.1 * _r("q", symbol, q))
        quarters.append({"quarter": f"Q{(q % 4) + 1}FY{25 + q // 4}", "revenue_cr": round(rev, 0),
                         "pat_cr": round(rev * margin * (0.85 + 0.3 * _r("qp", symbol, q)), 0)})
    return {"symbol": symbol, "name": a.name, "sector": a.sector, "industry": a.industry, "price": price, "ratios": ratios,
            "annual": years, "quarterly": quarters, "source": "mock"}


async def fundamental_dashboard(symbol: str, price: float | None = None) -> dict[str, Any]:
    base = fundamentals_for(symbol, price)
    a = BY_SYMBOL[symbol]
    peers = []
    for p in EQUITIES:
        if p.sector == a.sector:
            f = fundamentals_for(p.symbol)
            peers.append({"symbol": p.symbol, "name": p.name, **{k: f["ratios"][k] for k in
                          ("market_cap_cr", "pe", "pb", "roe_pct", "debt_to_equity", "net_margin_pct", "dividend_yield_pct")}})
    peers.sort(key=lambda x: -x["market_cap_cr"])
    sh = await call_nse_tool("get_shareholding_pattern", {"symbol": symbol})
    actions = await call_nse_tool("get_corporate_actions", {"symbol": symbol})
    return {**base, "peers": peers[:10], "shareholding": sh, "corporate_actions": actions.get("rows", [])}
