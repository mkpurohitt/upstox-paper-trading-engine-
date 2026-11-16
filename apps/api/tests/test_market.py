import time


def test_market_endpoints(client, auth_headers):
    h = auth_headers
    r = client.get("/api/market/quotes", params={"symbols": "NSE_INDEX:NIFTY,NSE:RELIANCE,BAD:SYM"}, headers=h)
    assert r.status_code == 200
    syms = [q["symbol"] for q in r.json()]
    assert syms == ["NSE_INDEX:NIFTY", "NSE:RELIANCE"]

    r = client.get("/api/market/candles", params={"symbol": "NSE:TCS", "interval": "1d", "days": 60}, headers=h)
    assert r.status_code == 200 and len(r.json()) > 30

    r = client.get("/api/market/candles", params={"symbol": "NSE:TCS", "interval": "5m", "days": 3}, headers=h)
    assert r.status_code == 200 and len(r.json()) > 0

    r = client.get("/api/market/option-chain", params={"underlying": "BANKNIFTY", "strikes": 5}, headers=h)
    body = r.json()
    assert r.status_code == 200 and len(body["rows"]) == 11 and body["lot_size"] == 30

    r = client.get("/api/market/search", params={"q": "relia"}, headers=h)
    assert r.json()[0]["symbol"] == "NSE:RELIANCE"

    r = client.get("/api/market/overview", headers=h)
    ov = r.json()
    assert r.status_code == 200 and len(ov["top_gainers"]) == 10 and ov["breadth"]["universe"] > 50
    assert ov["fii_dii"]["rows"]

    assert client.get("/api/market/status", headers=h).json()[0]["exchange"] == "NSE"
    tools = client.get("/api/market/nse/tools", headers=h).json()
    assert any(t["name"] == "get_bulk_block_deals" for t in tools)
    r = client.post("/api/market/nse/tools/get_market_breadth", json={}, headers=h)
    assert "advances" in r.json()


def test_ws_tick_stream(client, auth_headers):
    token = auth_headers["Authorization"].split()[1]
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "subscribe", "channel": "ticks", "symbols": ["NSE:INFY"]})
        assert ws.receive_json()["type"] == "subscribed"
        deadline = time.time() + 8
        got = None
        while time.time() < deadline:
            msg = ws.receive_json()
            if msg["type"] == "tick" and msg["data"]["symbol"] == "NSE:INFY":
                got = msg
                break
        assert got is not None and got["data"]["ltp"] > 0
