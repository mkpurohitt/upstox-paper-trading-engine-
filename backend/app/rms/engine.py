from app.core.config import Settings
from app.core.time import now_ist
from app.data.repository import Repository
from app.models.schemas import RmsEvent, Signal


class RmsEngine:
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo

    def validate_signal(self, signal: Signal) -> tuple[bool, list[RmsEvent]]:
        events: list[RmsEvent] = []
        tick = self.repo.ticks.get(signal.instrument_key)
        price = signal.limit_price or (tick.ltp if tick else 0)
        notional = float(signal.quantity) * float(price or 0)
        if signal.instrument_key not in self.repo.ticks:
            events.append(self._event(signal, "missing_market_data", "critical", "Blocked: instrument has no active market data subscription."))
        if notional > self.settings.risk_max_order_value:
            events.append(self._event(signal, "max_order_value", "critical", f"Blocked: order value {notional:.2f} exceeds limit."))
        if signal.quantity <= 0:
            events.append(self._event(signal, "invalid_quantity", "critical", "Blocked: quantity must be positive."))
        if signal.confidence < 0.2:
            events.append(self._event(signal, "low_confidence", "warning", "Blocked: signal confidence below configured floor."))
        for event in events:
            self.repo.rms_events.appendleft(event)
        return not any(event.severity == "critical" for event in events), events

    def _event(self, signal: Signal, event_type: str, severity: str, message: str) -> RmsEvent:
        return RmsEvent(
            strategy_id=signal.strategy_id,
            event_type=event_type,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            event=signal.model_dump(mode="json"),
            created_at=now_ist(),
        )
