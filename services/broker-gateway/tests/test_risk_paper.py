from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from algo_common.errors import RiskRejectedError
from algo_common.schemas.market import Quote
from algo_db.audit import verify_chain
from algo_db.models import Deployment, Notification, RiskLimit, Strategy, SystemFlag, Trade
from broker_gateway.killswitch import engage_user, release_user
from broker_gateway.models import OrderRequest, OrderType, Product, Side
from broker_gateway.paper import PaperBroker, PaperMatcher
from broker_gateway.risk import GLOBAL_KILL_FLAG
from broker_gateway.router import OrderRouter
from market_data.mock import MockProvider


class FixedPrices(MockProvider):
    """Mock provider with controllable LTPs for deterministic fills."""

    def __init__(self, prices: dict[str, float]) -> None:
        super().__init__()
        self.prices = prices

    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        now = datetime.now(UTC)
        return {s: Quote(symbol=s, ts=now, ltp=self.prices[s]) for s in symbols if s in self.prices}


def buy(sym: str = "NSE:SBIN", qty: int = 10, **kw: object) -> OrderRequest:
    return OrderRequest(symbol=sym, side=Side.BUY, quantity=qty, product=Product.MIS, **kw)  # type: ignore[arg-type]


def sell(sym: str = "NSE:SBIN", qty: int = 10, **kw: object) -> OrderRequest:
    return OrderRequest(symbol=sym, side=Side.SELL, quantity=qty, product=Product.MIS, **kw)  # type: ignore[arg-type]


async def test_paper_market_round_trip_and_ledger(db, user):
    prov = FixedPrices({"NSE:SBIN": 800.0})
    router = OrderRouter(prov)
    rows = await router.place(db, user, buy(qty=100))
    assert rows[0].status == "complete" and rows[0].average_price == pytest.approx(800.4, abs=0.05)  # 5 bps slippage
    assert rows[0].algo_id.endswith("MANUAL")
    prov.prices["NSE:SBIN"] = 810.0
    pb = PaperBroker(user.id, db, prov)
    pos = (await pb.get_positions())[0]
    assert pos.quantity == 100 and pos.unrealised_pnl == pytest.approx((810 - 800.4) * 100, abs=1)
    await router.place(db, user, sell(qty=100))
    pos = (await pb.get_positions())[0]
    trades = (await db.execute(select(Trade))).scalars().all()
    charges = sum(t.charges for t in trades)
    assert pos.quantity == 0 and charges > 0
    assert pos.realised_pnl == pytest.approx((809.6 - 800.4) * 100 - charges, abs=1)
    assert await pb.day_pnl() == pytest.approx(pos.realised_pnl, abs=1)
    funds = await pb.get_funds()
    assert funds.total == pytest.approx(1_000_000 + pos.realised_pnl, abs=1)
    ok, bad = await verify_chain(db)
    assert ok, bad


async def test_resting_limit_and_stop_orders_fill_via_matcher(db, user):
    from algo_db import session as sess

    prov = FixedPrices({"NSE:SBIN": 800.0})
    router = OrderRouter(prov)
    lim = (await router.place(db, user, buy(order_type=OrderType.LIMIT, price=790.0)))[0]
    sl = (await router.place(db, user, sell(order_type=OrderType.SL_M, trigger_price=780.0, qty=5)))[0]
    await db.commit()
    assert lim.status == "open" and sl.status == "trigger_pending"
    prov.prices["NSE:SBIN"] = 789.0
    matcher = PaperMatcher(prov)
    assert await matcher.step() == 1  # limit fills, stop not yet triggered
    prov.prices["NSE:SBIN"] = 779.0
    assert await matcher.step() == 1
    async with sess.session_scope() as s2:
        fills = (await s2.execute(select(Trade))).scalars().all()
    assert len(fills) == 2
    await db.refresh(lim)
    await db.refresh(sl)
    assert lim.status == "complete" and lim.average_price <= 790.0
    assert sl.status == "complete"


async def test_risk_rules(db, user):
    prov = FixedPrices({"NSE:SBIN": 800.0, "NFO:NIFTY17NOV2626200CE": 80.0})
    router = OrderRouter(prov)
    with pytest.raises(RiskRejectedError, match="qty"):
        await router.place(db, user, buy(qty=6000))
    with pytest.raises(RiskRejectedError, match="multiple of lot size"):
        await router.place(db, user, buy("NFO:NIFTY17NOV2626200CE", qty=10))
    with pytest.raises(RiskRejectedError, match="lots"):
        await router.place(db, user, buy("NFO:NIFTY17NOV2626200CE", qty=65 * 11))
    with pytest.raises(RiskRejectedError, match="position"):
        await router.place(db, user, buy(qty=2000))  # 16L notional > 10L default cap
    with pytest.raises(RiskRejectedError, match="away from LTP"):
        await router.place(db, user, buy(order_type=OrderType.LIMIT, price=1200))
    with pytest.raises(RiskRejectedError, match="two-factor"):
        await router.place(db, user, buy(), mode="live")
    rl = (await db.execute(select(RiskLimit).where(RiskLimit.user_id == user.id))).scalar_one()
    rl.allowed_exchanges = ["NFO"]
    with pytest.raises(RiskRejectedError, match="not in"):
        await router.place(db, user, buy())
    rl.allowed_exchanges = ["NSE", "NFO"]
    rl.allowed_instruments = ["NSE:TCS"]
    with pytest.raises(RiskRejectedError, match="not allowed"):
        await router.place(db, user, buy())
    rejected = [r for r in (await db.execute(select(__import__("algo_db.models", fromlist=["Order"]).Order))).scalars()
                if r.status == "rejected"]
    assert len(rejected) == 8 and all(r.risk_decision["allowed"] is False for r in rejected)


async def test_rate_limits(db, user, monkeypatch):
    prov = FixedPrices({"NSE:SBIN": 800.0})
    router = OrderRouter(prov)
    rl = (await db.execute(select(RiskLimit).where(RiskLimit.user_id == user.id))).scalar_one()
    rl.max_orders_per_min = 3
    for _ in range(3):
        await router.place(db, user, buy(qty=1))
    with pytest.raises(RiskRejectedError, match="last minute"):
        await router.place(db, user, buy(qty=1))
    # SEBI per-second threshold
    rl.max_orders_per_min = 600
    from algo_common.kv import MemoryKV, set_kv
    from broker_gateway import risk as risk_mod

    set_kv(MemoryKV())  # fresh rate windows
    risk_mod._engine = None
    monkeypatch.setattr(risk_mod.get_settings(), "order_rate_limit_per_sec", 2)
    router2 = OrderRouter(prov)
    await router2.place(db, user, buy("NSE:SBIN", qty=1))
    await router2.place(db, user, buy("NSE:SBIN", qty=1))
    with pytest.raises(RiskRejectedError, match="orders/sec"):
        await router2.place(db, user, buy("NSE:SBIN", qty=1))
    risk_mod._engine = None


async def test_daily_loss_blocks_new_risk_but_allows_exits(db, user):
    prov = FixedPrices({"NSE:SBIN": 800.0})
    router = OrderRouter(prov)
    rl = (await db.execute(select(RiskLimit).where(RiskLimit.user_id == user.id))).scalar_one()
    rl.max_loss_per_day = 1000
    await router.place(db, user, buy(qty=100))
    prov.prices["NSE:SBIN"] = 780.0  # -2000 unrealised
    with pytest.raises(RiskRejectedError, match="breached"):
        await router.place(db, user, buy(qty=1))
    rows = await router.place(db, user, sell(qty=100))  # reducing order allowed
    assert rows[0].status == "complete"


async def test_kill_switch_user_and_global(db, user):
    prov = FixedPrices({"NSE:SBIN": 800.0})
    router = OrderRouter(prov)
    await router.place(db, user, buy(qty=10))
    s = Strategy(user_id=user.id, name="s", dsl={"name": "s"}, kind="equity")
    db.add(s)
    await db.flush()
    d = Deployment(user_id=user.id, strategy_id=s.id, dsl={"name": "s"}, mode="paper", status="running", algo_id="X")
    db.add(d)
    await db.flush()
    summary = await engage_user(db, user, router=router)
    assert summary["deployments_stopped"] == 1 and summary["squared_off"] == 1
    assert d.status == "stopped"
    assert (await PaperBroker(user.id, db, prov).get_positions(include_closed=False)) == []
    with pytest.raises(RiskRejectedError, match="kill switch"):
        await router.place(db, user, buy())
    notes = (await db.execute(select(Notification))).scalars().all()
    assert any("Kill switch" in n.title for n in notes)
    await release_user(db, user)
    await router.place(db, user, buy(qty=1))
    db.add(SystemFlag(key=GLOBAL_KILL_FLAG, value={"engaged": True}))
    await db.flush()
    with pytest.raises(RiskRejectedError, match="platform"):
        await router.place(db, user, buy(qty=1))


async def test_freeze_quantity_slicing(db, user):
    prov = FixedPrices({"NFO:NIFTY17NOV2626200CE": 50.0})
    router = OrderRouter(prov)
    rl = (await db.execute(select(RiskLimit).where(RiskLimit.user_id == user.id))).scalar_one()
    rl.max_lots, rl.max_qty_per_order, rl.max_position_value = 100, 100_000, 1e9
    rows = await router.place(db, user, buy("NFO:NIFTY17NOV2626200CE", qty=65 * 30, product=None) if False else
                              OrderRequest(symbol="NFO:NIFTY17NOV2626200CE", side=Side.BUY, quantity=65 * 30, product=Product.NRML))
    assert [r.quantity for r in rows] == [1755, 195]  # NIFTY freeze 1800 -> 27 lots per slice
    assert rows[1].parent_order_id == rows[0].id
