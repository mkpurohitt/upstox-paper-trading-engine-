from app.core.time import now_ist
from app.models.schemas import Fill, Position, Side


def apply_fill(position: Position | None, fill: Fill, side: Side, strategy_id: str | None, instrument_key: str) -> Position:
    position = position or Position(strategy_id=strategy_id, instrument_key=instrument_key, updated_at=now_ist())
    signed_qty = fill.fill_quantity if side == Side.BUY else -fill.fill_quantity
    new_qty = position.quantity + signed_qty
    if position.quantity == 0 or (position.quantity > 0 and signed_qty > 0) or (position.quantity < 0 and signed_qty < 0):
        total_cost = position.avg_price * abs(position.quantity) + fill.fill_price * fill.fill_quantity
        position.avg_price = total_cost / max(abs(new_qty), 1)
    else:
        closed_qty = min(abs(position.quantity), fill.fill_quantity)
        pnl_per_unit = (fill.fill_price - position.avg_price) * (1 if position.quantity > 0 else -1)
        position.realized_pnl += pnl_per_unit * closed_qty
        if new_qty == 0:
            position.avg_price = 0
        elif abs(signed_qty) > abs(position.quantity):
            position.avg_price = fill.fill_price
    position.quantity = new_qty
    position.ltp = fill.fill_price
    position.unrealized_pnl = (position.ltp - position.avg_price) * position.quantity
    position.mtm = position.realized_pnl + position.unrealized_pnl
    position.updated_at = now_ist()
    return position

