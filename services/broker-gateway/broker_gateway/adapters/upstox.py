"""Upstox (API v2 orders, OAuth 2.0 authorization-code flow)."""

from __future__ import annotations

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
from broker_gateway.base import BrokerError, HttpBrokerAdapter, as_int, num
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
    Product,
    Profile,
    Trade,
)

PRODUCT = {Product.MIS: "I", Product.CNC: "D", Product.NRML: "D"}


class UpstoxAdapter(HttpBrokerAdapter):
    name = "upstox"
    display_name = "Upstox"
    auth_type = "oauth"
    base_url = "https://api.upstox.com"
    docs_url = "https://upstox.com/developer/api-documentation"
    rate_limit_per_sec = 9.0
    credential_fields: ClassVar = [
        CredentialField(name="api_key", label="API key"),
        CredentialField(name="api_secret", label="API secret", secret=True),
    ]

    def headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.session.get("access_token"):
            h["Authorization"] = f"Bearer {self.session['access_token']}"
        return h

    def login_url(self, state: str, redirect_uri: str) -> str:
        q = urlencode({"response_type": "code", "client_id": self.credentials["api_key"], "redirect_uri": redirect_uri, "state": state})
        return f"https://api.upstox.com/v2/login/authorization/dialog?{q}"

    async def oauth_callback(self, params: dict[str, str], redirect_uri: str) -> dict[str, Any]:
        body = await self.request("POST", "/v2/login/authorization/token", data={
            "code": params["code"], "client_id": self.credentials["api_key"], "client_secret": self.credentials["api_secret"],
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if "access_token" not in body:
            raise BrokerError("Upstox token exchange failed")
        self.session = {"access_token": body["access_token"], "user_id": body.get("user_id"),
                        "expires_at": day_end_expiry().isoformat()}
        return self.session

    def _key(self, symbol: str) -> str:
        tok = self.symbol_map(symbol).get("token")
        if not tok:
            raise BrokerError(f"No Upstox instrument_key for {symbol}; refresh the Upstox instrument master")
        return str(tok)

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        return {
            "quantity": req.quantity, "product": PRODUCT[req.product], "validity": req.validity,
            "price": req.price or 0, "tag": (req.tag or req.algo_id or "")[:20], "instrument_token": self._key(req.symbol),
            "order_type": req.order_type.value, "transaction_type": req.side.value, "disclosed_quantity": 0,
            "trigger_price": req.trigger_price or 0, "is_amo": False,
        }

    async def place_order(self, req: OrderRequest) -> OrderAck:
        body = await self.request("POST", "/v2/order/place", json=self.to_payload(req))
        return OrderAck(broker_order_id=str(body["data"]["order_id"]), status=OrderStatus.PENDING)

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        payload = {"order_id": broker_order_id, "validity": "DAY", "disclosed_quantity": 0,
                   "quantity": req.quantity or (original.quantity if original else 0),
                   "price": req.price if req.price is not None else (original.price if original else 0) or 0,
                   "order_type": (req.order_type or (original.order_type if original else None) or "LIMIT").__str__(),
                   "trigger_price": req.trigger_price or 0}
        body = await self.request("PUT", "/v2/order/modify", json=payload)
        return OrderAck(broker_order_id=str(body["data"]["order_id"]), status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        await self.request("DELETE", "/v2/order/cancel", params={"order_id": broker_order_id})
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    def _sym(self, row: dict[str, Any]) -> str:
        return self.from_broker(row.get("exchange", "NSE"), row.get("trading_symbol") or row.get("tradingsymbol", ""))

    async def get_order_book(self) -> list[Order]:
        rows = (await self.request("GET", "/v2/order/retrieve-all")).get("data") or []
        return [Order(
            broker_order_id=str(r["order_id"]), symbol=self.from_broker_token(r), side=side_from(r["transaction_type"]),
            quantity=as_int(r["quantity"]), filled_quantity=as_int(r.get("filled_quantity")), price=num(r.get("price")),
            trigger_price=num(r.get("trigger_price")), average_price=num(r.get("average_price")),
            order_type=order_type_from(r.get("order_type")), product=product_from(r.get("product")),
            status=status_from(r.get("status")), status_message=r.get("status_message"), tag=r.get("tag"),
            ts=parse_ts(r.get("order_timestamp")),
        ) for r in rows]

    def from_broker_token(self, r: dict[str, Any]) -> str:
        from broker_gateway.symbols import TOKENS

        return TOKENS.symbol(self.name, str(r.get("instrument_token", ""))) or self._sym(r)

    async def get_trade_book(self) -> list[Trade]:
        rows = (await self.request("GET", "/v2/order/trades/get-trades-for-day")).get("data") or []
        return [Trade(broker_trade_id=str(r["trade_id"]), broker_order_id=str(r["order_id"]), symbol=self.from_broker_token(r),
                      side=side_from(r["transaction_type"]), quantity=as_int(r["quantity"]), price=num(r["average_price"]),
                      product=product_from(r.get("product")), ts=parse_ts(r.get("order_timestamp"))) for r in rows]

    async def get_positions(self) -> list[Position]:
        rows = (await self.request("GET", "/v2/portfolio/short-term-positions")).get("data") or []
        return [Position(symbol=self.from_broker_token(r), product=product_from(r.get("product")), quantity=as_int(r["quantity"]),
                         average_price=num(r.get("average_price")), last_price=num(r.get("last_price")),
                         realised_pnl=num(r.get("realised")), unrealised_pnl=num(r.get("unrealised")), broker=self.name)
                for r in rows]

    async def get_holdings(self) -> list[Holding]:
        rows = (await self.request("GET", "/v2/portfolio/long-term-holdings")).get("data") or []
        return [Holding(symbol=self.from_broker_token(r), quantity=as_int(r["quantity"]), average_price=num(r["average_price"]),
                        last_price=num(r.get("last_price")), pnl=num(r.get("pnl")), isin=r.get("isin"), broker=self.name)
                for r in rows]

    async def get_funds(self) -> Funds:
        d = (await self.request("GET", "/v2/user/get-funds-and-margin")).get("data") or {}
        eq = d.get("equity") or {}
        avail, used = num(eq.get("available_margin")), num(eq.get("used_margin"))
        return Funds(available=avail, used=used, total=avail + used)

    async def get_profile(self) -> Profile:
        d = (await self.request("GET", "/v2/user/profile")).get("data") or {}
        return Profile(user_id=str(d.get("user_id", "")), name=d.get("user_name", ""), email=d.get("email"),
                       broker=self.name, exchanges=d.get("exchanges", []))
