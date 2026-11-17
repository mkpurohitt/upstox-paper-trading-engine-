"""Embedded background runtime.

When `EMBEDDED_WORKERS=true` (default for `make dev-lite` and tests) the API
process also hosts the tick streamer, live strategy runners and periodic jobs,
so the whole product works with a single process and no Redis. In the Docker
deployment these run in the dedicated `market-data`, `strategy-runner` and
`worker` containers instead.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from algo_common.logging import get_logger
from algo_common.settings import get_settings

log = get_logger("runtime")

StartHook = Callable[[], Awaitable[None]]


class Runtime:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task[None]] = []
        self._stop_hooks: list[Callable[[], Awaitable[None]]] = []

    def spawn(self, name: str, coro: Awaitable[None]) -> None:
        async def _guard() -> None:
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("runtime.task_crashed", task=name)

        self._tasks.append(asyncio.create_task(_guard(), name=name))

    def on_stop(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._stop_hooks.append(hook)

    async def start(self) -> None:
        s = get_settings()
        from app.ws.gateway import manager

        manager.start()
        manager.backtest_owner = _backtest_owner
        self.on_stop(manager.stop)
        if not s.embedded_workers:
            log.info("runtime.embedded_workers_disabled")
            return
        from app import embedded

        await embedded.start(self)
        log.info("runtime.started", tasks=[t.get_name() for t in self._tasks])

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        for hook in reversed(self._stop_hooks):
            with contextlib.suppress(Exception):
                await hook()
        self._tasks.clear()


async def _backtest_owner(backtest_id: int) -> int | None:
    from algo_db.models import Backtest
    from algo_db.session import session_scope

    async with session_scope() as db:
        bt = await db.get(Backtest, backtest_id)
        return bt.user_id if bt else None


runtime = Runtime()
