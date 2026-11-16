from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from algo_db.base import Base, BigIntId, IdMixin, TimestampMixin, utcnow


class Plan(IdMixin, Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    price_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    interval: Mapped[str] = mapped_column(String(16), default="month")
    limits: Mapped[dict[str, Any]] = mapped_column(default=dict)
    features: Mapped[list[Any]] = mapped_column(default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Subscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(16), default="active")
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64))

    plan: Mapped[Plan] = relationship(lazy="joined")


class Payment(IdMixin, Base):
    __tablename__ = "payments"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("plans.id"))
    subscription_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("subscriptions.id"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    status: Mapped[str] = mapped_column(String(16), default="created")
    provider: Mapped[str] = mapped_column(String(16), default="razorpay")
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64))
    razorpay_signature: Mapped[str | None] = mapped_column(String(128))
    method: Mapped[str | None] = mapped_column(String(32))
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
