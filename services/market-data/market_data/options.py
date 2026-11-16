"""Black-Scholes(-Merton) pricing, Greeks and implied volatility.

Conventions: `sigma` and `r` are decimals (0.14 == 14%), `t` in years,
theta is per *calendar day*, vega and rho per 1 percentage point.
Indian index options are European; stock options are European too (cash
settled since 2018/physically settled on expiry) - BS is the market norm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

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
