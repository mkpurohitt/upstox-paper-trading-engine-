import gzip
import json
import math
from datetime import date, datetime, timedelta

import httpx
import pytest

from algo_common.schemas.market import Interval
from algo_common.timeutils import IST, now_ist
from market_data.mock import MockProvider, max_pain
from market_data.nse_mcp import MockNseTools
from market_data.options import bs_greeks, bs_price, implied_vol, prob_between
from market_data.proto import MarketDataFeedV3_pb2 as pb
from market_data.symbols import future_symbol, option_symbol, parse
from market_data.upstox import UpstoxProvider, instrument_from_upstox
from market_data.upstox_feed import decode_feed


def test_black_scholes_put_call_parity_and_iv_roundtrip():
    s, k, t, v, r = 26000, 26100, 7 / 365, 0.13, 0.065
    c, p = bs_price(s, k, t, v, r, True), bs_price(s, k, t, v, r, False)
    assert math.isclose(c - p, s - k * math.exp(-r * t), rel_tol=1e-9)
    assert math.isclose(implied_vol(c, s, k, t, r, True), v, abs_tol=1e-4)
    g = bs_greeks(s, k, t, v, r, True)
    assert 0.3 < g.delta < 0.6 and g.gamma > 0 and g.theta < 0 and g.vega > 0
    assert 0.0 < prob_between(s, s * 0.97, s * 1.03, t, v) < 1.0


def test_symbol_roundtrip():
    sym = option_symbol("NIFTY", date(2026, 11, 24), 26200, "CE")
    assert sym == "NFO:NIFTY24NOV2626200CE"
    p = parse(sym)
    assert p.underlying == "NIFTY" and p.strike == 26200 and p.option_type == "CE" and p.expiry == date(2026, 11, 24)
    f = parse(future_symbol("BANKNIFTY", date(2026, 12, 29)))
    assert f.is_future and f.underlying == "BANKNIFTY"
    assert parse("NSE:RELIANCE").is_derivative is False
    assert parse(option_symbol("SENSEX", date(2026, 11, 26), 85600, "PE")).exchange == "BFO"


async def test_mock_is_deterministic_and_consistent():
    a, b = MockProvider(), MockProvider()
    end = now_ist()
    start = end - timedelta(days=400)
    ca = await a.candles("NSE:RELIANCE", Interval.D1, start, end)
    cb = await b.candles("NSE:RELIANCE", Interval.D1, start, end)
    assert len(ca) > 250
    # historical bars identical across instances (today's partial bar may differ by live noise)
    assert [c.close for c in ca[:-1]] == [c.close for c in cb[:-1]]
    for c in ca:
        assert c.low <= min(c.open, c.close) + 1e-6 and c.high >= max(c.open, c.close) - 1e-6
    # 1m aggregates agree with the daily bar on a recent full day
    day = ca[-3]
    d = day.ts.astimezone(IST).date()
    s0 = datetime.combine(d, datetime.min.time(), tzinfo=IST)
    mins = await a.candles("NSE:RELIANCE", Interval.M1, s0, s0 + timedelta(days=1))
    assert len(mins) == 375
    assert math.isclose(mins[-1].close, day.close, rel_tol=1e-3)
    assert math.isclose(mins[0].open, day.open, rel_tol=1e-3)


async def test_mock_option_chain_and_quotes():
    p = MockProvider()
    chain = await p.option_chain("NIFTY", strikes=10)
    assert len(chain.rows) == 21 and chain.lot_size == 65
    assert chain.pcr and 0.3 < chain.pcr < 3
    atm = min(chain.rows, key=lambda r: abs(r.strike - chain.spot))
    assert 0.35 < atm.call.greeks.delta < 0.65 and -0.65 < atm.put.greeks.delta < -0.35
    # OTM puts carry higher IV than OTM calls (negative skew)
    assert chain.rows[0].put.iv > chain.rows[-1].call.iv
    q = (await p.quotes([atm.call.symbol]))[atm.call.symbol]
    assert abs(q.ltp - atm.call.ltp) / atm.call.ltp < 0.05
    assert chain.max_pain in [r.strike for r in chain.rows]


def test_max_pain_simple():
    from algo_common.schemas.market import OptionChainRow, OptionLeg

    rows = [
        OptionChainRow(strike=k, expiry=date(2026, 1, 1),
                       call=OptionLeg(symbol="c", ltp=1, oi=co), put=OptionLeg(symbol="p", ltp=1, oi=po))
        for k, co, po in [(100, 10, 500), (110, 100, 100), (120, 500, 10)]
    ]
    assert max_pain(rows) == 110


def test_decode_upstox_feed():
    resp = pb.FeedResponse(type=pb.live_feed, currentTs=1)
    f = resp.feeds["NSE_EQ|INE002A01018"]
    f.fullFeed.marketFF.ltpc.ltp = 1500.5
    f.fullFeed.marketFF.ltpc.cp = 1490.0
    f.fullFeed.marketFF.ltpc.ltt = 1_763_300_000_000
    f.fullFeed.marketFF.vtt = 123456
    q = f.fullFeed.marketFF.marketLevel.bidAskQuote.add()
    q.bidP, q.askP = 1500.4, 1500.6
    idx = resp.feeds["NSE_INDEX|Nifty 50"]
    idx.fullFeed.indexFF.ltpc.ltp = 26000
    idx.fullFeed.indexFF.ltpc.cp = 25900
    ticks = decode_feed(resp.SerializeToString(), {"NSE_EQ|INE002A01018": "NSE:RELIANCE", "NSE_INDEX|Nifty 50": "NSE_INDEX:NIFTY"})
    by = {t.symbol: t for t in ticks}
    assert by["NSE:RELIANCE"].ltp == 1500.5 and by["NSE:RELIANCE"].bid == 1500.4
    assert round(by["NSE_INDEX:NIFTY"].change_pct, 3) == round(100 / 25900 * 100, 3)


def _upstox_transport():
    master = [
        {"segment": "NSE_EQ", "instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES",
         "instrument_type": "EQ", "lot_size": 1, "tick_size": 5.0, "isin": "INE002A01018"},
        {"segment": "NSE_INDEX", "instrument_key": "NSE_INDEX|Nifty 50", "trading_symbol": "NIFTY", "name": "Nifty 50",
         "instrument_type": "INDEX"},
        {"segment": "NSE_FO", "instrument_key": "NSE_FO|1", "trading_symbol": "NIFTY 26200 CE 24 NOV 26", "name": "NIFTY",
         "underlying_symbol": "NIFTY", "instrument_type": "CE", "strike_price": 26200, "lot_size": 65, "tick_size": 5.0,
         "expiry": int(datetime(2026, 11, 24, 15, 30, tzinfo=IST).timestamp() * 1000)},
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if "complete.json.gz" in str(req.url):
            return httpx.Response(200, content=gzip.compress(json.dumps(master).encode()))
        if path.startswith("/v3/historical-candle/"):
            return httpx.Response(200, json={"status": "success", "data": {"candles": [
                ["2026-11-13T00:00:00+05:30", 1510, 1525, 1500, 1520, 1000, 0],
                ["2026-11-12T00:00:00+05:30", 1500, 1515, 1495, 1510, 900, 0]]}})
        if path == "/v3/market-quote/quotes":
            return httpx.Response(200, json={"status": "success", "data": {"NSE_EQ:RELIANCE": {
                "instrument_token": "NSE_EQ|INE002A01018", "last_price": 1521.0, "prev_close_price": 1500.0, "volume": 5,
                "ohlc": {"open": 1505, "high": 1530, "low": 1499, "close": 1521},
                "depth": {"buy": [{"price": 1520.9, "quantity": 10, "orders": 1}], "sell": [{"price": 1521.1, "quantity": 5, "orders": 1}]}}}})
        if path == "/v2/option/contract":
            return httpx.Response(200, json={"status": "success", "data": [{"expiry": "2099-11-24"}]})
        if path == "/v2/option/chain":
            return httpx.Response(200, json={"status": "success", "data": [{
                "strike_price": 26200, "underlying_spot_price": 26180, "pcr": 1.1,
                "call_options": {"instrument_key": "NSE_FO|1", "market_data": {"ltp": 80, "oi": 1000, "prev_oi": 900, "volume": 50},
                                 "option_greeks": {"delta": 0.5, "iv": 12.5}},
                "put_options": {"instrument_key": "NSE_FO|2", "market_data": {"ltp": 95, "oi": 1100, "prev_oi": 1000, "volume": 60},
                                "option_greeks": {"delta": -0.5, "iv": 13.0}}}]})
        if path.startswith("/v2/market/status/"):
            return httpx.Response(200, json={"status": "success", "data": {"status": "NORMAL_OPEN"}})
        if path == "/v2/market/holidays":
            return httpx.Response(429, json={"status": "error"})
        return httpx.Response(404, json={"status": "error", "errors": [{"message": "nope"}]})

    return httpx.MockTransport(handler)


async def test_upstox_provider_with_mock_transport(monkeypatch):
    transport = _upstox_transport()
    real_client = httpx.AsyncClient

    def patched(*a, **kw):
        kw.setdefault("transport", transport)
        return real_client(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    p = UpstoxProvider(token="t", transport=transport)
    ins = await p.instruments()
    syms = {i.symbol for i in ins}
    assert {"NSE:RELIANCE", "NSE_INDEX:NIFTY", "NFO:NIFTY24NOV2626200CE"} <= syms
    q = (await p.quotes(["NSE:RELIANCE"]))["NSE:RELIANCE"]
    assert q.ltp == 1521 and q.bid == 1520.9 and round(q.change_pct, 2) == 1.4
    cs = await p.candles("NSE:RELIANCE", Interval.D1, datetime(2026, 11, 1, tzinfo=IST), datetime(2026, 11, 14, tzinfo=IST))
    assert [c.close for c in cs] == [1510, 1520]
    chain = await p.option_chain("NIFTY")
    assert chain.rows[0].call.symbol == "NFO:NIFTY24NOV2626200CE" and chain.rows[0].put.oi_change == 100
    assert (await p.market_status())[0].is_open is True
    await p.close()


def test_instrument_mapping_tick_size():
    ins = instrument_from_upstox({"segment": "BSE_EQ", "instrument_key": "BSE_EQ|X", "trading_symbol": "TCS",
                                  "instrument_type": "EQ", "tick_size": 5.0, "name": "TCS"})
    assert ins and ins.symbol == "BSE:TCS" and ins.tick_size == 0.05


async def test_mock_nse_tools():
    tools = MockNseTools()
    names = {t["name"] for t in await tools.list_tools()}
    assert "get_fii_dii_activity" in names
    res = await tools.call_tool("get_fii_dii_activity", {"days": 5})
    assert len(res["rows"]) == 5 and "fii_net" in res["rows"][0]
    sh = await tools.call_tool("get_shareholding_pattern", {"symbol": "NSE:RELIANCE"})
    assert pytest.approx(sh["promoter"] + sh["fii"] + sh["dii"] + sh["public"], abs=0.01) == 100 or sh["public"] == 2
