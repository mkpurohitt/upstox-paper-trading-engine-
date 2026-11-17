"""Risk limits, kill switch, dry-run risk checks and the user's audit trail."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from algo_common.settings import get_settings
from algo_db.audit import audit
from algo_db.models import AuditLog, RiskLimit, Strategy
from app.core.deps import DB, CurrentUser, client_ip
from app.schemas.trading import (
    AuditOut,
    KillSwitchIn,
    KillSwitchOut,
    OrderIn,
    RiskCheckOut,
    RiskLimitsIn,
    RiskLimitsOut,
)
from broker_gateway.killswitch import engage_user, release_user
from broker_gateway.models import OrderRequest
from broker_gateway.risk import get_risk_engine, global_kill_engaged
from broker_gateway.router import OrderRouter

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/kill-switch", response_model=KillSwitchOut)
async def kill_state(user: CurrentUser, db: DB) -> KillSwitchOut:
    return KillSwitchOut(user_engaged=user.kill_switch, global_engaged=await global_kill_engaged(db))


@router.post("/kill-switch", response_model=KillSwitchOut)
async def kill(body: KillSwitchIn, user: CurrentUser, db: DB, request: Request) -> KillSwitchOut:
    summary = {}
    if body.engaged:
        summary = await engage_user(db, user, square_off=body.square_off, ip=client_ip(request))
    else:
        await release_user(db, user, ip=client_ip(request))
    return KillSwitchOut(user_engaged=user.kill_switch, global_engaged=await global_kill_engaged(db), summary=summary)


async def _limit_row(db: DB, user_id: int, strategy_id: int | None) -> RiskLimit:
    q = select(RiskLimit).where(RiskLimit.user_id == user_id)
    q = q.where(RiskLimit.strategy_id == strategy_id) if strategy_id else q.where(RiskLimit.strategy_id.is_(None))
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        row = RiskLimit(user_id=user_id, strategy_id=strategy_id)
        db.add(row)
        await db.flush()
    return row


def _out(row: RiskLimit) -> RiskLimitsOut:
    out = RiskLimitsOut.model_validate(row)
    s = get_settings()
    out.sebi_order_rate_limit_per_sec, out.static_egress_ip = s.order_rate_limit_per_sec, s.egress_static_ip
    return out


@router.get("/limits", response_model=RiskLimitsOut)
async def get_limits(user: CurrentUser, db: DB, strategy_id: int | None = None) -> RiskLimitsOut:
    return _out(await _limit_row(db, user.id, strategy_id))


@router.put("/limits", response_model=RiskLimitsOut)
async def set_limits(body: RiskLimitsIn, user: CurrentUser, db: DB, request: Request, strategy_id: int | None = None) -> RiskLimitsOut:
    if strategy_id:
        s = await db.get(Strategy, strategy_id)
        if s is None or s.user_id != user.id:
            raise HTTPException(404, "Strategy not found")
    row = await _limit_row(db, user.id, strategy_id)
    changes = body.model_dump(exclude_none=True)
    if "allowed_exchanges" in changes:
        bad = set(changes["allowed_exchanges"]) - {"NSE", "BSE", "NFO", "BFO", "MCX", "CDS"}
        if bad:
            raise HTTPException(422, f"Unknown exchanges {sorted(bad)}")
    for k, v in changes.items():
        setattr(row, k, v)
    await audit(db, "risk.limits_update", user_id=user.id, entity_type="risk_limits", entity_id=row.id,
                payload={"strategy_id": strategy_id, **changes}, ip=client_ip(request))
    return _out(row)


@router.post("/check", response_model=RiskCheckOut)
async def dry_run(body: OrderIn, user: CurrentUser, db: DB) -> RiskCheckOut:
    req = OrderRequest(symbol=body.symbol, side=body.side, quantity=body.quantity, order_type=body.order_type, product=body.product,
                       price=body.price, trigger_price=body.trigger_price)
    r = OrderRouter()
    adapter, _, _ = await r.adapter(db, user.id, body.mode, body.connection_id)
    ltp, lot, _ = await r._meta(req.symbol)
    positions = await adapter.get_positions()
    d = await get_risk_engine().evaluate(db, user, req, mode=body.mode, ltp=ltp, lot_size=lot, positions=positions,
                                         day_pnl=await r.day_pnl(adapter, positions), record_rate=False)
    return RiskCheckOut(**d.as_dict())


@router.get("/audit", response_model=list[AuditOut])
async def my_audit(user: CurrentUser, db: DB, action: str | None = None, limit: int = Query(100, le=1000)) -> list[AuditLog]:
    q = select(AuditLog).where(AuditLog.user_id == user.id)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    return list((await db.execute(q.order_by(AuditLog.id.desc()).limit(limit))).scalars())
