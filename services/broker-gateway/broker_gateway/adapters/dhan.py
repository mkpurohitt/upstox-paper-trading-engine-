"""Dhan API v2 (client id + access token)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from broker_gateway.adapters._common import order_type_from, parse_ts, product_from, side_from, status_from
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

ORDER_TYPE = {OrderType.MARKET: "MARKET", OrderType.LIMIT: "LIMIT", OrderType.SL: "STOP_LOSS", OrderType.SL_M: "STOP_LOSS_MARKET"}
PRODUCT = {Product.MIS: "INTRADAY", Product.CNC: "CNC", Product.NRML: "MARGIN"}
STATUS = {"transit": OrderStatus.PENDING, "pending": OrderStatus.OPEN, "traded": OrderStatus.COMPLETE,
          "part traded": OrderStatus.OPEN, "expired": OrderStatus.CANCELLED}


class DhanAdapter(HttpBrokerAdapter):
    name = "dhan"
    display_name = "Dhan"
    auth_type = "token"
    base_url = "https://api.dhan.co"
    docs_url = "https://dhanhq.co/docs/v2/"
    rate_limit_per_sec = 9.0
    credential_fields: ClassVar = [
        CredentialField(name="client_id", label="Dhan client ID"),
        CredentialField(name="access_token", label="Access token (from web.dhan.co -> DhanHQ APIs)", secret=True),
    ]

    def headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json",
                "access-token": str(self.session.get("access_token") or self.credentials.get("access_token", "")),
                "client-id": str(self.credentials.get("client_id", ""))}

    async def login(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        self.session = {"access_token": self.credentials["access_token"]}
        await self.get_funds()  # validates the token
        return self.session

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        m = self.symbol_map(req.symbol)
        if not m.get("token"):
            raise BrokerError(f"No Dhan securityId for {req.symbol}; refresh the Dhan instrument master")
        return {
            "dhanClientId": self.credentials["client_id"], "correlationId": (req.tag or uuid.uuid4().hex)[:25],
            "transactionType": req.side.value, "exchangeSegment": m["exchange"], "productType": PRODUCT[req.product],
            "orderType": ORDER_TYPE[req.order_type], "validity": req.validity, "securityId": str(m["token"]),
            "quantity": req.quantity, "disclosedQuantity": 0, "price": req.price or 0, "triggerPrice": req.trigger_price or 0,
            "afterMarketOrder": False,
        }

    async def place_order(self, req: OrderRequest) -> OrderAck:
        body = await self.request("POST", "/v2/orders", json=self.to_payload(req))
        return OrderAck(broker_order_id=str(body["orderId"]), status=status_from(body.get("orderStatus"), STATUS))

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        ot = req.order_type or (original.order_type if original else OrderType.LIMIT)
        payload = {"dhanClientId": self.credentials["client_id"], "orderId": broker_order_id, "orderType": ORDER_TYPE[ot],
                   "legName": "", "quantity": req.quantity or (original.quantity if original else 0),
                   "price": req.price if req.price is not None else (original.price if original else 0) or 0,
                   "disclosedQuantity": 0, "triggerPrice": req.trigger_price or 0, "validity": "DAY"}
        body = await self.request("PUT", f"/v2/orders/{broker_order_id}", json=payload)
        return OrderAck(broker_order_id=str(body.get("orderId", broker_order_id)), status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        await self.request("DELETE", f"/v2/orders/{broker_order_id}")
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    def _sym(self, r: dict[str, Any]) -> str:
        from broker_gateway.symbols import TOKENS

        return TOKENS.symbol(self.name, str(r.get("securityId", ""))) or self.from_broker(r.get("exchangeSegment", "NSE"),
                                                                                         r.get("tradingSymbol", ""))

    async def get_order_book(self) -> list[Order]:
        rows = await self.request("GET", "/v2/orders") or []
        return [Order(
            broker_order_id=str(r["orderId"]), symbol=self._sym(r), side=side_from(r["transactionType"]), quantity=as_int(r["quantity"]),
            filled_quantity=as_int(r.get("filledQty")), price=num(r.get("price")), trigger_price=num(r.get("triggerPrice")),
            average_price=num(r.get("averageTradedPrice")), order_type=order_type_from(r.get("orderType")),
            product=product_from(r.get("productType")), status=status_from(r.get("orderStatus"), STATUS),
            status_message=r.get("omsErrorDescription"), tag=r.get("correlationId"), ts=parse_ts(r.get("createTime")),
        ) for r in rows]

    async def get_trade_book(self) -> list[Trade]:
        rows = await self.request("GET", "/v2/trades") or []
        return [Trade(broker_trade_id=str(r.get("exchangeTradeId")), broker_order_id=str(r["orderId"]), symbol=self._sym(r),
                      side=side_from(r["transactionType"]), quantity=as_int(r.get("tradedQuantity")), price=num(r.get("tradedPrice")),
                      product=product_from(r.get("productType")), ts=parse_ts(r.get("exchangeTime"))) for r in rows]

    async def get_positions(self) -> list[Position]:
        rows = await self.request("GET", "/v2/positions") or []
        return [Position(symbol=self._sym(r), product=product_from(r.get("productType")), quantity=as_int(r.get("netQty")),
                         average_price=num(r.get("costPrice", r.get("buyAvg"))), last_price=0.0,
                         realised_pnl=num(r.get("realizedProfit")), unrealised_pnl=num(r.get("unrealizedProfit")), broker=self.name)
                for r in rows]

    async def get_holdings(self) -> list[Holding]:
        rows = await self.request("GET", "/v2/holdings") or []
        rows = rows if isinstance(rows, list) else []
        return [Holding(symbol=self._sym({**r, "exchangeSegment": r.get("exchange", "NSE")}), quantity=as_int(r.get("totalQty")),
                        average_price=num(r.get("avgCostPrice")), isin=r.get("isin"), broker=self.name) for r in rows]

    async def get_funds(self) -> Funds:
        d = await self.request("GET", "/v2/fundlimit") or {}
        avail = num(d.get("availabelBalance", d.get("availableBalance")))  # API field is misspelt upstream
        used = num(d.get("utilizedAmount"))
        return Funds(available=avail, used=used, total=avail + used)

    async def get_profile(self) -> Profile:
        d = await self.request("GET", "/v2/profile") or {}
        return Profile(user_id=str(d.get("dhanClientId", self.credentials.get("client_id", ""))), broker=self.name)
