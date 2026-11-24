"""Charts terminal APIs: bars + paging, layouts, price alerts, and the admin Upstox token switch."""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import UTC, datetime

from tests.conftest import register


def _user(client) -> tuple[dict[str, str], str]:
    email = f"chart-{uuid.uuid4().hex[:8]}@example.com"
    return {"Authorization": f"Bearer {register(client, email)['access_token']}"}, email


def _admin(client) -> dict[str, str]:
    h, email = _user(client)

    async def promote():
        from sqlalchemy import update

        from algo_db.models import User
        from algo_db.session import session_scope

        async with session_scope() as db:
            await db.execute(update(User).where(User.email == email).values(role="admin"))

    client.portal.call(promote)
    return h


def test_bars_timeframes_and_paging(client, auth_headers):
    src = client.get("/api/charts/source", headers=auth_headers).json()
    assert src["live"] is False and src["provider"] == "mock" and "Simulated" in src["label"]
    for tf, label in (("1", "1m"), ("45", "45m"), ("60", "1h"), ("D", "1D"), ("W", "1W"), ("M", "1M")):
        r = client.get(f"/api/charts/bars?symbol=NSE:RELIANCE&tf={tf}&count=120", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        bars = d["bars"]
        assert d["label"] == label and 0 < len(bars) <= 120 and d["source"]["provider"] == "mock"
        assert all(b["l"] <= min(b["o"], b["c"]) and b["h"] >= max(b["o"], b["c"]) for b in bars)
        assert [b["t"] for b in bars] == sorted({b["t"] for b in bars})  # strictly increasing, unique
        assert ("d" in bars[0]) == (tf in ("D", "W", "M"))
    first = client.get("/api/charts/bars?symbol=NSE:RELIANCE&tf=15&count=100", headers=auth_headers).json()
    older = client.get("/api/charts/bars", params={"symbol": "NSE:RELIANCE", "tf": "15", "count": 100, "to": first["next_to"]},
                       headers=auth_headers).json()
    assert first["has_more"] and older["bars"] and older["bars"][-1]["t"] < first["bars"][0]["t"]
    assert client.get("/api/charts/bars?symbol=NSE:RELIANCE&tf=abc", headers=auth_headers).status_code == 422
    assert client.get("/api/charts/bars?symbol=NSE:NOPE&tf=D", headers=auth_headers).status_code == 404


def test_layouts_crud_default_and_isolation(client):
    h, _ = _user(client)
    other, _ = _user(client)
    a = client.post("/api/charts/layouts", json={"name": "Main", "state": {"cells": [{"symbol": "NSE:INFY"}]}}, headers=h).json()
    assert a["is_default"] is True  # the first layout becomes the default
    b = client.post("/api/charts/layouts", json={"name": "Options", "state": {}, "is_default": True}, headers=h).json()
    rows = client.get("/api/charts/layouts", headers=h).json()
    assert [r["name"] for r in rows] == ["Options", "Main"] and [r["is_default"] for r in rows] == [True, False]
    assert "state" not in rows[0]
    assert client.get(f"/api/charts/layouts/{a['id']}", headers=h).json()["state"]["cells"][0]["symbol"] == "NSE:INFY"
    client.put(f"/api/charts/layouts/{a['id']}", json={"name": "Main 2", "state": {"x": 1}}, headers=h)
    got = client.get(f"/api/charts/layouts/{a['id']}", headers=h).json()
    assert got["name"] == "Main 2" and got["state"] == {"x": 1}
    big = {"drawings": ["x" * 1000] * 600}
    assert client.put(f"/api/charts/layouts/{a['id']}", json={"state": big}, headers=h).status_code == 413
    assert client.get(f"/api/charts/layouts/{a['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/charts/layouts/{b['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/charts/layouts/{b['id']}", headers=h).status_code == 200
    assert len(client.get("/api/charts/layouts", headers=h).json()) == 1


def test_price_alerts_fire_once_with_notification(client, monkeypatch):
    from algo_common.schemas.market import Quote
    from algo_jobs.price_alerts import evaluate_once
    from market_data.registry import get_mock

    h, _ = _user(client)
    ltp = client.get("/api/market/quote/NSE:SBIN", headers=h).json()["ltp"]
    r = client.post("/api/alerts", json={"symbol": "NSE:SBIN", "value": round(ltp * 1.05, 2), "message": "breakout"}, headers=h)
    assert r.status_code == 201, r.text
    alert = r.json()
    assert alert["op"] == "above" and alert["status"] == "active"
    below = client.post("/api/alerts", json={"symbol": "NSE:SBIN", "value": round(ltp * 0.9, 2)}, headers=h).json()
    assert below["op"] == "below"
    # a level the price is already past is refused (it would fire instantly)
    assert client.post("/api/alerts", json={"symbol": "NSE:SBIN", "value": round(ltp * 0.9, 2), "op": "above"}, headers=h).status_code == 422
    assert len(client.get("/api/alerts?symbol=NSE:SBIN", headers=h).json()) == 2

    async def jump(symbols):
        return {s: Quote(symbol=s, ts=datetime.now(UTC), ltp=ltp * 1.06) for s in symbols}

    monkeypatch.setattr(get_mock(), "quotes", jump)
    assert client.portal.call(evaluate_once) >= 1
    rows = {a["id"]: a for a in client.get("/api/alerts", headers=h).json()}
    assert rows[alert["id"]]["status"] == "triggered" and rows[below["id"]]["status"] == "active"
    assert client.portal.call(evaluate_once) == 0  # fires once
    notes = client.get("/api/notifications", headers=h).json()
    assert any("SBIN crossed above" in n["title"] for n in notes["items"])
    monkeypatch.undo()
    re = client.patch(f"/api/alerts/{alert['id']}", json={"status": "active", "value": round(ltp * 1.2, 2)}, headers=h).json()
    assert re["status"] == "active" and re["op"] == "above"
    assert client.delete(f"/api/alerts/{alert['id']}", headers=h).status_code == 200


def _jwt(exp: int) -> str:
    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64({'sub': 'TEST', 'exp': exp})}.signature0123456789"


def test_admin_switches_to_live_upstox_and_back(client, monkeypatch):
    from app.routes import admin as admin_routes
    from market_data.registry import get_provider

    user, _ = _user(client)
    h = _admin(client)
    assert client.get("/api/admin/market-data", headers=user).status_code == 403
    status = client.get("/api/admin/market-data", headers=h).json()
    assert status["live"] is False and status["saved"] is False

    async def reject(token):
        from algo_common.errors import ProviderError

        raise ProviderError("Upstox error: Invalid token used to access API", details={"status": 401})

    monkeypatch.setattr(admin_routes, "verify_upstox_token", reject)
    r = client.put("/api/admin/market-data", json={"token": _jwt(int(time.time()) + 3600), "enabled": True}, headers=h)
    assert r.status_code == 422 and "invalid or has expired" in r.json()["error"]["message"]
    assert client.put("/api/admin/market-data", json={"enabled": True}, headers=h).status_code == 422  # no token yet

    async def accept(token):
        return {"nifty_ltp": 26123.45}

    monkeypatch.setattr(admin_routes, "verify_upstox_token", accept)
    token = _jwt(int(time.time()) + 3600)
    try:
        r = client.put("/api/admin/market-data", json={"token": f"Bearer {token}", "enabled": True}, headers=h)
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["live"] is True and s["name"] == "upstox" and s["source"] == "admin" and s["enabled"] is True
        assert s["token_hint"] and token not in json.dumps(s) and s["expires_at"] and s["expired"] is False
        assert s["verified_nifty_ltp"] == 26123.45
        assert get_provider().name == "upstox"
        assert client.get("/api/charts/source", headers=user).json()["live"] is True
        # paused: keeps the token, back to simulated data
        s = client.put("/api/admin/market-data", json={"enabled": False}, headers=h).json()
        assert s["live"] is False and s["saved"] is True and s["token_hint"]
        s = client.put("/api/admin/market-data", json={"enabled": True}, headers=h).json()
        assert s["live"] is True
        audit = client.get("/api/admin/audit?action=market_data.configure", headers=h)
        assert audit.status_code == 200 and len(audit.json()) >= 3 and token not in audit.text
    finally:
        s = client.delete("/api/admin/market-data", headers=h).json()
    assert s["live"] is False and s["saved"] is False and get_provider().name == "mock"
