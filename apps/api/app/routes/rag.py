"""Knowledge base (RAG) management: admin uploads/URLs/text, re-index, delete; search for any signed-in user."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from ai_agent.rag import IngestError, delete_document, extract_text, fetch_url, ingest_text, reindex, search
from algo_db.audit import audit
from algo_db.models import RagChunk, RagDocument
from app.core.deps import DB, AdminUser, CurrentUser
from app.schemas.common import Message

router = APIRouter(prefix="/api/rag", tags=["rag"])


class DocumentOut(BaseModel):
    id: int
    title: str
    source_type: str
    source_url: str | None
    mime: str
    status: str
    chunk_count: int
    error: str | None
    created_at: datetime
    indexed_at: datetime | None


def _doc(d: RagDocument) -> DocumentOut:
    return DocumentOut(id=d.id, title=d.title, source_type=d.source_type, source_url=d.source_url, mime=d.mime, status=d.status,
                       chunk_count=d.chunk_count, error=d.error, created_at=d.created_at, indexed_at=d.indexed_at)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(_: AdminUser, db: DB) -> list[DocumentOut]:
    rows = (await db.execute(select(RagDocument).order_by(RagDocument.id.desc()))).scalars().all()
    return [_doc(d) for d in rows]


@router.post("/documents/upload", response_model=DocumentOut, status_code=201)
async def upload(user: AdminUser, db: DB, file: UploadFile = File(...), title: str | None = Form(None)) -> DocumentOut:
    data = await file.read()
    try:
        t, text, mime = extract_text(file.filename or "upload.txt", data, file.content_type)
        d = await ingest_text(db, title=title or t, text=text, source_type="upload", mime=mime, uploaded_by=user.id,
                              meta={"filename": file.filename, "bytes": len(data)})
    except IngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit(db, "rag.upload", user_id=user.id, actor="admin", entity_type="rag_document", entity_id=d.id,
                payload={"title": d.title, "chunks": d.chunk_count})
    return _doc(d)


class UrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    title: str | None = None


@router.post("/documents/url", response_model=DocumentOut, status_code=201)
async def add_url(body: UrlIn, user: AdminUser, db: DB) -> DocumentOut:
    try:
        t, text, mime = await fetch_url(body.url)
        d = await ingest_text(db, title=body.title or t, text=text, source_type="url", source_url=body.url, mime=mime, uploaded_by=user.id)
    except IngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"could not fetch URL: {exc.__class__.__name__}") from exc
    await audit(db, "rag.url", user_id=user.id, actor="admin", entity_type="rag_document", entity_id=d.id, payload={"url": body.url})
    return _doc(d)


class TextIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=20, max_length=2_000_000)


@router.post("/documents/text", response_model=DocumentOut, status_code=201)
async def add_text(body: TextIn, user: AdminUser, db: DB) -> DocumentOut:
    try:
        d = await ingest_text(db, title=body.title, text=body.text, source_type="text", uploaded_by=user.id)
    except IngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit(db, "rag.text", user_id=user.id, actor="admin", entity_type="rag_document", entity_id=d.id, payload={"title": d.title})
    return _doc(d)


@router.post("/documents/{doc_id}/reindex", response_model=DocumentOut)
async def reindex_doc(doc_id: int, user: AdminUser, db: DB) -> DocumentOut:
    try:
        d = await reindex(db, doc_id)
    except IngestError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 422, str(exc)) from exc
    await audit(db, "rag.reindex", user_id=user.id, actor="admin", entity_type="rag_document", entity_id=doc_id)
    return _doc(d)


@router.delete("/documents/{doc_id}", response_model=Message)
async def remove(doc_id: int, user: AdminUser, db: DB) -> Message:
    if not await delete_document(db, doc_id):
        raise HTTPException(404, "Document not found")
    await audit(db, "rag.delete", user_id=user.id, actor="admin", entity_type="rag_document", entity_id=doc_id)
    return Message(message="Deleted")


class ChunkOut(BaseModel):
    id: int
    ordinal: int
    token_count: int
    content: str
    meta: dict[str, Any]


@router.get("/documents/{doc_id}/chunks", response_model=list[ChunkOut])
async def chunks(doc_id: int, _: AdminUser, db: DB) -> list[ChunkOut]:
    rows = (await db.execute(select(RagChunk).where(RagChunk.document_id == doc_id).order_by(RagChunk.ordinal))).scalars().all()
    return [ChunkOut(id=c.id, ordinal=c.ordinal, token_count=c.token_count, content=c.content, meta=c.meta or {}) for c in rows]


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(default=5, ge=1, le=20)


class HitOut(BaseModel):
    n: int
    chunk_id: int
    document_id: int
    title: str
    heading: str | None
    source_url: str | None
    source_type: str
    snippet: str
    score: float


@router.post("/search", response_model=list[HitOut])
async def search_kb(body: SearchIn, _: CurrentUser, db: DB) -> list[HitOut]:
    hits = await search(db, body.query, body.k)
    return [HitOut(**h.citation()) for h in hits]
