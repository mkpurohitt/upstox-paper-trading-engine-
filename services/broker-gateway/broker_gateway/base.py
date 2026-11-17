"""Unified broker adapter interface + shared HTTP plumbing.

Design notes (informed by studying OpenAlgo's per-broker modules - see
ARCHITECTURE.md for the licensing decision): every adapter only knows how to
(1) authenticate, (2) translate a normalised `OrderRequest` into the broker's
wire format, and (3) normalise the broker's books back. Risk checks, audit,
persistence and Algo-ID tagging live above it in `OrderRouter`.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, ClassVar, Literal

import httpx

from algo_common.errors import AlgoError, ProviderError
from algo_common.logging import get_logger
from algo_common.ratelimit import TokenBucket
from algo_common.settings import get_settings
from broker_gateway.models import (
    CredentialField,
    Funds,
    Holding,
    ModifyRequest,
    Order,
    OrderAck,
    OrderRequest,
    OrderStatus,
    Position,
    Profile,
    Side,
    Trade,
)

log = get_logger("broker")
AuthType = Literal["oauth", "totp", "token", "none"]


class BrokerError(AlgoError):
    code = "broker_error"
    status_code = 502


class BrokerAuthError(BrokerError):
    code = "broker_auth"
    status_code = 401


class BrokerAdapter(ABC):
    name: ClassVar[str] = "base"
    display_name: ClassVar[str] = "Broker"
    auth_type: ClassVar[AuthType] = "oauth"
    credential_fields: ClassVar[list[CredentialField]] = []
    docs_url: ClassVar[str] = ""
    rate_limit_per_sec: ClassVar[float] = 9.0
    supports_streaming: ClassVar[bool] = False

    def __init__(self, credentials: dict[str, Any] | None = None, session: dict[str, Any] | None = None) -> None:
        self.credentials = credentials or {}
        self.session = session or {}

    # ---- authentication -------------------------------------------------------
    def login_url(self, state: str, redirect_uri: str) -> str | None:
        """OAuth brokers: URL to send the user to. Others return None."""
        return None

    async def oauth_callback(self, params: dict[str, str], redirect_uri: str) -> dict[str, Any]:
        raise BrokerError(f"{self.display_name} does not use OAuth")

    async def login(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        """TOTP / token brokers: create a session from stored credentials (+ one-time inputs)."""
        raise BrokerError(f"{self.display_name} uses OAuth; use the connect flow")

    async def refresh_session(self) -> dict[str, Any] | None:
        """Most Indian brokers issue day-scoped tokens with no refresh; re-login is required."""
        return None

    # ---- account --------------------------------------------------------------
    @abstractmethod
    async def get_profile(self) -> Profile: ...

    @abstractmethod
    async def get_funds(self) -> Funds: ...

    # ---- orders ---------------------------------------------------------------
    @abstractmethod
    async def place_order(self, req: OrderRequest) -> OrderAck: ...

    @abstractmethod
    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck: ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> OrderAck: ...

    @abstractmethod
    async def get_order_book(self) -> list[Order]: ...

    @abstractmethod
    async def get_trade_book(self) -> list[Trade]: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_holdings(self) -> list[Holding]: ...

    async def square_off_all(self, products: tuple[str, ...] = ("MIS", "NRML")) -> list[OrderAck]:
        acks: list[OrderAck] = []
        for p in await self.get_positions():
            if p.quantity == 0 or p.product.value not in products:
                continue
            req = OrderRequest(symbol=p.symbol, side=Side.SELL if p.quantity > 0 else Side.BUY,
                               quantity=abs(p.quantity), product=p.product, tag="squareoff")
            try:
                acks.append(await self.place_order(req))
            except BrokerError as exc:
                acks.append(OrderAck(broker_order_id="", status=OrderStatus.REJECTED, message=str(exc)))
        return acks

    async def cancel_all_open(self) -> list[OrderAck]:
        out = []
        for o in await self.get_order_book():
            if o.status in (OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING, OrderStatus.PENDING):
                try:
                    out.append(await self.cancel_order(o.broker_order_id))
                except BrokerError as exc:
                    out.append(OrderAck(broker_order_id=o.broker_order_id, status=OrderStatus.REJECTED, message=str(exc)))
        return out

    async def stream_order_updates(self, interval_s: float = 2.0) -> AsyncIterator[Order]:
        """Default: poll the order book and yield changed orders (brokers with a
        postback / websocket feed override this)."""
        seen: dict[str, tuple[str, int]] = {}
        while True:
            try:
                for o in await self.get_order_book():
                    sig = (o.status.value, o.filled_quantity)
                    if seen.get(o.broker_order_id) != sig:
                        seen[o.broker_order_id] = sig
                        yield o
            except BrokerError as exc:
                log.warning("broker.stream_poll_failed", broker=self.name, error=str(exc))
            await asyncio.sleep(interval_s)

    # ---- symbols ----------------------------------------------------------------
    def symbol_map(self, symbol: str) -> dict[str, Any]:
        """Canonical -> broker identifiers. Default: exchange + tradingsymbol."""
        from broker_gateway.symbols import default_map

        return default_map(self.name, symbol)

    def from_broker(self, exchange: str, tradingsymbol: str) -> str:
        from broker_gateway.symbols import to_canonical

        return to_canonical(self.name, exchange, tradingsymbol)

    async def close(self) -> None:
        return None


class HttpBrokerAdapter(BrokerAdapter):
    base_url: ClassVar[str] = ""

    def __init__(self, credentials: dict[str, Any] | None = None, session: dict[str, Any] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(credentials, session)
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._bucket = TokenBucket(self.rate_limit_per_sec, capacity=max(1, int(self.rate_limit_per_sec)))

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=get_settings().broker_http_timeout_s,
                                           transport=self._transport)
        return self._http

    def headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    async def request(self, method: str, path: str, *, json: Any = None, data: Any = None, params: Any = None,
                      content: str | bytes | None = None, headers: dict[str, str] | None = None) -> Any:
        await self._bucket.acquire()
        try:
            r = await self.http.request(method, path, json=json, data=data, params=params, content=content,
                                        headers={**self.headers(), **(headers or {})})
        except httpx.TransportError as exc:
            raise BrokerError(f"{self.display_name} unreachable: {exc}") from exc
        if r.status_code in (401, 403):
            raise BrokerAuthError(f"{self.display_name} session expired or unauthorised", details={"status": r.status_code})
        try:
            body = r.json() if r.content else {}
        except ValueError:
            body = {"raw": r.text[:500]}
        if r.status_code >= 400:
            raise BrokerError(f"{self.display_name} error {r.status_code}: {self.error_message(body)}",
                              details={"status": r.status_code, "body": body if isinstance(body, dict) else {}})
        return body

    @staticmethod
    def error_message(body: Any) -> str:
        if isinstance(body, dict):
            for k in ("message", "errorMessage", "emsg", "Error", "error", "errors", "remarks"):
                if body.get(k):
                    v = body[k]
                    return str(v[0].get("message", v[0]) if isinstance(v, list) and v and isinstance(v[0], dict) else v)
        return str(body)[:200]

    def token(self) -> str:
        tok = self.session.get("access_token")
        if not tok:
            raise BrokerAuthError(f"Not logged in to {self.display_name}")
        return str(tok)

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()


def num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def as_int(v: Any) -> int:
    return int(num(v))


__all__ = ["BrokerAdapter", "BrokerAuthError", "BrokerError", "HttpBrokerAdapter", "ProviderError", "as_int", "num"]
