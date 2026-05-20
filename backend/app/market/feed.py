import asyncio
import math
import logging
from contextlib import suppress
from random import random
from typing import Any, Callable, Awaitable

from app.core.time import now_ist
from app.data.repository import Repository
from app.data.token_store import token_store
from app.models.schemas import MarketTick, Candle
from app.services.event_bus import EventBus

logger = logging.getLogger(__name__)

class MarketDataService:
    def __init__(self, repo: Repository, bus: EventBus, default_instruments: list[str]) -> None:
        self.repo = repo
        self.bus = bus
        self.subscriptions: set[str] = set(default_instruments)
        
        # Obscribers type signatures matching strict Pyright requirements
        self.tick_handlers: list[Callable[[MarketTick], Awaitable[None]]] = []
        self.candle_handlers: list[Callable[[Candle], Awaitable[None]]] = []
        
        self._task: asyncio.Task[None] | None = None
        self._seed_prices: dict[str, float] = {
            instrument: 22000.0 + index * 100 for index, instrument in enumerate(default_instruments)
        }
        
        # State tracking caches for real-time OHLC aggregation
        self._active_candles: dict[str, Candle] = {}
        self._candle_volume_baselines: dict[str, int] = {}

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
        """Ingests live raw ticks, saves state, and aggregates them into OHLC candles."""
        self.repo.upsert_tick(tick)
        await self.bus.publish("market-data", tick.model_dump(mode="json"))
        
        # Broadcast ticks to registered handlers (e.g. Strategy Engine and PaperOMS Matching Loop)
        for handler in self.tick_handlers:
            await handler(tick)
            
        # Process real-time 1-minute bar aggregation
        await self._aggregate_candle_bar(tick)

    async def _aggregate_candle_bar(self, tick: MarketTick) -> None:
        """Aggregates ticks into minute-aligned candles and calculates incremental volume changes."""
        inst_key = tick.instrument_key
        tick_time = tick.timestamp
        # Force alignment to the exact minute boundary
        candle_time = tick_time.replace(second=0, microsecond=0)
        
        current_candle = self._active_candles.get(inst_key)
        
        # Check if the time window has rolled over to a new minute bar boundary
        if current_candle and current_candle.timestamp != candle_time:
            # Period closed: Dispatch finalized bar to the event bus and strategies
            await self._emit_candle(current_candle)
            current_candle = None
            
        if not current_candle:
            # Establish baseline volume for the new candle period
            tick_vol = tick.volume if tick.volume is not None else 0
            self._candle_volume_baselines[inst_key] = tick_vol
            
            new_candle = Candle(
                instrument_key=inst_key,
                timeframe="1m",
                timestamp=candle_time,
                open=tick.ltp,
                high=tick.ltp,
                low=tick.ltp,
                close=tick.ltp,
                volume=0,
                payload={"source": tick.raw.get("source", "live")}
            )
            self._active_candles[inst_key] = new_candle
        else:
            # Update values within the current active time bar window
            current_candle.high = max(current_candle.high, tick.ltp)
            current_candle.low = min(current_candle.low, tick.ltp)
            current_candle.close = tick.ltp
            
            if tick.volume is not None:
                baseline = self._candle_volume_baselines.get(inst_key, 0)
                # Compute absolute incremental difference instead of raw addition
                current_candle.volume = max(0, tick.volume - baseline)

    async def _emit_candle(self, candle: Candle) -> None:
        """Publishes consolidated candles to systemic consumers."""
        await self.bus.publish("market-candle", candle.model_dump(mode="json"))
        for handler in self.candle_handlers:
            await handler(candle)

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
                    volume=1000 + (step * 5),  # Emulates expanding volume profile
                    greeks={"delta": round(0.5 + math.sin(step / 20) * 0.1, 4), "theta": -12.5},
                    raw={"source": "simulated"},
                )
                await self.ingest_tick(tick)
            step += 1
            await asyncio.sleep(1)