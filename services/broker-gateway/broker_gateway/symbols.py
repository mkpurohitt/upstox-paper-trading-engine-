"""Canonical <-> broker symbol mapping.

Canonical: ``NSE:SBIN``, ``NFO:NIFTY24NOV2626200CE`` (UND+DDMMMYY+STRIKE+CE/PE),
``NFO:BANKNIFTY29DEC26FUT``, ``MCX:CRUDEOIL18DEC26FUT``.

Broker formats implemented here:

=========  ==========================  ==================================  ==========================
broker     equity                      option (weekly / monthly)           future
=========  ==========================  ==================================  ==========================
zerodha    SBIN                        NIFTY2611726200CE / NIFTY26NOV26200CE  NIFTY26NOVFUT
fyers      NSE:SBIN-EQ                 NSE:NIFTY2611726200CE / NSE:NIFTY26NOV26200CE  NSE:NIFTY26NOVFUT
angel      SBIN-EQ (+symboltoken)      NIFTY24NOV2626200CE (+token)        NIFTY24NOV26FUT
shoonya    SBIN-EQ                     NIFTY24NOV26C26200                  NIFTY24NOV26F
kotak      SBIN-EQ                     zerodha style (master override)     zerodha style
others     token from instrument master (upstox instrument_key, dhan securityId, 5paisa ScripCode,
           aliceblue instrumentId, ICICI stock_code)
=========  ==========================  ==================================  ==========================

Brokers that need numeric tokens read them from `TokenStore`, which is filled
from each broker's instrument master (``instruments.broker_tokens``).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from algo_common.timeutils import monthly_expiry
from market_data.symbols import MONTHS, ParsedSymbol, parse

_WEEKLY_MONTH = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "O", 11: "N", 12: "D"}
_WEEKLY_MONTH_REV = {v: k for k, v in _WEEKLY_MONTH.items()}
INDEX_NAMES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}

DHAN_SEGMENT = {"NSE": "NSE_EQ", "BSE": "BSE_EQ", "NFO": "NSE_FNO", "BFO": "BSE_FNO", "MCX": "MCX_COMM",
                "NSE_INDEX": "IDX_I", "BSE_INDEX": "IDX_I"}
KOTAK_SEGMENT = {"NSE": "nse_cm", "BSE": "bse_cm", "NFO": "nse_fo", "BFO": "bse_fo", "MCX": "mcx_fo"}
FIVEPAISA_EXCH = {"NSE": ("N", "C"), "BSE": ("B", "C"), "NFO": ("N", "D"), "BFO": ("B", "D"), "MCX": ("M", "D")}
UPSTOX_SEGMENT = {"NSE": "NSE_EQ", "BSE": "BSE_EQ", "NFO": "NSE_FO", "BFO": "BSE_FO", "MCX": "MCX_FO"}


class TokenStore:
    """broker -> canonical symbol -> broker token (and the reverse)."""

    def __init__(self) -> None:
        self._fwd: dict[str, dict[str, str]] = {}
        self._rev: dict[str, dict[str, str]] = {}

    def set(self, broker: str, mapping: dict[str, str]) -> None:
        self._fwd.setdefault(broker, {}).update(mapping)
        self._rev.setdefault(broker, {}).update({v: k for k, v in mapping.items()})

    def token(self, broker: str, symbol: str) -> str | None:
        return self._fwd.get(broker, {}).get(symbol)

    def symbol(self, broker: str, token: str) -> str | None:
        return self._rev.get(broker, {}).get(str(token))

    def clear(self) -> None:
        self._fwd.clear()
        self._rev.clear()


TOKENS = TokenStore()


async def load_tokens_from_db(broker: str) -> int:
    """Populate TOKENS from the instruments table (``broker_tokens[broker]``)."""
    from sqlalchemy import select

    from algo_db.models import InstrumentRow
    from algo_db.session import session_scope

    async with session_scope() as db:
        rows = (await db.execute(select(InstrumentRow.symbol, InstrumentRow.broker_tokens))).all()
    mapping = {sym: str(tok[broker]) for sym, tok in rows if tok and broker in tok}
    TOKENS.set(broker, mapping)
    return len(mapping)


def is_monthly(p: ParsedSymbol) -> bool:
    if p.expiry is None:
        return True
    exch = "BSE" if p.exchange == "BFO" else ("MCX" if p.exchange == "MCX" else "NSE")
    return monthly_expiry(p.expiry.year, p.expiry.month, exch) == p.expiry


def _strike(p: ParsedSymbol) -> str:
    assert p.strike is not None
    return str(int(p.strike)) if float(p.strike).is_integer() else f"{p.strike:g}"


def kite_tradingsymbol(p: ParsedSymbol) -> str:
    """Zerodha / Kotak style derivative symbol."""
    if not p.is_derivative:
        return p.tradingsymbol
    assert p.expiry is not None and p.underlying is not None
    yy = f"{p.expiry.year % 100:02d}"
    if p.is_future:
        return f"{p.underlying}{yy}{MONTHS[p.expiry.month - 1]}FUT"
    if is_monthly(p):
        return f"{p.underlying}{yy}{MONTHS[p.expiry.month - 1]}{_strike(p)}{p.option_type}"
    return f"{p.underlying}{yy}{_WEEKLY_MONTH[p.expiry.month]}{p.expiry.day:02d}{_strike(p)}{p.option_type}"


def noren_tradingsymbol(p: ParsedSymbol) -> str:
    """Shoonya / Finvasia (Noren OMS) format."""
    if not p.is_derivative:
        return p.tradingsymbol if p.exchange == "MCX" or p.tradingsymbol in INDEX_NAMES else f"{p.tradingsymbol}-EQ"
    assert p.expiry is not None
    dmy = f"{p.expiry.day:02d}{MONTHS[p.expiry.month - 1]}{p.expiry.year % 100:02d}"
    if p.is_future:
        return f"{p.underlying}{dmy}F"
    return f"{p.underlying}{dmy}{'C' if p.option_type == 'CE' else 'P'}{_strike(p)}"


def default_map(broker: str, symbol: str) -> dict[str, Any]:
    p = parse(symbol)
    ex = p.exchange
    token = TOKENS.token(broker, symbol)
    if broker in ("zerodha", "paper"):
        return {"exchange": ex, "tradingsymbol": kite_tradingsymbol(p), "token": token}
    if broker == "fyers":
        fex = {"NFO": "NSE", "BFO": "BSE"}.get(ex, ex)
        ts = kite_tradingsymbol(p) if p.is_derivative else (p.tradingsymbol if ex == "MCX" else f"{p.tradingsymbol}-EQ")
        return {"exchange": fex, "tradingsymbol": f"{fex}:{ts}", "token": token}
    if broker == "angel":
        ts = p.tradingsymbol if p.is_derivative or ex == "MCX" else f"{p.tradingsymbol}-EQ"
        return {"exchange": ex, "tradingsymbol": ts, "token": token}
    if broker == "shoonya":
        return {"exchange": ex, "tradingsymbol": noren_tradingsymbol(p), "token": token}
    if broker == "kotak":
        ts = kite_tradingsymbol(p) if p.is_derivative else f"{p.tradingsymbol}-EQ"
        return {"exchange": KOTAK_SEGMENT.get(ex, ex.lower()), "tradingsymbol": token or ts, "token": token}
    if broker == "dhan":
        return {"exchange": DHAN_SEGMENT.get(ex, ex), "tradingsymbol": p.tradingsymbol, "token": token}
    if broker == "fivepaisa":
        e, t = FIVEPAISA_EXCH.get(ex, ("N", "C"))
        return {"exchange": e, "exchange_type": t, "tradingsymbol": p.tradingsymbol, "token": token}
    if broker == "upstox":
        return {"exchange": UPSTOX_SEGMENT.get(ex, ex), "tradingsymbol": p.tradingsymbol, "token": token}
    if broker == "icici":
        out: dict[str, Any] = {"exchange": ex, "tradingsymbol": token or p.underlying or p.tradingsymbol, "token": token}
        if p.is_derivative and p.expiry is not None:
            out.update(expiry_date=f"{p.expiry.isoformat()}T06:00:00.000Z",
                       right="others" if p.is_future else ("call" if p.option_type == "CE" else "put"),
                       strike_price=_strike(p) if p.is_option else "0",
                       product="futures" if p.is_future else "options",
                       stock_code=token or p.underlying)
        return out
    return {"exchange": ex, "tradingsymbol": p.tradingsymbol, "token": token}


_KITE_MONTHLY = re.compile(r"^(?P<und>[A-Z&\-]+?)(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?:(?P<strike>\d+(?:\.\d+)?)(?P<opt>CE|PE)|FUT)$")
_KITE_WEEKLY = re.compile(r"^(?P<und>[A-Z&\-]+?)(?P<yy>\d{2})(?P<m>[1-9OND])(?P<dd>\d{2})(?P<strike>\d+(?:\.\d+)?)(?P<opt>CE|PE)$")
_NOREN = re.compile(r"^(?P<und>[A-Z&\-]+?)(?P<dd>\d{2})(?P<mon>[A-Z]{3})(?P<yy>\d{2})(?:(?P<cp>[CP])(?P<strike>\d+(?:\.\d+)?)|F)$")


def to_canonical(broker: str, exchange: str, tradingsymbol: str, token: str | None = None) -> str:
    """Best-effort reverse mapping used when parsing broker books."""
    from market_data.symbols import future_symbol, option_symbol

    if token:
        hit = TOKENS.symbol(broker, token)
        if hit:
            return hit
    ex = exchange.upper()
    seg_rev = {v: k for k, v in {**DHAN_SEGMENT, **KOTAK_SEGMENT, **UPSTOX_SEGMENT}.items() if not k.endswith("INDEX")}
    ex = seg_rev.get(exchange, seg_rev.get(ex, ex))
    ts = tradingsymbol.upper()
    if ":" in ts:  # fyers style
        fex, ts = ts.split(":", 1)
        if ex in ("", "NSE", "BSE") and fex in ("NSE", "BSE"):
            ex = fex
    if ts.endswith("-EQ") or ts.endswith("-BE"):
        return f"{ex if ex in ('NSE', 'BSE') else 'NSE'}:{ts[:-3]}"
    deriv_ex = {"NSE": "NFO", "BSE": "BFO"}.get(ex, ex)
    m = _NOREN.match(ts)
    if m and broker == "shoonya":
        d = date(2000 + int(m["yy"]), MONTHS.index(m["mon"]) + 1, int(m["dd"]))
        if m["cp"]:
            return option_symbol(m["und"], d, float(m["strike"]), "CE" if m["cp"] == "C" else "PE", exchange=deriv_ex)
        return future_symbol(m["und"], d, exchange=deriv_ex)
    m = _KITE_WEEKLY.match(ts)
    if m:
        d = date(2000 + int(m["yy"]), _WEEKLY_MONTH_REV[m["m"]], int(m["dd"]))
        return option_symbol(m["und"], d, float(m["strike"]), m["opt"], exchange=deriv_ex)
    m = _KITE_MONTHLY.match(ts)
    if m and m["mon"] in MONTHS:
        y, mo = 2000 + int(m["yy"]), MONTHS.index(m["mon"]) + 1
        exp = monthly_expiry(y, mo, "BSE" if deriv_ex == "BFO" else ("MCX" if deriv_ex == "MCX" else "NSE"))
        if m["opt"]:
            return option_symbol(m["und"], exp, float(m["strike"]), m["opt"], exchange=deriv_ex)
        return future_symbol(m["und"], exp, exchange=deriv_ex)
    if parse(f"{deriv_ex}:{ts}").is_derivative:
        return f"{deriv_ex}:{ts}"
    return f"{ex}:{ts}"
