"""Chart timeframes / resampling and the hot-swappable provider proxy."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from algo_common.schemas.market import Candle, Interval, Tick
from algo_common.timeutils import IST
from market_data import registry
from market_data.bars import bucket_start, exchange_of, lookback, parse_timeframe, resample
from market_data.mock import MockProvider


def test_parse_timeframe():
    assert parse_timeframe("5").minutes == 5 and parse_timeframe("5").base == Interval.M5
    assert parse_timeframe("45").base == Interval.M15
    assert parse_timeframe("2h").minutes == 120 and parse_timeframe("120").base == Interval.H1
    assert parse_timeframe("10").base == Interval.M5 and parse_timeframe("7").base == Interval.M1
    assert parse_timeframe("1D").unit == "D" and parse_timeframe("w").unit == "W" and parse_timeframe("M").unit == "M"
    assert parse_timeframe("240").label == "4h" and parse_timeframe("45").label == "45m"
    for bad in ("0", "400", "abc", "-5"):
        with pytest.raises(ValueError):
            parse_timeframe(bad)


def test_buckets_align_to_session_open():
    at = datetime(2026, 11, 20, 10, 20, tzinfo=IST)
    assert bucket_start(at, parse_timeframe("60")).strftime("%H:%M") == "10:15"
    assert bucket_start(at, parse_timeframe("45")).strftime("%H:%M") == "10:00"
    assert bucket_start(at, parse_timeframe("240")).strftime("%H:%M") == "09:15"
    assert bucket_start(datetime(2026, 11, 20, 13, 20, tzinfo=IST), parse_timeframe("240")).strftime("%H:%M") == "13:15"
    assert bucket_start(at, parse_timeframe("60"), "MCX").strftime("%H:%M") == "10:00"  # MCX opens 09:00
    assert bucket_start(datetime(2026, 11, 20, 9, 7, tzinfo=IST), parse_timeframe("15")).strftime("%H:%M") == "09:15"
    assert bucket_start(at, parse_timeframe("W")).date().isoformat() == "2026-11-16"  # Monday
    assert bucket_start(at, parse_timeframe("M")).date().isoformat() == "2026-11-01"
    assert exchange_of("MCX:CRUDEOIL") == "MCX" and exchange_of("BSE:TCS") == "BSE" and exchange_of("NSE_INDEX:NIFTY") == "NSE"


def _minute_bars(day: str, n: int, start_px: float = 100.0) -> list[Candle]:
    t0 = datetime.fromisoformat(f"{day}T09:15:00+05:30")
    out = []
    for i in range(n):
        o = start_px + i
        out.append(Candle(ts=(t0 + timedelta(minutes=i)).astimezone(UTC), open=o, high=o + 2, low=o - 1, close=o + 1, volume=10))
    return out


def test_resample_ohlcv():
    bars = resample(_minute_bars("2026-11-20", 90), parse_timeframe("30"))
    assert len(bars) == 3
    first = bars[0]
    assert first.open == 100 and first.close == 130 and first.high == 131 and first.low == 99 and first.volume == 300
    assert first.ts.astimezone(IST).strftime("%H:%M") == "09:15" and bars[1].ts.astimezone(IST).strftime("%H:%M") == "09:45"


def test_resample_weekly_and_monthly_stamp_first_trading_day():
    days = [datetime(2026, 10, d, 9, 15, tzinfo=IST) for d in (29, 30)] + [datetime(2026, 11, d, 9, 15, tzinfo=IST) for d in (2, 3, 4, 6, 9)]
    daily = [Candle(ts=t.astimezone(UTC), open=10 + i, high=20 + i, low=5, close=11 + i, volume=1) for i, t in enumerate(days)]
    weekly = resample(daily, parse_timeframe("W"))
    assert [b.ts.astimezone(IST).date().isoformat() for b in weekly] == ["2026-10-29", "2026-11-02", "2026-11-09"]
    assert weekly[1].open == 12 and weekly[1].close == 16 and weekly[1].high == 25 and weekly[1].volume == 4
    monthly = resample(daily, parse_timeframe("M"))
    assert [b.ts.astimezone(IST).date().isoformat() for b in monthly] == ["2026-10-29", "2026-11-02"]


def test_lookback_covers_requested_bars():
    assert lookback(parse_timeframe("5"), 750).days >= 10  # 75 bars/day -> 10 trading days
    assert lookback(parse_timeframe("D"), 300).days >= 420
    assert lookback(parse_timeframe("M"), 24).days >= 24 * 30


class _Fake(MockProvider):
    def __init__(self, label: str, price: float) -> None:
        super().__init__()
        self.label, self.price = label, price
        self.name = label

    async def stream(self, demand) -> AsyncIterator[list[Tick]]:  # type: ignore[override]
        while True:
            yield [Tick(symbol="NSE:TEST", ts=datetime.now(UTC), ltp=self.price)]
            await asyncio.sleep(0.01)


def test_proxy_switches_provider_and_stream_without_restart():
    async def scenario() -> list[float]:
        a, b = _Fake("a", 1.0), _Fake("b", 2.0)
        registry.set_provider(a)
        proxy = registry.get_provider()
        assert proxy.name == "a"
        seen: list[float] = []
        gen = proxy.stream(lambda: {"NSE:TEST"}).__aiter__()
        seen.append((await gen.__anext__())[0].ltp)
        registry.set_provider(b)  # e.g. an admin pasted a new Upstox token
        assert proxy.name == "b"
        for _ in range(5):
            seen.append((await gen.__anext__())[0].ltp)
        await gen.aclose()
        return seen

    try:
        seen = asyncio.run(scenario())
    finally:
        registry.set_provider(None)
    assert seen[0] == 1.0 and seen[-1] == 2.0 and seen.count(2.0) >= 4
    assert registry.get_provider().name == "mock"
