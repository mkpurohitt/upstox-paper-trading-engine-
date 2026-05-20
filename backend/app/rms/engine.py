import logging
import httpx  # type: ignore[import-unresolved]
from typing import Any

from app.core.time import now_ist
from app.data.repository import Repository
from app.data.token_store import token_store
from app.models.schemas import RmsEvent, Signal

logger = logging.getLogger(__name__)

class RmsEngine:
    def __init__(self, settings: Any, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo
        self._last_signal_timestamps: dict[str, Any] = {}

    async def validate_signal(self, signal: Signal) -> tuple[bool, list[RmsEvent]]:
        """Asynchronous pre-trade validation engine using the official Upstox Margin API."""
        events: list[RmsEvent] = []
        now = now_ist()
        
        # 1. Active Market Data Ingestion Check
        tick = self.repo.ticks.get(signal.instrument_key)
        if not tick:
            events.append(self._event(signal, "missing_market_data", "critical", 
                "Blocked: Instrument has no active market data subscription."))
            self._record_events(events)
            return False, events

        price = float(signal.limit_price or tick.ltp)
        qty = int(signal.quantity)

        # 2. Basic Invariant Boundaries
        if qty <= 0:
            events.append(self._event(signal, "invalid_quantity", "critical", 
                "Blocked: Order execution quantity must be strictly positive."))
        if signal.confidence < 0.2:
            events.append(self._event(signal, "low_confidence", "warning", 
                "Blocked: Signal confidence score falls below configured baseline floor."))

        # 3. Cooldown Duplicate Protection Check
        last_sig_time = self._last_signal_timestamps.get(signal.instrument_key)
        cooldown_seconds = float(getattr(self.settings, "risk_cooldown_seconds", 2.0))
        if last_sig_time and (now - last_sig_time).total_seconds() < cooldown_seconds:
            events.append(self._event(signal, "cooldown_violation", "critical", 
                f"Blocked: Throttling duplicate signal. Cooldown window is {cooldown_seconds}s."))

        # 4. Fetch Margin Cost from Upstox API (with fail-safe fallback)
        estimated_margin_cost = await self._fetch_upstox_official_margin(signal, price, tick.ltp)
        available_margin = float(self.repo.capital.available_margin if self.repo.capital else 0.0)
        
        if estimated_margin_cost > available_margin:
            events.append(self._event(signal, "margin_breach", "critical", 
                f"Blocked: Insufficient virtual margin. Required: {estimated_margin_cost:.2f}, Available: {available_margin:.2f}."))

        # 5. Position Concentration Check
        max_pos_size = float(getattr(self.settings, "risk_max_position_size", 500000.0))
        current_strategy_exposure = self._calculate_current_exposure(signal.strategy_id)
        if (current_strategy_exposure + estimated_margin_cost) > max_pos_size:
            events.append(self._event(signal, "concentration_breach", "critical", 
                f"Blocked: Exceeds maximum strategy concentration limit of {max_pos_size:.2f}."))

        # 6. Intraday Max Loss Drawdown Check
        max_daily_loss = float(getattr(self.settings, "risk_max_loss_per_day", 20000.0))
        current_daily_pnl = self._calculate_current_pnl(signal.strategy_id)
        if current_daily_pnl < -max_daily_loss:
            events.append(self._event(signal, "drawdown_breach", "critical", 
                f"Blocked: Trading halted. Strategy day loss limits breached: {current_daily_pnl:.2f} / -{max_daily_loss:.2f}."))

        critical_triggered = any(e.severity == "critical" for e in events)
        if not critical_triggered:
            self._last_signal_timestamps[signal.instrument_key] = now

        self._record_events(events)
        return not critical_triggered, events

    async def _fetch_upstox_official_margin(self, signal: Signal, execution_price: float, current_ltp: float) -> float:
        """Calls the official Upstox Charges/Margin API with local fallback protections."""
        token = (
            token_store.access_token("sandbox") 
            or token_store.access_token("live") 
            or getattr(self.settings, "live_token", None)
        )
        
        if not token:
            logger.warning("No authentication token detected in token_store. Using local margin calculation fallback.")
            return self._calculate_local_fallback_margin(signal, execution_price, current_ltp)

        # Uses str().upper() to handle StrEnums safely without accessing .value on a str union
        payload = {
            "instruments": [
                {
                    "instrument_key": signal.instrument_key,
                    "quantity": int(signal.quantity),
                    "transaction_type": str(signal.side).upper(),
                    "product": str(signal.product).upper()
                }
            ]
        }
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.post("https://api.upstox.com/v2/charges/margin", json=payload, headers=headers)
                if response.status_code == 200:
                    res_data = response.json()
                    return float(res_data.get("data", {}).get("required_margin", 0.0))
                else:
                    logger.error(f"Upstox Margin API returned non-200 response: {response.status_code} - {response.text}")
        except Exception as api_err:
            logger.error(f"Network error querying official Upstox Margin Calculator API: {str(api_err)}")

        return self._calculate_local_fallback_margin(signal, execution_price, current_ltp)

    def _calculate_local_fallback_margin(self, signal: Signal, execution_price: float, current_ltp: float) -> float:
        """Fall-back pricing approximation model for structural safety."""
        side_str = str(signal.side).upper()
        inst_key = signal.instrument_key.upper()
        qty = float(signal.quantity)
        
        if side_str == "BUY":
            return qty * execution_price

        if "FO|" in inst_key or "|CE" in inst_key or "|PE" in inst_key:
            underlying_spot = current_ltp if current_ltp > 0 else execution_price
            return (underlying_spot * qty * 0.15) + (qty * execution_price)

        return qty * execution_price * 0.20

    def _calculate_current_exposure(self, strategy_id: str) -> float:
        exposure = 0.0
        for pos in list(self.repo.positions.values()):
            if getattr(pos, "strategy_id", None) == strategy_id:
                qty = abs(float(getattr(pos, "quantity", 0.0)))
                ltp = float(getattr(pos, "ltp", 0.0))
                exposure += (qty * ltp)
        return exposure

    def _calculate_current_pnl(self, strategy_id: str) -> float:
        total_pnl = 0.0
        for pos in list(self.repo.positions.values()):
            if getattr(pos, "strategy_id", None) == strategy_id:
                realized = float(getattr(pos, "realized_pnl", 0.0))
                unrealized = float(getattr(pos, "unrealized_pnl", 0.0))
                total_pnl += (realized + unrealized)
        return total_pnl

    def _record_events(self, events: list[RmsEvent]) -> None:
        for event in events:
            if hasattr(self.repo.rms_events, "appendleft"):
                self.repo.rms_events.appendleft(event)
            else:
                self.repo.rms_events.append(event)

    def _event(self, signal: Signal, event_type: str, severity: str, message: str) -> RmsEvent:
        return RmsEvent(
            strategy_id=signal.strategy_id,
            event_type=event_type,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            event=signal.model_dump(mode="json"),
            created_at=now_ist(),
        )