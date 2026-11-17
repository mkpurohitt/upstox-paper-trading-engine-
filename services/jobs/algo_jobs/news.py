"""News ingestion: RSS feeds (or the offline generator), NSE announcements, AI summaries, sentiment, tickers."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from algo_common.logging import get_logger
from algo_common.settings import get_settings
from algo_common.timeutils import now_ist
from algo_db.models import NewsItem
from algo_db.session import session_scope
from algo_jobs.registry import cron, job
from market_data import news as news_mod

log = get_logger("jobs.news")
MAX_AI_SUMMARIES_PER_RUN = 8


async def _fetch_feed(client: httpx.AsyncClient, url: str) -> list[news_mod.Article]:
    try:
        r = await client.get(url)
        r.raise_for_status()
        source = httpx.URL(url).host.replace("www.", "").split(".")[0].title()
        return news_mod.parse_feed(r.content, source)
    except Exception as exc:
        log.warning("news.feed_failed", url=url, error=str(exc)[:200])
        return []


async def _announcements() -> list[news_mod.Article]:
    from market_data.nse_mcp import call_nse_tool

    try:
        res = await call_nse_tool("get_corporate_announcements", {"limit": 15})
    except Exception as exc:
        log.warning("news.announcements_failed", error=str(exc))
        return []
    rows = next((v for v in res.values() if isinstance(v, list)), []) if isinstance(res, dict) else []
    out = []
    for r in rows:
        title = r.get("subject") or r.get("title") or r.get("purpose") or ""
        sym = r.get("symbol")
        if not title:
            continue
        ts = now_ist()
        for k in ("date", "an_dt", "ts", "published_at"):
            if r.get(k):
                try:
                    ts = datetime.fromisoformat(str(r[k]))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=now_ist().tzinfo)
                except ValueError:
                    pass
                break
        stable = hashlib.sha1(f"{sym}|{title}|{ts.date()}".encode()).hexdigest()[:12]  # noqa: S324 (identifier, not security)
        url = r.get("url") or r.get("attachment") or f"https://www.nseindia.com/companies-listing/corporate-filings-announcements#{sym}-{stable}"
        a = news_mod.Article(source="NSE filings", url=str(url), title=f"{sym}: {title}" if sym else title,
                             summary=str(r.get("details") or r.get("description") or ""), published_at=ts, category="announcement",
                             tickers=[f"NSE:{sym}"] if sym else [])
        out.append(news_mod.enrich(a))
    return out


_lock = asyncio.Lock()  # one refresh at a time per process (scheduler vs. first-request population)


@job("refresh_news")
async def refresh_news(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    async with _lock:
        return await _refresh()


async def _refresh() -> dict[str, Any]:
    s = get_settings()
    articles: list[news_mod.Article] = []
    source = "rss"
    if s.data_mode == "live" and s.news_feed_list:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers={"User-Agent": "AlgoDeskNews/1.0"}) as client:
            for batch in await asyncio.gather(*(_fetch_feed(client, u) for u in s.news_feed_list)):
                articles += batch
    if not articles:
        articles = news_mod.mock_articles(None, 24)
        source = "sample"
    articles += await _announcements()

    from ai_agent.summaries import summarize

    added = summarised = 0
    async with session_scope() as db:
        urls = [a.url for a in articles]
        existing = set((await db.execute(select(NewsItem.url).where(NewsItem.url.in_(urls)))).scalars())
        for a in articles:
            if a.url in existing:
                continue
            existing.add(a.url)
            item = NewsItem(source=a.source[:80], url=a.url[:1000], title=a.title[:500], summary=a.summary[:4000], category=a.category,
                            published_at=a.published_at, sentiment=a.sentiment, sentiment_score=a.sentiment_score, tickers=a.tickers)
            if s.llm_configured and summarised < MAX_AI_SUMMARIES_PER_RUN and a.category != "announcement":
                sm = await summarize(a.title, a.summary)
                if sm.provider != "extractive":
                    item.ai_summary, item.sentiment, item.sentiment_score = sm.summary, sm.sentiment, sm.score
                    summarised += 1
            try:  # savepoint per row: a concurrent refresh may insert the same URL first
                async with db.begin_nested():
                    db.add(item)
                    await db.flush()
                added += 1
            except IntegrityError:
                pass
    log.info("news.refreshed", source=source, fetched=len(articles), added=added, ai_summaries=summarised)
    return {"source": source, "fetched": len(articles), "added": added, "ai_summaries": summarised}


cron("refresh_news", minute={0, 15, 30, 45})
