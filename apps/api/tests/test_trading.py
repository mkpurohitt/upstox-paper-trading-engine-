import pyotp
from tests.conftest import register

from strategy_engine.templates import TEMPLATES


def test_paper_order_positions_funds_and_audit(client, auth_headers):
    h = auth_headers
    r = client.post("/api/orders", json={"symbol": "NSE:INFY", "side": "BUY", "quantity": 5, "mode": "paper"}, headers=h)
    assert r.status_code == 201, r.text
    o = r.json()[0]
    assert o["status"] == "complete" and o["algo_id"].startswith("ALGO-PENDING")
    pos = client.get("/api/positions", params={"mode": "paper"}, headers=h).json()
    assert pos[0]["symbol"] == "NSE:INFY" and pos[0]["quantity"] == 5
    funds = client.get("/api/funds", headers=h).json()
    assert funds["used"] > 0
    r = client.post("/api/orders", json={"symbol": "NSE:INFY", "side": "BUY", "quantity": 99999, "mode": "paper"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["decision"]["rule"] == "max_qty_per_order"
    audit = client.get("/api/risk/audit", headers=h).json()
    assert {"risk.reject", "order.place", "risk.allow"} <= {a["action"] for a in audit}
    chk = client.post("/api/risk/check", json={"symbol": "NSE:INFY", "side": "SELL", "quantity": 5}, headers=h).json()
    assert chk["allowed"] is True and chk["reducing"] is True


def test_live_order_requires_2fa(client, auth_headers):
    r = client.post("/api/orders", json={"symbol": "NSE:INFY", "side": "BUY", "quantity": 1, "mode": "live"}, headers=auth_headers)
    assert r.status_code == 403 and "two-factor" in r.json()["detail"].lower()


def test_kill_switch_endpoint(client, auth_headers):
    h = auth_headers
    client.post("/api/orders", json={"symbol": "NSE:TCS", "side": "BUY", "quantity": 2}, headers=h)
    r = client.post("/api/risk/kill-switch", json={"engaged": True, "square_off": True}, headers=h).json()
    assert r["user_engaged"] is True and r["summary"]["squared_off"] == 1
    r = client.post("/api/orders", json={"symbol": "NSE:TCS", "side": "BUY", "quantity": 1}, headers=h)
    assert r.status_code == 409
    assert client.post("/api/risk/kill-switch", json={"engaged": False}, headers=h).json()["user_engaged"] is False


def test_risk_limits_and_broker_connections(client, auth_headers):
    h = auth_headers
    r = client.put("/api/risk/limits", json={"max_loss_per_day": 5000, "allowed_exchanges": ["NSE", "NFO"]}, headers=h)
    assert r.json()["max_loss_per_day"] == 5000 and r.json()["sebi_order_rate_limit_per_sec"] < 10
    cat = client.get("/api/brokers/catalog", headers=h).json()
    assert len(cat) == 10
    r = client.post("/api/brokers/connections", json={"broker": "zerodha", "credentials": {"api_key": "k"}}, headers=h)
    assert r.status_code == 422
    r = client.post("/api/brokers/connections", json={"broker": "zerodha", "label": "Kite",
                                                       "credentials": {"api_key": "kitekey123", "api_secret": "supersecret"}}, headers=h)
    assert r.status_code == 201
    conn = r.json()
    assert conn["status"] == "disconnected" and conn["is_default"] is True and "supersecret" not in r.text
    url = client.get(f"/api/brokers/connections/{conn['id']}/oauth-url", headers=h).json()["url"]
    assert "kite.zerodha.com/connect/login" in url and "kitekey123" in url
    assert client.delete(f"/api/brokers/connections/{conn['id']}", headers=h).status_code == 200


def test_deploy_paper_and_controls(client):
    tok = register(client, "deployer@example.com")
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    s = client.post("/api/strategies", json={"dsl": TEMPLATES[0]}, headers=h).json()
    r = client.post("/api/deployments", json={"strategy_id": s["id"], "mode": "paper", "acknowledge_risk": False}, headers=h)
    assert r.status_code == 422
    r = client.post("/api/deployments", json={"strategy_id": s["id"], "mode": "paper", "acknowledge_risk": True,
                                              "risk_limits": {"max_loss_per_day": 3000}}, headers=h)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "running" and d["algo_id"].endswith(f"S{s['id']}") and d["symbols"]
    assert client.post(f"/api/deployments/{d['id']}/pause", headers=h).json()["status"] == "paused"
    assert client.post(f"/api/deployments/{d['id']}/resume", headers=h).json()["status"] == "running"
    assert client.post(f"/api/deployments/{d['id']}/stop", headers=h).json()["status"] == "stopped"
    # live deploy requires 2FA
    r = client.post("/api/deployments", json={"strategy_id": s["id"], "mode": "live", "acknowledge_risk": True}, headers=h)
    assert r.status_code == 403
    setup = client.post("/api/auth/2fa/setup", headers=h).json()
    client.post("/api/auth/2fa/enable", headers=h, json={"code": pyotp.TOTP(setup["secret"]).now()})
    r = client.post("/api/deployments", json={"strategy_id": s["id"], "mode": "live", "acknowledge_risk": True,
                                              "totp_code": "000000"}, headers=h)
    assert r.status_code == 401
