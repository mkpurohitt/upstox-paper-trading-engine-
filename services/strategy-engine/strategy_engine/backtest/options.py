"""Multi-leg options backtester.

Each trading day: when the entry window opens and the (optional) entry
conditions on the underlying are true, legs are selected from the option
chain *at that moment* (ATM±n / delta / premium), then marked to market every
bar. Exits: combined premium SL/target (% of net premium or ₹), leg-wise SL /
target, square-off time, expiry settlement (STT on exercised ITM longs), and
optional re-entry after a stop.

Historical option prices come from an `OptionPricer`:
* `MockChainPricer` - the mock provider's IV surface (consistent with the
  offline option chain), or
* `HVPricer` - Black-Scholes with the underlying's realised volatility and a
  skew model (used with live underlying data when no chain snapshots exist).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol

import numpy as np
import pandas as pd

from algo_common.timeutils import IST, upcoming_expiries
from market_data.options import RISK_FREE, atm_strike, bs_greeks, business_variance_ratio, strike_step
from market_data.symbols import option_symbol, parse
from strategy_engine.backtest.engine import BacktestParams, EngineResult, ProgressFn, round_tick
from strategy_engine.costs import Charges, CostModel, split_orders
from strategy_engine.dsl import OptionLegSpec, StrategyDSL
from strategy_engine.signals import generate_signals, ist_index


class OptionPricer(Protocol):
    def iv(self, underlying: str, strike: float, spot: float, t_years: float, at: datetime) -> float: ...


class MockChainPricer:
    def __init__(self) -> None:
        from market_data.registry import get_mock

        self.mock = get_mock()

    def iv(self, underlying: str, strike: float, spot: float, t_years: float, at: datetime) -> float:
        return self.mock.iv_for(underlying, strike, spot, t_years, at)


class HVPricer:
    """Realised-vol based IV with a simple negative skew."""

    def __init__(self, daily_close: pd.Series) -> None:
        r = np.log(daily_close).diff()
        self.hv = (r.rolling(20).std() * math.sqrt(252)).bfill().fillna(0.15)
        self.hv.index = pd.to_datetime(self.hv.index)

    def iv(self, underlying: str, strike: float, spot: float, t_years: float, at: datetime) -> float:
        d = pd.Timestamp(at.astimezone(IST).date())
        base = float(self.hv.asof(d)) if len(self.hv) else 0.15
        base = max(0.06, base * 1.1)
        m = math.log(strike / spot)
        scale = math.sqrt(max(t_years, 1 / 365) * 12)
        base *= math.sqrt(business_variance_ratio(at, t_years))  # variance arrives in trading hours
        return base * max(0.6, 1 - 1.4 * m / scale + 9 * (m / scale) ** 2)


@dataclass
class _Leg:
    spec: OptionLegSpec
    symbol: str
    strike: float
    opt: str
    expiry: date
    qty: int
    sign: int  # +1 buy, -1 sell
    entry_price: float
    entry_ts: pd.Timestamp
    charges: Charges = field(default_factory=Charges)
    exit_price: float | None = None
    exit_ts: pd.Timestamp | None = None
    exit_reason: str | None = None


def _hhmm(s: str | None) -> time | None:
    if not s:
        return None
    h, m = s.split(":")
    return time(int(h), int(m))


class OptionsEngine:
    def __init__(self, dsl: StrategyDSL, params: BacktestParams, pricer: OptionPricer, lot_size: int, freeze_qty: int | None) -> None:
        self.dsl = dsl
        self.p = params
        self.pricer = pricer
        self.lot = lot_size
        self.freeze = freeze_qty
        self.und = (dsl.universe.underlying or "NIFTY").upper()
        self.exch = "BSE" if self.und in ("SENSEX", "BANKEX") else "NSE"
        self.costs = CostModel(params.broker)
        self.multiplier = int(dsl.sizing.value) if dsl.sizing.mode == "fixed_lots" else 1

    # ---- pricing ------------------------------------------------------------------
    @staticmethod
    def _t(expiry: date, at: datetime) -> float:
        exp_dt = datetime.combine(expiry, time(15, 30), tzinfo=IST)
        return max(0.0, (exp_dt - at.astimezone(IST)).total_seconds() / (365 * 86400))

    def price(self, strike: float, opt: str, expiry: date, spot: float, at: datetime) -> tuple[float, float]:
        t = self._t(expiry, at)
        if t <= 0:
            intrinsic = max(0.0, spot - strike) if opt == "CE" else max(0.0, strike - spot)
            return intrinsic, (1.0 if intrinsic > 0 else 0.0) * (1 if opt == "CE" else -1)
        iv = self.pricer.iv(self.und, strike, spot * math.exp(RISK_FREE * t), t, at)
        g = bs_greeks(spot, strike, t, iv, call=opt == "CE")
        return max(0.05, round_tick(g.price, 0.05)), g.delta

    def _expiry(self, which: str, d: date) -> date:
        if which == "monthly":
            return upcoming_expiries("_MONTHLY_", d, 1, self.exch)[0]
        exps = upcoming_expiries(self.und, d, 2, self.exch)
        return exps[1] if which == "next" else exps[0]

    def _select_strike(self, leg: OptionLegSpec, spot: float, expiry: date, at: datetime) -> float:
        step = strike_step(self.und, spot)
        atm = atm_strike(spot, step)
        sel = leg.strike
        if sel.mode == "ATM_OFFSET" or leg.option_type == "FUT":
            return atm + sel.offset * step
        candidates = [atm + k * step for k in range(-30, 31)]
        target_delta, target_premium = sel.delta, sel.premium
        if sel.mode == "DELTA" and target_delta:
            return min(candidates, key=lambda k: abs(abs(self.price(k, leg.option_type, expiry, spot, at)[1]) - target_delta))
        if sel.mode == "PREMIUM" and target_premium:
            return min(candidates, key=lambda k: abs(self.price(k, leg.option_type, expiry, spot, at)[0] - target_premium))
        return atm

    def _charge(self, ts: pd.Timestamp, sign: int, price: float, qty: int, exercised: float = 0.0) -> Charges:
        orders = len(split_orders(qty, self.freeze, self.lot))
        return self.costs.charges(
            on=ts.tz_convert(IST).date(), side="BUY" if sign > 0 else "SELL", price=price, quantity=qty,
            exchange="BFO" if self.exch == "BSE" else "NSE", instrument="CE", product="NRML", orders=orders,
            exercised_intrinsic=exercised,
        )

    def _fill(self, price: float, sign: int) -> float:
        slip = max(0.05, price * self.p.slippage_bps / 1e4)
        return max(0.05, round_tick(price + slip if sign > 0 else price - slip, 0.05))

    # ---- main loop ------------------------------------------------------------------
    def run(self, frame: pd.DataFrame, progress: ProgressFn | None = None) -> EngineResult:
        dsl = self.dsl
        sig = generate_signals(frame, dsl)
        cond = sig["entry_long"].to_numpy(bool) if dsl.entry.long else np.ones(len(frame), dtype=bool)
        idx = ist_index(frame)
        close, high, low = frame["close"].to_numpy(float), frame["high"].to_numpy(float), frame["low"].to_numpy(float)
        entry_after, entry_before = _hhmm(dsl.schedule.entry_after), _hhmm(dsl.schedule.entry_before)
        sq = _hhmm(dsl.schedule.square_off) if dsl.product != "NRML" or dsl.schedule.square_off else None
        days = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}
        allowed = {days[d] for d in dsl.schedule.days}
        ox = dsl.options_exit

        cash = self.p.initial_capital
        legs: list[_Leg] = []
        net_premium = 0.0
        set_entry_ts: pd.Timestamp | None = None
        trades: list[dict[str, Any]] = []
        leg_trades: list[dict[str, Any]] = []
        total = Charges()
        eq: list[float] = []
        cur_day: date | None = None
        entries_today = sl_today = 0
        day_pnl = 0.0
        halted_day = False

        def mtm(spot: float, at: datetime) -> float:
            v = 0.0
            for lg in legs:
                if lg.exit_price is not None:
                    v += (lg.exit_price - lg.entry_price) * lg.qty * lg.sign
                else:
                    px, _ = self.price(lg.strike, lg.opt, lg.expiry, spot, at)
                    v += (px - lg.entry_price) * lg.qty * lg.sign
            return v

        def close_leg(lg: _Leg, spot: float, ts: pd.Timestamp, reason: str) -> None:
            nonlocal cash, total
            at = ts.to_pydatetime()
            raw, _ = self.price(lg.strike, lg.opt, lg.expiry, spot, at)
            expired = self._t(lg.expiry, at) <= 0
            px = raw if expired else self._fill(raw, -lg.sign)
            exercised = raw if (expired and lg.sign > 0 and raw > 0) else 0.0
            ch = self._charge(ts, -lg.sign, 0.0 if expired else px, lg.qty, exercised)
            lg.exit_price, lg.exit_ts, lg.exit_reason = px, ts, reason
            lg.charges = lg.charges + ch
            total = total + ch
            cash += (px - lg.entry_price) * lg.qty * lg.sign - ch.total

        def close_set(spot: float, ts: pd.Timestamp, reason: str, bars: int) -> None:
            nonlocal legs, net_premium, day_pnl, sl_today
            for lg in legs:
                if lg.exit_price is None:
                    close_leg(lg, spot, ts, reason)
            gross = sum(((lg.exit_price or 0.0) - lg.entry_price) * lg.qty * lg.sign for lg in legs)
            charges = sum(lg.charges.total for lg in legs)
            net = gross - charges
            day_pnl += net
            if reason in ("stop_loss", "leg_stop_loss"):
                sl_today += 1
            trades.append({
                "symbol": f"{self.und} {len(legs)}-leg", "side": "SET", "quantity": legs[0].qty if legs else 0,
                "entry_ts": set_entry_ts.isoformat() if set_entry_ts else ts.isoformat(), "entry_price": round(net_premium, 2),
                "exit_ts": ts.isoformat(), "exit_price": None, "gross_pnl": round(gross, 2), "charges": round(charges, 2),
                "net_pnl": round(net, 2), "exit_reason": reason, "bars_held": bars,
                "legs": [{"leg": lg.spec.id, "symbol": lg.symbol, "action": lg.spec.action, "qty": lg.qty,
                          "entry": lg.entry_price, "exit": lg.exit_price, "reason": lg.exit_reason} for lg in legs],
            })
            for lg in legs:
                leg_trades.append({
                    "symbol": lg.symbol, "leg": lg.spec.id, "side": "LONG" if lg.sign > 0 else "SHORT", "quantity": lg.qty,
                    "entry_ts": lg.entry_ts.isoformat(), "entry_price": lg.entry_price,
                    "exit_ts": lg.exit_ts.isoformat() if lg.exit_ts else None, "exit_price": lg.exit_price,
                    "gross_pnl": round((lg.exit_price - lg.entry_price) * lg.qty * lg.sign, 2),  # type: ignore[operator]
                    "charges": round(lg.charges.total, 2),
                    "net_pnl": round((lg.exit_price - lg.entry_price) * lg.qty * lg.sign - lg.charges.total, 2),  # type: ignore[operator]
                    "exit_reason": lg.exit_reason, "bars_held": bars,
                })
            legs = []
            net_premium = 0.0

        entry_bar = 0
        n = len(frame)
        for i in range(n):
            ts = frame.index[i]
            t_ist = idx[i]
            at = t_ist.to_pydatetime()
            d = t_ist.date()
            if d != cur_day:
                cur_day, entries_today, sl_today, day_pnl, halted_day = d, 0, 0, 0.0, False
            spot = close[i]
            bt = t_ist.time()

            if legs:
                # intrabar worst case using underlying extremes
                worst = min(mtm(high[i], at), mtm(low[i], at))
                cur = mtm(spot, at)
                credit = abs(net_premium) if net_premium else 1.0
                reason = None
                if ox.stop_loss_amount and worst <= -ox.stop_loss_amount:
                    reason = "stop_loss"
                elif ox.combined_stop_loss_pct and worst <= -credit * legs[0].qty * ox.combined_stop_loss_pct / 100:
                    reason = "stop_loss"
                elif ox.target_amount and cur >= ox.target_amount:
                    reason = "target"
                elif ox.combined_target_pct and cur >= credit * legs[0].qty * ox.combined_target_pct / 100:
                    reason = "target"
                elif sq and bt >= sq and dsl.product == "MIS":
                    reason = "square_off"
                elif any(self._t(lg.expiry, at) <= 0 or (lg.expiry == d and bt >= time(15, 25)) for lg in legs):
                    reason = "expiry"
                elif ox.exit_on_expiry_day_at and any(lg.expiry == d for lg in legs) and bt >= (_hhmm(ox.exit_on_expiry_day_at) or time(15, 15)):
                    reason = "expiry_day_exit"
                if reason:
                    close_set(spot, ts, reason, i - entry_bar)
                else:
                    for lg in legs:
                        if lg.exit_price is not None:
                            continue
                        px, _ = self.price(lg.strike, lg.opt, lg.expiry, spot, at)
                        sl, tg = lg.spec.stop_loss_pct, lg.spec.target_pct
                        if sl and ((lg.sign < 0 and px >= lg.entry_price * (1 + sl / 100)) or (lg.sign > 0 and px <= lg.entry_price * (1 - sl / 100))):
                            close_leg(lg, spot, ts, "leg_stop_loss")
                        elif tg and ((lg.sign < 0 and px <= lg.entry_price * (1 - tg / 100)) or (lg.sign > 0 and px >= lg.entry_price * (1 + tg / 100))):
                            close_leg(lg, spot, ts, "leg_target")
                    if legs and all(lg.exit_price is not None for lg in legs):
                        close_set(spot, ts, "legs_closed", i - entry_bar)
                if dsl.risk.max_loss_per_day and day_pnl + (mtm(spot, at) if legs else 0) <= -dsl.risk.max_loss_per_day:
                    if legs:
                        close_set(spot, ts, "daily_loss_limit", i - entry_bar)
                    halted_day = True

            can_enter = (
                not legs and not halted_day and t_ist.dayofweek in allowed
                and (entry_after is None or bt >= entry_after) and (entry_before is None or bt < entry_before)
                and cond[i] and (sq is None or bt < sq or dsl.product != "MIS")
            )
            max_entries = 1 + (dsl.reentry.max_per_day if dsl.reentry.enabled else 0)
            if dsl.risk.max_trades_per_day:
                max_entries = min(max_entries, dsl.risk.max_trades_per_day)
            if can_enter and entries_today < max_entries and (entries_today == 0 or sl_today > 0):
                set_entry_ts, entry_bar = ts, i
                net_premium = 0.0
                for spec in dsl.legs:
                    expiry = self._expiry(spec.expiry, d)
                    if spec.option_type == "FUT":
                        continue  # futures legs are not modelled in the options engine
                    strike = self._select_strike(spec, spot, expiry, at)
                    raw, _ = self.price(strike, spec.option_type, expiry, spot, at)
                    sign = 1 if spec.action == "BUY" else -1
                    qty = spec.lots * self.lot * self.multiplier
                    px = self._fill(raw, sign)
                    ch = self._charge(ts, sign, px, qty)
                    total = total + ch
                    cash -= ch.total
                    net_premium += -sign * px
                    legs.append(_Leg(spec, option_symbol(self.und, expiry, strike, spec.option_type), strike,
                                     spec.option_type, expiry, qty, sign, px, ts, ch))
                entries_today += 1

            eq.append(cash + (mtm(spot, at) - sum(
                (lg.exit_price - lg.entry_price) * lg.qty * lg.sign for lg in legs if lg.exit_price is not None) if legs else 0.0))
            if progress and n and i % max(1, n // 50) == 0:
                progress(i / n, f"bar {i}/{n}")

        if legs and n:
            close_set(close[-1], frame.index[-1], "end_of_test", n - 1 - entry_bar)
            eq[-1] = cash
        res = EngineResult(equity=pd.Series(eq, index=frame.index, dtype=float), trades=trades, charges=total,
                           signals={"underlying": sig})
        res.warnings.append("Option prices are modelled (Black-Scholes on an IV surface), not exchange tick data.")
        res.leg_trades = leg_trades  # type: ignore[attr-defined]
        return res


def lot_meta(underlying: str) -> tuple[int, int | None]:
    from market_data.universe import asset_for_underlying

    a = asset_for_underlying(underlying)
    if a is None or not a.lot_size:
        return 1, None
    return a.lot_size, a.freeze_qty


__all__ = ["HVPricer", "MockChainPricer", "OptionsEngine", "lot_meta", "parse", "timedelta"]
