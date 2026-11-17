"""Backtest orchestration: pick the engine for the strategy kind / mode,
compute metrics and package results for storage and the UI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from strategy_engine.backtest.engine import BacktestParams, EngineResult, EventEngine, InstrumentMeta
from strategy_engine.backtest.metrics import compute_metrics, dow_stats, downsample, drawdown, monthly_returns
from strategy_engine.backtest.montecarlo import monte_carlo
from strategy_engine.backtest.optimise import optimise
from strategy_engine.backtest.options import HVPricer, MockChainPricer, OptionsEngine, lot_meta
from strategy_engine.backtest.pairs import PairEngine
from strategy_engine.backtest.vectorised import run_vectorised
from strategy_engine.backtest.walkforward import walk_forward
from strategy_engine.dsl import StrategyDSL

Progress = Callable[[float, str], None]


def instrument_meta(symbols: list[str]) -> dict[str, InstrumentMeta]:
    from market_data.symbols import parse
    from market_data.universe import asset_for_underlying

    out = {}
    for s in symbols:
        p = parse(s)
        if p.is_derivative and p.underlying:
            a = asset_for_underlying(p.underlying)
            out[s] = InstrumentMeta(s, exchange="MCX" if p.exchange == "MCX" else ("BFO" if p.exchange == "BFO" else "NSE"),
                                    instrument_type="FUT" if p.is_future else (p.option_type or "CE"),
                                    lot_size=(a.lot_size if a and a.lot_size else 1), freeze_qty=a.freeze_qty if a else None)
        else:
            out[s] = InstrumentMeta(s, exchange="BSE" if p.exchange == "BSE" else ("MCX" if p.exchange == "MCX" else "NSE"))
    return out


def run_engine(dsl: StrategyDSL, params: BacktestParams, frames: dict[str, pd.DataFrame], progress: Progress | None = None,
               mock_pricing: bool = True) -> EngineResult:
    if dsl.kind == "options":
        und = dsl.symbols[0]
        frame = frames[und]
        lot, freeze = lot_meta(dsl.universe.underlying or "NIFTY")
        pricer = MockChainPricer() if mock_pricing else HVPricer(frame["close"].resample("1D").last().dropna())
        return OptionsEngine(dsl, params, pricer, lot, freeze).run(frame, progress)
    if dsl.kind == "pair":
        return PairEngine(dsl, params, instrument_meta(dsl.symbols)).run(frames, progress)
    if params.mode == "vectorised":
        return run_vectorised(dsl, params, frames)
    return EventEngine(dsl, params, instrument_meta(list(frames))).run(frames, progress)


def package(dsl: StrategyDSL, params: BacktestParams, res: EngineResult, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    eq = res.equity
    metrics = compute_metrics(eq, res.trades, params.initial_capital, params.risk_free)
    # exposure: share of bars with an open position (approx from trades)
    if len(eq) and res.trades:
        held = sum(t.get("bars_held", 0) for t in res.trades)
        metrics["exposure_pct"] = round(min(100.0, held / len(eq) * 100), 1)
    bench_sym = dsl.symbols[0] if dsl.symbols else None
    bench = None
    if bench_sym and bench_sym in frames and not frames[bench_sym].empty:
        c = frames[bench_sym]["close"]
        bench = downsample(c / c.iloc[0] * params.initial_capital)
        metrics["benchmark_return_pct"] = round(float(c.iloc[-1] / c.iloc[0] - 1) * 100, 2)
    charges = res.charges.as_dict() if res.charges else {}
    extra: dict[str, Any] = {
        "dow_stats": dow_stats(res.trades) if res.trades else [],
        "charges_breakdown": charges,
        "benchmark_curve": bench,
        "benchmark_symbol": bench_sym,
        "warnings": res.warnings,
        "symbols": list(frames),
        "exit_reasons": _count(res.trades, "exit_reason"),
    }
    if hasattr(res, "leg_trades"):
        extra["leg_trades"] = res.leg_trades[:2000]  # type: ignore[attr-defined]
    return {
        "metrics": metrics,
        "equity_curve": downsample(eq),
        "drawdown_curve": downsample(drawdown(eq) * 100) if len(eq) else [],
        "monthly_returns": monthly_returns(eq) if len(eq) else [],
        "extra": extra,
        "trades": res.trades,
    }


def _count(trades: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in trades:
        k = str(t.get(key))
        out[k] = out.get(k, 0) + 1
    return out


def run_backtest_sync(
    kind: str, dsl: StrategyDSL, params: BacktestParams, frames: dict[str, pd.DataFrame], options: dict[str, Any],
    progress: Progress | None = None, mock_pricing: bool = True,
) -> dict[str, Any]:
    """CPU-bound entry point (run in a worker thread / process)."""
    if kind == "optimise":
        res = optimise(dsl, params, frames, options.get("space", []), method=options.get("method", "grid"),
                       objective=options.get("objective", "sharpe"), n_random=int(options.get("n_random", 60)),
                       oos_fraction=float(options.get("oos_fraction", 0.3)), progress=progress)
        best = res["best"]
        return {"metrics": best["metrics"], "equity_curve": [], "drawdown_curve": [], "monthly_returns": [],
                "extra": {"optimisation": res, "warnings": res["warnings"]}, "trades": []}
    if kind == "walk_forward":
        res = walk_forward(dsl, params, frames, options.get("space", []), windows=int(options.get("windows", 5)),
                           train_ratio=float(options.get("train_ratio", 0.7)), objective=options.get("objective", "sharpe"),
                           progress=progress)
        return {"metrics": res["oos_metrics"], "equity_curve": res["equity_curve"], "drawdown_curve": [],
                "monthly_returns": [], "extra": {"walk_forward": res, "warnings": res["warnings"]}, "trades": []}
    engine_res = run_engine(dsl, params, frames, progress, mock_pricing)
    out = package(dsl, params, engine_res, frames)
    if kind == "monte_carlo" or options.get("monte_carlo"):
        pnls = [t["net_pnl"] for t in engine_res.trades]
        try:
            out["extra"]["monte_carlo"] = monte_carlo(pnls, params.initial_capital, runs=int(options.get("runs", 1000)),
                                                      method=options.get("mc_method", "bootstrap"))
        except ValueError as exc:
            out["extra"].setdefault("warnings", []).append(str(exc))
    return out
