"""Performance statistics for equity curves and trade lists."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 252
_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _safe(x: float | None, digits: int = 4) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), digits)


def daily_equity(equity: pd.Series) -> pd.Series:
    idx = equity.index.tz_convert("Asia/Kolkata") if equity.index.tz is not None else equity.index
    return pd.Series(equity.to_numpy(), index=idx).groupby(idx.date).last()


def drawdown(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    return equity / peak - 1.0


def compute_metrics(equity: pd.Series, trades: list[dict[str, Any]], initial_capital: float, rf: float = 0.065) -> dict[str, Any]:
    if equity.empty:
        return {"trades": 0}
    daily = daily_equity(equity)
    rets = daily.pct_change().dropna()
    final = float(equity.iloc[-1])
    days = max(1, (pd.Timestamp(daily.index[-1]) - pd.Timestamp(daily.index[0])).days)
    years = days / 365.25
    total_ret = final / initial_capital - 1
    cagr = (final / initial_capital) ** (1 / years) - 1 if years > 0 and final > 0 else None
    vol = rets.std(ddof=1) * math.sqrt(TRADING_DAYS) if len(rets) > 1 else None
    excess = rets - rf / TRADING_DAYS
    sharpe = excess.mean() / rets.std(ddof=1) * math.sqrt(TRADING_DAYS) if len(rets) > 1 and rets.std(ddof=1) > 0 else None
    downside = rets[rets < 0]
    dstd = math.sqrt((downside**2).sum() / max(1, len(rets))) * math.sqrt(TRADING_DAYS) if len(downside) else None
    sortino = (rets.mean() * TRADING_DAYS - rf) / dstd if dstd else None
    dd = drawdown(equity)
    max_dd = float(dd.min())
    # max drawdown duration (bars -> days)
    underwater = (dd < 0).astype(int)
    longest = cur = 0
    for v in underwater.to_numpy():
        cur = cur + 1 if v else 0
        longest = max(longest, cur)
    dd_days = daily_equity(drawdown(equity))
    dd_dur_days = int(max(((dd_days < 0).astype(int).groupby((dd_days >= 0).cumsum()).sum()).max(), 0)) if len(dd_days) else 0
    calmar = (cagr / abs(max_dd)) if cagr is not None and max_dd < 0 else None

    pnls = np.array([t["net_pnl"] for t in trades], dtype=float) if trades else np.array([])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    win_rate = len(wins) / len(pnls) if len(pnls) else None
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = losses.mean() if len(losses) else 0.0
    streak_w = streak_l = cw = cl = 0
    for p in pnls:
        if p > 0:
            cw, cl = cw + 1, 0
        else:
            cl, cw = cl + 1, 0
        streak_w, streak_l = max(streak_w, cw), max(streak_l, cl)
    holding = [t.get("bars_held", 0) for t in trades]
    charges = sum(t.get("charges", 0.0) for t in trades)
    return {
        "initial_capital": round(initial_capital, 2),
        "final_equity": round(final, 2),
        "net_pnl": round(final - initial_capital, 2),
        "total_return_pct": _safe(total_ret * 100, 2),
        "cagr_pct": _safe(cagr * 100 if cagr is not None else None, 2),
        "volatility_pct": _safe(vol * 100 if vol is not None else None, 2),
        "sharpe": _safe(sharpe, 2),
        "sortino": _safe(sortino, 2),
        "calmar": _safe(calmar, 2),
        "max_drawdown_pct": _safe(max_dd * 100, 2),
        "max_drawdown_days": dd_dur_days,
        "trades": len(pnls),
        "win_rate_pct": _safe(win_rate * 100 if win_rate is not None else None, 2),
        "profit_factor": _safe(gross_win / gross_loss if gross_loss > 0 else (None if gross_win == 0 else float("inf")), 2),
        "expectancy": _safe(pnls.mean() if len(pnls) else None, 2),
        "avg_win": _safe(avg_win, 2),
        "avg_loss": _safe(avg_loss, 2),
        "payoff_ratio": _safe(avg_win / abs(avg_loss) if avg_loss else None, 2),
        "best_trade": _safe(pnls.max() if len(pnls) else None, 2),
        "worst_trade": _safe(pnls.min() if len(pnls) else None, 2),
        "max_consecutive_wins": streak_w,
        "max_consecutive_losses": streak_l,
        "avg_bars_held": _safe(float(np.mean(holding)) if holding else None, 1),
        "total_charges": round(charges, 2),
        "charges_pct_of_gross": _safe(charges / (abs(pnls.sum()) + charges) * 100 if len(pnls) and (abs(pnls.sum()) + charges) else None, 2),
        "exposure_pct": None,
        "trading_days": len(daily),
    }


def monthly_returns(equity: pd.Series) -> list[dict[str, Any]]:
    daily = daily_equity(equity)
    s = pd.Series(daily.to_numpy(), index=pd.to_datetime(list(daily.index)))
    m = s.resample("ME").last()
    prev = m.shift(1)
    prev.iloc[0] = s.iloc[0]
    rets = (m / prev - 1) * 100
    return [{"year": int(ts.year), "month": int(ts.month), "return_pct": round(float(v), 2)}
            for ts, v in rets.items() if math.isfinite(v)]


def dow_stats(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, list[float]] = {}
    for t in trades:
        ts = pd.Timestamp(t["entry_ts"])
        ts = ts.tz_convert("Asia/Kolkata") if ts.tzinfo else ts
        buckets.setdefault(ts.dayofweek, []).append(t["net_pnl"])
    out = []
    for d in range(5):
        p = buckets.get(d, [])
        out.append({"day": _DOW[d], "trades": len(p), "net_pnl": round(sum(p), 2),
                    "avg_pnl": round(sum(p) / len(p), 2) if p else 0.0,
                    "win_rate_pct": round(sum(1 for x in p if x > 0) / len(p) * 100, 1) if p else 0.0})
    return out


def downsample(series: pd.Series, max_points: int = 1500) -> list[dict[str, Any]]:
    s = series.dropna()
    if len(s) > max_points:
        step = math.ceil(len(s) / max_points)
        s = pd.concat([s.iloc[::step], s.iloc[[-1]]])
        s = s[~s.index.duplicated(keep="last")]
    return [{"ts": ts.isoformat(), "value": round(float(v), 4)} for ts, v in s.items()]
