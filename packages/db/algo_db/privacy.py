"""DPDP erasure: purge personal data after the deletion grace period.

Orders, trades and the audit trail are retained (linked to a pseudonymised account) because exchange / SEBI
record-keeping obligations take precedence over erasure (DPDP Act s.8(7) and s.17)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.timeutils import utcnow
from algo_db.audit import audit
from algo_db.models import (
    Alert,
    BrokerConnection,
    ChartLayout,
    ChatMessage,
    ChatSession,
    Notification,
    Screen,
    User,
    Watchlist,
)
from algo_db.models import Session as UserSession

DELETION_GRACE_DAYS = 7


async def purge_user(db: AsyncSession, user: User) -> dict[str, int]:
    uid = user.id
    counts: dict[str, int] = {}
    sessions = (await db.execute(select(ChatSession.id).where(ChatSession.user_id == uid))).scalars().all()
    stmts: list[tuple[str, Any]] = [
        ("chat_messages", ChatMessage.__table__.delete().where(ChatMessage.session_id.in_(sessions))),
        ("chats", ChatSession.__table__.delete().where(ChatSession.user_id == uid)),
        ("broker_connections", BrokerConnection.__table__.delete().where(BrokerConnection.user_id == uid)),
        ("notifications", Notification.__table__.delete().where(Notification.user_id == uid)),
        ("watchlists", Watchlist.__table__.delete().where(Watchlist.user_id == uid)),
        ("chart_layouts", ChartLayout.__table__.delete().where(ChartLayout.user_id == uid)),
        ("alerts", Alert.__table__.delete().where(Alert.user_id == uid)),
        ("screens", Screen.__table__.delete().where(Screen.user_id == uid)),
        ("sessions", UserSession.__table__.delete().where(UserSession.user_id == uid)),
    ]
    for name, stmt in stmts:
        counts[name] = (await db.execute(stmt)).rowcount or 0
    user.email = f"deleted-{uid}@deleted.invalid"
    user.full_name, user.phone, user.avatar_url, user.google_sub, user.password_hash = "", None, None, None, None
    user.pan_last4, user.notification_prefs, user.is_active, user.kyc_status = None, {}, False, "erased"
    await audit(db, "privacy.purged", user_id=uid, actor="system", payload=counts)
    return counts


async def purge_due(db: AsyncSession) -> int:
    cutoff = utcnow() - timedelta(days=DELETION_GRACE_DAYS)
    due = (await db.execute(select(User).where(User.deletion_requested_at.is_not(None), User.deletion_requested_at <= cutoff,
                                               User.is_active.is_(True)))).scalars().all()
    for u in due:
        await purge_user(db, u)
    return len(due)
