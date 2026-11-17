"""Compile a StrategyDSL into vectorised boolean signals over an OHLCV frame.

The backtester (both modes) and the live runner use exactly this code path,
so a strategy behaves identically in research and production.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from strategy_engine import indicators as ind
from strategy_engine.dsl import (
    CompareCondition,
    DayCondition,
    GroupCondition,
    IndicatorOperand,
    PatternCondition,
    PriceOperand,
    StrategyDSL,
    TimeCondition,
)
from strategy_engine.patterns import detect

CustomRunner = Callable[[str, pd.DataFrame, dict[str, Any]], pd.Series]
_DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}


def ist_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return idx.tz_convert("Asia/Kolkata")


def compute_indicators(df: pd.DataFrame, dsl: StrategyDSL, custom_runner: CustomRunner | None = None) -> pd.DataFrame:
    """Return a frame of indicator columns named ``id`` or ``id.output``."""
    cols: dict[str, pd.Series] = {}
    for spec in dsl.indicators:
        if spec.kind == "CUSTOM":
            if custom_runner is None:
                from strategy_engine.sandbox import run_custom_indicator

                custom_runner = run_custom_indicator
            cols[spec.id] = custom_runner(spec.code or "", df, dict(spec.params)).reindex(df.index)
            continue
        res = ind.compute(df, spec.kind, dict(spec.params), spec.source)
        if len(res.columns) == 1:
            cols[spec.id] = res.iloc[:, 0]
        else:
            for c in res.columns:
                cols[f"{spec.id}.{c}"] = res[c]
    return pd.DataFrame(cols, index=df.index)


def _price(df: pd.DataFrame, field: str) -> pd.Series:
    return ind.src(df, field) if field in ("hl2", "hlc3", "ohlc4") else df[field].astype(float)


def _operand(o: Any, df: pd.DataFrame, inds: pd.DataFrame) -> pd.Series:
    if isinstance(o, IndicatorOperand):
        s = inds[o.ref]
        return s.shift(o.offset) if o.offset else s
    if isinstance(o, PriceOperand):
        s = _price(df, o.field)
        return s.shift(o.offset) if o.offset else s
    return pd.Series(float(o.value), index=df.index)


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def evaluate(cond: Any, df: pd.DataFrame, inds: pd.DataFrame) -> pd.Series:
    if isinstance(cond, GroupCondition):
        if not cond.conditions:
            return pd.Series(cond.kind == "all", index=df.index)
        parts = [evaluate(c, df, inds) for c in cond.conditions]
        out = parts[0]
        for p in parts[1:]:
            out = (out & p) if cond.kind == "all" else (out | p)
        return out
    if isinstance(cond, CompareCondition):
        a, b = _operand(cond.left, df, inds), _operand(cond.right, df, inds)
        valid = a.notna() & b.notna()
        op = cond.op
        if op == ">":
            r = a > b
        elif op == "<":
            r = a < b
        elif op == ">=":
            r = a >= b
        elif op == "<=":
            r = a <= b
        elif op == "==":
            r = np.isclose(a, b)
            r = pd.Series(r, index=df.index)
        elif op == "crosses_above":
            r = (a > b) & (a.shift() <= b.shift())
            valid &= a.shift().notna() & b.shift().notna()
        else:
            r = (a < b) & (a.shift() >= b.shift())
            valid &= a.shift().notna() & b.shift().notna()
        return (r & valid).astype(bool)
    if isinstance(cond, TimeCondition):
        idx = ist_index(df)
        mins = pd.Series(idx.hour * 60 + idx.minute, index=df.index)
        r = pd.Series(True, index=df.index)
        if cond.after:
            r &= mins >= _hhmm(cond.after)
        if cond.before:
            r &= mins < _hhmm(cond.before)
        return r
    if isinstance(cond, DayCondition):
        idx = ist_index(df)
        allowed = {_DAYS[d] for d in cond.days}
        return pd.Series(np.isin(idx.dayofweek, list(allowed)), index=df.index)
    if isinstance(cond, PatternCondition):
        return detect(df, cond.name, cond.lookback)
    raise TypeError(f"unsupported condition {type(cond).__name__}")


def generate_signals(df: pd.DataFrame, dsl: StrategyDSL, custom_runner: CustomRunner | None = None) -> pd.DataFrame:
    """Columns: entry_long, entry_short, exit_long, exit_short (+ indicator columns)."""
    inds = compute_indicators(df, dsl, custom_runner)
    false = pd.Series(False, index=df.index)
    out = pd.DataFrame(index=df.index)
    out["entry_long"] = evaluate(dsl.entry.long, df, inds) if dsl.entry.long else false
    out["entry_short"] = evaluate(dsl.entry.short, df, inds) if dsl.entry.short else false
    out["exit_long"] = evaluate(dsl.exit.long, df, inds) if dsl.exit.long else false
    out["exit_short"] = evaluate(dsl.exit.short, df, inds) if dsl.exit.short else false
    for c in inds.columns:
        out[f"ind:{c}"] = inds[c]
    return out


def warmup_bars(dsl: StrategyDSL) -> int:
    """Bars needed before indicators stabilise (used by live runner history fetch)."""
    n = 50
    for spec in dsl.indicators:
        for v in spec.params.values():
            if isinstance(v, int | float):
                n = max(n, int(v) * 3)
    return min(n, 1500)
