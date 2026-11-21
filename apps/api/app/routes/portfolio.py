"""Consolidated portfolio across the paper account and connected brokers: holdings, positions, allocation,
performance (XIRR), concentration, strategy overlap and upcoming dividends."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from algo_common.logging import get_logger
from algo_common.schemas.market import Interval
from algo_common.settings import get_settings
from algo_common.timeutils import IST, is_trading_day, now_ist, utcnow
from algo_db.models import BrokerConnection, Deployment, Strategy, Trade, User
from app.core.deps import DB, CurrentUser
from broker_gateway.connections import live_adapter
from broker_gateway.paper import PaperBroker
from market_data.nse_mcp import call_nse_tool
from market_data.registry import get_provider
from market_data.universe import BY_SYMBOL
from strategy_engine.analytics.portfolio import analyze_positions, mtm_equity_by_day, xirr

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])
log = get_logger("api.portfolio")


def _pos_dict(p: Any, account: str) -> dict[str, Any]:
    return {"account": account, "symbol": p.symbol, "product": getattr(p.product, "value", p.product), "quantity": p.quantity,
            "average_price": round(p.average_price, 2), "last_price": round(p.last_price, 2),
            "unrealised_pnl": round(p.unrealised_pnl, 2), "realised_pnl": round(p.realised_pnl, 2),
            "value": round(p.quantity * (p.last_price or p.average_price), 2)}


def _hold_dict(h: Any, account: str) -> dict[str, Any]:
    a = BY_SYMBOL.get(h.symbol)
    invested = h.quantity * h.average_price
    value = h.quantity * (h.last_price or h.average_price)
    return {"account": account, "symbol": h.symbol, "name": a.name if a else h.symbol, "sector": a.sector if a else None,
            "quantity": h.quantity, "average_price": round(h.average_price, 2), "last_price": round(h.last_price, 2),
            "invested": round(invested, 2), "value": round(value, 2), "pnl": round(value - invested, 2),
            "pnl_pct": round((value / invested - 1) * 100, 2) if invested else None}


@router.get("/summary")
async def summary(user: CurrentUser, db: DB) -> dict[str, Any]:
    accounts: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    pb = PaperBroker(user.id, db, get_provider())
    paper_pos = await pb.get_positions()
    paper_funds = await pb.get_funds()
    day = await pb.day_pnl()
    accounts.append({"account": "paper", "label": "Paper trading", "broker": "paper", "status": "connected",
                     "funds": {"available": round(paper_funds.available, 2), "used": round(paper_funds.used, 2), "total": round(paper_funds.total, 2)},
                     "day_pnl": day, "error": None})
    for p in paper_pos:
        if p.quantity:
            (holdings.append(_hold_dict(p, "paper")) if p.product.value == "CNC" and p.quantity > 0 else positions.append(_pos_dict(p, "paper")))
    conns = (await db.execute(select(BrokerConnection).where(BrokerConnection.user_id == user.id))).scalars().all()
    for c in conns:
        label = f"{c.broker} · {c.client_id}" if c.client_id else c.broker
        acct = {"account": f"live:{c.id}", "label": label, "broker": c.broker, "status": c.status, "funds": None, "day_pnl": None, "error": None}
        if c.status != "connected":
            acct["error"] = c.status_message or "not connected"
            accounts.append(acct)
            continue
        try:
            adapter, _ = await live_adapter(db, user.id, c.id)
            f = await adapter.get_funds()
            acct["funds"] = {"available": f.available, "used": f.used, "total": f.total}
            holdings += [_hold_dict(h, acct["account"]) for h in await adapter.get_holdings()]
            positions += [_pos_dict(p, acct["account"]) for p in await adapter.get_positions() if p.quantity]
        except Exception as exc:  # one broker failing must not break the page
            acct["error"] = str(getattr(exc, "detail", exc))[:200]
        accounts.append(acct)
    rows_for_risk = [{"symbol": h["symbol"], "quantity": h["quantity"], "average_price": h["average_price"], "last_price": h["last_price"],
                      "unrealised_pnl": h["pnl"]} for h in holdings] + positions
    analysis = analyze_positions(rows_for_risk)
    invested = sum(h["invested"] for h in holdings)
    value = sum(h["value"] for h in holdings)
    totals = {
        "holdings_value": round(value, 2), "holdings_invested": round(invested, 2), "holdings_pnl": round(value - invested, 2),
        "holdings_pnl_pct": round((value / invested - 1) * 100, 2) if invested else None,
        "positions_unrealised": round(sum(p["unrealised_pnl"] for p in positions), 2),
        "cash": round(sum((a["funds"] or {}).get("available", 0) for a in accounts), 2),
        "net_worth": round(sum((a["funds"] or {}).get("total", 0) for a in accounts), 2),
        "day_pnl": round(sum(a["day_pnl"] or 0 for a in accounts), 2),
    }
    return {"as_of": now_ist().isoformat(), "accounts": accounts, "holdings": holdings, "positions": positions, "totals": totals,
            "analysis": analysis}


@router.get("/performance")
async def performance(user: CurrentUser, db: DB, days: int = Query(180, ge=7, le=3650)) -> dict[str, Any]:
    """Paper-account performance marked to market daily: equity curve, daily P&L, winning days and XIRR."""
    rows = (await db.execute(select(Trade).where(Trade.user_id == user.id, Trade.mode == "paper").order_by(Trade.ts))).scalars().all()
    capital = get_settings().paper_starting_capital
    u = await db.get(User, user.id)
    today = now_ist().date()
    start = (rows[0].ts.astimezone(IST) if rows else (u.created_at if u else utcnow()).astimezone(IST)).date()
    pb = PaperBroker(user.id, db, get_provider())
    funds = await pb.get_funds()
    fills = [{"date": t.ts.astimezone(IST).date(), "ts": t.ts, "symbol": t.symbol, "product": t.product, "side": t.side,
              "quantity": t.quantity, "price": t.price, "charges": t.charges} for t in rows]
    window_start = max(start, date.fromordinal(today.toordinal() - days))
    provider = get_provider()
    closes: dict[str, dict[date, float]] = {}
    for sym in sorted({f["symbol"] for f in fills}):
        try:
            candles = await provider.candles(sym, Interval.D1, datetime.combine(start, time(0), tzinfo=IST),
                                             datetime.combine(today, time(23, 59), tzinfo=IST))
        except Exception as exc:  # a symbol without history is valued at its last fill price
            log.warning("portfolio.history_failed", symbol=sym, error=str(exc))
            continue
        closes[sym] = {c.ts.astimezone(IST).date(): c.close for c in candles}
    extra = {start} | ({today} if is_trading_day(today) else set()) if rows else set()
    session_days = sorted({d for series in closes.values() for d in series if start <= d <= today} | extra)
    open_syms = [p.symbol for p in await pb.get_positions(include_closed=False)]
    live = {s: q.ltp for s, q in (await provider.quotes(open_syms)).items()} if open_syms else {}
    curve = mtm_equity_by_day(fills, closes, capital, session_days, live) if rows else []
    recent = [p for p in curve if date.fromisoformat(p["date"]) >= window_start]
    active = [p for p in curve if p["pnl"] != 0]
    flows: list[tuple[date, float]] = [(start, -capital), (today, funds.total)]
    rate = xirr(flows) if (today - start).days >= 7 else None
    peak, max_dd = capital, 0.0
    for p in curve:
        peak = max(peak, p["equity"])
        max_dd = min(max_dd, p["equity"] / peak - 1)
    return {
        "starting_capital": capital, "current_value": round(funds.total, 2),
        "total_return_pct": round((funds.total / capital - 1) * 100, 2), "xirr_pct": rate,
        "max_drawdown_pct": round(max_dd * 100, 2), "since": start.isoformat(),
        "trading_days": len(active), "winning_days": sum(1 for p in active if p["pnl"] > 0),
        "best_day": max(active, key=lambda p: p["pnl"], default=None), "worst_day": min(active, key=lambda p: p["pnl"], default=None),
        "daily": recent, "equity": [{"date": p["date"], "equity": p["equity"]} for p in recent],
        "note": "Marked to market at each day's close (today at live prices), net of charges. XIRR treats the paper "
                "starting capital as the only contribution.",
    }


@router.get("/overlap")
async def overlap(user: CurrentUser, db: DB) -> dict[str, Any]:
    """Instruments shared by more than one active deployment (hidden concentration across strategies)."""
    rows = (await db.execute(
        select(Deployment, Strategy.name).join(Strategy, Strategy.id == Deployment.strategy_id)
        .where(Deployment.user_id == user.id, Deployment.status.in_(("running", "paused")))
    )).all()
    by_inst: dict[str, list[dict[str, Any]]] = defaultdict(list)
    deps = [d for d, _ in rows]
    names = {d.id: name for d, name in rows}
    for d in deps:
        dsl = d.dsl or {}
        uni = dsl.get("universe") or {}
        insts = set(uni.get("symbols") or [])
        if uni.get("underlying"):
            insts.add(f"{uni['underlying']} options")
        pair = dsl.get("pair") or {}
        insts |= {s for s in (pair.get("leg_a"), pair.get("leg_b")) if s}
        for i in insts:
            by_inst[i].append({"deployment_id": d.id, "name": names.get(d.id) or f"Deployment #{d.id}", "mode": d.mode,
                               "status": d.status})
    shared = [{"instrument": k, "deployments": v} for k, v in sorted(by_inst.items(), key=lambda kv: -len(kv[1])) if len(v) > 1]
    return {"active_deployments": len(deps), "instruments": len(by_inst), "shared": shared}


_DIV = re.compile(r"dividend\D*?(?:rs\.?|₹|inr)\s*([\d.]+)", re.I)


@router.get("/dividends")
async def dividends(user: CurrentUser, db: DB) -> dict[str, Any]:
    """Upcoming corporate actions for held stocks, with estimated dividend cash flow."""
    s = await summary(user, db)
    held: dict[str, int] = defaultdict(int)
    for h in s["holdings"]:
        held[h["symbol"]] += h["quantity"]
    for p in s["positions"]:
        if p["quantity"] > 0 and p["symbol"].startswith("NSE:"):
            held[p["symbol"]] += p["quantity"]
    out = []
    for sym, qty in held.items():
        try:
            r = await call_nse_tool("get_corporate_actions", {"symbol": sym.split(":")[-1]})
        except Exception as exc:
            log.warning("portfolio.corporate_actions_failed", symbol=sym, error=str(exc))
            continue
        for a in (r.get("rows", []) if isinstance(r, dict) else []):
            m = _DIV.search(str(a.get("purpose", "")))
            dps = float(m.group(1)) if m else None
            out.append({"symbol": sym, "quantity": qty, "purpose": a.get("purpose"), "ex_date": a.get("ex_date"),
                        "record_date": a.get("record_date"), "dividend_per_share": dps,
                        "estimated_amount": round(dps * qty, 2) if dps else None})
    out.sort(key=lambda x: x["ex_date"] or "")
    return {"items": out, "estimated_total": round(sum(x["estimated_amount"] or 0 for x in out), 2),
            "as_of": datetime.now().date().isoformat()}
