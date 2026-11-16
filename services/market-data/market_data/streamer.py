"""Demand-driven live tick fan-out: provider stream -> bus `ticks:{symbol}`.

Demand comes from three places:
* WebSocket gateways (KV set `md:demand` + per-symbol heartbeat keys, and
  immediate `md:control` messages),
* in-process consumers such as strategy runners (`TickStreamer.pin()`),
* always-on symbols (index strip in the top bar).
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from algo_common.bus import Bus, get_bus
from algo_common.kv import KV, get_kv
from algo_common.logging import get_logger
from algo_common.metrics import TICKS_PUBLISHED
from market_data.base import MarketDataProvider

log = get_logger("streamer")

ALWAYS_ON = {"NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY", "BSE_INDEX:SENSEX", "NSE_INDEX:INDIAVIX"}
MAX_SYMBOLS = 3000


class TickStreamer:
    def __init__(self, provider: MarketDataProvider, bus: Bus | None = None, kv: KV | None = None) -> None:
        self.provider = provider
        self.bus = bus or get_bus()
        self.kv = kv or get_kv()
        self._demand: set[str] = set(ALWAYS_ON)
        self._pinned: dict[str, int] = {}
        self._last_publish: dict[str, float] = {}
        self.published = 0

    # ---- in-process demand (strategy runners) ------------------------------------------
    def pin(self, symbols: set[str] | list[str]) -> None:
        for s in symbols:
            self._pinned[s] = self._pinned.get(s, 0) + 1
            self._demand.add(s)

    def unpin(self, symbols: set[str] | list[str]) -> None:
        for s in symbols:
            n = self._pinned.get(s, 0) - 1
            if n <= 0:
                self._pinned.pop(s, None)
            else:
                self._pinned[s] = n

    def demand(self) -> set[str]:
        return self._demand

    async def _refresh_demand(self) -> None:
        while True:
            try:
                wanted = set(ALWAYS_ON) | set(self._pinned)
                remote = await self.kv.smembers("md:demand")
                dead = []
                for s in remote:
                    if await self.kv.get(f"md:demand:hb:{s}") is not None:
                        wanted.add(s)
                    else:
                        dead.append(s)
                if dead:
                    await self.kv.srem("md:demand", *dead)
                self._demand = set(sorted(wanted)[:MAX_SYMBOLS])
            except Exception as exc:
                log.warning("streamer.demand_refresh_failed", error=str(exc))
            await asyncio.sleep(2.0)

    async def _listen_control(self) -> None:
        async for _, msg in self.bus.subscribe("md:control"):
            if msg.get("action") == "subscribe":
                self._demand |= set(msg.get("symbols", []))

    async def run(self) -> None:
        tasks = [asyncio.create_task(self._refresh_demand()), asyncio.create_task(self._listen_control())]
        log.info("streamer.started", provider=self.provider.name)
        try:
            while True:
                try:
                    async for batch in self.provider.stream(self.demand):
                        now = time.monotonic()
                        for tick in batch:
                            await self.bus.publish(f"ticks:{tick.symbol}", tick.model_dump(mode="json"))
                            self._last_publish[tick.symbol] = now
                        self.published += len(batch)
                        TICKS_PUBLISHED.labels(self.provider.name).inc(len(batch))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("streamer.stream_error_restarting", error=str(exc))
                    await asyncio.sleep(2.0)
        finally:
            for t in tasks:
                t.cancel()
                with contextlib.suppress(BaseException):
                    await t


_streamer: TickStreamer | None = None


def get_streamer() -> TickStreamer | None:
    return _streamer


def set_streamer(s: TickStreamer | None) -> None:
    global _streamer
    _streamer = s
