"""Technical indicators (pandas / numpy; TA-Lib used transparently when installed).

All functions take an OHLCV DataFrame (columns open/high/low/close/volume,
DatetimeIndex in UTC) and return a Series, or a DataFrame whose columns are the
indicator's named outputs. Wilder smoothing is used where the canonical
definition requires it (RSI, ATR, ADX).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

try:  # optional acceleration
    import talib as _talib  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - TA-Lib is optional
    _talib = None

IST = "Asia/Kolkata"


def src(df: pd.DataFrame, source: str = "close") -> pd.Series:
    if source == "hl2":
        return (df["high"] + df["low"]) / 2
    if source == "hlc3":
        return (df["high"] + df["low"] + df["close"]) / 3
    if source == "ohlc4":
        return (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    return df[source].astype(float)


def _wilder(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def sma(df: pd.DataFrame, source: str = "close", period: int = 20) -> pd.Series:
    if _talib is not None:
        return pd.Series(_talib.SMA(src(df, source).to_numpy(float), int(period)), index=df.index)
    return src(df, source).rolling(int(period), min_periods=int(period)).mean()


def ema(df: pd.DataFrame, source: str = "close", period: int = 20) -> pd.Series:
    return src(df, source).ewm(span=int(period), adjust=False, min_periods=int(period)).mean()


def wma(df: pd.DataFrame, source: str = "close", period: int = 20) -> pd.Series:
    p = int(period)
    w = np.arange(1, p + 1, dtype=float)
    return src(df, source).rolling(p).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)


def vwap(df: pd.DataFrame, source: str = "hlc3") -> pd.Series:
    """Session-anchored VWAP (resets every IST trading day)."""
    tp = src(df, source)
    pv = tp * df["volume"]
    day = df.index.tz_convert(IST).date if df.index.tz is not None else df.index.date
    cum_pv = pv.groupby(day).cumsum()
    cum_v = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return (cum_pv / cum_v).fillna(tp)


def rsi(df: pd.DataFrame, source: str = "close", period: int = 14) -> pd.Series:
    s = src(df, source)
    if _talib is not None:
        return pd.Series(_talib.RSI(s.to_numpy(float), int(period)), index=df.index)
    d = s.diff()
    up = _wilder(d.clip(lower=0), int(period))
    dn = _wilder(-d.clip(upper=0), int(period))
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0)


def macd(df: pd.DataFrame, source: str = "close", fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    s = src(df, source)
    m = s.ewm(span=int(fast), adjust=False).mean() - s.ewm(span=int(slow), adjust=False).mean()
    sig = m.ewm(span=int(signal), adjust=False).mean()
    out = pd.DataFrame({"macd": m, "signal": sig, "hist": m - sig}, index=df.index)
    out.iloc[: int(slow)] = np.nan
    return out


def bbands(df: pd.DataFrame, source: str = "close", period: int = 20, std: float = 2.0) -> pd.DataFrame:
    s = src(df, source)
    mid = s.rolling(int(period)).mean()
    sd = s.rolling(int(period)).std(ddof=0)
    up, lo = mid + std * sd, mid - std * sd
    return pd.DataFrame({"upper": up, "middle": mid, "lower": lo, "width": (up - lo) / mid * 100,
                         "pct_b": (s - lo) / (up - lo)}, index=df.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift()
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, source: str = "close", period: int = 14) -> pd.Series:
    return _wilder(true_range(df), int(period))


def supertrend(df: pd.DataFrame, source: str = "close", period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    a = atr(df, period=int(period)).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    upper = hl2 + multiplier * a
    lower = hl2 - multiplier * a
    st = np.full(n, np.nan)
    direction = np.zeros(n)
    fu, fl = upper.copy(), lower.copy()
    for i in range(1, n):
        if np.isnan(a[i]):
            continue
        fu[i] = upper[i] if (upper[i] < fu[i - 1] or close[i - 1] > fu[i - 1] or np.isnan(fu[i - 1])) else fu[i - 1]
        fl[i] = lower[i] if (lower[i] > fl[i - 1] or close[i - 1] < fl[i - 1] or np.isnan(fl[i - 1])) else fl[i - 1]
        prev_dir = direction[i - 1] if direction[i - 1] != 0 else 1
        if prev_dir == 1:
            direction[i] = -1 if close[i] < fl[i] else 1
        else:
            direction[i] = 1 if close[i] > fu[i] else -1
        st[i] = fl[i] if direction[i] == 1 else fu[i]
    return pd.DataFrame({"value": st, "direction": np.where(np.isnan(st), np.nan, direction)}, index=df.index)


def adx(df: pd.DataFrame, source: str = "close", period: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = _wilder(true_range(df), int(period))
    pdi = 100 * _wilder(pd.Series(plus_dm, index=df.index), int(period)) / tr
    mdi = 100 * _wilder(pd.Series(minus_dm, index=df.index), int(period)) / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"adx": _wilder(dx, int(period)), "plus_di": pdi, "minus_di": mdi}, index=df.index)


def stoch(df: pd.DataFrame, source: str = "close", k: int = 14, d: int = 3, smooth: int = 3) -> pd.DataFrame:
    ll = df["low"].rolling(int(k)).min()
    hh = df["high"].rolling(int(k)).max()
    raw = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    kk = raw.rolling(int(smooth)).mean()
    return pd.DataFrame({"k": kk, "d": kk.rolling(int(d)).mean()}, index=df.index)


def cci(df: pd.DataFrame, source: str = "hlc3", period: int = 20) -> pd.Series:
    tp = src(df, source)
    ma = tp.rolling(int(period)).mean()
    md = tp.rolling(int(period)).apply(lambda x: float(np.mean(np.abs(x - x.mean()))), raw=True)
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def obv(df: pd.DataFrame, source: str = "close") -> pd.Series:
    sign = np.sign(df["close"].diff().fillna(0))
    return (sign * df["volume"]).cumsum()


def ichimoku(df: pd.DataFrame, source: str = "close", tenkan: int = 9, kijun: int = 26, senkou: int = 52) -> pd.DataFrame:
    def mid(n: int) -> pd.Series:
        return (df["high"].rolling(n).max() + df["low"].rolling(n).min()) / 2

    t, k = mid(int(tenkan)), mid(int(kijun))
    return pd.DataFrame({
        "tenkan": t, "kijun": k,
        "senkou_a": ((t + k) / 2).shift(int(kijun)),
        "senkou_b": mid(int(senkou)).shift(int(kijun)),
        "chikou": df["close"].shift(-int(kijun)),
    }, index=df.index)


def _daily_prev(df: pd.DataFrame) -> pd.DataFrame:
    """Previous IST session's H/L/C aligned to each bar."""
    idx = df.index.tz_convert(IST) if df.index.tz is not None else df.index
    day = pd.Series(idx.date, index=df.index)
    g = df.groupby(day.values)
    daily = pd.DataFrame({"h": g["high"].max(), "l": g["low"].min(), "c": g["close"].last()}).shift(1)
    return daily.reindex(day.values).set_axis(df.index)


def pivots(df: pd.DataFrame, source: str = "close") -> pd.DataFrame:
    p = _daily_prev(df)
    pp = (p["h"] + p["l"] + p["c"]) / 3
    rng = p["h"] - p["l"]
    return pd.DataFrame({
        "pp": pp, "r1": 2 * pp - p["l"], "s1": 2 * pp - p["h"], "r2": pp + rng, "s2": pp - rng,
        "r3": p["h"] + 2 * (pp - p["l"]), "s3": p["l"] - 2 * (p["h"] - pp),
    }, index=df.index)


def cpr(df: pd.DataFrame, source: str = "close") -> pd.DataFrame:
    p = _daily_prev(df)
    pivot = (p["h"] + p["l"] + p["c"]) / 3
    bc = (p["h"] + p["l"]) / 2
    tc = 2 * pivot - bc
    top, bottom = np.maximum(tc, bc), np.minimum(tc, bc)
    return pd.DataFrame({"pivot": pivot, "tc": top, "bc": bottom, "width_pct": (top - bottom) / pivot * 100}, index=df.index)


def heikin_ashi(df: pd.DataFrame, source: str = "close") -> pd.DataFrame:
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    ha_open = np.empty(len(df))
    if len(df):
        ha_open[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
    hc = ha_close.to_numpy()
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i - 1] + hc[i - 1]) / 2
    ho = pd.Series(ha_open, index=df.index)
    return pd.DataFrame({
        "open": ho, "close": ha_close,
        "high": pd.concat([df["high"], ho, ha_close], axis=1).max(axis=1),
        "low": pd.concat([df["low"], ho, ha_close], axis=1).min(axis=1),
    }, index=df.index)


def roc(df: pd.DataFrame, source: str = "close", period: int = 10) -> pd.Series:
    s = src(df, source)
    return (s / s.shift(int(period)) - 1) * 100


def donchian(df: pd.DataFrame, source: str = "close", period: int = 20) -> pd.DataFrame:
    up = df["high"].rolling(int(period)).max()
    lo = df["low"].rolling(int(period)).min()
    return pd.DataFrame({"upper": up, "lower": lo, "middle": (up + lo) / 2}, index=df.index)


def highest(df: pd.DataFrame, source: str = "high", period: int = 20) -> pd.Series:
    return src(df, source).rolling(int(period)).max()


def lowest(df: pd.DataFrame, source: str = "low", period: int = 20) -> pd.Series:
    return src(df, source).rolling(int(period)).min()


def volume_sma(df: pd.DataFrame, source: str = "volume", period: int = 20) -> pd.Series:
    return df["volume"].rolling(int(period)).mean()


def zscore(df: pd.DataFrame, source: str = "close", period: int = 20) -> pd.Series:
    s = src(df, source)
    return (s - s.rolling(int(period)).mean()) / s.rolling(int(period)).std(ddof=0)


def hv(df: pd.DataFrame, source: str = "close", period: int = 20) -> pd.Series:
    """Annualised close-to-close historical volatility in %."""
    r = np.log(src(df, source)).diff()
    return r.rolling(int(period)).std() * np.sqrt(252) * 100


@dataclass(frozen=True)
class IndicatorDef:
    name: str
    fn: Callable[..., pd.Series | pd.DataFrame]
    params: dict[str, tuple[float, float, float]] = field(default_factory=dict)  # name -> (default, min, max)
    outputs: list[str] = field(default_factory=lambda: ["value"])
    overlay: bool = False
    description: str = ""
    default_source: str = "close"


REGISTRY: dict[str, IndicatorDef] = {d.name: d for d in [
    IndicatorDef("SMA", sma, {"period": (20, 1, 500)}, overlay=True, description="Simple moving average"),
    IndicatorDef("EMA", ema, {"period": (20, 1, 500)}, overlay=True, description="Exponential moving average"),
    IndicatorDef("WMA", wma, {"period": (20, 1, 500)}, overlay=True, description="Weighted moving average"),
    IndicatorDef("VWAP", vwap, {}, overlay=True, description="Session VWAP (resets daily)", default_source="hlc3"),
    IndicatorDef("RSI", rsi, {"period": (14, 2, 100)}, description="Relative strength index (Wilder)"),
    IndicatorDef("MACD", macd, {"fast": (12, 2, 100), "slow": (26, 3, 200), "signal": (9, 2, 50)},
                 ["macd", "signal", "hist"], description="Moving average convergence divergence"),
    IndicatorDef("BBANDS", bbands, {"period": (20, 2, 200), "std": (2.0, 0.5, 5.0)},
                 ["upper", "middle", "lower", "width", "pct_b"], overlay=True, description="Bollinger bands"),
    IndicatorDef("SUPERTREND", supertrend, {"period": (10, 2, 100), "multiplier": (3.0, 0.5, 10.0)},
                 ["value", "direction"], overlay=True, description="Supertrend (direction +1/-1)"),
    IndicatorDef("ATR", atr, {"period": (14, 2, 100)}, description="Average true range (Wilder)"),
    IndicatorDef("ADX", adx, {"period": (14, 2, 100)}, ["adx", "plus_di", "minus_di"], description="Average directional index"),
    IndicatorDef("STOCH", stoch, {"k": (14, 2, 100), "d": (3, 1, 20), "smooth": (3, 1, 20)}, ["k", "d"],
                 description="Stochastic oscillator"),
    IndicatorDef("CCI", cci, {"period": (20, 2, 200)}, description="Commodity channel index", default_source="hlc3"),
    IndicatorDef("OBV", obv, {}, description="On-balance volume"),
    IndicatorDef("ICHIMOKU", ichimoku, {"tenkan": (9, 2, 100), "kijun": (26, 2, 200), "senkou": (52, 2, 300)},
                 ["tenkan", "kijun", "senkou_a", "senkou_b", "chikou"], overlay=True, description="Ichimoku cloud"),
    IndicatorDef("PIVOTS", pivots, {}, ["pp", "r1", "s1", "r2", "s2", "r3", "s3"], overlay=True,
                 description="Classic floor pivots from previous session"),
    IndicatorDef("CPR", cpr, {}, ["pivot", "tc", "bc", "width_pct"], overlay=True, description="Central pivot range"),
    IndicatorDef("HEIKIN_ASHI", heikin_ashi, {}, ["open", "high", "low", "close"], overlay=True, description="Heikin-Ashi candles"),
    IndicatorDef("ROC", roc, {"period": (10, 1, 500)}, description="Rate of change %"),
    IndicatorDef("DONCHIAN", donchian, {"period": (20, 2, 500)}, ["upper", "lower", "middle"], overlay=True,
                 description="Donchian channel"),
    IndicatorDef("HIGHEST", highest, {"period": (20, 1, 500)}, overlay=True, description="Highest high", default_source="high"),
    IndicatorDef("LOWEST", lowest, {"period": (20, 1, 500)}, overlay=True, description="Lowest low", default_source="low"),
    IndicatorDef("VOLUME_SMA", volume_sma, {"period": (20, 1, 500)}, description="Volume moving average", default_source="volume"),
    IndicatorDef("ZSCORE", zscore, {"period": (20, 2, 500)}, description="Rolling z-score of price"),
    IndicatorDef("HV", hv, {"period": (20, 2, 500)}, description="Historical volatility (annualised %)"),
]}


def compute(df: pd.DataFrame, kind: str, params: dict[str, Any] | None = None, source: str | None = None) -> pd.DataFrame:
    """Compute a registered indicator; always returns a DataFrame of outputs."""
    spec = REGISTRY[kind.upper()]
    kwargs = {k: v[0] for k, v in spec.params.items()}
    kwargs.update({k: v for k, v in (params or {}).items() if k in spec.params})
    for k, (d, _, _) in spec.params.items():
        if isinstance(d, int) and not isinstance(d, bool):
            kwargs[k] = int(kwargs[k])
    res = spec.fn(df, source=source or spec.default_source, **kwargs)
    if isinstance(res, pd.Series):
        return res.to_frame(spec.outputs[0])
    return res


def catalog() -> list[dict[str, Any]]:
    return [
        {"kind": d.name, "description": d.description, "outputs": d.outputs, "overlay": d.overlay,
         "default_source": d.default_source,
         "params": [{"name": k, "default": v[0], "min": v[1], "max": v[2]} for k, v in d.params.items()]}
        for d in REGISTRY.values()
    ] + [{"kind": "CUSTOM", "description": "Sandboxed Python: def compute(df, params) -> Series", "outputs": ["value"],
          "overlay": False, "default_source": "close", "params": []}]
