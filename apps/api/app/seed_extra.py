"""Seed demo strategies (+ backtests), templates and mock data. Idempotent."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from algo_common.logging import get_logger
from algo_common.timeutils import now_ist
from algo_db.models import Backtest, Strategy, StrategyVersion
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


async def run(demo_user_id: int, admin_user_id: int | None) -> None:
    await seed_templates()
    ids = await seed_demo_strategies(demo_user_id)
    await seed_demo_backtests(demo_user_id, ids)
