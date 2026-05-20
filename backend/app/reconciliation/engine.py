from app.core.time import now_ist
from app.data.repository import Repository
from app.models.schemas import Fill, Order, ReconciliationEvent, Signal


class ReconciliationEngine:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def signal_approved(self, signal: Signal) -> ReconciliationEvent:
        return self._record("signal_approved", signal_id=signal.id, strategy_id=signal.strategy_id)

    def signal_rejected(self, signal: Signal, reason: str) -> ReconciliationEvent:
        return self._record("signal_rejected", signal_id=signal.id, strategy_id=signal.strategy_id, details={"reason": reason})

    def order_sent(self, signal: Signal, order: Order) -> ReconciliationEvent:
        return self._record("order_sent", signal.id, order.id, strategy_id=signal.strategy_id)

    def fill_received(self, order: Order, fill: Fill) -> ReconciliationEvent:
        return self._record("fill_received", order_id=order.id, fill_id=fill.id, strategy_id=order.strategy_id)

    def _record(
        self,
        status: str,
        signal_id: str | None = None,
        order_id: str | None = None,
        fill_id: str | None = None,
        strategy_id: str | None = None,
        details: dict | None = None,
    ) -> ReconciliationEvent:
        event = ReconciliationEvent(
            strategy_id=strategy_id,
            signal_id=signal_id,
            order_id=order_id,
            fill_id=fill_id,
            status=status,
            details=details or {},
            created_at=now_ist(),
        )
        self.repo.reconciliation_events.appendleft(event)
        return event

