"""Technical dashboard: candles + indicator overlays/oscillators, patterns, S/R, multi-timeframe trend."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

import pandas as pd

from algo_common.schemas.market import Interval
from algo_common.timeutils import utcnow
from market_data.base import MarketDataProvider
from strategy_engine import indicators as ind
from strategy_engine.data import candles_to_frame
from strategy_engine.patterns import scan_patterns, support_resistance

LOOKBACK_DAYS = {"1m": 3, "3m": 5, "5m": 10, "15m": 30, "30m": 60, "1h": 120, "1d": 730, "1w": 2500}


def _series(s: pd.Series) -> list[dict[str, Any]]:
    return [{"ts": ts.isoformat(), "value": None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v), 4)}
            for ts, v in s.items()]


async def frame_for(provider: MarketDataProvider, symbol: str, interval: str, days: int | None = None) -> pd.DataFrame:
    end = utcnow()
    candles = await provider.candles(symbol, Interval(interval), end - timedelta(days=days or LOOKBACK_DAYS.get(interval, 365)), end)
    return candles_to_frame(candles)


def trend_summary(df: pd.DataFrame) -> dict[str, Any]:
    if len(df) < 60:
        return {"trend": "insufficient data"}
    close = df["close"]
    e20, e50 = ind.ema(df, period=20).iloc[-1], ind.ema(df, period=50).iloc[-1]
    rsi = ind.rsi(df).iloc[-1]
    adx = ind.adx(df)["adx"].iloc[-1]
    st = ind.supertrend(df)["direction"].iloc[-1]
    score = (1 if close.iloc[-1] > e20 else -1) + (1 if e20 > e50 else -1) + (1 if st == 1 else -1)
    trend = "bullish" if score >= 2 else "bearish" if score <= -2 else "neutral"
    return {"trend": trend, "score": int(score), "close": round(float(close.iloc[-1]), 2), "ema20": round(float(e20), 2),
            "ema50": round(float(e50), 2), "rsi": round(float(rsi), 1), "adx": round(float(adx), 1),
            "supertrend": "up" if st == 1 else "down"}


async def technical_dashboard(provider: MarketDataProvider, symbol: str, interval: str, indicators: list[str]) -> dict[str, Any]:
    df = await frame_for(provider, symbol, interval)
    if df.empty:
        raise ValueError(f"no data for {symbol}")
    overlays: list[dict[str, Any]] = []
    oscillators: list[dict[str, Any]] = []
    for spec in indicators:
        kind, _, arg = spec.partition(":")
        kind = kind.upper()
        if kind not in ind.REGISTRY:
            continue
        d = ind.REGISTRY[kind]
        params = {}
        if arg and d.params:
            first = next(iter(d.params))
            params[first] = float(arg) if "." in arg else int(arg)
        res = ind.compute(df, kind, params)
        label = f"{kind}({arg})" if arg else kind
        for col in res.columns:
            entry = {"id": f"{label}.{col}" if len(res.columns) > 1 else label, "kind": kind, "output": col, "series": _series(res[col])}
            (overlays if d.overlay else oscillators).append(entry)
    mtf = {}
    for tf in ("15m", "1h", "1d"):
        f = df if tf == interval else await frame_for(provider, symbol, tf)
        mtf[tf] = trend_summary(f)
    return {
        "symbol": symbol, "interval": interval,
        "candles": [{"ts": ts.isoformat(), "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume}
                    for ts, r in df.iterrows()],
        "overlays": overlays, "oscillators": oscillators,
        "patterns": scan_patterns(df, last_n=60), "levels": support_resistance(df.tail(300)),
        "mtf": mtf, "summary": trend_summary(df),
    }
