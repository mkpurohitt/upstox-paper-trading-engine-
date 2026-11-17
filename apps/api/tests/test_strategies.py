import time

from strategy_engine.templates import TEMPLATES


def _wait(client, h, bt_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/backtests/{bt_id}", headers=h).json()
        if r["status"] in ("completed", "failed"):
            return r
        time.sleep(0.3)
    raise AssertionError("backtest did not finish")


def test_strategy_crud_versions_and_validation(client, auth_headers):
    h = auth_headers
    r = client.post("/api/strategies/validate", json={"name": "x", "kind": "equity"}, headers=h)
    assert r.json()["valid"] is False and r.json()["errors"]

    r = client.post("/api/strategies", json={"dsl": TEMPLATES[0], "source": "template"}, headers=h)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["version"] == 1 and s["kind"] == "equity"

    dsl = {**s["dsl"], "description": "tweaked"}
    r = client.put(f"/api/strategies/{s['id']}", json={"dsl": dsl, "source": "form"}, headers=h)
    assert r.json()["version"] == 2
    assert len(client.get(f"/api/strategies/{s['id']}/versions", headers=h).json()) == 2

    # invalid DSL rejected with a 422
    bad = {**dsl, "indicators": []}
    assert client.put(f"/api/strategies/{s['id']}", json={"dsl": bad}, headers=h).status_code == 422

    assert len(client.get("/api/strategies/indicators", headers=h).json()) > 20
    assert "properties" in client.get("/api/strategies/dsl/schema", headers=h).json()

    # black-box listing needs an RA number
    r = client.patch(f"/api/strategies/{s['id']}/listing", json={"visibility": "marketplace", "box_type": "black_box"}, headers=h)
    assert r.status_code == 422
    r = client.patch(f"/api/strategies/{s['id']}/listing",
                     json={"visibility": "marketplace", "box_type": "black_box", "provider_ra_number": "INH000012345"}, headers=h)
    assert r.status_code == 200 and r.json()["ra_status"] == "pending"


def test_code_mode_compile(client, auth_headers):
    code = client.get("/api/strategies/code-template", headers=auth_headers).json()["code"]
    r = client.post("/api/strategies/compile-code", json={"code": code}, headers=auth_headers)
    assert r.json()["ok"] is True, r.json()
    r = client.post("/api/strategies/compile-code", json={"code": "import os"}, headers=auth_headers)
    assert r.json()["ok"] is False and "not allowed" in r.json()["errors"][0]["message"]


def test_backtest_job_lifecycle(client, auth_headers):
    h = auth_headers
    s = client.post("/api/strategies", json={"dsl": TEMPLATES[4], "source": "template"}, headers=h).json()
    r = client.post("/api/backtests", json={"strategy_id": s["id"], "kind": "backtest", "params": {
        "start": "2024-01-01T00:00:00+05:30", "end": "2026-11-01T00:00:00+05:30", "initial_capital": 500000,
        "broker": "zerodha", "options": {"monte_carlo": True}}}, headers=h)
    assert r.status_code == 202, r.text
    bt = _wait(client, h, r.json()["id"])
    assert bt["status"] == "completed", bt.get("error")
    assert bt["metrics"]["trades"] >= 1 and bt["equity_curve"] and bt["extra"]["charges_breakdown"]
    trades = client.get(f"/api/backtests/{bt['id']}/trades", headers=h).json()
    assert len(trades) == bt["metrics"]["trades"]
    lst = client.get(f"/api/strategies/{s['id']}", headers=h).json()
    assert lst["last_backtest"]["id"] == bt["id"]

    r = client.post("/api/backtests", json={"strategy_id": s["id"], "kind": "optimise", "params": {
        "start": "2022-01-01T00:00:00+05:30", "end": "2026-11-01T00:00:00+05:30",
        "options": {"space": [{"path": "indicators.rsi.params.period", "values": [10, 14]}], "objective": "sharpe"}}}, headers=h)
    opt = _wait(client, h, r.json()["id"])
    assert opt["status"] == "completed", opt.get("error")
    assert opt["extra"]["optimisation"]["combinations"] == 2


def test_backtest_ws_progress(client, auth_headers):
    h = auth_headers
    token = h["Authorization"].split()[1]
    s = client.post("/api/strategies", json={"dsl": TEMPLATES[0]}, headers=h).json()
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "ready"
        r = client.post("/api/backtests", json={"strategy_id": s["id"], "params": {
            "start": "2026-08-01T00:00:00+05:30", "end": "2026-11-01T00:00:00+05:30"}}, headers=h)
        ws.send_json({"type": "subscribe", "channel": "backtest", "id": r.json()["id"]})
        statuses = set()
        deadline = time.time() + 60
        while time.time() < deadline and "completed" not in statuses and "failed" not in statuses:
            msg = ws.receive_json()
            if msg["type"] == "backtest":
                statuses.add(msg["data"]["status"])
        assert "completed" in statuses
