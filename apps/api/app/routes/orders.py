"""Manual order ticket, order / trade books, positions, funds (paper and live)."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from algo_common.errors import RiskRejectedError
from algo_common.timeutils import IST, now_ist
from algo_db.models import Order as OrderRow
from algo_db.models import Trade as TradeRow
from app.core.deps import DB, CurrentUser, client_ip, verify_step_up
from app.schemas.trading import FundsOut, ModifyIn, OrderIn, OrderOut, PositionOut, TradeOut
from broker_gateway.base import BrokerError
from broker_gateway.models import ModifyRequest, OrderRequest
from broker_gateway.router import OrderRouter

router = APIRouter(prefix="/api", tags=["orders"])


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, RiskRejectedError):
        return HTTPException(409, {"message": exc.message, "decision": exc.details})
    if isinstance(exc, BrokerError):
        return HTTPException(exc.status_code if exc.status_code != 502 else 400, exc.message)
    raise exc


@router.post("/orders", response_model=list[OrderOut], status_code=201)
async def place(body: OrderIn, user: CurrentUser, db: DB, request: Request) -> list[OrderRow]:
    if body.mode == "live":
        await verify_step_up(db, user, body.totp_code)
    try:
        req = OrderRequest(symbol=body.symbol, side=body.side, quantity=body.quantity, order_type=body.order_type,
                           product=body.product, price=body.price, trigger_price=body.trigger_price, tag="manual")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        rows = await OrderRouter().place(db, user, req, mode=body.mode, connection_id=body.connection_id, ip=client_ip(request))
    except (RiskRejectedError, BrokerError) as exc:
        await db.commit()  # keep the rejected order row + audit entry
        raise _err(exc)
    return rows


@router.get("/orders", response_model=list[OrderOut])
async def orders(user: CurrentUser, db: DB, mode: str | None = None, deployment_id: int | None = None,
                 today: bool = False, limit: int = Query(200, le=1000)) -> list[OrderRow]:
    q = select(OrderRow).where(OrderRow.user_id == user.id)
    if mode:
        q = q.where(OrderRow.mode == mode)
    if deployment_id:
        q = q.where(OrderRow.deployment_id == deployment_id)
    if today:
        q = q.where(OrderRow.created_at >= datetime.combine(now_ist().date(), time(0, 0), tzinfo=IST))
    return list((await db.execute(q.order_by(OrderRow.id.desc()).limit(limit))).scalars())


@router.patch("/orders/{order_id}", response_model=OrderOut)
async def modify(order_id: int, body: ModifyIn, user: CurrentUser, db: DB) -> OrderRow:
    try:
        return await OrderRouter().modify(db, user.id, order_id, ModifyRequest(**body.model_dump()))
    except BrokerError as exc:
        raise _err(exc)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel(order_id: int, user: CurrentUser, db: DB) -> OrderRow:
    try:
        return await OrderRouter().cancel(db, user.id, order_id)
    except BrokerError as exc:
        raise _err(exc)


@router.get("/trades", response_model=list[TradeOut])
async def trades(user: CurrentUser, db: DB, mode: str | None = None, deployment_id: int | None = None,
                 limit: int = Query(500, le=5000)) -> list[TradeRow]:
    q = select(TradeRow).where(TradeRow.user_id == user.id)
    if mode:
        q = q.where(TradeRow.mode == mode)
    if deployment_id:
        q = q.where(TradeRow.deployment_id == deployment_id)
    return list((await db.execute(q.order_by(TradeRow.ts.desc()).limit(limit))).scalars())


@router.get("/positions", response_model=list[PositionOut])
async def positions(user: CurrentUser, db: DB, mode: str = "paper", connection_id: int | None = None) -> list[dict[str, Any]]:
    try:
        adapter, _, _ = await OrderRouter().adapter(db, user.id, mode, connection_id)
        return [p.model_dump(mode="json") for p in await adapter.get_positions()]
    except BrokerError as exc:
        raise _err(exc)


@router.post("/positions/square-off", response_model=list[OrderOut])
async def square_off(user: CurrentUser, db: DB, mode: str = "paper", connection_id: int | None = None,
                     totp_code: str | None = None) -> list[OrderRow]:
    if mode == "live":
        await verify_step_up(db, user, totp_code)
    return await OrderRouter().square_off(db, user.id, mode=mode, connection_id=connection_id, actor="user")


@router.get("/funds", response_model=FundsOut)
async def funds(user: CurrentUser, db: DB, mode: str = "paper", connection_id: int | None = None) -> FundsOut:
    try:
        adapter, _, _ = await OrderRouter().adapter(db, user.id, mode, connection_id)
        f = await adapter.get_funds()
    except BrokerError as exc:
        raise _err(exc)
    return FundsOut(**f.model_dump(), mode=mode)
