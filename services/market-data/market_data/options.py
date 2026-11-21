"""Black-Scholes(-Merton) pricing, Greeks and implied volatility.

Conventions: `sigma` and `r` are decimals (0.14 == 14%), `t` in years,
theta is per *calendar day*, vega and rho per 1 percentage point.
Indian index options are European; stock options are European too (cash
settled since 2018/physically settled on expiry) - BS is the market norm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache

import numpy as np
from scipy.stats import norm

from algo_common.timeutils import IST, is_trading_day

RISK_FREE = 0.065  # ~ 91-day T-bill
_SQRT_2PI = math.sqrt(2 * math.pi)


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


@dataclass(frozen=True)
class BSResult:
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


def bs_price(s: float, k: float, t: float, sigma: float, r: float = RISK_FREE, call: bool = True, q: float = 0.0) -> float:
    if t <= 0 or sigma <= 0:
        return max(0.0, (s - k) if call else (k - s))
    sqt = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * sqt)
    d2 = d1 - sigma * sqt
    if call:
        return s * math.exp(-q * t) * _ncdf(d1) - k * math.exp(-r * t) * _ncdf(d2)
    return k * math.exp(-r * t) * _ncdf(-d2) - s * math.exp(-q * t) * _ncdf(-d1)


def bs_greeks(s: float, k: float, t: float, sigma: float, r: float = RISK_FREE, call: bool = True, q: float = 0.0) -> BSResult:
    price = bs_price(s, k, t, sigma, r, call, q)
    if t <= 0 or sigma <= 0:
        itm = (s > k) if call else (s < k)
        return BSResult(price, (1.0 if call else -1.0) if itm else 0.0, 0.0, 0.0, 0.0, 0.0)
    sqt = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * sqt)
    d2 = d1 - sigma * sqt
    pdf = _npdf(d1)
    disc_q, disc_r = math.exp(-q * t), math.exp(-r * t)
    gamma = disc_q * pdf / (s * sigma * sqt)
    vega = s * disc_q * pdf * sqt / 100.0
    if call:
        delta = disc_q * _ncdf(d1)
        theta = (-s * disc_q * pdf * sigma / (2 * sqt) - r * k * disc_r * _ncdf(d2) + q * s * disc_q * _ncdf(d1)) / 365.0
        rho = k * t * disc_r * _ncdf(d2) / 100.0
    else:
        delta = -disc_q * _ncdf(-d1)
        theta = (-s * disc_q * pdf * sigma / (2 * sqt) + r * k * disc_r * _ncdf(-d2) - q * s * disc_q * _ncdf(-d1)) / 365.0
        rho = -k * t * disc_r * _ncdf(-d2) / 100.0
    return BSResult(price, delta, gamma, theta, vega, rho)


def implied_vol(
    price: float, s: float, k: float, t: float, r: float = RISK_FREE, call: bool = True, q: float = 0.0
) -> float | None:
    """Newton-Raphson with bisection fallback. Returns None when no solution."""
    if t <= 0 or price <= 0:
        return None
    intrinsic = max(0.0, (s * math.exp(-q * t) - k * math.exp(-r * t)) if call else (k * math.exp(-r * t) - s * math.exp(-q * t)))
    if price < intrinsic - 1e-6:
        return None
    sigma = 0.25
    for _ in range(50):
        g = bs_greeks(s, k, t, sigma, r, call, q)
        diff = g.price - price
        if abs(diff) < 1e-5:
            return sigma
        v = g.vega * 100.0
        if v < 1e-8:
            break
        sigma -= diff / v
        if not 0.001 < sigma < 5.0:
            break
    lo, hi = 1e-4, 5.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if bs_price(s, k, t, mid, r, call, q) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-6:
            return mid
    return None


# ---- vectorised helpers (payoff diagrams, scanners) ---------------------------------

def bs_price_vec(s: np.ndarray, k: float, t: float, sigma: float, r: float = RISK_FREE, call: bool = True) -> np.ndarray:
    s = np.asarray(s, dtype=float)
    if t <= 0 or sigma <= 0:
        return np.maximum(0.0, (s - k) if call else (k - s))
    sqt = np.sqrt(t)
    d1 = (np.log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * sqt)
    d2 = d1 - sigma * sqt
    if call:
        return s * norm.cdf(d1) - k * np.exp(-r * t) * norm.cdf(d2)
    return k * np.exp(-r * t) * norm.cdf(-d2) - s * norm.cdf(-d1)


def prob_between(s: float, lo: float, hi: float, t: float, sigma: float, r: float = RISK_FREE) -> float:
    """Risk-neutral probability that S_T ends inside [lo, hi] (lognormal)."""
    if t <= 0 or sigma <= 0:
        return 1.0 if lo <= s <= hi else 0.0

    def cdf(x: float) -> float:
        if x <= 0:
            return 0.0
        d2 = (math.log(s / x) + (r - 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
        return 1.0 - _ncdf(d2)

    return max(0.0, min(1.0, cdf(hi) - cdf(lo)))


def strike_step(underlying: str, spot: float) -> float:
    u = underlying.upper()
    table = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25, "SENSEX": 100, "BANKEX": 100,
             "CRUDEOIL": 50, "NATURALGAS": 5, "GOLD": 100, "SILVER": 250}
    if u in table:
        return float(table[u])
    if spot < 250:
        return 2.5
    if spot < 500:
        return 5.0
    if spot < 1000:
        return 10.0
    if spot < 2500:
        return 20.0
    if spot < 5000:
        return 50.0
    return 100.0


def atm_strike(spot: float, step: float) -> float:
    return round(spot / step) * step


# ---------------------------------------------------------------------------------------------------- business time
# Prices only move while the exchange is open (plus the overnight gap), but quoted IVs and Greeks use calendar
# time (NSE convention). Pricing with calendar time alone makes options decay 24x7 while variance arrives only in
# trading hours, which systematically mis-prices intraday option P&L. We therefore measure variance in trading
# days (252 a year): each trading day = an overnight gap (GAP_SHARE) + a 375-minute session, and convert a
# business-time volatility into the calendar-quoted IV that gives the same total variance.
SESSION_OPEN, SESSION_CLOSE, SESSION_MINUTES = time(9, 15), time(15, 30), 375
GAP_SHARE = 0.09  # share of a day's variance realised in the overnight gap


def _trading_day_units(at: datetime, expiry: datetime) -> float:
    """Variance-weighted trading days between ``at`` and ``expiry`` (both aware datetimes)."""
    a, e = at.astimezone(IST), expiry.astimezone(IST)
    if e <= a:
        return 0.0

    def remaining_today(t: datetime, until: datetime | None) -> float:
        if not is_trading_day(t.date()):
            return 0.0
        start = datetime.combine(t.date(), SESSION_OPEN, tzinfo=IST)
        close = datetime.combine(t.date(), SESSION_CLOSE, tzinfo=IST)
        end = min(close, until) if until else close
        units = 0.0
        if t < start:
            units += GAP_SHARE
            t = start
        if end > t:
            units += (1 - GAP_SHARE) * (end - t).total_seconds() / (SESSION_MINUTES * 60)
        return units

    if a.date() == e.date():
        return remaining_today(a, e)
    units = remaining_today(a, None)
    d = a.date() + timedelta(days=1)
    while d < e.date():
        if is_trading_day(d):
            units += 1.0
        d += timedelta(days=1)
    return units + remaining_today(datetime.combine(e.date(), time(0, 0), tzinfo=IST), e)


@lru_cache(maxsize=4096)
def _ratio_cached(at_min: int, exp_min: int) -> float:
    at = datetime.fromtimestamp(at_min * 60, IST)
    exp = datetime.fromtimestamp(exp_min * 60, IST)
    t_cal = (exp - at).total_seconds() / (365 * 86400)
    if t_cal <= 0:
        return 1.0
    t_bus = _trading_day_units(at, exp) / 252
    return max(0.05, min(12.0, t_bus / t_cal))


def business_variance_ratio(at: datetime, t_years: float) -> float:
    """T_business / T_calendar for an option expiring ``t_years`` (calendar) after ``at``.

    Multiply a business-time variance by this ratio to get the calendar-time variance to quote:
    ``iv_calendar = sigma_business * sqrt(ratio)``.
    """
    if t_years <= 0:
        return 1.0
    exp = at + timedelta(seconds=t_years * 365 * 86400)
    return _ratio_cached(int(at.timestamp() // 60), int(exp.timestamp() // 60))


def business_date_units(at: datetime, expiry_day: date) -> float:
    """Trading-day units from ``at`` to the 15:30 close of ``expiry_day`` (for display/what-if helpers)."""
    return _trading_day_units(at, datetime.combine(expiry_day, SESSION_CLOSE, tzinfo=IST))
