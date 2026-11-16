"""Provider selection + caching.

`DATA_MODE=live` and an Upstox analytics token -> UpstoxProvider (wrapped in a
cache); anything else -> MockProvider. Live failures for a request never fall
back silently to mock data (that would be misleading) - they surface as errors.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime

from algo_common.kv import get_kv
from algo_common.logging import get_logger
from algo_common.schemas.market import Candle, Instrument, Interval, MarketStatus, OptionChain, Quote, Tick
from algo_common.settings import get_settings
from market_data.base import DemandFn, MarketDataProvider
from market_data.mock import MockProvider

log = get_logger("market_data")

_TTL = {"quotes": 1.0, "chain": 3.0, "expiries": 3600.0, "status": 30.0, "holidays": 86400.0,
        "candles_intraday": 20.0, "candles_daily": 600.0}


class CachedProvider(MarketDataProvider):
    """Read-through KV cache (Redis or memory) in front of a live provider."""

    def __init__(self, inner: MarketDataProvider) -> None:
        self.inner = inner
        self.name = inner.name

    async def instruments(self, exchange: str | None = None) -> list[Instrument]:
        return await self.inner.instruments(exchange)

    async def instrument(self, symbol: str) -> Instrument | None:
        return await self.inner.instrument(symbol)

    async def search(self, query: str, limit: int = 20) -> list[Instrument]:
        return await self.inner.search(query, limit)

    async def candles(self, symbol: str, interval: Interval, start: datetime, end: datetime) -> list[Candle]:
        ttl = _TTL["candles_daily"] if interval in (Interval.D1, Interval.W1) else _TTL["candles_intraday"]
        key = f"md:c:{self.name}:{symbol}:{interval.value}:{start:%Y%m%d%H%M}:{end:%Y%m%d%H%M}"

        async def produce() -> list[dict]:
            return [c.model_dump(mode="json") for c in await self.inner.candles(symbol, interval, start, end)]

        return [Candle.model_validate(c) for c in await get_kv().cached(key, ttl, produce)]

    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        kv = get_kv()
        out: dict[str, Quote] = {}
        missing: list[str] = []
        for s in symbols:
            raw = await kv.get(f"md:q:{self.name}:{s}")
            if raw:
                out[s] = Quote.model_validate_json(raw)
            else:
                missing.append(s)
        if missing:
            fresh = await self.inner.quotes(missing)
            for s, q in fresh.items():
                await kv.set(f"md:q:{self.name}:{s}", q.model_dump_json(), ttl=_TTL["quotes"])
                out[s] = q
        return out

    async def expiries(self, underlying: str) -> list[date]:
        key = f"md:exp:{self.name}:{underlying}"

        async def produce() -> list[str]:
            return [d.isoformat() for d in await self.inner.expiries(underlying)]

        return [date.fromisoformat(d) for d in await get_kv().cached(key, _TTL["expiries"], produce)]

    async def option_chain(self, underlying: str, expiry: date | None = None, strikes: int = 20) -> OptionChain:
        key = f"md:oc:{self.name}:{underlying}:{expiry}:{strikes}"
        raw = await get_kv().get(key)
        if raw:
            return OptionChain.model_validate_json(raw)
        chain = await self.inner.option_chain(underlying, expiry, strikes)
        await get_kv().set(key, chain.model_dump_json(), ttl=_TTL["chain"])
        return chain

    async def market_status(self) -> list[MarketStatus]:
        key = f"md:status:{self.name}"

        async def produce() -> list[dict]:
            return [m.model_dump(mode="json") for m in await self.inner.market_status()]

        return [MarketStatus.model_validate(m) for m in await get_kv().cached(key, _TTL["status"], produce)]

    async def holidays(self, year: int | None = None) -> list[dict[str, str]]:
        key = f"md:hol:{self.name}:{year}"

        async def produce() -> list[dict[str, str]]:
            return await self.inner.holidays(year)

        return await get_kv().cached(key, _TTL["holidays"], produce)

    def stream(self, demand: DemandFn) -> AsyncIterator[list[Tick]]:
        return self.inner.stream(demand)

    async def close(self) -> None:
        await self.inner.close()


_provider: MarketDataProvider | None = None
_mock: MockProvider | None = None


def get_mock() -> MockProvider:
    global _mock
    if _mock is None:
        _mock = MockProvider()
    return _mock


def get_provider() -> MarketDataProvider:
    global _provider
    if _provider is None:
        s = get_settings()
        if s.is_live_data and s.upstox_configured:
            from market_data.upstox import UpstoxProvider

            _provider = CachedProvider(UpstoxProvider())
            log.info("market_data.provider", provider="upstox")
        else:
            if s.is_live_data:
                log.warning("market_data.live_requested_but_unconfigured_using_mock")
            _provider = get_mock()
            log.info("market_data.provider", provider="mock")
    return _provider


def set_provider(p: MarketDataProvider | None) -> None:
    global _provider
    _provider = p


def provider_info() -> dict[str, str | bool]:
    p = get_provider()
    return {"name": p.name, "live": p.name != "mock", "data_mode": get_settings().data_mode}


def dumps(obj: object) -> str:
    return json.dumps(obj, default=str)
