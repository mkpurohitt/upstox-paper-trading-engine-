"""Knowledge-base jobs: bulk re-index (e.g. after switching embedding provider) and background URL ingestion."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from algo_common.logging import get_logger
from algo_db.models import RagDocument
from algo_db.session import session_scope
from algo_jobs.registry import job

log = get_logger("jobs.rag")


@job("rag_reindex_all")
async def rag_reindex_all(ctx: dict[str, Any]) -> dict[str, Any]:
    from ai_agent.rag import reindex

    async with session_scope() as db:
        ids = list((await db.execute(select(RagDocument.id))).scalars())
    done, failed = 0, 0
    for doc_id in ids:
        try:
            async with session_scope() as db:
                await reindex(db, doc_id)
            done += 1
        except Exception as exc:  # keep going; the document is marked status=error
            failed += 1
            log.warning("rag.reindex_failed", document_id=doc_id, error=str(exc))
    log.info("rag.reindex_all", done=done, failed=failed)
    return {"reindexed": done, "failed": failed}


@job("rag_ingest_url")
async def rag_ingest_url(ctx: dict[str, Any], url: str, title: str | None = None, user_id: int | None = None) -> dict[str, Any]:
    from ai_agent.rag import fetch_url, ingest_text

    t, text, mime = await fetch_url(url)
    async with session_scope() as db:
        d = await ingest_text(db, title=title or t, text=text, source_type="url", source_url=url, mime=mime, uploaded_by=user_id)
        return {"document_id": d.id, "chunks": d.chunk_count}
