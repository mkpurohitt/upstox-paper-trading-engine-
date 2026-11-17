from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORM
from strategy_engine.dsl import StrategyDSL


class StrategyIn(BaseModel):
    dsl: StrategyDSL
    source: Literal["form", "visual", "code", "ai", "template"] = "form"
    code: str | None = Field(default=None, max_length=20_000)
    graph: dict[str, Any] | None = None
    note: str = Field(default="", max_length=200)


class StrategyOut(ORM):
    id: int
    user_id: int | None
    name: str
    description: str
    dsl: StrategyDSL
    version: int
    kind: str
    source: str
    code: str | None = None
    graph: dict[str, Any] | None = None
    visibility: str
    is_template: bool
    box_type: str
    provider_ra_number: str | None = None
    ra_status: str
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime
    last_backtest: dict[str, Any] | None = None


class StrategyVersionOut(ORM):
    id: int
    version: int
    note: str
    created_at: datetime
    dsl: dict[str, Any]


class ListingIn(BaseModel):
    visibility: Literal["private", "marketplace"]
    box_type: Literal["white_box", "black_box"] = "white_box"
    provider_ra_number: str | None = Field(default=None, pattern=r"^INH\d{9}$", description="SEBI Research Analyst reg. no.")


class ValidateOut(BaseModel):
    valid: bool
    errors: list[dict[str, Any]]
    dsl: StrategyDSL | None = None


class CompileCodeIn(BaseModel):
    code: str = Field(max_length=20_000)


class CompileCodeOut(BaseModel):
    ok: bool
    dsl: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = []
    stdout: str = ""


class IndicatorParam(BaseModel):
    name: str
    default: float
    min: float
    max: float


class IndicatorCatalogItem(BaseModel):
    kind: str
    description: str
    outputs: list[str]
    overlay: bool
    default_source: str
    params: list[IndicatorParam]


class BacktestParamsIn(BaseModel):
    start: datetime
    end: datetime
    initial_capital: float = Field(default=1_000_000, gt=1000, le=1e10)
    broker: str = "zerodha"
    slippage_bps: float = Field(default=5, ge=0, le=200)
    fill: Literal["next_open", "close"] = "next_open"
    mode: Literal["event", "vectorised"] = "event"
    options: dict[str, Any] = Field(default_factory=dict, description="optimise/walk-forward/monte-carlo options")


class BacktestIn(BaseModel):
    strategy_id: int | None = None
    dsl: StrategyDSL | None = None
    kind: Literal["backtest", "optimise", "walk_forward", "monte_carlo"] = "backtest"
    params: BacktestParamsIn


class BacktestSummary(ORM):
    id: int
    strategy_id: int | None
    strategy_version: int | None
    kind: str
    status: str
    progress: float
    metrics: dict[str, Any]
    params: dict[str, Any]
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    name: str | None = None


class BacktestOut(BacktestSummary):
    dsl: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    drawdown_curve: list[dict[str, Any]]
    monthly_returns: list[dict[str, Any]]
    extra: dict[str, Any]


class BacktestTradeOut(ORM):
    id: int
    symbol: str
    leg: str | None
    side: str
    quantity: int
    entry_ts: datetime
    entry_price: float
    exit_ts: datetime | None
    exit_price: float | None
    gross_pnl: float
    charges: float
    net_pnl: float
    exit_reason: str | None
    meta: dict[str, Any]
