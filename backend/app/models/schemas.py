from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class Product(StrEnum):
    INTRADAY = "I"
    DELIVERY = "D"
    MTF = "MTF"
    MIS = "MIS"


class MarketTick(BaseModel):
    instrument_key: str
    timestamp: datetime
    ltp: float
    close: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: int | None = None
    greeks: dict[str, float] = Field(default_factory=dict)
    depth: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class Candle(BaseModel):
    instrument_key: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    open_interest: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class StrategyDefinition(BaseModel):
    id: str = Field(default_factory=lambda: f"strat_{uuid4().hex[:8]}")
    name: str
    version: str = "0.1.0"
    file_path: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class StrategyRun(BaseModel):
    id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:8]}")
    strategy_id: str
    status: Literal["starting", "running", "stopped", "failed"]
    started_at: datetime
    stopped_at: datetime | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class Signal(BaseModel):
    id: str = Field(default_factory=lambda: f"sig_{uuid4().hex[:10]}")
    strategy_id: str
    timestamp: datetime
    instrument_key: str
    symbol: str | None = None
    side: Side
    action: Literal["OPEN", "CLOSE", "REDUCE", "ADD"] = "OPEN"
    order_type: OrderType = OrderType.LIMIT
    product: Product | str = Product.INTRADAY
    quantity: int = Field(gt=0)
    limit_price: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: Literal["created", "approved", "rejected", "routed"] = "created"


class Order(BaseModel):
    id: str = Field(default_factory=lambda: f"ord_{uuid4().hex[:10]}")
    strategy_id: str | None = None
    signal_id: str | None = None
    broker_order_id: str | None = None
    instrument_key: str
    side: Side
    order_type: OrderType
    product: Product | str = Product.INTRADAY
    quantity: int
    price: float = 0
    trigger_price: float = 0
    status: OrderStatus = OrderStatus.CREATED
    idempotency_key: str = Field(default_factory=lambda: uuid4().hex)
    raw_response: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class Fill(BaseModel):
    id: str = Field(default_factory=lambda: f"fill_{uuid4().hex[:10]}")
    order_id: str
    fill_price: float
    fill_quantity: int
    fill_timestamp: datetime
    raw_response: dict[str, Any] = Field(default_factory=dict)


class Position(BaseModel):
    id: str = Field(default_factory=lambda: f"pos_{uuid4().hex[:10]}")
    strategy_id: str | None = None
    instrument_key: str
    quantity: int = 0
    avg_price: float = 0
    ltp: float = 0
    mtm: float = 0
    realized_pnl: float = 0
    unrealized_pnl: float = 0
    updated_at: datetime


class CapitalAccount(BaseModel):
    id: str = Field(default_factory=lambda: f"cap_{uuid4().hex[:8]}")
    user_id: str = "local"
    strategy_id: str | None = None
    starting_capital: float
    current_capital: float
    available_margin: float
    updated_at: datetime


class RmsEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"rms_{uuid4().hex[:10]}")
    strategy_id: str | None = None
    event_type: str
    severity: Literal["info", "warning", "critical"] = "warning"
    message: str
    event: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ReconciliationEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"rec_{uuid4().hex[:10]}")
    strategy_id: str | None = None
    signal_id: str | None = None
    order_id: str | None = None
    fill_id: str | None = None
    status: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DashboardSummary(BaseModel):
    mode: str
    capital: CapitalAccount
    positions: list[Position]
    open_orders: list[Order]
    signals: list[Signal]
    rms_events: list[RmsEvent]
    reconciliation_events: list[ReconciliationEvent]
    pnl: dict[str, float]

