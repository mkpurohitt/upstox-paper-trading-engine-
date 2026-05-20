from app.core.time import now_ist
from app.data.repository import Repository
from app.execution.upstox_sandbox import UpstoxSandboxExecutionAdapter
from app.models.schemas import Fill, Order, OrderStatus, Signal
from app.pnl.engine import apply_fill
from app.reconciliation.engine import ReconciliationEngine
from app.rms.engine import RmsEngine
from app.services.event_bus import EventBus


class PaperOMS:
    def __init__(self, repo: Repository, bus: EventBus, rms: RmsEngine, reconciliation: ReconciliationEngine, adapter: UpstoxSandboxExecutionAdapter) -> None:
        self.repo = repo
        self.bus = bus
        self.rms = rms
        self.reconciliation = reconciliation
        self.adapter = adapter

    async def route_signal(self, signal: Signal) -> Order | None:
        approved, events = self.rms.validate_signal(signal)
        if not approved:
            signal.status = "rejected"
            reason = "; ".join(event.message for event in events)
            rec = self.reconciliation.signal_rejected(signal, reason)
            await self.bus.publish("rms-alerts", {"events": [event.model_dump(mode="json") for event in events]})
            await self.bus.publish("reconciliation-events", rec.model_dump(mode="json"))
            return None
        signal.status = "approved"
        self.reconciliation.signal_approved(signal)
        now = now_ist()
        last_tick = self.repo.ticks.get(signal.instrument_key)
        price = signal.limit_price or (last_tick.ltp if last_tick else 0)
        order = Order(
            strategy_id=signal.strategy_id,
            signal_id=signal.id,
            instrument_key=signal.instrument_key,
            side=signal.side,
            order_type=signal.order_type,
            product=signal.product,
            quantity=signal.quantity,
            price=price,
            status=OrderStatus.SENT,
            created_at=now,
            updated_at=now,
        )
        self.repo.orders[order.id] = order
        response = await self.adapter.place_order(order)
        order.raw_response = response
        order.broker_order_id = response.get("data", {}).get("order_ids", [None])[0]
        order.status = OrderStatus.ACCEPTED
        order.updated_at = now_ist()
        sent = self.reconciliation.order_sent(signal, order)
        await self.bus.publish("order-updates", order.model_dump(mode="json"))
        await self.bus.publish("reconciliation-events", sent.model_dump(mode="json"))
        await self._simulate_fill(order)
        signal.status = "routed"
        return order

    async def _simulate_fill(self, order: Order) -> None:
        fill = Fill(order_id=order.id, fill_price=order.price, fill_quantity=order.quantity, fill_timestamp=now_ist(), raw_response={"mode": "local_fill"})
        self.repo.fills[fill.id] = fill
        order.status = OrderStatus.FILLED
        order.updated_at = now_ist()
        position = apply_fill(self.repo.get_position(order.strategy_id, order.instrument_key), fill, order.side, order.strategy_id, order.instrument_key)
        self.repo.upsert_position(position)
        if self.repo.capital:
            self.repo.capital.current_capital = self.repo.capital.starting_capital + sum(pos.mtm for pos in self.repo.positions.values())
            self.repo.capital.available_margin = self.repo.capital.current_capital
            self.repo.capital.updated_at = now_ist()
        rec = self.reconciliation.fill_received(order, fill)
        await self.bus.publish("fill-updates", fill.model_dump(mode="json"))
        await self.bus.publish("pnl-updates", position.model_dump(mode="json"))
        await self.bus.publish("order-updates", order.model_dump(mode="json"))
        await self.bus.publish("reconciliation-events", rec.model_dump(mode="json"))

