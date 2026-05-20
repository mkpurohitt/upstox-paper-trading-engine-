import asyncio
import json
from contextlib import suppress
from typing import Awaitable, Callable

import websockets

from app.market.normalizer import normalize_ws_feed
from app.market.upstox_client import UpstoxClient
from app.models.schemas import MarketTick


TickHandler = Callable[[MarketTick], Awaitable[None]]


class UpstoxMarketWebSocket:
    """Reconnectable V3 feed client.

    Upstox V3 feed payloads are protobuf in production. This class keeps the
    network lifecycle isolated; plug the generated protobuf decoder into
    `_decode_message` when the official `.proto` file is added to the repo.
    """

    def __init__(self, client: UpstoxClient, on_tick: TickHandler) -> None:
        self.client = client
        self.on_tick = on_tick
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        delay = 1
        while self._running:
            try:
                ws_url = await self.client.get_market_authorize_url_v3()
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as websocket:
                    delay = 1
                    async for message in websocket:
                        payload = self._decode_message(message)
                        for tick in normalize_ws_feed(payload):
                            await self.on_tick(tick)
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def stop(self) -> None:
        self._running = False

    def _decode_message(self, message: bytes | str) -> dict:
        if isinstance(message, bytes):
            with suppress(UnicodeDecodeError, json.JSONDecodeError):
                return json.loads(message.decode("utf-8"))
            return {}
        with suppress(json.JSONDecodeError):
            return json.loads(message)
        return {}

