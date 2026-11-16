"""Pluggable market data provider interface.

Every implementation returns the normalised schema from
`algo_common.schemas.market`, keyed by canonical symbols.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from datetime import date, datetime

from algo_common.schemas.market import Candle, Instrument, Interval, MarketStatus, OptionChain, Quote, Tick

DemandFn = Callable[[], set[str]]


class MarketDataProvider(ABC):
    name: str = "base"
    supports_streaming: bool = True

    # ---- reference data -------------------------------------------------------
    @abstractmethod
    async def instruments(self, exchange: str | None = None) -> list[Instrument]: ...

    async def search(self, query: str, limit: int = 20) -> list[Instrument]:
        q = query.strip().upper()
        if not q:
            return []
        items = await self.instruments()
        scored: list[tuple[int, Instrument]] = []
        for ins in items:
            ts = ins.tradingsymbol.upper()
            name = ins.name.upper()
            if ts == q:
                score = 0
            elif ts.startswith(q):
                score = 1 + len(ts) // 10
            elif q in ts:
                score = 5
            elif q in name:
                score = 8
            else:
                continue
            # prefer cash/index over derivatives for the same match quality
            score += {"INDEX": 0, "EQ": 0, "FUT": 2, "CE": 3, "PE": 3}.get(ins.instrument_type.value, 4)
            scored.append((score, ins))
        scored.sort(key=lambda x: (x[0], x[1].tradingsymbol))
        return [i for _, i in scored[:limit]]

    async def instrument(self, symbol: str) -> Instrument | None:
        for ins in await self.instruments():
            if ins.symbol == symbol:
                return ins
        return None

    # ---- prices -------------------------------------------------------------------
    @abstractmethod
    async def candles(self, symbol: str, interval: Interval, start: datetime, end: datetime) -> list[Candle]: ...

    async def intraday_candles(self, symbol: str, interval: Interval = Interval.M1) -> list[Candle]:
        from algo_common.timeutils import now_ist

        now = now_ist()
        start = now.replace(hour=9, minute=0, second=0, microsecond=0)
        return await self.candles(symbol, interval, start, now)

    @abstractmethod
    async def quotes(self, symbols: list[str]) -> dict[str, Quote]: ...

    async def ltp(self, symbols: list[str]) -> dict[str, float]:
        return {s: q.ltp for s, q in (await self.quotes(symbols)).items()}

    # ---- derivatives ---------------------------------------------------------------
    @abstractmethod
    async def expiries(self, underlying: str) -> list[date]: ...

    @abstractmethod
    async def option_chain(self, underlying: str, expiry: date | None = None, strikes: int = 20) -> OptionChain: ...

    # ---- market calendar -------------------------------------------------------------
    @abstractmethod
    async def market_status(self) -> list[MarketStatus]: ...

    @abstractmethod
    async def holidays(self, year: int | None = None) -> list[dict[str, str]]: ...

    # ---- streaming ----------------------------------------------------------------------
    @abstractmethod
    def stream(self, demand: DemandFn) -> AsyncIterator[list[Tick]]:
        """Yield batches of ticks for the symbols returned by `demand()` (re-evaluated continuously)."""

    async def close(self) -> None:
        return None
