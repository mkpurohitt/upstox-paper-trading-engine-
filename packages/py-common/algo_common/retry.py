"""Async retry with exponential backoff and full jitter."""

from __future__ import annotations

import asyncio
import functools
import random
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base_delay: float = 0.25,
    max_delay: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    should_retry: Callable[[BaseException], bool] | None = None,
) -> T:
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except retry_on as exc:
            last = exc
            if should_retry is not None and not should_retry(exc):
                raise
            if attempt == attempts - 1:
                break
            delay = min(max_delay, base_delay * (2**attempt))
            await asyncio.sleep(random.uniform(0, delay))
    assert last is not None
    raise last


def with_retry(**kwargs: object) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    def deco(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kw: P.kwargs) -> T:
            return await retry_async(lambda: fn(*args, **kw), **kwargs)  # type: ignore[arg-type]

        return wrapper

    return deco
