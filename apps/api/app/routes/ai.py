"""Copilot API: streaming chat (SSE + WebSocket), chat history, sharing, feedback, usage and status."""

from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from ai_agent.agent import TurnInput, run_turn
from ai_agent.llm import get_router
from ai_agent.rag.embedder import get_embedder
from algo_common.logging import get_logger
from algo_common.settings import get_settings
from algo_common.timeutils import utcnow
from algo_db.audit import audit
from algo_db.models import ChatMessage, ChatSession, LLMUsage, RagChunk, RagDocument
from algo_db.session import session_scope
from app.core.deps import DB, CurrentUser, client_ip
from app.schemas.common import Message
from app.services.quotas import enforce, plan_limits, usage
from app.ws.gateway import Client, manager

router = APIRouter(prefix="/api/ai", tags=["ai"])
log = get_logger("api.ai")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: int | None = None
    context: str | None = Field(default=None, max_length=8000, description="dashboard context from 'Ask AI'")


class SessionOut(BaseModel):
    id: int
    title: str
    pinned: bool
    shared: bool
    created_at: datetime
    updated_at: datetime
    preview: str | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    cards: list[Any] = []
    citations: list[Any] = []
    suggestions: list[Any] = []
    tool_calls: list[Any] = []
    model: str | None = None
    created_at: datetime


class SessionDetail(SessionOut):
    messages: list[MessageOut]
    share_token: str | None = None


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)


def _quota_for(user_id: int):  # type: ignore[no-untyped-def]
    async def check(kind: str) -> None:
        async with session_scope() as db:
            await enforce(db, user_id, kind)
    return check


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


@router.post("/chat", summary="Stream a copilot turn as Server-Sent Events")
async def chat(body: ChatIn, user: CurrentUser, db: DB) -> StreamingResponse:
    await enforce(db, user.id, "ai")
    if body.session_id is not None:
        s = await db.get(ChatSession, body.session_id)
        if s is None or s.user_id != user.id:
            raise HTTPException(404, "Chat not found")
    inp = TurnInput(user_id=user.id, role=user.role, text=body.message, session_id=body.session_id, context=body.context,
                    quota=_quota_for(user.id))

    async def gen() -> AsyncIterator[str]:
        try:
            async for ev in run_turn(inp):
                yield _sse(ev)
        except Exception as exc:
            log.exception("ai.chat_failed", user_id=user.id)
            yield _sse({"type": "error", "message": "Something went wrong while answering." if not isinstance(exc, PermissionError) else str(exc)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


async def ws_chat(client: Client, msg: dict[str, Any]) -> None:
    """WebSocket variant: {"type":"chat","message","session_id?","context?","request_id"} -> chat.event frames."""
    rid = msg.get("request_id")
    text = str(msg.get("message") or "")[:4000]
    if not text.strip():
        await client.send({"type": "chat.event", "request_id": rid, "event": {"type": "error", "message": "empty message"}})
        return
    try:
        async with session_scope() as db:
            await enforce(db, client.user_id, "ai")
    except HTTPException as exc:
        await client.send({"type": "chat.event", "request_id": rid, "event": {"type": "error", "message": exc.detail, "status": exc.status_code}})
        return
    inp = TurnInput(user_id=client.user_id, role=client.role, text=text, session_id=msg.get("session_id"),
                    context=(msg.get("context") or None), quota=_quota_for(client.user_id))
    try:
        async for ev in run_turn(inp):
            await client.send({"type": "chat.event", "request_id": rid, "event": ev})
    except PermissionError as exc:
        await client.send({"type": "chat.event", "request_id": rid, "event": {"type": "error", "message": str(exc)}})


manager.chat_handler = ws_chat


# ---------------------------------------------------------------- sessions


def _session_out(s: ChatSession, preview: str | None = None) -> SessionOut:
    return SessionOut(id=s.id, title=s.title, pinned=s.pinned, shared=bool(s.share_token), created_at=s.created_at,
                      updated_at=s.updated_at, preview=preview)


async def _owned(db: Any, user_id: int, session_id: int) -> ChatSession:
    s = await db.get(ChatSession, session_id)
    if s is None or s.user_id != user_id:
        raise HTTPException(404, "Chat not found")
    return s


def _msg_out(m: ChatMessage) -> MessageOut:
    return MessageOut(id=m.id, role=m.role, content=m.content, cards=m.cards or [], citations=m.citations or [],
                      suggestions=m.suggestions or [], tool_calls=[{"name": t.get("name"), "ok": t.get("ok")} for t in (m.tool_calls or [])],
                      model=m.model, created_at=m.created_at)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(user: CurrentUser, db: DB, q: str | None = None, limit: int = Query(50, le=200)) -> list[SessionOut]:
    stmt = select(ChatSession).where(ChatSession.user_id == user.id)
    if q:
        like = f"%{q.strip()[:80]}%"
        sub = select(ChatMessage.session_id).where(ChatMessage.content.ilike(like))
        stmt = stmt.where(or_(ChatSession.title.ilike(like), ChatSession.id.in_(sub)))
    rows = (await db.execute(stmt.order_by(ChatSession.pinned.desc(), ChatSession.updated_at.desc()).limit(limit))).scalars().all()
    return [_session_out(s) for s in rows]


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(user: CurrentUser, db: DB) -> SessionOut:
    s = ChatSession(user_id=user.id, title="New chat", context={})
    db.add(s)
    await db.flush()
    await db.refresh(s)
    return _session_out(s)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: int, user: CurrentUser, db: DB) -> SessionDetail:
    s = await _owned(db, user.id, session_id)
    msgs = (await db.execute(select(ChatMessage).where(ChatMessage.session_id == s.id).order_by(ChatMessage.id))).scalars().all()
    base = _session_out(s)
    return SessionDetail(**base.model_dump(), messages=[_msg_out(m) for m in msgs], share_token=s.share_token)


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def patch_session(session_id: int, body: SessionPatch, user: CurrentUser, db: DB) -> SessionOut:
    s = await _owned(db, user.id, session_id)
    if body.title is not None:
        s.title = body.title.strip()
    if body.pinned is not None:
        s.pinned = body.pinned
    await db.flush()
    return _session_out(s)


@router.delete("/sessions/{session_id}", response_model=Message)
async def delete_session(session_id: int, user: CurrentUser, db: DB) -> Message:
    s = await _owned(db, user.id, session_id)
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == s.id))
    await db.delete(s)
    return Message(message="Deleted")


class ShareOut(BaseModel):
    token: str
    path: str


@router.post("/sessions/{session_id}/share", response_model=ShareOut)
async def share_session(session_id: int, user: CurrentUser, db: DB) -> ShareOut:
    s = await _owned(db, user.id, session_id)
    if not s.share_token:
        s.share_token = secrets.token_urlsafe(24)
        await audit(db, "ai.chat_shared", user_id=user.id, entity_type="chat_session", entity_id=s.id)
    return ShareOut(token=s.share_token, path=f"/share/{s.share_token}")


@router.delete("/sessions/{session_id}/share", response_model=Message)
async def unshare_session(session_id: int, user: CurrentUser, db: DB) -> Message:
    s = await _owned(db, user.id, session_id)
    s.share_token = None
    return Message(message="Sharing disabled")


class SharedOut(BaseModel):
    title: str
    created_at: datetime
    messages: list[MessageOut]


@router.get("/shared/{token}", response_model=SharedOut, summary="Public read-only view of a shared chat")
async def shared(token: str, db: DB) -> SharedOut:
    if len(token) < 16:
        raise HTTPException(404, "Not found")
    s = (await db.execute(select(ChatSession).where(ChatSession.share_token == token))).scalars().first()
    if s is None:
        raise HTTPException(404, "Not found")
    msgs = (await db.execute(select(ChatMessage).where(ChatMessage.session_id == s.id, ChatMessage.role.in_(("user", "assistant")))
                             .order_by(ChatMessage.id))).scalars().all()
    out = []
    for m in msgs:
        mo = _msg_out(m)
        # never expose deploy/portfolio cards on public links
        mo.cards = [c for c in mo.cards if c.get("type") not in ("deploy_confirm", "portfolio", "portfolio_analysis")]
        out.append(mo)
    return SharedOut(title=s.title, created_at=s.created_at, messages=out)


@router.post("/messages/{message_id}/feedback", response_model=Message)
async def feedback(message_id: int, body: FeedbackIn, user: CurrentUser, db: DB, request: Request) -> Message:
    m = await db.get(ChatMessage, message_id)
    if m is None:
        raise HTTPException(404, "Message not found")
    s = await _owned(db, user.id, m.session_id)
    await audit(db, "ai.feedback", user_id=user.id, entity_type="chat_message", entity_id=m.id, ip=client_ip(request),
                payload={"session_id": s.id, "rating": body.rating, "comment": (body.comment or "")[:500], "model": m.model})
    return Message(message="Thanks for the feedback")


# ---------------------------------------------------------------- usage & status


class UsageDay(BaseModel):
    day: str
    queries: int
    tokens_in: int
    tokens_out: int
    cost_usd: float


class UsageOut(BaseModel):
    queries_today: int
    limit_per_day: int
    tokens_today: int
    cost_today_usd: float
    days: list[UsageDay]


@router.get("/usage", response_model=UsageOut)
async def ai_usage(user: CurrentUser, db: DB) -> UsageOut:
    lim = await plan_limits(db, user.id)
    used = await usage(db, user.id)
    since = utcnow() - timedelta(days=14)
    rows = (await db.execute(select(LLMUsage).where(LLMUsage.user_id == user.id, LLMUsage.created_at >= since))).scalars().all()
    by: dict[str, UsageDay] = {}
    for r in rows:
        d = r.created_at.date().isoformat()
        u = by.setdefault(d, UsageDay(day=d, queries=0, tokens_in=0, tokens_out=0, cost_usd=0.0))
        u.queries += 1
        u.tokens_in += r.tokens_in
        u.tokens_out += r.tokens_out
        u.cost_usd = round(u.cost_usd + r.cost_usd, 6)
    today = utcnow().date().isoformat()
    t = by.get(today)
    return UsageOut(queries_today=used["ai_queries_today"], limit_per_day=int(lim.get("ai_queries_per_day", 0)),
                    tokens_today=(t.tokens_in + t.tokens_out) if t else 0, cost_today_usd=t.cost_usd if t else 0.0,
                    days=sorted(by.values(), key=lambda x: x.day))


class StatusOut(BaseModel):
    llm_configured: bool
    providers: list[dict[str, Any]]
    embedding_provider: str
    advice_enabled: bool
    rag_documents: int
    rag_chunks: int
    queries_today: int
    limit_per_day: int


@router.get("/status", response_model=StatusOut)
async def ai_status(user: CurrentUser, db: DB) -> StatusOut:
    s = get_settings()
    docs = (await db.execute(select(func.count()).select_from(RagDocument).where(RagDocument.status == "ready"))).scalar_one()
    chunks = (await db.execute(select(func.count()).select_from(RagChunk))).scalar_one()
    lim = await plan_limits(db, user.id)
    used = await usage(db, user.id)
    return StatusOut(llm_configured=s.llm_configured, providers=get_router().status(), embedding_provider=get_embedder().name,
                     advice_enabled=s.advice_enabled, rag_documents=int(docs), rag_chunks=int(chunks),
                     queries_today=used["ai_queries_today"], limit_per_day=int(lim.get("ai_queries_per_day", 0)))
