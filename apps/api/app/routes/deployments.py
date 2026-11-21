"""Strategy deployments (paper / live / notify) and their lifecycle controls."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from algo_common.bus import get_bus
from algo_common.timeutils import utcnow
from algo_db.audit import audit
from algo_db.models import BrokerConnection, Deployment, DeploymentLog, RiskLimit, Strategy
from app.core.deps import DB, CurrentUser, client_ip, verify_step_up
from app.schemas.common import Message
from app.schemas.trading import DeploymentIn, DeploymentLogOut, DeploymentOut
from app.services.quotas import enforce
from broker_gateway.risk import global_kill_engaged
from broker_gateway.router import OrderRouter, algo_id_for
from strategy_engine.dsl import StrategyDSL

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


def _out(d: Deployment) -> DeploymentOut:
    o = DeploymentOut.model_validate(d)
    o.name = d.dsl.get("name", "")
    o.kind = d.dsl.get("kind", "")
    try:
        o.symbols = StrategyDSL.model_validate(d.dsl).symbols
    except Exception:
        o.symbols = []
    return o


async def _owned(db: DB, user_id: int, dep_id: int) -> Deployment:
    d = await db.get(Deployment, dep_id)
    if d is None or d.user_id != user_id:
        raise HTTPException(404, "Deployment not found")
    return d


@router.post("", response_model=DeploymentOut, status_code=201)
async def deploy(body: DeploymentIn, user: CurrentUser, db: DB, request: Request) -> DeploymentOut:
    if not body.acknowledge_risk:
        raise HTTPException(422, "Confirm the risk disclosure to deploy")
    s = await db.get(Strategy, body.strategy_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Strategy not found")
    if s.box_type == "black_box" and s.ra_status != "approved":
        raise HTTPException(403, "Black-box strategies can be deployed only after RA approval")
    if user.kill_switch or await global_kill_engaged(db):
        raise HTTPException(409, "Kill switch is engaged - release it before deploying")
    broker = "paper"
    if body.mode == "live":
        await verify_step_up(db, user, body.totp_code)
        await enforce(db, user.id, "live")
        conn = await db.get(BrokerConnection, body.connection_id) if body.connection_id else None
        if conn is None or conn.user_id != user.id:
            raise HTTPException(422, "Choose a connected broker for live deployment")
        if conn.status != "connected":
            raise HTTPException(409, f"{conn.broker} session is {conn.status}; reconnect first")
        broker = conn.broker
    else:
        await enforce(db, user.id, "paper")
    limits = {k: v for k, v in body.risk_limits.model_dump().items() if v is not None}
    limits["capital"] = body.capital
    d = Deployment(user_id=user.id, strategy_id=s.id, strategy_version=s.version, dsl=s.dsl, broker=broker,
                   broker_connection_id=body.connection_id if body.mode == "live" else None, mode=body.mode,
                   status="running", multiplier=body.multiplier, risk_limits=limits, notify_channels=body.notify_channels,
                   algo_id=algo_id_for(s.id), started_at=utcnow(),
                   confirmed_2fa_at=utcnow() if body.mode == "live" else None)
    db.add(d)
    await db.flush()
    # per-strategy limits enforced by the risk engine for every order of this strategy
    rl = (await db.execute(select(RiskLimit).where(RiskLimit.user_id == user.id, RiskLimit.strategy_id == s.id))).scalar_one_or_none()
    if rl is None:
        rl = RiskLimit(user_id=user.id, strategy_id=s.id)
        db.add(rl)
    for k in ("max_loss_per_day", "max_orders_per_min", "max_position_value", "max_lots", "max_qty_per_order"):
        if limits.get(k) is not None:
            setattr(rl, k, limits[k])
    await audit(db, "deployment.start", user_id=user.id, entity_type="deployment", entity_id=d.id, ip=client_ip(request),
                payload={"strategy_id": s.id, "version": s.version, "mode": body.mode, "broker": broker,
                         "multiplier": body.multiplier, "risk_limits": limits, "algo_id": d.algo_id})
    await db.commit()
    await get_bus().publish("deploy:control", {"action": "start", "deployment_id": d.id})
    await get_bus().publish(f"deploy:{user.id}", {"type": "status", "deployment_id": d.id, "status": "running"})
    return _out(d)


@router.get("", response_model=list[DeploymentOut])
async def list_deployments(user: CurrentUser, db: DB, active: bool = False) -> list[DeploymentOut]:
    q = select(Deployment).where(Deployment.user_id == user.id)
    if active:
        q = q.where(Deployment.status.in_(("running", "paused", "pending")))
    return [_out(d) for d in (await db.execute(q.order_by(Deployment.id.desc()).limit(100))).scalars()]


@router.get("/{dep_id}", response_model=DeploymentOut)
async def get_deployment(dep_id: int, user: CurrentUser, db: DB) -> DeploymentOut:
    return _out(await _owned(db, user.id, dep_id))


@router.get("/{dep_id}/logs", response_model=list[DeploymentLogOut])
async def logs(dep_id: int, user: CurrentUser, db: DB, limit: int = Query(200, le=2000)) -> list[DeploymentLog]:
    await _owned(db, user.id, dep_id)
    q = select(DeploymentLog).where(DeploymentLog.deployment_id == dep_id).order_by(DeploymentLog.id.desc()).limit(limit)
    return list((await db.execute(q)).scalars())


async def _set_status(db: DB, d: Deployment, status: str, action: str, user_id: int, ip: str | None) -> None:
    d.status = status
    if status == "stopped":
        d.stopped_at = utcnow()
    await audit(db, f"deployment.{action}", user_id=user_id, entity_type="deployment", entity_id=d.id, ip=ip)
    await db.commit()
    await get_bus().publish("deploy:control", {"action": action, "deployment_id": d.id})
    await get_bus().publish(f"deploy:{user_id}", {"type": "status", "deployment_id": d.id, "status": status})


@router.post("/{dep_id}/pause", response_model=DeploymentOut)
async def pause(dep_id: int, user: CurrentUser, db: DB, request: Request) -> DeploymentOut:
    d = await _owned(db, user.id, dep_id)
    if d.status != "running":
        raise HTTPException(409, f"Deployment is {d.status}")
    await _set_status(db, d, "paused", "pause", user.id, client_ip(request))
    return _out(d)


@router.post("/{dep_id}/restart", response_model=DeploymentOut)
async def restart(dep_id: int, user: CurrentUser, db: DB, request: Request) -> DeploymentOut:
    """Restart a deployment whose runner stopped with an error (paper / notify only: a live deployment must be
    redeployed so the user re-confirms with a fresh 2FA code)."""
    d = await _owned(db, user.id, dep_id)
    if d.status != "error":
        raise HTTPException(409, f"Only a deployment in error can be restarted (this one is {d.status})")
    if d.mode == "live":
        raise HTTPException(409, "Live deployments must be redeployed from the Build page (requires a fresh 2FA code)")
    if user.kill_switch or await global_kill_engaged(db):
        raise HTTPException(409, "Kill switch is engaged - release it before restarting")
    d.error = None
    d.stopped_at = None
    await _set_status(db, d, "running", "restart", user.id, client_ip(request))
    await get_bus().publish("deploy:control", {"action": "start", "deployment_id": d.id})
    return _out(d)


@router.post("/{dep_id}/resume", response_model=DeploymentOut)
async def resume(dep_id: int, user: CurrentUser, db: DB, request: Request) -> DeploymentOut:
    d = await _owned(db, user.id, dep_id)
    if d.status != "paused":
        raise HTTPException(409, f"Deployment is {d.status}")
    if user.kill_switch:
        raise HTTPException(409, "Kill switch is engaged")
    await _set_status(db, d, "running", "resume", user.id, client_ip(request))
    return _out(d)


@router.post("/{dep_id}/stop", response_model=DeploymentOut)
async def stop(dep_id: int, user: CurrentUser, db: DB, request: Request, square_off: bool = False) -> DeploymentOut:
    d = await _owned(db, user.id, dep_id)
    if d.status in ("stopped", "squared_off"):
        return _out(d)
    if square_off:
        await OrderRouter().square_off(db, user.id, mode=d.mode if d.mode != "notify" else "paper",
                                       connection_id=d.broker_connection_id, deployment_id=d.id, strategy_id=d.strategy_id,
                                       actor="user", products=("MIS", "NRML", "CNC"))
    await _set_status(db, d, "squared_off" if square_off else "stopped", "stop", user.id, client_ip(request))
    return _out(d)


@router.post("/{dep_id}/square-off", response_model=Message)
async def square_off(dep_id: int, user: CurrentUser, db: DB) -> Message:
    d = await _owned(db, user.id, dep_id)
    rows = await OrderRouter().square_off(db, user.id, mode=d.mode if d.mode != "notify" else "paper",
                                          connection_id=d.broker_connection_id, deployment_id=d.id, strategy_id=d.strategy_id,
                                          products=("MIS", "NRML", "CNC"), actor="user")
    await audit(db, "deployment.square_off", user_id=user.id, entity_type="deployment", entity_id=d.id,
                payload={"orders": [r.id for r in rows]})
    return Message(message=f"Placed {len(rows)} square-off order(s)")


def _summary(rows: list[Any]) -> dict[str, Any]:
    return {"count": len(rows)}
