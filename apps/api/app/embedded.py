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
    await asyncio.sleep(0)
