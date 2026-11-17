"""ICICI Direct Breeze API (session token + per-request SHA-256 checksum headers).

Every call carries X-Checksum = "token " + sha256(timestamp + json_body + secret),
X-Timestamp (ISO-8601 UTC, millisecond precision), X-AppKey and X-SessionToken.
GET requests send a JSON body (a Breeze quirk).
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import quote

from broker_gateway.adapters._common import day_end_expiry, parse_ts, side_from, status_from
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

ORDER_TYPE = {OrderType.MARKET: "market", OrderType.LIMIT: "limit", OrderType.SL: "stoploss", OrderType.SL_M: "stoploss"}
STATUS = {"executed": OrderStatus.COMPLETE, "ordered": OrderStatus.OPEN, "requested": OrderStatus.PENDING}


class IciciBreezeAdapter(HttpBrokerAdapter):
    name = "icici"
    display_name = "ICICI Direct (Breeze)"
    auth_type = "oauth"
    base_url = "https://api.icicidirect.com/breezeapi/api/v1"
    docs_url = "https://api.icicidirect.com/breezeapi/documents/index.html"
    rate_limit_per_sec = 1.6  # 100 calls / minute
    credential_fields: ClassVar = [
        CredentialField(name="api_key", label="App key"),
        CredentialField(name="api_secret", label="Secret key", secret=True),
    ]

    def login_url(self, state: str, redirect_uri: str) -> str:
        return f"https://api.icicidirect.com/apiuser/login?api_key={quote(self.credentials['api_key'], safe='')}"

    def _signed(self, body: dict[str, Any]) -> tuple[str, dict[str, str]]:
        payload = json.dumps(body, separators=(",", ":"))
        ts = datetime.now(UTC).isoformat()[:19] + ".000Z"
        checksum = hashlib.sha256((ts + payload + self.credentials["api_secret"]).encode()).hexdigest()
        return payload, {"Content-Type": "application/json", "X-Checksum": "token " + checksum, "X-Timestamp": ts,
                         "X-AppKey": self.credentials["api_key"], "X-SessionToken": str(self.session.get("access_token", ""))}

    async def call(self, method: str, path: str, body: dict[str, Any]) -> Any:
        payload, headers = self._signed(body)
        res = await self.request(method, path, content=payload, headers=headers)
        if isinstance(res, dict) and res.get("Status") not in (200, None) and res.get("Error"):
            raise BrokerError(f"Breeze: {res.get('Error')}")
        return res.get("Success") if isinstance(res, dict) else res

    async def oauth_callback(self, params: dict[str, str], redirect_uri: str) -> dict[str, Any]:
        api_session = params.get("apisession") or params.get("API_Session") or params["code"]
        payload = json.dumps({"SessionToken": api_session, "AppKey": self.credentials["api_key"]})
        res = await self.request("GET", "/customerdetails", content=payload, headers={"Content-Type": "application/json"})
        succ = (res or {}).get("Success") or {}
        raw = succ.get("session_token")
        if not raw:
            raise BrokerError("Breeze customer details did not return a session token")
        user_id, token = base64.b64decode(raw).decode().split(":", 1)
        self.session = {"access_token": raw, "user_id": user_id, "session_key": token,
                        "expires_at": day_end_expiry().isoformat()}
        return self.session

    def to_payload(self, req: OrderRequest) -> dict[str, Any]:
        m = self.symbol_map(req.symbol)
        body: dict[str, Any] = {
            "stock_code": m.get("stock_code") or m["tradingsymbol"], "exchange_code": m["exchange"],
            "product": m.get("product") or ("cash" if req.product == Product.CNC else "margin"),
            "action": req.side.value.lower(), "order_type": ORDER_TYPE[req.order_type], "quantity": str(req.quantity),
            "price": str(req.price or 0), "stoploss": str(req.trigger_price or 0), "validity": req.validity.lower(),
            "disclosed_quantity": "0", "user_remark": (req.tag or req.algo_id or "")[:20],
        }
        if "expiry_date" in m:
            body.update(expiry_date=m["expiry_date"], right=m["right"], strike_price=m["strike_price"])
        return body

    async def place_order(self, req: OrderRequest) -> OrderAck:
        s = await self.call("POST", "/order", self.to_payload(req)) or {}
        return OrderAck(broker_order_id=str(s.get("order_id")), message=s.get("message"))

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        ex = original.symbol.split(":")[0] if original else "NSE"
        await self.call("PUT", "/order", {"order_id": broker_order_id, "exchange_code": ex,
                                          "order_type": ORDER_TYPE[req.order_type or (original.order_type if original else OrderType.LIMIT)],
                                          "quantity": str(req.quantity or (original.quantity if original else 0)),
                                          "price": str(req.price or 0), "stoploss": str(req.trigger_price or 0), "validity": "day"})
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.OPEN)

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        await self.call("DELETE", "/order", {"order_id": broker_order_id, "exchange_code": "NSE"})
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    def _sym(self, r: dict[str, Any]) -> str:
        from broker_gateway.symbols import TOKENS

        return TOKENS.symbol(self.name, str(r.get("stock_code", ""))) or f"{r.get('exchange_code', 'NSE')}:{r.get('stock_code', '')}"

    async def get_order_book(self) -> list[Order]:
        today = datetime.now(UTC)
        rows = []
        for ex in ("NSE", "NFO"):
            rows += await self.call("GET", "/order", {"exchange_code": ex, "from_date": (today - timedelta(days=1)).isoformat()[:19] + ".000Z",
                                                      "to_date": today.isoformat()[:19] + ".000Z"}) or []
        return [Order(
            broker_order_id=str(r["order_id"]), symbol=self._sym(r), side=side_from(r.get("action")), quantity=as_int(r.get("quantity")),
            filled_quantity=as_int(r.get("quantity")) - as_int(r.get("pending_quantity")), price=num(r.get("price")),
            trigger_price=num(r.get("stoploss")), average_price=num(r.get("average_price")),
            order_type=OrderType.LIMIT if r.get("order_type") == "limit" else (OrderType.SL if r.get("order_type") == "stoploss" else OrderType.MARKET),
            product=Product.CNC if r.get("product_type") == "cash" else Product.MIS, status=status_from(r.get("status"), STATUS),
            status_message=r.get("user_remark"), ts=parse_ts(r.get("order_datetime")),
        ) for r in rows]

    async def get_trade_book(self) -> list[Trade]:
        today = datetime.now(UTC)
        rows = await self.call("GET", "/trades", {"exchange_code": "NSE", "from_date": (today - timedelta(days=1)).isoformat()[:19] + ".000Z",
                                                  "to_date": today.isoformat()[:19] + ".000Z"}) or []
        return [Trade(broker_trade_id=str(r.get("trade_id", r.get("order_id"))), broker_order_id=str(r.get("order_id")), symbol=self._sym(r),
                      side=side_from(r.get("action")), quantity=as_int(r.get("quantity")), price=num(r.get("average_cost", r.get("price"))))
                for r in rows]

    async def get_positions(self) -> list[Position]:
        rows = await self.call("GET", "/portfoliopositions", {}) or []
        out = []
        for r in rows:
            q = as_int(r.get("quantity"))
            out.append(Position(symbol=self._sym(r), product=Product.NRML if r.get("product_type") in ("futures", "options") else Product.MIS,
                                quantity=q if str(r.get("action", "buy")).lower() == "buy" else -q, average_price=num(r.get("average_price")),
                                last_price=num(r.get("ltp")), broker=self.name))
        return out

    async def get_holdings(self) -> list[Holding]:
        rows = await self.call("GET", "/portfolioholdings", {"exchange_code": "NSE"}) or []
        return [Holding(symbol=self._sym(r), quantity=as_int(r.get("quantity")), average_price=num(r.get("average_price")),
                        last_price=num(r.get("current_market_price")), broker=self.name) for r in rows]

    async def get_funds(self) -> Funds:
        d = await self.call("GET", "/funds", {}) or {}
        avail = num(d.get("unallocated_balance")) + num(d.get("allocated_equity")) + num(d.get("allocated_fno"))
        used = num(d.get("block_by_trade_equity")) + num(d.get("block_by_trade_fno"))
        return Funds(available=avail - used, used=used, total=num(d.get("total_bank_balance"), avail))

    async def get_profile(self) -> Profile:
        return Profile(user_id=str(self.session.get("user_id", "")), broker=self.name)
