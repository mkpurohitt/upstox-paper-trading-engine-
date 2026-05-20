import logging
from typing import Any, cast

from app.core.time import now_ist
from app.data.repository import Repository
from app.execution.upstox_sandbox import UpstoxSandboxExecutionAdapter
from app.models.schemas import Fill, Order, OrderStatus, Signal, MarketTick
from app.pnl.engine import apply_fill
from app.reconciliation.engine import ReconciliationEngine
from app.rms.engine import RmsEngine
from app.services.event_bus import EventBus

logger = logging.getLogger(__name__)

class PaperOMS:
    def __init__(
        self, 
        repo: Repository, 
        bus: EventBus, 
        rms: RmsEngine, 
        reconciliation: ReconciliationEngine, 
        adapter: UpstoxSandboxExecutionAdapter
    ) -> None:
        self.repo = repo
        self.bus = bus
        self.rms = rms
        self.reconciliation = reconciliation
        self.adapter = adapter

    async def route_signal(self, signal: Signal) -> Order | None:
        """Validates a signal against the RMS rules and submits it to the execution gateway."""
        # ADDED AWAIT: Wires the new asynchronous Upstox Margin API capability safely
        approved, events = await self.rms.validate_signal(signal)
        
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
        price = signal.limit_price or (last_tick.ltp if last_tick else 0.0)
        
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
        
        # Assign an initial execution tracking token to protect against double execution
        order.idempotency_key = getattr(signal, "idempotency_key", f"idmp_{order.id}")
        self.repo.orders[order.id] = order
        
        try:
            response = await self.adapter.place_order(order)
            order.raw_response = response
            
            # Extract broker token payload safely matching Upstox V3 open schema
            order_ids = response.get("data", {}).get("order_ids", [])
            order.broker_order_id = order_ids[0] if order_ids else f"local_{order.id}"
            order.status = OrderStatus.ACCEPTED
            order.updated_at = now_ist()
            
            sent = self.reconciliation.order_sent(signal, order)
            await self.bus.publish("order-updates", order.model_dump(mode="json"))
            await self.bus.publish("reconciliation-events", sent.model_dump(mode="json"))
            
            # If order submission to the true broker sandbox sandbox API is active,
            # we do NOT call local fill matching execution; we wait for the update loop.
            if not self.adapter.settings.enable_order_submission:
                # Handle instant market order filling if order_type is MARKET
                order_type_str = order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type)
                if order_type_str.upper() == "MARKET":
                    await self._execute_fill(order, fill_price=float(price), execution_mode="simulated_market")
            
            signal.status = "routed"
            return order
            
        except Exception as ex:
            logger.error(f"Execution routing critical exception for order {order.id}: {str(ex)}")
            order.status = OrderStatus.REJECTED
            order.updated_at = now_ist()
            await self.bus.publish("order-updates", order.model_dump(mode="json"))
            return order

    async def on_market_tick(self, tick: MarketTick) -> None:
        """Asynchronous Exchange Simulation Matching Engine.
        
        Processes outstanding pending limit and stop orders against live tick order books.
        """
        # Iterate over open orders to determine if matching parameters have crossed thresholds
        for order in list(self.repo.orders.values()):
            if order.status != OrderStatus.ACCEPTED or order.instrument_key != tick.instrument_key:
                continue
                
            order_type_str = order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type)
            side_str = order.side.value if hasattr(order.side, "value") else str(order.side)
            
            # Process matching calculations for limit execution patterns
            if order_type_str.upper() == "LIMIT":
                target_price = float(order.price)
                
                if side_str.upper() == "BUY":
                    # Buy limit hits if ask price or LTP dips to or below your limit target price
                    match_price = float(tick.ask if tick.ask else tick.ltp)
                    if match_price <= target_price:
                        await self._execute_fill(order, fill_price=match_price, execution_mode="simulated_limit_cross")
                        
                elif side_str.upper() == "SELL":
                    # Sell limit hits if bid price or LTP marks a high cross over your limit target price
                    match_price = float(tick.bid if tick.bid else tick.ltp)
                    if match_price >= target_price:
                        await self._execute_fill(order, fill_price=match_price, execution_mode="simulated_limit_cross")

    async def process_broker_update(self, broker_payload: dict[str, Any]) -> None:
        """Asynchronous entry point for streaming Upstox Sandbox/Live websocket feed status modifications."""
        broker_order_id = broker_payload.get("order_id")
        status_str = str(broker_payload.get("order_status", "")).upper()
        
        if not broker_order_id:
            return
            
        # Match incoming broker execution state maps with our internal repositories
        for order in list(self.repo.orders.values()):
            if order.broker_order_id == broker_order_id:
                if status_str == "FILLED" and order.status != OrderStatus.FILLED:
                    fill_price = float(broker_payload.get("average_price", order.price))
                    await self._execute_fill(order, fill_price=fill_price, execution_mode="broker_websocket_fill")
                elif status_str == "REJECTED":
                    order.status = OrderStatus.REJECTED
                    order.updated_at = now_ist()
                    await self.bus.publish("order-updates", order.model_dump(mode="json"))
                break

    async def _execute_fill(self, order: Order, fill_price: float, execution_mode: str) -> None:
        """Processes and calculates filled transactions, updates P&L, positions, and capital allocation states."""
        fill = Fill(
            order_id=order.id,
            fill_price=fill_price,
            fill_quantity=order.quantity,
            fill_timestamp=now_ist(),
            raw_response={"mode": execution_mode},
        )
        
        self.repo.fills[fill.id] = fill
        order.status = OrderStatus.FILLED
        order.updated_at = now_ist()
        
        # Calculate resulting adjustments on current inventory books
        raw_position = self.repo.get_position(order.strategy_id, order.instrument_key)
        position = apply_fill(raw_position, fill, order.side, order.strategy_id, order.instrument_key)
        self.repo.upsert_position(position)
        
        # Rebase virtual margin allocations across live capital accounts accounts
        if self.repo.capital:
            self.repo.capital.current_capital = self.repo.capital.starting_capital + sum(
                float(pos.mtm if hasattr(pos, "mtm") else 0.0) for pos in self.repo.positions.values()
            )
            self.repo.capital.available_margin = self.repo.capital.current_capital
            self.repo.capital.updated_at = now_ist()
            
        rec = self.reconciliation.fill_received(order, fill)
        
        await self.bus.publish("fill-updates", fill.model_dump(mode="json"))
        await self.bus.publish("pnl-updates", position.model_dump(mode="json"))
        await self.bus.publish("order-updates", order.model_dump(mode="json"))
        await self.bus.publish("reconciliation-events", rec.model_dump(mode="json"))
        logger.info(f"Order {order.id} completely filled via [{execution_mode}] entry criteria at price: {fill_price}")