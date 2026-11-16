"""Job registry. Job functions have the arq signature ``async def job(ctx, **kwargs)``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

JobFn = Callable[..., Awaitable[Any]]
JOBS: dict[str, JobFn] = {}
CRON: list[tuple[str, dict[str, Any]]] = []  # (job name, arq.cron kwargs)


def job(name: str | None = None) -> Callable[[JobFn], JobFn]:
    def deco(fn: JobFn) -> JobFn:
        JOBS[name or fn.__name__] = fn
        return fn

    return deco


def cron(job_name: str, **schedule: Any) -> None:
    CRON.append((job_name, schedule))


def load_all() -> dict[str, JobFn]:
    """Import every job module so decorators register."""
    import importlib

    for mod in ("backtests", "market", "rag", "news", "alerts"):
        try:
            importlib.import_module(f"algo_jobs.{mod}")
        except ModuleNotFoundError as exc:
            if exc.name != f"algo_jobs.{mod}":
                raise
    return JOBS
