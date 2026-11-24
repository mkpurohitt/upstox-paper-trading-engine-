"""Background services hosted inside the API process when EMBEDDED_WORKERS=true."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from algo_common.logging import get_logger

if TYPE_CHECKING:
    from app.runtime import Runtime

log = get_logger("embedded")


async def start(rt: Runtime) -> None:
    from market_data.registry import get_provider
    from market_data.streamer import TickStreamer, set_streamer

    provider = get_provider()
    # warm instrument master / mock history off the event loop
    rt.spawn("md-warmup", provider.instruments())
    streamer = TickStreamer(provider)
    set_streamer(streamer)
    rt.spawn("tick-streamer", streamer.run())

    from broker_gateway.paper import PaperMatcher
    from strategy_engine.live.manager import RunnerManager

    rt.spawn("paper-matcher", PaperMatcher(provider).run())
    rt.spawn("runner-manager", RunnerManager(provider).run())
    rt.spawn("scheduler", _scheduler())
    from algo_jobs.price_alerts import run_forever

    rt.spawn("price-alerts", run_forever())


async def _scheduler() -> None:
    """In-process stand-in for arq cron jobs (screen alerts, news refresh...)."""
    from algo_jobs.registry import JOBS, load_all

    load_all()
    every = {"run_screen_alerts": 300, "refresh_news": 900, "purge_deleted_accounts": 6 * 3600}
    last: dict[str, float] = {}
    loop = asyncio.get_running_loop()
    while True:
        for name, period in every.items():
            fn = JOBS.get(name)
            if fn and loop.time() - last.get(name, -1e9) >= period:
                last[name] = loop.time()
                try:
                    await fn({"embedded": True})
                except Exception:
                    log.exception("scheduler.job_failed", job=name)
        await asyncio.sleep(30)
    await asyncio.sleep(0)
