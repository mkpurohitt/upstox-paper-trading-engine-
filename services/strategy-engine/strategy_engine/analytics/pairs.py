"""Pair trading analytics: Engle-Granger & Johansen cointegration, hedge ratio, spread z-score, half-life."""

from __future__ import annotations

import itertools
import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.tsa.vector_ar.vecm import coint_johansen

from market_data.base import MarketDataProvider
from market_data.universe import EQUITIES
from strategy_engine.analytics.quant import closes


def half_life(spread: pd.Series) -> float | None:
    lag = spread.shift(1).dropna()
    delta = spread.diff().dropna()
    lag, delta = lag.align(delta, join="inner")
    if len(lag) < 20:
        return None
    beta = sm.OLS(delta, sm.add_constant(lag)).fit().params.iloc[1]
    return round(float(-math.log(2) / beta), 2) if beta < 0 else None


def analyse_pair(a: pd.Series, b: pd.Series, lookback: int = 60, entry_z: float = 2.0, exit_z: float = 0.5) -> dict[str, Any]:
    df = pd.concat({"a": np.log(a), "b": np.log(b)}, axis=1).dropna()
    eg_t, eg_p, eg_crit = coint(df["a"], df["b"])
    ols = sm.OLS(df["a"], sm.add_constant(df["b"])).fit()
    hedge = float(ols.params.iloc[1])
    spread = df["a"] - hedge * df["b"] - float(ols.params.iloc[0])
    z = (spread - spread.rolling(lookback).mean()) / spread.rolling(lookback).std(ddof=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # statsmodels complex-cast / API-transition warnings
        jo = coint_johansen(df[["a", "b"]], det_order=0, k_ar_diff=1)
        adf_p = float(adfuller(spread.dropna())[1])
    zi = float(z.iloc[-1]) if len(z.dropna()) else 0.0
    signal = "short spread (sell A, buy B)" if zi >= entry_z else "long spread (buy A, sell B)" if zi <= -entry_z else (
        "exit / flat" if abs(zi) <= exit_z else "hold / wait")
    return {
        "engle_granger": {"t_stat": round(float(eg_t), 3), "p_value": round(float(eg_p), 4),
                          "crit_values": {"1%": round(float(eg_crit[0]), 3), "5%": round(float(eg_crit[1]), 3), "10%": round(float(eg_crit[2]), 3)},
                          "cointegrated_5pct": bool(eg_p < 0.05)},
        "johansen": {"trace_stat": [round(float(x), 3) for x in jo.lr1], "trace_crit_95": [round(float(x), 3) for x in jo.cvt[:, 1]],
                     "max_eig_stat": [round(float(x), 3) for x in jo.lr2], "max_eig_crit_95": [round(float(x), 3) for x in jo.cvm[:, 1]],
                     "rank_95": int(sum(jo.lr1[i] > jo.cvt[i, 1] for i in range(2)))},
        "hedge_ratio": round(hedge, 4), "spread_adf_p": round(adf_p, 4), "half_life_days": half_life(spread),
        "correlation": round(float(df["a"].diff().corr(df["b"].diff())), 3),
        "current_z": round(zi, 3), "signal": signal, "entry_z": entry_z, "exit_z": exit_z, "lookback": lookback,
        "series": [{"ts": ts.isoformat(), "a": round(float(math.exp(df.loc[ts, "a"])), 2), "b": round(float(math.exp(df.loc[ts, "b"])), 2),
                    "spread": round(float(spread.loc[ts]), 5), "z": None if pd.isna(z.loc[ts]) else round(float(z.loc[ts]), 3)}
                   for ts in df.index],
    }


async def pair_dashboard(provider: MarketDataProvider, a: str, b: str, days: int = 730, lookback: int = 60) -> dict[str, Any]:
    px = (await closes(provider, [a, b], days)).dropna()
    return {"a": a, "b": b, **analyse_pair(px[a], px[b], lookback)}


async def scan_pairs(provider: MarketDataProvider, sector: str | None = None, days: int = 500, limit: int = 15) -> list[dict[str, Any]]:
    syms = [e.symbol for e in EQUITIES if sector is None or e.sector == sector][:20]
    px = (await closes(provider, syms, days)).dropna(axis=1, how="any")
    out = []
    for x, y in itertools.combinations(px.columns, 2):
        la, lb = np.log(px[x]), np.log(px[y])
        try:
            _, p, _ = coint(la, lb)
        except Exception:  # noqa: S112
            continue
        out.append({"a": x, "b": y, "p_value": round(float(p), 4), "correlation": round(float(la.diff().corr(lb.diff())), 3)})
    out.sort(key=lambda r: r["p_value"])
    return out[:limit]
