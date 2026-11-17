"""Helpers shared by adapters."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from algo_common.timeutils import IST, now_ist
from broker_gateway.models import OrderStatus, OrderType, Product, Side


def day_end_expiry() -> datetime:
    """Most Indian broker tokens expire around 03:30-06:00 IST next day."""
    nxt = (now_ist() + timedelta(days=1)).date()
    return datetime.combine(nxt, time(3, 30), tzinfo=IST).astimezone(UTC)


def status_from(text: Any, mapping: dict[str, OrderStatus] | None = None) -> OrderStatus:
    s = str(text or "").strip().lower().replace("_", " ")
    if mapping and s in mapping:
        return mapping[s]
    if s in ("complete", "completed", "traded", "filled", "executed", "fully executed"):
        return OrderStatus.COMPLETE
    if s in ("rejected", "reject", "failed", "expired"):
        return OrderStatus.REJECTED
    if s in ("cancelled", "canceled", "cancel"):
        return OrderStatus.CANCELLED
    if "trigger" in s:
        return OrderStatus.TRIGGER_PENDING
    if s in ("transit", "put order req received", "validation pending", "pending", "modify pending", "open pending"):
        return OrderStatus.PENDING
    return OrderStatus.OPEN


def side_from(v: Any) -> Side:
    s = str(v).upper()
    return Side.BUY if s in ("BUY", "B", "1") else Side.SELL


def product_from(v: Any) -> Product:
    s = str(v).upper()
    if s in ("CNC", "D", "DELIVERY", "C", "LONGTERM"):
        return Product.CNC
    if s in ("NRML", "MARGIN", "CARRYFORWARD", "M"):
        return Product.NRML
    return Product.MIS


def order_type_from(v: Any) -> OrderType:
    s = str(v).upper().replace("_", "-")
    if s in ("LIMIT", "L", "LMT", "1"):
        return OrderType.LIMIT
    if s in ("SL", "STOPLOSS-LIMIT", "STOP-LOSS", "SL-LMT", "4", "STOPLOSS"):
        return OrderType.SL
    if s in ("SL-M", "SLM", "STOPLOSS-MARKET", "STOP-LOSS-MARKET", "SL-MKT", "3"):
        return OrderType.SL_M
    return OrderType.MARKET


def parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%H:%M:%S %d-%m-%Y", "%d/%m/%Y %H:%M:%S"):
        try:
            dt = datetime.fromisoformat(str(v)) if fmt is None else datetime.strptime(str(v), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=IST)
        except ValueError:
            continue
    return None
