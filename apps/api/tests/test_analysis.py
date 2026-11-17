def test_options_dashboards(client, auth_headers):
    h = auth_headers
    r = client.get("/api/analysis/option-chain", params={"underlying": "NIFTY", "strikes": 8}, headers=h).json()
    a = r["analytics"]
    assert len(a["strikes"]) == 17 and a["expected_range"][0] < r["chain"]["spot"] < a["expected_range"][1]
    assert {x["call_buildup"] for x in a["strikes"]} <= {"Long buildup", "Short buildup", "Short covering", "Long unwinding"}

    p = client.post("/api/analysis/payoff", json={"underlying": "NIFTY", "structure": "iron_condor", "days_forward": 0}, headers=h).json()
    assert len(p["legs"]) == 4 and len(p["breakevens"]) == 2 and p["max_loss"] < 0 and 0 < p["pop"] <= 1
    p2 = client.post("/api/analysis/payoff", json={"underlying": "BANKNIFTY", "legs": [
        {"action": "BUY", "option_type": "CE", "offset": 0}, {"action": "SELL", "option_type": "CE", "offset": 4}]}, headers=h).json()
    assert p2["max_profit"] > 0 and p2["max_loss"] < 0
    naked = client.post("/api/analysis/payoff", json={"structure": "short_straddle"}, headers=h).json()
    assert naked["max_loss"] is None  # unlimited risk

    s = client.get("/api/analysis/straddle", params={"underlying": "NIFTY", "otm_steps": 2}, headers=h).json()
    assert s["type"] == "strangle" and s["breakevens"][0] < s["spot"] < s["breakevens"][1] and s["decay"]

    rs = client.post("/api/analysis/ratio-spreads", json={"underlying": "NIFTY", "kind": "PE"}, headers=h).json()
    assert rs["candidates"] and all(c["legs"][1]["lots"] >= 2 for c in rs["candidates"])

    arb = client.get("/api/analysis/arbitrage", headers=h).json()
    assert arb["cash_futures"] and arb["nse_bse"] and arb["put_call_parity"] and arb["calendar"]


def test_equity_dashboards(client, auth_headers):
    h = auth_headers
    t = client.get("/api/analysis/technical", params={"symbol": "NSE:TCS", "interval": "1d", "indicators": "EMA:20,RSI,MACD"}, headers=h).json()
    assert t["candles"] and {o["kind"] for o in t["overlays"]} == {"EMA"} and {o["kind"] for o in t["oscillators"]} == {"RSI", "MACD"}
    assert set(t["mtf"]) == {"15m", "1h", "1d"}
    f = client.get("/api/analysis/fundamentals", params={"symbol": "NSE:INFY"}, headers=h).json()
    assert f["source"] == "mock" and len(f["annual"]) == 5 and f["peers"]
    assert client.get("/api/analysis/fundamentals", params={"symbol": "NSE_INDEX:NIFTY"}, headers=h).status_code == 404
    q = client.get("/api/analysis/quant", params={"symbol": "NSE:SBIN", "basket": "NSE:PNB,NSE:BANKBARODA"}, headers=h).json()
    assert len(q["correlation"]["matrix"]) == 4 and q["histogram"] and q["seasonality_month"]
    pr = client.get("/api/analysis/pairs", params={"a": "NSE:HDFCBANK", "b": "NSE:ICICIBANK"}, headers=h).json()
    assert 0 <= pr["engle_granger"]["p_value"] <= 1 and pr["series"]


def test_screener_and_saved_screens(client, auth_headers):
    h = auth_headers
    q = {"universe": "NIFTY100", "conditions": [{"field": "rsi14", "op": "<", "value": 100}, {"field": "pe", "op": ">", "value": 0}],
         "sort_by": "market_cap_cr", "limit": 5}
    r = client.post("/api/analysis/screener/run", json=q, headers=h).json()
    assert r["scanned"] > 50 and len(r["rows"]) == 5
    assert r["rows"][0]["market_cap_cr"] >= r["rows"][-1]["market_cap_cr"]
    assert client.post("/api/analysis/screener/run", json={"conditions": [{"field": "bogus", "op": ">", "value": 1}]}, headers=h).status_code == 422
    s = client.post("/api/analysis/screens", json={"name": "cheap", "query": q, "alert_enabled": True}, headers=h)
    assert s.status_code == 201
    assert client.get("/api/analysis/screens", headers=h).json()[0]["name"] == "cheap"
    w = client.post("/api/watchlists", json={"name": "Banks", "symbols": ["NSE:SBIN", "NSE:SBIN", "NSE:PNB"]}, headers=h).json()
    assert w["symbols"] == ["NSE:SBIN", "NSE:PNB"]
