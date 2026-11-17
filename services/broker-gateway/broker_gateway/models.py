"""Normalised broker-agnostic order / position / funds models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"  # stop-loss limit
    SL_M = "SL-M"  # stop-loss market


class Product(StrEnum):
    MIS = "MIS"
    CNC = "CNC"
    NRML = "NRML"


class OrderStatus(StrEnum):
    PENDING = "pending"  # created locally / in transit
    OPEN = "open"
    TRIGGER_PENDING = "trigger_pending"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in (OrderStatus.COMPLETE, OrderStatus.CANCELLED, OrderStatus.REJECTED)


class _M(BaseModel):
    model_config = ConfigDict(use_enum_values=False, populate_by_name=True)


class OrderRequest(_M):
    symbol: str = Field(description="canonical symbol, e.g. NSE:SBIN or NFO:NIFTY24NOV2626200CE")
    side: Side
    quantity: int = Field(gt=0)
    order_type: OrderType = OrderType.MARKET
    product: Product = Product.MIS
    price: float | None = Field(default=None, ge=0)
    trigger_price: float | None = Field(default=None, ge=0)
    validity: str = "DAY"
    tag: str | None = Field(default=None, max_length=20)
    strategy_id: int | None = None
    deployment_id: int | None = None
    algo_id: str | None = None

    @model_validator(mode="after")
    def _prices(self) -> OrderRequest:
        if self.order_type in (OrderType.LIMIT, OrderType.SL) and not self.price:
            raise ValueError(f"{self.order_type.value} orders need a price")
        if self.order_type in (OrderType.SL, OrderType.SL_M) and not self.trigger_price:
            raise ValueError(f"{self.order_type.value} orders need a trigger_price")
        return self

    @property
    def exchange(self) -> str:
        return self.symbol.split(":", 1)[0] if ":" in self.symbol else "NSE"

    @property
    def tradingsymbol(self) -> str:
        return self.symbol.split(":", 1)[1] if ":" in self.symbol else self.symbol


class ModifyRequest(_M):
    quantity: int | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, ge=0)
    trigger_price: float | None = Field(default=None, ge=0)
    order_type: OrderType | None = None


class OrderAck(_M):
    broker_order_id: str
    status: OrderStatus = OrderStatus.PENDING
    message: str | None = None
    filled_quantity: int = 0
    average_price: float | None = None


class Order(_M):
    broker_order_id: str
    symbol: str
    side: Side
    quantity: int
    filled_quantity: int = 0
    price: float | None = None
    trigger_price: float | None = None
    average_price: float | None = None
    order_type: OrderType = OrderType.MARKET
    product: Product = Product.MIS
    status: OrderStatus = OrderStatus.OPEN
    status_message: str | None = None
    tag: str | None = None
    ts: datetime | None = None


class Trade(_M):
    broker_trade_id: str
    broker_order_id: str
    symbol: str
    side: Side
    quantity: int
    price: float
    product: Product = Product.MIS
    ts: datetime | None = None


class Position(_M):
    symbol: str
    product: Product = Product.MIS
    quantity: int  # net (+ long / - short)
    average_price: float = 0.0
    last_price: float = 0.0
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    broker: str = ""

    @property
    def pnl(self) -> float:
        return self.realised_pnl + self.unrealised_pnl


class Holding(_M):
    symbol: str
    quantity: int
    average_price: float
    last_price: float = 0.0
    pnl: float = 0.0
    isin: str | None = None
    broker: str = ""


class Funds(_M):
    available: float
    used: float = 0.0
    total: float = 0.0
    currency: str = "INR"


class Profile(_M):
    user_id: str
    name: str = ""
    email: str | None = None
    broker: str = ""
    exchanges: list[str] = Field(default_factory=list)


class CredentialField(_M):
    name: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
