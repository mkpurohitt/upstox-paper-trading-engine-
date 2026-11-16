"""Copilot chats, RAG corpus and LLM usage accounting."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from algo_db.base import Base, BigIntId, Embedding, IdMixin, TimestampMixin, utcnow


class ChatSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    share_token: Mapped[str | None] = mapped_column(String(48), unique=True)
    context: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ChatMessage(IdMixin, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | tool
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list[Any]] = mapped_column(default=list)
    cards: Mapped[list[Any]] = mapped_column(default=list)
    citations: Mapped[list[Any]] = mapped_column(default=list)
    suggestions: Mapped[list[Any]] = mapped_column(default=list)
    model: Mapped[str | None] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RagDocument(IdMixin, Base):
    __tablename__ = "rag_documents"

    title: Mapped[str] = mapped_column(String(300))
    source_type: Mapped[str] = mapped_column(String(24), default="upload")
    source_url: Mapped[str | None] = mapped_column(String(1000))
    mime: Mapped[str] = mapped_column(String(64), default="text/plain")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_text: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    uploaded_by: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="SET NULL"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RagChunk(IdMixin, Base):
    __tablename__ = "rag_chunks"

    document_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("rag_documents.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding(384))
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LLMUsage(IdMixin, Base):
    __tablename__ = "llm_usage"

    user_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32), default="chat")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
