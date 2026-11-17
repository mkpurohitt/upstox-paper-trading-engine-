"""Per-plan usage quotas (AI queries, backtests, live strategies)."""

from __future__ import annotations

from datetime import datetime, time

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.timeutils import IST, now_ist
from algo_db.models import Backtest, ChatMessage, ChatSession, Deployment
from app.services.users import active_subscription, get_plan


def _today_start() -> datetime:
    return datetime.combine(now_ist().date(), time(0, 0), tzinfo=IST)


async def plan_limits(db: AsyncSession, user_id: int) -> dict[str, int]:
    sub = await active_subscription(db, user_id)
    plan = sub.plan if sub else await get_plan(db, "free")
    return dict(plan.limits)


async def usage(db: AsyncSession, user_id: int) -> dict[str, int]:
    start = _today_start()
    bt = (await db.execute(select(func.count()).select_from(Backtest)
                           .where(Backtest.user_id == user_id, Backtest.created_at >= start))).scalar_one()
    ai = (await db.execute(
        select(func.count()).select_from(ChatMessage).join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id, ChatMessage.role == "user", ChatMessage.created_at >= start)
    )).scalar_one()
    live = (await db.execute(select(func.count()).select_from(Deployment)
                             .where(Deployment.user_id == user_id, Deployment.mode == "live",
                                    Deployment.status.in_(("running", "paused", "pending"))))).scalar_one()
    paper = (await db.execute(select(func.count()).select_from(Deployment)
                              .where(Deployment.user_id == user_id, Deployment.mode != "live",
                                     Deployment.status.in_(("running", "paused", "pending"))))).scalar_one()
    return {"backtests_today": bt, "ai_queries_today": ai, "live_strategies": live, "paper_strategies": paper}


async def enforce(db: AsyncSession, user_id: int, kind: str) -> None:
    limits = await plan_limits(db, user_id)
    used = await usage(db, user_id)
    mapping = {"backtest": ("backtests_per_day", "backtests_today"), "ai": ("ai_queries_per_day", "ai_queries_today"),
               "live": ("live_strategies", "live_strategies"), "paper": ("paper_strategies", "paper_strategies")}
    lim_key, use_key = mapping[kind]
    if used[use_key] >= int(limits.get(lim_key, 0)):
        raise HTTPException(
            402, f"Plan limit reached: {lim_key.replace('_', ' ')} = {limits.get(lim_key, 0)}. Upgrade your plan for more.",
        )
