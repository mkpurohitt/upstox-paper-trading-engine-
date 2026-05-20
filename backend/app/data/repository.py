from collections import deque
from dataclasses import dataclass, field

from app.core.time import now_ist
from app.models.schemas import (
    CapitalAccount,
    Fill,
    MarketTick,
    Order,
    Position,
    ReconciliationEvent,
    RmsEvent,
    Signal,
    StrategyDefinition,
    StrategyRun,
)


@dataclass
class Repository:
    ticks: dict[str, MarketTick] = field(default_factory=dict)
    strategies: dict[str, StrategyDefinition] = field(default_factory=dict)
    runs: dict[str, StrategyRun] = field(default_factory=dict)
    signals: dict[str, Signal] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    fills: dict[str, Fill] = field(default_factory=dict)
    positions: dict[str, Position] = field(default_factory=dict)
    rms_events: deque[RmsEvent] = field(default_factory=lambda: deque(maxlen=500))
    reconciliation_events: deque[ReconciliationEvent] = field(default_factory=lambda: deque(maxlen=500))
    capital: CapitalAccount | None = None

    def ensure_capital(self, starting_capital: float) -> CapitalAccount:
        if self.capital is None:
            self.capital = CapitalAccount(
                starting_capital=starting_capital,
                current_capital=starting_capital,
                available_margin=starting_capital,
                updated_at=now_ist(),
            )
        return self.capital

    def upsert_tick(self, tick: MarketTick) -> None:
        self.ticks[tick.instrument_key] = tick

    def upsert_position(self, position: Position) -> None:
        key = f"{position.strategy_id}:{position.instrument_key}"
        self.positions[key] = position

    def get_position(self, strategy_id: str | None, instrument_key: str) -> Position | None:
        return self.positions.get(f"{strategy_id}:{instrument_key}")


repo = Repository()

