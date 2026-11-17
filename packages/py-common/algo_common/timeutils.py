"""India market time helpers (IST, sessions, expiry calendars)."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

NSE_OPEN = time(9, 15)
NSE_CLOSE = time(15, 30)
MCX_OPEN = time(9, 0)
MCX_CLOSE = time(23, 30)

# Approximate exchange holidays used in mock mode. Live mode pulls the
# authoritative list from the market data provider.
MOCK_HOLIDAYS: set[date] = {
    date(2026, 1, 26), date(2026, 3, 3), date(2026, 3, 26), date(2026, 3, 31), date(2026, 4, 3),
    date(2026, 4, 14), date(2026, 5, 1), date(2026, 5, 28), date(2026, 6, 26), date(2026, 9, 14),
    date(2026, 10, 2), date(2026, 10, 20), date(2026, 11, 10), date(2026, 11, 24), date(2026, 12, 25),
    date(2025, 2, 26), date(2025, 3, 14), date(2025, 3, 31), date(2025, 4, 10), date(2025, 4, 14),
    date(2025, 4, 18), date(2025, 5, 1), date(2025, 8, 15), date(2025, 8, 27), date(2025, 10, 2),
    date(2025, 10, 21), date(2025, 10, 22), date(2025, 11, 5), date(2025, 12, 25),
}


def now_ist() -> datetime:
    return datetime.now(tz=IST)


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def is_trading_day(d: date, holidays: set[date] | None = None) -> bool:
    hol = MOCK_HOLIDAYS if holidays is None else holidays
    return d.weekday() < 5 and d not in hol


def previous_trading_day(d: date, holidays: set[date] | None = None) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d, holidays):
        d -= timedelta(days=1)
    return d


def trading_days(start: date, end: date, holidays: set[date] | None = None) -> list[date]:
    out: list[date] = []
    d = start
    while d <= end:
        if is_trading_day(d, holidays):
            out.append(d)
        d += timedelta(days=1)
    return out


def is_market_open(at: datetime | None = None, exchange: str = "NSE") -> bool:
    at = to_ist(at or utcnow())
    if not is_trading_day(at.date()):
        return False
    t = at.time()
    if exchange.upper().startswith("MCX"):
        return MCX_OPEN <= t <= MCX_CLOSE
    return NSE_OPEN <= t <= NSE_CLOSE


def _adjust_back_for_holiday(d: date, holidays: set[date] | None = None) -> date:
    while not is_trading_day(d, holidays):
        d -= timedelta(days=1)
    return d


def last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


# Since Sep-2025: NSE derivatives expire on Tuesday, BSE on Thursday. Only NIFTY
# (NSE) and SENSEX (BSE) retain weekly expiries; other index and stock
# derivatives expire monthly (last Tuesday/Thursday of the month).
EXPIRY_WEEKDAY = {"NSE": 1, "NFO": 1, "BSE": 3, "BFO": 3, "MCX": 3}
WEEKLY_UNDERLYINGS = {"NIFTY", "SENSEX"}


def monthly_expiry(year: int, month: int, exchange: str = "NSE") -> date:
    wd = EXPIRY_WEEKDAY.get(exchange.upper(), 1)
    return _adjust_back_for_holiday(last_weekday_of_month(year, month, wd))


def expiry_from_date(at: datetime, exchange: str = "NSE") -> date:
    """First date whose contracts are still alive at `at`: expiring contracts stop trading at the close
    (15:30 IST for NSE/BSE, 23:30 for MCX), so after that the nearest expiry rolls forward."""
    t = to_ist(at)
    cutoff = time(23, 30) if exchange.upper() == "MCX" else time(15, 30)
    return t.date() + timedelta(days=1) if t.time() >= cutoff else t.date()


def upcoming_expiries(underlying: str, from_date: date, count: int = 6, exchange: str = "NSE") -> list[date]:
    """Return the next `count` expiry dates for an underlying (weekly where applicable)."""
    wd = EXPIRY_WEEKDAY.get(exchange.upper(), 1)
    out: list[date] = []
    if underlying.upper() in WEEKLY_UNDERLYINGS:
        d = from_date
        while d.weekday() != wd:
            d += timedelta(days=1)
        while len(out) < count:
            out.append(_adjust_back_for_holiday(d))
            d += timedelta(days=7)
        return out
    y, m = from_date.year, from_date.month
    while len(out) < count:
        e = monthly_expiry(y, m, exchange)
        if e >= from_date:
            out.append(e)
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def year_fraction(start: datetime | date, end: datetime | date) -> float:
    """ACT/365 year fraction; expiry treated as 15:30 IST."""
    if isinstance(start, date) and not isinstance(start, datetime):
        start = datetime.combine(start, time(9, 15), tzinfo=IST)
    if isinstance(end, date) and not isinstance(end, datetime):
        end = datetime.combine(end, NSE_CLOSE, tzinfo=IST)
    secs = (to_ist(end) - to_ist(start)).total_seconds()
    return max(secs, 0.0) / (365.0 * 24 * 3600)
