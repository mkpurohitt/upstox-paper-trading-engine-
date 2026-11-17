"""Broker connections: catalog, encrypted credential storage, OAuth / TOTP / token login."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from algo_common.kv import get_kv
from algo_common.settings import get_settings
from algo_db.audit import audit
from algo_db.models import BrokerConnection
from app.core.deps import DB, CurrentUser, client_ip
from app.schemas.common import Message
from app.schemas.trading import BrokerCatalogItem, ConnectionIn, ConnectionOut, FundsOut, LoginIn
from broker_gateway.adapters import ADAPTERS, catalog
from broker_gateway.base import BrokerError
from broker_gateway.connections import build_adapter, public_view, save_session, set_credentials

router = APIRouter(prefix="/api/brokers", tags=["brokers"])


def _redirect_uri(broker: str) -> str:
    s = get_settings()
    if broker == "upstox" and s.upstox_redirect_uri:
        return s.upstox_redirect_uri
    return f"{s.api_base_url}/api/brokers/{broker}/callback"


async def _owned(db: DB, user_id: int, conn_id: int) -> BrokerConnection:
    c = await db.get(BrokerConnection, conn_id)
    if c is None or c.user_id != user_id:
        raise HTTPException(404, "Connection not found")
    return c


@router.get("/catalog", response_model=list[BrokerCatalogItem])
async def broker_catalog(_: CurrentUser) -> list[dict[str, Any]]:
    return catalog()


@router.get("/connections", response_model=list[ConnectionOut])
async def connections(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.execute(select(BrokerConnection).where(BrokerConnection.user_id == user.id)
                             .order_by(BrokerConnection.id))).scalars().all()
    return [public_view(c) for c in rows]


@router.post("/connections", response_model=ConnectionOut, status_code=201)
async def add_connection(body: ConnectionIn, user: CurrentUser, db: DB, request: Request) -> dict[str, Any]:
    if body.broker not in ADAPTERS:
        raise HTTPException(422, f"Unsupported broker {body.broker}")
    conn = BrokerConnection(user_id=user.id, broker=body.broker, label=body.label or ADAPTERS[body.broker].display_name,
                            status="disconnected")
    db.add(conn)
    await db.flush()
    try:
        set_credentials(conn, body.credentials)
    except BrokerError as exc:
        raise HTTPException(422, exc.message)
    has_default = (await db.execute(select(BrokerConnection.id).where(BrokerConnection.user_id == user.id,
                                                                      BrokerConnection.is_default.is_(True)))).first()
    conn.is_default = not has_default
    await audit(db, "broker.connect_added", user_id=user.id, entity_type="broker_connection", entity_id=conn.id,
                payload={"broker": body.broker}, ip=client_ip(request))  # credentials are never audited
    return public_view(conn)


@router.get("/connections/{conn_id}/oauth-url")
async def oauth_url(conn_id: int, user: CurrentUser, db: DB) -> dict[str, str]:
    conn = await _owned(db, user.id, conn_id)
    adapter = build_adapter(conn)
    if adapter.auth_type != "oauth":
        raise HTTPException(400, f"{adapter.display_name} logs in with TOTP / token; use the login endpoint")
    state = secrets.token_urlsafe(24)
    await get_kv().set_json(f"oauth:broker:{state}", {"conn_id": conn.id, "user_id": user.id}, ttl=900)
    url = adapter.login_url(state, _redirect_uri(conn.broker))
    assert url
    return {"url": url, "redirect_uri": _redirect_uri(conn.broker)}


@router.get("/{broker}/callback", include_in_schema=False)
async def oauth_callback(broker: str, request: Request, db: DB) -> RedirectResponse:
    params = dict(request.query_params)
    state = params.get("state", "")
    web = get_settings().web_base_url
    ctx = await get_kv().get_json(f"oauth:broker:{state}") if state else None
    if ctx is None:
        return RedirectResponse(f"{web}/profile?tab=brokers&error=invalid_state")
    await get_kv().delete(f"oauth:broker:{state}")
    conn = await db.get(BrokerConnection, int(ctx["conn_id"]))
    if conn is None or conn.broker != broker or conn.user_id != ctx["user_id"]:
        return RedirectResponse(f"{web}/profile?tab=brokers&error=invalid_connection")
    adapter = build_adapter(conn)
    try:
        sess = await adapter.oauth_callback(params, _redirect_uri(broker))
        save_session(conn, sess)
        await audit(db, "broker.login", user_id=conn.user_id, entity_type="broker_connection", entity_id=conn.id,
                    payload={"broker": broker, "method": "oauth"})
        return RedirectResponse(f"{web}/profile?tab=brokers&connected={broker}")
    except BrokerError as exc:
        conn.status, conn.status_message = "error", exc.message[:500]
        return RedirectResponse(f"{web}/profile?tab=brokers&error=login_failed")
    finally:
        await adapter.close()


@router.post("/connections/{conn_id}/login", response_model=ConnectionOut)
async def login(conn_id: int, body: LoginIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    conn = await _owned(db, user.id, conn_id)
    adapter = build_adapter(conn)
    if adapter.auth_type == "oauth":
        raise HTTPException(400, "This broker uses OAuth - open the connect URL instead")
    try:
        sess = await adapter.login({"totp": body.totp} if body.totp else None)
        save_session(conn, sess)
        await audit(db, "broker.login", user_id=user.id, entity_type="broker_connection", entity_id=conn.id,
                    payload={"broker": conn.broker, "method": adapter.auth_type})
    except BrokerError as exc:
        conn.status, conn.status_message = "error", exc.message[:500]
        raise HTTPException(400, f"{adapter.display_name} login failed: {exc.message}")
    finally:
        await adapter.close()
    return public_view(conn)


@router.get("/connections/{conn_id}/funds", response_model=FundsOut)
async def funds(conn_id: int, user: CurrentUser, db: DB) -> FundsOut:
    conn = await _owned(db, user.id, conn_id)
    adapter = build_adapter(conn)
    try:
        f = await adapter.get_funds()
    except BrokerError as exc:
        raise HTTPException(502, exc.message)
    finally:
        await adapter.close()
    return FundsOut(**f.model_dump(), mode="live")


@router.post("/connections/{conn_id}/default", response_model=Message)
async def make_default(conn_id: int, user: CurrentUser, db: DB) -> Message:
    conn = await _owned(db, user.id, conn_id)
    for c in (await db.execute(select(BrokerConnection).where(BrokerConnection.user_id == user.id))).scalars():
        c.is_default = c.id == conn.id
    return Message(message=f"{conn.label} is now the default broker")


@router.delete("/connections/{conn_id}", response_model=Message)
async def disconnect(conn_id: int, user: CurrentUser, db: DB) -> Message:
    conn = await _owned(db, user.id, conn_id)
    from algo_db.models import Deployment

    live = (await db.execute(select(Deployment.id).where(Deployment.broker_connection_id == conn.id,
                                                         Deployment.status.in_(("running", "paused"))))).first()
    if live:
        raise HTTPException(409, "Stop deployments using this broker first")
    await db.delete(conn)
    await audit(db, "broker.disconnect", user_id=user.id, entity_type="broker_connection", entity_id=conn_id)
    return Message(message="Broker disconnected and credentials erased")
