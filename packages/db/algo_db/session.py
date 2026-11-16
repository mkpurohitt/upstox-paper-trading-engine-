"""Async engine / session management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from algo_common.settings import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _make_engine(url: str) -> AsyncEngine:
    s = get_settings()
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        engine = create_async_engine(url, echo=s.db_echo, **kwargs)

        @event.listens_for(engine.sync_engine, "connect")
        def _fk_on(dbapi_conn, _):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    return create_async_engine(
        url, echo=s.db_echo, pool_size=s.db_pool_size, max_overflow=s.db_pool_size, pool_pre_ping=True
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _make_engine(get_settings().database_url)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _sessionmaker


def configure_engine(url: str) -> None:
    """Re-point the module level engine (used by tests and CLI scripts)."""
    global _engine, _sessionmaker
    _engine = _make_engine(url)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope: commit on success, rollback on error."""
    session = get_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def create_all() -> None:
    """Create tables directly from metadata (SQLite / dev-lite only; Postgres uses Alembic)."""
    from algo_db import models  # noqa: F401  (register models)
    from algo_db.base import Base

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
