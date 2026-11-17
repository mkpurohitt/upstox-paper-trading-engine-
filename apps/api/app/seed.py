"""Idempotent seed: plans, admin + demo users (+ demo strategies and mock data from later phases).

Run:  python -m app.seed
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from algo_common.logging import configure_logging, get_logger
from algo_common.settings import get_settings
from algo_db.models import User
from algo_db.session import create_all, dispose_engine, session_scope
from app.services.users import create_user, ensure_plans

log = get_logger("seed")

ADMIN_EMAIL = "admin@algodesk.in"
ADMIN_PASSWORD = "admin12345"  # dev only; rotate immediately in any shared environment


async def seed_users() -> tuple[User, User]:
    s = get_settings()
    async with session_scope() as db:
        await ensure_plans(db)
        demo = (await db.execute(select(User).where(User.email == s.demo_user_email))).scalar_one_or_none()
        if demo is None:
            demo = await create_user(
                db, email=s.demo_user_email, password=s.demo_user_password.get_secret_value(),
                full_name="Demo Trader", plan_code="pro",
                consents={"terms": True, "privacy": True, "data_processing": True},
            )
        admin = (await db.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one_or_none()
        if admin is None and s.environment != "production":
            admin = await create_user(
                db, email=ADMIN_EMAIL, password=ADMIN_PASSWORD, full_name="Platform Admin", role="admin",
                plan_code="elite", consents={"terms": True, "privacy": True, "data_processing": True},
            )
        return demo, admin  # type: ignore[return-value]


async def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, False, service="seed")
    if s.is_sqlite:
        await create_all()
    demo, admin = await seed_users()
    from app import seed_extra

    await seed_extra.run(demo.id, admin.id if admin else None)
    from ai_agent.rag import seed_corpus

    async with session_scope() as db:
        docs = await seed_corpus(db)
    log.info("seed.rag_corpus", documents=docs)
    log.info("seed.done", demo=s.demo_user_email, admin=ADMIN_EMAIL)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
