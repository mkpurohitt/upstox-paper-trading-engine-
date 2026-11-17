"""Subscriptions & payments (Razorpay test/live mode, with a dev-only simulator when no keys are configured)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from algo_common.logging import get_logger
from algo_common.settings import get_settings
from algo_common.timeutils import utcnow
from algo_db.audit import audit
from algo_db.models import Payment, Plan, Subscription
from app.core.deps import DB, CurrentUser, client_ip
from app.schemas.common import Message
from app.services.quotas import plan_limits, usage
from app.services.users import active_subscription, get_plan

router = APIRouter(prefix="/api/billing", tags=["billing"])
log = get_logger("api.billing")
RZP = "https://api.razorpay.com/v1"


class PlanOut(BaseModel):
    code: str
    name: str
    price_paise: int
    interval: str
    limits: dict[str, Any]
    features: list[Any]


def _mode() -> Literal["test", "live", "simulated"]:
    s = get_settings()
    if not s.razorpay_configured:
        return "simulated"
    return "test" if (s.razorpay_key_id or "").startswith("rzp_test_") else "live"


@router.get("/plans", response_model=list[PlanOut])
async def plans(db: DB) -> list[PlanOut]:
    rows = (await db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))).scalars().all()
    return [PlanOut(code=p.code, name=p.name, price_paise=p.price_paise, interval=p.interval, limits=p.limits, features=p.features) for p in rows]


class PaymentOut(BaseModel):
    id: int
    plan: str | None
    amount_paise: int
    status: str
    method: str | None
    razorpay_order_id: str | None
    razorpay_payment_id: str | None
    created_at: datetime
    paid_at: datetime | None


@router.get("/subscription")
async def subscription(user: CurrentUser, db: DB) -> dict[str, Any]:
    sub = await active_subscription(db, user.id)
    plan = sub.plan if sub else await get_plan(db, "free")
    pays = (await db.execute(select(Payment).where(Payment.user_id == user.id).order_by(Payment.id.desc()).limit(24))).scalars().all()
    codes = {p.id: p.code for p in (await db.execute(select(Plan))).scalars()}
    s = get_settings()
    return {
        "plan": PlanOut(code=plan.code, name=plan.name, price_paise=plan.price_paise, interval=plan.interval, limits=plan.limits,
                        features=plan.features).model_dump(),
        "status": sub.status if sub else "active",
        "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
        "cancel_at_period_end": bool(sub and sub.cancel_at_period_end),
        "limits": await plan_limits(db, user.id), "usage": await usage(db, user.id),
        "payments": [PaymentOut(id=p.id, plan=codes.get(p.plan_id or -1), amount_paise=p.amount_paise, status=p.status, method=p.method,
                                razorpay_order_id=p.razorpay_order_id, razorpay_payment_id=p.razorpay_payment_id, created_at=p.created_at,
                                paid_at=p.paid_at).model_dump(mode="json") for p in pays],
        "razorpay": {"mode": _mode(), "key_id": s.razorpay_key_id if s.razorpay_configured else None},
    }


class CheckoutIn(BaseModel):
    plan_code: str = Field(min_length=2, max_length=32)


async def _activate(db: Any, user_id: int, plan: Plan, payment: Payment | None, actor: str = "user") -> Subscription:
    now = utcnow()
    for old in (await db.execute(select(Subscription).where(Subscription.user_id == user_id,
                                                            Subscription.status.in_(("active", "trialing"))))).scalars():
        old.status = "replaced"
    days = 365 if plan.interval == "year" else 30
    sub = Subscription(user_id=user_id, plan_id=plan.id, status="active", current_period_start=now,
                       current_period_end=None if plan.price_paise == 0 else now + timedelta(days=days))
    db.add(sub)
    await db.flush()
    if payment is not None:
        payment.subscription_id = sub.id
    await audit(db, "billing.subscription_activated", user_id=user_id, actor=actor, entity_type="subscription", entity_id=sub.id,
                payload={"plan": plan.code, "payment_id": payment.id if payment else None})
    return sub


@router.post("/checkout")
async def checkout(body: CheckoutIn, user: CurrentUser, db: DB, request: Request) -> dict[str, Any]:
    plan = (await db.execute(select(Plan).where(Plan.code == body.plan_code, Plan.is_active.is_(True)))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(404, "Plan not found")
    current = await active_subscription(db, user.id)
    if current and current.plan_id == plan.id and not current.cancel_at_period_end:
        raise HTTPException(409, "You are already on this plan")
    if plan.price_paise == 0:  # downgrade: keep paid features until the period ends
        if current and current.plan.price_paise > 0:
            current.cancel_at_period_end = True
            await audit(db, "billing.downgrade_scheduled", user_id=user.id, payload={"to": plan.code})
            return {"mode": "downgrade", "effective": current.current_period_end.isoformat() if current.current_period_end else None}
        await _activate(db, user.id, plan, None)
        return {"mode": "activated"}
    receipt = f"u{user.id}-{plan.code}-{secrets.token_hex(4)}"
    mode = _mode()
    if mode == "simulated":
        if get_settings().environment == "production":
            raise HTTPException(503, "Payments are not configured")
        order_id = f"order_sim_{secrets.token_hex(8)}"
    else:
        s = get_settings()
        try:
            async with httpx.AsyncClient(timeout=15.0, auth=(s.razorpay_key_id or "", s.razorpay_key_secret.get_secret_value())) as c:  # type: ignore[union-attr]
                r = await c.post(f"{RZP}/orders", json={"amount": plan.price_paise, "currency": "INR", "receipt": receipt,
                                                        "notes": {"user_id": str(user.id), "plan": plan.code}})
                r.raise_for_status()
                order_id = r.json()["id"]
        except httpx.HTTPError as exc:
            log.warning("billing.order_failed", error=str(exc))
            raise HTTPException(502, "Could not create the payment order; please try again") from exc
    pay = Payment(user_id=user.id, plan_id=plan.id, amount_paise=plan.price_paise, status="created", razorpay_order_id=order_id,
                  raw={"receipt": receipt, "mode": mode})
    db.add(pay)
    await db.flush()
    await audit(db, "billing.checkout", user_id=user.id, ip=client_ip(request), entity_type="payment", entity_id=pay.id,
                payload={"plan": plan.code, "mode": mode})
    return {"mode": mode, "order_id": order_id, "amount": plan.price_paise, "currency": "INR", "key_id": get_settings().razorpay_key_id,
            "name": "AlgoDesk", "description": f"{plan.name} plan · monthly", "prefill": {"name": user.full_name, "email": user.email}}


class VerifyIn(BaseModel):
    razorpay_order_id: str = Field(max_length=64)
    razorpay_payment_id: str = Field(max_length=64)
    razorpay_signature: str = Field(max_length=128)


async def _mark_paid(db: Any, pay: Payment, payment_id: str, signature: str | None, method: str | None, actor: str) -> Subscription | None:
    if pay.status == "paid":
        return None  # idempotent (checkout handler and webhook may both fire)
    pay.status, pay.razorpay_payment_id, pay.razorpay_signature, pay.method, pay.paid_at = "paid", payment_id, signature, method, utcnow()
    plan = await db.get(Plan, pay.plan_id)
    return await _activate(db, pay.user_id, plan, pay, actor=actor)


@router.post("/verify", response_model=Message)
async def verify(body: VerifyIn, user: CurrentUser, db: DB) -> Message:
    if _mode() == "simulated":
        raise HTTPException(400, "Payments are in simulated mode")
    pay = (await db.execute(select(Payment).where(Payment.razorpay_order_id == body.razorpay_order_id))).scalar_one_or_none()
    if pay is None or pay.user_id != user.id:
        raise HTTPException(404, "Order not found")
    secret = get_settings().razorpay_key_secret.get_secret_value()  # type: ignore[union-attr]
    expected = hmac.new(secret.encode(), f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, body.razorpay_signature):
        pay.status = "failed"
        await audit(db, "billing.signature_invalid", user_id=user.id, entity_type="payment", entity_id=pay.id)
        await db.commit()  # keep the failure + audit entry even though the request errors
        raise HTTPException(400, "Payment signature verification failed")
    await _mark_paid(db, pay, body.razorpay_payment_id, body.razorpay_signature, None, "user")
    return Message(message="Payment verified — plan activated")


class SimulateIn(BaseModel):
    order_id: str = Field(max_length=64)
    outcome: Literal["success", "failure"] = "success"


@router.post("/simulate", response_model=Message, summary="Dev/test only: complete a simulated checkout (no Razorpay keys)")
async def simulate(body: SimulateIn, user: CurrentUser, db: DB) -> Message:
    if _mode() != "simulated" or get_settings().environment == "production":
        raise HTTPException(403, "Simulation is only available without Razorpay keys outside production")
    pay = (await db.execute(select(Payment).where(Payment.razorpay_order_id == body.order_id))).scalar_one_or_none()
    if pay is None or pay.user_id != user.id:
        raise HTTPException(404, "Order not found")
    if body.outcome == "failure":
        pay.status = "failed"
        return Message(message="Simulated payment failed")
    await _mark_paid(db, pay, f"pay_sim_{secrets.token_hex(6)}", None, "simulated", "user")
    return Message(message="Simulated payment succeeded — plan activated")


@router.post("/cancel", response_model=Message)
async def cancel(user: CurrentUser, db: DB) -> Message:
    sub = await active_subscription(db, user.id)
    if sub is None or sub.plan.price_paise == 0:
        raise HTTPException(400, "No paid subscription to cancel")
    sub.cancel_at_period_end = True
    await audit(db, "billing.cancel", user_id=user.id, entity_type="subscription", entity_id=sub.id)
    return Message(message="Subscription will end at the close of the current period")


@router.post("/resume", response_model=Message)
async def resume(user: CurrentUser, db: DB) -> Message:
    sub = await active_subscription(db, user.id)
    if sub is None or not sub.cancel_at_period_end:
        raise HTTPException(400, "Nothing to resume")
    sub.cancel_at_period_end = False
    await audit(db, "billing.resume", user_id=user.id, entity_type="subscription", entity_id=sub.id)
    return Message(message="Subscription will renew")


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: DB) -> dict[str, str]:
    """Razorpay webhook (payment.captured / order.paid / payment.failed). Verified with RAZORPAY_WEBHOOK_SECRET."""
    s = get_settings()
    raw = await request.body()
    if not s.razorpay_webhook_secret:
        raise HTTPException(503, "Webhook secret not configured")
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(s.razorpay_webhook_secret.get_secret_value().encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(400, "Invalid signature")
    event = json.loads(raw or b"{}")
    kind = event.get("event", "")
    entity = (event.get("payload", {}).get("payment", {}) or {}).get("entity", {}) or {}
    order_id = entity.get("order_id") or (event.get("payload", {}).get("order", {}) or {}).get("entity", {}).get("id")
    pay = (await db.execute(select(Payment).where(Payment.razorpay_order_id == order_id))).scalar_one_or_none() if order_id else None
    if pay is None:
        return {"status": "ignored"}
    pay.raw = {**(pay.raw or {}), "last_event": kind}
    if kind in ("payment.captured", "order.paid"):
        await _mark_paid(db, pay, entity.get("id") or pay.razorpay_payment_id or "", None, entity.get("method"), "webhook")
    elif kind == "payment.failed" and pay.status != "paid":
        pay.status = "failed"
    await audit(db, "billing.webhook", actor="system", entity_type="payment", entity_id=pay.id, payload={"event": kind})
    return {"status": "ok"}

