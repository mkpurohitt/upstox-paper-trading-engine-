from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from algo_common.schemas.market import Quote
from algo_common.timeutils import IST
from algo_db.models import Deployment, Notification, Order, Strategy
from market_data.mock import MockProvider
from strategy_engine.live.bars import Bar, BarBuilder
from strategy_engine.live.runner import StrategyRunner, ledger_pnl


class Prices(MockProvider):
    def __init__(self, p: dict[str, float]) -> None:
        super().__init__()
        self.p = p

    async def quotes(self, symbols):  # type: ignore[override]
        now = datetime.now(UTC)
        return {s: Quote(symbol=s, ts=now, ltp=self.p[s]) for s in symbols if s in self.p}


DSL = {
    "name": "always long", "kind": "equity", "universe": {"symbols": ["NSE:SBIN"]}, "timeframe": "15m", "product": "MIS",
    "indicators": [], "entry": {"long": {"kind": "all", "conditions": [
        {"kind": "compare", "left": {"type": "price", "field": "close"}, "op": ">", "right": {"type": "const", "value": 0}}]}},
    "exit": {"stop_loss": {"type": "percent", "value": 1.0}}, "sizing": {"mode": "fixed_qty", "value": 10},
    "schedule": {"entry_after": None, "entry_before": None, "square_off": None},
}


def test_bar_builder_buckets():
    b = BarBuilder("15m")
    t0 = datetime(2026, 11, 16, 9, 16, tzinfo=IST)
    assert b.on_tick(t0, 100, 1000) is None
    assert b.on_tick(t0 + timedelta(minutes=5), 102, 1500) is None
    done = b.on_tick(t0 + timedelta(minutes=15), 101, 1600)
    assert done is not None and done.ts.strftime("%H:%M") == "09:15"
    assert (done.open, done.high, done.close, done.volume) == (100, 102, 102, 500)
    assert b.flush_if_due(t0 + timedelta(minutes=40)) is not None


async def _deployment(db, user, mode: str) -> int:
    s = Strategy(user_id=user.id, name="t", dsl=DSL, kind="equity")
    db.add(s)
    await db.flush()
    d = Deployment(user_id=user.id, strategy_id=s.id, dsl=DSL, mode=mode, status="running", algo_id="ALGO-PENDING-S1",
                   risk_limits={"capital": 1_000_000})
    db.add(d)
    await db.commit()
    return d.id


async def test_runner_paper_entry_and_stop(db, user):
    prov = Prices({"NSE:SBIN": 800.0})
    dep = await _deployment(db, user, "paper")
    r = StrategyRunner(dep, prov)
    await r.load()
    bar_ts = datetime(2026, 11, 16, 10, 0, tzinfo=IST)
    await r.on_bar("NSE:SBIN", Bar(bar_ts, 799, 801, 798, 800, 1000))
    pos = r.state["positions"]["NSE:SBIN"]
    assert pos["qty"] == 10 and pos["stop"] == pytest.approx(pos["entry"] * 0.99)
    prov.p["NSE:SBIN"] = 780.0
    await r.on_tick("NSE:SBIN", 780.0, bar_ts + timedelta(minutes=20))
    assert "NSE:SBIN" not in r.state["positions"]
    orders = (await db.execute(select(Order).where(Order.deployment_id == dep).order_by(Order.id))).scalars().all()
    assert [o.side for o in orders] == ["BUY", "SELL"] and all(o.status == "complete" for o in orders)
    assert all(o.algo_id == "ALGO-PENDING-S1" and o.strategy_id for o in orders)
    from algo_db.models import Trade

    trades = (await db.execute(select(Trade).where(Trade.deployment_id == dep))).scalars().all()
    realised, unreal, n_open = ledger_pnl(trades, {})
    assert n_open == 0 and realised < 0 and unreal == 0


async def test_runner_notify_mode(db, user):
    prov = Prices({"NSE:SBIN": 800.0})
    dep = await _deployment(db, user, "notify")
    r = StrategyRunner(dep, prov)
    await r.load()
    await r.on_bar("NSE:SBIN", Bar(datetime(2026, 11, 16, 10, 0, tzinfo=IST), 799, 801, 798, 800, 1000))
    assert (await db.execute(select(Order))).scalars().all() == []
    notes = (await db.execute(select(Notification))).scalars().all()
    assert notes and "BUY 10 NSE:SBIN" in notes[0].title
