from app.core.time import now_ist
from app.models.schemas import Fill, Side
from app.pnl.engine import apply_fill


def test_apply_fill_tracks_realized_pnl() -> None:
    buy = Fill(order_id="o1", fill_price=100, fill_quantity=10, fill_timestamp=now_ist())
    pos = apply_fill(None, buy, Side.BUY, "s1", "NSE_EQ|X")
    sell = Fill(order_id="o2", fill_price=110, fill_quantity=5, fill_timestamp=now_ist())
    pos = apply_fill(pos, sell, Side.SELL, "s1", "NSE_EQ|X")
    assert pos.quantity == 5
    assert pos.realized_pnl == 50

