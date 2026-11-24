"""Upstox V3 live market feed (WebSocket + protobuf).

1. GET /v3/feed/market-data-feed/authorize -> one-time wss URL
2. send binary JSON {"guid","method":"sub|unsub|change_mode","data":{"mode","instrumentKeys"}}
3. receive binary protobuf `FeedResponse` frames -> normalised `Tick`s

Subscriptions follow `demand()` (diffed every second). Reconnects with
exponential backoff; a data-silence watchdog forces reconnects on stalls.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx

from algo_common.logging import get_logger
from algo_common.schemas.market import Greeks, Instrument, Tick
from market_data.base import DemandFn
from market_data.proto import MarketDataFeedV3_pb2 as pb

log = get_logger("upstox.feed")
MAX_KEYS = 2000  # 'full' mode individual key cap (Upstox V3 limits table)
SILENCE_TIMEOUT = 90.0


def decode_feed(raw: bytes, key_to_symbol: dict[str, str]) -> list[Tick]:
    """Decode one protobuf FeedResponse into ticks (pure function, unit tested)."""
    resp = pb.FeedResponse()
    resp.ParseFromString(raw)
    out: list[Tick] = []
    for key, feed in resp.feeds.items():
        symbol = key_to_symbol.get(key, key)
        kind = feed.WhichOneof("FeedUnion")
        ltpc = None
        greeks: Greeks | None = None
        extra: dict[str, Any] = {}
        if kind == "ltpc":
            ltpc = feed.ltpc
        elif kind == "fullFeed":
            ff = feed.fullFeed
            which = ff.WhichOneof("FullFeedUnion")
            if which == "marketFF":
                m = ff.marketFF
                ltpc = m.ltpc
                extra = {"volume": float(m.vtt), "oi": float(m.oi) or None}
                if m.marketLevel.bidAskQuote:
                    best = m.marketLevel.bidAskQuote[0]
                    extra.update(bid=best.bidP or None, ask=best.askP or None)
                day = next((o for o in m.marketOHLC.ohlc if o.interval == "1d"), None)
                if day:
                    extra.update(open=day.open, high=day.high, low=day.low)
                if m.HasField("optionGreeks"):
                    g = m.optionGreeks
                    greeks = Greeks(delta=g.delta, gamma=g.gamma, theta=g.theta, vega=g.vega, rho=g.rho, iv=m.iv or None)
            elif which == "indexFF":
                ltpc = ff.indexFF.ltpc
                day = next((o for o in ff.indexFF.marketOHLC.ohlc if o.interval == "1d"), None)
                if day:
                    extra.update(open=day.open, high=day.high, low=day.low)
        elif kind == "firstLevelWithGreeks":
            f = feed.firstLevelWithGreeks
            ltpc = f.ltpc
            g = f.optionGreeks
            greeks = Greeks(delta=g.delta, gamma=g.gamma, theta=g.theta, vega=g.vega, rho=g.rho, iv=f.iv or None)
            extra = {"volume": float(f.vtt), "oi": float(f.oi) or None, "bid": f.firstDepth.bidP or None,
                     "ask": f.firstDepth.askP or None}
        if ltpc is None:
            continue
        cp = ltpc.cp or None
        ts = datetime.fromtimestamp(ltpc.ltt / 1000, tz=UTC) if ltpc.ltt else datetime.now(tz=UTC)
        out.append(Tick(
            symbol=symbol, ts=ts, ltp=ltpc.ltp, ltq=int(ltpc.ltq) or None, close=cp,
            change=(ltpc.ltp - cp) if cp else None, change_pct=((ltpc.ltp - cp) / cp * 100) if cp else None,
            greeks=greeks, **extra,
        ))
    return out


class FeedNotAuthorized(Exception):
    """The token is valid for REST but not allowed to authorize the WebSocket feed (HTTP 401/403)."""


class UpstoxFeed:
    def __init__(self, http: httpx.AsyncClient, by_symbol: dict[str, Instrument], by_key: dict[str, Instrument]) -> None:
        self._http = http
        self._by_symbol = by_symbol
        self._key_to_symbol = {k: i.symbol for k, i in by_key.items()}

    async def _authorize(self) -> str:
        r = await self._http.get("/v3/feed/market-data-feed/authorize")
        if r.status_code in (401, 403):
            msg = ""
            with contextlib.suppress(Exception):
                msg = ((r.json().get("errors") or [{}])[0]).get("message", "")
            raise FeedNotAuthorized(f"feed authorize returned {r.status_code}{': ' + msg if msg else ''}")
        r.raise_for_status()
        return str(r.json()["data"]["authorized_redirect_uri"])

    async def run(self, demand: DemandFn) -> AsyncIterator[list[Tick]]:
        import websockets

        from market_data.upstox import subscription_message

        attempt = 0
        while True:
            subscribed: set[str] = set()
            try:
                url = await self._authorize()
                async with websockets.connect(url, max_size=2**23, ping_interval=20) as ws:
                    attempt = 0
                    log.info("upstox.feed_connected")
                    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=5000)

                    async def reader(q: asyncio.Queue[bytes] = queue) -> None:
                        async for msg in ws:
                            if isinstance(msg, bytes):
                                await q.put(msg)

                    reader_task = asyncio.create_task(reader())
                    try:
                        last_data = asyncio.get_running_loop().time()
                        while not reader_task.done():
                            wanted = {
                                self._by_symbol[s].instrument_key for s in demand() if s in self._by_symbol
                            }
                            wanted = set(sorted(wanted)[:MAX_KEYS])
                            add, rem = wanted - subscribed, subscribed - wanted
                            if add:
                                await ws.send(subscription_message(sorted(add), "sub", "full"))
                            if rem:
                                await ws.send(subscription_message(sorted(rem), "unsub"))
                            subscribed = wanted
                            try:
                                raw = await asyncio.wait_for(queue.get(), timeout=1.0)
                                last_data = asyncio.get_running_loop().time()
                                batch = decode_feed(raw, self._key_to_symbol)
                                while not queue.empty() and len(batch) < 2000:
                                    batch.extend(decode_feed(queue.get_nowait(), self._key_to_symbol))
                                if batch:
                                    yield batch
                            except TimeoutError:
                                if subscribed and asyncio.get_running_loop().time() - last_data > SILENCE_TIMEOUT:
                                    log.warning("upstox.feed_silent_reconnect")
                                    break
                    finally:
                        reader_task.cancel()
                        with contextlib.suppress(BaseException):
                            await reader_task
            except (asyncio.CancelledError, FeedNotAuthorized):
                raise
            except Exception as exc:
                log.warning("upstox.feed_error", error=str(exc))
            attempt += 1
            await asyncio.sleep(min(30.0, 1.5**attempt) * (0.5 + random.random() / 2))
