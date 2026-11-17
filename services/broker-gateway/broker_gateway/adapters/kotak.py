"""Kotak Neo Trade API v2 (UCC + mobile + TOTP, then MPIN validate; jData form bodies)."""

from __future__ import annotations

import json
from typing import Any, ClassVar
from urllib.parse import quote

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
    Profile,
    Side,
    Trade,
)

PT = {OrderType.MARKET: "MKT", OrderType.LIMIT: "L", OrderType.SL: "SL", OrderType.SL_M: "SL-M"}
LOGIN_BASE = "https://mis.kotaksecurities.com"


class KotakAdapter(HttpBrokerAdapter):
    name = "kotak"
    display_name = "Kotak Neo"
    auth_type = "totp"
    base_url = "https://cis.kotaksecurities.com"
    docs_url = "https://github.com/Kotak-Neo/kotak-neo-api"
    rate_limit_per_sec = 9.0
    credential_fields: ClassVar = [
        CredentialField(name="access_token", label="Consumer access token (Neo app -> Invest -> Trade API)", secret=True),
        CredentialField(name="client_id", label="UCC (client code)"),
        CredentialField(name="mobile", label="Registered mobile (+91...)"),
        CredentialField(name="mpin", label="MPIN", secret=True),
        CredentialField(name="totp_secret", label="TOTP secret (optional)", secret=True, required=False),
    ]

    def headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "neo-fin-key": "neotradeapi"}
        if self.session.get("access_token"):
            h.update({"Sid": str(self.session.get("sid", "")), "Auth": str(self.session["access_token"])})
        return h

    async def login(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        h = {"Authorization": str(self.credentials["access_token"]), "neo-fin-key": "neotradeapi", "Content-Type": "application/json"}
        r1 = await self.request("POST", f"{LOGIN_BASE}/login/1.0/tradeApiLogin", headers=h, json={
            "mobileNumber": self.credentials["mobile"], "ucc": self.credentials["client_id"],
            "totp": resolve_totp(self.credentials, inputs)})
        d1 = r1.get("data") or {}
        r2 = await self.request("POST", f"{LOGIN_BASE}/login/1.0/tradeApiValidate",
                                headers={**h, "sid": str(d1.get("sid", "")), "Auth": str(d1.get("token", ""))},
                                json={"mpin": self.credentials["mpin"]})
        d2 = r2.get("data") or {}
        if not d2.get("token"):
            raise BrokerError("Kotak MPIN validation failed")
        self.session = {"access_token": d2["token"], "sid": d2.get("sid"), "base_url": d2.get("baseUrl") or self.base_url,
                        "expires_at": day_end_expiry().isoformat()}
        return self.session

    async def _form(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = self.session.get("base_url") or self.base_url
        body = await self.request("POST", f"{base}{path}", content=f"jData={quote(json.dumps(payload))}",
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        if str(body.get("stat", "Ok")).lower() == "not_ok":
            raise BrokerError(f"Kotak: {body.get('emsg') or body.get('errMsg')}")
        return body

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        m = self.symbol_map(req.symbol)
        return {"am": "NO", "dq": "0", "es": m["exchange"], "mp": "0", "pc": req.product.value, "pf": "N",
                "pr": str(req.price or 0), "pt": PT[req.order_type], "qt": str(req.quantity), "rt": req.validity,
                "tp": str(req.trigger_price or 0), "ts": m["tradingsymbol"], "tt": "B" if req.side == Side.BUY else "S"}

    async def place_order(self, req: OrderRequest) -> OrderAck:
        body = await self._form("/quick/order/rule/ms/place", self.to_payload(req))
        return OrderAck(broker_order_id=str(body["nOrdNo"]))

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        if original is None:
            raise BrokerError("Kotak modify needs the original order")
        m = self.symbol_map(original.symbol)
        ot = req.order_type or original.order_type
        await self._form("/quick/order/vr/modify", {
            "no": broker_order_id, "am": "NO", "es": m["exchange"], "ts": m["tradingsymbol"], "pc": original.product.value,
            "pt": PT[ot], "qt": str(req.quantity or original.quantity), "pr": str(req.price if req.price is not None else original.price or 0),
            "tp": str(req.trigger_price or original.trigger_price or 0), "tt": "B" if original.side == Side.BUY else "S",
            "vd": "DAY", "dq": "0", "mp": "0"})
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        await self._form("/quick/order/cancel", {"on": broker_order_id, "am": "NO"})
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    async def _get(self, path: str) -> list[dict[str, Any]]:
        base = self.session.get("base_url") or self.base_url
        body = await self.request("GET", f"{base}{path}")
        d = body.get("data")
        return d if isinstance(d, list) else []

    async def get_order_book(self) -> list[Order]:
        return [Order(
            broker_order_id=str(r["nOrdNo"]), symbol=self.from_broker(r.get("exSeg", "nse_cm"), r.get("trdSym", "")),
            side=side_from(r.get("trnsTp")), quantity=as_int(r.get("qty")), filled_quantity=as_int(r.get("fldQty")),
            price=num(r.get("prc")), trigger_price=num(r.get("trgPrc")), average_price=num(r.get("avgPrc")),
            order_type=order_type_from(r.get("prcTp")), product=product_from(r.get("prod")), status=status_from(r.get("ordSt")),
            status_message=r.get("rejRsn"), ts=parse_ts(r.get("ordDtTm")),
        ) for r in await self._get("/quick/user/orders")]

    async def get_trade_book(self) -> list[Trade]:
        return [Trade(broker_trade_id=str(r.get("flId", r.get("nOrdNo"))), broker_order_id=str(r["nOrdNo"]),
                      symbol=self.from_broker(r.get("exSeg", "nse_cm"), r.get("trdSym", "")), side=side_from(r.get("trnsTp")),
                      quantity=as_int(r.get("fldQty")), price=num(r.get("avgPrc")), product=product_from(r.get("prod")),
                      ts=parse_ts(r.get("flDtTm"))) for r in await self._get("/quick/user/trades")]

    async def get_positions(self) -> list[Position]:
        out = []
        for r in await self._get("/quick/user/positions"):
            buy = as_int(r.get("flBuyQty")) + as_int(r.get("cfBuyQty"))
            sell = as_int(r.get("flSellQty")) + as_int(r.get("cfSellQty"))
            buy_amt = num(r.get("buyAmt")) + num(r.get("cfBuyAmt"))
            sell_amt = num(r.get("sellAmt")) + num(r.get("cfSellAmt"))
            net = buy - sell
            avg = (buy_amt / buy if net > 0 and buy else sell_amt / sell if net < 0 and sell else 0.0)
            out.append(Position(symbol=self.from_broker(r.get("exSeg", "nse_cm"), r.get("trdSym", "")), product=product_from(r.get("prod")),
                                quantity=net, average_price=avg, realised_pnl=(sell_amt - buy_amt) if net == 0 else 0.0, broker=self.name))
        return out

    async def get_holdings(self) -> list[Holding]:
        return [Holding(symbol=self.from_broker(r.get("exchangeSegment", "nse_cm"), r.get("displaySymbol", "")),
                        quantity=as_int(r.get("quantity")), average_price=num(r.get("averagePrice")), last_price=num(r.get("closingPrice")),
                        broker=self.name) for r in await self._get("/portfolio/v1/holdings")]

    async def get_funds(self) -> Funds:
        body = await self._form("/quick/user/limits", {"seg": "ALL", "exch": "ALL", "prod": "ALL"})
        avail = num(body.get("Net"))
        used = num(body.get("MarginUsed"))
        return Funds(available=avail, used=used, total=avail + used)

    async def get_profile(self) -> Profile:
        return Profile(user_id=str(self.credentials.get("client_id", "")), broker=self.name)
