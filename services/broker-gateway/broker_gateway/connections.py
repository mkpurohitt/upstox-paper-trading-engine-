"""Encrypted broker-connection storage (AES-256-GCM via algo_common.crypto.Vault).

Credentials and sessions are bound to their owner with associated data
``user:{id}:broker:{name}`` so a ciphertext copied to another row/user cannot be
decrypted. Plaintext secrets never leave this module except to adapters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.crypto import Vault, mask
from algo_common.timeutils import utcnow
from algo_db.models import BrokerConnection
from broker_gateway.adapters import adapter_class
from broker_gateway.base import BrokerAdapter, BrokerAuthError, BrokerError


def _aad(conn: BrokerConnection) -> str:
    return f"user:{conn.user_id}:broker:{conn.broker}"


def set_credentials(conn: BrokerConnection, creds: dict[str, Any]) -> None:
    cls = adapter_class(conn.broker)
    missing = [f.name for f in cls.credential_fields if f.required and not creds.get(f.name)]
    if missing:
        raise BrokerError(f"Missing credential fields: {', '.join(missing)}", code="validation_failed")
    allowed = {f.name for f in cls.credential_fields}
    clean = {k: str(v).strip() for k, v in creds.items() if k in allowed and v not in (None, "")}
    conn.credentials_enc = Vault.from_settings().encrypt_json(clean, aad=_aad(conn))
    conn.client_id = clean.get("client_id") or clean.get("user_id") or clean.get("api_key", "")[:6]


def credentials(conn: BrokerConnection) -> dict[str, Any]:
    if not conn.credentials_enc:
        return {}
    return Vault.from_settings().decrypt_json(conn.credentials_enc, aad=_aad(conn))


def session(conn: BrokerConnection) -> dict[str, Any]:
    if not conn.session_enc:
        return {}
    return Vault.from_settings().decrypt_json(conn.session_enc, aad=_aad(conn))


def save_session(conn: BrokerConnection, sess: dict[str, Any]) -> None:
    conn.session_enc = Vault.from_settings().encrypt_json(sess, aad=_aad(conn))
    conn.status, conn.status_message = "connected", None
    exp = sess.get("expires_at")
    conn.token_expires_at = datetime.fromisoformat(exp) if isinstance(exp, str) else None
    conn.last_synced_at = utcnow()


def is_expired(conn: BrokerConnection) -> bool:
    return conn.token_expires_at is not None and conn.token_expires_at <= utcnow()


def build_adapter(conn: BrokerConnection, transport: Any = None) -> BrokerAdapter:
    cls = adapter_class(conn.broker)
    kwargs: dict[str, Any] = {"credentials": credentials(conn), "session": session(conn)}
    if transport is not None:
        kwargs["transport"] = transport
    return cls(**kwargs)  # type: ignore[arg-type]


async def get_connection(db: AsyncSession, user_id: int, connection_id: int | None) -> BrokerConnection:
    q = select(BrokerConnection).where(BrokerConnection.user_id == user_id)
    q = q.where(BrokerConnection.id == connection_id) if connection_id else q.where(BrokerConnection.is_default.is_(True))
    conn = (await db.execute(q)).scalars().first()
    if conn is None:
        raise BrokerError("Broker connection not found", code="not_found")
    return conn


async def live_adapter(db: AsyncSession, user_id: int, connection_id: int | None) -> tuple[BrokerAdapter, BrokerConnection]:
    conn = await get_connection(db, user_id, connection_id)
    if conn.status != "connected" or is_expired(conn):
        conn.status = "expired" if is_expired(conn) else conn.status
        raise BrokerAuthError(f"{conn.broker} session is not active - reconnect from Profile -> Brokers")
    return build_adapter(conn), conn


def public_view(conn: BrokerConnection) -> dict[str, Any]:
    cls = adapter_class(conn.broker)
    return {
        "id": conn.id, "broker": conn.broker, "display_name": cls.display_name, "auth_type": cls.auth_type,
        "label": conn.label, "client_id": mask(conn.client_id, 3) if conn.client_id else "", "status":
        "expired" if conn.status == "connected" and is_expired(conn) else conn.status, "status_message": conn.status_message,
        "token_expires_at": conn.token_expires_at, "last_synced_at": conn.last_synced_at, "is_default": conn.is_default,
        "created_at": conn.created_at,
    }
