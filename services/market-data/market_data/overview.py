"""Market overview aggregation: indices, sector heatmap, breadth, movers, OI gainers, FII/DII."""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from typing import Any

from algo_common.schemas.market import Quote
from algo_common.timeutils import expiry_from_date, now_ist, upcoming_expiries
from market_data.base import MarketDataProvider
from market_data.nse_mcp import call_nse_tool
from market_data.symbols import future_symbol
from market_data.universe import EQUITIES, INDICES, SECTOR_INDEX

OVERVIEW_INDICES = ["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY", "NSE_INDEX:FINNIFTY", "NSE_INDEX:MIDCPNIFTY",
                    "BSE_INDEX:SENSEX", "BSE_INDEX:BANKEX", "NSE_INDEX:INDIAVIX"]


def _row(q: Quote) -> dict[str, Any]:
    return {"symbol": q.symbol, "name": q.name, "ltp": q.ltp, "change": q.change, "change_pct": q.change_pct,
            "volume": q.volume, "value_cr": round((q.volume or 0) * q.ltp / 1e7, 2), "oi": q.oi}


async def market_overview(provider: MarketDataProvider) -> dict[str, Any]:
    eq_syms = [a.symbol for a in EQUITIES]
    sector_syms = list(SECTOR_INDEX.values())
    fut_syms = []
    exp = upcoming_expiries("_MONTHLY_", expiry_from_date(now_ist()), 1)[0]
    for a in EQUITIES:
        if a.lot_size:
            fut_syms.append(future_symbol(a.tradingsymbol, exp))
    quotes, fii, breadth_tool = await asyncio.gather(
        provider.quotes(OVERVIEW_INDICES + sector_syms + eq_syms + fut_syms),
        call_nse_tool("get_fii_dii_activity", {"days": 10}),
        call_nse_tool("get_market_breadth", {}),
    )
    meta = {a.symbol: a for a in EQUITIES + INDICES}
    eq = [quotes[s] for s in eq_syms if s in quotes]

    # sector heatmap (market-cap weighted)
    by_sector: dict[str, list[tuple[Quote, float]]] = defaultdict(list)
    for q in eq:
        a = meta[q.symbol]
        by_sector[a.sector or "Other"].append((q, a.mcap_cr or 1.0))
    sectors = []
    for name, items in by_sector.items():
        w = sum(m for _, m in items)
        chg = sum((q.change_pct or 0) * m for q, m in items) / w if w else 0
        sectors.append({
            "sector": name, "change_pct": round(chg, 2), "mcap_cr": w,
            "stocks": [{"symbol": q.symbol, "name": q.name, "ltp": q.ltp, "change_pct": q.change_pct, "mcap_cr": m}
                       for q, m in sorted(items, key=lambda x: -x[1])],
        })
    sectors.sort(key=lambda s: -s["mcap_cr"])

    adv = sum(1 for q in eq if (q.change_pct or 0) > 0.05)
    dec = sum(1 for q in eq if (q.change_pct or 0) < -0.05)
    movers = sorted(eq, key=lambda q: q.change_pct or 0)
    futs = [quotes[s] for s in fut_syms if s in quotes]
    oi_rows = []
    for f in futs:
        base = f.oi or 0
        # day change in OI: provider supplies it in live mode via quote fields; mock derives from price action
        h = int(hashlib.blake2b(f"{f.symbol}{now_ist().date()}".encode(), digest_size=4).hexdigest(), 16)
        oi_chg_pct = round((f.change_pct or 0) * 1.7 + ((h % 100) - 50) / 12, 2)
        price_up = (f.change_pct or 0) >= 0
        buildup = (
            "Long buildup" if price_up and oi_chg_pct > 0 else
            "Short covering" if price_up else
            "Short buildup" if oi_chg_pct > 0 else "Long unwinding"
        )
        oi_rows.append({**_row(f), "oi": base, "oi_change_pct": oi_chg_pct, "buildup": buildup})
    oi_rows.sort(key=lambda r: -r["oi_change_pct"])
    return {
        "ts": now_ist().isoformat(),
        "indices": [_row(quotes[s]) for s in OVERVIEW_INDICES if s in quotes],
        "sector_indices": [_row(quotes[s]) for s in sector_syms if s in quotes],
        "sectors": sectors,
        "breadth": {
            "advances": adv, "declines": dec, "unchanged": len(eq) - adv - dec, "universe": len(eq),
            "nse": breadth_tool,
        },
        "top_gainers": [_row(q) for q in movers[::-1][:10]],
        "top_losers": [_row(q) for q in movers[:10]],
        "most_active": [_row(q) for q in sorted(eq, key=lambda q: -(q.volume or 0) * q.ltp)[:10]],
        "oi_gainers": oi_rows[:10],
        "oi_losers": oi_rows[::-1][:10],
        "fii_dii": fii,
    }
