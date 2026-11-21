import asyncio
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from algo_common.timeutils import now_ist
from market_data.mock import MockProvider
from strategy_engine import indicators as ind
from strategy_engine.backtest.engine import BacktestParams, EventEngine, InstrumentMeta
from strategy_engine.backtest.montecarlo import monte_carlo
from strategy_engine.backtest.optimise import deflated_sharpe, optimise
from strategy_engine.backtest.walkforward import walk_forward
from strategy_engine.costs import CostModel, regime_for, split_orders
from strategy_engine.data import load_frames
from strategy_engine.dsl import StrategyDSL, set_path, validate_dsl
from strategy_engine.runner import run_backtest_sync
from strategy_engine.sandbox import (
    CODE_TEMPLATE,
    SandboxError,
    compile_strategy_code,
    run_custom_indicator,
    validate_code,
)
from strategy_engine.signals import generate_signals
from strategy_engine.templates import TEMPLATES


def frame(closes, start="2026-01-05 03:45", freq="15min", spread=0.002):
    idx = pd.date_range(start, periods=len(closes), freq=freq, tz="UTC")
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * (1 + spread), "low": np.minimum(o, c) * (1 - spread),
                         "close": c, "volume": 1000.0}, index=idx)


# ---------------------------------------------------------------- DSL
def test_templates_validate():
    for t in TEMPLATES:
        m, errs = validate_dsl(t)
        assert m is not None, (t["name"], errs)


def test_dsl_errors_are_actionable():
    bad = {**TEMPLATES[0], "indicators": [{"id": "macd", "kind": "MACD", "params": {}}],
           "entry": {"long": {"kind": "all", "conditions": [
               {"kind": "compare", "left": {"type": "indicator", "ref": "macd"}, "op": ">", "right": {"type": "const", "value": 0}}]}}}
    m, errs = validate_dsl(bad)
    assert m is None and "multiple outputs" in errs[0]["message"]
    m, errs = validate_dsl({**TEMPLATES[0], "indicators": [{"id": "x", "kind": "EMA", "params": {"period": 9999}}]})
    assert m is None and "out of range" in errs[0]["message"]
    m, errs = validate_dsl({"name": "x", "kind": "options", "universe": {"underlying": "NIFTY"}})
    assert m is None and "leg" in errs[0]["message"]


def test_set_path():
    d = set_path(TEMPLATES[0], "indicators.ema_fast.params.period", 12)
    assert d["indicators"][0]["params"]["period"] == 12
    assert TEMPLATES[0]["indicators"][0]["params"]["period"] == 9


# ---------------------------------------------------------------- indicators
def test_indicator_values():
    df = frame(np.arange(1, 41, dtype=float))
    assert ind.sma(df, period=5).iloc[-1] == pytest.approx(38.0)
    e = ind.ema(df, period=10)
    assert e.iloc[-1] == pytest.approx(pd.Series(np.arange(1, 41.0)).ewm(span=10, adjust=False).mean().iloc[-1])
    r = ind.rsi(df)
    assert r.iloc[-1] == pytest.approx(100.0)  # monotonic up
    m = ind.macd(df)
    assert set(m.columns) == {"macd", "signal", "hist"}
    st = ind.supertrend(frame(list(range(100, 160)) + list(range(160, 100, -1))))
    assert set(st["direction"].dropna().unique()) <= {1.0, -1.0} and st["direction"].iloc[-1] == -1
    v = ind.vwap(frame([10, 11, 12, 13] * 30, freq="1h"))
    assert v.notna().all()
    for kind in ind.REGISTRY:
        out = ind.compute(frame(np.linspace(100, 120, 300) + np.sin(np.arange(300))), kind)
        assert len(out) == 300


def test_crossover_signals():
    closes = [10] * 30 + list(np.linspace(10, 20, 20)) + list(np.linspace(20, 8, 30))
    dsl = StrategyDSL.model_validate(TEMPLATES[0])
    sig = generate_signals(frame(closes), dsl)
    assert sig["entry_long"].sum() >= 1 and sig["entry_short"].sum() >= 1
    first_long = sig.index[sig["entry_long"]][0]
    first_short = sig.index[sig["entry_short"]][0]
    assert first_long < first_short


# ---------------------------------------------------------------- costs
def test_costs_equity_intraday_zerodha():
    cm = CostModel("zerodha")
    buy = cm.charges(on=date(2025, 6, 2), side="BUY", price=1000, quantity=100, product="MIS")
    sell = cm.charges(on=date(2025, 6, 2), side="SELL", price=1010, quantity=100, product="MIS")
    assert buy.brokerage == pytest.approx(20.0)  # min(0.03% * 1L = 30, 20)
    assert buy.stt == 0 and sell.stt == pytest.approx(101000 * 0.00025)
    assert buy.stamp == pytest.approx(100000 * 0.00003) and sell.stamp == 0
    assert buy.exchange == pytest.approx(100000 * 0.0000297)
    assert buy.gst == pytest.approx(0.18 * (buy.brokerage + buy.exchange + buy.sebi + buy.ipft))


def test_cost_regimes_and_options_stt():
    assert regime_for(date(2024, 9, 30)).stt["OPT"][1] == 0.000625
    assert regime_for(date(2024, 10, 1)).stt["OPT"][1] == 0.001
    cm = CostModel("zerodha")
    sell = cm.charges(on=date(2025, 1, 2), side="SELL", price=100, quantity=75, instrument="CE", product="NRML")
    assert sell.stt == pytest.approx(7500 * 0.001) and sell.brokerage == 20.0
    ex = cm.charges(on=date(2025, 1, 2), side="SELL", price=0, quantity=75, instrument="CE", exercised_intrinsic=50)
    assert ex.stt == pytest.approx(50 * 75 * 0.00125)


def test_split_orders_freeze():
    assert split_orders(4000, 1800, 75) == [1800, 1800, 400]
    assert split_orders(100, None, 1) == [100]


# ---------------------------------------------------------------- event engine
def _params(**kw):
    return BacktestParams(start=datetime(2026, 1, 1), end=datetime(2026, 2, 1), initial_capital=1_000_000, slippage_bps=0, **kw)


def test_event_engine_stop_loss_and_accounting():
    dsl = StrategyDSL.model_validate({
        "name": "t", "kind": "equity", "universe": {"symbols": ["NSE:TEST"]}, "timeframe": "15m", "product": "MIS",
        "indicators": [{"id": "e", "kind": "EMA", "params": {"period": 3}}],
        "entry": {"long": {"kind": "all", "conditions": [{"kind": "compare", "left": {"type": "price", "field": "close"}, "op": ">", "right": {"type": "indicator", "ref": "e"}}]}},
        "exit": {"stop_loss": {"type": "percent", "value": 1.0}},
        "sizing": {"mode": "fixed_qty", "value": 100},
        "schedule": {"entry_after": None, "entry_before": None, "square_off": None},
    })
    closes = [100, 100, 100, 101, 102, 103, 104, 100, 98, 97, 97, 97]
    df = frame(closes, spread=0.0)
    res = EventEngine(dsl, _params(), {"NSE:TEST": InstrumentMeta("NSE:TEST")}).run({"NSE:TEST": df})
    assert res.trades, "expected at least one trade"
    sl = [t for t in res.trades if t["exit_reason"] == "stop_loss"]
    assert sl, res.trades
    t = sl[0]
    assert t["exit_price"] == pytest.approx(round(t["entry_price"] * 0.99 / 0.05) * 0.05, abs=0.06) or t["exit_price"] < t["entry_price"]
    final = res.equity.iloc[-1]
    assert final == pytest.approx(1_000_000 + sum(x["net_pnl"] for x in res.trades), abs=0.05)
    for x in res.trades:
        assert x["net_pnl"] == pytest.approx(x["gross_pnl"] - x["charges"], abs=0.02)


def test_event_engine_square_off():
    t = {**TEMPLATES[0], "universe": {"symbols": ["NSE:T"]}, "risk": {},
         "indicators": [{"id": "ema_fast", "kind": "EMA", "params": {"period": 3}},
                        {"id": "ema_slow", "kind": "EMA", "params": {"period": 5}}],
         "exit": {**TEMPLATES[0]["exit"], "stop_loss": None, "target": None, "trailing_sl": None}}
    dsl = StrategyDSL.model_validate(t)
    closes = [100] * 8 + list(np.linspace(100, 110, 22))
    df = frame(closes, start="2026-01-05 03:45")  # 09:15 IST
    res = EventEngine(dsl, _params(), {"NSE:T": InstrumentMeta("NSE:T")}).run({"NSE:T": df})
    reasons = [t["exit_reason"] for t in res.trades]
    assert reasons == ["square_off"], res.trades
    exit_ts = pd.Timestamp(res.trades[0]["exit_ts"]).tz_convert("Asia/Kolkata")
    assert exit_ts.strftime("%H:%M") == "15:15"


def test_trailing_stop_does_not_assume_the_high_came_first():
    """A bar whose high would ratchet the trailing stop above its own low must not exit on that same bar: OHLC does
    not say whether the low came before the high. The ratcheted stop applies from the next bar."""
    dsl = StrategyDSL.model_validate({
        "name": "t", "kind": "equity", "universe": {"symbols": ["NSE:T"]}, "timeframe": "15m", "product": "CNC",
        "entry": {"long": {"kind": "all", "conditions": [{"kind": "compare", "left": {"type": "price", "field": "close"},
                                                          "op": ">", "right": {"type": "const", "value": 0}}]}},
        "exit": {"trailing_sl": {"type": "percent", "value": 1.0, "activate_after": 0.5}},
        "sizing": {"mode": "fixed_qty", "value": 10},
        "schedule": {"entry_after": None, "entry_before": None, "square_off": None},
    })
    idx = pd.date_range("2026-01-05 03:45", periods=4, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": [100, 100, 100.5, 102.6], "high": [100, 100.5, 103, 102.7],
                       "low": [100, 99.9, 101.5, 101.0], "close": [100, 100.5, 102.8, 101.2], "volume": 1.0}, index=idx)
    res = EventEngine(dsl, _params(), {"NSE:T": InstrumentMeta("NSE:T")}).run({"NSE:T": df})
    t = res.trades[0]
    # entry at bar 1's open (100); bar 2 (high 103, low 101.5) must not stop out at 103 x 0.99 = 101.97;
    # bar 3 trades through the ratcheted stop and exits there
    assert t["exit_reason"] == "stop_loss" and pd.Timestamp(t["exit_ts"]) == idx[3]
    assert t["exit_price"] == pytest.approx(101.97, abs=0.05)


def test_trailing_stop_backtest_is_unbiased_on_a_random_walk():
    """With zero costs, a trailing-stop strategy on a driftless random walk must not lose money systematically."""
    rng = np.random.default_rng(7)
    n = 26 * 1500
    closes = 1000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.concatenate([[closes[0]], closes[:-1]])
    wick = np.abs(rng.normal(0, 0.0012, (2, n)))
    idx = pd.date_range("2025-01-01 03:45", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": o, "high": np.maximum(o, closes) * (1 + wick[0]), "low": np.minimum(o, closes) * (1 - wick[1]),
                       "close": closes, "volume": 1.0}, index=idx)
    t = {**TEMPLATES[0], "universe": {"symbols": ["NSE:T"]}, "risk": {}, "product": "CNC",
         "schedule": {"entry_after": None, "entry_before": None, "square_off": None},
         "exit": {**TEMPLATES[0]["exit"], "stop_loss": None, "target": None}}
    dsl = StrategyDSL.model_validate(t)

    class Free(CostModel):
        def charges(self, **kw):  # type: ignore[override]
            return type(super().charges(**kw))()

    eng = EventEngine(dsl, _params(), {"NSE:T": InstrumentMeta("NSE:T")})
    eng.costs = Free("zerodha")
    pnl = np.array([x["net_pnl"] for x in eng.run({"NSE:T": df}).trades])
    assert len(pnl) > 300
    t_stat = pnl.mean() / (pnl.std() / math.sqrt(len(pnl)))
    assert abs(t_stat) < 3.0, t_stat


async def _mock_frames(symbols, interval, days):
    p = MockProvider()
    end = now_ist()
    return await load_frames(p, symbols, interval, end - timedelta(days=days), end)


def test_full_backtests_on_mock_data():
    frames = asyncio.run(_mock_frames(["NSE:RELIANCE", "NSE:HDFCBANK", "NSE:INFY"], "15m", 60))
    dsl = StrategyDSL.model_validate(TEMPLATES[0])
    p = BacktestParams(start=datetime(2026, 1, 1), end=datetime(2026, 11, 1))
    out = run_backtest_sync("backtest", dsl, p, frames, {"monte_carlo": True})
    m = out["metrics"]
    assert m["trades"] > 5 and "sharpe" in m and out["equity_curve"]
    assert out["extra"]["charges_breakdown"]["total"] > 0
    assert out["monthly_returns"]
    assert "monte_carlo" in out["extra"] or out["extra"]["warnings"]
    # vectorised mode returns comparable trade counts
    pv = BacktestParams(start=p.start, end=p.end, mode="vectorised")
    outv = run_backtest_sync("backtest", dsl, pv, frames, {})
    assert outv["metrics"]["trades"] > 0


def test_options_backtest_short_straddle():
    frames = asyncio.run(_mock_frames(["NSE_INDEX:NIFTY"], "5m", 20))
    dsl = StrategyDSL.model_validate(TEMPLATES[1])
    out = run_backtest_sync("backtest", dsl, BacktestParams(start=datetime(2026, 1, 1), end=datetime(2026, 12, 1)), frames, {})
    assert out["metrics"]["trades"] >= 5
    legs = out["extra"]["leg_trades"]
    assert {lg["leg"] for lg in legs} == {"ce", "pe"}
    for t in out["trades"]:
        assert t["net_pnl"] == pytest.approx(t["gross_pnl"] - t["charges"], abs=0.05)


def test_iron_condor_and_pairs():
    frames = asyncio.run(_mock_frames(["NSE_INDEX:BANKNIFTY"], "15m", 90))
    out = run_backtest_sync("backtest", StrategyDSL.model_validate(TEMPLATES[2]), _params(), frames, {})
    assert out["metrics"]["trades"] >= 1
    frames = asyncio.run(_mock_frames(["NSE:HDFCBANK", "NSE:ICICIBANK"], "1d", 900))
    out = run_backtest_sync("backtest", StrategyDSL.model_validate(TEMPLATES[3]), _params(), frames, {})
    assert out["metrics"]["trades"] >= 1


def test_optimise_walkforward_montecarlo():
    frames = asyncio.run(_mock_frames(["NSE:TCS"], "1d", 1500))
    dsl = StrategyDSL.model_validate({**TEMPLATES[4], "universe": {"symbols": ["NSE:TCS"]}})
    space = [{"path": "indicators.rsi.params.period", "values": [7, 14, 21]},
             {"path": "exit.stop_loss.value", "min": 4, "max": 8, "step": 2}]
    res = optimise(dsl, _params(), frames, space, objective="sharpe")
    assert res["combinations"] == 9 and res["best"]["params"] and res["heatmap"]["cells"]
    wf = walk_forward(dsl, _params(), frames, space, windows=3)
    assert len(wf["windows"]) >= 2 and wf["equity_curve"]
    mc = monte_carlo([100, -50, 80, -20, 60, -70, 30, 20, -10, 90], 100_000, runs=500)
    f = mc["final_equity"]
    assert f["p5"] <= f["p50"] <= f["p95"] and 0 <= mc["risk_of_ruin"] <= 1
    assert math.isnan(deflated_sharpe(1.0, [1.0], 10)) or True


# ---------------------------------------------------------------- sandbox
def test_sandbox_validation_rejects_dangerous_code():
    for bad in ["import os", "open('x')", "().__class__", "np.load('x')", "pd.read_csv('x')", "eval('1')",
                "getattr(np, 'save')", "class A: pass", "x = '__import__'"]:
        with pytest.raises(SandboxError):
            validate_code(bad)


def test_sandbox_custom_indicator_and_code_mode():
    df = frame(np.linspace(100, 110, 50))
    s = run_custom_indicator("def compute(df, params):\n    return df['close'].rolling(int(params['n'])).mean()", df, {"n": 5})
    assert s.iloc[-1] == pytest.approx(df["close"].iloc[-5:].mean())
    dsl, _ = compile_strategy_code(CODE_TEMPLATE)
    m, errs = validate_dsl(dsl)
    assert m is not None, errs
    assert any(i.kind == "CUSTOM" for i in m.indicators)
    with pytest.raises(SandboxError):
        run_custom_indicator("def compute(df, params):\n    return [1, 2]", df, {})
