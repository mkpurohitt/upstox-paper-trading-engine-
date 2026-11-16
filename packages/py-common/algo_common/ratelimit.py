"""Rate limiting primitives.

* `SlidingWindowLimiter` - distributed (via KV) limiter used for API
  requests and the SEBI order-rate threshold.
* `TokenBucket` - in-process smoothing for outbound provider calls.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from algo_common.kv import KV, get_kv


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float, kv: KV | None = None, prefix: str = "rl") -> None:
        self.limit = limit
        self.window = window_s
        self._kv = kv
        self.prefix = prefix

    @property
    def kv(self) -> KV:
        return self._kv or get_kv()

    async def hit(self, key: str) -> tuple[bool, int]:
        """Record one event; returns (allowed, current_count)."""
        count = await self.kv.zadd_and_count(
            f"{self.prefix}:{key}", uuid.uuid4().hex, time.time(), self.window
        )
        return count <= self.limit, count


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: int | None = None) -> None:
        self.rate = rate_per_sec
        self.capacity = capacity or max(1, int(rate_per_sec))
        self._tokens = float(self.capacity)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                await asyncio.sleep((tokens - self._tokens) / self.rate)
