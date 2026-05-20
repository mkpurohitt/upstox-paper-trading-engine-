from app.core.time import now_ist
from app.models.schemas import OrderType, Side, Signal


class MomentumStrategy:
    strategy_name = "Sample Momentum"
    version = "0.1.0"
    default_config = {"instrument_key": "NSE_INDEX|Nifty 50", "quantity": 1, "threshold": 8}

    def initialize(self, context):
        self.last_price = None
        self.fired = False
        context.log("Momentum strategy initialized")

    def on_market_data(self, tick, context):
        self.tick = tick

    def on_bar(self, candle, context):
        return None

    def generate_signal(self, context):
        instrument = context.config.get("instrument_key")
        tick = context.latest(instrument)
        if tick is None:
            return None
        if self.last_price is None:
            self.last_price = tick.ltp
            return None
        move = tick.ltp - self.last_price
        self.last_price = tick.ltp
        if self.fired or abs(move) < context.config.get("threshold", 8):
            return None
        self.fired = True
        side = Side.BUY if move > 0 else Side.SELL
        return Signal(
            strategy_id=context.strategy_id,
            timestamp=now_ist(),
            instrument_key=instrument,
            symbol="NIFTY",
            side=side,
            order_type=OrderType.LIMIT,
            quantity=context.config.get("quantity", 1),
            limit_price=tick.ltp,
            confidence=0.72,
            reason=f"Momentum move detected: {move:.2f}",
            metadata={"timeframe": "tick", "sample": True},
        )

    def on_order_update(self, order_event, context):
        context.log(f"Order update: {order_event}")

    def on_fill(self, fill_event, context):
        context.log(f"Fill: {fill_event}")

    def shutdown(self, context):
        context.log("Momentum strategy stopped")


def create_strategy():
    return MomentumStrategy()

