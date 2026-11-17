"""Draft a strategy DSL from a plain-English description using the built-in templates.

Used when the model calls generate_strategy without authoring the DSL itself (and by the
offline model). The result is always validated against the StrategyDSL schema.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from ai_agent import nlu
from strategy_engine.templates import template_by_name


def _num(rx: str, text: str) -> float | None:
    m = re.search(rx, text)
    return float(m.group(1)) if m else None


def _time(text: str) -> str | None:
    m = re.search(r"\b(?:at|after|from)\s+(\d{1,2})[:.](\d{2})", text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h < 9 or h > 15 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def _cmp(left: dict[str, Any], op: str, right: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "compare", "left": left, "op": op, "right": right}


def _ind(ref: str) -> dict[str, Any]:
    return {"type": "indicator", "ref": ref, "offset": 0}


def _k(v: float) -> dict[str, Any]:
    return {"type": "const", "value": v}


_OPT_STRUCT = [
    ("iron condor", "iron_condor"), ("iron fly", "iron_fly"), ("iron butterfly", "iron_fly"), ("butterfly", "butterfly"),
    ("long straddle", "long_straddle"), ("short strangle", "short_strangle"), ("long strangle", "long_strangle"),
    ("strangle", "short_strangle"), ("straddle", "short_straddle"), ("bull call", "bull_call"), ("bear put", "bear_put"),
]
_LEGS: dict[str, list[tuple[str, str, int]]] = {
    "short_straddle": [("SELL", "CE", 0), ("SELL", "PE", 0)],
    "long_straddle": [("BUY", "CE", 0), ("BUY", "PE", 0)],
    "short_strangle": [("SELL", "CE", 4), ("SELL", "PE", -4)],
    "long_strangle": [("BUY", "CE", 4), ("BUY", "PE", -4)],
    "iron_condor": [("SELL", "CE", 4), ("BUY", "CE", 8), ("SELL", "PE", -4), ("BUY", "PE", -8)],
    "iron_fly": [("SELL", "CE", 0), ("SELL", "PE", 0), ("BUY", "CE", 5), ("BUY", "PE", -5)],
    "butterfly": [("BUY", "CE", -3), ("SELL", "CE", 0), ("SELL", "CE", 0), ("BUY", "CE", 3)],
    "bull_call": [("BUY", "CE", 0), ("SELL", "CE", 4)],
    "bear_put": [("BUY", "PE", 0), ("SELL", "PE", -4)],
}


def draft_from_description(text: str) -> tuple[dict[str, Any], str]:
    low = text.lower()
    notes: list[str] = []
    eqs = nlu.find_equities(text)
    structure = next((v for k, v in _OPT_STRUCT if k in low), None)

    # ---------------------------------------------------------------- options
    if structure or re.search(r"\boptions?\b.*\b(sell|buy|write)\b", low):
        structure = structure or "short_straddle"
        und = nlu.find_underlying(text)
        dsl = copy.deepcopy(template_by_name("NIFTY short straddle with SL"))
        assert dsl is not None
        leg_sl = _num(r"(\d+(?:\.\d+)?)\s*%\s*(?:leg[- ]?wise\s*)?(?:sl|stop)", low) or _num(r"(?:sl|stop[- ]?loss)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%", low)
        monthly = "monthly" in low
        dsl["legs"] = [{"id": f"{a.lower()}_{t.lower()}_{i}", "action": a, "option_type": t,
                        "strike": {"mode": "ATM_OFFSET", "offset": off}, "expiry": "monthly" if monthly else "current", "lots": 1,
                        **({"stop_loss_pct": leg_sl} if leg_sl and a == "SELL" else {})}
                       for i, (a, t, off) in enumerate(_LEGS[structure])]
        delta = _num(r"(0\.\d+)\s*delta", low)
        if delta and structure in ("short_strangle", "iron_condor"):
            for leg in dsl["legs"]:
                if leg["action"] == "SELL":
                    leg["strike"] = {"mode": "DELTA", "delta": delta}
            notes.append(f"short strikes selected at ~{delta} delta")
        dsl["universe"] = {"underlying": und}
        nice = structure.replace("_", " ")
        dsl["name"] = f"{und} {nice}" + (f" with {leg_sl:g}% SL" if leg_sl else "")
        dsl["description"] = f"Drafted from: {text[:200]}"
        entry = _time(low)
        intraday = not monthly and "positional" not in low and "overnight" not in low
        dsl["product"] = "MIS" if intraday else "NRML"
        dsl["schedule"] = {"entry_after": entry or "09:20", "entry_before": "10:30" if not entry else None,
                           "square_off": "15:15" if intraday else None}
        if dsl["schedule"]["entry_before"] is None:
            h, m = map(int, (entry or "09:20").split(":"))
            dsl["schedule"]["entry_before"] = f"{min(h + 1, 15):02d}:{m:02d}"
        tgt = _num(r"target\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%", low)
        dsl["options_exit"] = {"combined_target_pct": tgt or 50,
                               "combined_stop_loss_pct": None if leg_sl else (_num(r"combined\s*(?:sl|stop)\s*(\d+)\s*%", low) or 60)}
        dsl["risk"] = {"max_loss_per_day": _num(r"max(?:imum)? loss (?:of |per day )?(?:₹|rs\.?|inr)?\s*([\d,]+)", low.replace(",", "")) or 10000}
        dsl["tags"] = ["options", "copilot"]
        expl = (f"Sells/buys {len(dsl['legs'])} legs on {und} ({'monthly' if monthly else 'nearest weekly'} expiry) at "
                f"{dsl['schedule']['entry_after']}, {'squares off at 15:15' if intraday else 'held positionally'}"
                + (f", {leg_sl:g}% leg-wise stop-loss" if leg_sl else "") + f", combined target {dsl['options_exit']['combined_target_pct']:g}% of premium.")
        return dsl, expl + (" " + "; ".join(notes) + "." if notes else "")

    # ---------------------------------------------------------------- pair
    if re.search(r"\bpairs?\b|cointegrat|stat(istical)? arb", low) and len(eqs) >= 2:
        dsl = copy.deepcopy(template_by_name("HDFCBANK / ICICIBANK pair trade"))
        assert dsl is not None
        dsl["pair"]["leg_a"], dsl["pair"]["leg_b"] = eqs[0], eqs[1]
        if (z := _num(r"(?:entry|enter)\D{0,12}(\d+(?:\.\d+)?)\s*(?:z|sd|sigma|std)", low)) is not None:
            dsl["pair"]["entry_z"] = z
        dsl["name"] = f"{nlu.underlying_of(eqs[0])} / {nlu.underlying_of(eqs[1])} pair trade"
        dsl["description"] = f"Drafted from: {text[:200]}"
        dsl["tags"] = ["pair", "copilot"]
        p = dsl["pair"]
        return dsl, (f"Mean-reversion on the {p['lookback']}-bar z-score of the hedged spread: enter at ±{p['entry_z']}, "
                     f"exit near ±{p['exit_z']}, stop at ±{p.get('stop_z')}. Test cointegration on the Pairs dashboard first.")

    # ---------------------------------------------------------------- equity
    if "rsi" in low or "oversold" in low or "mean reversion" in low:
        base = "RSI mean reversion (daily)"
    elif "supertrend" in low or "adx" in low:
        base = "Supertrend + ADX trend rider"
    elif re.search(r"breakout|opening range|\borb\b", low):
        base = "Opening range breakout (15m)"
    else:
        base = "EMA 9/21 crossover"
    dsl = copy.deepcopy(template_by_name(base))
    assert dsl is not None
    if "bollinger" in low:
        dsl["indicators"] = [{"id": "bb", "kind": "BBANDS", "params": {"period": 20, "std": 2}}]
        dsl["entry"] = {"long": {"kind": "all", "conditions": [_cmp({"type": "price", "field": "close"}, "crosses_below", _ind("bb.lower"))]}}
        dsl["exit"] = {"long": {"kind": "any", "conditions": [_cmp({"type": "price", "field": "close"}, "crosses_above", _ind("bb.middle"))]},
                       "stop_loss": {"type": "percent", "value": 3}}
        base = "Bollinger mean reversion"
    elif "macd" in low:
        dsl["indicators"] = [{"id": "macd", "kind": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}}]
        dsl["entry"] = {"long": {"kind": "all", "conditions": [_cmp(_ind("macd.macd"), "crosses_above", _ind("macd.signal"))]},
                        "short": {"kind": "all", "conditions": [_cmp(_ind("macd.macd"), "crosses_below", _ind("macd.signal"))]}}
        dsl["exit"] = {"long": {"kind": "any", "conditions": [_cmp(_ind("macd.macd"), "crosses_below", _ind("macd.signal"))]},
                       "short": {"kind": "any", "conditions": [_cmp(_ind("macd.macd"), "crosses_above", _ind("macd.signal"))]},
                       "stop_loss": {"type": "percent", "value": 1.0}}
        base = "MACD crossover"
    elif base == "EMA 9/21 crossover":
        m = re.search(r"(\d{1,3})\s*(?:/|and|&|-|vs\.?|,)\s*(\d{1,3})", low)
        if m and ("ema" in low or "moving average" in low or "crossover" in low or "sma" in low):
            f, s = sorted((int(m.group(1)), int(m.group(2))))
            if 1 < f < s <= 400:
                kind = "SMA" if "sma" in low or "simple" in low else "EMA"
                dsl["indicators"] = [{"id": "ema_fast", "kind": kind, "params": {"period": f}},
                                     {"id": "ema_slow", "kind": kind, "params": {"period": s}}]
                base = f"{kind} {f}/{s} crossover"
        if "long only" in low or "long-only" in low or "no short" in low:
            dsl["entry"].pop("short", None)
            dsl["exit"].pop("short", None)
    if base.startswith("RSI"):
        lo_ = _num(r"rsi\D{0,20}?(?:below|under|<|less than)\s*(\d+)", low)
        hi_ = _num(r"(?:above|over|>|more than)\s*(\d+)", low) if lo_ else None
        if lo_:
            for c in dsl["entry"]["long"]["conditions"]:
                if c.get("right", {}).get("type") == "const":
                    c["right"]["value"] = lo_
        if hi_:
            for c in dsl["exit"]["long"]["conditions"]:
                if c.get("right", {}).get("type") == "const":
                    c["right"]["value"] = hi_
    if eqs:
        dsl["universe"] = {"symbols": eqs[:10]}
    elif (idx := [s for s in nlu.find_symbols(text) if s.startswith(("NSE_INDEX:", "BSE_INDEX:"))]):
        dsl["universe"] = {"symbols": idx[:1]}
        notes.append("an index cannot be traded directly — use its futures for live deployment")
    tf = nlu.find_interval(text, default=dsl["timeframe"])
    dsl["timeframe"] = tf if tf != "1w" else "1d"
    if dsl["timeframe"] == "1d":
        dsl["product"] = "CNC"
        dsl["schedule"] = {"entry_after": None, "entry_before": None, "square_off": None}
        if "short" in dsl.get("entry", {}) and "long only" not in low:
            dsl["entry"].pop("short", None)
            dsl["exit"].pop("short", None)
            notes.append("short entries removed: overnight cash-market shorts are not allowed in India")
    elif re.search(r"intraday|\bmis\b", low) or dsl["timeframe"] in ("1m", "3m", "5m", "15m", "30m"):
        dsl["product"] = "MIS"
        dsl.setdefault("schedule", {})["square_off"] = dsl.get("schedule", {}).get("square_off") or "15:15"
    sl = _num(r"(?:stop[- ]?loss|\bsl\b)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%", low) or _num(r"(\d+(?:\.\d+)?)\s*%\s*(?:stop|sl)\b", low)
    tgt = _num(r"(?:target|take[- ]?profit|tp)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%", low) or _num(r"(\d+(?:\.\d+)?)\s*%\s*target", low)
    if sl:
        dsl["exit"]["stop_loss"] = {"type": "percent", "value": sl}
    if tgt:
        dsl["exit"]["target"] = {"type": "percent", "value": tgt}
    if "trailing" in low:
        dsl["exit"]["trailing_sl"] = {"type": "percent", "value": sl or 1.0, "activate_after": 0.5}
    syms = ", ".join(nlu.underlying_of(s) for s in dsl["universe"].get("symbols", []))
    dsl["name"] = f"{base} on {syms}"[:120] if syms else base
    dsl["description"] = f"Drafted from: {text[:200]}"
    dsl["tags"] = [*(t for t in dsl.get("tags", []) if t != "template"), "copilot"][:10]
    ex = dsl["exit"]
    expl = (f"{base} on {syms or 'the template universe'} using {dsl['timeframe']} bars ({dsl['product']})"
            + (f", stop-loss {ex['stop_loss']['value']}{'%' if ex['stop_loss']['type'] == 'percent' else ' ' + ex['stop_loss']['type']}" if ex.get("stop_loss") else "")
            + (f", target {ex['target']['value']}%" if ex.get("target") else "")
            + (", trailing stop" if ex.get("trailing_sl") else "") + ".")
    return dsl, expl + (" Note: " + "; ".join(notes) + "." if notes else "")
