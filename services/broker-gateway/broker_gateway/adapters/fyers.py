"""Fyers API v3 (auth-code + appIdHash = sha256(app_id:secret))."""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar
from urllib.parse import urlencode

from broker_gateway.adapters._common import day_end_expiry, parse_ts, product_from
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
    OrderType,
    Position,
    Product,
    Profile,
    Side,
    Trade,
)

TYPE = {OrderType.LIMIT: 1, OrderType.MARKET: 2, OrderType.SL_M: 3, OrderType.SL: 4}
TYPE_REV = {v: k for k, v in TYPE.items()}
PRODUCT = {Product.MIS: "INTRADAY", Product.CNC: "CNC", Product.NRML: "MARGIN"}
STATUS = {1: OrderStatus.CANCELLED, 2: OrderStatus.COMPLETE, 4: OrderStatus.PENDING, 5: OrderStatus.REJECTED, 6: OrderStatus.OPEN,
          7: OrderStatus.REJECTED}


class FyersAdapter(HttpBrokerAdapter):
    name = "fyers"
    display_name = "Fyers"
    auth_type = "oauth"
    base_url = "https://api-t1.fyers.in"
    docs_url = "https://myapi.fyers.in/docsv3"
    rate_limit_per_sec = 9.0
    credential_fields: ClassVar = [
        CredentialField(name="api_key", label="App ID (e.g. XB12345-100)"),
        CredentialField(name="api_secret", label="Secret ID", secret=True),
    ]

    def headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.session.get("access_token"):
            h["Authorization"] = f"{self.credentials.get('api_key')}:{self.session['access_token']}"
        return h

    def login_url(self, state: str, redirect_uri: str) -> str:
        q = urlencode({"client_id": self.credentials["api_key"], "redirect_uri": redirect_uri, "response_type": "code", "state": state})
        return f"{self.base_url}/api/v3/generate-authcode?{q}"

    async def oauth_callback(self, params: dict[str, str], redirect_uri: str) -> dict[str, Any]:
        app_hash = hashlib.sha256(f"{self.credentials['api_key']}:{self.credentials['api_secret']}".encode()).hexdigest()
        body = await self.request("POST", "/api/v3/validate-authcode",
                                  json={"grant_type": "authorization_code", "appIdHash": app_hash, "code": params["auth_code"]})
        if body.get("s") != "ok":
            raise BrokerError(f"Fyers auth failed: {body.get('message')}")
        self.session = {"access_token": body["access_token"], "expires_at": day_end_expiry().isoformat()}
        return self.session

    def _check(self, body: dict[str, Any]) -> dict[str, Any]:
        if body.get("s") not in ("ok", None):
            raise BrokerError(f"Fyers: {body.get('message', body)}")
        return body

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        return {
            "symbol": self.symbol_map(req.symbol)["tradingsymbol"], "qty": req.quantity, "type": TYPE[req.order_type],
            "side": 1 if req.side == Side.BUY else -1, "productType": PRODUCT[req.product], "limitPrice": req.price or 0,
            "stopPrice": req.trigger_price or 0, "validity": req.validity, "disclosedQty": 0, "offlineOrder": False,
            "stopLoss": 0, "takeProfit": 0, "orderTag": "".join(ch for ch in (req.tag or req.algo_id or "algodesk") if ch.isalnum())[:20],
        }

    async def place_order(self, req: OrderRequest) -> OrderAck:
        body = self._check(await self.request("POST", "/api/v3/orders/sync", json=self.to_payload(req)))
        return OrderAck(broker_order_id=str(body["id"]))

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        p: dict[str, Any] = {"id": broker_order_id}
        if req.quantity:
            p["qty"] = req.quantity
        if req.price is not None:
            p["limitPrice"] = req.price
        if req.trigger_price is not None:
            p["stopPrice"] = req.trigger_price
        if req.order_type:
            p["type"] = TYPE[req.order_type]
        self._check(await self.request("PATCH", "/api/v3/orders/sync", json=p))
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        self._check(await self.request("DELETE", "/api/v3/orders/sync", json={"id": broker_order_id}))
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    async def get_order_book(self) -> list[Order]:
        rows = self._check(await self.request("GET", "/api/v3/orders")).get("orderBook") or []
        return [Order(
            broker_order_id=str(r["id"]), symbol=self.from_broker("", r["symbol"]), side=Side.BUY if r["side"] == 1 else Side.SELL,
            quantity=as_int(r["qty"]), filled_quantity=as_int(r.get("filledQty")), price=num(r.get("limitPrice")),
            trigger_price=num(r.get("stopPrice")), average_price=num(r.get("tradedPrice")),
            order_type=TYPE_REV.get(as_int(r.get("type")), OrderType.MARKET), product=product_from(r.get("productType")),
            status=STATUS.get(as_int(r.get("status")), OrderStatus.OPEN), status_message=r.get("message"),
            tag=r.get("orderTag"), ts=parse_ts(r.get("orderDateTime")),
        ) for r in rows]

    async def get_trade_book(self) -> list[Trade]:
        rows = self._check(await self.request("GET", "/api/v3/tradebook")).get("tradeBook") or []
        return [Trade(broker_trade_id=str(r.get("tradeNumber", r.get("id"))), broker_order_id=str(r.get("orderNumber", r.get("id"))),
                      symbol=self.from_broker("", r["symbol"]), side=Side.BUY if r["side"] == 1 else Side.SELL,
                      quantity=as_int(r.get("tradedQty")), price=num(r.get("tradePrice")), product=product_from(r.get("productType")),
                      ts=parse_ts(r.get("orderDateTime"))) for r in rows]

    async def get_positions(self) -> list[Position]:
        rows = self._check(await self.request("GET", "/api/v3/positions")).get("netPositions") or []
        return [Position(symbol=self.from_broker("", r["symbol"]), product=product_from(r.get("productType")),
                         quantity=as_int(r.get("netQty")), average_price=num(r.get("netAvg")), last_price=num(r.get("ltp")),
                         realised_pnl=num(r.get("realized_profit")), unrealised_pnl=num(r.get("unrealized_profit")), broker=self.name)
                for r in rows]

    async def get_holdings(self) -> list[Holding]:
        rows = self._check(await self.request("GET", "/api/v3/holdings")).get("holdings") or []
        return [Holding(symbol=self.from_broker("", r["symbol"]), quantity=as_int(r.get("quantity")), average_price=num(r.get("costPrice")),
                        last_price=num(r.get("ltp")), pnl=num(r.get("pl")), isin=r.get("isin"), broker=self.name) for r in rows]

    async def get_funds(self) -> Funds:
        rows = self._check(await self.request("GET", "/api/v3/funds")).get("fund_limit") or []
        by = {r.get("title", "").lower(): num(r.get("equityAmount")) for r in rows}
        avail, used = by.get("available balance", 0.0), by.get("utilized amount", 0.0)
        return Funds(available=avail, used=used, total=by.get("total balance", avail + used))

    async def get_profile(self) -> Profile:
        d = self._check(await self.request("GET", "/api/v3/profile")).get("data") or {}
        return Profile(user_id=str(d.get("fy_id", "")), name=d.get("name", ""), email=d.get("email_id"), broker=self.name)
