"""Shoonya / Finvasia (Noren OMS; OAuth code -> GenAcsTok with sha256(client_id+secret+code); jData bodies)."""

from __future__ import annotations

import hashlib
import json
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
    OrderType,
    Position,
    Product,
    Profile,
    Side,
    Trade,
)

PRCTYP = {OrderType.MARKET: "MKT", OrderType.LIMIT: "LMT", OrderType.SL: "SL-LMT", OrderType.SL_M: "SL-MKT"}
PRD = {Product.CNC: "C", Product.NRML: "M", Product.MIS: "I"}
API = "/NorenWClientAPI"


class ShoonyaAdapter(HttpBrokerAdapter):
    name = "shoonya"
    display_name = "Shoonya (Finvasia)"
    auth_type = "oauth"
    base_url = "https://api.shoonya.com"
    docs_url = "https://shoonya.com/api-documentation"
    rate_limit_per_sec = 9.0
    credential_fields: ClassVar = [
        CredentialField(name="client_id", label="OAuth client ID"),
        CredentialField(name="api_secret", label="OAuth secret", secret=True),
        CredentialField(name="user_id", label="User ID (UID)"),
    ]

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        if self.session.get("access_token"):
            h["Authorization"] = f"Bearer {self.session['access_token']}"
        return h

    def login_url(self, state: str, redirect_uri: str) -> str:
        q = urlencode({"client_id": self.credentials["client_id"], "redirect_uri": redirect_uri, "state": state, "response_type": "code"})
        return f"https://trade.shoonya.com/OAuthlogin/authorize/oauth?{q}"

    async def oauth_callback(self, params: dict[str, str], redirect_uri: str) -> dict[str, Any]:
        code = params["code"]
        checksum = hashlib.sha256(f"{self.credentials['client_id']}{self.credentials['api_secret']}{code}".encode()).hexdigest()
        body = await self._call("GenAcsTok", {"code": code, "checksum": checksum}, auth=False)
        tok = body.get("access_token") or body.get("susertoken")
        if not tok:
            raise BrokerError("Shoonya token exchange failed")
        self.session = {"access_token": tok, "user_id": body.get("uid", self.credentials.get("user_id")),
                        "expires_at": day_end_expiry().isoformat()}
        return self.session

    async def _call(self, endpoint: str, payload: dict[str, Any], auth: bool = True) -> Any:
        body = await self.request("POST", f"{API}/{endpoint}", content=f"jData={json.dumps(payload)}")
        if isinstance(body, dict) and body.get("stat") == "Not_Ok":
            emsg = str(body.get("emsg", ""))
            if "no data" in emsg.lower():
                return []
            raise BrokerError(f"Shoonya: {emsg}")
        return body

    @property
    def uid(self) -> str:
        return str(self.session.get("user_id") or self.credentials.get("user_id", ""))

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        m = self.symbol_map(req.symbol)
        return {"uid": self.uid, "actid": self.uid, "exch": m["exchange"], "tsym": m["tradingsymbol"], "qty": str(req.quantity),
                "prc": str(req.price or 0), "trgprc": str(req.trigger_price or 0), "dscqty": "0", "prd": PRD[req.product],
                "trantype": "B" if req.side == Side.BUY else "S", "prctyp": PRCTYP[req.order_type], "ret": req.validity,
                "ordersource": "API", "remarks": (req.tag or req.algo_id or "")[:20]}

    async def place_order(self, req: OrderRequest) -> OrderAck:
        body = await self._call("PlaceOrder", self.to_payload(req))
        return OrderAck(broker_order_id=str(body["norenordno"]))

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        if original is None:
            raise BrokerError("Shoonya modify needs the original order")
        m = self.symbol_map(original.symbol)
        ot = req.order_type or original.order_type
        await self._call("ModifyOrder", {"uid": self.uid, "norenordno": broker_order_id, "exch": m["exchange"], "tsym": m["tradingsymbol"],
                                         "qty": str(req.quantity or original.quantity), "prctyp": PRCTYP[ot],
                                         "prc": str(req.price if req.price is not None else original.price or 0),
                                         "trgprc": str(req.trigger_price or original.trigger_price or 0), "ret": "DAY"})
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        await self._call("CancelOrder", {"uid": self.uid, "norenordno": broker_order_id})
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    async def get_order_book(self) -> list[Order]:
        rows = await self._call("OrderBook", {"uid": self.uid}) or []
        return [Order(
            broker_order_id=str(r["norenordno"]), symbol=self.from_broker(r.get("exch", "NSE"), r.get("tsym", "")),
            side=side_from(r.get("trantype")), quantity=as_int(r.get("qty")), filled_quantity=as_int(r.get("fillshares")),
            price=num(r.get("prc")), trigger_price=num(r.get("trgprc")), average_price=num(r.get("avgprc")),
            order_type=order_type_from(r.get("prctyp")), product=product_from(r.get("prd")), status=status_from(r.get("status")),
            status_message=r.get("rejreason"), tag=r.get("remarks"), ts=parse_ts(r.get("norentm")),
        ) for r in rows]

    async def get_trade_book(self) -> list[Trade]:
        rows = await self._call("TradeBook", {"uid": self.uid, "actid": self.uid}) or []
        return [Trade(broker_trade_id=str(r.get("flid")), broker_order_id=str(r.get("norenordno")),
                      symbol=self.from_broker(r.get("exch", "NSE"), r.get("tsym", "")), side=side_from(r.get("trantype")),
                      quantity=as_int(r.get("flqty")), price=num(r.get("flprc")), product=product_from(r.get("prd")),
                      ts=parse_ts(r.get("fltm"))) for r in rows]

    async def get_positions(self) -> list[Position]:
        rows = await self._call("PositionBook", {"uid": self.uid, "actid": self.uid}) or []
        return [Position(symbol=self.from_broker(r.get("exch", "NSE"), r.get("tsym", "")), product=product_from(r.get("prd")),
                         quantity=as_int(r.get("netqty")), average_price=num(r.get("netavgprc")), last_price=num(r.get("lp")),
                         realised_pnl=num(r.get("rpnl")), unrealised_pnl=num(r.get("urmtom")), broker=self.name) for r in rows]

    async def get_holdings(self) -> list[Holding]:
        rows = await self._call("Holdings", {"uid": self.uid, "actid": self.uid, "prd": "C"}) or []
        out = []
        for r in rows:
            ts = (r.get("exch_tsym") or [{}])[0]
            out.append(Holding(symbol=self.from_broker(ts.get("exch", "NSE"), ts.get("tsym", "")), quantity=as_int(r.get("holdqty")),
                               average_price=num(r.get("upldprc")), broker=self.name))
        return out

    async def get_funds(self) -> Funds:
        b = await self._call("Limits", {"uid": self.uid, "actid": self.uid}) or {}
        cash, used = num(b.get("cash")) + num(b.get("payin")), num(b.get("marginused"))
        return Funds(available=cash - used, used=used, total=cash)

    async def get_profile(self) -> Profile:
        b = await self._call("UserDetails", {"uid": self.uid}) or {}
        return Profile(user_id=self.uid, name=b.get("uname", ""), email=b.get("email"), broker=self.name, exchanges=b.get("exarr", []))
