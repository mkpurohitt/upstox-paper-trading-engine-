from app.core.time import now_ist
from app.data.repository import Repository
from app.models.schemas import MarketTick, StrategyRun
from app.services.event_bus import EventBus
from app.strategies.base import StrategyContext
from app.strategies.loader import StrategyLoader


class StrategyEngine:
    def __init__(self, repo: Repository, bus: EventBus) -> None:
        self.repo = repo
        self.bus = bus
        self.loader = StrategyLoader()
        self.instances: dict[str, object] = {}
        self.contexts: dict[str, StrategyContext] = {}
        self.signal_handler = None

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
        run = StrategyRun(strategy_id=strategy_id, status="running", started_at=now_ist())
        self.repo.runs[run.id] = run
        await self.bus.publish("strategy-events", {"event": "strategy_started", "strategy_id": strategy_id})
        return run

    async def stop_strategy(self, strategy_id: str) -> None:
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
        for strategy_id, instance in list(self.instances.items()):
            context = self.contexts[strategy_id]
            if hasattr(instance, "on_market_data"):
                instance.on_market_data(tick, context)
            signal = instance.generate_signal(context) if hasattr(instance, "generate_signal") else None
            if signal:
                signal.strategy_id = strategy_id
                self.repo.signals[signal.id] = signal
                await self.bus.publish("strategy-events", {"event": "signal_created", "signal": signal.model_dump(mode="json")})
                if self.signal_handler:
                    await self.signal_handler(signal)
