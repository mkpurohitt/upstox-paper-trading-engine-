"""Instruments, time-series (Timescale hypertables), news, watchlists, screens, alerts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from algo_db.base import Base, BigIntId, IdMixin, TimestampMixin, utcnow


class InstrumentRow(IdMixin, Base):
    __tablename__ = "instruments"
    __table_args__ = (Index("ix_instruments_underlying_expiry", "underlying", "expiry"),)

    symbol: Mapped[str] = mapped_column(String(64), unique=True)
    instrument_key: Mapped[str] = mapped_column(String(80), index=True)
    exchange: Mapped[str] = mapped_column(String(16), index=True)
    segment: Mapped[str] = mapped_column(String(16), default="")
    tradingsymbol: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    instrument_type: Mapped[str] = mapped_column(String(8))
    underlying: Mapped[str | None] = mapped_column(String(64))
    expiry: Mapped[date | None] = mapped_column(Date)
    strike: Mapped[float | None] = mapped_column(Float)
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[float] = mapped_column(Float, default=0.05)
    freeze_qty: Mapped[int | None] = mapped_column(Integer)
    isin: Mapped[str | None] = mapped_column(String(16))
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(64))
    market_cap_cr: Mapped[float | None] = mapped_column(Float)
    broker_tokens: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class CandleRow(Base):
    """1m base candles + daily history. TimescaleDB hypertable on `ts` with
    continuous aggregates candles_5m / 15m / 1h / 1d (see migration 0002)."""

    __tablename__ = "candles"

    symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    interval: Mapped[str] = mapped_column(String(4), primary_key=True)
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    oi: Mapped[float | None] = mapped_column(Float)


class OptionChainSnapshot(Base):
    __tablename__ = "option_chain_snapshots"

    underlying: Mapped[str] = mapped_column(String(64), primary_key=True)
    expiry: Mapped[date] = mapped_column(Date, primary_key=True)
    strike: Mapped[float] = mapped_column(Float, primary_key=True)
    option_type: Mapped[str] = mapped_column(String(2), primary_key=True)
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    spot: Mapped[float] = mapped_column(Float)
    ltp: Mapped[float] = mapped_column(Float)
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    iv: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float)
    gamma: Mapped[float | None] = mapped_column(Float)
    theta: Mapped[float | None] = mapped_column(Float)
    vega: Mapped[float | None] = mapped_column(Float)
    oi: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)


class NewsItem(IdMixin, Base):
    __tablename__ = "news_items"

    source: Mapped[str] = mapped_column(String(80))
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    ai_summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(24), default="news")  # news | announcement | results | economy
    published_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    sentiment: Mapped[str] = mapped_column(String(10), default="neutral")
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    tickers: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Watchlist(IdMixin, TimestampMixin, Base):
    __tablename__ = "watchlists"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    symbols: Mapped[list[Any]] = mapped_column(default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ChartLayout(IdMixin, TimestampMixin, Base):
    """A saved chart workspace: grid layout, per-cell symbol/timeframe/style/indicators and drawings per symbol."""

    __tablename__ = "chart_layouts"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Screen(IdMixin, TimestampMixin, Base):
    __tablename__ = "screens"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    universe: Mapped[str] = mapped_column(String(32), default="NIFTY100")
    criteria: Mapped[dict[str, Any]] = mapped_column(default=dict)
    alert_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_run_at: Mapped[datetime | None] = mapped_column()
    last_results: Mapped[list[Any]] = mapped_column(default=list)


class Alert(IdMixin, TimestampMixin, Base):
    __tablename__ = "alerts"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="price")  # price | screen | strategy | news
    symbol: Mapped[str | None] = mapped_column(String(64))
    condition: Mapped[dict[str, Any]] = mapped_column(default=dict)
    channels: Mapped[list[Any]] = mapped_column(default=lambda: ["in_app"])
    status: Mapped[str] = mapped_column(String(16), default="active")
    message: Mapped[str] = mapped_column(String(500), default="")
    triggered_at: Mapped[datetime | None] = mapped_column()


class Notification(IdMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="system")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    channels_sent: Mapped[list[Any]] = mapped_column(default=list)
    read_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
