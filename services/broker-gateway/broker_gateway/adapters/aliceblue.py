"""Alice Blue open-api v2 (vendor login: sha256(userId+authCode+apiSecret) -> userSession)."""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar

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
    OrderType,
    Position,
    Product,
    Profile,
    Trade,
)

PRODUCT = {Product.CNC: "LONGTERM", Product.NRML: "NRML", Product.MIS: "INTRADAY"}
ORDER_TYPE = {OrderType.MARKET: "MARKET", OrderType.LIMIT: "LIMIT", OrderType.SL: "SL", OrderType.SL_M: "SLM"}
OD = "/open-api/od/v1"


class AliceBlueAdapter(HttpBrokerAdapter):
    name = "aliceblue"
    display_name = "Alice Blue"
    auth_type = "oauth"
    base_url = "https://a3.aliceblueonline.com"
    docs_url = "https://v2api.aliceblueonline.com"
    rate_limit_per_sec = 2.0  # 1800 requests / 15 min budget upstream
    credential_fields: ClassVar = [
        CredentialField(name="app_code", label="App code"),
        CredentialField(name="api_secret", label="API secret", secret=True),
    ]

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.session.get("access_token"):
            h["Authorization"] = f"Bearer {self.session['access_token']}"
        return h

    def login_url(self, state: str, redirect_uri: str) -> str:
        return f"https://ant.aliceblueonline.com/?appcode={self.credentials['app_code']}&state={state}"

    async def oauth_callback(self, params: dict[str, str], redirect_uri: str) -> dict[str, Any]:
        user_id, auth_code = params["userId"], params["authCode"]
        checksum = hashlib.sha256(f"{user_id}{auth_code}{self.credentials['api_secret']}".encode()).hexdigest()
        body = await self.request("POST", "https://ant.aliceblueonline.com/open-api/od/v1/vendor/getUserDetails",
                                  json={"checkSum": checksum})
        tok = body.get("userSession")
        if not tok:
            raise BrokerError(f"Alice Blue login failed: {self.error_message(body)}")
        self.session = {"access_token": tok, "user_id": user_id, "expires_at": day_end_expiry().isoformat()}
        return self.session

    @staticmethod
    def _result(body: Any) -> Any:
        if isinstance(body, dict):
            if str(body.get("status", "Ok")).lower() in ("not_ok", "error"):
                raise BrokerError(f"Alice Blue: {body.get('message')}")
            return body.get("result", body)
        return body

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        m = self.symbol_map(req.symbol)
        if not m.get("token"):
            raise BrokerError(f"No Alice Blue instrumentId for {req.symbol}; refresh the contract master")
        return {"exchange": m["exchange"], "instrumentId": str(m["token"]), "transactionType": req.side.value,
                "quantity": req.quantity, "product": PRODUCT[req.product], "orderComplexity": "REGULAR",
                "orderType": ORDER_TYPE[req.order_type], "validity": req.validity, "price": str(req.price or 0),
                "slTriggerPrice": str(req.trigger_price or 0), "disclosedQuantity": "0",
                "orderTag": (req.tag or req.algo_id or "algodesk")[:20]}

    async def place_order(self, req: OrderRequest) -> OrderAck:
        res = self._result(await self.request("POST", f"{OD}/orders/placeorder", json=[self.to_payload(req)]))
        first = res[0] if isinstance(res, list) and res else res
        return OrderAck(broker_order_id=str(first.get("brokerOrderId")))

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        ot = req.order_type or (original.order_type if original else OrderType.LIMIT)
        self._result(await self.request("POST", f"{OD}/orders/modify", json={
            "brokerOrderId": broker_order_id, "quantity": req.quantity or (original.quantity if original else 0),
            "orderType": ORDER_TYPE[ot], "price": str(req.price or 0), "slTriggerPrice": str(req.trigger_price or 0),
            "validity": "DAY", "disclosedQuantity": "0"}))
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        self._result(await self.request("POST", f"{OD}/orders/cancel", json={"brokerOrderId": broker_order_id}))
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    def _sym(self, r: dict[str, Any]) -> str:
        from broker_gateway.symbols import TOKENS

        return TOKENS.symbol(self.name, str(r.get("instrumentId", ""))) or self.from_broker(r.get("exchange", "NSE"),
                                                                                           r.get("tradingSymbol", ""))

    async def get_order_book(self) -> list[Order]:
        rows = self._result(await self.request("GET", f"{OD}/orders/book")) or []
        return [Order(
            broker_order_id=str(r["brokerOrderId"]), symbol=self._sym(r), side=side_from(r.get("transactionType")),
            quantity=as_int(r.get("quantity")), filled_quantity=as_int(r.get("filledQuantity")), price=num(r.get("price")),
            trigger_price=num(r.get("slTriggerPrice")), average_price=num(r.get("averageTradedPrice")),
            order_type=order_type_from(r.get("orderType")), product=product_from(r.get("product")),
            status=status_from(r.get("orderStatus")), status_message=r.get("rejectionReason"), tag=r.get("orderTag"),
            ts=parse_ts(r.get("orderTime")),
        ) for r in rows]

    async def get_trade_book(self) -> list[Trade]:
        rows = self._result(await self.request("GET", f"{OD}/orders/trades")) or []
        return [Trade(broker_trade_id=str(r.get("fillId", r.get("brokerOrderId"))), broker_order_id=str(r.get("brokerOrderId")),
                      symbol=self._sym(r), side=side_from(r.get("transactionType")), quantity=as_int(r.get("filledQuantity")),
                      price=num(r.get("averageTradedPrice")), product=product_from(r.get("product"))) for r in rows]

    async def get_positions(self) -> list[Position]:
        rows = self._result(await self.request("GET", f"{OD}/positions")) or []
        return [Position(symbol=self._sym(r), product=product_from(r.get("product")), quantity=as_int(r.get("netQuantity")),
                         average_price=num(r.get("netAveragePrice")), last_price=num(r.get("ltp")),
                         realised_pnl=num(r.get("realizedPnl")), unrealised_pnl=num(r.get("unrealizedPnl")), broker=self.name)
                for r in rows]

    async def get_holdings(self) -> list[Holding]:
        rows = self._result(await self.request("GET", f"{OD}/holdings/CNC")) or []
        return [Holding(symbol=self._sym(r), quantity=as_int(r.get("totalQuantity", r.get("quantity"))),
                        average_price=num(r.get("averagePrice")), last_price=num(r.get("ltp")), broker=self.name) for r in rows]

    async def get_funds(self) -> Funds:
        res = self._result(await self.request("GET", f"{OD}/limits/"))
        d = res[0] if isinstance(res, list) and res else (res or {})
        avail, used = num(d.get("tradingLimit", d.get("netAvailableMargin"))), num(d.get("utilizedMargin"))
        return Funds(available=avail, used=used, total=avail + used)

    async def get_profile(self) -> Profile:
        return Profile(user_id=str(self.session.get("user_id", "")), broker=self.name)
