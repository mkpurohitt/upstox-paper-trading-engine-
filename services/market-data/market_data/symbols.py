"""Canonical symbol helpers (OpenAlgo-compatible derivative naming).

* Option:  ``NFO:NIFTY25NOV2626200CE``  -> UNDERLYING + DD + MMM + YY + STRIKE + CE/PE
* Future:  ``NFO:BANKNIFTY29DEC26FUT``  -> UNDERLYING + DD + MMM + YY + FUT
* Equity:  ``NSE:RELIANCE``  Index: ``NSE_INDEX:NIFTY``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_DERIV = re.compile(r"^(?P<und>[A-Z&\-]+?)(?P<dd>\d{2})(?P<mon>[A-Z]{3})(?P<yy>\d{2})(?:(?P<strike>\d+(?:\.\d+)?)(?P<opt>CE|PE)|FUT)$")

INDEX_UNDERLYINGS = {
    "NIFTY": "NSE_INDEX:NIFTY",
    "BANKNIFTY": "NSE_INDEX:BANKNIFTY",
    "FINNIFTY": "NSE_INDEX:FINNIFTY",
    "MIDCPNIFTY": "NSE_INDEX:MIDCPNIFTY",
    "SENSEX": "BSE_INDEX:SENSEX",
    "BANKEX": "BSE_INDEX:BANKEX",
}


@dataclass(frozen=True)
class ParsedSymbol:
    exchange: str
    tradingsymbol: str
    underlying: str | None = None
    expiry: date | None = None
    strike: float | None = None
    option_type: str | None = None  # CE | PE | None
    is_future: bool = False

    @property
    def is_option(self) -> bool:
        return self.option_type is not None

    @property
    def is_derivative(self) -> bool:
        return self.is_option or self.is_future


def split(symbol: str) -> tuple[str, str]:
    if ":" not in symbol:
        return "NSE", symbol.upper()
    ex, ts = symbol.split(":", 1)
    return ex.upper(), ts.upper()


def fmt_expiry(d: date) -> str:
    return f"{d.day:02d}{MONTHS[d.month - 1]}{d.year % 100:02d}"


def _fmt_strike(strike: float) -> str:
    return str(int(strike)) if float(strike).is_integer() else f"{strike:g}"


def option_symbol(underlying: str, expiry: date, strike: float, opt: str, exchange: str | None = None) -> str:
    ex = exchange or ("BFO" if underlying.upper() in ("SENSEX", "BANKEX") else ("MCX" if underlying.upper() in COMMODITIES else "NFO"))
    return f"{ex}:{underlying.upper()}{fmt_expiry(expiry)}{_fmt_strike(strike)}{opt.upper()}"


def future_symbol(underlying: str, expiry: date, exchange: str | None = None) -> str:
    ex = exchange or ("BFO" if underlying.upper() in ("SENSEX", "BANKEX") else ("MCX" if underlying.upper() in COMMODITIES else "NFO"))
    return f"{ex}:{underlying.upper()}{fmt_expiry(expiry)}FUT"


def parse(symbol: str) -> ParsedSymbol:
    ex, ts = split(symbol)
    if ex in ("NFO", "BFO", "MCX", "CDS"):
        m = _DERIV.match(ts)
        if m:
            exp = datetime.strptime(f"{m['dd']}{m['mon']}{m['yy']}", "%d%b%y").date()
            if m["opt"]:
                return ParsedSymbol(ex, ts, m["und"], exp, float(m["strike"]), m["opt"])
            return ParsedSymbol(ex, ts, m["und"], exp, is_future=True)
    return ParsedSymbol(ex, ts)


def underlying_spot_symbol(underlying: str) -> str:
    u = underlying.upper()
    if u in INDEX_UNDERLYINGS:
        return INDEX_UNDERLYINGS[u]
    if u in COMMODITIES:
        return f"MCX:{u}"
    return f"NSE:{u}"


COMMODITIES = {"CRUDEOIL", "NATURALGAS", "GOLD", "GOLDM", "SILVER", "SILVERM", "COPPER", "ZINC", "ALUMINIUM"}
