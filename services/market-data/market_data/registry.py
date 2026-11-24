"""Provider selection + caching.

Live Upstox data comes from an access token saved by an admin (Admin -> Market data, stored encrypted) or from the
environment (`DATA_MODE=live` + `UPSTOX_ACCESS_TOKEN`/`UPSTOX_ANALYTICS_TOKEN`); anything else -> MockProvider. The
provider is reached through a proxy so it can be swapped at runtime. Live failures for a request never fall back
silently to mock data (that would be misleading) - they surface as errors.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

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


_current: MarketDataProvider | None = None
_mock: MockProvider | None = None
_generation = 0
_superseded: asyncio.Event | None = None
_source = "none"  # where the live configuration came from: "admin" | "env" | "none"
_last_error: str | None = None
_applied: tuple[Any, ...] | None = None
_closing: set[asyncio.Task[None]] = set()


def get_mock() -> MockProvider:
    global _mock
    if _mock is None:
        _mock = MockProvider()
    return _mock


def _from_env() -> MarketDataProvider:
    global _source
    s = get_settings()
    if s.is_live_data and s.upstox_configured:
        from market_data.upstox import UpstoxProvider

        _source = "env"
        log.info("market_data.provider", provider="upstox", source="env")
        return CachedProvider(UpstoxProvider())
    if s.is_live_data:
        log.warning("market_data.live_requested_but_unconfigured_using_mock")
    _source = "none"
    log.info("market_data.provider", provider="mock")
    return get_mock()


def _current_provider() -> MarketDataProvider:
    global _current
    if _current is None:
        _current = _from_env()
    return _current


class ProviderProxy(MarketDataProvider):
    """Stable handle on the configured provider.

    Every component (API routes, tick streamer, paper matcher, strategy runners) holds this proxy, so switching from
    mock to live Upstox data, or replacing an expired access token, takes effect everywhere without a restart. A tick
    stream in progress ends when the provider is replaced, and the streamer reconnects to the new one.
    """

    @property  # type: ignore[override]
    def name(self) -> str:
        return _current_provider().name

    @property
    def inner(self) -> MarketDataProvider:
        p = _current_provider()
        return p.inner if isinstance(p, CachedProvider) else p

    async def instruments(self, exchange: str | None = None) -> list[Instrument]:
        return await _current_provider().instruments(exchange)

    async def search(self, query: str, limit: int = 20) -> list[Instrument]:
        return await _current_provider().search(query, limit)

    async def instrument(self, symbol: str) -> Instrument | None:
        return await _current_provider().instrument(symbol)

    async def candles(self, symbol: str, interval: Interval, start: datetime, end: datetime) -> list[Candle]:
        return await _current_provider().candles(symbol, interval, start, end)

    async def intraday_candles(self, symbol: str, interval: Interval = Interval.M1) -> list[Candle]:
        return await _current_provider().intraday_candles(symbol, interval)

    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        return await _current_provider().quotes(symbols)

    async def ltp(self, symbols: list[str]) -> dict[str, float]:
        return await _current_provider().ltp(symbols)

    async def expiries(self, underlying: str) -> list[date]:
        return await _current_provider().expiries(underlying)

    async def option_chain(self, underlying: str, expiry: date | None = None, strikes: int = 20) -> OptionChain:
        return await _current_provider().option_chain(underlying, expiry, strikes)

    async def market_status(self) -> list[MarketStatus]:
        return await _current_provider().market_status()

    async def holidays(self, year: int | None = None) -> list[dict[str, str]]:
        return await _current_provider().holidays(year)

    async def stream(self, demand: DemandFn) -> AsyncIterator[list[Tick]]:  # type: ignore[override]
        while True:
            provider = _current_provider()
            stale = _superseded_event()
            agen = provider.stream(demand).__aiter__()
            try:
                while not stale.is_set():
                    nxt = asyncio.ensure_future(agen.__anext__())
                    waiter = asyncio.ensure_future(stale.wait())
                    done, _ = await asyncio.wait({nxt, waiter}, return_when=asyncio.FIRST_COMPLETED)
                    if nxt not in done:
                        nxt.cancel()
                        with contextlib.suppress(BaseException):
                            await nxt
                        break
                    waiter.cancel()
                    try:
                        batch = nxt.result()
                    except StopAsyncIteration:
                        return
                    yield batch
            finally:
                with contextlib.suppress(BaseException):
                    await agen.aclose()  # type: ignore[attr-defined]
            log.info("market_data.stream_switched", provider=_current_provider().name)

    async def close(self) -> None:
        await _current_provider().close()

    def __getattr__(self, item: str) -> object:  # provider-specific helpers (e.g. MockProvider.daily_closes)
        return getattr(self.inner, item)


def _superseded_event() -> asyncio.Event:
    global _superseded
    if _superseded is None:
        _superseded = asyncio.Event()
    return _superseded


_proxy = ProviderProxy()


def get_provider() -> MarketDataProvider:
    return _proxy


def set_provider(p: MarketDataProvider | None) -> None:
    """Replace the active provider (tests, runtime reconfiguration). `None` re-reads the environment."""
    global _current, _generation, _superseded
    old = _current
    _current = p
    _generation += 1
    if _superseded is not None:
        _superseded.set()  # end streams bound to the old provider
    _superseded = None
    if old is not None and old is not p and old is not _mock:
        with contextlib.suppress(RuntimeError):  # no running loop (sync tests): nothing to close asynchronously
            task = asyncio.get_running_loop().create_task(old.close())
            _closing.add(task)
            task.add_done_callback(_closing.discard)


def provider_generation() -> int:
    return _generation


def provider_info() -> dict[str, Any]:
    p = _current_provider()
    return {"name": p.name, "live": p.name != "mock", "data_mode": get_settings().data_mode, "source": _source,
            "last_error": _last_error}


def note_provider_error(message: str | None) -> None:
    global _last_error
    _last_error = message


# ------------------------------------------------------------------ runtime (admin) configuration
LIVE_CONFIG_KEY = "market_data.upstox"


async def apply_live_config(cfg: dict[str, Any] | None) -> None:
    """Activate the admin-saved Upstox configuration (or fall back to the environment when there is none)."""
    global _source, _applied
    fingerprint = (bool(cfg), bool(cfg and cfg.get("enabled")), (cfg or {}).get("token_enc"))
    if fingerprint == _applied and _current is not None:
        return  # already active (the publishing process also receives its own reload message)
    _applied = fingerprint
    if cfg and cfg.get("enabled") and cfg.get("token_enc"):
        from algo_common.crypto import Vault
        from market_data.upstox import UpstoxProvider

        token = Vault.from_settings().decrypt(cfg["token_enc"], aad=LIVE_CONFIG_KEY)
        set_provider(CachedProvider(UpstoxProvider(token)))
        _source = "admin"
        log.info("market_data.provider", provider="upstox", source="admin")
    elif cfg and not cfg.get("enabled"):
        set_provider(get_mock())
        _source = "none"
        log.info("market_data.provider", provider="mock", source="admin")
    else:
        set_provider(_from_env())
    note_provider_error(None)


async def load_live_config() -> dict[str, Any] | None:
    from algo_db.models import SystemFlag
    from algo_db.session import session_scope

    try:
        async with session_scope() as db:
            row = await db.get(SystemFlag, LIVE_CONFIG_KEY)
            return dict(row.value) if row and row.value else None
    except Exception as exc:  # tables may not exist yet (first migration)
        log.warning("market_data.live_config_unavailable", error=str(exc))
        return None


async def init_provider_from_db() -> None:
    """Called once at process start: admin configuration wins over the environment."""
    cfg = await load_live_config()
    if cfg is not None:
        try:
            await apply_live_config(cfg)
        except Exception as exc:
            log.error("market_data.live_config_failed", error=str(exc))
            note_provider_error(f"Saved Upstox configuration could not be applied: {exc}")
            set_provider(_from_env())


async def watch_provider_reloads() -> None:
    """Follow configuration changes made by another process (admin API -> market-data / runner containers)."""
    from algo_common.bus import get_bus

    async for _, msg in get_bus().subscribe("md:provider"):
        if msg.get("action") == "reload":
            try:
                await apply_live_config(await load_live_config())
            except Exception as exc:
                log.error("market_data.reload_failed", error=str(exc))
                note_provider_error(str(exc))


def dumps(obj: object) -> str:
    return json.dumps(obj, default=str)
