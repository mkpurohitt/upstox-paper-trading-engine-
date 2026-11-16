"""Provider-agnostic market data schema.

Canonical symbols look like ``EXCHANGE:TRADINGSYMBOL``:

* ``NSE:RELIANCE`` (cash equity)            * ``NSE_INDEX:NIFTY`` (index)
* ``NFO:NIFTY25DEC25800CE`` (index option)  * ``NFO:BANKNIFTY25DECFUT`` (future)
* ``BSE:500325`` / ``BSE:RELIANCE``          * ``MCX:CRUDEOIL25DECFUT``

Every provider maps its native keys (e.g. Upstox ``NSE_EQ|INE002A01018``) to
these canonical symbols so the rest of the platform never sees broker or
vendor specific identifiers.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    BFO = "BFO"
    MCX = "MCX"
    CDS = "CDS"
    NSE_INDEX = "NSE_INDEX"
    BSE_INDEX = "BSE_INDEX"


class InstrumentType(StrEnum):
    EQ = "EQ"
    INDEX = "INDEX"
    FUT = "FUT"
    CE = "CE"
    PE = "PE"


class OptionSide(StrEnum):
    CE = "CE"
    PE = "PE"


class Interval(StrEnum):
    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"

    @property
    def minutes(self) -> int:
        return {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 375, "1w": 1875}[self.value]


class _Model(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Instrument(_Model):
    symbol: str = Field(description="Canonical symbol, e.g. NSE:RELIANCE")
    instrument_key: str = Field(description="Provider native key, e.g. NSE_EQ|INE002A01018")
    exchange: Exchange
    tradingsymbol: str
    name: str
    instrument_type: InstrumentType
    segment: str = ""
    underlying: str | None = None
    expiry: date | None = None
    strike: float | None = None
    lot_size: int = 1
    tick_size: float = 0.05
    freeze_qty: int | None = None
    isin: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap_cr: float | None = None


class Candle(_Model):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
    oi: float | None = None


class DepthLevel(_Model):
    price: float
    quantity: int
    orders: int = 0


class Greeks(_Model):
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    iv: float | None = Field(default=None, description="Implied volatility in % (e.g. 14.2)")


class Tick(_Model):
    symbol: str
    ts: datetime
    ltp: float
    ltq: int | None = None
    volume: float | None = None
    oi: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = Field(default=None, description="Previous close")
    change: float | None = None
    change_pct: float | None = None
    bid: float | None = None
    ask: float | None = None
    greeks: Greeks | None = None


class Quote(Tick):
    name: str | None = None
    avg_price: float | None = None
    upper_circuit: float | None = None
    lower_circuit: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    total_buy_qty: float | None = None
    total_sell_qty: float | None = None
    bids: list[DepthLevel] = Field(default_factory=list)
    asks: list[DepthLevel] = Field(default_factory=list)


class OptionLeg(_Model):
    symbol: str
    ltp: float
    bid: float | None = None
    ask: float | None = None
    volume: float = 0
    oi: float = 0
    oi_change: float = 0
    iv: float | None = None
    greeks: Greeks = Field(default_factory=Greeks)


class OptionChainRow(_Model):
    strike: float
    expiry: date
    call: OptionLeg | None = None
    put: OptionLeg | None = None
    pcr: float | None = None


class OptionChain(_Model):
    underlying: str
    spot: float
    expiry: date
    expiries: list[date] = Field(default_factory=list)
    lot_size: int = 1
    atm_strike: float
    rows: list[OptionChainRow]
    pcr: float | None = None
    max_pain: float | None = None
    total_call_oi: float = 0
    total_put_oi: float = 0
    ts: datetime


class MarketStatus(_Model):
    exchange: str
    status: str
    is_open: bool
    ts: datetime
    next_event: str | None = None
