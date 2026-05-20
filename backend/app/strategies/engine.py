import asyncio
import logging
from contextlib import suppress
from typing import Any, Callable, Awaitable

from app.core.time import now_ist
from app.data.repository import Repository
from app.models.schemas import MarketTick, StrategyRun, Signal, Candle
from app.services.event_bus import EventBus
from app.strategies.base import StrategyContext
from app.strategies.loader import StrategyLoader

logger = logging.getLogger(__name__)

class StrategyEngine:
    def __init__(self, repo: Repository, bus: EventBus) -> None:
        self.repo = repo
        self.bus = bus
        self.loader = StrategyLoader()
        self.instances: dict[str, Any] = {}
        self.contexts: dict[str, StrategyContext] = {}
        # Unified tracking queue capable of handling sequential timeline components safely
        self.queues: dict[str, asyncio.Queue[MarketTick | Candle]] = {}
        self.worker_tasks: dict[str, asyncio.Task[Any]] = {}
        
        self.signal_handler: Callable[[Signal], Awaitable[Any]] | None = None
        self.MAX_QUEUE_SIZE = 1000 

    async def register_discovered(self, root) -> None:
        for definition in self.loader.discover(root):
            self.repo.strategies[definition.id] = definition

    async def start_strategy(self, strategy_id: str) -> StrategyRun:
        definition = self.repo.strategies[strategy_id]
        instance = self.loader.load(definition.file_path)
        
        context = StrategyContext(
            strategy_id=strategy_id,
            config=definition.config,
            market_cache=self.repo.ticks,
            positions=self.repo.positions,
            open_orders=self.repo.orders,
            risk_limits={},
        )
        
        if hasattr(instance, "initialize"):
            instance.initialize(context)
            
        self.instances[strategy_id] = instance
        self.contexts[strategy_id] = context
        
        self.queues[strategy_id] = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self.worker_tasks[strategy_id] = asyncio.create_task(self._strategy_worker(strategy_id))
        
        run = StrategyRun(strategy_id=strategy_id, status="running", started_at=now_ist())
        self.repo.runs[run.id] = run
        
        await self.bus.publish("strategy-events", {"event": "strategy_started", "strategy_id": strategy_id})
        logger.info(f"Successfully launched consolidated event worker loop for strategy: {strategy_id}")
        return run

    async def stop_strategy(self, strategy_id: str) -> None:
        task = self.worker_tasks.pop(strategy_id, None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
                
        self.queues.pop(strategy_id, None)
        instance = self.instances.pop(strategy_id, None)
        context = self.contexts.pop(strategy_id, None)
        
        if instance and context and hasattr(instance, "shutdown"):
            instance.shutdown(context)
            
        for run in self.repo.runs.values():
            if run.strategy_id == strategy_id and run.status == "running":
                run.status = "stopped"
                run.stopped_at = now_ist()
                
        await self.bus.publish("strategy-events", {"event": "strategy_stopped", "strategy_id": strategy_id})

    async def on_tick(self, tick: MarketTick) -> None:
        """Routes live market ticks to individual strategy worker tasks synchronously."""
        await self._push_to_queues(tick)

    async def on_candle(self, candle: Candle) -> None:
        """Routes consolidated time bars to individual strategy worker tasks synchronously."""
        await self._push_to_queues(candle)

    async def _push_to_queues(self, item: MarketTick | Candle) -> None:
        for strategy_id, queue in list(self.queues.items()):
            if queue.full():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except (asyncio.QueueEmpty, ValueError):
                    pass
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                logger.warning(f"Queue congestion dropped feed update for strategy {strategy_id}")

    async def _strategy_worker(self, strategy_id: str) -> None:
        """Unified consumer loop running continuously per running plugin."""
        queue = self.queues[strategy_id]
        
        while True:
            try:
                event_item = await queue.get()
                instance = self.instances.get(strategy_id)
                context = self.contexts.get(strategy_id)
                
                if not instance or not context:
                    queue.task_done()
                    continue
                
                try:
                    # Precise Type-Narrowing check for Pyright static analysis safety
                    if isinstance(event_item, MarketTick):
                        if hasattr(instance, "on_market_data"):
                            instance.on_market_data(event_item, context)
                    elif isinstance(event_item, Candle):
                        if hasattr(instance, "on_bar"):
                            instance.on_bar(event_item, context)
                        
                    if hasattr(instance, "generate_signal"):
                        signal = instance.generate_signal(context)
                        if signal:
                            signal.strategy_id = strategy_id
                            self.repo.signals[signal.id] = signal
                            await self.bus.publish(
                                "strategy-events", 
                                {"event": "signal_created", "signal": signal.model_dump(mode="json")}
                            )
                            if self.signal_handler is not None:
                                await self.signal_handler(signal)
                except Exception as eval_ex:
                    error_msg = f"Runtime exception inside strategy engine worker: {str(eval_ex)}"
                    context.log(error_msg)
                    logger.error(error_msg, exc_info=True)
                finally:
                    queue.task_done()
                    
            except asyncio.CancelledError:
                break