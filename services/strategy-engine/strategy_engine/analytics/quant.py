"""Quantitative dashboard: distribution, VaR/CVaR, volatility regimes, correlation, beta, seasonality."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from market_data.base import MarketDataProvider
from strategy_engine.analytics.technical import frame_for


async def closes(provider: MarketDataProvider, symbols: list[str], days: int) -> pd.DataFrame:
    out = {}
    for s in symbols:
        df = await frame_for(provider, s, "1d", days)
        if not df.empty:
            out[s] = df["close"]
    frame = pd.DataFrame(out)
    frame.index = frame.index.tz_convert("Asia/Kolkata").normalize()
    return frame.groupby(level=0).last().dropna(how="all")


async def quant_dashboard(provider: MarketDataProvider, symbol: str, basket: list[str], benchmark: str = "NSE_INDEX:NIFTY",
                          days: int = 1095) -> dict[str, Any]:
    syms = list(dict.fromkeys([symbol, benchmark, *basket]))
    px = await closes(provider, syms, days)
    r = np.log(px).diff().dropna(how="all")
    s = r[symbol].dropna()
    hist, edges = np.histogram(s * 100, bins=40)
    mu, sd = float(s.mean()), float(s.std(ddof=1))
    normal = [float(len(s) * (edges[i + 1] - edges[i]) * stats.norm.pdf((edges[i] + edges[i + 1]) / 2, mu * 100, sd * 100)) for i in range(len(hist))]
    var95, var99 = float(np.percentile(s, 5)), float(np.percentile(s, 1))
    cvar95 = float(s[s <= var95].mean())
    vol = s.rolling(20).std() * math.sqrt(252) * 100
    lo, hi = vol.quantile(0.33), vol.quantile(0.66)
    regime = vol.apply(lambda v: None if pd.isna(v) else ("low" if v < lo else "high" if v > hi else "normal"))
    b = r[benchmark].dropna()
    joined = pd.concat([s, b], axis=1, join="inner").dropna()
    cov = joined.cov().iloc[0, 1]
    beta = float(cov / joined.iloc[:, 1].var()) if len(joined) > 20 else None
    roll_beta = (joined.iloc[:, 0].rolling(60).cov(joined.iloc[:, 1]) / joined.iloc[:, 1].rolling(60).var()).dropna()
    corr = r[[c for c in syms if c in r]].corr().round(3)
    monthly = px[symbol].resample("ME").last().pct_change().dropna() * 100
    by_month = monthly.groupby(monthly.index.month).agg(["mean", "count", lambda x: (x > 0).mean() * 100])
    by_month.columns = ["mean", "count", "hit_rate"]
    dow = s.groupby(s.index.dayofweek).agg(["mean", "count"])
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return {
        "symbol": symbol, "benchmark": benchmark, "observations": len(s),
        "stats": {"mean_daily_pct": round(mu * 100, 4), "ann_return_pct": round(mu * 252 * 100, 2),
                  "ann_vol_pct": round(sd * math.sqrt(252) * 100, 2), "skew": round(float(stats.skew(s)), 3),
                  "excess_kurtosis": round(float(stats.kurtosis(s)), 3), "var95_pct": round(var95 * 100, 3),
                  "var99_pct": round(var99 * 100, 3), "cvar95_pct": round(cvar95 * 100, 3),
                  "jarque_bera_p": round(float(stats.jarque_bera(s).pvalue), 4), "beta": round(beta, 3) if beta is not None else None,
                  "current_vol_pct": round(float(vol.iloc[-1]), 2) if len(vol.dropna()) else None,
                  "current_regime": regime.iloc[-1] if len(regime) else None},
        "histogram": [{"bin": round(float((edges[i] + edges[i + 1]) / 2), 3), "count": int(hist[i]), "normal": round(normal[i], 2)} for i in range(len(hist))],
        "vol_regimes": [{"ts": ts.isoformat(), "vol": round(float(v), 2), "regime": regime.loc[ts]} for ts, v in vol.dropna().items()],
        "regime_thresholds": {"low": round(float(lo), 2), "high": round(float(hi), 2)},
        "rolling_beta": [{"ts": ts.isoformat(), "beta": round(float(v), 3)} for ts, v in roll_beta.items()],
        "correlation": {"symbols": list(corr.columns), "matrix": corr.fillna(0).values.tolist()},
        "seasonality_month": [{"month": months[m - 1], "mean_pct": round(float(row["mean"]), 2), "hit_rate_pct": round(float(row["hit_rate"]), 1),
                               "years": int(row["count"])} for m, row in by_month.iterrows()],
        "seasonality_dow": [{"day": ["Mon", "Tue", "Wed", "Thu", "Fri"][int(d)], "mean_pct": round(float(row["mean"]) * 100, 4), "count": int(row["count"])}
                            for d, row in dow.iterrows() if int(d) < 5],
    }
