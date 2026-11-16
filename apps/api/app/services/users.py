"""User lifecycle helpers shared by auth routes, OAuth and the seed script."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.timeutils import utcnow
from algo_db.audit import audit
from algo_db.models import Consent, Plan, RiskLimit, Subscription, User, Watchlist
from app.core.security import hash_password

DEFAULT_PLANS = [
    {
        "code": "free", "name": "Free", "price_paise": 0, "sort_order": 0,
        "limits": {"ai_queries_per_day": 25, "backtests_per_day": 10, "live_strategies": 0,
                   "paper_strategies": 2, "screens": 3, "rag_uploads": 0},
        "features": ["AI copilot (25 queries/day)", "10 backtests/day", "Paper trading (2 strategies)",
                     "All analysis dashboards (delayed refresh)"],
    },
    {
        "code": "pro", "name": "Pro", "price_paise": 99_900, "sort_order": 1,
        "limits": {"ai_queries_per_day": 300, "backtests_per_day": 200, "live_strategies": 3,
                   "paper_strategies": 10, "screens": 25, "rag_uploads": 20},
        "features": ["AI copilot (300 queries/day)", "200 backtests/day + optimisation", "3 live strategies",
                     "Real-time dashboards & scanners", "Telegram / WhatsApp alerts"],
    },
    {
        "code": "elite", "name": "Elite", "price_paise": 249_900, "sort_order": 2,
        "limits": {"ai_queries_per_day": 2000, "backtests_per_day": 2000, "live_strategies": 15,
                   "paper_strategies": 50, "screens": 200, "rag_uploads": 200},
        "features": ["AI copilot (2000 queries/day, strongest model)", "Walk-forward + Monte Carlo",
                     "15 live strategies across brokers", "Priority execution workers", "Document uploads to RAG"],
    },
]


async def ensure_plans(db: AsyncSession) -> None:
    existing = {p.code: p for p in (await db.execute(select(Plan))).scalars()}
    for spec in DEFAULT_PLANS:
        plan = existing.get(spec["code"])
        if plan is None:
            db.add(Plan(**spec))
        else:
            plan.limits, plan.features, plan.price_paise, plan.name = (
                spec["limits"], spec["features"], spec["price_paise"], spec["name"]
            )
    await db.flush()


async def get_plan(db: AsyncSession, code: str) -> Plan:
    plan = (await db.execute(select(Plan).where(Plan.code == code))).scalar_one_or_none()
    if plan is None:
        await ensure_plans(db)
        plan = (await db.execute(select(Plan).where(Plan.code == code))).scalar_one()
    return plan


async def active_subscription(db: AsyncSession, user_id: int) -> Subscription | None:
    q = (
        select(Subscription)
        .where(Subscription.user_id == user_id, Subscription.status.in_(("active", "trialing")))
        .order_by(Subscription.id.desc())
        .limit(1)
    )
    sub = (await db.execute(q)).scalar_one_or_none()
    if sub and sub.current_period_end and sub.current_period_end < utcnow() and sub.plan.code != "free":
        sub.status = "expired"
        await db.flush()
        return None
    return sub


async def plan_code_for(db: AsyncSession, user_id: int) -> str:
    sub = await active_subscription(db, user_id)
    return sub.plan.code if sub else "free"


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password: str | None,
    full_name: str = "",
    role: str = "user",
    google_sub: str | None = None,
    avatar_url: str | None = None,
    consents: dict[str, bool] | None = None,
    ip: str | None = None,
    plan_code: str = "free",
) -> User:
    user = User(
        email=email.lower().strip(),
        password_hash=hash_password(password) if password else None,
        full_name=full_name,
        role=role,
        google_sub=google_sub,
        avatar_url=avatar_url,
        email_verified=google_sub is not None,
        notification_prefs={"email": True, "telegram": False, "whatsapp": False, "push": True,
                            "order_updates": True, "strategy_alerts": True, "news_digest": False},
        twofa=None,
    )
    db.add(user)
    await db.flush()
    plan = await get_plan(db, plan_code)
    period_end = None if plan.code == "free" else utcnow() + timedelta(days=30)
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status="active", current_period_end=period_end))
    db.add(RiskLimit(user_id=user.id))
    db.add(Watchlist(user_id=user.id, name="My Watchlist",
                     symbols=["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY", "NSE:RELIANCE", "NSE:HDFCBANK",
                              "NSE:INFY", "NSE:TCS", "NSE:ICICIBANK", "NSE:SBIN"]))
    for purpose, granted in (consents or {}).items():
        db.add(Consent(user_id=user.id, purpose=purpose, granted=granted, ip=ip))
    await audit(db, "user.register", user_id=user.id, entity_type="user", entity_id=user.id,
                payload={"method": "google" if google_sub else "password", "role": role}, ip=ip)
    await db.flush()
    return user
