"""arq worker entrypoint:  arq algo_jobs.worker.WorkerSettings"""

from __future__ import annotations

from typing import Any

from arq import cron as arq_cron
from arq.connections import RedisSettings

from algo_common.logging import configure_logging
from algo_common.settings import get_settings
from algo_jobs.registry import CRON, JOBS, load_all

_settings = get_settings()
configure_logging(_settings.log_level, _settings.log_json, service="worker")
load_all()


async def startup(ctx: dict[str, Any]) -> None:
    ctx["settings"] = _settings


async def shutdown(ctx: dict[str, Any]) -> None:
    from algo_db.session import dispose_engine

    await dispose_engine()


class WorkerSettings:
    functions = list(JOBS.values())
    cron_jobs = [arq_cron(JOBS[name], **sched) for name, sched in CRON if name in JOBS]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url or "redis://localhost:6379/0")
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 8
    job_timeout = 1800
    keep_result = 3600
