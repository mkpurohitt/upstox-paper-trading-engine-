from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORM
from broker_gateway.models import OrderType, Product, Side

Mode = Literal["paper", "live"]


class CredentialFieldOut(BaseModel):
    name: str
    label: str
    secret: bool
    required: bool
    help: str = ""


class BrokerCatalogItem(BaseModel):
    name: str
    display_name: str
    auth_type: str
    docs_url: str
    rate_limit_per_sec: float
    credential_fields: list[CredentialFieldOut]


class ConnectionIn(BaseModel):
    broker: str
    label: str = Field(default="", max_length=64)
    credentials: dict[str, str]


class ConnectionOut(BaseModel):
    id: int
    broker: str
    display_name: str
    auth_type: str
    label: str
    client_id: str
    status: str
    status_message: str | None = None
    token_expires_at: datetime | None = None
    last_synced_at: datetime | None = None
    is_default: bool
    created_at: datetime


class LoginIn(BaseModel):
    totp: str | None = Field(default=None, max_length=10)


class OrderIn(BaseModel):
    symbol: str
    side: Side
    quantity: int = Field(gt=0, le=1_000_000)
    order_type: OrderType = OrderType.MARKET
    product: Product = Product.MIS
    price: float | None = Field(default=None, ge=0)
    trigger_price: float | None = Field(default=None, ge=0)
    mode: Mode = "paper"
    connection_id: int | None = None
    totp_code: str | None = Field(default=None, description="required for live orders (2FA step-up)")


class ModifyIn(BaseModel):
    quantity: int | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, ge=0)
    trigger_price: float | None = Field(default=None, ge=0)
    order_type: OrderType | None = None


class OrderOut(ORM):
    id: int
    client_order_id: str
    broker_order_id: str | None
    symbol: str
    exchange: str
    side: str
    quantity: int
    filled_quantity: int
    price: float | None
    trigger_price: float | None
    average_price: float | None
    order_type: str
    product: str
    status: str
    status_message: str | None
    mode: str
    broker: str
    algo_id: str
    strategy_id: int | None
    deployment_id: int | None
    tag: str | None
    risk_decision: dict[str, Any]
    created_at: datetime


class TradeOut(ORM):
    id: int
    order_id: int
    symbol: str
    side: str
    quantity: int
    price: float
    charges: float
    product: str
    mode: str
    broker: str
    deployment_id: int | None
    ts: datetime


class PositionOut(BaseModel):
    symbol: str
    product: str
    quantity: int
    average_price: float
    last_price: float
    realised_pnl: float
    unrealised_pnl: float
    broker: str


class FundsOut(BaseModel):
    available: float
    used: float
    total: float
    currency: str = "INR"
    mode: str = "paper"


class KillSwitchIn(BaseModel):
    engaged: bool
    square_off: bool = True


class KillSwitchOut(BaseModel):
    user_engaged: bool
    global_engaged: bool
    summary: dict[str, Any] = {}


class RiskLimitsIn(BaseModel):
    max_loss_per_day: float | None = Field(default=None, gt=0)
    max_orders_per_min: int | None = Field(default=None, gt=0, le=600)
    max_position_value: float | None = Field(default=None, gt=0)
    max_lots: int | None = Field(default=None, gt=0, le=1000)
    max_qty_per_order: int | None = Field(default=None, gt=0)
    allowed_instruments: list[str] | None = None
    allowed_exchanges: list[str] | None = None
    kill_switch: bool | None = None


class RiskLimitsOut(ORM):
    strategy_id: int | None
    max_loss_per_day: float
    max_orders_per_min: int
    max_position_value: float
    max_lots: int
    max_qty_per_order: int
    allowed_instruments: list[str]
    allowed_exchanges: list[str]
    kill_switch: bool
    sebi_order_rate_limit_per_sec: int = 0
    static_egress_ip: str | None = None


class RiskCheckOut(BaseModel):
    allowed: bool
    rule: str | None
    reason: str | None
    reducing: bool
    checks: list[dict[str, Any]]


class DeploymentIn(BaseModel):
    strategy_id: int
    mode: Literal["paper", "live", "notify"] = "paper"
    connection_id: int | None = None
    multiplier: int = Field(default=1, ge=1, le=50)
    capital: float = Field(default=1_000_000, gt=0)
    risk_limits: RiskLimitsIn = Field(default_factory=RiskLimitsIn)
    notify_channels: list[Literal["in_app", "email", "telegram", "whatsapp"]] = Field(default_factory=lambda: ["in_app"])
    totp_code: str | None = None
    acknowledge_risk: bool = Field(description="user confirmed the risk disclosure in the confirmation modal")


class DeploymentOut(ORM):
    id: int
    strategy_id: int
    strategy_version: int
    broker: str
    broker_connection_id: int | None
    mode: str
    status: str
    multiplier: int
    risk_limits: dict[str, Any]
    notify_channels: list[str]
    algo_id: str
    pnl_realised: float
    pnl_unrealised: float
    error: str | None
    started_at: datetime | None
    stopped_at: datetime | None
    last_heartbeat: datetime | None
    created_at: datetime
    name: str = ""
    kind: str = ""
    symbols: list[str] = []
    state: dict[str, Any] = {}


class DeploymentLogOut(ORM):
    id: int
    ts: datetime
    level: str
    message: str
    data: dict[str, Any]


class AuditOut(ORM):
    id: int
    ts: datetime
    actor: str
    action: str
    entity_type: str | None
    entity_id: str | None
    payload: dict[str, Any]
    hash: str
