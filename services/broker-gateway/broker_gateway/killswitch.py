"""Kill switch orchestration (user-level and platform-wide)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.bus import get_bus
from algo_common.logging import get_logger
from algo_common.metrics import KILL_SWITCH
from algo_common.timeutils import utcnow
from algo_db.audit import audit
from algo_db.models import BrokerConnection, Deployment, RiskLimit, SystemFlag, User
from broker_gateway.notify import notify
from broker_gateway.risk import GLOBAL_KILL_FLAG
from broker_gateway.router import OrderRouter

log = get_logger("killswitch")


async def _base_limit(db: AsyncSession, user_id: int) -> RiskLimit:
    row = (await db.execute(select(RiskLimit).where(RiskLimit.user_id == user_id, RiskLimit.strategy_id.is_(None)))).scalar_one_or_none()
    if row is None:
        row = RiskLimit(user_id=user_id)
        db.add(row)
        await db.flush()
    return row


async def stop_deployments(db: AsyncSession, user_id: int | None, reason: str) -> int:
    q = select(Deployment).where(Deployment.status.in_(("running", "paused", "pending")))
    if user_id is not None:
        q = q.where(Deployment.user_id == user_id)
    n = 0
    for d in (await db.execute(q)).scalars().all():
        d.status, d.stopped_at, d.error = "stopped", utcnow(), reason
        await get_bus().publish("deploy:control", {"action": "stop", "deployment_id": d.id, "reason": reason})
        await get_bus().publish(f"deploy:{d.user_id}", {"id": d.id, "status": "stopped", "reason": reason})
        n += 1
    return n


async def flatten_user(db: AsyncSession, user_id: int, router: OrderRouter) -> dict[str, Any]:
    """Cancel open orders and square off intraday/carry positions (paper + every connected live broker)."""
    out: dict[str, Any] = {"cancelled": 0, "squared_off": 0, "errors": []}
    out["cancelled"] += await router.cancel_open(db, user_id, "paper")
    out["squared_off"] += len(await router.square_off(db, user_id, mode="paper", actor="killswitch"))
    conns = (await db.execute(select(BrokerConnection).where(BrokerConnection.user_id == user_id,
                                                             BrokerConnection.status == "connected"))).scalars().all()
    for c in conns:
        try:
            out["cancelled"] += await router.cancel_open(db, user_id, "live")
            out["squared_off"] += len(await router.square_off(db, user_id, mode="live", connection_id=c.id, actor="killswitch"))
        except Exception as exc:
            out["errors"].append(f"{c.broker}: {exc}")
    return out


async def engage_user(db: AsyncSession, user: User, *, square_off: bool = True, actor: str = "user", ip: str | None = None,
                      router: OrderRouter | None = None) -> dict[str, Any]:
    router = router or OrderRouter()
    user.kill_switch = True
    (await _base_limit(db, user.id)).kill_switch = True
    await db.flush()
    stopped = await stop_deployments(db, user.id, "kill switch engaged")
    summary: dict[str, Any] = {"deployments_stopped": stopped}
    if square_off:
        summary.update(await flatten_user(db, user.id, router))
    await audit(db, "killswitch.engage", user_id=user.id, actor=actor, ip=ip, payload=summary)
    await notify(db, user.id, "Kill switch engaged", f"Stopped {stopped} strategies; cancelled {summary.get('cancelled', 0)} orders; "
                 f"squared off {summary.get('squared_off', 0)} positions.", kind="risk")
    await get_bus().publish("risk:killswitch", {"scope": "user", "user_id": user.id, "engaged": True})
    return summary


async def release_user(db: AsyncSession, user: User, *, actor: str = "user", ip: str | None = None) -> None:
    user.kill_switch = False
    (await _base_limit(db, user.id)).kill_switch = False
    await audit(db, "killswitch.release", user_id=user.id, actor=actor, ip=ip)
    await get_bus().publish("risk:killswitch", {"scope": "user", "user_id": user.id, "engaged": False})


async def set_global(db: AsyncSession, engaged: bool, admin: User, *, square_off: bool = False, ip: str | None = None) -> dict[str, Any]:
    flag = await db.get(SystemFlag, GLOBAL_KILL_FLAG)
    if flag is None:
        flag = SystemFlag(key=GLOBAL_KILL_FLAG, value={})
        db.add(flag)
    flag.value = {"engaged": engaged, "by": admin.id, "at": utcnow().isoformat()}
    flag.updated_by = admin.id
    summary: dict[str, Any] = {"engaged": engaged}
    if engaged:
        summary["deployments_stopped"] = await stop_deployments(db, None, "platform kill switch engaged")
        if square_off:
            router = OrderRouter()
            users = (await db.execute(select(Deployment.user_id).distinct())).scalars().all()
            for uid in users:
                try:
                    await flatten_user(db, uid, router)
                except Exception as exc:
                    log.warning("killswitch.global_flatten_failed", user=uid, error=str(exc))
    KILL_SWITCH.set(1 if engaged else 0)
    await audit(db, "killswitch.global", user_id=admin.id, actor="admin", ip=ip, payload=summary)
    await get_bus().publish("risk:killswitch", {"scope": "global", "engaged": engaged})
    return summary
