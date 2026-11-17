"""Aggregate live ticks into OHLCV bars aligned to the IST session (09:15)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from algo_common.timeutils import IST

TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 375}


@dataclass
class Bar:
    ts: datetime  # bar open time (IST aware)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class BarBuilder:
    def __init__(self, timeframe: str) -> None:
        self.minutes = TF_MINUTES[timeframe]
        self.current: Bar | None = None
        self._last_cum_vol: float | None = None

    def bucket_start(self, ts: datetime) -> datetime:
        t = ts.astimezone(IST)
        session = t.replace(hour=9, minute=15, second=0, microsecond=0)
        if self.minutes >= 375 or t < session:
            return session
        k = int((t - session).total_seconds() // 60) // self.minutes
        return session + timedelta(minutes=k * self.minutes)

    def bucket_end(self, start: datetime) -> datetime:
        if self.minutes >= 375:
            return start.replace(hour=15, minute=30)
        return start + timedelta(minutes=self.minutes)

    def on_tick(self, ts: datetime, price: float, cum_volume: float | None = None) -> Bar | None:
        """Feed a tick; returns the *completed* bar when the tick opens a new bucket."""
        vol = 0.0
        if cum_volume is not None:
            if self._last_cum_vol is not None and cum_volume >= self._last_cum_vol:
                vol = cum_volume - self._last_cum_vol
            self._last_cum_vol = cum_volume
        start = self.bucket_start(ts)
        done = None
        if self.current is not None and start > self.current.ts:
            done = self.current
            self.current = None
        if self.current is None:
            self.current = Bar(start, price, price, price, price, vol)
        else:
            c = self.current
            c.high, c.low, c.close = max(c.high, price), min(c.low, price), price
            c.volume += vol
        return done

    def flush_if_due(self, now: datetime) -> Bar | None:
        """Close the current bar once wall-clock passes its end (quiet markets)."""
        if self.current is not None and now.astimezone(IST) >= self.bucket_end(self.current.ts):
            done, self.current = self.current, None
            return done
        return None
