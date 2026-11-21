"""Seed demo strategies (+ backtests), templates and mock data. Idempotent."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select

from algo_common.logging import get_logger
from algo_common.timeutils import IST, now_ist
from algo_db.audit import audit
from algo_db.models import (
    Backtest,
    Deployment,
    DeploymentLog,
    Order,
    RiskLimit,
    Strategy,
    StrategyVersion,
    Trade,
)
from algo_db.session import session_scope
from strategy_engine.templates import TEMPLATES

log = get_logger("seed")

DEMO_STRATEGIES = ["EMA 9/21 crossover", "NIFTY short straddle with SL", "Bank Nifty iron condor",
                   "HDFCBANK / ICICIBANK pair trade"]
BACKTEST_WINDOWS = {"1d": 1100, "1h": 300, "15m": 120, "5m": 40}


async def seed_templates() -> None:
    async with session_scope() as db:
        existing = {s.name for s in (await db.execute(select(Strategy).where(Strategy.is_template.is_(True)))).scalars()}
        for t in TEMPLATES:
            if t["name"] in existing:
                continue
            s = Strategy(user_id=None, name=t["name"], description=t.get("description", ""), dsl=t, kind=t["kind"],
                         source="template", is_template=True, visibility="template", tags=t.get("tags", []))
            db.add(s)
            await db.flush()
            db.add(StrategyVersion(strategy_id=s.id, version=1, dsl=t, note="template"))


async def seed_demo_strategies(user_id: int) -> list[int]:
    ids: list[int] = []
    async with session_scope() as db:
        mine = {s.name: s for s in (await db.execute(select(Strategy).where(Strategy.user_id == user_id))).scalars()}
        for t in TEMPLATES:
            if t["name"] not in DEMO_STRATEGIES:
                continue
            if t["name"] in mine:
                ids.append(mine[t["name"]].id)
                continue
            s = Strategy(user_id=user_id, name=t["name"], description=t.get("description", ""), dsl=t, kind=t["kind"],
                         source="template", tags=t.get("tags", []))
            db.add(s)
            await db.flush()
            db.add(StrategyVersion(strategy_id=s.id, version=1, dsl=t, note="demo seed"))
            ids.append(s.id)
    return ids


async def seed_demo_backtests(user_id: int, strategy_ids: list[int]) -> None:
    from algo_jobs.backtests import run_backtest

    for sid in strategy_ids:
        async with session_scope() as db:
            done = (await db.execute(select(Backtest.id).where(Backtest.strategy_id == sid, Backtest.status == "completed"))).first()
            if done:
                continue
            s = await db.get(Strategy, sid)
            assert s is not None
            end = now_ist()
            start = end - timedelta(days=BACKTEST_WINDOWS.get(s.dsl.get("timeframe", "1d"), 120))
            bt = Backtest(user_id=user_id, strategy_id=sid, strategy_version=s.version, kind="backtest", dsl=s.dsl,
                          params={"start": start.isoformat(), "end": end.isoformat(), "initial_capital": 1_000_000,
                                  "broker": "zerodha", "slippage_bps": 5, "fill": "next_open", "mode": "event",
                                  "options": {"monte_carlo": True}})
            db.add(bt)
            await db.flush()
            bt_id = bt.id
        res = await run_backtest({"seed": True}, backtest_id=bt_id)
        log.info("seed.backtest", strategy_id=sid, status=res.get("status"))


# Paper-account history for the demo user so Portfolio, Live and the copilot's portfolio tools have something real
# to show on first launch: (symbol, quantity, trading days ago[, sold quantity, trading days ago]).
DEMO_TAG = "demo-seed"
DEMO_BUYS: list[tuple[str, int, int]] = [
    ("NSE:RELIANCE", 40, 160), ("NSE:HDFCBANK", 60, 140), ("NSE:INFY", 45, 120), ("NSE:TCS", 15, 100),
    ("NSE:ITC", 250, 80), ("NSE:LT", 12, 60), ("NSE:SBIN", 70, 40), ("NSE:BHARTIARTL", 25, 20),
    ("NSE:MARUTI", 4, 130), ("NSE:SUNPHARMA", 30, 110),
]
DEMO_SELLS: list[tuple[str, int, int]] = [("NSE:MARUTI", 4, 35), ("NSE:SUNPHARMA", 30, 25), ("NSE:ITC", 100, 10)]


def _close_on(symbol: str, days_ago: int) -> tuple[datetime, float]:
    """Close of the trading day `days_ago` sessions back (mock history), stamped at 15:20 IST."""
    from market_data.registry import get_mock
    from market_data.universe import BY_SYMBOL

    mock = get_mock()
    daily = mock._daily_for(BY_SYMBOL[symbol])
    today = now_ist().date()
    past = [i for i, d in enumerate(daily.dates) if d < today]
    i = past[-min(days_ago, len(past))]
    ts = datetime.combine(daily.dates[i], time(15, 20), tzinfo=IST).astimezone(UTC)
    return ts, round(float(daily.close[i]) / 0.05) * 0.05


async def seed_demo_portfolio(user_id: int) -> None:
    from broker_gateway.costs import CostModel
    from broker_gateway.router import algo_id_for

    costs = CostModel("zerodha")
    async with session_scope() as db:
        if (await db.execute(select(Order.id).where(Order.user_id == user_id, Order.tag == DEMO_TAG))).first():
            return
        fills = [(sym, "BUY", qty, ago) for sym, qty, ago in DEMO_BUYS] + [(sym, "SELL", qty, ago) for sym, qty, ago in DEMO_SELLS]
        fills.sort(key=lambda f: -f[3])  # oldest first
        for sym, side, qty, ago in fills:
            ts, px = _close_on(sym, ago)
            ch = costs.charges(on=ts.date(), side=side, price=px, quantity=qty, exchange="NSE", instrument="EQ", product="CNC")
            o = Order(user_id=user_id, broker="paper", mode="paper", client_order_id=uuid.uuid4().hex[:24], symbol=sym,
                      exchange="NSE", side=side, quantity=qty, filled_quantity=qty, average_price=px, order_type="MARKET",
                      product="CNC", status="complete", algo_id=algo_id_for(None), tag=DEMO_TAG,
                      risk_decision={"approved": True, "checks": ["seed"]}, created_at=ts, updated_at=ts)
            db.add(o)
            await db.flush()
            db.add(Trade(order_id=o.id, user_id=user_id, broker="paper", mode="paper", symbol=sym, exchange="NSE", side=side,
                         quantity=qty, price=px, charges=round(ch.total, 2), product="CNC", ts=ts))
        # one running and one paused paper deployment
        strategies = {s.name: s for s in (await db.execute(select(Strategy).where(Strategy.user_id == user_id))).scalars()}
        plan = [("EMA 9/21 crossover", "running", 300_000, 3), ("NIFTY short straddle with SL", "paused", 400_000, 6)]
        for name, status, capital, days in plan:
            st = strategies.get(name)
            if st is None:
                continue
            started = datetime.now(UTC) - timedelta(days=days)
            limits = {"capital": capital, "max_loss_per_day": 15_000, "max_orders_per_min": 20}
            d = Deployment(user_id=user_id, strategy_id=st.id, strategy_version=st.version, dsl=st.dsl, broker="paper",
                           mode="paper", status=status, multiplier=1, risk_limits=limits, notify_channels=["in_app"],
                           algo_id=algo_id_for(st.id), started_at=started)
            db.add(d)
            await db.flush()
            rl = (await db.execute(select(RiskLimit).where(RiskLimit.user_id == user_id, RiskLimit.strategy_id == st.id))).scalar_one_or_none()
            if rl is None:
                db.add(RiskLimit(user_id=user_id, strategy_id=st.id, max_loss_per_day=15_000, max_orders_per_min=20))
            db.add(DeploymentLog(deployment_id=d.id, ts=started, level="info",
                                 message=f"Deployment started in paper mode (capital ₹{capital:,})", data={"seed": True}))
            if status == "paused":
                db.add(DeploymentLog(deployment_id=d.id, ts=started + timedelta(days=2), level="info",
                                     message="Paused by user", data={"seed": True}))
            await audit(db, "deployment.start", user_id=user_id, entity_type="deployment", entity_id=d.id,
                        payload={"strategy_id": st.id, "mode": "paper", "seed": True, "algo_id": d.algo_id})
    log.info("seed.demo_portfolio", fills=len(DEMO_BUYS) + len(DEMO_SELLS))


async def run(demo_user_id: int, admin_user_id: int | None) -> None:
    await seed_templates()
    ids = await seed_demo_strategies(demo_user_id)
    await seed_demo_backtests(demo_user_id, ids)
    await seed_demo_portfolio(demo_user_id)
