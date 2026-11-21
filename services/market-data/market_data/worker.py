"""Market data worker:  python -m market_data.worker

* live tick fan-out (provider stream -> Redis pub/sub)
* daily instrument master refresh
* end-of-day candle ingestion for the reference universe
* periodic option chain snapshots for index underlyings (market hours)
"""

from __future__ import annotations

import asyncio
import signal
from datetime import time

from algo_common.logging import configure_logging, get_logger
from algo_common.schemas.market import Interval
from algo_common.settings import get_settings
from algo_common.timeutils import is_market_open, is_trading_day, now_ist
from algo_db.session import session_scope
from market_data.ingestion import ingest_candles, refresh_instruments, snapshot_option_chain
from market_data.registry import get_provider
from market_data.streamer import TickStreamer, set_streamer
from market_data.universe import UNIVERSES

log = get_logger("market_data.worker")
CHAIN_UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]


async def instruments_loop() -> None:
    provider = get_provider()
    while True:
        try:
            async with session_scope() as db:
                await refresh_instruments(db, provider)
        except Exception as exc:
            log.warning("worker.instruments_failed", error=str(exc))
        await asyncio.sleep(6 * 3600)


async def eod_ingestion_loop() -> None:
    provider = get_provider()
    done_for: set = set()
    while True:
        now = now_ist()
        if is_trading_day(now.date()) and now.time() >= time(16, 0) and now.date() not in done_for:
            symbols = UNIVERSES["NIFTY100"] + ["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY", "BSE_INDEX:SENSEX"]
            async with session_scope() as db:
                daily = await ingest_candles(db, provider, symbols, Interval.D1, 10)
                minute = await ingest_candles(db, provider, symbols[:30], Interval.M1, 1)
            log.info("worker.eod_ingested", daily=sum(daily.values()), minute=sum(minute.values()))
            done_for.add(now.date())
        await asyncio.sleep(300)


async def chain_snapshot_loop(every_s: int = 300) -> None:
    provider = get_provider()
    while True:
        if is_market_open(now_ist()):
            for und in CHAIN_UNDERLYINGS:
                try:
                    chain = await provider.option_chain(und, None, 25)
                    async with session_scope() as db:
                        await snapshot_option_chain(db, chain)
                except Exception as exc:
                    log.warning("worker.chain_snapshot_failed", underlying=und, error=str(exc))
        await asyncio.sleep(every_s)


async def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json, service="market-data")
    provider = get_provider()
    streamer = TickStreamer(provider)
    set_streamer(streamer)
    tasks = [
        asyncio.create_task(streamer.run(), name="streamer"),
        asyncio.create_task(instruments_loop(), name="instruments"),
        asyncio.create_task(eod_ingestion_loop(), name="eod"),
        asyncio.create_task(chain_snapshot_loop(), name="chains"),
    ]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C raises KeyboardInterrupt instead
            pass
    await stop.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
