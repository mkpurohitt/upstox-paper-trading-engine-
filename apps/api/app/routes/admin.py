"""Admin console API (role-gated): stats, users, subscriptions, health, global kill switch, audit trail,
black-box strategy (SEBI RA) reviews."""

from __future__ import annotations

import platform
import time
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select, text

from algo_common.kv import get_kv
from algo_common.settings import get_settings
from algo_common.timeutils import now_ist, utcnow
from algo_db.audit import audit, verify_chain
from algo_db.models import (
    AuditLog,
    ChatMessage,
    Deployment,
    LLMUsage,
    Order,
    Payment,
    Plan,
    RagDocument,
    Strategy,
    Subscription,
    SystemFlag,
    User,
)
from app.core.deps import DB, AdminUser, client_ip
from app.services.users import active_subscription
from broker_gateway.killswitch import set_global
from broker_gateway.notify import notify
from broker_gateway.risk import GLOBAL_KILL_FLAG

router = APIRouter(prefix="/api/admin", tags=["admin"])
STARTED = time.time()


def _day_start() -> datetime:
    n = now_ist()
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/stats")
async def stats(_: AdminUser, db: DB) -> dict[str, Any]:
    async def count(q: Any) -> int:
        return int((await db.execute(q)).scalar_one())

    start = _day_start()
    subs = (await db.execute(select(Plan.code, func.count()).join(Subscription, Subscription.plan_id == Plan.id)
                             .where(Subscription.status.in_(("active", "trialing"))).group_by(Plan.code))).all()
    deps = (await db.execute(select(Deployment.mode, func.count()).where(Deployment.status.in_(("running", "paused")))
                             .group_by(Deployment.mode))).all()
    cost = (await db.execute(select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0), func.coalesce(func.sum(LLMUsage.tokens_in + LLMUsage.tokens_out), 0))
                             .where(LLMUsage.created_at >= start))).one()
    revenue = await count(select(func.coalesce(func.sum(Payment.amount_paise), 0)).where(Payment.status == "paid"))
    return {
        "users": await count(select(func.count()).select_from(User)),
        "active_users_7d": await count(select(func.count()).select_from(User).where(User.last_login_at >= utcnow() - timedelta(days=7))),
        "new_users_today": await count(select(func.count()).select_from(User).where(User.created_at >= start)),
        "subscriptions": {code: n for code, n in subs},
        "deployments_running": {mode: n for mode, n in deps},
        "orders_today": await count(select(func.count()).select_from(Order).where(Order.created_at >= start)),
        "ai_queries_today": await count(select(func.count()).select_from(ChatMessage).where(ChatMessage.role == "user", ChatMessage.created_at >= start)),
        "llm_tokens_today": int(cost[1]), "llm_cost_today_usd": round(float(cost[0]), 4),
        "rag_documents": await count(select(func.count()).select_from(RagDocument)),
        "revenue_paise": revenue,
        "pending_reviews": await count(select(func.count()).select_from(Strategy).where(Strategy.ra_status == "pending")),
    }


# ---------------------------------------------------------------- users


class AdminUserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    plan: str
    totp_enabled: bool
    kill_switch: bool
    kyc_status: str
    created_at: datetime
    last_login_at: datetime | None
    deletion_requested_at: datetime | None


async def _admin_user(db: Any, u: User) -> AdminUserOut:
    sub = await active_subscription(db, u.id)
    return AdminUserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role, is_active=u.is_active,
                        plan=sub.plan.code if sub else "free", totp_enabled=bool(u.twofa and u.twofa.enabled), kill_switch=u.kill_switch,
                        kyc_status=u.kyc_status, created_at=u.created_at, last_login_at=u.last_login_at,
                        deletion_requested_at=u.deletion_requested_at)


@router.get("/users", response_model=list[AdminUserOut])
async def users(_: AdminUser, db: DB, q: str | None = None, role: str | None = None, limit: int = Query(50, le=500),
                offset: int = Query(0, ge=0)) -> list[AdminUserOut]:
    stmt = select(User)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.full_name.ilike(like)))
    if role:
        stmt = stmt.where(User.role == role)
    rows = (await db.execute(stmt.order_by(desc(User.id)).offset(offset).limit(limit))).scalars().all()
    return [await _admin_user(db, u) for u in rows]


class UserPatchIn(BaseModel):
    role: Literal["user", "admin"] | None = None
    is_active: bool | None = None
    plan_code: str | None = None
    note: str | None = Field(default=None, max_length=300)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def patch_user(user_id: int, body: UserPatchIn, admin: AdminUser, db: DB, request: Request) -> AdminUserOut:
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and (body.role == "user" or body.is_active is False):
        raise HTTPException(400, "You cannot demote or deactivate yourself")
    changes: dict[str, Any] = {}
    if body.role is not None and body.role != u.role:
        changes["role"], u.role = [u.role, body.role], body.role
    if body.is_active is not None and body.is_active != u.is_active:
        changes["is_active"], u.is_active = [u.is_active, body.is_active], body.is_active
    if body.plan_code:
        plan = (await db.execute(select(Plan).where(Plan.code == body.plan_code))).scalar_one_or_none()
        if plan is None:
            raise HTTPException(404, "Plan not found")
        for old in (await db.execute(select(Subscription).where(Subscription.user_id == u.id, Subscription.status.in_(("active", "trialing"))))).scalars():
            old.status = "replaced"
        db.add(Subscription(user_id=u.id, plan_id=plan.id, status="active",
                            current_period_end=None if plan.price_paise == 0 else utcnow() + timedelta(days=30)))
        changes["plan"] = body.plan_code
    await audit(db, "admin.user_update", user_id=admin.id, actor="admin", entity_type="user", entity_id=u.id, ip=client_ip(request),
                payload={**changes, "note": body.note})
    await db.flush()
    return await _admin_user(db, u)


@router.get("/subscriptions")
async def subscriptions(_: AdminUser, db: DB, limit: int = Query(100, le=1000)) -> list[dict[str, Any]]:
    rows = (await db.execute(select(Subscription, User.email).join(User, User.id == Subscription.user_id)
                             .order_by(desc(Subscription.id)).limit(limit))).all()
    return [{"id": s.id, "user_id": s.user_id, "email": email, "plan": s.plan.code, "status": s.status,
             "current_period_end": s.current_period_end, "cancel_at_period_end": s.cancel_at_period_end, "created_at": s.created_at}
            for s, email in rows]


@router.get("/payments")
async def payments(_: AdminUser, db: DB, limit: int = Query(100, le=1000)) -> list[dict[str, Any]]:
    rows = (await db.execute(select(Payment, User.email).join(User, User.id == Payment.user_id).order_by(desc(Payment.id)).limit(limit))).all()
    return [{"id": p.id, "email": email, "amount_paise": p.amount_paise, "status": p.status, "method": p.method,
             "order_id": p.razorpay_order_id, "payment_id": p.razorpay_payment_id, "created_at": p.created_at, "paid_at": p.paid_at}
            for p, email in rows]


# ---------------------------------------------------------------- health


async def _timed(fn: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        detail = await fn()
        return {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "detail": detail}
    except Exception as exc:
        return {"ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "detail": f"{exc.__class__.__name__}: {str(exc)[:200]}"}


@router.get("/health")
async def health(_: AdminUser, db: DB) -> dict[str, Any]:
    from ai_agent.llm import get_router
    from ai_agent.rag.embedder import get_embedder
    from algo_jobs.registry import CRON, load_all
    from app.ws.gateway import manager
    from market_data.nse_mcp import MockNseTools, get_nse_tools
    from market_data.registry import get_provider

    s = get_settings()

    async def db_check() -> str:
        await db.execute(text("SELECT 1"))
        return db.bind.dialect.name if db.bind else "?"

    async def kv_check() -> str:
        kv = get_kv()
        await kv.set("health:ping", "1", ttl=10)
        assert await kv.get("health:ping") == "1"
        return kv.__class__.__name__

    async def md_check() -> str:
        p = get_provider()
        q = (await p.quotes(["NSE_INDEX:NIFTY"])).get("NSE_INDEX:NIFTY")
        return f"{p.name} · NIFTY {q.ltp if q else 'n/a'}"

    async def nse_check() -> str:
        c = get_nse_tools()
        tools = await c.list_tools()
        return f"{'mock' if isinstance(c, MockNseTools) else 'mcp server'} · {len(tools)} tools"

    jobs = load_all()
    checks = {
        "database": await _timed(db_check),
        "cache_bus": await _timed(kv_check),
        "market_data": await _timed(md_check),
        "nse_mcp": await _timed(nse_check),
    }
    flag = await db.get(SystemFlag, GLOBAL_KILL_FLAG)
    return {
        "status": "ok" if all(c["ok"] for c in checks.values()) else "degraded",
        "checks": checks,
        "llm": {"configured": s.llm_configured, "providers": get_router().status(), "embedder": get_embedder().name,
                "advice_enabled": s.advice_enabled},
        "jobs": {"mode": "arq (redis)" if s.redis_url and not s.embedded_workers else "embedded", "registered": sorted(jobs),
                 "cron": [name for name, _ in CRON]},
        "realtime": {"ws_clients": len(manager.clients), "channels": len(manager.by_channel)},
        "runtime": {"environment": s.environment, "data_mode": s.data_mode, "embedded_workers": s.embedded_workers,
                    "python": platform.python_version(), "uptime_s": int(time.time() - STARTED),
                    "egress_static_ip": s.egress_static_ip},
        "global_kill_switch": bool(flag and (flag.value or {}).get("engaged")),
    }


# ---------------------------------------------------------------- global kill switch


class GlobalKillIn(BaseModel):
    engaged: bool
    square_off: bool = False
    reason: str = Field(min_length=3, max_length=300)


@router.get("/kill-switch")
async def get_kill(_: AdminUser, db: DB) -> dict[str, Any]:
    flag = await db.get(SystemFlag, GLOBAL_KILL_FLAG)
    return {"engaged": bool(flag and (flag.value or {}).get("engaged")), "details": flag.value if flag else {}}


@router.post("/kill-switch")
async def post_kill(body: GlobalKillIn, admin: AdminUser, db: DB, request: Request) -> dict[str, Any]:
    summary = await set_global(db, body.engaged, admin, square_off=body.square_off, ip=client_ip(request))
    flag = await db.get(SystemFlag, GLOBAL_KILL_FLAG)
    if flag is not None:
        flag.value = {**(flag.value or {}), "reason": body.reason}
    return {**summary, "reason": body.reason}


# ---------------------------------------------------------------- audit


class AuditOut(BaseModel):
    id: int
    ts: datetime
    user_id: int | None
    actor: str
    action: str
    entity_type: str | None
    entity_id: str | None
    payload: dict[str, Any]
    ip: str | None
    hash: str


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(_: AdminUser, db: DB, action: str | None = None, user_id: int | None = None, actor: str | None = None,
                    before_id: int | None = None, limit: int = Query(100, le=1000)) -> list[AuditOut]:
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action.ilike(f"{action}%"))
    if user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
    if actor:
        q = q.where(AuditLog.actor == actor)
    if before_id:
        q = q.where(AuditLog.id < before_id)
    rows = (await db.execute(q.order_by(desc(AuditLog.id)).limit(limit))).scalars().all()
    return [AuditOut(id=r.id, ts=r.ts, user_id=r.user_id, actor=r.actor, action=r.action, entity_type=r.entity_type,
                     entity_id=r.entity_id, payload=r.payload or {}, ip=r.ip, hash=r.hash) for r in rows]


@router.get("/audit/verify")
async def audit_verify(admin: AdminUser, db: DB) -> dict[str, Any]:
    t0 = time.perf_counter()
    ok, bad = await verify_chain(db)
    n = int((await db.execute(select(func.count()).select_from(AuditLog))).scalar_one())
    await audit(db, "admin.audit_verify", user_id=admin.id, actor="admin", payload={"ok": ok, "first_bad_id": bad, "entries": n})
    return {"ok": ok, "first_bad_id": bad, "entries": n, "seconds": round(time.perf_counter() - t0, 3)}


# ---------------------------------------------------------------- black-box (SEBI RA) reviews


@router.get("/strategies/review")
async def review_queue(_: AdminUser, db: DB, status: Literal["pending", "approved", "rejected"] = "pending") -> list[dict[str, Any]]:
    rows = (await db.execute(select(Strategy, User.email).join(User, User.id == Strategy.user_id)
                             .where(Strategy.box_type == "black_box", Strategy.ra_status == status).order_by(desc(Strategy.updated_at)))).all()
    return [{"id": s.id, "name": s.name, "kind": s.kind, "owner": email, "provider_ra_number": s.provider_ra_number,
             "ra_status": s.ra_status, "visibility": s.visibility, "updated_at": s.updated_at, "description": s.description} for s, email in rows]


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=3, max_length=500)


@router.post("/strategies/{strategy_id}/review")
async def review(strategy_id: int, body: ReviewIn, admin: AdminUser, db: DB, request: Request) -> dict[str, Any]:
    s = await db.get(Strategy, strategy_id)
    if s is None or s.box_type != "black_box":
        raise HTTPException(404, "Black-box strategy not found")
    s.ra_status = "approved" if body.decision == "approve" else "rejected"
    await audit(db, "admin.ra_review", user_id=admin.id, actor="admin", entity_type="strategy", entity_id=s.id, ip=client_ip(request),
                payload={"decision": body.decision, "note": body.note, "ra_number": s.provider_ra_number})
    if s.user_id:
        await notify(db, s.user_id, f"Black-box listing {s.ra_status}: {s.name}", body.note, kind="system",
                     data={"strategy_id": s.id}, channels=[])
    return {"id": s.id, "ra_status": s.ra_status}


# ------------------------------------------------------------------ market data (Upstox access token)
class MarketDataIn(BaseModel):
    token: str | None = Field(None, max_length=4096, description="Upstox access token or analytics token")
    enabled: bool = True


def token_expiry(token: str) -> datetime | None:
    """Upstox tokens are JWTs; read the `exp` claim (no signature check: informational only)."""
    import base64
    import json as _json

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = _json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return datetime.fromtimestamp(int(exp), tz=now_ist().tzinfo) if exp else None
    except (IndexError, ValueError, TypeError):
        return None


async def verify_upstox_token(token: str) -> dict[str, Any]:
    """One cheap market-data call proves the token works for quotes, candles and the live feed."""
    from market_data.upstox import UpstoxProvider

    p = UpstoxProvider(token)
    try:
        data = await p._get("/v3/market-quote/ltp", {"instrument_key": "NSE_INDEX|Nifty 50"}) or {}
    finally:
        await p.close()
    row = next(iter(data.values()), {}) if isinstance(data, dict) else {}
    return {"nifty_ltp": row.get("last_price")}


async def _market_data_status(db: DB) -> dict[str, Any]:
    from market_data.registry import LIVE_CONFIG_KEY, provider_info

    s = get_settings()
    flag = await db.get(SystemFlag, LIVE_CONFIG_KEY)
    cfg = dict(flag.value) if flag and flag.value else {}
    exp = datetime.fromisoformat(cfg["expires_at"]) if cfg.get("expires_at") else None
    return {
        **provider_info(),
        "saved": bool(cfg), "enabled": bool(cfg.get("enabled")), "token_hint": cfg.get("token_hint"),
        "expires_at": exp.isoformat() if exp else None, "expired": bool(exp and exp <= now_ist()),
        "verified_at": cfg.get("verified_at"), "verified_nifty_ltp": cfg.get("verified_nifty_ltp"),
        "updated_at": cfg.get("set_at"), "env_token_configured": s.upstox_configured,
    }


@router.get("/market-data")
async def market_data_status(_: AdminUser, db: DB) -> dict[str, Any]:
    return await _market_data_status(db)


@router.put("/market-data")
async def set_market_data(body: MarketDataIn, admin: AdminUser, db: DB, request: Request) -> dict[str, Any]:
    from algo_common.bus import get_bus
    from algo_common.crypto import Vault, mask
    from algo_common.errors import ProviderError
    from market_data.registry import LIVE_CONFIG_KEY, apply_live_config

    flag = await db.get(SystemFlag, LIVE_CONFIG_KEY)
    cfg: dict[str, Any] = dict(flag.value) if flag and flag.value else {}
    if body.token and body.token.strip():
        token = body.token.strip().removeprefix("Bearer ").strip()
        try:
            check = await verify_upstox_token(token)
        except ProviderError as exc:
            status = (exc.details or {}).get("status")
            why = "it is invalid or has expired" if status in (401, 403) else str(exc)
            raise HTTPException(422, f"Upstox did not accept this token: {why}") from exc
        except Exception as exc:  # network / DNS / proxy
            raise HTTPException(502, f"Could not reach Upstox to verify the token: {exc.__class__.__name__}: {exc}") from exc
        exp = token_expiry(token)
        cfg.update(token_enc=Vault.from_settings().encrypt(token, aad=LIVE_CONFIG_KEY), token_hint=mask(token),
                   expires_at=exp.isoformat() if exp else None, verified_at=utcnow().isoformat(),
                   verified_nifty_ltp=check.get("nifty_ltp"))
    elif body.enabled and not cfg.get("token_enc"):
        raise HTTPException(422, "Paste an Upstox access token to turn on live data")
    cfg.update(enabled=body.enabled, set_by=admin.id, set_at=utcnow().isoformat())
    if flag is None:
        db.add(SystemFlag(key=LIVE_CONFIG_KEY, value=cfg, updated_by=admin.id))
    else:
        flag.value, flag.updated_by = cfg, admin.id
    await audit(db, "market_data.configure", user_id=admin.id, actor="admin", entity_type="system_flag",
                entity_id=LIVE_CONFIG_KEY, ip=client_ip(request),
                payload={"enabled": body.enabled, "token_changed": bool(body.token), "token_hint": cfg.get("token_hint"),
                         "expires_at": cfg.get("expires_at")})
    await db.commit()
    await apply_live_config(cfg)
    await get_bus().publish("md:provider", {"action": "reload"})
    return await _market_data_status(db)


@router.delete("/market-data")
async def clear_market_data(admin: AdminUser, db: DB, request: Request) -> dict[str, Any]:
    from algo_common.bus import get_bus
    from market_data.registry import LIVE_CONFIG_KEY, apply_live_config

    flag = await db.get(SystemFlag, LIVE_CONFIG_KEY)
    if flag is not None:
        await db.delete(flag)
    await audit(db, "market_data.clear", user_id=admin.id, actor="admin", entity_type="system_flag",
                entity_id=LIVE_CONFIG_KEY, ip=client_ip(request))
    await db.commit()
    await apply_live_config(None)
    await get_bus().publish("md:provider", {"action": "reload"})
    return await _market_data_status(db)
