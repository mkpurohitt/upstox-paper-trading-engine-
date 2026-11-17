"""Zerodha Kite Connect v3 (request-token + SHA-256 checksum login)."""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar
from urllib.parse import urlencode

from broker_gateway.adapters._common import (
    day_end_expiry,
    order_type_from,
    parse_ts,
    product_from,
    side_from,
    status_from,
)
from broker_gateway.base import HttpBrokerAdapter, as_int, num
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
    Trade,
)


class ZerodhaAdapter(HttpBrokerAdapter):
    name = "zerodha"
    display_name = "Zerodha (Kite Connect)"
    auth_type = "oauth"
    base_url = "https://api.kite.trade"
    docs_url = "https://kite.trade/docs/connect/v3/"
    rate_limit_per_sec = 9.0
    credential_fields: ClassVar = [
        CredentialField(name="api_key", label="API key"),
        CredentialField(name="api_secret", label="API secret", secret=True),
    ]

    def headers(self) -> dict[str, str]:
        h = {"X-Kite-Version": "3", "Accept": "application/json"}
        if self.session.get("access_token"):
            h["Authorization"] = f"token {self.credentials.get('api_key')}:{self.session['access_token']}"
        return h

    def login_url(self, state: str, redirect_uri: str) -> str:
        # Kite redirects to the URL registered on the developer console; `state` round-trips via redirect_params
        return f"https://kite.zerodha.com/connect/login?{urlencode({'v': 3, 'api_key': self.credentials['api_key'], 'redirect_params': f'state={state}'})}"

    async def oauth_callback(self, params: dict[str, str], redirect_uri: str) -> dict[str, Any]:
        rt = params["request_token"]
        checksum = hashlib.sha256(f"{self.credentials['api_key']}{rt}{self.credentials['api_secret']}".encode()).hexdigest()
        body = await self.request("POST", "/session/token", data={"api_key": self.credentials["api_key"], "request_token": rt,
                                                                    "checksum": checksum})
        d = body["data"]
        self.session = {"access_token": d["access_token"], "user_id": d.get("user_id"), "expires_at": day_end_expiry().isoformat()}
        return self.session

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        m = self.symbol_map(req.symbol)
        p: dict[str, Any] = {
            "tradingsymbol": m["tradingsymbol"], "exchange": m["exchange"], "transaction_type": req.side.value,
            "order_type": req.order_type.value, "quantity": req.quantity, "product": req.product.value,
            "validity": req.validity, "tag": (req.tag or req.algo_id or "")[:20],
        }
        if req.price:
            p["price"] = req.price
        if req.trigger_price:
            p["trigger_price"] = req.trigger_price
        if req.order_type.value == "MARKET" and m["exchange"] in ("NFO", "BFO", "MCX"):
            p["market_protection"] = -1  # broker-side protection for market orders on derivatives
        return p

    async def place_order(self, req: OrderRequest) -> OrderAck:
        body = await self.request("POST", "/orders/regular", data=self.to_payload(req))
        return OrderAck(broker_order_id=str(body["data"]["order_id"]))

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        data = {k: v for k, v in {"quantity": req.quantity, "price": req.price, "trigger_price": req.trigger_price,
                                   "order_type": req.order_type.value if req.order_type else None}.items() if v is not None}
        body = await self.request("PUT", f"/orders/regular/{broker_order_id}", data=data)
        return OrderAck(broker_order_id=str(body["data"]["order_id"]), status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        await self.request("DELETE", f"/orders/regular/{broker_order_id}")
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    async def get_order_book(self) -> list[Order]:
        rows = (await self.request("GET", "/orders")).get("data") or []
        return [Order(
            broker_order_id=str(r["order_id"]), symbol=self.from_broker(r["exchange"], r["tradingsymbol"]),
            side=side_from(r["transaction_type"]), quantity=as_int(r["quantity"]), filled_quantity=as_int(r.get("filled_quantity")),
            price=num(r.get("price")), trigger_price=num(r.get("trigger_price")), average_price=num(r.get("average_price")),
            order_type=order_type_from(r.get("order_type")), product=product_from(r.get("product")),
            status=status_from(r.get("status")), status_message=r.get("status_message"), tag=r.get("tag"),
            ts=parse_ts(r.get("order_timestamp")),
        ) for r in rows]

    async def get_trade_book(self) -> list[Trade]:
        rows = (await self.request("GET", "/trades")).get("data") or []
        return [Trade(broker_trade_id=str(r["trade_id"]), broker_order_id=str(r["order_id"]),
                      symbol=self.from_broker(r["exchange"], r["tradingsymbol"]), side=side_from(r["transaction_type"]),
                      quantity=as_int(r["quantity"]), price=num(r["average_price"]), product=product_from(r.get("product")),
                      ts=parse_ts(r.get("fill_timestamp"))) for r in rows]

    async def get_positions(self) -> list[Position]:
        net = ((await self.request("GET", "/portfolio/positions")).get("data") or {}).get("net") or []
        return [Position(symbol=self.from_broker(r["exchange"], r["tradingsymbol"]), product=product_from(r.get("product")),
                         quantity=as_int(r["quantity"]), average_price=num(r.get("average_price")), last_price=num(r.get("last_price")),
                         realised_pnl=num(r.get("realised")), unrealised_pnl=num(r.get("unrealised", r.get("m2m"))), broker=self.name)
                for r in net]

    async def get_holdings(self) -> list[Holding]:
        rows = (await self.request("GET", "/portfolio/holdings")).get("data") or []
        return [Holding(symbol=self.from_broker(r["exchange"], r["tradingsymbol"]), quantity=as_int(r["quantity"]),
                        average_price=num(r["average_price"]), last_price=num(r.get("last_price")), pnl=num(r.get("pnl")),
                        isin=r.get("isin"), broker=self.name) for r in rows]

    async def get_funds(self) -> Funds:
        eq = ((await self.request("GET", "/user/margins")).get("data") or {}).get("equity") or {}
        avail = num((eq.get("available") or {}).get("live_balance"), num(eq.get("net")))
        used = num((eq.get("utilised") or {}).get("debits"))
        return Funds(available=avail, used=used, total=avail + used)

    async def get_profile(self) -> Profile:
        d = (await self.request("GET", "/user/profile")).get("data") or {}
        return Profile(user_id=d.get("user_id", ""), name=d.get("user_name", ""), email=d.get("email"), broker=self.name,
                       exchanges=d.get("exchanges", []))
