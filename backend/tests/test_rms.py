from app.core.config import Settings
from app.core.time import now_ist
from app.data.repository import Repository
from app.models.schemas import MarketTick, Side, Signal
from app.rms.engine import RmsEngine


def test_rms_blocks_missing_market_data() -> None:
    repo = Repository()
    engine = RmsEngine(Settings(risk_max_order_value=1000), repo)
    signal = Signal(strategy_id="s1", timestamp=now_ist(), instrument_key="NSE_EQ|X", side=Side.BUY, quantity=1, limit_price=10)
    approved, events = engine.validate_signal(signal)
    assert approved is False
    assert events[0].event_type == "missing_market_data"


def test_rms_allows_valid_signal() -> None:
    repo = Repository()
    repo.upsert_tick(MarketTick(instrument_key="NSE_EQ|X", timestamp=now_ist(), ltp=10))
    engine = RmsEngine(Settings(risk_max_order_value=1000), repo)
    signal = Signal(strategy_id="s1", timestamp=now_ist(), instrument_key="NSE_EQ|X", side=Side.BUY, quantity=10, limit_price=10)
    approved, events = engine.validate_signal(signal)
    assert approved is True
    assert events == []

