"""Fast vectorised backtest (used for optimisation sweeps and walk-forward).

Approximations vs the event engine: fills at signal-bar close, stops/targets
checked on closes, costs as an average fraction of turnover per side. Results
are typically within a few % of the event engine and ~50-200x faster.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from strategy_engine.backtest.engine import BacktestParams, EngineResult
from strategy_engine.costs import CostModel
from strategy_engine.dsl import StrategyDSL
from strategy_engine.signals import generate_signals, ist_index


def cost_fraction(broker: str, product: str, price: float, qty: int, on: date) -> float:
    cm = CostModel(broker)
    buy = cm.charges(on=on, side="BUY", price=price, quantity=qty, product=product)
    sell = cm.charges(on=on, side="SELL", price=price, quantity=qty, product=product)
    return (buy.total + sell.total) / 2 / max(1.0, price * qty)


def run_vectorised(dsl: StrategyDSL, params: BacktestParams, frames: dict[str, pd.DataFrame]) -> EngineResult:
    per_symbol_equity = []
    trades: list[dict[str, Any]] = []
    alloc = params.initial_capital / max(1, len(frames))
    for sym, df in frames.items():
        if df.empty:
            continue
        sig = generate_signals(df, dsl)
        close = df["close"].to_numpy(float)
        el, es = sig["entry_long"].to_numpy(bool), sig["entry_short"].to_numpy(bool)
        xl, xs = sig["exit_long"].to_numpy(bool), sig["exit_short"].to_numpy(bool)
        idx = ist_index(df)
        mins = idx.hour * 60 + idx.minute
        sq = None
        if dsl.product == "MIS" and dsl.schedule.square_off:
            h, m = dsl.schedule.square_off.split(":")
            sq = int(h) * 60 + int(m)
        sl = dsl.exit.stop_loss.value / 100 if dsl.exit.stop_loss and dsl.exit.stop_loss.type == "percent" else None
        tg = dsl.exit.target.value / 100 if dsl.exit.target and dsl.exit.target.type == "percent" else None
        n = len(close)
        pos = np.zeros(n)
        cur, entry, entry_i = 0, 0.0, 0
        for i in range(n):
            if cur != 0:
                r = (close[i] / entry - 1) * cur
                if (sl and r <= -sl) or (tg and r >= tg) or (sq is not None and mins[i] >= sq) or (xl[i] if cur > 0 else xs[i]):
                    reason = "stop_loss" if sl and r <= -sl else "target" if tg and r >= tg else "signal"
                    trades.append({"symbol": sym, "side": "LONG" if cur > 0 else "SHORT", "entry_ts": df.index[entry_i].isoformat(),
                                   "exit_ts": df.index[i].isoformat(), "entry_price": entry, "exit_price": float(close[i]),
                                   "ret": r, "exit_reason": reason, "bars_held": i - entry_i})
                    cur = 0
            if cur == 0 and (sq is None or mins[i] < sq) and el[i] != es[i]:
                cur, entry, entry_i = (1 if el[i] else -1), float(close[i]), i
            pos[i] = cur
        rets = pd.Series(close, index=df.index).pct_change().fillna(0).to_numpy()
        held = np.roll(pos, 1)
        held[0] = 0
        frac = dsl.sizing.value / 100 if dsl.sizing.mode == "capital_pct" else 1.0
        frac = min(frac * len(frames), 1.0 if dsl.product == "CNC" else params.leverage_intraday)
        turnover = np.abs(np.diff(np.concatenate([[0.0], pos])))
        cf = cost_fraction(params.broker, dsl.product, float(close[-1]), max(1, int(alloc * frac / close[-1])), df.index[-1].date())
        slip = params.slippage_bps / 1e4
        strat = held * rets * frac - turnover * (cf + slip) * frac
        eq = alloc * np.cumprod(1 + strat)
        per_symbol_equity.append(pd.Series(eq, index=df.index))
        for t in trades:
            if t["symbol"] == sym and "net_pnl" not in t:
                notional = alloc * frac
                t["quantity"] = int(notional / t["entry_price"])
                gross = t["ret"] * notional
                ch = 2 * (cf + slip) * notional
                t.update(gross_pnl=round(gross, 2), charges=round(ch, 2), net_pnl=round(gross - ch, 2))
    if not per_symbol_equity:
        return EngineResult(equity=pd.Series(dtype=float), trades=[])
    total = pd.concat(per_symbol_equity, axis=1).ffill().fillna(alloc).sum(axis=1)
    return EngineResult(equity=total, trades=trades)
