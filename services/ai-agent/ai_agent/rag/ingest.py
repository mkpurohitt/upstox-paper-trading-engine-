"""Document ingestion: extract -> semantic chunks -> embeddings -> rag_chunks."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.rag.embedder import get_embedder
from ai_agent.rag.retriever import bump_version
from ai_agent.rag.text import semantic_chunks
from algo_common.logging import get_logger
from algo_common.timeutils import utcnow
from algo_db.models import RagChunk, RagDocument

log = get_logger("ai.rag.ingest")
MAX_BYTES = 10 * 1024 * 1024
CORPUS_DIR = Path(__file__).parent / "corpus"
INDEX_VERSION = 3  # bump when chunking / tokenisation / embedding changes; outdated documents are re-indexed on startup


class IngestError(ValueError):
    pass


def extract_text(filename: str, data: bytes, mime: str | None = None) -> tuple[str, str, str]:
    """Return (title, text, mime) for PDF, HTML, Markdown or plain-text uploads."""
    if len(data) > MAX_BYTES:
        raise IngestError("file too large (max 10 MB)")
    name = filename.lower()
    if name.endswith(".pdf") or mime == "application/pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [p.extract_text() or "" for p in reader.pages]
        except Exception as exc:
            raise IngestError(f"could not read PDF: {exc}") from exc
        text = "\n\n".join(f"## Page {i + 1}\n{p.strip()}" for i, p in enumerate(pages) if p.strip())
        title = (reader.metadata.title if reader.metadata and reader.metadata.title else None) or Path(filename).stem
        return str(title), text, "application/pdf"
    raw = data.decode("utf-8", errors="replace")
    if name.endswith((".html", ".htm")) or (mime or "").startswith("text/html"):
        return html_to_text(raw, Path(filename).stem)
    if name.endswith((".md", ".markdown")):
        m = re.search(r"^#\s+(.+)$", raw, flags=re.M)
        return (m.group(1).strip() if m else Path(filename).stem), raw, "text/markdown"
    if name.endswith((".txt", ".csv", ".json")) or (mime or "").startswith("text/"):
        return Path(filename).stem, raw, "text/plain"
    raise IngestError("unsupported file type (PDF, HTML, Markdown or text)")


def html_to_text(html: str, fallback_title: str = "Web page") -> tuple[str, str, str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else fallback_title
    lines: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td"]):
        t = el.get_text(" ", strip=True)
        if not t:
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            lines.append("\n" + "#" * int(el.name[1]) + " " + t)
        elif el.name == "li":
            lines.append("- " + t)
        else:
            lines.append(t)
    return title, "\n\n".join(lines), "text/html"


async def ingest_text(db: AsyncSession, *, title: str, text: str, source_type: str = "upload", source_url: str | None = None,
                      mime: str = "text/markdown", meta: dict[str, Any] | None = None, uploaded_by: int | None = None) -> RagDocument:
    text = (text or "").strip()
    if len(text) < 20:
        raise IngestError("document has no extractable text")
    digest = hashlib.sha256(text.encode()).hexdigest()
    existing = (await db.execute(select(RagDocument).where(RagDocument.content_hash == digest, RagDocument.status == "ready"))).scalars().first()
    if existing is not None:
        return existing
    doc = RagDocument(title=title[:300], source_type=source_type, source_url=source_url, mime=mime, status="indexing",
                      content_hash=digest, raw_text=text, meta=meta or {}, uploaded_by=uploaded_by)
    db.add(doc)
    await db.flush()
    await _index_document(db, doc)
    return doc


async def _index_document(db: AsyncSession, doc: RagDocument) -> None:
    try:
        chunks = semantic_chunks(doc.raw_text or "", title=doc.title)
        embs = await get_embedder().embed([c.content for c in chunks])
        await db.execute(delete(RagChunk).where(RagChunk.document_id == doc.id))
        for c, e in zip(chunks, embs, strict=True):
            db.add(RagChunk(document_id=doc.id, ordinal=c.meta["ordinal"], content=c.content, token_count=c.token_count,
                            embedding=e, meta=c.meta))
        doc.status, doc.chunk_count, doc.indexed_at, doc.error = "ready", len(chunks), utcnow(), None
        doc.meta = {**(doc.meta or {}), "index_version": INDEX_VERSION, "embedder": get_embedder().name}
        await db.flush()
        await bump_version()
        log.info("rag.indexed", document_id=doc.id, chunks=len(chunks))
    except Exception as exc:
        doc.status, doc.error = "error", str(exc)[:500]
        await db.flush()
        log.exception("rag.index_failed", document_id=doc.id)
        raise IngestError(f"indexing failed: {exc}") from exc


async def reindex(db: AsyncSession, document_id: int) -> RagDocument:
    doc = await db.get(RagDocument, document_id)
    if doc is None:
        raise IngestError("document not found")
    doc.status = "indexing"
    await _index_document(db, doc)
    return doc


async def delete_document(db: AsyncSession, document_id: int) -> bool:
    doc = await db.get(RagDocument, document_id)
    if doc is None:
        return False
    await db.execute(delete(RagChunk).where(RagChunk.document_id == document_id))
    await db.delete(doc)
    await db.flush()
    await bump_version()
    return True


async def fetch_url(url: str) -> tuple[str, str, str]:
    if not re.match(r"^https?://", url):
        raise IngestError("URL must start with http:// or https://")
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "AlgoDeskRAG/1.0"}) as c:
        r = await c.get(url)
        r.raise_for_status()
        if len(r.content) > MAX_BYTES:
            raise IngestError("page too large")
        ctype = r.headers.get("content-type", "")
    if "pdf" in ctype:
        return extract_text("download.pdf", r.content, "application/pdf")
    if "html" in ctype:
        return html_to_text(r.text, url)
    return url, r.text, "text/plain"


async def seed_corpus(db: AsyncSession) -> int:
    """Index the bundled knowledge base (idempotent: skips documents whose title already exists)."""
    have = set((await db.execute(select(RagDocument.title).where(RagDocument.source_type == "seed"))).scalars())
    stale = [d for d in (await db.execute(select(RagDocument).where(RagDocument.status == "ready"))).scalars()
             if (d.meta or {}).get("index_version") != INDEX_VERSION or (d.meta or {}).get("embedder") != get_embedder().name]
    for d in stale:
        await _index_document(db, d)
    added = 0
    for path in sorted(CORPUS_DIR.glob("*.md")):
        title, text, mime = extract_text(path.name, path.read_bytes())
        if title in have:
            continue
        await ingest_text(db, title=title, text=text, source_type="seed", mime=mime, meta={"file": path.name})
        added += 1
    return added


async def corpus_size(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(RagChunk))).scalar_one())
