from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models.schemas import MarketTick, Signal


class StrategyBase(Protocol):
    strategy_name: str
    version: str

    def initialize(self, context: "StrategyContext") -> None: ...
    def on_market_data(self, tick: MarketTick, context: "StrategyContext") -> None: ...
    def on_bar(self, candle: Any, context: "StrategyContext") -> None: ...
    def generate_signal(self, context: "StrategyContext") -> Signal | None: ...
    def on_order_update(self, order_event: Any, context: "StrategyContext") -> None: ...
    def on_fill(self, fill_event: Any, context: "StrategyContext") -> None: ...
    def shutdown(self, context: "StrategyContext") -> None: ...


@dataclass
class StrategyContext:
    strategy_id: str
    config: dict[str, Any]
    market_cache: dict[str, MarketTick]
    positions: dict[str, Any]
    open_orders: dict[str, Any]
    risk_limits: dict[str, Any]
    logs: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        self.logs.append(message)

    def latest(self, instrument_key: str) -> MarketTick | None:
        return self.market_cache.get(instrument_key)

