"""Chart timeframes: parsing, the base interval to fetch, and session-aligned resampling.

Timeframes use chart notation: minutes as numbers ("1", "3", "45", "120", "240"), "D" (day), "W" (week, starting
Monday) and "M" (calendar month). Providers serve a fixed set of base intervals (1m, 3m, 5m, 15m, 30m, 1h, 1d); any
other timeframe is built from the largest base interval that divides it. Intraday buckets are aligned to the
exchange session open (09:15 IST for NSE/BSE, 09:00 for MCX), the way Indian brokers and charting tools draw them,
so a 1-hour bar runs 09:15-10:15 and a 45-minute bar 09:15-10:00.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from algo_common.schemas.market import Candle, Interval
from algo_common.timeutils import IST

MINUTE_BASES: tuple[tuple[int, Interval], ...] = (
    (60, Interval.H1), (30, Interval.M30), (15, Interval.M15), (5, Interval.M5), (3, Interval.M3), (1, Interval.M1),
)
MAX_INTRADAY_MINUTES = 375  # one NSE session
SESSION_MINUTES = {"NSE": 375, "BSE": 375, "MCX": 870}


@dataclass(frozen=True)
class Timeframe:
    code: str  # "5", "60", "D", "W", "M"
    unit: str  # "min" | "D" | "W" | "M"
    minutes: int = 0

    @property
    def intraday(self) -> bool:
        return self.unit == "min"

    @property
    def base(self) -> Interval:
        if self.unit != "min":
            return Interval.D1
        for size, iv in MINUTE_BASES:
            if self.minutes % size == 0:
                return iv
        return Interval.M1

    @property
    def label(self) -> str:
        if self.unit == "D":
            return "1D"
        if self.unit == "W":
            return "1W"
        if self.unit == "M":
            return "1M"
        return f"{self.minutes // 60}h" if self.minutes % 60 == 0 else f"{self.minutes}m"


def parse_timeframe(code: str) -> Timeframe:
    c = code.strip().upper()
    aliases = {"1D": "D", "1W": "W", "1M": "M", "DAY": "D", "WEEK": "W", "MONTH": "M"}
    c = aliases.get(c, c)
    if c in ("D", "W", "M"):
        return Timeframe(c, c)
    if c.endswith("H") and c[:-1].isdigit():
        c = str(int(c[:-1]) * 60)
    elif c.endswith("MIN") and c[:-3].isdigit():
        c = c[:-3]
    if not c.isdigit():
        raise ValueError(f"unknown timeframe '{code}' (use minutes such as 5 or 60, or D, W, M)")
    m = int(c)
    if not 1 <= m <= MAX_INTRADAY_MINUTES:
        raise ValueError(f"intraday timeframe must be 1-{MAX_INTRADAY_MINUTES} minutes")
    return Timeframe(str(m), "min", m)


def session_open(exchange: str) -> time:
    return time(9, 0) if exchange.upper().startswith("MCX") else time(9, 15)


def exchange_of(symbol: str) -> str:
    ex = symbol.split(":", 1)[0].upper()
    if ex.startswith("MCX"):
        return "MCX"
    if ex.startswith("BSE") or ex == "BFO":
        return "BSE"
    return "NSE"


def bucket_start(ts: datetime, tf: Timeframe, exchange: str = "NSE") -> datetime:
    """Start (IST) of the bar containing `ts`."""
    t = ts.astimezone(IST)
    if tf.unit == "D":
        return datetime.combine(t.date(), time(0), tzinfo=IST)
    if tf.unit == "W":
        d = t.date() - timedelta(days=t.weekday())
        return datetime.combine(d, time(0), tzinfo=IST)
    if tf.unit == "M":
        return datetime.combine(date(t.year, t.month, 1), time(0), tzinfo=IST)
    open_ = datetime.combine(t.date(), session_open(exchange), tzinfo=IST)
    mins = (t - open_).total_seconds() / 60
    if mins < 0:  # pre-open prints belong to the first bar
        return open_
    return open_ + timedelta(minutes=math.floor(mins / tf.minutes) * tf.minutes)


def resample(candles: list[Candle], tf: Timeframe, exchange: str = "NSE") -> list[Candle]:
    """Aggregate base candles (sorted) into `tf` bars. Weekly/monthly bars are stamped with the date of their first
    trading day, so they line up with the daily bars they contain."""
    if not candles:
        return []
    out: list[Candle] = []
    cur_key: datetime | None = None
    for c in candles:
        key = bucket_start(c.ts, tf, exchange)
        if cur_key is None or key != cur_key:
            stamp = key if tf.intraday else c.ts  # first trading day of the week/month for W/M; the day itself for D
            out.append(Candle(ts=stamp.astimezone(c.ts.tzinfo or IST), open=c.open, high=c.high, low=c.low, close=c.close,
                              volume=c.volume or 0.0, oi=c.oi))
            cur_key = key
        else:
            b = out[-1]
            out[-1] = b.model_copy(update={
                "high": max(b.high, c.high), "low": min(b.low, c.low), "close": c.close,
                "volume": (b.volume or 0.0) + (c.volume or 0.0), "oi": c.oi if c.oi is not None else b.oi,
            })
    return out


def lookback(tf: Timeframe, count: int, exchange: str = "NSE") -> timedelta:
    """Calendar span that comfortably holds `count` bars (weekends and holidays included)."""
    if tf.unit == "D":
        return timedelta(days=int(count * 1.5) + 10)
    if tf.unit == "W":
        return timedelta(days=count * 7 + 14)
    if tf.unit == "M":
        return timedelta(days=count * 31 + 62)
    per_day = max(1, SESSION_MINUTES.get(exchange, 375) // tf.minutes)
    trading_days = math.ceil(count / per_day)
    return timedelta(days=math.ceil(trading_days * 1.5) + 4)
