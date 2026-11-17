"""Realistic Indian transaction cost model.

Statutory charges are effective-dated, so a backtest spanning a regime change
(e.g. the Oct-2024 STT / exchange-fee revision) is charged correctly per trade.

Rates are expressed as decimal fractions of turnover (premium turnover for
options). Sources: NSE/BSE/MCX circulars and Finance Acts. **Verify against
the latest circulars before relying on them**; override per deployment via
`set_rate_override()`.

Brokerage plans are approximations of each broker's public retail tariff.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Segment = Literal["EQ_DELIVERY", "EQ_INTRADAY", "FUT", "OPT", "MCX_FUT", "MCX_OPT"]
Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class RateRegime:
    effective_from: date
    stt: dict[str, tuple[float, float]]  # segment -> (buy, sell)
    stt_exercise: float  # on intrinsic value of exercised long options
    exchange_nse: dict[str, float]
    exchange_bse: dict[str, float]
    exchange_mcx: dict[str, float]
    stamp_buy: dict[str, float]
    sebi_fee: float = 10 / 1e7  # ₹10 per crore
    ipft_nse: dict[str, float] = field(default_factory=lambda: {"EQ": 10 / 1e7, "FUT": 10 / 1e7, "OPT": 50 / 1e7})
    gst: float = 0.18
    note: str = ""


_STAMP = {"EQ_DELIVERY": 0.00015, "EQ_INTRADAY": 0.00003, "FUT": 0.00002, "OPT": 0.00003, "MCX_FUT": 0.00002, "MCX_OPT": 0.00003}
_MCX_EXCH = {"MCX_FUT": 0.000021, "MCX_OPT": 0.000418}

REGIMES: list[RateRegime] = [
    RateRegime(
        effective_from=date(2023, 4, 1),
        stt={"EQ_DELIVERY": (0.001, 0.001), "EQ_INTRADAY": (0.0, 0.00025), "FUT": (0.0, 0.000125),
             "OPT": (0.0, 0.000625), "MCX_FUT": (0.0, 0.0001), "MCX_OPT": (0.0, 0.0005)},
        stt_exercise=0.00125,
        exchange_nse={"EQ": 0.0000322, "FUT": 0.000019, "OPT": 0.000495},
        exchange_bse={"EQ": 0.0000375, "FUT": 0.0, "OPT": 0.000325},
        exchange_mcx=_MCX_EXCH, stamp_buy=_STAMP,
        note="FY24 rates (pre Oct-2024 revision)",
    ),
    RateRegime(
        effective_from=date(2024, 10, 1),
        stt={"EQ_DELIVERY": (0.001, 0.001), "EQ_INTRADAY": (0.0, 0.00025), "FUT": (0.0, 0.0002),
             "OPT": (0.0, 0.001), "MCX_FUT": (0.0, 0.0001), "MCX_OPT": (0.0, 0.0005)},
        stt_exercise=0.00125,
        exchange_nse={"EQ": 0.0000297, "FUT": 0.0000173, "OPT": 0.0003503},
        exchange_bse={"EQ": 0.0000375, "FUT": 0.0, "OPT": 0.000325},
        exchange_mcx=_MCX_EXCH, stamp_buy=_STAMP,
        note="Finance (No.2) Act 2024 STT + NSE uniform charges from 01-Oct-2024",
    ),
    RateRegime(
        effective_from=date(2026, 4, 1),
        stt={"EQ_DELIVERY": (0.001, 0.001), "EQ_INTRADAY": (0.0, 0.00025), "FUT": (0.0, 0.0005),
             "OPT": (0.0, 0.0015), "MCX_FUT": (0.0, 0.0001), "MCX_OPT": (0.0, 0.0005)},
        stt_exercise=0.0015,
        exchange_nse={"EQ": 0.0000297, "FUT": 0.0000173, "OPT": 0.0003503},
        exchange_bse={"EQ": 0.0000375, "FUT": 0.0, "OPT": 0.000325},
        exchange_mcx=_MCX_EXCH, stamp_buy=_STAMP,
        note="Union Budget 2026 F&O STT revision (verify against the enacted Finance Act)",
    ),
]

_override: dict[str, float] = {}


def set_rate_override(overrides: dict[str, float]) -> None:
    """e.g. {"stt.OPT.sell": 0.001}; applies on top of the dated regime."""
    _override.clear()
    _override.update(overrides)


def regime_for(d: date) -> RateRegime:
    chosen = REGIMES[0]
    for r in REGIMES:
        if d >= r.effective_from:
            chosen = r
    return chosen


@dataclass(frozen=True)
class BrokeragePlan:
    name: str
    delivery_pct: float = 0.0
    delivery_cap: float | None = None
    intraday_pct: float = 0.0003
    intraday_cap: float = 20.0
    fno_flat: float = 20.0  # per executed order (futures & options)
    fut_pct: float | None = 0.0003  # futures: min(pct, flat)
    mcx_flat: float = 20.0
    note: str = "approximate public retail tariff"


BROKERS: dict[str, BrokeragePlan] = {
    "paper": BrokeragePlan("paper"),
    "zerodha": BrokeragePlan("zerodha"),
    "upstox": BrokeragePlan("upstox", delivery_pct=0.0, intraday_pct=0.001, intraday_cap=20),
    "angel": BrokeragePlan("angel", delivery_pct=0.001, delivery_cap=20, intraday_pct=0.0003, intraday_cap=20),
    "dhan": BrokeragePlan("dhan", delivery_pct=0.0, intraday_pct=0.0003, intraday_cap=20),
    "fyers": BrokeragePlan("fyers", delivery_pct=0.0, intraday_pct=0.0003, intraday_cap=20),
    "kotak": BrokeragePlan("kotak", delivery_pct=0.0, intraday_pct=0.0, intraday_cap=0.0, fno_flat=10.0, fut_pct=None),
    "fivepaisa": BrokeragePlan("fivepaisa", delivery_pct=1.0, delivery_cap=20, intraday_pct=1.0, intraday_cap=20, fut_pct=None),
    "icici": BrokeragePlan("icici", delivery_pct=0.0, intraday_pct=0.0, intraday_cap=20, fno_flat=20.0, fut_pct=None),
    "aliceblue": BrokeragePlan("aliceblue", delivery_pct=0.0, intraday_pct=0.0003, intraday_cap=20, fno_flat=20.0),
    "shoonya": BrokeragePlan("shoonya", delivery_pct=0.0, intraday_pct=0.0, intraday_cap=0.0, fno_flat=0.0, fut_pct=None,
                             mcx_flat=0.0, note="zero-brokerage plan"),
}


@dataclass
class Charges:
    brokerage: float = 0.0
    stt: float = 0.0
    exchange: float = 0.0
    sebi: float = 0.0
    stamp: float = 0.0
    ipft: float = 0.0
    gst: float = 0.0

    @property
    def total(self) -> float:
        return self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.ipft + self.gst

    def __add__(self, o: Charges) -> Charges:
        return Charges(*(getattr(self, f) + getattr(o, f) for f in ("brokerage", "stt", "exchange", "sebi", "stamp", "ipft", "gst")))

    def as_dict(self) -> dict[str, float]:
        d = {f: round(getattr(self, f), 2) for f in ("brokerage", "stt", "exchange", "sebi", "stamp", "ipft", "gst")}
        d["total"] = round(self.total, 2)
        return d


def segment_for(exchange: str, instrument: str, product: str) -> Segment:
    """instrument: EQ | FUT | CE | PE ; product: MIS | CNC | NRML"""
    if exchange == "MCX":
        return "MCX_OPT" if instrument in ("CE", "PE") else "MCX_FUT"
    if instrument in ("CE", "PE"):
        return "OPT"
    if instrument == "FUT":
        return "FUT"
    return "EQ_DELIVERY" if product == "CNC" else "EQ_INTRADAY"


class CostModel:
    def __init__(self, broker: str = "paper") -> None:
        self.plan = BROKERS.get(broker, BROKERS["paper"])

    def brokerage(self, segment: Segment, turnover: float, orders: int = 1) -> float:
        p = self.plan
        if segment == "EQ_DELIVERY":
            if p.delivery_pct >= 1.0:  # flat per order
                return (p.delivery_cap or 20.0) * orders
            b = turnover * p.delivery_pct
            return min(b, (p.delivery_cap or b) * orders)
        if segment == "EQ_INTRADAY":
            if p.intraday_pct >= 1.0:
                return p.intraday_cap * orders
            return min(turnover * p.intraday_pct, p.intraday_cap * orders)
        if segment in ("MCX_FUT", "MCX_OPT"):
            return p.mcx_flat * orders
        if segment == "FUT" and p.fut_pct is not None:
            return min(turnover * p.fut_pct, p.fno_flat * orders)
        return p.fno_flat * orders

    def charges(
        self,
        *,
        on: date,
        side: Side,
        price: float,
        quantity: int,
        exchange: str = "NSE",
        instrument: str = "EQ",
        product: str = "MIS",
        orders: int = 1,
        exercised_intrinsic: float = 0.0,
    ) -> Charges:
        seg = segment_for(exchange, instrument, product)
        r = regime_for(on)
        turnover = abs(price * quantity)
        c = Charges()
        c.brokerage = self.brokerage(seg, turnover, orders)
        buy_rate, sell_rate = r.stt[seg]
        buy_rate = _override.get(f"stt.{seg}.buy", buy_rate)
        sell_rate = _override.get(f"stt.{seg}.sell", sell_rate)
        c.stt = turnover * (buy_rate if side == "BUY" else sell_rate)
        if exercised_intrinsic > 0:
            c.stt += exercised_intrinsic * quantity * r.stt_exercise
        kind = "OPT" if seg in ("OPT",) else ("FUT" if seg == "FUT" else "EQ")
        if exchange == "MCX":
            c.exchange = turnover * r.exchange_mcx[seg]
        elif exchange in ("BSE", "BFO"):
            c.exchange = turnover * r.exchange_bse[kind]
        else:
            c.exchange = turnover * r.exchange_nse[kind]
            c.ipft = turnover * r.ipft_nse[kind]
        c.sebi = turnover * r.sebi_fee
        if side == "BUY":
            c.stamp = turnover * r.stamp_buy[seg]
        c.gst = r.gst * (c.brokerage + c.exchange + c.sebi + c.ipft)
        return c


def split_orders(quantity: int, freeze_qty: int | None, lot_size: int = 1) -> list[int]:
    """Split a large F&O order into exchange freeze-limit compliant slices (lot multiples)."""
    if not freeze_qty or quantity <= freeze_qty:
        return [quantity]
    max_slice = max(lot_size, (freeze_qty // lot_size) * lot_size)
    n = math.ceil(quantity / max_slice)
    out = [max_slice] * (n - 1)
    out.append(quantity - max_slice * (n - 1))
    return out


def segment_instrument(symbol: str) -> tuple[str, str]:
    """canonical symbol -> (exchange for charges, instrument type EQ|FUT|CE|PE)."""
    from market_data.symbols import parse

    p = parse(symbol)
    exch = "MCX" if p.exchange == "MCX" else ("BSE" if p.exchange in ("BSE", "BFO") else "NSE")
    if p.is_option:
        return exch, p.option_type or "CE"
    if p.is_future:
        return exch, "FUT"
    return exch, "EQ"
