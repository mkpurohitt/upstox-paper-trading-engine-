"""Pub/sub message bus.

`RedisBus` is used whenever `REDIS_URL` is configured so that the market-data
worker, strategy runners and every API replica share one fan-out fabric.
`InMemoryBus` keeps the single-process developer experience (and tests)
dependency free.

Channels used across the platform:
    ticks:{symbol}          live normalised ticks
    orders:{user_id}        order / trade updates
    backtest:{backtest_id}  backtest progress + completion
    scanner:{name}          scanner results
    deploy:{user_id}        strategy deployment logs / P&L
    md:control              market data subscription demand changes
    risk:killswitch         kill switch broadcasts
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from algo_common.logging import get_logger

log = get_logger(__name__)


def _default(o: Any) -> Any:
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    return str(o)


def dumps(message: Any) -> str:
    return json.dumps(message, default=_default, separators=(",", ":"))


class Bus(ABC):
    @abstractmethod
    async def publish(self, channel: str, message: dict[str, Any]) -> None: ...

    @abstractmethod
    def subscribe(self, *patterns: str) -> AsyncIterator[tuple[str, dict[str, Any]]]: ...

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None


class _Subscriber:
    def __init__(self, patterns: tuple[str, ...], maxsize: int = 10_000) -> None:
        self.patterns = patterns
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=maxsize)

    def matches(self, channel: str) -> bool:
        return any(fnmatch.fnmatchcase(channel, p) for p in self.patterns)


class InMemoryBus(Bus):
    def __init__(self) -> None:
        self._subs: set[_Subscriber] = set()

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        # round-trip through JSON so in-memory and redis behave identically
        payload = json.loads(dumps(message))
        for sub in list(self._subs):
            if sub.matches(channel):
                try:
                    sub.queue.put_nowait((channel, payload))
                except asyncio.QueueFull:
                    log.warning("bus.subscriber_queue_full", channel=channel)

    async def subscribe(self, *patterns: str) -> AsyncIterator[tuple[str, dict[str, Any]]]:  # type: ignore[override]
        sub = _Subscriber(patterns)
        self._subs.add(sub)
        try:
            while True:
                yield await sub.queue.get()
        finally:
            self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)


class RedisBus(Bus):
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url, decode_responses=True)

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self._redis.publish(channel, dumps(message))

    async def subscribe(self, *patterns: str) -> AsyncIterator[tuple[str, dict[str, Any]]]:  # type: ignore[override]
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(*patterns)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") not in ("pmessage", "message"):
                    continue
                try:
                    yield msg["channel"], json.loads(msg["data"])
                except (TypeError, ValueError):
                    continue
        finally:
            with contextlib.suppress(Exception):
                await pubsub.punsubscribe(*patterns)
                await pubsub.aclose()

    async def close(self) -> None:
        await self._redis.aclose()


_bus: Bus | None = None


def get_bus() -> Bus:
    global _bus
    if _bus is None:
        from algo_common.settings import get_settings

        url = get_settings().redis_url
        _bus = RedisBus(url) if url else InMemoryBus()
    return _bus


def set_bus(bus: Bus | None) -> None:
    global _bus
    _bus = bus
