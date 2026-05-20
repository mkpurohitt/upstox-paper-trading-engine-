from app.core.time import now_ist
from app.models.schemas import OrderType, Side, Signal


class MyNiftyStrategy:
    strategy_name = "My Nifty Strategy"
    version = "0.1.0"

    default_config = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "quantity": 1,
        "buy_above": 23650,
        "sell_below": 23550,
    }

    def initialize(self, context):
        self.last_signal = None
        context.log("My strategy started")

    def on_market_data(self, tick, context):
        self.latest_tick = tick

    def on_bar(self, candle, context):
        pass

    def generate_signal(self, context):
        instrument = context.config["instrument_key"]
        tick = context.latest(instrument)

        if tick is None:
            return None

        if tick.ltp > context.config["buy_above"] and self.last_signal != "BUY":
            self.last_signal = "BUY"
            return Signal(
                strategy_id=context.strategy_id,
                timestamp=now_ist(),
                instrument_key=instrument,
                symbol="NIFTY",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=context.config["quantity"],
                limit_price=tick.ltp,
                confidence=0.80,
                reason=f"Nifty crossed above {context.config['buy_above']}",
                metadata={"source": "live_tick"},
            )

        if tick.ltp < context.config["sell_below"] and self.last_signal != "SELL":
            self.last_signal = "SELL"
            return Signal(
                strategy_id=context.strategy_id,
                timestamp=now_ist(),
                instrument_key=instrument,
                symbol="NIFTY",
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                quantity=context.config["quantity"],
                limit_price=tick.ltp,
                confidence=0.80,
                reason=f"Nifty crossed below {context.config['sell_below']}",
                metadata={"source": "live_tick"},
            )

        return None

    def on_order_update(self, order_event, context):
        context.log(f"Order update: {order_event}")

    def on_fill(self, fill_event, context):
        context.log(f"Fill event: {fill_event}")

    def shutdown(self, context):
        context.log("My strategy stopped")


def create_strategy():
    return MyNiftyStrategy()