"""OrderRouter: the single path every order takes.

    OrderRequest -> Algo-ID tagging -> RiskEngine -> freeze-qty slicing -> persist (orders)
                 -> BrokerAdapter (paper | live) -> fills (trades, charges) -> audit -> bus `orders:{user}`
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.bus import get_bus
from algo_common.errors import RiskRejectedError
from algo_common.logging import get_logger
from algo_common.metrics import ORDERS_PLACED
from algo_common.settings import get_settings
from algo_common.timeutils import IST, now_ist, utcnow
from algo_db.audit import audit
from algo_db.models import Order as OrderRow
from algo_db.models import Trade as TradeRow
from algo_db.models import User
from broker_gateway.base import BrokerAdapter, BrokerError
from broker_gateway.connections import live_adapter
from broker_gateway.costs import CostModel, segment_instrument, split_orders
from broker_gateway.models import (
    ModifyRequest,
    Order,
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Product,
    Side,
)
from broker_gateway.paper import PaperBroker
from broker_gateway.risk import RiskDecision, get_risk_engine
from market_data.base import MarketDataProvider
from market_data.symbols import parse

log = get_logger("router")


def algo_id_for(strategy_id: int | None) -> str:
    """Placeholder for the exchange-assigned Algo-ID (SEBI retail algo framework).
    Replaced by the real ID once the strategy is registered through the broker."""
    return f"{get_settings().algo_id_prefix}-{'S' + str(strategy_id) if strategy_id else 'MANUAL'}"


def order_payload(row: OrderRow) -> dict[str, Any]:
    return {
        "id": row.id, "client_order_id": row.client_order_id, "broker_order_id": row.broker_order_id, "symbol": row.symbol,
        "side": row.side, "quantity": row.quantity, "filled_quantity": row.filled_quantity, "price": row.price,
        "trigger_price": row.trigger_price, "average_price": row.average_price, "order_type": row.order_type,
        "product": row.product, "status": row.status, "status_message": row.status_message, "mode": row.mode,
        "broker": row.broker, "algo_id": row.algo_id, "strategy_id": row.strategy_id, "deployment_id": row.deployment_id,
        "tag": row.tag, "created_at": row.created_at,
    }


class OrderRouter:
    def __init__(self, provider: MarketDataProvider | None = None) -> None:
        from market_data.registry import get_provider

        self.provider = provider or get_provider()
        self.risk = get_risk_engine()

    # ---- adapter resolution ------------------------------------------------------
    async def adapter(self, db: AsyncSession, user_id: int, mode: str, connection_id: int | None) -> tuple[BrokerAdapter, str, int | None]:
        if mode == "paper":
            return PaperBroker(user_id, db, self.provider), "paper", None
        if mode != "live":
            raise BrokerError(f"unsupported mode {mode}")
        adapter, conn = await live_adapter(db, user_id, connection_id)
        return adapter, conn.broker, conn.id

    async def _meta(self, symbol: str) -> tuple[float | None, int, int | None]:
        ltp = None
        try:
            q = (await self.provider.quotes([symbol])).get(symbol)
            ltp = q.ltp if q else None
        except Exception:
            ltp = None
        lot, freeze = 1, None
        p = parse(symbol)
        if p.is_derivative:
            try:
                ins = await self.provider.instrument(symbol)
            except Exception:
                ins = None
            if ins is not None:
                lot, freeze = ins.lot_size, ins.freeze_qty
            else:
                from market_data.universe import asset_for_underlying

                a = asset_for_underlying(p.underlying or "")
                if a and a.lot_size:
                    lot, freeze = a.lot_size, a.freeze_qty
        return ltp, lot, freeze

    async def day_pnl(self, adapter: BrokerAdapter, positions: list[Position]) -> float:
        if isinstance(adapter, PaperBroker):
            return await adapter.day_pnl()
        return sum(p.realised_pnl + p.unrealised_pnl for p in positions)

    # ---- placement ----------------------------------------------------------------
    async def place(
        self, db: AsyncSession, user: User | int, req: OrderRequest, *, mode: str = "paper", connection_id: int | None = None,
        bypass_risk: bool = False, bypass_kill: bool = False, actor: str = "user", ip: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> list[OrderRow]:
        if isinstance(user, int):
            u = await db.get(User, user)
            if u is None:
                raise BrokerError("user not found")
            user = u
        req = req.model_copy(update={"algo_id": req.algo_id or algo_id_for(req.strategy_id)})
        if mode == "live" and not bypass_risk and not user.totp_enabled:
            # fail closed before any broker is contacted
            decision = RiskDecision(False, "live_requires_2fa", "enable two-factor authentication to trade live")
            await self._reject(db, user.id, req, mode, "live", None, decision, actor, ip)
        adapter, broker, conn_id = await self.adapter(db, user.id, mode, connection_id)
        ltp, lot, freeze = await self._meta(req.symbol)
        positions = await adapter.get_positions()
        if bypass_risk:
            decision = RiskDecision(True, "bypass", "system order (square-off / kill switch)")
        else:
            decision = await self.risk.evaluate(db, user, req, mode=mode, ltp=ltp, lot_size=lot, positions=positions,
                                                day_pnl=await self.day_pnl(adapter, positions), overrides=overrides,
                                                bypass_kill=bypass_kill)
        if not decision.allowed:
            await self._reject(db, user.id, req, mode, broker, conn_id, decision, actor, ip)
        await audit(db, "risk.allow", user_id=user.id, actor=actor, ip=ip, entity_type="order",
                    payload={"request": req.model_dump(mode="json"), "decision": decision.as_dict(), "mode": mode})

        slices = split_orders(req.quantity, freeze, lot) if parse(req.symbol).is_derivative else [req.quantity]
        rows: list[OrderRow] = []
        parent_id: int | None = None
        for qty in slices:
            sreq = req.model_copy(update={"quantity": qty})
            row = self._new_row(user.id, sreq, mode, broker, conn_id, qty)
            row.risk_decision = decision.as_dict()
            row.parent_order_id = parent_id
            db.add(row)
            await db.flush()
            parent_id = parent_id or row.id
            try:
                ack = await adapter.place_order(sreq)
            except BrokerError as exc:
                ack = OrderAck(broker_order_id="", status=OrderStatus.REJECTED, message=exc.message)
            await self._apply_ack(db, row, ack)
            ORDERS_PLACED.labels(broker, mode, row.status).inc()
            await audit(db, "order.place", user_id=user.id, actor=actor, ip=ip, entity_type="order", entity_id=row.id,
                        payload={"order": order_payload(row), "slice_of": len(slices)})
            await get_bus().publish(f"orders:{user.id}", order_payload(row))
            rows.append(row)
        return rows

    async def _reject(self, db: AsyncSession, user_id: int, req: OrderRequest, mode: str, broker: str, conn_id: int | None,
                      decision: RiskDecision, actor: str, ip: str | None) -> None:
        await audit(db, "risk.reject", user_id=user_id, actor=actor, ip=ip, entity_type="order",
                    payload={"request": req.model_dump(mode="json"), "decision": decision.as_dict(), "mode": mode})
        row = self._new_row(user_id, req, mode, broker, conn_id, req.quantity)
        row.status, row.status_message, row.risk_decision = "rejected", f"Risk: {decision.reason}", decision.as_dict()
        db.add(row)
        await db.flush()
        ORDERS_PLACED.labels(broker, mode, "risk_rejected").inc()
        await get_bus().publish(f"orders:{user_id}", order_payload(row))
        raise RiskRejectedError(decision.reason or "rejected by risk engine", details=decision.as_dict())

    def _new_row(self, user_id: int, req: OrderRequest, mode: str, broker: str, conn_id: int | None, qty: int) -> OrderRow:
        return OrderRow(
            user_id=user_id, deployment_id=req.deployment_id, strategy_id=req.strategy_id, broker=broker,
            broker_connection_id=conn_id, mode=mode, client_order_id=uuid.uuid4().hex[:24], symbol=req.symbol,
            exchange=req.exchange, side=req.side.value, quantity=qty, price=req.price, trigger_price=req.trigger_price,
            order_type=req.order_type.value, product=req.product.value, validity=req.validity, status="pending",
            algo_id=req.algo_id or algo_id_for(req.strategy_id), tag=req.tag,
        )

    async def _apply_ack(self, db: AsyncSession, row: OrderRow, ack: OrderAck) -> None:
        row.broker_order_id = ack.broker_order_id or row.broker_order_id
        row.status = ack.status.value
        row.status_message = ack.message
        if ack.filled_quantity and ack.average_price:
            await self.record_fill(db, row, ack.filled_quantity, ack.average_price, publish=False)

    async def record_fill(self, db: AsyncSession, row: OrderRow, qty: int, price: float, publish: bool = True) -> TradeRow:
        prev = row.filled_quantity
        row.filled_quantity = prev + qty
        row.average_price = ((row.average_price or 0) * prev + price * qty) / row.filled_quantity
        row.status = "complete" if row.filled_quantity >= row.quantity else "open"
        exch, instrument = segment_instrument(row.symbol)
        charges = CostModel(row.broker).charges(on=now_ist().date(), side=row.side, price=price, quantity=qty,  # type: ignore[arg-type]
                                                exchange=exch, instrument=instrument, product=row.product)
        trade = TradeRow(order_id=row.id, user_id=row.user_id, deployment_id=row.deployment_id, strategy_id=row.strategy_id,
                         broker=row.broker, mode=row.mode, broker_trade_id=f"{row.broker_order_id}-{row.filled_quantity}",
                         symbol=row.symbol, exchange=row.exchange, side=row.side, quantity=qty, price=price,
                         charges=round(charges.total, 2), product=row.product, ts=utcnow())
        db.add(trade)
        await db.flush()
        await audit(db, "order.fill", user_id=row.user_id, actor="system", entity_type="order", entity_id=row.id,
                    payload={"qty": qty, "price": price, "charges": charges.as_dict()})
        if publish:
            await get_bus().publish(f"orders:{row.user_id}", order_payload(row))
        return trade

    # ---- modify / cancel -------------------------------------------------------------
    async def _owned(self, db: AsyncSession, user_id: int, order_id: int) -> OrderRow:
        row = await db.get(OrderRow, order_id)
        if row is None or row.user_id != user_id:
            raise BrokerError("Order not found", code="not_found")
        return row

    @staticmethod
    def _to_order(row: OrderRow) -> Order:
        return Order(broker_order_id=row.broker_order_id or "", symbol=row.symbol, side=Side(row.side), quantity=row.quantity,
                     filled_quantity=row.filled_quantity, price=row.price, trigger_price=row.trigger_price,
                     order_type=OrderType(row.order_type), product=Product(row.product), status=OrderStatus(row.status))

    async def modify(self, db: AsyncSession, user_id: int, order_id: int, req: ModifyRequest, actor: str = "user") -> OrderRow:
        row = await self._owned(db, user_id, order_id)
        if OrderStatus(row.status).is_terminal:
            raise BrokerError(f"Order is already {row.status}")
        adapter, _, _ = await self.adapter(db, user_id, row.mode, row.broker_connection_id)
        before = order_payload(row)
        await adapter.modify_order(row.broker_order_id or "", req, self._to_order(row))
        if row.mode != "paper":
            if req.quantity:
                row.quantity = req.quantity
            if req.price is not None:
                row.price = req.price
            if req.trigger_price is not None:
                row.trigger_price = req.trigger_price
        await audit(db, "order.modify", user_id=user_id, actor=actor, entity_type="order", entity_id=row.id,
                    payload={"before": before, "change": req.model_dump(mode="json", exclude_none=True)})
        await get_bus().publish(f"orders:{user_id}", order_payload(row))
        return row

    async def cancel(self, db: AsyncSession, user_id: int, order_id: int, actor: str = "user") -> OrderRow:
        row = await self._owned(db, user_id, order_id)
        if OrderStatus(row.status).is_terminal:
            raise BrokerError(f"Order is already {row.status}")
        adapter, _, _ = await self.adapter(db, user_id, row.mode, row.broker_connection_id)
        ack = await adapter.cancel_order(row.broker_order_id or "")
        row.status = ack.status.value
        await audit(db, "order.cancel", user_id=user_id, actor=actor, entity_type="order", entity_id=row.id)
        await get_bus().publish(f"orders:{user_id}", order_payload(row))
        return row

    async def cancel_open(self, db: AsyncSession, user_id: int, mode: str = "paper", deployment_id: int | None = None,
                          actor: str = "system") -> int:
        q = select(OrderRow).where(OrderRow.user_id == user_id, OrderRow.mode == mode,
                                   OrderRow.status.in_(("open", "trigger_pending", "pending")))
        if deployment_id:
            q = q.where(OrderRow.deployment_id == deployment_id)
        n = 0
        for row in (await db.execute(q)).scalars().all():
            try:
                await self.cancel(db, user_id, row.id, actor=actor)
                n += 1
            except BrokerError as exc:
                log.warning("router.cancel_failed", order=row.id, error=exc.message)
        return n

    async def square_off(self, db: AsyncSession, user_id: int, *, mode: str = "paper", connection_id: int | None = None,
                         deployment_id: int | None = None, products: tuple[str, ...] = ("MIS", "NRML"), actor: str = "system",
                         strategy_id: int | None = None) -> list[OrderRow]:
        adapter, _, _ = await self.adapter(db, user_id, mode, connection_id)
        positions = await adapter.get_positions()
        if deployment_id:
            # only what this deployment opened
            deployed = await self.deployment_positions(db, deployment_id)
            positions = [p.model_copy(update={"quantity": deployed.get((p.symbol, p.product.value), 0)}) for p in positions]
        out: list[OrderRow] = []
        for p in positions:
            if not p.quantity or p.product.value not in products:
                continue
            req = OrderRequest(symbol=p.symbol, side=Side.SELL if p.quantity > 0 else Side.BUY, quantity=abs(p.quantity),
                               product=p.product, tag="squareoff", deployment_id=deployment_id, strategy_id=strategy_id)
            try:
                out += await self.place(db, user_id, req, mode=mode, connection_id=connection_id, bypass_risk=True, actor=actor)
            except Exception as exc:
                log.warning("router.squareoff_failed", symbol=p.symbol, error=str(exc))
        return out

    async def deployment_positions(self, db: AsyncSession, deployment_id: int) -> dict[tuple[str, str], int]:
        rows = (await db.execute(select(TradeRow).where(TradeRow.deployment_id == deployment_id))).scalars()
        net: dict[tuple[str, str], int] = {}
        for t in rows:
            k = (t.symbol, t.product)
            net[k] = net.get(k, 0) + (t.quantity if t.side == "BUY" else -t.quantity)
        return net

    # ---- live order sync ------------------------------------------------------------------
    async def sync_live(self, db: AsyncSession, user_id: int, connection_id: int) -> int:
        adapter, _, _ = await self.adapter(db, user_id, "live", connection_id)
        book = {o.broker_order_id: o for o in await adapter.get_order_book()}
        start = datetime.combine(now_ist().date(), time(0, 0), tzinfo=IST)
        rows = (await db.execute(select(OrderRow).where(OrderRow.user_id == user_id, OrderRow.mode == "live",
                                                        OrderRow.broker_connection_id == connection_id,
                                                        OrderRow.created_at >= start))).scalars().all()
        changed = 0
        for row in rows:
            o = book.get(row.broker_order_id or "")
            if o is None:
                continue
            if o.filled_quantity > row.filled_quantity and o.average_price:
                delta = o.filled_quantity - row.filled_quantity
                # back out the average of the new fills from the cumulative average
                px = (o.average_price * o.filled_quantity - (row.average_price or 0) * row.filled_quantity) / delta
                await self.record_fill(db, row, delta, round(px, 2), publish=False)
                changed += 1
            if row.status != o.status.value:
                row.status, row.status_message = o.status.value, o.status_message
                changed += 1
                await get_bus().publish(f"orders:{user_id}", order_payload(row))
        return changed
