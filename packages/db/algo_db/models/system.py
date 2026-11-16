"""Immutable audit log and system-wide flags (kill switch, feature flags)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from algo_db.base import Base, BigIntId, IdMixin, utcnow


class AuditLog(IdMixin, Base):
    """Append-only, hash-chained audit trail.

    `hash = sha256(prev_hash || canonical_json(entry))`. A Postgres trigger
    (migration 0002) rejects UPDATE/DELETE, and `verify_chain()` detects any
    tampering performed out-of-band.
    """

    __tablename__ = "audit_log"

    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(BigIntId, index=True)
    actor: Mapped[str] = mapped_column(String(16), default="user")  # user | system | admin | agent | runner
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64), default="0" * 64)
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class SystemFlag(Base):
    __tablename__ = "system_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_by: Mapped[int | None] = mapped_column(BigIntId)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
