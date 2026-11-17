"""Angel One SmartAPI (client code + PIN + TOTP login, JWT session)."""

from __future__ import annotations

from typing import Any, ClassVar

from broker_gateway.adapters._common import (
    day_end_expiry,
    order_type_from,
    parse_ts,
    product_from,
    side_from,
    status_from,
)
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
    Trade,
)

ORDER_TYPE = {OrderType.MARKET: "MARKET", OrderType.LIMIT: "LIMIT", OrderType.SL: "STOPLOSS_LIMIT", OrderType.SL_M: "STOPLOSS_MARKET"}
PRODUCT = {Product.MIS: "INTRADAY", Product.CNC: "DELIVERY", Product.NRML: "CARRYFORWARD"}


class AngelAdapter(HttpBrokerAdapter):
    name = "angel"
    display_name = "Angel One (SmartAPI)"
    auth_type = "totp"
    base_url = "https://apiconnect.angelone.in"
    docs_url = "https://smartapi.angelbroking.com/docs"
    rate_limit_per_sec = 9.0
    credential_fields: ClassVar = [
        CredentialField(name="api_key", label="SmartAPI key"),
        CredentialField(name="client_id", label="Client code"),
        CredentialField(name="pin", label="Login PIN", secret=True),
        CredentialField(name="totp_secret", label="TOTP secret (optional, enables auto-login)", secret=True, required=False),
    ]

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json", "X-UserType": "USER", "X-SourceID": "WEB",
             "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1", "X-MACAddress": "00:00:00:00:00:00",
             "X-PrivateKey": str(self.credentials.get("api_key", ""))}
        if self.session.get("access_token"):
            h["Authorization"] = f"Bearer {self.session['access_token']}"
        return h

    def _data(self, body: dict[str, Any]) -> Any:
        if body.get("status") is False or (body.get("message") not in (None, "SUCCESS", "") and body.get("data") is None):
            raise BrokerError(f"Angel: {body.get('message')} ({body.get('errorcode', '')})")
        return body.get("data")

    async def login(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        body = await self.request("POST", "/rest/auth/angelbroking/user/v1/loginByPassword", json={
            "clientcode": self.credentials["client_id"], "password": self.credentials["pin"],
            "totp": resolve_totp(self.credentials, inputs)})
        d = self._data(body)
        self.session = {"access_token": d["jwtToken"], "refresh_token": d.get("refreshToken"), "feed_token": d.get("feedToken"),
                        "expires_at": day_end_expiry().isoformat()}
        return self.session

    async def refresh_session(self) -> dict[str, Any] | None:
        if not self.session.get("refresh_token"):
            return None
        d = self._data(await self.request("POST", "/rest/auth/angelbroking/jwt/v1/generateTokens",
                                          json={"refreshToken": self.session["refresh_token"]}))
        self.session.update(access_token=d["jwtToken"], refresh_token=d.get("refreshToken", self.session["refresh_token"]))
        return self.session

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        m = self.symbol_map(req.symbol)
        if not m.get("token"):
            raise BrokerError(f"No Angel symboltoken for {req.symbol}; refresh the Angel instrument master")
        return {
            "variety": "STOPLOSS" if req.order_type in (OrderType.SL, OrderType.SL_M) else "NORMAL",
            "tradingsymbol": m["tradingsymbol"], "symboltoken": m["token"], "transactiontype": req.side.value,
            "exchange": m["exchange"], "ordertype": ORDER_TYPE[req.order_type], "producttype": PRODUCT[req.product],
            "duration": req.validity, "price": str(req.price or 0), "triggerprice": str(req.trigger_price or 0),
            "squareoff": "0", "stoploss": "0", "quantity": str(req.quantity), "ordertag": (req.tag or req.algo_id or "")[:20],
        }

    async def place_order(self, req: OrderRequest) -> OrderAck:
        d = self._data(await self.request("POST", "/rest/secure/angelbroking/order/v1/placeOrder", json=self.to_payload(req)))
        return OrderAck(broker_order_id=str(d["orderid"]))

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        if original is None:
            raise BrokerError("Angel modify needs the original order")
        m = self.symbol_map(original.symbol)
        ot = req.order_type or original.order_type
        payload = {"variety": "STOPLOSS" if ot in (OrderType.SL, OrderType.SL_M) else "NORMAL", "orderid": broker_order_id,
                   "ordertype": ORDER_TYPE[ot], "producttype": PRODUCT[original.product], "duration": "DAY",
                   "price": str(req.price if req.price is not None else original.price or 0),
                   "triggerprice": str(req.trigger_price or original.trigger_price or 0),
                   "quantity": str(req.quantity or original.quantity), "tradingsymbol": m["tradingsymbol"],
                   "symboltoken": m["token"], "exchange": m["exchange"]}
        self._data(await self.request("POST", "/rest/secure/angelbroking/order/v1/modifyOrder", json=payload))
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        self._data(await self.request("POST", "/rest/secure/angelbroking/order/v1/cancelOrder",
                                      json={"variety": "NORMAL", "orderid": broker_order_id}))
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    def _sym(self, r: dict[str, Any]) -> str:
        from broker_gateway.symbols import TOKENS

        return TOKENS.symbol(self.name, str(r.get("symboltoken", ""))) or self.from_broker(r["exchange"], r["tradingsymbol"])

    async def get_order_book(self) -> list[Order]:
        rows = self._data(await self.request("GET", "/rest/secure/angelbroking/order/v1/getOrderBook")) or []
        return [Order(
            broker_order_id=str(r["orderid"]), symbol=self._sym(r), side=side_from(r["transactiontype"]), quantity=as_int(r["quantity"]),
            filled_quantity=as_int(r.get("filledshares")), price=num(r.get("price")), trigger_price=num(r.get("triggerprice")),
            average_price=num(r.get("averageprice")), order_type=order_type_from(r.get("ordertype")),
            product=product_from(r.get("producttype")), status=status_from(r.get("status") or r.get("orderstatus")),
            status_message=r.get("text"), tag=r.get("ordertag"), ts=parse_ts(r.get("updatetime")),
        ) for r in rows]

    async def get_trade_book(self) -> list[Trade]:
        rows = self._data(await self.request("GET", "/rest/secure/angelbroking/order/v1/getTradeBook")) or []
        return [Trade(broker_trade_id=str(r.get("fillid")), broker_order_id=str(r["orderid"]), symbol=self._sym(r),
                      side=side_from(r["transactiontype"]), quantity=as_int(r.get("fillsize")), price=num(r.get("fillprice")),
                      product=product_from(r.get("producttype")), ts=parse_ts(r.get("filltime"))) for r in rows]

    async def get_positions(self) -> list[Position]:
        rows = self._data(await self.request("GET", "/rest/secure/angelbroking/order/v1/getPosition")) or []
        return [Position(symbol=self._sym(r), product=product_from(r.get("producttype")), quantity=as_int(r.get("netqty")),
                         average_price=num(r.get("avgnetprice", r.get("netprice"))), last_price=num(r.get("ltp")),
                         realised_pnl=num(r.get("realised")), unrealised_pnl=num(r.get("unrealised", r.get("pnl"))), broker=self.name)
                for r in rows]

    async def get_holdings(self) -> list[Holding]:
        d = self._data(await self.request("GET", "/rest/secure/angelbroking/portfolio/v1/getAllHolding")) or {}
        rows = d.get("holdings", []) if isinstance(d, dict) else d
        return [Holding(symbol=self._sym(r), quantity=as_int(r.get("quantity")), average_price=num(r.get("averageprice")),
                        last_price=num(r.get("ltp")), pnl=num(r.get("profitandloss")), isin=r.get("isin"), broker=self.name)
                for r in rows]

    async def get_funds(self) -> Funds:
        d = self._data(await self.request("GET", "/rest/secure/angelbroking/user/v1/getRMS")) or {}
        avail, used = num(d.get("availablecash")), num(d.get("utiliseddebits"))
        return Funds(available=avail, used=used, total=num(d.get("net"), avail + used))

    async def get_profile(self) -> Profile:
        d = self._data(await self.request("GET", "/rest/secure/angelbroking/user/v1/getProfile")) or {}
        return Profile(user_id=d.get("clientcode", ""), name=d.get("name", ""), email=d.get("email"), broker=self.name,
                       exchanges=d.get("exchanges", []))
