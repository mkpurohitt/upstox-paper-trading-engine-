"""Candlestick / price-action pattern detection and support-resistance levels."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


def _range(df: pd.DataFrame) -> pd.Series:
    return (df["high"] - df["low"]).replace(0, np.nan)


def detect(df: pd.DataFrame, name: str, lookback: int = 20) -> pd.Series:
    o, h, lo, c = df["open"], df["high"], df["low"], df["close"]
    body, rng = _body(df), _range(df)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - lo
    bull, bear = c > o, c < o
    po, pc = o.shift(), c.shift()
    if name == "doji":
        out = body <= 0.1 * rng
    elif name == "hammer":
        out = (lower >= 2 * body) & (upper <= 0.3 * body + 0.1 * rng) & (c.rolling(5).mean().shift() > c)
    elif name == "inverted_hammer":
        out = (upper >= 2 * body) & (lower <= 0.3 * body + 0.1 * rng) & (c.rolling(5).mean().shift() > c)
    elif name == "shooting_star":
        out = (upper >= 2 * body) & (lower <= 0.3 * body + 0.1 * rng) & (c.rolling(5).mean().shift() < c)
    elif name == "bullish_engulfing":
        out = bull & (pc < po) & (c >= po) & (o <= pc)
    elif name == "bearish_engulfing":
        out = bear & (pc > po) & (o >= pc) & (c <= po)
    elif name == "morning_star":
        o2, c2 = o.shift(2), c.shift(2)
        out = (c2 < o2) & (_body(df).shift() < 0.3 * (o2 - c2)) & bull & (c > (o2 + c2) / 2)
    elif name == "evening_star":
        o2, c2 = o.shift(2), c.shift(2)
        out = (c2 > o2) & (_body(df).shift() < 0.3 * (c2 - o2)) & bear & (c < (o2 + c2) / 2)
    elif name == "inside_bar":
        out = (h < h.shift()) & (lo > lo.shift())
    elif name == "outside_bar":
        out = (h > h.shift()) & (lo < lo.shift())
    elif name == "three_white_soldiers":
        out = bull & bull.shift() & bull.shift(2) & (c > c.shift()) & (c.shift() > c.shift(2))
    elif name == "three_black_crows":
        out = bear & bear.shift() & bear.shift(2) & (c < c.shift()) & (c.shift() < c.shift(2))
    elif name == "breakout_high":
        out = c > h.shift().rolling(lookback).max()
    elif name == "breakdown_low":
        out = c < lo.shift().rolling(lookback).min()
    elif name == "gap_up":
        out = o > h.shift() * 1.002
    elif name == "gap_down":
        out = o < lo.shift() * 0.998
    else:
        raise ValueError(f"unknown pattern {name}")
    return out.fillna(False).astype(bool)


PATTERNS = ["doji", "hammer", "inverted_hammer", "shooting_star", "bullish_engulfing", "bearish_engulfing",
            "morning_star", "evening_star", "inside_bar", "outside_bar", "three_white_soldiers", "three_black_crows",
            "breakout_high", "breakdown_low", "gap_up", "gap_down"]
BULLISH = {"hammer", "inverted_hammer", "bullish_engulfing", "morning_star", "three_white_soldiers", "breakout_high", "gap_up"}


def scan_patterns(df: pd.DataFrame, last_n: int = 30) -> list[dict[str, Any]]:
    out = []
    tail = df.tail(last_n)
    for name in PATTERNS:
        hits = detect(df, name).reindex(tail.index)
        for ts in hits[hits].index:
            out.append({"ts": ts.isoformat(), "pattern": name, "bias": "bullish" if name in BULLISH else
                        ("neutral" if name in ("doji", "inside_bar", "outside_bar") else "bearish"),
                        "price": float(df.loc[ts, "close"])})
    out.sort(key=lambda x: x["ts"])
    return out


def support_resistance(df: pd.DataFrame, window: int = 5, tolerance_pct: float = 0.6, max_levels: int = 6) -> list[dict[str, Any]]:
    """Swing-pivot clustering: levels touched most often, weighted by recency."""
    h, lo = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    pts: list[tuple[float, int, str]] = []
    for i in range(window, n - window):
        if h[i] == h[i - window : i + window + 1].max():
            pts.append((h[i], i, "R"))
        if lo[i] == lo[i - window : i + window + 1].min():
            pts.append((lo[i], i, "S"))
    pts.sort()
    clusters: list[list[tuple[float, int, str]]] = []
    for p in pts:
        if clusters and abs(p[0] - clusters[-1][-1][0]) / p[0] * 100 <= tolerance_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    last = float(df["close"].iloc[-1]) if n else 0.0
    levels: list[dict[str, Any]] = []
    for cl in clusters:
        price = float(np.mean([x[0] for x in cl]))
        strength = sum(0.5 + i / n for _, i, _ in cl)
        levels.append({"price": round(price, 2), "touches": len(cl), "strength": round(strength, 2),
                       "type": "resistance" if price > last else "support"})
    levels.sort(key=lambda x: -x["strength"])
    return sorted(levels[:max_levels], key=lambda x: x["price"])
