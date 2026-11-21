"""Tiny key-value abstraction (Redis or in-process) used for caches,
rate limiters, OAuth state and subscription demand tracking."""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")



# `set` is also a method name on the KV classes; this alias keeps annotations pointing at the builtin.
StrSet = set[str]

class KV(ABC):
    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl: float | None = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def incr(self, key: str, ttl: float | None = None) -> int: ...

    @abstractmethod
    async def zadd_and_count(self, key: str, member: str, score: float, window: float) -> int:
        """Add `member` at `score`, evict entries older than `score - window`, return count."""

    @abstractmethod
    async def sadd(self, key: str, *members: str) -> None: ...

    @abstractmethod
    async def srem(self, key: str, *members: str) -> None: ...

    @abstractmethod
    async def smembers(self, key: str) -> StrSet: ...

    async def get_json(self, key: str) -> Any | None:
        raw = await self.get(key)
        return None if raw is None else json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: float | None = None) -> None:
        await self.set(key, json.dumps(value, default=str), ttl)

    async def cached(self, key: str, ttl: float, producer: Callable[[], Awaitable[T]]) -> T:
        hit = await self.get_json(key)
        if hit is not None:
            return hit  # type: ignore[no-any-return]
        value = await producer()
        await self.set_json(key, value, ttl)
        return value


class MemoryKV(KV):
    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._lock = asyncio.Lock()

    def _alive(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, exp = item
        if exp is not None and exp < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def get(self, key: str) -> str | None:
        v = self._alive(key)
        return v if isinstance(v, str) else None

    async def set(self, key: str, value: str, ttl: float | None = None) -> None:
        self._data[key] = (value, time.monotonic() + ttl if ttl else None)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, ttl: float | None = None) -> int:
        async with self._lock:
            cur = self._alive(key)
            n = int(cur or 0) + 1
            exp = self._data.get(key, (None, None))[1] if cur is not None else (time.monotonic() + ttl if ttl else None)
            self._data[key] = (str(n), exp)
            return n

    async def zadd_and_count(self, key: str, member: str, score: float, window: float) -> int:
        async with self._lock:
            z: dict[str, float] = self._alive(key) or {}
            z = {m: s for m, s in z.items() if s > score - window}
            z[member] = score
            self._data[key] = (z, time.monotonic() + window * 2)
            return len(z)

    async def sadd(self, key: str, *members: str) -> None:
        s: set[str] = self._alive(key) or set()
        s.update(members)
        self._data[key] = (s, None)

    async def srem(self, key: str, *members: str) -> None:
        s: set[str] = self._alive(key) or set()
        s.difference_update(members)
        self._data[key] = (s, None)

    async def smembers(self, key: str) -> StrSet:
        return set(self._alive(key) or set())


class RedisKV(KV):
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._r = Redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)  # type: ignore[no-any-return]

    async def set(self, key: str, value: str, ttl: float | None = None) -> None:
        await self._r.set(key, value, px=int(ttl * 1000) if ttl else None)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def incr(self, key: str, ttl: float | None = None) -> int:
        async with self._r.pipeline(transaction=True) as p:
            p.incr(key)
            if ttl:
                p.expire(key, int(ttl), nx=True)
            res = await p.execute()
        return int(res[0])

    async def zadd_and_count(self, key: str, member: str, score: float, window: float) -> int:
        async with self._r.pipeline(transaction=True) as p:
            p.zremrangebyscore(key, "-inf", score - window)
            p.zadd(key, {member: score})
            p.zcard(key)
            p.expire(key, int(window * 2) + 1)
            res = await p.execute()
        return int(res[2])

    async def sadd(self, key: str, *members: str) -> None:
        if members:
            await self._r.sadd(key, *members)

    async def srem(self, key: str, *members: str) -> None:
        if members:
            await self._r.srem(key, *members)

    async def smembers(self, key: str) -> StrSet:
        return set(await self._r.smembers(key))


_kv: KV | None = None


def get_kv() -> KV:
    global _kv
    if _kv is None:
        from algo_common.settings import get_settings

        url = get_settings().redis_url
        _kv = RedisKV(url) if url else MemoryKV()
    return _kv


def set_kv(kv: KV | None) -> None:
    global _kv
    _kv = kv
