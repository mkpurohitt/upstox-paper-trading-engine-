"""WebSocket gateway.

Protocol (JSON text frames):

client -> server
    {"type": "auth", "token": "<access jwt>"}                      (must be first)
    {"type": "subscribe", "channel": "ticks", "symbols": ["NSE:RELIANCE"]}
    {"type": "unsubscribe", "channel": "ticks", "symbols": [...]}
    {"type": "subscribe", "channel": "orders" | "deployments" | "notifications"}
    {"type": "subscribe", "channel": "backtest", "id": 42}
    {"type": "subscribe", "channel": "scanner", "name": "arbitrage"}
    {"type": "chat", "session_id": 1, "message": "...", "request_id": "..."}
    {"type": "ping"}

server -> client
    {"type": "ready", "user_id": 1}
    {"type": "tick", "data": {...}} | {"type": "order", "data": {...}} | {"type": "backtest", "data": {...}}
    {"type": "deployment", ...} | {"type": "notification", ...} | {"type": "scanner", ...}
    {"type": "chat.event", "request_id": "...", "event": {...}}
    {"type": "pong"} | {"type": "error", "message": "..."}
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from algo_common.bus import get_bus
from algo_common.kv import get_kv
from algo_common.logging import get_logger
from algo_common.metrics import WS_CONNECTIONS
from app.core.security import ACCESS, decode_token

log = get_logger("ws")
router = APIRouter()

MAX_SYMBOLS_PER_CLIENT = 400
CHANNEL_TYPES = {"ticks": "tick", "orders": "order", "backtest": "backtest", "scanner": "scanner",
                 "deploy": "deployment", "notify": "notification"}

ChatHandler = Callable[["Client", dict[str, Any]], Awaitable[None]]


class Client:
    def __init__(self, ws: WebSocket, user_id: int, role: str) -> None:
        self.ws = ws
        self.user_id = user_id
        self.role = role
        self.channels: set[str] = set()
        self.send_lock = asyncio.Lock()

    async def send(self, message: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.ws.send_json(message)


class ConnectionManager:
    def __init__(self) -> None:
        self.by_channel: dict[str, set[Client]] = defaultdict(set)
        self.clients: set[Client] = set()
        self._pump: asyncio.Task[None] | None = None
        self._heartbeat: asyncio.Task[None] | None = None
        self.chat_handler: ChatHandler | None = None
        self.backtest_owner: Callable[[int], Awaitable[int | None]] | None = None

    # ---- lifecycle ------------------------------------------------------------
    def start(self) -> None:
        if self._pump is None:
            self._pump = asyncio.create_task(self._pump_bus(), name="ws-bus-pump")
            self._heartbeat = asyncio.create_task(self._demand_heartbeat(), name="ws-demand-heartbeat")

    async def stop(self) -> None:
        for t in (self._pump, self._heartbeat):
            if t:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
        self._pump = self._heartbeat = None

    async def _pump_bus(self) -> None:
        bus = get_bus()
        async for channel, message in bus.subscribe(*(f"{c}:*" for c in CHANNEL_TYPES)):
            clients = self.by_channel.get(channel)
            if not clients:
                continue
            kind = CHANNEL_TYPES.get(channel.split(":", 1)[0], "event")
            frame = {"type": kind, "channel": channel, "data": message}
            for c in list(clients):
                try:
                    await c.send(frame)
                except Exception:
                    self.disconnect(c)

    def active_symbols(self) -> set[str]:
        return {ch.split(":", 1)[1] for ch, cl in self.by_channel.items() if ch.startswith("ticks:") and cl}

    async def _demand_heartbeat(self) -> None:
        kv = get_kv()
        while True:
            syms = self.active_symbols()
            if syms:
                await kv.sadd("md:demand", *syms)
                for s in syms:
                    await kv.set(f"md:demand:hb:{s}", str(time.time()), ttl=90)
            await asyncio.sleep(30)

    # ---- membership -------------------------------------------------------------
    def connect(self, client: Client) -> None:
        self.clients.add(client)
        WS_CONNECTIONS.inc()

    def disconnect(self, client: Client) -> None:
        if client in self.clients:
            self.clients.discard(client)
            WS_CONNECTIONS.dec()
        for ch in list(client.channels):
            self.by_channel[ch].discard(client)
            if not self.by_channel[ch]:
                self.by_channel.pop(ch, None)
        client.channels.clear()

    async def subscribe(self, client: Client, channels: list[str]) -> None:
        new_syms: list[str] = []
        for ch in channels:
            if ch.startswith("ticks:") and ch not in self.by_channel:
                new_syms.append(ch.split(":", 1)[1])
            self.by_channel[ch].add(client)
            client.channels.add(ch)
        if new_syms:
            kv = get_kv()
            await kv.sadd("md:demand", *new_syms)
            for s in new_syms:
                await kv.set(f"md:demand:hb:{s}", str(time.time()), ttl=90)
            await get_bus().publish("md:control", {"action": "subscribe", "symbols": new_syms})

    def unsubscribe(self, client: Client, channels: list[str]) -> None:
        for ch in channels:
            self.by_channel.get(ch, set()).discard(client)
            client.channels.discard(ch)
            if ch in self.by_channel and not self.by_channel[ch]:
                self.by_channel.pop(ch, None)


manager = ConnectionManager()


async def _resolve_channels(client: Client, msg: dict[str, Any]) -> list[str]:
    ch = msg.get("channel")
    if ch == "ticks":
        symbols = [str(s) for s in (msg.get("symbols") or [])][:MAX_SYMBOLS_PER_CLIENT]
        return [f"ticks:{s}" for s in symbols]
    if ch == "orders":
        return [f"orders:{client.user_id}"]
    if ch == "deployments":
        return [f"deploy:{client.user_id}"]
    if ch == "notifications":
        return [f"notify:{client.user_id}"]
    if ch == "scanner":
        return [f"scanner:{msg.get('name', '')}"]
    if ch == "backtest":
        bt_id = int(msg.get("id", 0))
        owner = await manager.backtest_owner(bt_id) if manager.backtest_owner else client.user_id
        if owner != client.user_id and client.role != "admin":
            raise PermissionError("not your backtest")
        return [f"backtest:{bt_id}"]
    raise ValueError(f"unknown channel {ch!r}")


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if first.get("type") != "auth":
            raise ValueError("auth required")
        payload = decode_token(str(first.get("token", "")), ACCESS)
    except (TimeoutError, ValueError, jwt.PyJWTError, WebSocketDisconnect):
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": "authentication failed"})
            await ws.close(code=4401)
        return

    client = Client(ws, int(payload["sub"]), str(payload.get("role", "user")))
    manager.connect(client)
    await client.send({"type": "ready", "user_id": client.user_id})
    chat_tasks: set[asyncio.Task[None]] = set()
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            try:
                if kind == "ping":
                    await client.send({"type": "pong", "ts": time.time()})
                elif kind == "subscribe":
                    chans = await _resolve_channels(client, msg)
                    if len(client.channels) + len(chans) > MAX_SYMBOLS_PER_CLIENT + 20:
                        raise ValueError("subscription limit reached")
                    await manager.subscribe(client, chans)
                    await client.send({"type": "subscribed", "channels": chans})
                elif kind == "unsubscribe":
                    chans = await _resolve_channels(client, msg)
                    manager.unsubscribe(client, chans)
                    await client.send({"type": "unsubscribed", "channels": chans})
                elif kind == "chat" and manager.chat_handler is not None:
                    t = asyncio.create_task(manager.chat_handler(client, msg))
                    chat_tasks.add(t)
                    t.add_done_callback(chat_tasks.discard)
                else:
                    raise ValueError(f"unsupported message type {kind!r}")
            except (ValueError, PermissionError) as exc:
                await client.send({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws.error", user_id=client.user_id)
    finally:
        for t in chat_tasks:
            t.cancel()
        manager.disconnect(client)
