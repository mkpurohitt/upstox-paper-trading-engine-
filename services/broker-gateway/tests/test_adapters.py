"""Adapter contract tests against mocked broker HTTP APIs (no network)."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, unquote

import httpx
import pyotp
import pytest

from broker_gateway.adapters import ADAPTERS
from broker_gateway.adapters.aliceblue import AliceBlueAdapter
from broker_gateway.adapters.angel import AngelAdapter
from broker_gateway.adapters.dhan import DhanAdapter
from broker_gateway.adapters.fivepaisa import FivePaisaAdapter
from broker_gateway.adapters.fyers import FyersAdapter
from broker_gateway.adapters.icici import IciciBreezeAdapter
from broker_gateway.adapters.kotak import KotakAdapter
from broker_gateway.adapters.shoonya import ShoonyaAdapter
from broker_gateway.adapters.upstox import UpstoxAdapter
from broker_gateway.adapters.zerodha import ZerodhaAdapter
from broker_gateway.base import BrokerAuthError, BrokerError
from broker_gateway.models import ModifyRequest, Order, OrderRequest, OrderStatus, OrderType, Product, Side
from broker_gateway.symbols import TOKENS


class Fake:
    """Route table: (METHOD, path-suffix) -> JSON response (or callable)."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.calls: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        for (m, suffix), resp in self.routes.items():
            if req.method == m and str(req.url).split("?")[0].endswith(suffix):
                body = resp(req) if callable(resp) else resp
                status = body.pop("__status", 200) if isinstance(body, dict) else 200
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"message": f"no route {req.method} {req.url}"})

    def last(self, method: str, suffix: str) -> httpx.Request:
        return next(r for r in reversed(self.calls) if r.method == method and str(r.url).split("?")[0].endswith(suffix))

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def form(req: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(req.content.decode()).items()}


def jdata(req: httpx.Request) -> dict[str, Any]:
    raw = req.content.decode()
    assert raw.startswith("jData=")
    return json.loads(unquote(raw[len("jData="):]))


BUY = OrderRequest(symbol="NSE:SBIN", side=Side.BUY, quantity=10, product=Product.MIS, tag="t1", algo_id="ALGO-1")
LIMIT_OPT = OrderRequest(symbol="NFO:NIFTY17NOV2626200CE", side=Side.SELL, quantity=65, order_type=OrderType.LIMIT, price=80.5,
                         product=Product.NRML)


def test_registry_has_ten_brokers():
    assert set(ADAPTERS) == {"upstox", "zerodha", "angel", "dhan", "fyers", "kotak", "fivepaisa", "icici", "aliceblue", "shoonya"}
    for cls in ADAPTERS.values():
        assert cls.credential_fields and cls.display_name


async def test_zerodha_flow():
    f = Fake({
        ("POST", "/session/token"): {"data": {"access_token": "AT", "user_id": "AB1234"}},
        ("POST", "/orders/regular"): {"data": {"order_id": "250101000001"}},
        ("GET", "/orders"): {"data": [{"order_id": "1", "exchange": "NFO", "tradingsymbol": "NIFTY26N1726200CE", "transaction_type": "SELL",
                                       "quantity": 65, "filled_quantity": 65, "average_price": 80.1, "order_type": "LIMIT",
                                       "product": "NRML", "status": "COMPLETE"}]},
        ("GET", "/portfolio/positions"): {"data": {"net": [{"exchange": "NSE", "tradingsymbol": "SBIN", "product": "MIS", "quantity": -10,
                                                            "average_price": 800, "last_price": 795, "realised": 0, "unrealised": 50}]}},
        ("GET", "/user/margins"): {"data": {"equity": {"available": {"live_balance": 50000}, "utilised": {"debits": 1000}}}},
    })
    a = ZerodhaAdapter({"api_key": "KEY", "api_secret": "SEC"}, transport=f.transport)
    assert "api_key=KEY" in a.login_url("st", "http://cb")
    await a.oauth_callback({"request_token": "RT"}, "http://cb")
    assert form(f.last("POST", "/session/token"))["checksum"] == hashlib.sha256(b"KEYRTSEC").hexdigest()
    assert (await a.place_order(BUY)).broker_order_id == "250101000001"
    req = f.last("POST", "/orders/regular")
    assert req.headers["Authorization"] == "token KEY:AT" and req.headers["X-Kite-Version"] == "3"
    p = form(req)
    assert p["tradingsymbol"] == "SBIN" and p["transaction_type"] == "BUY" and p["product"] == "MIS" and p["tag"] == "t1"
    await a.place_order(LIMIT_OPT)
    p = form(f.last("POST", "/orders/regular"))
    assert p["tradingsymbol"] == "NIFTY26N1726200CE" and p["price"] == "80.5" and p["exchange"] == "NFO"
    orders = await a.get_order_book()
    assert orders[0].symbol == "NFO:NIFTY17NOV2626200CE" and orders[0].status == OrderStatus.COMPLETE
    pos = await a.get_positions()
    assert pos[0].symbol == "NSE:SBIN" and pos[0].quantity == -10
    assert (await a.get_funds()).available == 50000


async def test_upstox_flow():
    TOKENS.set("upstox", {"NSE:SBIN": "NSE_EQ|INE062A01020"})
    f = Fake({
        ("POST", "/v2/login/authorization/token"): {"access_token": "UT", "user_id": "U1"},
        ("POST", "/v2/order/place"): {"status": "success", "data": {"order_id": "U-1"}},
        ("GET", "/v2/order/retrieve-all"): {"status": "success", "data": [{"order_id": "U-1", "instrument_token": "NSE_EQ|INE062A01020",
                                           "trading_symbol": "SBIN", "exchange": "NSE", "transaction_type": "BUY", "quantity": 10,
                                           "filled_quantity": 0, "order_type": "MARKET", "product": "I", "status": "trigger pending"}]},
        ("DELETE", "/v2/order/cancel"): {"status": "success", "data": {"order_id": "U-1"}},
    })
    a = UpstoxAdapter({"api_key": "K", "api_secret": "S"}, transport=f.transport)
    assert "client_id=K" in a.login_url("x", "http://cb")
    await a.oauth_callback({"code": "C"}, "http://cb")
    assert form(f.last("POST", "/v2/login/authorization/token"))["grant_type"] == "authorization_code"
    await a.place_order(BUY)
    body = json.loads(f.last("POST", "/v2/order/place").content)
    assert body["instrument_token"] == "NSE_EQ|INE062A01020" and body["product"] == "I" and body["transaction_type"] == "BUY"
    o = (await a.get_order_book())[0]
    assert o.symbol == "NSE:SBIN" and o.status == OrderStatus.TRIGGER_PENDING
    assert (await a.cancel_order("U-1")).status == OrderStatus.CANCELLED
    with pytest.raises(BrokerError):
        a.to_payload(OrderRequest(symbol="NSE:UNKNOWN", side=Side.BUY, quantity=1))


async def test_angel_totp_login_and_order():
    secret = pyotp.random_base32()
    TOKENS.set("angel", {"NSE:SBIN": "3045"})
    f = Fake({
        ("POST", "/user/v1/loginByPassword"): {"status": True, "message": "SUCCESS", "data": {"jwtToken": "J", "refreshToken": "R", "feedToken": "F"}},
        ("POST", "/order/v1/placeOrder"): {"status": True, "message": "SUCCESS", "data": {"orderid": "A1"}},
        ("GET", "/order/v1/getPosition"): {"status": True, "message": "SUCCESS", "data": [{"tradingsymbol": "SBIN-EQ", "symboltoken": "3045",
                                            "exchange": "NSE", "producttype": "INTRADAY", "netqty": "10", "avgnetprice": "800", "ltp": "805", "pnl": "50"}]},
    })
    a = AngelAdapter({"api_key": "K", "client_id": "C1", "pin": "1234", "totp_secret": secret}, transport=f.transport)
    await a.login()
    login = json.loads(f.last("POST", "/user/v1/loginByPassword").content)
    assert login["clientcode"] == "C1" and len(login["totp"]) == 6
    await a.place_order(BUY)
    req = f.last("POST", "/order/v1/placeOrder")
    p = json.loads(req.content)
    assert req.headers["Authorization"] == "Bearer J" and req.headers["X-PrivateKey"] == "K"
    assert p["tradingsymbol"] == "SBIN-EQ" and p["symboltoken"] == "3045" and p["producttype"] == "INTRADAY" and p["variety"] == "NORMAL"
    assert (await a.get_positions())[0].quantity == 10


async def test_angel_requires_totp():
    a = AngelAdapter({"api_key": "K", "client_id": "C1", "pin": "1"}, transport=Fake({}).transport)
    with pytest.raises(BrokerAuthError):
        await a.login()


async def test_dhan_order_and_status():
    TOKENS.set("dhan", {"NFO:NIFTY17NOV2626200CE": "54321"})
    f = Fake({
        ("POST", "/v2/orders"): {"orderId": "D1", "orderStatus": "TRANSIT"},
        ("GET", "/v2/orders"): [{"orderId": "D1", "securityId": "54321", "exchangeSegment": "NSE_FNO", "transactionType": "SELL",
                                 "quantity": 65, "filledQty": 65, "averageTradedPrice": 80, "orderType": "LIMIT",
                                 "productType": "MARGIN", "orderStatus": "TRADED"}],
        ("GET", "/v2/fundlimit"): {"availabelBalance": 12345.5, "utilizedAmount": 100},
    })
    a = DhanAdapter({"client_id": "100", "access_token": "TOK"}, transport=f.transport)
    await a.login()
    ack = await a.place_order(LIMIT_OPT)
    assert ack.broker_order_id == "D1" and ack.status == OrderStatus.PENDING
    p = json.loads(f.last("POST", "/v2/orders").content)
    assert p["exchangeSegment"] == "NSE_FNO" and p["securityId"] == "54321" and p["orderType"] == "LIMIT" and p["productType"] == "MARGIN"
    assert f.last("POST", "/v2/orders").headers["access-token"] == "TOK"
    o = (await a.get_order_book())[0]
    assert o.status == OrderStatus.COMPLETE and o.symbol == "NFO:NIFTY17NOV2626200CE"
    assert (await a.get_funds()).available == 12345.5


async def test_fyers_flow():
    f = Fake({
        ("POST", "/api/v3/validate-authcode"): {"s": "ok", "access_token": "FT"},
        ("POST", "/api/v3/orders/sync"): {"s": "ok", "id": "F1"},
        ("GET", "/api/v3/orders"): {"s": "ok", "orderBook": [{"id": "F1", "symbol": "NSE:SBIN-EQ", "side": -1, "qty": 10, "filledQty": 0,
                                                              "type": 1, "productType": "INTRADAY", "status": 6, "limitPrice": 800}]},
    })
    a = FyersAdapter({"api_key": "APP-100", "api_secret": "SEC"}, transport=f.transport)
    await a.oauth_callback({"auth_code": "AC"}, "http://cb")
    assert json.loads(f.last("POST", "/api/v3/validate-authcode").content)["appIdHash"] == hashlib.sha256(b"APP-100:SEC").hexdigest()
    await a.place_order(BUY)
    req = f.last("POST", "/api/v3/orders/sync")
    p = json.loads(req.content)
    assert req.headers["Authorization"] == "APP-100:FT"
    assert p["symbol"] == "NSE:SBIN-EQ" and p["side"] == 1 and p["type"] == 2 and p["productType"] == "INTRADAY"
    o = (await a.get_order_book())[0]
    assert o.side == Side.SELL and o.status == OrderStatus.OPEN and o.order_type == OrderType.LIMIT and o.symbol == "NSE:SBIN"


async def test_kotak_jdata_flow():
    f = Fake({
        ("POST", "/login/1.0/tradeApiLogin"): {"data": {"token": "VIEW", "sid": "S1"}},
        ("POST", "/login/1.0/tradeApiValidate"): {"data": {"token": "TRADE", "sid": "S2", "baseUrl": "https://cis.kotaksecurities.com"}},
        ("POST", "/quick/order/rule/ms/place"): {"stat": "Ok", "nOrdNo": "K1"},
    })
    a = KotakAdapter({"access_token": "CONSUMER", "client_id": "UCC1", "mobile": "+919999999999", "mpin": "123456"}, transport=f.transport)
    await a.login({"totp": "123456"})
    await a.place_order(BUY)
    req = f.last("POST", "/quick/order/rule/ms/place")
    p = jdata(req)
    assert req.headers["Auth"] == "TRADE" and req.headers["Sid"] == "S2" and req.headers["neo-fin-key"] == "neotradeapi"
    assert p["ts"] == "SBIN-EQ" and p["es"] == "nse_cm" and p["tt"] == "B" and p["pt"] == "MKT" and p["pc"] == "MIS"


async def test_fivepaisa_flow():
    TOKENS.set("fivepaisa", {"NSE:SBIN": "3045"})
    f = Fake({
        ("POST", "/TOTPLogin"): {"body": {"RequestToken": "REQ", "Status": 0}},
        ("POST", "/GetAccessToken"): {"body": {"AccessToken": "ACC", "ClientCode": "CC1", "Status": 0}},
        ("POST", "/V1/PlaceOrderRequest"): {"body": {"BrokerOrderID": 77, "ExchOrderID": "1100000001", "Status": 0, "Message": "ok"}},
    })
    a = FivePaisaAdapter({"api_key": "K", "encryption_key": "E", "user_id": "U", "client_id": "CC1", "pin": "1"}, transport=f.transport)
    await a.login({"totp": "111111"})
    assert json.loads(f.last("POST", "/GetAccessToken").content)["body"]["RequestToken"] == "REQ"
    ack = await a.place_order(BUY)
    p = json.loads(f.last("POST", "/V1/PlaceOrderRequest").content)
    assert ack.broker_order_id == "1100000001"
    assert p["body"]["ScripCode"] == 3045 and p["body"]["Exchange"] == "N" and p["body"]["ExchangeType"] == "C"
    assert p["body"]["IsIntraday"] is True and p["body"]["Price"] == 0 and p["head"]["key"] == "K"


async def test_shoonya_flow():
    f = Fake({
        ("POST", "/NorenWClientAPI/GenAcsTok"): {"stat": "Ok", "access_token": "ST", "uid": "FA1"},
        ("POST", "/NorenWClientAPI/PlaceOrder"): {"stat": "Ok", "norenordno": "N1"},
        ("POST", "/NorenWClientAPI/PositionBook"): {"stat": "Not_Ok", "emsg": "no data"},
    })
    a = ShoonyaAdapter({"client_id": "CID", "api_secret": "SEC", "user_id": "FA1"}, transport=f.transport)
    await a.oauth_callback({"code": "C0"}, "http://cb")
    assert jdata(f.last("POST", "/GenAcsTok"))["checksum"] == hashlib.sha256(b"CIDSECC0").hexdigest()
    await a.place_order(LIMIT_OPT)
    req = f.last("POST", "/NorenWClientAPI/PlaceOrder")
    p = jdata(req)
    assert req.headers["Authorization"] == "Bearer ST"
    assert p["tsym"] == "NIFTY17NOV26C26200" and p["trantype"] == "S" and p["prctyp"] == "LMT" and p["prd"] == "M" and p["exch"] == "NFO"
    assert await a.get_positions() == []


async def test_aliceblue_flow():
    TOKENS.set("aliceblue", {"NSE:SBIN": "3045"})
    f = Fake({
        ("POST", "/vendor/getUserDetails"): {"userSession": "AS"},
        ("POST", "/orders/placeorder"): {"status": "Ok", "result": [{"brokerOrderId": "AB1"}]},
    })
    a = AliceBlueAdapter({"app_code": "APP", "api_secret": "SEC"}, transport=f.transport)
    await a.oauth_callback({"userId": "U1", "authCode": "AUTH"}, "http://cb")
    assert json.loads(f.last("POST", "/vendor/getUserDetails").content)["checkSum"] == hashlib.sha256(b"U1AUTHSEC").hexdigest()
    assert (await a.place_order(BUY)).broker_order_id == "AB1"
    body = json.loads(f.last("POST", "/orders/placeorder").content)
    assert isinstance(body, list) and body[0]["instrumentId"] == "3045" and body[0]["product"] == "INTRADAY"


async def test_icici_breeze_checksum_headers():
    f = Fake({("POST", "/order"): {"Success": {"order_id": "IC1", "message": "ok"}, "Status": 200, "Error": None}})
    a = IciciBreezeAdapter({"api_key": "APPKEY", "api_secret": "SECRET"}, {"access_token": "SESS"}, transport=f.transport)
    ack = await a.place_order(LIMIT_OPT)
    assert ack.broker_order_id == "IC1"
    req = f.last("POST", "/order")
    body = req.content.decode()
    ts = req.headers["X-Timestamp"]
    assert req.headers["X-Checksum"] == "token " + hashlib.sha256((ts + body + "SECRET").encode()).hexdigest()
    p = json.loads(body)
    assert p["right"] == "call" and p["strike_price"] == "26200" and p["product"] == "options" and p["action"] == "sell"


async def test_auth_errors_and_square_off():
    f = Fake({("GET", "/portfolio/positions"): {"__status": 403, "message": "token expired"}})
    a = ZerodhaAdapter({"api_key": "K", "api_secret": "S"}, {"access_token": "X"}, transport=f.transport)
    with pytest.raises(BrokerAuthError):
        await a.get_positions()

    placed: list[dict[str, str]] = []

    def place(req: httpx.Request) -> dict[str, Any]:
        placed.append(form(req))
        return {"data": {"order_id": str(len(placed))}}

    f2 = Fake({
        ("GET", "/portfolio/positions"): {"data": {"net": [
            {"exchange": "NSE", "tradingsymbol": "SBIN", "product": "MIS", "quantity": 10, "average_price": 1},
            {"exchange": "NSE", "tradingsymbol": "TCS", "product": "CNC", "quantity": 5, "average_price": 1},
            {"exchange": "NFO", "tradingsymbol": "NIFTY26NOV26200PE", "product": "NRML", "quantity": -65, "average_price": 1}]}},
        ("POST", "/orders/regular"): place,
    })
    a2 = ZerodhaAdapter({"api_key": "K", "api_secret": "S"}, {"access_token": "X"}, transport=f2.transport)
    acks = await a2.square_off_all()
    assert len(acks) == 2  # CNC holding untouched
    assert {(p["tradingsymbol"], p["transaction_type"]) for p in placed} == {("SBIN", "SELL"), ("NIFTY26NOV26200PE", "BUY")}


async def test_modify_uses_original_order():
    TOKENS.set("angel", {"NSE:SBIN": "3045"})
    f = Fake({("POST", "/order/v1/modifyOrder"): {"status": True, "message": "SUCCESS", "data": {"orderid": "A1"}}})
    a = AngelAdapter({"api_key": "K", "client_id": "C", "pin": "1"}, {"access_token": "J"}, transport=f.transport)
    orig = Order(broker_order_id="A1", symbol="NSE:SBIN", side=Side.BUY, quantity=10, order_type=OrderType.LIMIT, price=800,
                 product=Product.MIS)
    await a.modify_order("A1", ModifyRequest(price=805), orig)
    p = json.loads(f.last("POST", "/order/v1/modifyOrder").content)
    assert p["price"] == "805.0" and p["quantity"] == "10" and p["symboltoken"] == "3045"
