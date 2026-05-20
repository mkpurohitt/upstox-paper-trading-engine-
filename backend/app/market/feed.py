import asyncio
import math
from contextlib import suppress
from random import random

from app.core.time import now_ist
from app.data.repository import Repository
from app.data.token_store import token_store
from app.models.schemas import MarketTick
from app.services.event_bus import EventBus


class MarketDataService:
    def __init__(self, repo: Repository, bus: EventBus, default_instruments: list[str]) -> None:
        self.repo = repo
        self.bus = bus
        self.subscriptions: set[str] = set(default_instruments)
        self.tick_handlers = []
        self._task: asyncio.Task[None] | None = None
        self._seed_prices: dict[str, float] = {instrument: 22000.0 + index * 100 for index, instrument in enumerate(default_instruments)}

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._simulate_ticks())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def subscribe(self, instrument_keys: list[str]) -> list[str]:
        for key in instrument_keys:
            self.subscriptions.add(key)
            self._seed_prices.setdefault(key, 100.0 + random() * 1000)
        return sorted(self.subscriptions)

    async def ingest_tick(self, tick: MarketTick) -> None:
        self.repo.upsert_tick(tick)
        await self.bus.publish("market-data", tick.model_dump(mode="json"))
        for handler in self.tick_handlers:
            await handler(tick)

    async def _simulate_ticks(self) -> None:
        step = 0
        while True:
            if token_store.access_token("live"):
                await asyncio.sleep(2)
                continue
            for instrument in list(self.subscriptions):
                base = self._seed_prices.setdefault(instrument, 100.0)
                wave = math.sin(step / 8) * 12
                noise = (random() - 0.5) * 3
                ltp = max(1, base + wave + noise)
                tick = MarketTick(
                    instrument_key=instrument,
                    timestamp=now_ist(),
                    ltp=round(ltp, 2),
                    close=round(base, 2),
                    bid=round(ltp - 0.05, 2),
                    ask=round(ltp + 0.05, 2),
                    volume=1000 + step,
                    greeks={"delta": round(0.5 + math.sin(step / 20) * 0.1, 4), "theta": -12.5},
                    raw={"source": "simulated"},
                )
                await self.ingest_tick(tick)
            step += 1
            await asyncio.sleep(1)
