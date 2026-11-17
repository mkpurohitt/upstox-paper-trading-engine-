"""Historical data loading for backtests (DB first, provider fallback)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from algo_common.schemas.market import Candle, Interval
from market_data.base import MarketDataProvider

MAX_INTRADAY_DAYS = {"1m": 60, "3m": 120, "5m": 200, "15m": 400, "30m": 600, "1h": 900}


def candles_to_frame(candles: list[Candle]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([], tz="UTC"))
    df = pd.DataFrame([c.model_dump() for c in candles])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close", "volume"] + (["oi"] if "oi" in df else [])].astype(float)


def clamp_range(interval: str, start: datetime, end: datetime) -> tuple[datetime, datetime, str | None]:
    limit = MAX_INTRADAY_DAYS.get(interval)
    if limit and (end - start).days > limit:
        return end - timedelta(days=limit), end, f"Intraday ({interval}) backtests are limited to {limit} days; range clipped."
    return start, end, None


async def load_frames(
    provider: MarketDataProvider, symbols: list[str], interval: str, start: datetime, end: datetime,
    session=None,  # type: ignore[no-untyped-def]
) -> dict[str, pd.DataFrame]:
    iv = Interval(interval)
    out: dict[str, pd.DataFrame] = {}
    for s in symbols:
        candles: list[Candle] = []
        if session is not None:
            from market_data.ingestion import load_candles

            candles = await load_candles(session, s, iv, start, end)
            # use stored data only when it covers the requested range reasonably
            if candles and (candles[0].ts - start).days > 7:
                candles = []
        if not candles:
            candles = await provider.candles(s, iv, start, end)
        out[s] = candles_to_frame(candles)
    return out
