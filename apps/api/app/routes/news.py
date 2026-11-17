"""News feed, AI summaries, sentiment, announcements and calendars."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, or_, select

from algo_common.logging import get_logger
from algo_common.timeutils import now_ist, utcnow
from algo_db.audit import audit
from algo_db.models import LLMUsage, NewsItem
from app.core.deps import DB, AdminUser, CurrentUser
from app.schemas.common import Message
from market_data import news as news_mod
from market_data.nse_mcp import call_nse_tool

router = APIRouter(prefix="/api/news", tags=["news"])
log = get_logger("api.news")


class NewsOut(BaseModel):
    id: int
    source: str
    url: str
    title: str
    summary: str
    ai_summary: str | None
    category: str
    published_at: datetime
    sentiment: str
    sentiment_score: float
    tickers: list[str]


def _out(n: NewsItem) -> NewsOut:
    return NewsOut(id=n.id, source=n.source, url=n.url, title=n.title, summary=n.summary, ai_summary=n.ai_summary, category=n.category,
                   published_at=n.published_at, sentiment=n.sentiment, sentiment_score=n.sentiment_score, tickers=list(n.tickers or []))


async def _ensure_feed(db: Any) -> None:
    """First request on an empty database populates the feed so the page is never blank."""
    from algo_jobs.news import _lock, refresh_news

    if _lock.locked():  # a scheduled refresh is running in this process: wait for it
        async with _lock:
            pass
    if (await db.execute(select(func.count()).select_from(NewsItem))).scalar_one() < 5:
        await db.commit()
        await refresh_news({})


@router.get("", response_model=list[NewsOut])
async def feed(_: CurrentUser, db: DB, category: Literal["news", "announcement", "results", "economy"] | None = None,
               sentiment: Literal["positive", "negative", "neutral"] | None = None, symbol: str | None = None,
               q: str | None = Query(None, max_length=100), before: datetime | None = None,
               limit: int = Query(40, ge=1, le=200)) -> list[NewsOut]:
    await _ensure_feed(db)
    stmt = select(NewsItem)
    if category:
        stmt = stmt.where(NewsItem.category == category)
    if sentiment:
        stmt = stmt.where(NewsItem.sentiment == sentiment)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(NewsItem.title.ilike(like), NewsItem.summary.ilike(like)))
    if before:
        stmt = stmt.where(NewsItem.published_at < before)
    rows = (await db.execute(stmt.order_by(desc(NewsItem.published_at)).limit(limit * (4 if symbol else 1)))).scalars().all()
    if symbol:
        sym = symbol.upper() if ":" in symbol else f"NSE:{symbol.upper()}"
        rows = [r for r in rows if sym in (r.tickers or [])][:limit]
    return [_out(r) for r in rows]


@router.get("/sentiment")
async def sentiment_overview(_: CurrentUser, db: DB, hours: int = Query(48, ge=1, le=24 * 14)) -> dict[str, Any]:
    await _ensure_feed(db)
    since = utcnow() - timedelta(hours=hours)
    rows = (await db.execute(select(NewsItem).where(NewsItem.published_at >= since))).scalars().all()
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    by_ticker: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        counts[r.sentiment] = counts.get(r.sentiment, 0) + 1
        for t in r.tickers or []:
            by_ticker[t].append(r.sentiment_score)
    tickers = sorted(({"symbol": t, "mentions": len(v), "avg_score": round(sum(v) / len(v), 3)} for t, v in by_ticker.items()),
                     key=lambda x: (-x["mentions"], -abs(x["avg_score"])))[:15]
    total = sum(counts.values()) or 1
    return {"hours": hours, "articles": len(rows), "counts": counts,
            "net_score": round((counts["positive"] - counts["negative"]) / total, 3), "tickers": tickers}


@router.get("/calendar")
async def calendar(_: CurrentUser, days: int = Query(30, ge=1, le=90)) -> dict[str, Any]:
    today = now_ist().date()
    results: list[Any] = []
    actions: list[Any] = []
    try:
        r = await call_nse_tool("get_results_calendar", {"days": min(days, 30)})
        results = next((v for v in r.values() if isinstance(v, list)), []) if isinstance(r, dict) else []
        a = await call_nse_tool("get_corporate_actions", {})
        actions = next((v for v in a.values() if isinstance(v, list)), []) if isinstance(a, dict) else []
    except Exception as exc:  # calendars are best-effort
        log.warning("news.calendar_partial", error=str(exc))
    return {"economic": news_mod.economic_calendar(today, days), "results": results[:40], "corporate_actions": actions[:40],
            "note": "Economic dates are an indicative schedule of recurring releases; confirm on official calendars."}


@router.get("/announcements")
async def announcements(_: CurrentUser, symbol: str | None = None, limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    args: dict[str, Any] = {"limit": limit}
    if symbol:
        args["symbol"] = symbol.split(":")[-1].upper()
    return await call_nse_tool("get_corporate_announcements", args)


@router.get("/{news_id}", response_model=NewsOut)
async def item(news_id: int, _: CurrentUser, db: DB) -> NewsOut:
    n = await db.get(NewsItem, news_id)
    if n is None:
        raise HTTPException(404, "Article not found")
    return _out(n)


@router.post("/{news_id}/summarize", response_model=NewsOut)
async def summarize_item(news_id: int, user: CurrentUser, db: DB) -> NewsOut:
    from ai_agent.summaries import summarize

    n = await db.get(NewsItem, news_id)
    if n is None:
        raise HTTPException(404, "Article not found")
    if not n.ai_summary:
        s = await summarize(n.title, n.content or n.summary)
        n.ai_summary = s.summary
        if s.provider != "extractive":
            n.sentiment, n.sentiment_score = s.sentiment, s.score
            db.add(LLMUsage(user_id=user.id, provider=s.provider, model="summary", purpose="news_summary",
                            tokens_in=s.tokens_in, tokens_out=s.tokens_out, cost_usd=s.cost_usd))
        await db.flush()
    return _out(n)


@router.post("/refresh", response_model=Message, status_code=202)
async def refresh(user: AdminUser, db: DB) -> Message:
    from algo_jobs.queue import enqueue

    await audit(db, "news.refresh", user_id=user.id, actor="admin")
    await enqueue("refresh_news")
    return Message(message="News refresh queued")
