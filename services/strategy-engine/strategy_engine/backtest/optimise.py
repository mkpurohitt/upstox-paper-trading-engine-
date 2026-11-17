"""Parameter optimisation (grid / random) with overfitting diagnostics.

Diagnostics:
* too few trades in the best configuration,
* in-sample vs out-of-sample degradation (if an OOS split is requested),
* parameter-neighbourhood instability (the optimum is an isolated spike),
* multiple-testing haircut: deflated Sharpe ratio (Bailey & Lopez de Prado, 2014).
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

from strategy_engine.backtest.engine import BacktestParams
from strategy_engine.backtest.metrics import compute_metrics
from strategy_engine.backtest.vectorised import run_vectorised
from strategy_engine.dsl import StrategyDSL, set_path

Objective = str  # sharpe | cagr_pct | calmar | profit_factor | net_pnl | sortino
MAX_COMBOS = 400


def expand_space(space: list[dict[str, Any]]) -> list[tuple[str, list[Any]]]:
    out = []
    for p in space:
        if p.get("values"):
            vals = list(p["values"])
        else:
            lo, hi, step = float(p["min"]), float(p["max"]), float(p.get("step") or 1)
            vals = list(np.round(np.arange(lo, hi + step / 2, step), 6))
            if all(float(v).is_integer() for v in vals):
                vals = [int(v) for v in vals]
        out.append((p["path"], vals))
    return out


def _score(m: dict[str, Any], objective: Objective) -> float:
    v = m.get(objective)
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return -1e9
    return float(v)


def deflated_sharpe(sharpe_best: float, sharpes: list[float], n_obs: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """Probability that the best Sharpe is genuinely > 0 after selecting among N trials."""
    n = len(sharpes)
    if n < 2 or n_obs < 10:
        return float("nan")
    sd = float(np.std(sharpes, ddof=1)) or 1e-9
    emc = 0.5772156649
    sr0 = sd * ((1 - emc) * norm.ppf(1 - 1 / n) + emc * norm.ppf(1 - 1 / (n * math.e)))
    sr, sr0d = sharpe_best / math.sqrt(252), sr0 / math.sqrt(252)  # per-period
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    return float(norm.cdf((sr - sr0d) * math.sqrt(n_obs - 1) / denom))


def optimise(
    dsl: StrategyDSL,
    params: BacktestParams,
    frames: dict[str, pd.DataFrame],
    space: list[dict[str, Any]],
    *,
    method: str = "grid",
    objective: Objective = "sharpe",
    n_random: int = 60,
    oos_fraction: float = 0.3,
    progress: Callable[[float, str], None] | None = None,
    seed: int = 7,
) -> dict[str, Any]:
    dims = expand_space(space)
    if not dims:
        raise ValueError("parameter space is empty")
    combos = list(itertools.product(*[v for _, v in dims]))
    if method == "random" or len(combos) > MAX_COMBOS:
        rnd = random.Random(seed)
        combos = rnd.sample(combos, min(len(combos), n_random if method == "random" else MAX_COMBOS))
    # in-sample / out-of-sample split by time
    split_frames_is, split_frames_oos = {}, {}
    for s, df in frames.items():
        cut = int(len(df) * (1 - oos_fraction)) if oos_fraction > 0 else len(df)
        split_frames_is[s], split_frames_oos[s] = df.iloc[:cut], df.iloc[cut:]
    base = dsl.model_dump(mode="json")
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for k, combo in enumerate(combos):
        cfg = base
        for (path, _), val in zip(dims, combo, strict=True):
            cfg = set_path(cfg, path, val)
        try:
            cand = StrategyDSL.model_validate(cfg)
        except Exception as exc:  # parameter combination violates DSL bounds -> skip it
            skipped.append(str(exc).splitlines()[0][:120])
            continue
        res = run_vectorised(cand, params, split_frames_is)
        m = compute_metrics(res.equity, res.trades, params.initial_capital, params.risk_free)
        rows.append({"params": {p: v for (p, _), v in zip(dims, combo, strict=True)}, "metrics": m,
                     "score": _score(m, objective), "_cfg": cfg})
        if progress:
            progress((k + 1) / len(combos) * 0.9, f"{k + 1}/{len(combos)} combinations")
    if not rows:
        raise ValueError("no valid parameter combinations")
    rows.sort(key=lambda r: -r["score"])
    best = rows[0]
    warnings: list[str] = []
    if skipped:
        warnings.append(f"{len(skipped)} parameter combinations were invalid and skipped (e.g. {skipped[0]}).")
    oos_metrics = None
    if oos_fraction > 0 and all(len(f) > 20 for f in split_frames_oos.values()):
        oos = run_vectorised(StrategyDSL.model_validate(best["_cfg"]), params, split_frames_oos)
        oos_metrics = compute_metrics(oos.equity, oos.trades, params.initial_capital, params.risk_free)
        is_s, oos_s = best["metrics"].get("sharpe") or 0, oos_metrics.get("sharpe") or 0
        if is_s > 0 and oos_s < 0.5 * is_s:
            warnings.append(f"Out-of-sample Sharpe ({oos_s:.2f}) is less than half of in-sample ({is_s:.2f}) - likely overfit.")
    if (best["metrics"].get("trades") or 0) < 30:
        warnings.append(f"Best configuration has only {best['metrics'].get('trades', 0)} trades - statistically weak.")
    # neighbourhood stability
    if len(dims) >= 1 and len(rows) > 4:
        def dist(a: dict[str, Any], b: dict[str, Any]) -> float:
            return sum(abs(float(a[p]) - float(b[p])) / (max(float(x) for x in vals) - min(float(x) for x in vals) or 1)
                       for p, vals in dims if isinstance(a[p], int | float))
        neigh = sorted(rows[1:], key=lambda r: dist(r["params"], best["params"]))[: max(2, len(rows) // 10)]
        med = float(np.median([r["score"] for r in neigh]))
        if best["score"] > 0 and med < 0.5 * best["score"]:
            warnings.append("Optimum is an isolated spike: neighbouring parameters perform much worse (fragile).")
    sharpes = [r["metrics"].get("sharpe") or 0.0 for r in rows]
    n_obs = int(best["metrics"].get("trading_days") or 0)
    dsr = deflated_sharpe(best["metrics"].get("sharpe") or 0.0, sharpes, n_obs)
    if math.isfinite(dsr) and dsr < 0.95:
        warnings.append(f"Deflated Sharpe probability {dsr:.2f} < 0.95 after testing {len(rows)} combinations (multiple-testing risk).")
    heatmap = None
    if len(dims) == 2:
        heatmap = {"x": dims[0][0], "y": dims[1][0], "cells": [
            {"x": r["params"][dims[0][0]], "y": r["params"][dims[1][0]], "value": r["score"] if r["score"] > -1e8 else None}
            for r in rows]}
    for r in rows:
        r.pop("_cfg", None)
    return {
        "objective": objective, "method": method, "combinations": len(rows), "best": best, "results": rows[:200],
        "oos_metrics": oos_metrics, "oos_fraction": oos_fraction, "deflated_sharpe_prob": None if not math.isfinite(dsr) else round(dsr, 3),
        "warnings": warnings, "heatmap": heatmap,
    }
