"""Monte Carlo resampling of a trade sequence (shuffle or bootstrap)."""

from __future__ import annotations

from typing import Any

import numpy as np


def monte_carlo(
    trade_pnls: list[float], initial_capital: float, *, runs: int = 1000, method: str = "bootstrap",
    ruin_pct: float = 50.0, seed: int = 11, sample_paths: int = 25,
) -> dict[str, Any]:
    pnl = np.asarray(trade_pnls, dtype=float)
    if len(pnl) < 5:
        raise ValueError("need at least 5 trades for a Monte Carlo simulation")
    rng = np.random.default_rng(seed)
    n = len(pnl)
    if method == "shuffle":
        sims = np.array([rng.permutation(pnl) for _ in range(runs)])
    else:
        sims = rng.choice(pnl, size=(runs, n), replace=True)
    paths = initial_capital + np.cumsum(sims, axis=1)
    paths = np.concatenate([np.full((runs, 1), initial_capital), paths], axis=1)
    peaks = np.maximum.accumulate(paths, axis=1)
    dd = (paths / peaks - 1).min(axis=1) * 100
    final = paths[:, -1]
    ruin_level = initial_capital * (1 - ruin_pct / 100)
    ruined = (paths.min(axis=1) <= ruin_level).mean()
    pct = [5, 25, 50, 75, 95]
    bands = {f"p{p}": np.percentile(paths, p, axis=0).round(2).tolist() for p in pct}
    return {
        "runs": runs, "method": method, "trades": n,
        "final_equity": {f"p{p}": round(float(np.percentile(final, p)), 2) for p in pct},
        "max_drawdown_pct": {f"p{p}": round(float(np.percentile(dd, 100 - p)), 2) for p in pct},
        "probability_of_profit": round(float((final > initial_capital).mean()), 4),
        "risk_of_ruin": round(float(ruined), 4), "ruin_threshold_pct": ruin_pct,
        "bands": bands,
        "sample_paths": paths[rng.choice(runs, size=min(sample_paths, runs), replace=False)].round(2).tolist(),
    }
