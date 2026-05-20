# Strategy Contract

Strategy files live in `strategies/sample_strategies` or any mounted strategy folder. A strategy may expose `create_strategy()` or a class that implements the methods below:

```python
class StrategyBase:
    strategy_name: str
    version: str

    def initialize(self, context): ...
    def on_market_data(self, tick, context): ...
    def on_bar(self, candle, context): ...
    def generate_signal(self, context): ...
    def on_order_update(self, order_event, context): ...
    def on_fill(self, fill_event, context): ...
    def shutdown(self, context): ...
```

`generate_signal()` returns an `app.models.schemas.Signal`. The engine attaches the strategy id and routes the signal through RMS before any execution.

Context exposes:

- `market_cache`
- `positions`
- `open_orders`
- `risk_limits`
- `latest(instrument_key)`
- `log(message)`

