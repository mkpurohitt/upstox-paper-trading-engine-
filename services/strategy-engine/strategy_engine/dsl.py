"""Strategy DSL v1.0 - a declarative, versioned JSON format.

The same document drives the form builder, the visual (React Flow) builder,
the code builder, the backtester and the live runner. It is *data*, never
executable code: custom Python (advanced mode) is only allowed inside
`IndicatorSpec(kind="CUSTOM")` and always runs in the sandbox.

Example (EMA crossover)::

    {
      "dsl_version": "1.0", "name": "EMA 9/21 crossover", "kind": "equity",
      "universe": {"symbols": ["NSE:RELIANCE"]}, "timeframe": "15m", "product": "MIS",
      "indicators": [{"id": "fast", "kind": "EMA", "params": {"period": 9}},
                     {"id": "slow", "kind": "EMA", "params": {"period": 21}}],
      "entry": {"long": {"kind": "all", "conditions": [
          {"kind": "compare", "left": {"type": "indicator", "ref": "fast"},
           "op": "crosses_above", "right": {"type": "indicator", "ref": "slow"}}]}},
      "exit": {"long": {"kind": "any", "conditions": [
          {"kind": "compare", "left": {"type": "indicator", "ref": "fast"},
           "op": "crosses_below", "right": {"type": "indicator", "ref": "slow"}}]},
               "stop_loss": {"type": "percent", "value": 1.0}, "target": {"type": "percent", "value": 2.0}},
      "sizing": {"mode": "capital_pct", "value": 20},
      "schedule": {"entry_after": "09:20", "entry_before": "14:45", "square_off": "15:15"}
    }
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DSL_VERSION: Final = "1.0"
_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

Timeframe = Literal["1m", "3m", "5m", "15m", "30m", "1h", "1d"]
CompareOp = Literal[">", "<", ">=", "<=", "==", "crosses_above", "crosses_below"]
PriceField = Literal["open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4"]
DayName = Literal["MON", "TUE", "WED", "THU", "FRI"]
_WEEKDAYS: tuple[DayName, ...] = ("MON", "TUE", "WED", "THU", "FRI")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- operands
class IndicatorOperand(_M):
    type: Literal["indicator"] = "indicator"
    ref: str = Field(description="indicator id, optionally `.output` e.g. `macd.signal`")
    offset: int = Field(default=0, ge=0, le=50, description="bars ago")


class PriceOperand(_M):
    type: Literal["price"] = "price"
    field: PriceField = "close"
    offset: int = Field(default=0, ge=0, le=50)


class ConstOperand(_M):
    type: Literal["const"] = "const"
    value: float


Operand = Annotated[IndicatorOperand | PriceOperand | ConstOperand, Field(discriminator="type")]


# ---------------------------------------------------------------- conditions
class CompareCondition(_M):
    kind: Literal["compare"] = "compare"
    left: Operand
    op: CompareOp
    right: Operand


class TimeCondition(_M):
    kind: Literal["time"] = "time"
    after: str | None = Field(default=None, description="HH:MM IST, inclusive")
    before: str | None = Field(default=None, description="HH:MM IST, exclusive")

    @field_validator("after", "before")
    @classmethod
    def _hhmm(cls, v: str | None) -> str | None:
        if v is not None and not _HHMM.match(v):
            raise ValueError("time must be HH:MM")
        return v


class DayCondition(_M):
    kind: Literal["day_of_week"] = "day_of_week"
    days: list[DayName] = Field(min_length=1)


PatternName = Literal[
    "doji", "hammer", "inverted_hammer", "shooting_star", "bullish_engulfing", "bearish_engulfing",
    "morning_star", "evening_star", "inside_bar", "outside_bar", "three_white_soldiers", "three_black_crows",
    "breakout_high", "breakdown_low", "gap_up", "gap_down",
]


class PatternCondition(_M):
    kind: Literal["pattern"] = "pattern"
    name: PatternName
    lookback: int = Field(default=20, ge=2, le=500)


class GroupCondition(_M):
    kind: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(default_factory=list)


Condition = Annotated[
    CompareCondition | TimeCondition | DayCondition | PatternCondition | GroupCondition,
    Field(discriminator="kind"),
]
GroupCondition.model_rebuild()


# ---------------------------------------------------------------- building blocks
class IndicatorSpec(_M):
    id: str
    kind: str = Field(description="e.g. EMA, RSI, MACD, SUPERTREND, CUSTOM")
    params: dict[str, float | int | str] = Field(default_factory=dict)
    source: PriceField = "close"
    code: str | None = Field(default=None, description="CUSTOM only: `def compute(df, params): ...` (sandboxed)")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("indicator id must be lowercase snake_case (max 32 chars)")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        return v.upper()


class Universe(_M):
    symbols: list[str] = Field(default_factory=list, max_length=50)
    underlying: str | None = Field(default=None, description="options: NIFTY, BANKNIFTY, ... or a stock")


class StopSpec(_M):
    type: Literal["percent", "points", "atr"] = "percent"
    value: float = Field(gt=0)
    atr_period: int = Field(default=14, ge=2, le=100)


class TrailingSpec(_M):
    type: Literal["percent", "points"] = "percent"
    value: float = Field(gt=0)
    activate_after: float = Field(default=0.0, ge=0, description="profit (same unit) before trailing starts")


class SideRules(_M):
    long: GroupCondition | None = None
    short: GroupCondition | None = None


class ExitRules(SideRules):
    stop_loss: StopSpec | None = None
    target: StopSpec | None = None
    trailing_sl: TrailingSpec | None = None
    max_holding_bars: int | None = Field(default=None, ge=1, le=100_000)


class StrikeSelector(_M):
    mode: Literal["ATM_OFFSET", "DELTA", "PREMIUM"] = "ATM_OFFSET"
    offset: int = Field(default=0, ge=-30, le=30, description="ATM_OFFSET: strikes away from ATM (+ = higher strike)")
    delta: float | None = Field(default=None, ge=0.01, le=0.99, description="DELTA: absolute delta target")
    premium: float | None = Field(default=None, gt=0, description="PREMIUM: closest premium in ₹")


class OptionLegSpec(_M):
    id: str = Field(default="leg")
    action: Literal["BUY", "SELL"]
    option_type: Literal["CE", "PE", "FUT"]
    strike: StrikeSelector = Field(default_factory=StrikeSelector)
    expiry: Literal["current", "next", "monthly"] = "current"
    lots: int = Field(default=1, ge=1, le=100)
    stop_loss_pct: float | None = Field(default=None, gt=0, le=1000, description="leg SL as % of entry premium")
    target_pct: float | None = Field(default=None, gt=0, le=100)


class OptionsExit(_M):
    combined_stop_loss_pct: float | None = Field(default=None, gt=0, le=1000, description="% of net premium")
    combined_target_pct: float | None = Field(default=None, gt=0, le=100, description="% of net premium captured")
    stop_loss_amount: float | None = Field(default=None, gt=0, description="₹ MTM loss per set")
    target_amount: float | None = Field(default=None, gt=0, description="₹ MTM profit per set")
    exit_on_expiry_day_at: str | None = None


class Sizing(_M):
    mode: Literal["fixed_qty", "fixed_lots", "capital_pct", "fixed_capital"] = "capital_pct"
    value: float = Field(default=10, gt=0)


class Schedule(_M):
    entry_after: str | None = "09:20"
    entry_before: str | None = "15:00"
    square_off: str | None = "15:15"
    days: list[DayName] = Field(default_factory=lambda: list(_WEEKDAYS))

    @field_validator("entry_after", "entry_before", "square_off")
    @classmethod
    def _hhmm(cls, v: str | None) -> str | None:
        if v is not None and not _HHMM.match(v):
            raise ValueError("time must be HH:MM")
        return v


class Reentry(_M):
    enabled: bool = False
    max_per_day: int = Field(default=1, ge=0, le=20)
    cooldown_bars: int = Field(default=0, ge=0, le=500)


class RiskSpec(_M):
    max_loss_per_day: float | None = Field(default=None, gt=0, description="₹; stop trading for the day")
    max_trades_per_day: int | None = Field(default=None, ge=1, le=500)
    portfolio_max_loss: float | None = Field(default=None, gt=0, description="₹ from initial capital; halt strategy")
    max_profit_per_day: float | None = Field(default=None, gt=0)


class PairSpec(_M):
    leg_a: str
    leg_b: str
    lookback: int = Field(default=60, ge=10, le=2000)
    entry_z: float = Field(default=2.0, gt=0, le=10)
    exit_z: float = Field(default=0.5, ge=0, le=5)
    stop_z: float | None = Field(default=4.0, gt=0, le=20)
    hedge: Literal["ols", "fixed"] = "ols"
    fixed_ratio: float | None = None


class StrategyDSL(_M):
    dsl_version: Literal["1.0"] = DSL_VERSION
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    kind: Literal["equity", "options", "pair"] = "equity"
    universe: Universe = Field(default_factory=Universe)
    timeframe: Timeframe = "15m"
    product: Literal["MIS", "CNC", "NRML"] = "MIS"
    indicators: list[IndicatorSpec] = Field(default_factory=list, max_length=30)
    entry: SideRules = Field(default_factory=SideRules)
    exit: ExitRules = Field(default_factory=ExitRules)
    legs: list[OptionLegSpec] = Field(default_factory=list, max_length=8)
    options_exit: OptionsExit = Field(default_factory=OptionsExit)
    pair: PairSpec | None = None
    sizing: Sizing = Field(default_factory=Sizing)
    schedule: Schedule = Field(default_factory=Schedule)
    reentry: Reentry = Field(default_factory=Reentry)
    risk: RiskSpec = Field(default_factory=RiskSpec)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _cross_validate(self) -> StrategyDSL:
        from strategy_engine.indicators import REGISTRY

        ids = [i.id for i in self.indicators]
        if len(ids) != len(set(ids)):
            raise ValueError("indicator ids must be unique")
        outputs: dict[str, list[str]] = {}
        for ind in self.indicators:
            if ind.kind == "CUSTOM":
                if not ind.code:
                    raise ValueError(f"custom indicator {ind.id!r} needs `code`")
                outputs[ind.id] = []
                continue
            spec = REGISTRY.get(ind.kind)
            if spec is None:
                raise ValueError(f"unknown indicator kind {ind.kind!r}")
            unknown = set(ind.params) - set(spec.params)
            if unknown:
                raise ValueError(f"{ind.id}: unknown params {sorted(unknown)} for {ind.kind}")
            for p, v in ind.params.items():
                lo, hi = spec.params[p][1], spec.params[p][2]
                if isinstance(v, int | float) and not (lo <= float(v) <= hi):
                    raise ValueError(f"{ind.id}.{p}={v} out of range [{lo}, {hi}]")
            outputs[ind.id] = spec.outputs if len(spec.outputs) > 1 else []

        def check_operand(o: Any) -> None:
            if isinstance(o, IndicatorOperand):
                base, _, out = o.ref.partition(".")
                if base not in outputs:
                    raise ValueError(f"condition references unknown indicator {o.ref!r}")
                if out and outputs[base] and out not in outputs[base]:
                    raise ValueError(f"{base} has no output {out!r} (choose from {outputs[base]})")
                if not out and outputs[base]:
                    raise ValueError(f"{base} has multiple outputs; use one of {[f'{base}.{x}' for x in outputs[base]]}")

        def walk(c: Any) -> None:
            if isinstance(c, GroupCondition):
                for x in c.conditions:
                    walk(x)
            elif isinstance(c, CompareCondition):
                check_operand(c.left)
                check_operand(c.right)

        for g in (self.entry.long, self.entry.short, self.exit.long, self.exit.short):
            if g is not None:
                walk(g)

        if self.kind == "equity":
            if not self.universe.symbols:
                raise ValueError("equity strategies need at least one symbol in universe.symbols")
            if self.entry.long is None and self.entry.short is None:
                raise ValueError("define at least one entry rule (long or short)")
        elif self.kind == "options":
            if not self.universe.underlying:
                raise ValueError("options strategies need universe.underlying")
            if not self.legs:
                raise ValueError("options strategies need at least one leg")
            leg_ids = [leg.id for leg in self.legs]
            if len(leg_ids) != len(set(leg_ids)):
                raise ValueError("leg ids must be unique")
        elif self.kind == "pair" and self.pair is None:
            raise ValueError("pair strategies need a `pair` block")
        return self

    # convenience -----------------------------------------------------------
    @property
    def symbols(self) -> list[str]:
        if self.kind == "pair" and self.pair:
            return [self.pair.leg_a, self.pair.leg_b]
        if self.kind == "options" and self.universe.underlying:
            from market_data.symbols import underlying_spot_symbol

            return [underlying_spot_symbol(self.universe.underlying)]
        return self.universe.symbols


def validate_dsl(data: dict[str, Any]) -> tuple[StrategyDSL | None, list[dict[str, Any]]]:
    """Validate raw JSON; returns (model, errors) with UI-friendly error paths."""
    from pydantic import ValidationError

    try:
        return StrategyDSL.model_validate(data), []
    except ValidationError as exc:
        return None, [
            {"path": ".".join(str(p) for p in e["loc"]), "message": e["msg"].removeprefix("Value error, ")}
            for e in exc.errors()
        ]


def dsl_json_schema() -> dict[str, Any]:
    return StrategyDSL.model_json_schema()


def set_path(dsl: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Set a parameter by dotted path; list items are addressed by `id`
    (e.g. ``indicators.fast.params.period``, ``exit.stop_loss.value``)."""
    import copy

    out = copy.deepcopy(dsl)
    cur: Any = out
    parts = path.split(".")
    for i, part in enumerate(parts[:-1]):
        if isinstance(cur, list):
            cur = next(x for x in cur if x.get("id") == part)
        else:
            if cur.get(part) is None:
                cur[part] = {}
            cur = cur[part]
        _ = i
    last = parts[-1]
    if isinstance(cur, list):
        raise ValueError(f"path {path} ends in a list")
    cur[last] = value
    return out
