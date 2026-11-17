"""Account & privacy (DPDP Act 2023): consents ledger, data export, deletion with a grace period, KYC placeholder,
and in-app notifications."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, update

from algo_common.timeutils import utcnow
from algo_db.audit import audit
from algo_db.models import (
    AuditLog,
    Backtest,
    BrokerConnection,
    ChatMessage,
    ChatSession,
    Consent,
    Deployment,
    LLMUsage,
    Notification,
    Order,
    Screen,
    Strategy,
    StrategyVersion,
    Trade,
    Watchlist,
)
from algo_db.models import Session as UserSession
from algo_db.privacy import DELETION_GRACE_DAYS
from app.core.deps import DB, CurrentUser, client_ip
from app.schemas.common import Message

router = APIRouter(tags=["account"])

REQUIRED_PURPOSES = {"terms", "privacy", "data_processing"}
OPTIONAL_PURPOSES = {"marketing", "analytics", "ai_personalisation"}
PURPOSE_TEXT = {
    "terms": "Terms of service",
    "privacy": "Privacy notice",
    "data_processing": "Processing of account and trading data to provide the service (required)",
    "marketing": "Product updates and offers by email",
    "analytics": "Anonymous usage analytics to improve the product",
    "ai_personalisation": "Use my chat history to personalise copilot answers",
}


# ---------------------------------------------------------------- consents


class ConsentState(BaseModel):
    purpose: str
    description: str
    required: bool
    granted: bool
    version: str
    updated_at: datetime | None


class ConsentLedgerRow(BaseModel):
    purpose: str
    granted: bool
    version: str
    created_at: datetime


class ConsentsOut(BaseModel):
    current: list[ConsentState]
    ledger: list[ConsentLedgerRow]


@router.get("/api/account/consents", response_model=ConsentsOut)
async def consents(user: CurrentUser, db: DB) -> ConsentsOut:
    rows = (await db.execute(select(Consent).where(Consent.user_id == user.id).order_by(Consent.id))).scalars().all()
    latest: dict[str, Consent] = {}
    for r in rows:
        latest[r.purpose] = r
    current = [ConsentState(purpose=p, description=PURPOSE_TEXT[p], required=p in REQUIRED_PURPOSES,
                            granted=latest[p].granted if p in latest else False, version=latest[p].version if p in latest else "1.0",
                            updated_at=latest[p].created_at if p in latest else None)
               for p in [*sorted(REQUIRED_PURPOSES), *sorted(OPTIONAL_PURPOSES)]]
    return ConsentsOut(current=current, ledger=[ConsentLedgerRow(purpose=r.purpose, granted=r.granted, version=r.version,
                                                                 created_at=r.created_at) for r in reversed(rows)][:100])


class ConsentIn(BaseModel):
    purpose: str
    granted: bool


@router.post("/api/account/consents", response_model=ConsentsOut)
async def set_consent(body: ConsentIn, user: CurrentUser, db: DB, request: Request) -> ConsentsOut:
    if body.purpose not in OPTIONAL_PURPOSES:
        raise HTTPException(422, "Required consents can only be withdrawn by deleting the account")
    db.add(Consent(user_id=user.id, purpose=body.purpose, granted=body.granted, ip=client_ip(request)))
    await audit(db, "privacy.consent", user_id=user.id, ip=client_ip(request), payload={"purpose": body.purpose, "granted": body.granted})
    await db.flush()
    return await consents(user, db)


# ---------------------------------------------------------------- export


def _row(o: Any, exclude: set[str] = frozenset()) -> dict[str, Any]:  # type: ignore[assignment]
    return {c.key: getattr(o, c.key) for c in o.__table__.columns if c.key not in exclude}


@router.get("/api/account/export", summary="Download all personal data (DPDP right to access)")
async def export(user: CurrentUser, db: DB, request: Request) -> JSONResponse:
    uid = user.id

    async def rows(model: Any, *where: Any, exclude: set[str] = frozenset(), limit: int = 50_000) -> list[dict[str, Any]]:  # type: ignore[assignment]
        return [_row(r, exclude) for r in (await db.execute(select(model).where(*where).limit(limit))).scalars()]

    sessions = (await db.execute(select(ChatSession.id).where(ChatSession.user_id == uid))).scalars().all()
    strategies = (await db.execute(select(Strategy.id).where(Strategy.user_id == uid))).scalars().all()
    data = {
        "exported_at": utcnow().isoformat(),
        "format": "AlgoDesk personal data export v1",
        "profile": _row(user, {"password_hash"}),
        "consents": await rows(Consent, Consent.user_id == uid),
        "sessions": await rows(UserSession, UserSession.user_id == uid, exclude={"refresh_token_hash"}),
        "broker_connections": await rows(BrokerConnection, BrokerConnection.user_id == uid, exclude={"credentials_enc", "session_enc"}),
        "strategies": await rows(Strategy, Strategy.user_id == uid),
        "strategy_versions": await rows(StrategyVersion, StrategyVersion.strategy_id.in_(strategies)) if strategies else [],
        "backtests": await rows(Backtest, Backtest.user_id == uid, exclude={"equity_curve", "drawdown_curve"}),
        "deployments": await rows(Deployment, Deployment.user_id == uid),
        "orders": await rows(Order, Order.user_id == uid),
        "trades": await rows(Trade, Trade.user_id == uid),
        "chats": await rows(ChatSession, ChatSession.user_id == uid),
        "chat_messages": await rows(ChatMessage, ChatMessage.session_id.in_(sessions)) if sessions else [],
        "watchlists": await rows(Watchlist, Watchlist.user_id == uid),
        "screens": await rows(Screen, Screen.user_id == uid),
        "notifications": await rows(Notification, Notification.user_id == uid),
        "llm_usage": await rows(LLMUsage, LLMUsage.user_id == uid),
        "audit_log": await rows(AuditLog, AuditLog.user_id == uid, exclude={"prev_hash", "hash"}, limit=20_000),
    }
    await audit(db, "privacy.export", user_id=uid, ip=client_ip(request), payload={k: len(v) for k, v in data.items() if isinstance(v, list)})
    import json

    body = json.loads(json.dumps(data, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o)))
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="algodesk-export-{uid}.json"'})


# ---------------------------------------------------------------- deletion


class DeleteIn(BaseModel):
    confirm_email: str
    reason: str | None = Field(default=None, max_length=500)


class DeletionOut(BaseModel):
    deletion_requested_at: datetime | None
    purge_after: datetime | None
    message: str


@router.post("/api/account/delete", response_model=DeletionOut)
async def request_deletion(body: DeleteIn, user: CurrentUser, db: DB, request: Request) -> DeletionOut:
    if body.confirm_email.strip().lower() != user.email.lower():
        raise HTTPException(422, "Type your account email to confirm")
    from broker_gateway.killswitch import engage_user

    summary = await engage_user(db, user, square_off=True, actor="user", ip=client_ip(request))  # stop all trading first
    user.deletion_requested_at = utcnow()
    db.add(Consent(user_id=user.id, purpose="data_processing", granted=False, ip=client_ip(request)))
    await audit(db, "privacy.deletion_requested", user_id=user.id, ip=client_ip(request),
                payload={"reason": (body.reason or "")[:200], "trading_halted": summary})
    purge = user.deletion_requested_at + timedelta(days=DELETION_GRACE_DAYS)
    return DeletionOut(deletion_requested_at=user.deletion_requested_at, purge_after=purge,
                       message=f"Trading halted. Your personal data will be erased on {purge.date()} unless you cancel before then.")


@router.post("/api/account/delete/cancel", response_model=DeletionOut)
async def cancel_deletion(user: CurrentUser, db: DB, request: Request) -> DeletionOut:
    if user.deletion_requested_at is None:
        raise HTTPException(400, "No deletion pending")
    user.deletion_requested_at = None
    db.add(Consent(user_id=user.id, purpose="data_processing", granted=True, ip=client_ip(request)))
    await audit(db, "privacy.deletion_cancelled", user_id=user.id, ip=client_ip(request))
    return DeletionOut(deletion_requested_at=None, purge_after=None,
                       message="Deletion cancelled. Your kill switch is still engaged; release it from the top bar when ready.")


# ---------------------------------------------------------------- KYC (placeholder)


class KycIn(BaseModel):
    pan: str = Field(min_length=10, max_length=10)
    name_on_pan: str = Field(min_length=2, max_length=120)


class KycOut(BaseModel):
    status: str
    pan_last4: str | None
    note: str


@router.get("/api/account/kyc", response_model=KycOut)
async def kyc_status(user: CurrentUser) -> KycOut:
    return KycOut(status=user.kyc_status, pan_last4=user.pan_last4,
                  note="KYC is a placeholder: live trading KYC is performed by your broker; we store only the last 4 characters of PAN.")


@router.post("/api/account/kyc", response_model=KycOut)
async def submit_kyc(body: KycIn, user: CurrentUser, db: DB, request: Request) -> KycOut:
    pan = body.pan.upper()
    if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan):
        raise HTTPException(422, "Invalid PAN format")
    user.pan_last4, user.kyc_status = pan[-4:], "submitted"
    await audit(db, "kyc.submitted", user_id=user.id, ip=client_ip(request), payload={"pan_last4": pan[-4:]})  # never the full PAN
    return await kyc_status(user)


# ---------------------------------------------------------------- notifications


class NotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    data: dict[str, Any]
    channels_sent: list[Any]
    read_at: datetime | None
    created_at: datetime


class NotificationsOut(BaseModel):
    unread: int
    items: list[NotificationOut]


@router.get("/api/notifications", response_model=NotificationsOut)
async def notifications(user: CurrentUser, db: DB, unread_only: bool = False, limit: int = Query(30, le=200)) -> NotificationsOut:
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = (await db.execute(q.order_by(desc(Notification.id)).limit(limit))).scalars().all()
    unread = len((await db.execute(select(Notification.id).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                                   .limit(1000))).all())
    return NotificationsOut(unread=unread, items=[NotificationOut(id=n.id, kind=n.kind, title=n.title, body=n.body, data=n.data or {},
                                                                  channels_sent=n.channels_sent or [], read_at=n.read_at, created_at=n.created_at)
                                                  for n in rows])


@router.post("/api/notifications/{notification_id}/read", response_model=Message)
async def mark_read(notification_id: int, user: CurrentUser, db: DB) -> Message:
    await db.execute(update(Notification).where(Notification.id == notification_id, Notification.user_id == user.id,
                                                Notification.read_at.is_(None)).values(read_at=utcnow()))
    return Message(message="ok")


@router.post("/api/notifications/read-all", response_model=Message)
async def mark_all_read(user: CurrentUser, db: DB) -> Message:
    await db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    return Message(message="ok")


class TestIn(BaseModel):
    channels: list[Literal["in_app", "email", "telegram", "whatsapp"]] = Field(default_factory=lambda: ["in_app"])


@router.post("/api/notifications/test", response_model=NotificationOut)
async def test_notification(body: TestIn, user: CurrentUser, db: DB) -> NotificationOut:
    from broker_gateway.notify import notify

    n = await notify(db, user.id, "Test notification", "If you can read this, alerts for this channel are working.", kind="system",
                     channels=[c for c in body.channels if c != "in_app"])
    return NotificationOut(id=n.id, kind=n.kind, title=n.title, body=n.body, data=n.data or {}, channels_sent=n.channels_sent or [],
                           read_at=n.read_at, created_at=n.created_at)
