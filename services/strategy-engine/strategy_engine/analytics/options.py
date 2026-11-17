"""Options analytics: chain enrichment, payoff engine, straddles, structures, scanners."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np

from algo_common.schemas.market import Interval, OptionChain
from algo_common.timeutils import IST, expiry_from_date, now_ist, upcoming_expiries
from market_data.base import MarketDataProvider
from market_data.options import RISK_FREE, bs_greeks, bs_price_vec, implied_vol, prob_between, strike_step
from market_data.symbols import future_symbol, option_symbol, underlying_spot_symbol
from market_data.universe import EQUITIES, asset_for_underlying

# ---------------------------------------------------------------- chain enrichment


def buildup(price_chg: float, oi_chg: float) -> str:
    if oi_chg >= 0:
        return "Long buildup" if price_chg >= 0 else "Short buildup"
    return "Short covering" if price_chg >= 0 else "Long unwinding"


def years_to(expiry: date, at: datetime | None = None) -> float:
    exp = datetime.combine(expiry, time(15, 30), tzinfo=IST)
    return max(0.0, (exp - (at or now_ist())).total_seconds() / (365 * 86400))


def chain_analytics(chain: OptionChain, changes: dict[str, float] | None = None) -> dict[str, Any]:
    """`changes`: leg symbol -> day price change (from quotes) used for OI buildup classification."""
    changes = changes or {}
    t = years_to(chain.expiry)
    atm = min(chain.rows, key=lambda r: abs(r.strike - chain.spot)) if chain.rows else None
    atm_iv = None
    if atm and atm.call and atm.put and atm.call.iv and atm.put.iv:
        atm_iv = (atm.call.iv + atm.put.iv) / 2
    straddle = (atm.call.ltp + atm.put.ltp) if atm and atm.call and atm.put else None
    exp_move = chain.spot * (atm_iv / 100) * math.sqrt(t) if atm_iv else None
    rows = []
    for r in chain.rows:
        c, p = r.call, r.put
        rows.append({
            "strike": r.strike,
            "call_oi": c.oi if c else 0, "put_oi": p.oi if p else 0,
            "call_oi_change": c.oi_change if c else 0, "put_oi_change": p.oi_change if p else 0,
            "call_iv": c.iv if c else None, "put_iv": p.iv if p else None,
            "call_change": changes.get(c.symbol) if c else None, "put_change": changes.get(p.symbol) if p else None,
            "call_buildup": buildup(changes.get(c.symbol, 0.0), c.oi_change) if c else None,
            "put_buildup": buildup(changes.get(p.symbol, 0.0), p.oi_change) if p else None,
            "pcr": r.pcr,
        })
    calls = sorted(chain.rows, key=lambda r: -(r.call.oi if r.call else 0))
    puts = sorted(chain.rows, key=lambda r: -(r.put.oi if r.put else 0))
    return {
        "atm_strike": chain.atm_strike, "atm_iv": round(atm_iv, 2) if atm_iv else None,
        "atm_straddle": round(straddle, 2) if straddle else None,
        "expected_move": round(exp_move, 2) if exp_move else None,
        "expected_range": [round(chain.spot - exp_move, 2), round(chain.spot + exp_move, 2)] if exp_move else None,
        "days_to_expiry": round(t * 365, 2),
        "resistance": [r.strike for r in calls[:3]], "support": [r.strike for r in puts[:3]],
        "pcr": chain.pcr, "max_pain": chain.max_pain,
        "oi_change_pcr": round(sum(r.put.oi_change for r in chain.rows if r.put) / (sum(r.call.oi_change for r in chain.rows if r.call) or 1), 3),
        "strikes": rows,
    }


# ---------------------------------------------------------------- payoff engine


def _leg_value(leg: dict[str, Any], s: np.ndarray, t: float, iv_shift: float, r: float = RISK_FREE) -> np.ndarray:
    if leg["option_type"] == "FUT":
        return s * math.exp(r * t)
    sigma = max(0.01, leg["iv"] / 100 + iv_shift / 100)
    return bs_price_vec(s, leg["strike"], t, sigma, r, call=leg["option_type"] == "CE")


def payoff(
    spot: float, legs: list[dict[str, Any]], lot_size: int, *, expiry: date, days_forward: float = 0.0,
    spot_shift_pct: float = 0.0, iv_shift: float = 0.0, range_pct: float = 0.12, points: int = 241,
) -> dict[str, Any]:
    """legs: {action BUY|SELL, option_type CE|PE|FUT, strike, premium, iv(%), lots}"""
    s0 = spot * (1 + spot_shift_pct / 100)
    grid = np.linspace(spot * (1 - range_pct), spot * (1 + range_pct), points)
    t_now = years_to(expiry)
    t_fwd = max(0.0, t_now - days_forward / 365)
    exp_pnl = np.zeros_like(grid)
    fwd_pnl = np.zeros_like(grid)
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    net_premium = 0.0
    for leg in legs:
        sign = 1 if leg["action"] == "BUY" else -1
        qty = int(leg.get("lots", 1)) * lot_size
        prem = float(leg["premium"])
        net_premium += -sign * prem * qty
        if leg["option_type"] == "FUT":
            exp_val = grid
        else:
            exp_val = np.maximum(0, grid - leg["strike"]) if leg["option_type"] == "CE" else np.maximum(0, leg["strike"] - grid)
        exp_pnl += sign * (exp_val - prem) * qty
        fwd_pnl += sign * (_leg_value(leg, grid, t_fwd, iv_shift) - prem) * qty
        if leg["option_type"] != "FUT":
            g = bs_greeks(s0, leg["strike"], max(t_fwd, 1e-6), max(0.01, leg["iv"] / 100 + iv_shift / 100), call=leg["option_type"] == "CE")
            greeks["delta"] += sign * g.delta * qty
            greeks["gamma"] += sign * g.gamma * qty
            greeks["theta"] += sign * g.theta * qty
            greeks["vega"] += sign * g.vega * qty
        else:
            greeks["delta"] += sign * qty
    # breakevens at expiry
    be = []
    for i in range(1, len(grid)):
        if (exp_pnl[i - 1] < 0 <= exp_pnl[i]) or (exp_pnl[i - 1] > 0 >= exp_pnl[i]):
            x0, x1, y0, y1 = grid[i - 1], grid[i], exp_pnl[i - 1], exp_pnl[i]
            be.append(round(float(x0 - y0 * (x1 - x0) / (y1 - y0)), 2))
    # probability of profit (lognormal at expiry with ATM-ish IV)
    ivs = [leg["iv"] for leg in legs if leg["option_type"] != "FUT"] or [15.0]
    sigma = max(0.01, float(np.mean(ivs)) / 100)
    profit_mask = exp_pnl > 0
    pop = 0.0
    edges = np.concatenate([[grid[0] * 0.5], (grid[1:] + grid[:-1]) / 2, [grid[-1] * 1.5]])
    for i, ok in enumerate(profit_mask):
        if ok:
            pop += prob_between(spot, edges[i], edges[i + 1], t_now, sigma)
    wide = np.linspace(spot * 0.5, spot * 1.5, 801)
    wide_exp = np.zeros_like(wide)
    for leg in legs:
        sign = 1 if leg["action"] == "BUY" else -1
        qty = int(leg.get("lots", 1)) * lot_size
        if leg["option_type"] == "FUT":
            v = wide
        else:
            v = np.maximum(0, wide - leg["strike"]) if leg["option_type"] == "CE" else np.maximum(0, leg["strike"] - wide)
        wide_exp += sign * (v - leg["premium"]) * qty
    unbounded_up = wide_exp[-1] - wide_exp[-2]
    unbounded_dn = wide_exp[0] - wide_exp[1]
    max_profit = None if unbounded_up > 1e-6 or unbounded_dn > 1e-6 else round(float(wide_exp.max()), 2)
    max_loss = None if unbounded_up < -1e-6 or unbounded_dn < -1e-6 else round(float(wide_exp.min()), 2)
    return {
        "spot": round(spot, 2), "lot_size": lot_size, "net_premium": round(net_premium, 2),
        "points": [{"spot": round(float(x), 2), "expiry": round(float(a), 2), "t": round(float(b), 2)} for x, a, b in zip(grid, exp_pnl, fwd_pnl, strict=True)],
        "breakevens": be, "max_profit": max_profit, "max_loss": max_loss, "pop": round(min(1.0, pop), 4),
        "greeks": {k: round(v, 4) for k, v in greeks.items()},
        "days_to_expiry": round(t_now * 365, 2), "days_forward": days_forward,
    }


async def legs_from_chain(provider: MarketDataProvider, underlying: str, expiry: date | None,
                          specs: list[dict[str, Any]]) -> tuple[OptionChain, list[dict[str, Any]]]:
    """Resolve legs {action, option_type, strike|offset, lots} against the live chain (premium + IV)."""
    chain = await provider.option_chain(underlying, expiry, 30)
    step = strike_step(underlying, chain.spot)
    by_strike = {r.strike: r for r in chain.rows}
    legs = []
    for sp in specs:
        strike = float(sp["strike"]) if sp.get("strike") is not None else chain.atm_strike + int(sp.get("offset", 0)) * step
        if sp["option_type"] == "FUT":
            fq = (await provider.quotes([future_symbol(underlying, chain.expiry)])).get(future_symbol(underlying, chain.expiry))
            legs.append({**sp, "strike": 0.0, "premium": float(sp.get("premium") or (fq.ltp if fq else chain.spot)), "iv": 0.0,
                         "symbol": future_symbol(underlying, chain.expiry)})
            continue
        row = by_strike.get(strike) or min(chain.rows, key=lambda r: abs(r.strike - strike))
        leg = row.call if sp["option_type"] == "CE" else row.put
        premium = float(sp.get("premium") or (leg.ltp if leg else 0))
        iv = float(sp.get("iv") or (leg.iv if leg and leg.iv else 15))
        legs.append({**sp, "strike": row.strike, "premium": premium, "iv": iv, "lots": int(sp.get("lots", 1)),
                     "symbol": option_symbol(underlying, chain.expiry, row.strike, sp["option_type"])})
    return chain, legs


STRUCTURES = {
    "long_straddle": [("BUY", "CE", 0), ("BUY", "PE", 0)],
    "short_straddle": [("SELL", "CE", 0), ("SELL", "PE", 0)],
    "short_strangle": [("SELL", "CE", 3), ("SELL", "PE", -3)],
    "long_strangle": [("BUY", "CE", 3), ("BUY", "PE", -3)],
    "long_call_butterfly": [("BUY", "CE", -2), ("SELL", "CE", 0), ("SELL", "CE", 0), ("BUY", "CE", 2)],
    "iron_fly": [("SELL", "CE", 0), ("SELL", "PE", 0), ("BUY", "CE", 4), ("BUY", "PE", -4)],
    "iron_condor": [("SELL", "CE", 3), ("BUY", "CE", 6), ("SELL", "PE", -3), ("BUY", "PE", -6)],
    "bull_call_spread": [("BUY", "CE", 0), ("SELL", "CE", 3)],
    "bear_put_spread": [("BUY", "PE", 0), ("SELL", "PE", -3)],
}


def structure_specs(name: str, width: int | None = None, wing: int | None = None) -> list[dict[str, Any]]:
    base = STRUCTURES[name]
    out = []
    for action, opt, off in base:
        o = off
        if width is not None and name in ("iron_condor", "short_strangle", "long_strangle") and abs(off) == 3:
            o = int(math.copysign(width, off))
        if wing is not None and name == "iron_condor" and abs(off) == 6:
            o = int(math.copysign((width or 3) + wing, off))
        if wing is not None and name == "iron_fly" and abs(off) == 4:
            o = int(math.copysign(wing, off))
        if wing is not None and name == "long_call_butterfly" and abs(off) == 2:
            o = int(math.copysign(wing, off))
        out.append({"action": action, "option_type": opt, "offset": o, "lots": 1})
    return out


# ---------------------------------------------------------------- straddle / strangle


async def straddle_dashboard(provider: MarketDataProvider, underlying: str, expiry: date | None, otm_steps: int = 0) -> dict[str, Any]:
    chain = await provider.option_chain(underlying, expiry, 20)
    step = strike_step(underlying, chain.spot)
    ce_k, pe_k = chain.atm_strike + otm_steps * step, chain.atm_strike - otm_steps * step
    ce_sym = option_symbol(underlying, chain.expiry, ce_k, "CE")
    pe_sym = option_symbol(underlying, chain.expiry, pe_k, "PE")
    end = now_ist()
    start = end - timedelta(days=5)
    ce_c = await provider.candles(ce_sym, Interval.M5, start, end)
    pe_c = await provider.candles(pe_sym, Interval.M5, start, end)
    pe_map = {c.ts: c for c in pe_c}
    series = [{"ts": c.ts.isoformat(), "ce": c.close, "pe": pe_map[c.ts].close, "combined": round(c.close + pe_map[c.ts].close, 2)}
              for c in ce_c if c.ts in pe_map]
    ce_row = next((r for r in chain.rows if r.strike == ce_k), None)
    pe_row = next((r for r in chain.rows if r.strike == pe_k), None)
    ce_px = ce_row.call.ltp if ce_row and ce_row.call else 0
    pe_px = pe_row.put.ltp if pe_row and pe_row.put else 0
    combined = ce_px + pe_px
    spot_sym = underlying_spot_symbol(underlying)
    daily = await provider.candles(spot_sym, Interval.D1, end - timedelta(days=120), end)
    closes = np.array([c.close for c in daily])
    rets = np.diff(np.log(closes)) if len(closes) > 2 else np.array([0.0])
    hv20 = float(np.std(rets[-20:], ddof=1) * math.sqrt(252) * 100) if len(rets) > 20 else None
    hv_series = [{"ts": daily[i].ts.isoformat(), "hv": round(float(np.std(rets[i - 20:i], ddof=1) * math.sqrt(252) * 100), 2)}
                 for i in range(21, len(daily))]
    iv = ((ce_row.call.iv if ce_row and ce_row.call and ce_row.call.iv else 0) + (pe_row.put.iv if pe_row and pe_row.put and pe_row.put.iv else 0)) / 2
    t = years_to(chain.expiry)
    theta = (ce_row.call.greeks.theta if ce_row and ce_row.call else 0) + (pe_row.put.greeks.theta if pe_row and pe_row.put else 0)
    # decay projection: theoretical combined premium per remaining day at constant spot/IV
    # (hourly steps when fewer than 3 days remain, so expiry-day decay is visible)
    decay = []
    dte_days = t * 365
    steps = [i / 24 for i in range(0, max(1, math.ceil(dte_days * 24)) + 1)] if dte_days < 3 else list(range(max(1, math.ceil(dte_days)) + 1))
    for d in steps:
        tt = max(0.0, t - d / 365)
        c = bs_greeks(chain.spot, ce_k, max(tt, 1e-6), max(0.01, iv / 100), call=True).price
        p = bs_greeks(chain.spot, pe_k, max(tt, 1e-6), max(0.01, iv / 100), call=False).price
        decay.append({"day": round(d, 4), "premium": round(c + p, 2)})
    return {
        "underlying": underlying.upper(), "expiry": chain.expiry.isoformat(), "spot": chain.spot, "lot_size": chain.lot_size,
        "type": "straddle" if otm_steps == 0 else "strangle", "call_strike": ce_k, "put_strike": pe_k,
        "call_symbol": ce_sym, "put_symbol": pe_sym, "call_premium": ce_px, "put_premium": pe_px, "combined_premium": round(combined, 2),
        "breakevens": [round(pe_k - combined, 2), round(ce_k + combined, 2)],
        "breakeven_pct": round(combined / chain.spot * 100, 2), "iv": round(iv, 2), "hv20": round(hv20, 2) if hv20 else None,
        "iv_hv_ratio": round(iv / hv20, 2) if hv20 else None, "theta_per_day": round(theta, 2),
        "theta_per_lot": round(theta * chain.lot_size, 2), "days_to_expiry": round(t * 365, 2),
        "intraday": series, "hv_series": hv_series[-90:], "decay": decay,
    }


# ---------------------------------------------------------------- scanners


async def ratio_spreads(
    provider: MarketDataProvider, underlying: str, expiry: date | None, *, kind: str = "CE", ratios: tuple[int, ...] = (2, 3),
    min_credit: float | None = None, max_debit: float | None = 0.0, delta_min: float = 0.05, delta_max: float = 0.6, limit: int = 25,
) -> dict[str, Any]:
    """Buy 1 near strike, sell N further OTM strikes (front ratio). Ranked by credit / max-risk zone."""
    chain = await provider.option_chain(underlying, expiry, 25)
    rows = [r for r in chain.rows if (r.call if kind == "CE" else r.put)]
    out = []
    for i, near in enumerate(rows):
        for far in rows:
            if (kind == "CE" and far.strike <= near.strike) or (kind == "PE" and far.strike >= near.strike):
                continue
            nl = near.call if kind == "CE" else near.put
            fl = far.call if kind == "CE" else far.put
            assert nl is not None and fl is not None
            if not (delta_min <= abs(fl.greeks.delta) <= delta_max):
                continue
            for n in ratios:
                net = n * fl.ltp - nl.ltp  # credit if positive
                if max_debit is not None and net < -max_debit:
                    continue
                if min_credit is not None and net < min_credit:
                    continue
                width = abs(far.strike - near.strike)
                max_profit = width + net  # at the short strike
                # upside (CE) / downside (PE) breakeven beyond the short strike
                be = far.strike + max_profit / (n - 1) if kind == "CE" else far.strike - max_profit / (n - 1)
                lower_be = near.strike - net if net < 0 and kind == "CE" else (near.strike + net if net < 0 else None)
                net_delta = nl.greeks.delta - n * fl.greeks.delta
                out.append({
                    "type": f"1x{n} {kind} ratio", "buy_strike": near.strike, "sell_strike": far.strike, "ratio": n,
                    "buy_premium": nl.ltp, "sell_premium": fl.ltp, "net_credit": round(net, 2),
                    "net_credit_per_lot": round(net * chain.lot_size, 2), "max_profit": round(max_profit, 2),
                    "max_profit_per_lot": round(max_profit * chain.lot_size, 2), "breakeven": round(be, 2),
                    "lower_breakeven": round(lower_be, 2) if lower_be else None, "net_delta": round(net_delta, 3),
                    "short_delta": round(fl.greeks.delta, 3), "distance_pct": round(abs(be - chain.spot) / chain.spot * 100, 2),
                    "legs": [{"action": "BUY", "option_type": kind, "strike": near.strike, "premium": nl.ltp, "iv": nl.iv or 15, "lots": 1},
                             {"action": "SELL", "option_type": kind, "strike": far.strike, "premium": fl.ltp, "iv": fl.iv or 15, "lots": n}],
                })
        _ = i
    out.sort(key=lambda x: (-x["distance_pct"] if x["net_credit"] >= 0 else 0, -x["net_credit"]))
    return {"underlying": underlying.upper(), "spot": chain.spot, "expiry": chain.expiry.isoformat(), "lot_size": chain.lot_size,
            "candidates": out[:limit], "count": len(out)}


async def arbitrage_scan(provider: MarketDataProvider, cost_bps: float = 6.0) -> dict[str, Any]:
    """Cash-futures basis, calendar spreads, NSE-BSE gaps, put-call parity breaks."""
    today = expiry_from_date(now_ist())
    monthly = upcoming_expiries("_MONTHLY_", today, 2)
    stocks = [a for a in EQUITIES if a.lot_size][:40]
    syms: list[str] = []
    for a in stocks:
        syms += [a.symbol, f"BSE:{a.tradingsymbol}", future_symbol(a.tradingsymbol, monthly[0]), future_symbol(a.tradingsymbol, monthly[1])]
    q = await provider.quotes(syms)
    cash_fut, calendar, nse_bse = [], [], []
    for a in stocks:
        spot = q.get(a.symbol)
        f1 = q.get(future_symbol(a.tradingsymbol, monthly[0]))
        f2 = q.get(future_symbol(a.tradingsymbol, monthly[1]))
        bse = q.get(f"BSE:{a.tradingsymbol}")
        if spot and f1:
            t = max(1, (monthly[0] - today).days)
            basis = f1.ltp - spot.ltp
            ann = basis / spot.ltp * 365 / t * 100
            net = ann - cost_bps / 100 * 365 / t
            cash_fut.append({"symbol": a.tradingsymbol, "spot": spot.ltp, "future": f1.ltp, "expiry": monthly[0].isoformat(),
                             "basis": round(basis, 2), "basis_pct": round(basis / spot.ltp * 100, 3), "annualised_pct": round(ann, 2),
                             "net_annualised_pct": round(net, 2), "days": t, "lot_size": a.lot_size,
                             "signal": "cash & carry" if net > RISK_FREE * 100 else ("reverse c&c" if ann < 0 else "fair")})
        if f1 and f2:
            spread = f2.ltp - f1.ltp
            fair = f1.ltp * (math.exp(RISK_FREE * (monthly[1] - monthly[0]).days / 365) - 1)
            calendar.append({"symbol": a.tradingsymbol, "near": f1.ltp, "far": f2.ltp, "spread": round(spread, 2),
                             "fair_spread": round(fair, 2), "mispricing": round(spread - fair, 2),
                             "mispricing_pct": round((spread - fair) / f1.ltp * 100, 3)})
        if spot and bse:
            diff = bse.ltp - spot.ltp
            nse_bse.append({"symbol": a.tradingsymbol, "nse": spot.ltp, "bse": bse.ltp, "diff": round(diff, 2),
                            "diff_bps": round(diff / spot.ltp * 1e4, 2), "actionable": abs(diff / spot.ltp * 1e4) > cost_bps})
    pcp = []
    for und in ("NIFTY", "BANKNIFTY"):
        chain = await provider.option_chain(und, None, 10)
        t = years_to(chain.expiry)
        for r in chain.rows:
            if not (r.call and r.put):
                continue
            lhs = r.call.ltp - r.put.ltp
            rhs = chain.spot - r.strike * math.exp(-RISK_FREE * t)
            dev = lhs - rhs
            thresh = chain.spot * cost_bps / 1e4
            pcp.append({"underlying": und, "strike": r.strike, "call": r.call.ltp, "put": r.put.ltp, "c_minus_p": round(lhs, 2),
                        "s_minus_pv_k": round(rhs, 2), "deviation": round(dev, 2), "violation": abs(dev) > thresh,
                        "trade": ("sell call, buy put, buy underlying" if dev > 0 else "buy call, sell put, sell underlying") if abs(dev) > thresh else "-"})
    cash_fut.sort(key=lambda r: -abs(r["net_annualised_pct"]))
    calendar.sort(key=lambda r: -abs(r["mispricing_pct"]))
    nse_bse.sort(key=lambda r: -abs(r["diff_bps"]))
    pcp.sort(key=lambda r: -abs(r["deviation"]))
    return {"ts": now_ist().isoformat(), "cost_bps": cost_bps, "cash_futures": cash_fut, "calendar": calendar,
            "nse_bse": nse_bse, "put_call_parity": pcp,
            "note": "Gross of execution risk; net figures subtract round-trip costs of ~cost_bps. Educational only."}


def implied_vol_for(price: float, spot: float, strike: float, expiry: date, call: bool) -> float | None:
    v = implied_vol(price, spot, strike, years_to(expiry), call=call)
    return round(v * 100, 2) if v else None


def lot_size_for(underlying: str) -> int:
    a = asset_for_underlying(underlying)
    return a.lot_size if a and a.lot_size else 1
