"""Strategy runner service:  python -m strategy_engine.live.service

Hosts the RunnerManager (live / paper / notify deployments) and the paper
order matcher.
"""

from __future__ import annotations

import asyncio
import signal

from algo_common.logging import configure_logging
from algo_common.settings import get_settings
from broker_gateway.paper import PaperMatcher
from strategy_engine.live.manager import RunnerManager


async def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json, service="strategy-runner")
    from market_data.registry import init_provider_from_db, watch_provider_reloads

    await init_provider_from_db()
    manager = RunnerManager()
    tasks = [asyncio.create_task(manager.run(), name="runner-manager"),
             asyncio.create_task(PaperMatcher().run(), name="paper-matcher"),
             asyncio.create_task(watch_provider_reloads(), name="provider-watch")]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C raises KeyboardInterrupt instead
            pass
    await stop.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
