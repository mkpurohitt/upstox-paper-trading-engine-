"""Statistical-arbitrage pair backtester (rolling OLS hedge ratio, z-score bands)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from strategy_engine.backtest.engine import (
    BacktestParams,
    EngineResult,
    InstrumentMeta,
    ProgressFn,
    round_tick,
)
from strategy_engine.costs import Charges, CostModel
from strategy_engine.dsl import StrategyDSL


def rolling_hedge(a: pd.Series, b: pd.Series, lookback: int) -> pd.Series:
    la, lb = np.log(a), np.log(b)
    cov = la.rolling(lookback).cov(lb)
    var = lb.rolling(lookback).var()
    return cov / var


def spread_zscore(a: pd.Series, b: pd.Series, lookback: int, beta: pd.Series | float) -> tuple[pd.Series, pd.Series]:
    spread = np.log(a) - beta * np.log(b)
    z = (spread - spread.rolling(lookback).mean()) / spread.rolling(lookback).std(ddof=0)
    return spread, z


class PairEngine:
    def __init__(self, dsl: StrategyDSL, params: BacktestParams, meta: dict[str, InstrumentMeta] | None = None) -> None:
        assert dsl.pair is not None
        self.dsl, self.p, self.ps = dsl, params, dsl.pair
        self.meta = meta or {}
        self.costs = CostModel(params.broker)

    def _ch(self, ts: pd.Timestamp, sym: str, side: int, price: float, qty: int) -> Charges:
        m = self.meta.get(sym) or InstrumentMeta(sym)
        return self.costs.charges(on=ts.tz_convert("Asia/Kolkata").date(), side="BUY" if side > 0 else "SELL",
                                  price=price, quantity=qty, exchange=m.exchange, instrument=m.instrument_type,
                                  product=self.dsl.product)

    def run(self, frames: dict[str, pd.DataFrame], progress: ProgressFn | None = None) -> EngineResult:
        ps = self.ps
        a = frames[ps.leg_a]["close"]
        b = frames[ps.leg_b]["close"]
        df = pd.concat({"a": a, "b": b}, axis=1).dropna()
        beta = rolling_hedge(df["a"], df["b"], ps.lookback) if ps.hedge == "ols" else pd.Series(ps.fixed_ratio or 1.0, index=df.index)
        _, z = spread_zscore(df["a"], df["b"], ps.lookback, beta)
        cash = self.p.initial_capital
        pos = 0  # +1 long spread (long A, short B), -1 short spread
        qa = qb = 0
        ea = eb = 0.0
        entry_ts = None
        entry_i = 0
        ent_ch = Charges()
        trades: list[dict[str, Any]] = []
        total = Charges()
        eq = []
        slip = self.p.slippage_bps / 1e4
        za, pa, pb, bb = z.to_numpy(), df["a"].to_numpy(), df["b"].to_numpy(), beta.to_numpy()
        n = len(df)
        for i in range(n):
            ts = df.index[i]
            zi = za[i]
            if pos != 0:
                exit_reason = None
                if abs(zi) <= ps.exit_z or (pos > 0 and zi >= 0) or (pos < 0 and zi <= 0):
                    exit_reason = "mean_reversion"
                elif ps.stop_z and abs(zi) >= ps.stop_z:
                    exit_reason = "stop_z"
                elif self.dsl.exit.max_holding_bars and i - entry_i >= self.dsl.exit.max_holding_bars:
                    exit_reason = "max_holding"
                if exit_reason:
                    xa = round_tick(pa[i] * (1 - slip * pos), 0.05)
                    xb = round_tick(pb[i] * (1 + slip * pos), 0.05)
                    ch = self._ch(ts, ps.leg_a, -pos, xa, qa) + self._ch(ts, ps.leg_b, pos, xb, qb)
                    gross = (xa - ea) * qa * pos - (xb - eb) * qb * pos
                    cash += gross - ch.total
                    total = total + ch
                    all_ch = ent_ch + ch
                    trades.append({
                        "symbol": f"{ps.leg_a}/{ps.leg_b}", "side": "LONG_SPREAD" if pos > 0 else "SHORT_SPREAD",
                        "quantity": qa, "entry_ts": entry_ts.isoformat() if entry_ts is not None else ts.isoformat(),
                        "entry_price": round(float(za[entry_i]), 3), "exit_ts": ts.isoformat(), "exit_price": round(float(zi), 3),
                        "gross_pnl": round(gross, 2), "charges": round(all_ch.total, 2), "net_pnl": round(gross - all_ch.total, 2),
                        "exit_reason": exit_reason, "bars_held": i - entry_i,
                        "legs": [{"symbol": ps.leg_a, "qty": qa, "entry": ea, "exit": xa}, {"symbol": ps.leg_b, "qty": qb, "entry": eb, "exit": xb}],
                    })
                    pos = 0
            if pos == 0 and np.isfinite(zi) and np.isfinite(bb[i]) and abs(zi) >= ps.entry_z and (not ps.stop_z or abs(zi) < ps.stop_z):
                pos = -1 if zi > 0 else 1
                equity = cash
                notional = equity * (self.dsl.sizing.value / 100 if self.dsl.sizing.mode == "capital_pct" else 0.2) / 2
                if self.dsl.sizing.mode == "fixed_capital":
                    notional = self.dsl.sizing.value / 2
                qa = max(1, int(notional / pa[i]))
                qb = max(1, int(notional * abs(bb[i]) / pb[i]))
                ea = round_tick(pa[i] * (1 + slip * pos), 0.05)
                eb = round_tick(pb[i] * (1 - slip * pos), 0.05)
                ent_ch = self._ch(ts, ps.leg_a, pos, ea, qa) + self._ch(ts, ps.leg_b, -pos, eb, qb)
                cash -= ent_ch.total
                total = total + ent_ch
                entry_ts, entry_i = ts, i
            unreal = ((pa[i] - ea) * qa * pos - (pb[i] - eb) * qb * pos) if pos else 0.0
            eq.append(cash + unreal)
            if progress and n and i % max(1, n // 50) == 0:
                progress(i / n, f"bar {i}/{n}")
        res = EngineResult(equity=pd.Series(eq, index=df.index, dtype=float), trades=trades, charges=total)
        res.signals = {"pair": pd.DataFrame({"z": z, "beta": beta}, index=df.index)}
        return res
