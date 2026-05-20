import asyncio
from contextlib import suppress

from app.core.config import Settings
from app.data.token_store import token_store
from app.market.normalizer import normalize_quote_response
from app.market.upstox_client import UpstoxClient


class LiveQuotePollingService:
    def __init__(self, settings: Settings, client: UpstoxClient, tick_handler) -> None:
        self.settings = settings
        self.client = client
        self.tick_handler = tick_handler
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self.last_error: str | None = None
        self.last_success_at: str | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while self._running:
            if not (token_store.access_token("live") or self.settings.live_token):
                await asyncio.sleep(2)
                continue
            try:
                payload = await self.client.full_market_quote(self.settings.default_instrument_list)
                for tick in normalize_quote_response(payload):
                    tick.raw["source"] = "upstox_quote"
                    await self.tick_handler(tick)
                self.last_error = None
                self.last_success_at = __import__("app.core.time", fromlist=["now_ist"]).now_ist().isoformat()
            except Exception as exc:
                self.last_error = str(exc)
            await asyncio.sleep(2)

    def status(self) -> dict[str, str | bool | None]:
        return {
            "running": self._running,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
        }
