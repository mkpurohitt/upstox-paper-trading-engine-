"""Enqueue abstraction: arq when Redis + dedicated workers, asyncio task otherwise."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from algo_common.logging import get_logger
from algo_common.settings import get_settings
from algo_jobs.registry import JOBS, load_all

log = get_logger("jobs")
_pool: Any = None
_local_tasks: set[asyncio.Task[Any]] = set()


async def _arq_pool() -> Any:
    global _pool
    if _pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url or ""))
    return _pool


async def enqueue(name: str, **kwargs: Any) -> str:
    s = get_settings()
    job_id = uuid.uuid4().hex
    if s.redis_url and not s.embedded_workers:
        pool = await _arq_pool()
        await pool.enqueue_job(name, _job_id=job_id, **kwargs)
        return job_id
    load_all()
    fn = JOBS.get(name)
    if fn is None:
        raise KeyError(f"unknown job {name!r}")

    async def _run() -> None:
        try:
            await fn({"job_id": job_id, "local": True}, **kwargs)
        except Exception:
            log.exception("jobs.local_failed", job=name)

    task = asyncio.create_task(_run(), name=f"job:{name}:{job_id[:6]}")
    _local_tasks.add(task)
    task.add_done_callback(_local_tasks.discard)
    return job_id


async def drain(timeout: float = 30.0) -> None:
    """Wait for in-process jobs (tests)."""
    if _local_tasks:
        await asyncio.wait(list(_local_tasks), timeout=timeout)
