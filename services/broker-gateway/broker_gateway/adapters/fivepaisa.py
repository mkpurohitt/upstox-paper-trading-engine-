"""5paisa OpenAPI (TOTP login -> RequestToken -> AccessToken; head/body JSON envelopes)."""

from __future__ import annotations

from typing import Any, ClassVar

from broker_gateway.adapters._common import parse_ts, side_from, status_from
from broker_gateway.adapters._totp import resolve_totp
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

STATUS = {"fully executed": OrderStatus.COMPLETE, "pending": OrderStatus.OPEN, "rejected by 5p": OrderStatus.REJECTED,
          "rejected by exch": OrderStatus.REJECTED, "cancelled": OrderStatus.CANCELLED, "partially executed": OrderStatus.OPEN}
SVC = "/VendorsAPI/Service1.svc"


class FivePaisaAdapter(HttpBrokerAdapter):
    name = "fivepaisa"
    display_name = "5paisa"
    auth_type = "totp"
    base_url = "https://Openapi.5paisa.com"
    docs_url = "https://www.5paisa.com/developerapi/overview"
    rate_limit_per_sec = 9.0
    credential_fields: ClassVar = [
        CredentialField(name="api_key", label="User key"),
        CredentialField(name="encryption_key", label="Encryption key", secret=True),
        CredentialField(name="user_id", label="User ID"),
        CredentialField(name="client_id", label="Client code"),
        CredentialField(name="pin", label="PIN", secret=True),
        CredentialField(name="totp_secret", label="TOTP secret (optional)", secret=True, required=False),
    ]

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.session.get("access_token"):
            h["Authorization"] = f"bearer {self.session['access_token']}"
        return h

    def _body(self, resp: dict[str, Any]) -> dict[str, Any]:
        b = resp.get("body") or {}
        if isinstance(b, dict) and str(b.get("Status", "0")) not in ("0", "None"):
            raise BrokerError(f"5paisa: {b.get('Message') or b}")
        return b

    async def login(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        key = self.credentials["api_key"]
        r1 = self._body(await self.request("POST", f"{SVC}/TOTPLogin", json={"head": {"Key": key}, "body": {
            "Email_ID": self.credentials["client_id"], "TOTP": resolve_totp(self.credentials, inputs), "PIN": self.credentials["pin"]}}))
        r2 = self._body(await self.request("POST", f"{SVC}/GetAccessToken", json={"head": {"Key": key}, "body": {
            "RequestToken": r1.get("RequestToken"), "EncryKey": self.credentials["encryption_key"], "UserId": self.credentials["user_id"]}}))
        if not r2.get("AccessToken"):
            raise BrokerError("5paisa access token missing")
        self.session = {"access_token": r2["AccessToken"], "client_code": r2.get("ClientCode", self.credentials["client_id"])}
        return self.session

    def _env(self, body: dict[str, Any]) -> dict[str, Any]:
        return {"head": {"key": self.credentials["api_key"]}, "body": {"ClientCode": self.session.get("client_code", ""), **body}}

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        m = self.symbol_map(req.symbol)
        if not m.get("token"):
            raise BrokerError(f"No 5paisa ScripCode for {req.symbol}; refresh the 5paisa scrip master")
        market = req.order_type in (OrderType.MARKET, OrderType.SL_M)
        return {
            "Exchange": m["exchange"], "ExchangeType": m["exchange_type"], "ScripCode": int(m["token"]), "ScripData": "",
            "Price": 0 if market else (req.price or 0), "OrderType": req.side.value, "Qty": req.quantity,
            "DisQty": 0, "StopLossPrice": req.trigger_price or 0, "IsIntraday": req.product == Product.MIS,
            "iOrderValidity": 0, "AHPlaced": "N", "RemoteOrderID": (req.tag or req.algo_id or "algodesk")[:20],
        }

    async def place_order(self, req: OrderRequest) -> OrderAck:
        b = self._body(await self.request("POST", f"{SVC}/V1/PlaceOrderRequest", json=self._env(self.to_payload(req))))
        return OrderAck(broker_order_id=str(b.get("ExchOrderID") or b.get("BrokerOrderID")), message=b.get("Message"))

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        body = {"ExchOrderID": broker_order_id}
        if req.quantity:
            body["Qty"] = req.quantity  # type: ignore[assignment]
        if req.price is not None:
            body["Price"] = req.price  # type: ignore[assignment]
        if req.trigger_price is not None:
            body["StopLossPrice"] = req.trigger_price  # type: ignore[assignment]
        self._body(await self.request("POST", f"{SVC}/V1/ModifyOrderRequest", json=self._env(body)))
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        self._body(await self.request("POST", f"{SVC}/V1/CancelOrderRequest", json=self._env({"ExchOrderID": broker_order_id})))
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    def _sym(self, r: dict[str, Any]) -> str:
        from broker_gateway.symbols import TOKENS

        hit = TOKENS.symbol(self.name, str(r.get("ScripCode", "")))
        if hit:
            return hit
        ex = {"N": "NSE", "B": "BSE", "M": "MCX"}.get(str(r.get("Exch", "N")), "NSE")
        if str(r.get("ExchType", "C")) == "D":
            ex = {"NSE": "NFO", "BSE": "BFO"}.get(ex, ex)
        return f"{ex}:{str(r.get('ScripName') or r.get('Symbol', '')).split(' ')[0]}"

    async def get_order_book(self) -> list[Order]:
        rows = self._body(await self.request("POST", f"{SVC}/V3/OrderBook", json=self._env({}))).get("OrderBookDetail") or []
        return [Order(
            broker_order_id=str(r.get("ExchOrderID") or r.get("BrokerOrderId")), symbol=self._sym(r), side=side_from(r.get("BuySell")),
            quantity=as_int(r.get("Qty")), filled_quantity=as_int(r.get("TradedQty")), price=num(r.get("Rate")),
            trigger_price=num(r.get("SLTriggerRate")), average_price=num(r.get("AveragePrice")),
            order_type=OrderType.MARKET if r.get("AtMarket") == "Y" else (OrderType.SL if num(r.get("SLTriggerRate")) else OrderType.LIMIT),
            product=Product.MIS if r.get("DelvIntra") == "I" else Product.CNC, status=status_from(r.get("OrderStatus"), STATUS),
            status_message=r.get("Reason"), ts=parse_ts(r.get("BrokerOrderTime")),
        ) for r in rows]

    async def get_trade_book(self) -> list[Trade]:
        rows = self._body(await self.request("POST", f"{SVC}/V1/TradeBook", json=self._env({}))).get("TradeBookDetail") or []
        return [Trade(broker_trade_id=str(r.get("ExchangeTradeID")), broker_order_id=str(r.get("ExchOrderID")), symbol=self._sym(r),
                      side=side_from(r.get("BuySell")), quantity=as_int(r.get("Qty")), price=num(r.get("Rate")),
                      product=Product.MIS if r.get("DelvIntra") == "I" else Product.CNC) for r in rows]

    async def get_positions(self) -> list[Position]:
        rows = self._body(await self.request("POST", f"{SVC}/V2/NetPositionNetWise", json=self._env({}))).get("NetPositionDetail") or []
        return [Position(symbol=self._sym(r), product=Product.MIS if r.get("OrderFor") == "I" else Product.NRML,
                         quantity=as_int(r.get("NetQty")), average_price=num(r.get("AvgRate")), last_price=num(r.get("LTP")),
                         realised_pnl=num(r.get("BookedPL")), unrealised_pnl=num(r.get("MTOM")), broker=self.name) for r in rows]

    async def get_holdings(self) -> list[Holding]:
        rows = self._body(await self.request("POST", f"{SVC}/V3/Holding", json=self._env({}))).get("Data") or []
        return [Holding(symbol=self._sym(r), quantity=as_int(r.get("Quantity")), average_price=num(r.get("AvgRate")),
                        last_price=num(r.get("CurrentPrice")), broker=self.name) for r in rows]

    async def get_funds(self) -> Funds:
        b = self._body(await self.request("POST", f"{SVC}/V4/Margin", json=self._env({})))
        eq = (b.get("EquityMargin") or [{}])[0]
        avail, used = num(eq.get("NetAvailableMargin")), num(eq.get("MarginUtilized"))
        return Funds(available=avail, used=used, total=avail + used)

    async def get_profile(self) -> Profile:
        return Profile(user_id=str(self.session.get("client_code") or self.credentials.get("client_id", "")), broker=self.name)


_ = Side
