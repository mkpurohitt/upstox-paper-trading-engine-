import pyotp
from tests.conftest import register


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] is True and body["data_mode"] == "mock"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_register_login_me_refresh_logout(client):
    tok = register(client, "alice@example.com")
    assert tok["user"]["plan"] == "free"
    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.get("/api/me", headers=headers).json()["email"] == "alice@example.com"

    # duplicate
    r = client.post("/api/auth/register", json={"email": "alice@example.com", "password": "password123",
                                                "accept_terms": True, "accept_privacy": True})
    assert r.status_code == 409

    r = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-pass"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "password123"})
    assert r.status_code == 200 and r.json()["token"]["access_token"]

    # refresh requires CSRF double-submit
    assert client.post("/api/auth/refresh").status_code == 403
    csrf = client.cookies.get("algo_csrf")
    r = client.post("/api/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    csrf = client.cookies.get("algo_csrf")
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200


def test_refresh_token_reuse_revokes_family(client):
    register(client, "bob@example.com")
    old_refresh = client.cookies.get("algo_refresh")
    csrf = client.cookies.get("algo_csrf")
    assert client.post("/api/auth/refresh", headers={"X-CSRF-Token": csrf}).status_code == 200
    # replay the rotated (old) token
    client.cookies.clear()
    r = client.post(
        "/api/auth/refresh",
        headers={"X-CSRF-Token": csrf, "Cookie": f"algo_refresh={old_refresh}; algo_csrf={csrf}"},
    )
    assert r.status_code == 401


def test_totp_2fa_flow(client):
    tok = register(client, "carol@example.com")
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    setup = client.post("/api/auth/2fa/setup", headers=h).json()
    code = pyotp.TOTP(setup["secret"]).now()
    r = client.post("/api/auth/2fa/enable", headers=h, json={"code": code})
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 8
    recovery = r.json()["recovery_codes"][0]

    r = client.post("/api/auth/login", json={"email": "carol@example.com", "password": "password123"})
    body = r.json()
    assert body["requires_2fa"] and body["token"] is None
    # same code cannot be replayed (replay protection) -> use recovery code
    r = client.post("/api/auth/login/2fa", json={"challenge_token": body["challenge_token"], "code": code})
    assert r.status_code == 401
    r = client.post("/api/auth/login/2fa", json={"challenge_token": body["challenge_token"], "code": recovery})
    assert r.status_code == 200 and r.json()["user"]["totp_enabled"] is True


def test_requires_auth(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_demo_login(client):
    r = client.post("/api/auth/demo")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "demo@algodesk.in"


def test_websocket_auth(client):
    tok = register(client, "dave@example.com")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": tok["access_token"]})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": "bad"})
        assert ws.receive_json()["type"] == "error"
