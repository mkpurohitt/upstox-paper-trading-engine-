"""Event-driven backtester for equity / futures strategies.

Execution model
* Signals are evaluated on bar close. With ``fill="next_open"`` (default) the
  order fills at the next bar's open, otherwise at the signal bar's close.
* Stops / targets are checked intrabar using high/low. If both are touched in
  the same bar the stop is assumed to fill first (conservative); gaps fill at
  the open.
* Fills include slippage (bps) and are rounded to the tick size. Charges come
  from `CostModel` (brokerage + STT + exchange + SEBI + stamp + IPFT + GST) and
  orders above the freeze quantity are split (each slice is a separate order).
* MIS positions are squared off at `schedule.square_off`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Literal

import numpy as np
import pandas as pd

from strategy_engine.costs import Charges, CostModel, split_orders
from strategy_engine.dsl import StrategyDSL
from strategy_engine.signals import generate_signals, ist_index

ProgressFn = Callable[[float, str], None]


@dataclass
class BacktestParams:
    start: datetime
    end: datetime
    initial_capital: float = 1_000_000.0
    broker: str = "zerodha"
    slippage_bps: float = 5.0
    fill: Literal["next_open", "close"] = "next_open"
    mode: Literal["event", "vectorised"] = "event"
    risk_free: float = 0.0  # idle cash earns nothing in the simulation, so Sharpe/Sortino use rf=0 (DECISIONS #52)
    leverage_intraday: float = 5.0


@dataclass
class InstrumentMeta:
    symbol: str
    exchange: str = "NSE"
    instrument_type: str = "EQ"
    lot_size: int = 1
    tick_size: float = 0.05
    freeze_qty: int | None = None


@dataclass
class _Pos:
    symbol: str
    side: int
    qty: int
    entry_price: float
    entry_ts: pd.Timestamp
    entry_bar: int
    entry_charges: Charges
    stop: float | None = None
    target: float | None = None
    best: float = 0.0
    trailing_active: bool = False


@dataclass
class EngineResult:
    equity: pd.Series
    trades: list[dict[str, Any]]
    charges: Charges = field(default_factory=Charges)
    signals: dict[str, pd.DataFrame] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _hhmm(s: str | None) -> time | None:
    if not s:
        return None
    h, m = s.split(":")
    return time(int(h), int(m))


def round_tick(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 2) if tick > 0 else price


class EventEngine:
    def __init__(self, dsl: StrategyDSL, params: BacktestParams, meta: dict[str, InstrumentMeta] | None = None) -> None:
        self.dsl = dsl
        self.p = params
        self.meta = meta or {}
        self.costs = CostModel(params.broker)
        self.entry_after = _hhmm(dsl.schedule.entry_after)
        self.entry_before = _hhmm(dsl.schedule.entry_before)
        self.square_off = _hhmm(dsl.schedule.square_off) if dsl.product == "MIS" else None
        self.days = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}
        self.allowed_days = {self.days[d] for d in dsl.schedule.days}

    # ------------------------------------------------------------------ helpers
    def _m(self, symbol: str) -> InstrumentMeta:
        return self.meta.get(symbol) or InstrumentMeta(symbol=symbol)

    def _fill_price(self, price: float, side: int, meta: InstrumentMeta) -> float:
        slip = price * self.p.slippage_bps / 1e4
        return round_tick(price + slip if side > 0 else price - slip, meta.tick_size)

    def _charges(self, ts: pd.Timestamp, side: int, price: float, qty: int, meta: InstrumentMeta) -> Charges:
        orders = len(split_orders(qty, meta.freeze_qty, meta.lot_size))
        return self.costs.charges(
            on=ts.tz_convert("Asia/Kolkata").date(), side="BUY" if side > 0 else "SELL", price=price, quantity=qty,
            exchange=meta.exchange, instrument=meta.instrument_type, product=self.dsl.product, orders=orders,
        )

    def _size(self, equity: float, price: float, meta: InstrumentMeta) -> int:
        s = self.dsl.sizing
        lot = max(1, meta.lot_size)
        if s.mode == "fixed_qty":
            qty = int(s.value)
            qty = max(lot, (qty // lot) * lot)
        elif s.mode == "fixed_lots":
            qty = int(s.value) * lot
        else:
            notional = equity * s.value / 100 if s.mode == "capital_pct" else s.value
            qty = int(notional / price / lot) * lot
        lev = self.p.leverage_intraday if self.dsl.product != "CNC" else 1.0
        cap = int(equity * lev / price / lot) * lot
        return max(0, min(qty, cap))

    def _trail(self, pos: _Pos, price: float) -> None:
        """Move the position's best price to `price` (if better) and ratchet the trailing stop from it."""
        pos.best = max(pos.best, price) if pos.side > 0 else (min(pos.best, price) if pos.best else price)
        tr = self.dsl.exit.trailing_sl
        if tr is None:
            return
        profit = (pos.best - pos.entry_price) * pos.side
        trigger = tr.activate_after * (pos.entry_price / 100 if tr.type == "percent" else 1)
        if profit >= trigger:
            dist = pos.best * tr.value / 100 if tr.type == "percent" else tr.value
            new_stop = pos.best - pos.side * dist
            if pos.stop is None or (new_stop - pos.stop) * pos.side > 0:
                pos.stop = new_stop
                pos.trailing_active = True

    def _stops(self, side: int, price: float, atr_val: float | None) -> tuple[float | None, float | None]:
        ex = self.dsl.exit

        def level(spec: Any, against: bool) -> float | None:
            if spec is None:
                return None
            if spec.type == "percent":
                d = price * spec.value / 100
            elif spec.type == "points":
                d = spec.value
            else:
                if atr_val is None or not math.isfinite(atr_val):
                    return None
                d = atr_val * spec.value
            return price - side * d if against else price + side * d

        return level(ex.stop_loss, True), level(ex.target, False)

    # ------------------------------------------------------------------ main loop
    def run(self, frames: dict[str, pd.DataFrame], progress: ProgressFn | None = None) -> EngineResult:
        dsl, p = self.dsl, self.p
        sigs: dict[str, pd.DataFrame] = {}
        atrs: dict[str, np.ndarray] = {}
        for sym, df in frames.items():
            sigs[sym] = generate_signals(df, dsl)
            if (dsl.exit.stop_loss and dsl.exit.stop_loss.type == "atr") or (dsl.exit.target and dsl.exit.target.type == "atr"):
                from strategy_engine.indicators import atr

                period = (dsl.exit.stop_loss or dsl.exit.target).atr_period  # type: ignore[union-attr]
                atrs[sym] = atr(df, period=period).to_numpy()

        timeline = sorted(set().union(*[set(df.index) for df in frames.values()])) if frames else []
        pos_idx = {sym: {ts: i for i, ts in enumerate(df.index)} for sym, df in frames.items()}
        arr = {sym: (df["open"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float))
               for sym, df in frames.items()}
        ist = {sym: ist_index(df) for sym, df in frames.items()}
        sig_arr = {sym: {c: s[c].to_numpy(bool) for c in ("entry_long", "entry_short", "exit_long", "exit_short")}
                   for sym, s in sigs.items()}

        cash = p.initial_capital
        positions: dict[str, _Pos] = {}
        pending: dict[str, tuple[str, int]] = {}  # symbol -> (action, side) to fill at next open
        trades: list[dict[str, Any]] = []
        total_charges = Charges()
        equity_pts: list[float] = []
        last_close: dict[str, float] = {}
        day_state: dict[str, Any] = {"date": None, "pnl": 0.0, "trades": 0, "halted": False, "sl_hits": {}, "entries": {}}
        cooldown_until: dict[str, int] = {}
        halted_forever = False
        warnings: list[str] = []
        n = len(timeline)

        def close_position(sym: str, price: float, ts: pd.Timestamp, bar: int, reason: str, raw: bool = False) -> None:
            nonlocal cash, total_charges
            pos = positions.pop(sym)
            meta = self._m(sym)
            px = price if raw else self._fill_price(price, -pos.side, meta)
            ch = self._charges(ts, -pos.side, px, pos.qty, meta)
            gross = (px - pos.entry_price) * pos.qty * pos.side
            cash += gross - ch.total
            all_ch = pos.entry_charges + ch
            total_charges = total_charges + ch
            net = gross - all_ch.total
            day_state["pnl"] += net
            if reason == "stop_loss":
                day_state["sl_hits"][sym] = day_state["sl_hits"].get(sym, 0) + 1
                cooldown_until[sym] = bar + dsl.reentry.cooldown_bars
            trades.append({
                "symbol": sym, "side": "LONG" if pos.side > 0 else "SHORT", "quantity": pos.qty,
                "entry_ts": pos.entry_ts.isoformat(), "entry_price": pos.entry_price, "exit_ts": ts.isoformat(),
                "exit_price": px, "gross_pnl": round(gross, 2), "charges": round(all_ch.total, 2),
                "net_pnl": round(net, 2), "exit_reason": reason, "bars_held": bar - pos.entry_bar,
                "charges_breakdown": all_ch.as_dict(),
            })

        def open_position(sym: str, side: int, price: float, ts: pd.Timestamp, bar: int, equity: float) -> None:
            nonlocal cash, total_charges
            meta = self._m(sym)
            px = self._fill_price(price, side, meta)
            qty = self._size(equity, px, meta)
            if qty <= 0:
                return
            ch = self._charges(ts, side, px, qty, meta)
            cash -= ch.total
            total_charges = total_charges + ch
            atr_v = float(atrs[sym][bar]) if sym in atrs else None
            stop, target = self._stops(side, px, atr_v)
            positions[sym] = _Pos(sym, side, qty, px, ts, bar, ch, stop, target, best=px)
            day_state["trades"] += 1
            day_state["entries"][sym] = day_state["entries"].get(sym, 0) + 1

        for k, ts in enumerate(timeline):
            for sym in frames:
                i = pos_idx[sym].get(ts)
                if i is None:
                    continue
                o, h, lo, c = (a[i] for a in arr[sym])
                t_ist = ist[sym][i]
                d = t_ist.date()
                if day_state["date"] != d:
                    day_state.update(date=d, pnl=0.0, trades=0, halted=False, sl_hits={}, entries={})
                bar_time = t_ist.time()

                # 1) pending orders fill at this bar's open
                if sym in pending:
                    action, side = pending.pop(sym)
                    if action == "exit" and sym in positions:
                        close_position(sym, o, ts, i, "signal")
                    elif action == "enter" and sym not in positions and not day_state["halted"] and not halted_forever:
                        open_position(sym, side, o, ts, i, self._equity(cash, positions, last_close))

                # 2) manage open position intrabar
                pos = positions.get(sym)
                if pos is not None:
                    # The trailing level in force during this bar may only use prices known before the bar's range
                    # unfolds (earlier extremes and this bar's open); the bar's own high/low ratchet it afterwards.
                    # Ratcheting with this bar's high and then testing this bar's low assumes the high came first,
                    # which biases every trailing-stop backtest downwards (DECISIONS #78).
                    self._trail(pos, o)
                    hit_stop = pos.stop is not None and ((pos.side > 0 and lo <= pos.stop) or (pos.side < 0 and h >= pos.stop))
                    hit_tgt = pos.target is not None and ((pos.side > 0 and h >= pos.target) or (pos.side < 0 and lo <= pos.target))
                    if hit_stop:
                        assert pos.stop is not None
                        px = min(o, pos.stop) if pos.side > 0 else max(o, pos.stop)
                        close_position(sym, px, ts, i, "stop_loss")
                    elif hit_tgt:
                        assert pos.target is not None
                        px = max(o, pos.target) if pos.side > 0 else min(o, pos.target)
                        close_position(sym, px, ts, i, "target")
                    elif self.square_off and bar_time >= self.square_off:
                        close_position(sym, c, ts, i, "square_off")
                    elif dsl.exit.max_holding_bars and i - pos.entry_bar >= dsl.exit.max_holding_bars:
                        close_position(sym, c, ts, i, "max_holding")
                    else:
                        ex = sig_arr[sym]["exit_long" if pos.side > 0 else "exit_short"][i]
                        rev = sig_arr[sym]["entry_short" if pos.side > 0 else "entry_long"][i]
                        if ex or rev:
                            if p.fill == "close" or i + 1 >= len(frames[sym]):
                                close_position(sym, c, ts, i, "signal")
                            else:
                                pending[sym] = ("exit", 0)

                pos = positions.get(sym)
                if pos is not None:
                    self._trail(pos, h if pos.side > 0 else lo)

                last_close[sym] = c

                # 3) daily / portfolio risk
                eq_now = self._equity(cash, positions, last_close)
                if dsl.risk.max_loss_per_day and day_state["pnl"] + self._unrealised(positions, last_close) <= -dsl.risk.max_loss_per_day:
                    for s2 in list(positions):
                        close_position(s2, last_close.get(s2, c), ts, i, "daily_loss_limit")
                    day_state["halted"] = True
                if dsl.risk.max_profit_per_day and day_state["pnl"] >= dsl.risk.max_profit_per_day:
                    day_state["halted"] = True
                if dsl.risk.portfolio_max_loss and eq_now <= p.initial_capital - dsl.risk.portfolio_max_loss and not halted_forever:
                    for s2 in list(positions):
                        close_position(s2, last_close.get(s2, c), ts, i, "portfolio_max_loss")
                    halted_forever = True
                    warnings.append(f"Portfolio max loss hit on {d}; strategy halted")

                # 4) entries
                if sym in positions or sym in pending or day_state["halted"] or halted_forever:
                    continue
                if t_ist.dayofweek not in self.allowed_days:
                    continue
                if self.entry_after and bar_time < self.entry_after:
                    continue
                if self.entry_before and bar_time >= self.entry_before:
                    continue
                if dsl.risk.max_trades_per_day and day_state["trades"] >= dsl.risk.max_trades_per_day:
                    continue
                sl_today = day_state["sl_hits"].get(sym, 0)
                if sl_today and (not dsl.reentry.enabled or sl_today > dsl.reentry.max_per_day):
                    continue
                if i < cooldown_until.get(sym, -1):
                    continue
                el, es = sig_arr[sym]["entry_long"][i], sig_arr[sym]["entry_short"][i]
                if el == es:
                    continue
                side = 1 if el else -1
                if p.fill == "close":
                    open_position(sym, side, c, ts, i, eq_now)
                elif i + 1 < len(frames[sym]):
                    pending[sym] = ("enter", side)

            equity_pts.append(self._equity(cash, positions, last_close))
            if progress and n and k % max(1, n // 50) == 0:
                progress(k / n, f"bar {k}/{n}")

        # close anything left at the final bar
        if timeline:
            ts = timeline[-1]
            for sym in list(positions):
                close_position(sym, last_close[sym], ts, len(frames[sym]) - 1, "end_of_test")
            if equity_pts:
                equity_pts[-1] = self._equity(cash, positions, last_close)
        equity = pd.Series(equity_pts, index=pd.DatetimeIndex(timeline), dtype=float)
        return EngineResult(equity=equity, trades=trades, charges=total_charges, signals=sigs, warnings=warnings)

    @staticmethod
    def _unrealised(positions: dict[str, _Pos], last: dict[str, float]) -> float:
        return sum((last.get(s, p.entry_price) - p.entry_price) * p.qty * p.side for s, p in positions.items())

    def _equity(self, cash: float, positions: dict[str, _Pos], last: dict[str, float]) -> float:
        return cash + self._unrealised(positions, last)
