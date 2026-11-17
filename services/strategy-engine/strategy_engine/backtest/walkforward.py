"""Rolling walk-forward analysis: optimise on a training window, trade the next
test window with the chosen parameters, roll forward, stitch OOS equity."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from strategy_engine.backtest.engine import BacktestParams
from strategy_engine.backtest.metrics import compute_metrics, downsample
from strategy_engine.backtest.optimise import optimise
from strategy_engine.backtest.vectorised import run_vectorised
from strategy_engine.dsl import StrategyDSL, set_path


def walk_forward(
    dsl: StrategyDSL,
    params: BacktestParams,
    frames: dict[str, pd.DataFrame],
    space: list[dict[str, Any]],
    *,
    windows: int = 5,
    train_ratio: float = 0.7,
    objective: str = "sharpe",
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    first = next(iter(frames.values()))
    n = len(first)
    seg = n // (windows + 1)
    if seg < 50:
        raise ValueError("not enough data for the requested number of walk-forward windows")
    train_len = int(seg * (windows + 1) * train_ratio / windows) if windows > 1 else int(n * train_ratio)
    test_len = seg
    out_windows = []
    oos_curves: list[pd.Series] = []
    capital = params.initial_capital
    start = 0
    w = 0
    while start + train_len + 10 < n and w < windows:
        tr = {s: f.iloc[start : start + train_len] for s, f in frames.items()}
        te = {s: f.iloc[start + train_len : start + train_len + test_len] for s, f in frames.items()}
        opt = optimise(dsl, params, tr, space, objective=objective, oos_fraction=0.0)
        cfg = dsl.model_dump(mode="json")
        for path, val in opt["best"]["params"].items():
            cfg = set_path(cfg, path, val)
        p2 = BacktestParams(**{**params.__dict__, "initial_capital": capital})
        res = run_vectorised(StrategyDSL.model_validate(cfg), p2, te)
        m = compute_metrics(res.equity, res.trades, capital, params.risk_free) if len(res.equity) else {}
        if len(res.equity):
            oos_curves.append(res.equity)
            capital = float(res.equity.iloc[-1])
        out_windows.append({
            "window": w + 1,
            "train": [first.index[start].isoformat(), first.index[start + train_len - 1].isoformat()],
            "test": [first.index[start + train_len].isoformat(), first.index[min(n - 1, start + train_len + test_len - 1)].isoformat()],
            "best_params": opt["best"]["params"], "is_metrics": opt["best"]["metrics"], "oos_metrics": m,
        })
        start += test_len
        w += 1
        if progress:
            progress(w / windows, f"window {w}/{windows}")
    if not oos_curves:
        raise ValueError("walk-forward produced no out-of-sample windows")
    stitched = pd.concat(oos_curves)
    stitched = stitched[~stitched.index.duplicated(keep="last")]
    total = compute_metrics(stitched, [], params.initial_capital, params.risk_free)
    is_cagr = [x["is_metrics"].get("cagr_pct") or 0 for x in out_windows]
    oos_cagr = [x["oos_metrics"].get("cagr_pct") or 0 for x in out_windows]
    wfe = (sum(oos_cagr) / len(oos_cagr)) / (sum(is_cagr) / len(is_cagr)) if sum(is_cagr) else None
    stable = len({tuple(sorted(x["best_params"].items())) for x in out_windows})
    warnings = []
    if wfe is not None and wfe < 0.5:
        warnings.append(f"Walk-forward efficiency {wfe:.2f} < 0.5: in-sample edge does not carry over.")
    if stable == len(out_windows) and len(out_windows) > 2:
        warnings.append("Optimal parameters change every window - the edge may be parameter-fragile.")
    return {"windows": out_windows, "oos_metrics": total, "walk_forward_efficiency": None if wfe is None else round(wfe, 3),
            "equity_curve": downsample(stitched), "warnings": warnings}
