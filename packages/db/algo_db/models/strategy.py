"""Strategies, versions, backtests, deployments."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from algo_db.base import Base, BigIntId, IdMixin, TimestampMixin, utcnow


class Strategy(IdMixin, TimestampMixin, Base):
    __tablename__ = "strategies"

    user_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    dsl: Mapped[dict[str, Any]] = mapped_column()
    dsl_version: Mapped[str] = mapped_column(String(8), default="1.0")
    version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(16), default="equity")  # equity | options | pair
    source: Mapped[str] = mapped_column(String(16), default="form")  # form | visual | code | ai | template
    code: Mapped[str | None] = mapped_column(Text)
    graph: Mapped[dict[str, Any] | None] = mapped_column()
    visibility: Mapped[str] = mapped_column(String(16), default="private")  # private | template | marketplace
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    box_type: Mapped[str] = mapped_column(String(16), default="white_box")  # white_box | black_box
    provider_ra_number: Mapped[str | None] = mapped_column(String(32))
    ra_status: Mapped[str] = mapped_column(String(16), default="none")  # none | pending | approved | rejected
    tags: Mapped[list[Any]] = mapped_column(default=list)


class StrategyVersion(IdMixin, Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version", name="uq_strategy_versions_sv"),)

    strategy_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("strategies.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    dsl: Mapped[dict[str, Any]] = mapped_column()
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Backtest(IdMixin, Base):
    __tablename__ = "backtests"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    strategy_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("strategies.id", ondelete="SET NULL"))
    strategy_version: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="backtest")  # backtest | optimise | walk_forward | monte_carlo
    dsl: Mapped[dict[str, Any]] = mapped_column()
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    equity_curve: Mapped[list[Any]] = mapped_column(default=list)
    drawdown_curve: Mapped[list[Any]] = mapped_column(default=list)
    monthly_returns: Mapped[list[Any]] = mapped_column(default=list)
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BacktestTrade(IdMixin, Base):
    __tablename__ = "backtest_trades"

    backtest_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("backtests.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(64))
    leg: Mapped[str | None] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(5))
    quantity: Mapped[int] = mapped_column(Integer)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[float] = mapped_column(Float)
    exit_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float | None] = mapped_column(Float)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    charges: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    exit_reason: Mapped[str | None] = mapped_column(String(32))
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Deployment(IdMixin, TimestampMixin, Base):
    __tablename__ = "deployments"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    strategy_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("strategies.id", ondelete="CASCADE"))
    strategy_version: Mapped[int] = mapped_column(Integer, default=1)
    dsl: Mapped[dict[str, Any]] = mapped_column()
    broker: Mapped[str] = mapped_column(String(32), default="paper")
    broker_connection_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("broker_connections.id"))
    mode: Mapped[str] = mapped_column(String(8), default="paper")  # paper | live | notify
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    multiplier: Mapped[int] = mapped_column(Integer, default=1)
    risk_limits: Mapped[dict[str, Any]] = mapped_column(default=dict)
    notify_channels: Mapped[list[Any]] = mapped_column(default=list)
    algo_id: Mapped[str] = mapped_column(String(64))
    pnl_realised: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_unrealised: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_2fa_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeploymentLog(IdMixin, Base):
    __tablename__ = "deployment_logs"

    deployment_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("deployments.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(8), default="info")
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
