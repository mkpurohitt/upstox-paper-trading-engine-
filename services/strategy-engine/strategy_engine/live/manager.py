"""RunnerManager: owns one asyncio task per running deployment.

Control messages on the bus channel ``deploy:control``:
    {"action": "start" | "stop" | "pause" | "resume" | "squareoff", "deployment_id": 42}
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from sqlalchemy import select

from algo_common.bus import get_bus
from algo_common.kv import get_kv
from algo_common.logging import get_logger
from algo_common.metrics import ACTIVE_DEPLOYMENTS
from algo_common.timeutils import utcnow
from algo_db.models import Deployment
from algo_db.session import session_scope
from broker_gateway.router import OrderRouter
from market_data.base import MarketDataProvider
from strategy_engine.live.runner import StrategyRunner

log = get_logger("runner.manager")


class RunnerManager:
    def __init__(self, provider: MarketDataProvider | None = None) -> None:
        from market_data.registry import get_provider

        self.provider = provider or get_provider()
        self.router = OrderRouter(self.provider)
        self.runners: dict[int, StrategyRunner] = {}
        self.tasks: dict[int, asyncio.Task[None]] = {}

    async def start_deployment(self, deployment_id: int) -> None:
        if deployment_id in self.tasks and not self.tasks[deployment_id].done():
            return
        runner = StrategyRunner(deployment_id, self.provider, self.router)
        self.runners[deployment_id] = runner

        async def _run() -> None:
            try:
                await runner.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("runner.crashed", deployment=deployment_id)
                async with session_scope() as db:
                    d = await db.get(Deployment, deployment_id)
                    if d is not None:
                        d.status, d.error = "error", str(exc)[:1000]
                with contextlib.suppress(Exception):
                    await runner.log("error", f"Runner crashed: {exc}")

        self.tasks[deployment_id] = asyncio.create_task(_run(), name=f"runner:{deployment_id}")
        self._gauge()

    async def stop_deployment(self, deployment_id: int) -> None:
        t = self.tasks.pop(deployment_id, None)
        if t:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self.runners.pop(deployment_id, None)
        self._gauge()

    def _gauge(self) -> None:
        modes: dict[str, int] = {"paper": 0, "live": 0, "notify": 0}
        for r in self.runners.values():
            modes[r.mode] = modes.get(r.mode, 0) + 1
        for m, n in modes.items():
            ACTIVE_DEPLOYMENTS.labels(m).set(n)

    async def resume_all(self) -> None:
        async with session_scope() as db:
            ids = (await db.execute(select(Deployment.id).where(Deployment.status.in_(("running", "paused"))))).scalars().all()
        for i in ids:
            await self.start_deployment(i)
        log.info("runner.resumed", count=len(ids))

    async def _control(self) -> None:
        async for _, msg in get_bus().subscribe("deploy:control"):
            did = int(msg.get("deployment_id", 0))
            action = msg.get("action")
            try:
                if action == "start":
                    await self.start_deployment(did)
                elif action == "stop":
                    await self.stop_deployment(did)
                elif action in ("pause", "resume") and did in self.runners:
                    self.runners[did].paused = action == "pause"
                    await self.runners[did].log("info", f"Deployment {action}d")
            except Exception:
                log.exception("runner.control_failed", action=action, deployment=did)

    async def _demand(self) -> None:
        """Keep market-data subscriptions alive for every symbol a runner needs."""
        from market_data.streamer import get_streamer

        while True:
            syms: set[str] = set()
            for r in self.runners.values():
                syms |= r._tick_symbols
            streamer = get_streamer()
            if streamer is not None:
                streamer.pin(syms)
            elif syms:
                kv = get_kv()
                await kv.sadd("md:demand", *syms)
                for s in syms:
                    await kv.set(f"md:demand:hb:{s}", str(time.time()), ttl=90)
            await asyncio.sleep(20)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(30)
            async with session_scope() as db:
                for did in list(self.runners):
                    d = await db.get(Deployment, did)
                    if d is not None:
                        d.last_heartbeat = utcnow()
                    if d is None or d.status not in ("running", "paused"):
                        await self.stop_deployment(did)

    async def run(self) -> None:
        await self.resume_all()
        await asyncio.gather(self._control(), self._demand(), self._heartbeat())
