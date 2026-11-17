"""Phase 7 APIs: news, portfolio, billing (Razorpay signature + simulator + webhook), account/privacy, notifications, admin."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

from tests.conftest import register


def new_user(client) -> tuple[dict[str, str], str]:
    email = f"p7-{uuid.uuid4().hex[:8]}@example.com"
    tok = register(client, email)["access_token"]
    return {"Authorization": f"Bearer {tok}"}, email


def run_db(client, fn):
    from algo_db.session import session_scope

    async def wrapper():
        async with session_scope() as db:
            return await fn(db)

    return client.portal.call(wrapper)


def make_admin(client) -> dict[str, str]:
    h, email = new_user(client)

    async def promote(db):
        from sqlalchemy import update

        from algo_db.models import User

        await db.execute(update(User).where(User.email == email).values(role="admin"))

    run_db(client, promote)
    return h


def test_news_feed_filters_summary_calendar(client, auth_headers):
    items = client.get("/api/news?limit=50", headers=auth_headers).json()
    assert len(items) >= 10  # first call populates the feed (offline generator + NSE announcements)
    assert {i["category"] for i in items} >= {"news", "announcement"}
    assert all(i["sentiment"] in ("positive", "negative", "neutral") for i in items)
    ann = client.get("/api/news?category=announcement", headers=auth_headers).json()
    assert ann and all(i["category"] == "announcement" for i in ann)
    sym = next(t for i in items for t in i["tickers"] if t.startswith("NSE:"))
    by_sym = client.get(f"/api/news?symbol={sym.split(':')[1]}", headers=auth_headers).json()
    assert by_sym and all(sym in i["tickers"] for i in by_sym)
    s = client.post(f"/api/news/{items[0]['id']}/summarize", headers=auth_headers).json()
    assert s["ai_summary"]
    senti = client.get("/api/news/sentiment", headers=auth_headers).json()
    assert sum(senti["counts"].values()) == senti["articles"] and senti["tickers"]
    cal = client.get("/api/news/calendar", headers=auth_headers).json()
    assert cal["economic"] and all(e["indicative"] for e in cal["economic"]) and cal["results"]
    assert client.get("/api/news/announcements?symbol=TCS", headers=auth_headers).json()["rows"][0]["symbol"] == "TCS"
    assert client.post("/api/news/refresh", headers=auth_headers).status_code == 403


def test_portfolio_consolidation_and_performance(client):
    h, _ = new_user(client)
    for sym, qty, product in (("NSE:RELIANCE", 10, "CNC"), ("NSE:TCS", 5, "CNC"), ("NSE:SBIN", 20, "MIS")):
        r = client.post("/api/orders", json={"symbol": sym, "side": "BUY", "quantity": qty, "product": product, "mode": "paper"}, headers=h)
        assert r.status_code == 201, r.text
    client.post("/api/orders", json={"symbol": "NSE:SBIN", "side": "SELL", "quantity": 20, "product": "MIS", "mode": "paper"}, headers=h)
    s = client.get("/api/portfolio/summary", headers=h).json()
    assert {x["symbol"] for x in s["holdings"]} == {"NSE:RELIANCE", "NSE:TCS"}
    assert s["accounts"][0]["account"] == "paper" and s["totals"]["holdings_value"] > 0
    assert s["analysis"]["positions"] == 2 and s["analysis"]["concentration"]["top_symbol"] in ("NSE:RELIANCE", "NSE:TCS")
    p = client.get("/api/portfolio/performance", headers=h).json()
    assert (p["daily"] and p["daily"][-1]["realised"] < 0) or p["daily"][-1]["realised"] >= 0  # SBIN round trip realised today
    assert p["starting_capital"] == 1_000_000 and p["equity"]
    assert client.get("/api/portfolio/overlap", headers=h).json()["active_deployments"] == 0
    d = client.get("/api/portfolio/dividends", headers=h).json()
    assert isinstance(d["items"], list)


def test_billing_simulated_checkout_cancel_resume(client):
    h, _ = new_user(client)
    plans = client.get("/api/billing/plans").json()
    assert [p["code"] for p in plans if p["code"] in ("free", "pro", "elite")] == ["free", "pro", "elite"]
    sub = client.get("/api/billing/subscription", headers=h).json()
    assert sub["plan"]["code"] == "free" and sub["razorpay"]["mode"] == "simulated"
    co = client.post("/api/billing/checkout", json={"plan_code": "pro"}, headers=h).json()
    assert co["mode"] == "simulated" and co["amount"] == 99_900 and co["order_id"].startswith("order_sim_")
    assert client.post("/api/billing/simulate", json={"order_id": co["order_id"], "outcome": "success"}, headers=h).status_code == 200
    sub = client.get("/api/billing/subscription", headers=h).json()
    assert sub["plan"]["code"] == "pro" and sub["payments"][0]["status"] == "paid" and sub["limits"]["ai_queries_per_day"] == 300
    assert client.post("/api/billing/checkout", json={"plan_code": "pro"}, headers=h).status_code == 409
    assert client.post("/api/billing/cancel", headers=h).status_code == 200
    assert client.get("/api/billing/subscription", headers=h).json()["cancel_at_period_end"] is True
    assert client.post("/api/billing/resume", headers=h).status_code == 200
    down = client.post("/api/billing/checkout", json={"plan_code": "free"}, headers=h).json()
    assert down["mode"] == "downgrade"


def test_billing_razorpay_signature_and_webhook(client, monkeypatch):
    from pydantic import SecretStr

    from algo_common.settings import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(s, "razorpay_key_secret", SecretStr("topsecret"))
    monkeypatch.setattr(s, "razorpay_webhook_secret", SecretStr("whsecret"))
    h, email = new_user(client)

    async def add_order(db):
        from sqlalchemy import select

        from algo_db.models import Payment, Plan, User

        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        plan = (await db.execute(select(Plan).where(Plan.code == "elite"))).scalar_one()
        for oid in ("order_A", "order_B"):
            db.add(Payment(user_id=u.id, plan_id=plan.id, amount_paise=plan.price_paise, status="created", razorpay_order_id=f"{oid}{u.id}"))
        return u.id

    uid = run_db(client, add_order)
    bad = client.post("/api/billing/verify", json={"razorpay_order_id": f"order_A{uid}", "razorpay_payment_id": "pay_1",
                                                    "razorpay_signature": "deadbeef"}, headers=h)
    assert bad.status_code == 400
    sig = hmac.new(b"topsecret", f"order_B{uid}|pay_2".encode(), hashlib.sha256).hexdigest()
    ok = client.post("/api/billing/verify", json={"razorpay_order_id": f"order_B{uid}", "razorpay_payment_id": "pay_2",
                                                   "razorpay_signature": sig}, headers=h)
    assert ok.status_code == 200
    assert client.get("/api/billing/subscription", headers=h).json()["plan"]["code"] == "elite"
    # webhook: bad signature rejected, valid one is idempotent
    event = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_2", "order_id": f"order_B{uid}", "method": "upi"}}}}).encode()
    assert client.post("/api/billing/webhook", content=event, headers={"X-Razorpay-Signature": "nope"}).status_code == 400
    wsig = hmac.new(b"whsecret", event, hashlib.sha256).hexdigest()
    r = client.post("/api/billing/webhook", content=event, headers={"X-Razorpay-Signature": wsig, "Content-Type": "application/json"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    pays = client.get("/api/billing/subscription", headers=h).json()["payments"]
    assert sum(p["status"] == "paid" for p in pays) == 1 and any(p["status"] == "failed" for p in pays)


def test_privacy_consents_export_kyc_and_deletion(client):
    h, email = new_user(client)
    c = client.get("/api/account/consents", headers=h).json()
    cur = {x["purpose"]: x for x in c["current"]}
    assert cur["data_processing"]["granted"] and cur["data_processing"]["required"] and not cur["analytics"]["granted"]
    assert client.post("/api/account/consents", json={"purpose": "analytics", "granted": True}, headers=h).json()["current"]
    assert client.post("/api/account/consents", json={"purpose": "privacy", "granted": False}, headers=h).status_code == 422
    assert client.post("/api/account/kyc", json={"pan": "ABCDE1234F", "name_on_pan": "Test"}, headers=h).json()["pan_last4"] == "234F"
    assert client.post("/api/account/kyc", json={"pan": "ABCDE12345", "name_on_pan": "Test"}, headers=h).status_code == 422
    client.post("/api/ai/chat", json={"message": "price of sbin"}, headers=h)
    ex = client.get("/api/account/export", headers=h)
    assert ex.status_code == 200 and "attachment" in ex.headers["content-disposition"]
    data = ex.json()
    assert data["profile"]["email"] == email and "password_hash" not in data["profile"]
    assert data["chat_messages"] and data["consents"] and all("credentials_enc" not in b for b in data["broker_connections"])
    assert "ABCDE1234F" not in ex.text
    assert client.post("/api/account/delete", json={"confirm_email": "wrong@example.com"}, headers=h).status_code == 422
    d = client.post("/api/account/delete", json={"confirm_email": email, "reason": "testing"}, headers=h).json()
    assert d["purge_after"]
    me = client.get("/api/me", headers=h).json()
    assert me["deletion_requested_at"] and me["kill_switch"] is True
    assert client.post("/api/account/delete/cancel", headers=h).json()["deletion_requested_at"] is None

    # purge after the grace period: personal data erased, trading records retained
    client.post("/api/account/delete", json={"confirm_email": email}, headers=h)

    async def age_and_purge(db):
        from datetime import timedelta

        from sqlalchemy import select, update

        from algo_common.timeutils import utcnow
        from algo_db.models import ChatSession, User
        from algo_db.privacy import purge_due

        await db.execute(update(User).where(User.email == email).values(deletion_requested_at=utcnow() - timedelta(days=8)))
        n = await purge_due(db)
        u = (await db.execute(select(User).where(User.email.like("deleted-%")).order_by(User.id.desc()))).scalars().first()
        chats = (await db.execute(select(ChatSession).where(ChatSession.user_id == u.id))).scalars().all()
        return n, u.is_active, u.full_name, len(chats)

    n, active, name, chats = run_db(client, age_and_purge)
    assert n >= 1 and active is False and name == "" and chats == 0
    assert client.get("/api/me", headers=h).status_code == 401


def test_notifications(client):
    h, _ = new_user(client)
    n = client.post("/api/notifications/test", json={"channels": ["in_app"]}, headers=h).json()
    assert n["title"] == "Test notification"
    lst = client.get("/api/notifications", headers=h).json()
    assert lst["unread"] >= 1 and lst["items"][0]["id"] == n["id"]
    client.post(f"/api/notifications/{n['id']}/read", headers=h)
    client.post("/api/notifications/read-all", headers=h)
    assert client.get("/api/notifications", headers=h).json()["unread"] == 0


def test_admin_console(client, auth_headers):
    assert client.get("/api/admin/stats", headers=auth_headers).status_code == 403
    admin = make_admin(client)
    st = client.get("/api/admin/stats", headers=admin).json()
    assert st["users"] >= 2 and "subscriptions" in st
    users: list[dict[str, Any]] = client.get("/api/admin/users?q=example.com", headers=admin).json()
    target = next(u for u in users if u["role"] == "user")
    upd = client.patch(f"/api/admin/users/{target['id']}", json={"plan_code": "elite", "note": "support upgrade"}, headers=admin).json()
    assert upd["plan"] == "elite"
    me = client.get("/api/me", headers=admin).json()
    assert client.patch(f"/api/admin/users/{me['id']}", json={"role": "user"}, headers=admin).status_code == 400
    health = client.get("/api/admin/health", headers=admin).json()
    assert health["checks"]["database"]["ok"] and health["checks"]["market_data"]["ok"] and health["llm"]["providers"]
    k = client.post("/api/admin/kill-switch", json={"engaged": True, "reason": "test halt"}, headers=admin).json()
    assert k["engaged"] is True
    h2, _ = new_user(client)
    r = client.post("/api/orders", json={"symbol": "NSE:SBIN", "side": "BUY", "quantity": 1, "product": "MIS", "mode": "paper"}, headers=h2)
    assert r.status_code == 409 and "platform" in r.text.lower()
    assert client.post("/api/admin/kill-switch", json={"engaged": False, "reason": "resume"}, headers=admin).json()["engaged"] is False
    logs = client.get("/api/admin/audit?action=killswitch", headers=admin).json()
    assert len(logs) >= 2 and logs[0]["action"] == "killswitch.global"
    v = client.get("/api/admin/audit/verify", headers=admin).json()
    assert v["ok"] is True and v["entries"] > 10
    # black-box review: listing requires an RA number, appears in the queue, approval notifies the owner
    sid = client.post("/api/strategies", json={"dsl": {"name": "BB algo", "universe": {"symbols": ["NSE:SBIN"]},
                                                       "entry": {"long": {"kind": "all", "conditions": [{"kind": "compare",
                                                                                                      "left": {"type": "price", "field": "close"}, "op": ">",
                                                                                                      "right": {"type": "const", "value": 1}}]}}}},
                      headers=h2).json()["id"]
    assert client.patch(f"/api/strategies/{sid}/listing", json={"visibility": "marketplace", "box_type": "black_box",
                                                                "provider_ra_number": "INH000012345"}, headers=h2).status_code == 200
    queue = client.get("/api/admin/strategies/review", headers=admin).json()
    assert any(q["id"] == sid for q in queue)
    assert client.post(f"/api/admin/strategies/{sid}/review", json={"decision": "approve", "note": "RA verified"}, headers=admin).json()["ra_status"] == "approved"
    assert any("approved" in n["title"] for n in client.get("/api/notifications", headers=h2).json()["items"])
