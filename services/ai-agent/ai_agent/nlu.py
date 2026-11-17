"""Lightweight NLU: symbol resolution and intent hints from free text.

Used by the offline rule-based model, follow-up suggestions and evals. A real LLM does
its own understanding; these helpers never override its tool choices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from market_data.universe import COMMODITY_ASSETS, EQUITIES, INDICES

INDEX_ALIASES = {
    "nifty 50": "NIFTY", "nifty50": "NIFTY", "nifty": "NIFTY", "bank nifty": "BANKNIFTY", "banknifty": "BANKNIFTY",
    "nifty bank": "BANKNIFTY", "finnifty": "FINNIFTY", "fin nifty": "FINNIFTY", "midcpnifty": "MIDCPNIFTY",
    "midcap nifty": "MIDCPNIFTY", "sensex": "SENSEX", "bankex": "BANKEX", "india vix": "INDIAVIX", "vix": "INDIAVIX",
    "nifty it": "NIFTYIT",
}
_STOP = {"bank", "india", "industries", "limited", "ltd", "the", "and", "of", "company", "corporation", "finance",
         "motors", "steel", "power", "tata", "life", "insurance", "services", "consumer", "products", "enterprises", "ports"}


@lru_cache(maxsize=1)
def _alias_map() -> dict[str, str]:
    """lower-case alias -> canonical symbol (index aliases map to NSE_INDEX:/BSE_INDEX: symbols)."""
    out: dict[str, str] = {}
    first_words: dict[str, list[str]] = {}
    for a in EQUITIES + COMMODITY_ASSETS:
        t = a.tradingsymbol.lower()
        out[t] = a.symbol
        out[a.name.lower()] = a.symbol
        w = re.split(r"[\s&.-]+", a.name.lower())[0]
        if len(w) > 3 and w not in _STOP:
            first_words.setdefault(w, []).append(a.symbol)
    for w, syms in first_words.items():
        if len(syms) == 1 and w not in out:
            out[w] = syms[0]
    idx = {a.tradingsymbol: a.symbol for a in INDICES}
    for alias, und in INDEX_ALIASES.items():
        if und in idx:
            out[alias] = idx[und]
    return out


@lru_cache(maxsize=1)
def _alias_regex() -> re.Pattern[str]:
    keys = sorted(_alias_map(), key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in keys) + r")(?![a-z0-9])")


def find_symbols(text: str) -> list[str]:
    """Canonical symbols mentioned in `text`, in order of appearance, de-duplicated."""
    low = text.lower()
    seen: list[str] = []
    for m in _alias_regex().finditer(low):
        sym = _alias_map()[m.group(1)]
        if sym not in seen:
            seen.append(sym)
    # explicit canonical symbols like NSE:TCS
    for m in re.finditer(r"\b(NSE|BSE|NFO|MCX|NSE_INDEX|BSE_INDEX):([A-Z0-9&-]+)", text.upper()):
        s = f"{m.group(1)}:{m.group(2)}"
        if s not in seen:
            seen.append(s)
    return seen


def underlying_of(symbol: str) -> str:
    return symbol.split(":", 1)[-1]


def find_underlying(text: str, default: str = "NIFTY") -> str:
    for s in find_symbols(text):
        if s.startswith(("NSE_INDEX:", "BSE_INDEX:")) and underlying_of(s) in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
            return underlying_of(s)
        if s.startswith("NSE:"):
            return underlying_of(s)
    return default


def find_equities(text: str) -> list[str]:
    return [s for s in find_symbols(text) if s.startswith(("NSE:", "BSE:"))]


INTERVALS = {"1 minute": "1m", "1m": "1m", "5 minute": "5m", "5m": "5m", "15 minute": "15m", "15m": "15m", "30m": "30m",
             "hourly": "1h", "1 hour": "1h", "1h": "1h", "daily": "1d", "1d": "1d", "weekly": "1w", "1w": "1w"}


def find_interval(text: str, default: str = "1d") -> str:
    low = text.lower()
    for k, v in INTERVALS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", low):
            return v
    if "intraday" in low:
        return "15m"
    return default


# ---------------------------------------------------------------- screener phrase parsing

_FIELD_PHRASES: list[tuple[str, str]] = [
    (r"rsi(?:\s*\(?14\)?)?", "rsi14"), (r"p\s*/?\s*e(?:\s+ratio)?", "pe"), (r"p\s*/\s*b|price to book", "pb"),
    (r"roe", "roe_pct"), (r"roce", "roce_pct"), (r"debt\s*(?:to|/)\s*equity|d\s*/\s*e", "debt_to_equity"),
    (r"dividend yield", "dividend_yield_pct"), (r"net margin", "net_margin_pct"), (r"adx", "adx14"),
    (r"market cap(?:italisation|italization)?", "market_cap_cr"), (r"1\s*y(?:ear)? return", "ret_1y_pct"),
    (r"1\s*m(?:onth)? return", "ret_1m_pct"), (r"3\s*m(?:onth)? return", "ret_3m_pct"), (r"volume ratio", "volume_ratio"),
]
_OPS = [(r"(?:below|under|less than|<|lower than)", "<"), (r"(?:above|over|more than|greater than|>|higher than)", ">")]


@dataclass
class ScreenIntent:
    conditions: list[dict[str, object]] = field(default_factory=list)
    universe: str = "NIFTY100"
    sort_by: str = "market_cap_cr"
    descending: bool = True


def parse_screen(text: str) -> ScreenIntent:
    low = text.lower()
    si = ScreenIntent()
    if "nifty 50" in low or "nifty50" in low:
        si.universe = "NIFTY50"
    elif "f&o" in low or "fno" in low:
        si.universe = "FNO"
    elif "bank" in low and "stocks" in low:
        si.universe = "BANKNIFTY"
    for fpat, field_name in _FIELD_PHRASES:
        for opat, op in _OPS:
            m = re.search(rf"(?<![a-z]){fpat}\s*(?:is\s*)?{opat}\s*(-?\d+(?:\.\d+)?)", low)
            if m:
                si.conditions.append({"field": field_name, "op": op, "value": float(m.group(1))})
    if "oversold" in low and not any(c["field"] == "rsi14" for c in si.conditions):
        si.conditions.append({"field": "rsi14", "op": "<", "value": 30.0})
    if "overbought" in low and not any(c["field"] == "rsi14" for c in si.conditions):
        si.conditions.append({"field": "rsi14", "op": ">", "value": 70.0})
    if re.search(r"52[\s-]*week high|52w high|all[\s-]*time high", low):
        si.conditions.append({"field": "dist_52w_high_pct", "op": "<", "value": 3.0})
    if re.search(r"52[\s-]*week low|52w low", low):
        si.conditions.append({"field": "dist_52w_low_pct", "op": "<", "value": 5.0})
    if ("above 200" in low and "sma" in low) or "above their 200" in low:
        si.conditions.append({"field": "dist_sma200_pct", "op": ">", "value": 0.0})
    if "low debt" in low or "debt free" in low or "debt-free" in low:
        si.conditions.append({"field": "debt_to_equity", "op": "<", "value": 0.3})
    if "high roe" in low and not any(c["field"] == "roe_pct" for c in si.conditions):
        si.conditions.append({"field": "roe_pct", "op": ">", "value": 18.0})
    if "cheap" in low or "undervalued" in low or "low pe" in low:
        if not any(c["field"] == "pe" for c in si.conditions):
            si.conditions.append({"field": "pe", "op": "<", "value": 18.0})
    if "volume" in low and ("spike" in low or "surge" in low or "high volume" in low):
        si.conditions.append({"field": "volume_ratio", "op": ">", "value": 1.5})
    if si.conditions:
        f = si.conditions[0]["field"]
        si.sort_by = str(f)
        si.descending = si.conditions[0]["op"] == ">"
    return si
