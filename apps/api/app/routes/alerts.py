"""Price alerts (set from the Charts terminal): fire once when the last price reaches a level."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from algo_common.timeutils import utcnow
from algo_db.models import Alert
from app.core.deps import DB, CurrentUser
from market_data.registry import get_provider

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
MAX_ACTIVE = 200


class AlertIn(BaseModel):
    symbol: str = Field(min_length=3, max_length=64)
    value: float = Field(gt=0)
    op: Literal["above", "below"] | None = Field(None, description="Omit to infer from the current price")
    message: str = Field("", max_length=300)
    channels: list[Literal["in_app", "email", "telegram", "whatsapp"]] = Field(default_factory=lambda: ["in_app"])


class AlertPatch(BaseModel):
    value: float | None = Field(None, gt=0)
    op: Literal["above", "below"] | None = None
    message: str | None = Field(None, max_length=300)
    status: Literal["active", "paused"] | None = None


def _out(a: Alert) -> dict[str, Any]:
    c = a.condition or {}
    return {"id": a.id, "symbol": a.symbol, "op": c.get("op"), "value": c.get("value"), "message": a.message,
            "status": a.status, "channels": a.channels, "created_at": a.created_at.isoformat() if a.created_at else None,
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None}


async def _owned(db: DB, user_id: int, alert_id: int) -> Alert:
    a = await db.get(Alert, alert_id)
    if a is None or a.user_id != user_id or a.kind != "price":
        raise HTTPException(404, "Alert not found")
    return a


async def _ltp(symbol: str) -> float | None:
    try:
        q = (await get_provider().quotes([symbol])).get(symbol)
    except Exception:
        return None
    return q.ltp if q else None


@router.get("")
async def list_alerts(user: CurrentUser, db: DB, symbol: str | None = Query(None)) -> list[dict[str, Any]]:
    q = select(Alert).where(Alert.user_id == user.id, Alert.kind == "price")
    if symbol:
        q = q.where(Alert.symbol == symbol)
    return [_out(a) for a in (await db.execute(q.order_by(Alert.id.desc()).limit(500))).scalars()]


@router.post("", status_code=201)
async def create_alert(body: AlertIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    active = (await db.execute(select(func.count()).select_from(Alert).where(
        Alert.user_id == user.id, Alert.kind == "price", Alert.status == "active"))).scalar_one()
    if active >= MAX_ACTIVE:
        raise HTTPException(409, f"You can have up to {MAX_ACTIVE} active price alerts")
    ltp = await _ltp(body.symbol)
    if ltp is None:
        raise HTTPException(404, f"No price for {body.symbol}")
    op = body.op or ("above" if body.value >= ltp else "below")
    if (op == "above" and ltp >= body.value) or (op == "below" and ltp <= body.value):
        raise HTTPException(422, f"The price is already {'above' if op == 'above' else 'below'} {body.value:,.2f} "
                                 f"(last {ltp:,.2f}); choose a level the price has not reached yet")
    a = Alert(user_id=user.id, kind="price", symbol=body.symbol, condition={"op": op, "value": body.value, "ltp_at_create": ltp},
              channels=list(dict.fromkeys(["in_app", *body.channels])), status="active", message=body.message)
    db.add(a)
    await db.commit()
    return _out(a)


@router.patch("/{alert_id}")
async def update_alert(alert_id: int, body: AlertPatch, user: CurrentUser, db: DB) -> dict[str, Any]:
    a = await _owned(db, user.id, alert_id)
    cond = dict(a.condition or {})
    if body.value is not None or body.op is not None:
        ltp = await _ltp(a.symbol or "")
        value = body.value if body.value is not None else float(cond.get("value", 0))
        op = body.op or (("above" if value >= ltp else "below") if ltp else cond.get("op", "above"))
        cond.update(value=value, op=op)
        a.condition = cond
    if body.message is not None:
        a.message = body.message
    if body.status is not None:
        a.status = body.status
        if body.status == "active":
            a.triggered_at = None
    a.updated_at = utcnow()
    await db.commit()
    return _out(a)


@router.delete("/{alert_id}")
async def delete_alert(alert_id: int, user: CurrentUser, db: DB) -> dict[str, str]:
    await db.delete(await _owned(db, user.id, alert_id))
    await db.commit()
    return {"message": "deleted"}
