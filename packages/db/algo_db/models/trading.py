"""Broker connections, orders, trades, positions and risk limits."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from algo_db.base import Base, BigIntId, IdMixin, TimestampMixin, utcnow


class BrokerConnection(IdMixin, TimestampMixin, Base):
    __tablename__ = "broker_connections"
    __table_args__ = (UniqueConstraint("user_id", "broker", "client_id", name="uq_broker_conn_user_broker_client"),)

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    broker: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(64), default="")
    client_id: Mapped[str] = mapped_column(String(64), default="")
    # AES-GCM ciphertexts (see algo_common.crypto.Vault). Never logged, never returned by the API.
    credentials_enc: Mapped[str | None] = mapped_column(Text)
    session_enc: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="disconnected")
    status_message: Mapped[str | None] = mapped_column(String(500))
    token_expires_at: Mapped[datetime | None] = mapped_column()
    last_synced_at: Mapped[datetime | None] = mapped_column()
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Order(IdMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_user_created", "user_id", "created_at"),)

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"))
    deployment_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("deployments.id"), index=True)
    strategy_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("strategies.id"), index=True)
    broker: Mapped[str] = mapped_column(String(32), default="paper")
    broker_connection_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("broker_connections.id"))
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    client_order_id: Mapped[str] = mapped_column(String(40), unique=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    parent_order_id: Mapped[int | None] = mapped_column(BigIntId)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    exchange: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(Integer)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float | None] = mapped_column(Float)
    trigger_price: Mapped[float | None] = mapped_column(Float)
    average_price: Mapped[float | None] = mapped_column(Float)
    order_type: Mapped[str] = mapped_column(String(8), default="MARKET")
    product: Mapped[str] = mapped_column(String(8), default="MIS")
    validity: Mapped[str] = mapped_column(String(8), default="DAY")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    status_message: Mapped[str | None] = mapped_column(String(500))
    algo_id: Mapped[str] = mapped_column(String(64))
    tag: Mapped[str | None] = mapped_column(String(64))
    risk_decision: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Trade(IdMixin, Base):
    __tablename__ = "trades"

    order_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    deployment_id: Mapped[int | None] = mapped_column(BigIntId, index=True)
    strategy_id: Mapped[int | None] = mapped_column(BigIntId)
    broker: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    broker_trade_id: Mapped[str | None] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    exchange: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    charges: Mapped[float] = mapped_column(Float, default=0.0)
    product: Mapped[str] = mapped_column(String(8), default="MIS")
    ts: Mapped[datetime] = mapped_column(default=utcnow)


class PositionSnapshot(IdMixin, Base):
    __tablename__ = "positions_snapshots"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    broker: Mapped[str] = mapped_column(String(32))
    broker_connection_id: Mapped[int | None] = mapped_column(BigIntId)
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    positions: Mapped[list[Any]] = mapped_column(default=list)
    holdings: Mapped[list[Any]] = mapped_column(default=list)
    pnl_realised: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_unrealised: Mapped[float] = mapped_column(Float, default=0.0)
    taken_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class RiskLimit(IdMixin, TimestampMixin, Base):
    """Per-user (strategy_id NULL) or per-strategy risk limits."""

    __tablename__ = "risk_limits"
    __table_args__ = (UniqueConstraint("user_id", "strategy_id", name="uq_risk_limits_user_strategy"),)

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    strategy_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("strategies.id", ondelete="CASCADE"))
    max_loss_per_day: Mapped[float] = mapped_column(Float, default=25_000.0)
    max_orders_per_min: Mapped[int] = mapped_column(Integer, default=60)
    max_position_value: Mapped[float] = mapped_column(Float, default=1_000_000.0)
    max_lots: Mapped[int] = mapped_column(Integer, default=10)
    max_qty_per_order: Mapped[int] = mapped_column(Integer, default=5_000)
    allowed_instruments: Mapped[list[Any]] = mapped_column(default=list)  # glob patterns; empty = all
    allowed_exchanges: Mapped[list[Any]] = mapped_column(default=lambda: ["NSE", "BSE", "NFO", "BFO", "MCX"])
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
