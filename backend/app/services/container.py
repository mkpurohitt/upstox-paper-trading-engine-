from pathlib import Path

from app.core.config import get_settings
from app.data.repository import repo
from app.execution.oms import PaperOMS
from app.execution.upstox_sandbox import UpstoxSandboxExecutionAdapter
from app.market.feed import MarketDataService
from app.market.instruments import InstrumentMasterService
from app.market.live_quote import LiveQuotePollingService
from app.market.upstox_client import UpstoxClient
from app.market.upstox_ws import UpstoxMarketWebSocket
from app.reconciliation.engine import ReconciliationEngine
from app.rms.engine import RmsEngine
from app.services.event_bus import event_bus
from app.strategies.engine import StrategyEngine


class ServiceContainer:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.market_data = MarketDataService(repo, event_bus, self.settings.default_instrument_list)
        self.instruments = InstrumentMasterService(self.settings)
        self.strategy_engine = StrategyEngine(repo, event_bus)
        self.rms = RmsEngine(self.settings, repo)
        self.reconciliation = ReconciliationEngine(repo)
        self.execution_adapter = UpstoxSandboxExecutionAdapter(self.settings)
        self.oms = PaperOMS(repo, event_bus, self.rms, self.reconciliation, self.execution_adapter)
        
        # Establish operational pipelines across core boundaries
        self.strategy_engine.signal_handler = self.oms.route_signal
        
        # 1. Wire live ticks into the Strategy Engine queue
        self.market_data.tick_handlers.append(self.strategy_engine.on_tick)
        # 2. Wire live ticks to run the asynchronous Order Matching Engine simulation logic
        self.market_data.tick_handlers.append(self.oms.on_market_tick)
        # 3. Wire time bars/candles into the Strategy Engine queue
        self.market_data.candle_handlers.append(self.strategy_engine.on_candle)
        
        self.upstox_client = UpstoxClient(self.settings)
        self.upstox_ws = UpstoxMarketWebSocket(self.upstox_client, self.market_data.ingest_tick)
        self.live_quote = LiveQuotePollingService(self.settings, self.upstox_client, self.market_data.ingest_tick)
        self._upstox_ws_task = None
        self.startup_warnings: list[str] = []

    async def startup(self) -> None:
        repo.ensure_capital(self.settings.base_capital)
        if self.settings.download_instruments_on_start:
            try:
                await self.instruments.refresh()
            except Exception as exc:
                self.startup_warnings.append(f"Instrument download failed: {exc}")
        strategy_root = Path(__file__).resolve().parents[3] / "strategies" / "sample_strategies"
        await self.strategy_engine.register_discovered(strategy_root)
        if self.settings.enable_live_upstox_ws:
            import asyncio

            self._upstox_ws_task = asyncio.create_task(self.upstox_ws.run_forever())
        else:
            await self.market_data.start()
        if self.settings.enable_live_quote_polling:
            await self.live_quote.start()

    async def shutdown(self) -> None:
        await self.live_quote.stop()
        await self.upstox_ws.stop()
        if self._upstox_ws_task:
            self._upstox_ws_task.cancel()
        await self.market_data.stop()


services = ServiceContainer()