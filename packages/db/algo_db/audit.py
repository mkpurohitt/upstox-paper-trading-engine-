"""Hash-chained, append-only audit trail helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from algo_db.base import utcnow
from algo_db.models.system import AuditLog

GENESIS = "0" * 64


def _canonical(entry: dict[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(entry)).encode()).hexdigest()


def _entry_dict(
    ts: datetime, user_id: int | None, actor: str, action: str, entity_type: str | None,
    entity_id: str | None, payload: dict[str, Any],
) -> dict[str, Any]:
    if ts.tzinfo is None:  # SQLite drops tzinfo on round-trip
        ts = ts.replace(tzinfo=UTC)
    return {
        "ts": ts.astimezone(UTC).isoformat(),
        "user_id": user_id,
        "actor": actor,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
    }


async def audit(
    session: AsyncSession,
    action: str,
    *,
    user_id: int | None = None,
    actor: str = "user",
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    payload: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Append an audit entry inside the caller's transaction."""
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        # serialise chain appends across concurrent writers
        await session.execute(text("SELECT pg_advisory_xact_lock(4242424242)"))
    prev = (await session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))).scalar()
    prev_hash = prev or GENESIS
    ts = utcnow()
    payload = json.loads(_canonical(payload or {}))
    eid = None if entity_id is None else str(entity_id)
    entry = _entry_dict(ts, user_id, actor, action, entity_type, eid, payload)
    row = AuditLog(
        ts=ts, user_id=user_id, actor=actor, action=action, entity_type=entity_type, entity_id=eid,
        payload=payload, ip=ip, prev_hash=prev_hash, hash=compute_hash(prev_hash, entry),
    )
    session.add(row)
    await session.flush()
    return row


async def verify_chain(session: AsyncSession, limit: int | None = None) -> tuple[bool, int | None]:
    """Recompute the chain. Returns (ok, first_bad_id)."""
    q = select(AuditLog).order_by(AuditLog.id.asc())
    if limit:
        q = q.limit(limit)
    prev = GENESIS
    for row in (await session.execute(q)).scalars():
        entry = _entry_dict(row.ts, row.user_id, row.actor, row.action, row.entity_type, row.entity_id, row.payload)
        if row.prev_hash != prev or compute_hash(prev, entry) != row.hash:
            return False, row.id
        prev = row.hash
    return True, None
