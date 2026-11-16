"""Persist market data into Postgres/TimescaleDB (or SQLite in dev-lite)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.logging import get_logger
from algo_common.schemas.market import Candle, Instrument, Interval, OptionChain
from algo_common.timeutils import utcnow
from algo_db.models import CandleRow, InstrumentRow, OptionChainSnapshot
from market_data.base import MarketDataProvider

log = get_logger("ingestion")
_AGG = {Interval.M5: "candles_5m", Interval.M15: "candles_15m", Interval.H1: "candles_1h", Interval.D1: "candles_1d"}


async def _upsert(session: AsyncSession, model: type, rows: list[dict], keys: list[str]) -> None:
    if not rows:
        return
    dialect = session.bind.dialect.name if session.bind else "postgresql"
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        for i in range(0, len(rows), 2000):
            stmt = pg_insert(model).values(rows[i : i + 2000])
            cols = {c: stmt.excluded[c] for c in rows[0] if c not in keys}
            await session.execute(stmt.on_conflict_do_update(index_elements=keys, set_=cols))
    else:
        from sqlalchemy.dialects.sqlite import insert as sq_insert

        for i in range(0, len(rows), 500):
            stmt = sq_insert(model).values(rows[i : i + 500])
            cols = {c: stmt.excluded[c] for c in rows[0] if c not in keys}
            await session.execute(stmt.on_conflict_do_update(index_elements=keys, set_=cols))


async def store_candles(session: AsyncSession, symbol: str, interval: Interval, candles: Iterable[Candle]) -> int:
    rows = [
        {"symbol": symbol, "interval": interval.value, "ts": c.ts, "open": c.open, "high": c.high, "low": c.low,
         "close": c.close, "volume": c.volume, "oi": c.oi}
        for c in candles
    ]
    await _upsert(session, CandleRow, rows, ["symbol", "interval", "ts"])
    return len(rows)


async def ingest_candles(
    session: AsyncSession, provider: MarketDataProvider, symbols: list[str], interval: Interval, days: int
) -> dict[str, int]:
    end = utcnow()
    start = end - timedelta(days=days)
    out: dict[str, int] = {}
    for s in symbols:
        try:
            out[s] = await store_candles(session, s, interval, await provider.candles(s, interval, start, end))
        except Exception as exc:
            log.warning("ingestion.candles_failed", symbol=s, error=str(exc))
            out[s] = 0
    return out


async def load_candles(
    session: AsyncSession, symbol: str, interval: Interval, start: datetime, end: datetime
) -> list[Candle]:
    """Read candles from the DB, using Timescale continuous aggregates when present."""
    dialect = session.bind.dialect.name if session.bind else ""
    view = _AGG.get(interval)
    if dialect == "postgresql" and view:
        exists = (await session.execute(text("SELECT to_regclass(:v)"), {"v": view})).scalar()
        if exists:
            rows = await session.execute(
                text(f"SELECT ts, open, high, low, close, volume, oi FROM {view} "
                     "WHERE symbol = :s AND ts BETWEEN :a AND :b ORDER BY ts"),
                {"s": symbol, "a": start, "b": end},
            )
            return [Candle(ts=r.ts, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume or 0, oi=r.oi)
                    for r in rows]
    q = (
        select(CandleRow)
        .where(CandleRow.symbol == symbol, CandleRow.interval == interval.value, CandleRow.ts.between(start, end))
        .order_by(CandleRow.ts)
    )
    return [Candle.model_validate(r) for r in (await session.execute(q)).scalars()]


async def refresh_instruments(session: AsyncSession, provider: MarketDataProvider) -> int:
    items: list[Instrument] = await provider.instruments()
    now = utcnow()
    rows = [
        {"symbol": i.symbol, "instrument_key": i.instrument_key, "exchange": i.exchange.value, "segment": i.segment,
         "tradingsymbol": i.tradingsymbol, "name": i.name[:200], "instrument_type": i.instrument_type.value,
         "underlying": i.underlying, "expiry": i.expiry, "strike": i.strike, "lot_size": i.lot_size,
         "tick_size": i.tick_size, "freeze_qty": i.freeze_qty, "isin": i.isin, "sector": i.sector,
         "industry": i.industry, "market_cap_cr": i.market_cap_cr, "broker_tokens": {provider.name: i.instrument_key},
         "updated_at": now}
        for i in items
    ]
    await _upsert(session, InstrumentRow, rows, ["symbol"])
    # drop expired contracts
    await session.execute(delete(InstrumentRow).where(InstrumentRow.expiry < (now - timedelta(days=3)).date()))
    log.info("ingestion.instruments_refreshed", count=len(rows))
    return len(rows)


async def snapshot_option_chain(session: AsyncSession, chain: OptionChain) -> int:
    rows = []
    for r in chain.rows:
        for leg, opt in ((r.call, "CE"), (r.put, "PE")):
            if leg is None:
                continue
            rows.append({
                "underlying": chain.underlying, "expiry": chain.expiry, "strike": r.strike, "option_type": opt,
                "ts": chain.ts, "spot": chain.spot, "ltp": leg.ltp, "bid": leg.bid, "ask": leg.ask, "iv": leg.iv,
                "delta": leg.greeks.delta, "gamma": leg.greeks.gamma, "theta": leg.greeks.theta,
                "vega": leg.greeks.vega, "oi": leg.oi, "volume": leg.volume,
            })
    await _upsert(session, OptionChainSnapshot, rows, ["underlying", "expiry", "strike", "option_type", "ts"])
    return len(rows)
