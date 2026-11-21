"""Deterministic, realistic synthetic market data for offline development.

* Daily history: log-price Brownian bridge between a 2019 anchor and the
  ANCHOR_DATE price, with market-factor correlation (beta), then a
  date-seeded GBM continuation after the anchor. The same symbol always yields
  the same history.
* Intraday: a 375-minute bridge from each day's open to close, seeded by
  (symbol, date); daily high/low/volume are derived from that path so 1m and 1D
  candles agree.
* Derivatives: futures = spot x carry; options = Black-Scholes on a skewed,
  VIX-linked IV surface with plausible OI / volume profiles.
* Live ticks follow today's path in real time while the market is open and stay at
  the last close when it is closed.
* Stocks load on a market factor and a sector factor; indices (NIFTY, SENSEX, Bank
  Nifty, sector indices) are cap-weighted composites of their constituents, so the
  index, heatmap, breadth and screener always agree.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import random
import time as _time
from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
from scipy.stats import norm

from algo_common.schemas.market import (
    Candle,
    DepthLevel,
    Exchange,
    Greeks,
    Instrument,
    InstrumentType,
    Interval,
    MarketStatus,
    OptionChain,
    OptionChainRow,
    Quote,
    Tick,
)
from algo_common.schemas.market import OptionLeg as Leg
from algo_common.settings import get_settings
from algo_common.timeutils import (
    IST,
    MOCK_HOLIDAYS,
    NSE_OPEN,
    expiry_from_date,
    is_market_open,
    is_trading_day,
    now_ist,
    trading_days,
    upcoming_expiries,
    year_fraction,
)
from market_data.base import DemandFn, MarketDataProvider
from market_data.options import RISK_FREE, atm_strike, bs_greeks, business_variance_ratio, strike_step
from market_data.symbols import (
    COMMODITIES,
    ParsedSymbol,
    future_symbol,
    option_symbol,
    parse,
    underlying_spot_symbol,
)
from market_data.universe import (
    ALL_ASSETS,
    ANCHOR_DATE,
    BASE_IV,
    BY_SYMBOL,
    COMMODITY_ASSETS,
    DERIVATIVE_UNDERLYINGS,
    EQUITIES,
    HISTORY_START,
    INDEX_CONSTITUENTS,
    Asset,
)

MINUTES = 375  # 09:15 -> 15:30
FULL_PATH_DAYS = 260  # ~1 year of exact intraday paths
MCX_MINUTES = 870  # 09:00 -> 23:30


def _seed(*parts: object) -> int:
    h = hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest()
    return int.from_bytes(h, "little")


def _rng(*parts: object) -> np.random.Generator:
    return np.random.default_rng(_seed(get_settings().mock_seed, *parts))


class _Daily:
    """Per-symbol daily arrays (closed form, cached)."""

    __slots__ = ("close", "dates", "high", "low", "open", "volume")

    def __init__(self, dates: list[date], o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, v: np.ndarray):
        self.dates, self.open, self.high, self.low, self.close, self.volume = dates, o, h, lo, c, v

    def index_of(self, d: date) -> int | None:
        # dates are sorted
        lo, hi = 0, len(self.dates) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.dates[mid] == d:
                return mid
            if self.dates[mid] < d:
                lo = mid + 1
            else:
                hi = mid - 1
        return None


class MockProvider(MarketDataProvider):
    name = "mock"

    def __init__(self, tick_interval_ms: int | None = None) -> None:
        self._daily: OrderedDict[tuple[str, date], _Daily] = OrderedDict()
        self._paths: OrderedDict[tuple[str, date], np.ndarray] = OrderedDict()
        self._instruments: list[Instrument] | None = None
        self._by_symbol: dict[str, Instrument] = {}
        self._noise: dict[str, tuple[float, float]] = {}
        self._tick_interval = (tick_interval_ms or get_settings().tick_interval_ms) / 1000.0
        self._market_z: np.ndarray | None = None
        self._calendar: list[date] | None = None

    # ------------------------------------------------------------------ calendar
    def _days(self) -> list[date]:
        today = now_ist().date()
        if self._calendar is None or (self._calendar[-1] < today - timedelta(days=0) and is_trading_day(today)):
            start = date.fromisoformat(HISTORY_START)
            self._calendar = trading_days(start, today)
        return self._calendar

    def _anchor_index(self, days: list[date]) -> int:
        anchor = date.fromisoformat(ANCHOR_DATE)
        idx = 0
        for i, d in enumerate(days):
            if d <= anchor:
                idx = i
        return idx

    # ------------------------------------------------------------------ daily history
    def _market_shocks(self, n: int) -> np.ndarray:
        if self._market_z is None or len(self._market_z) < n:
            self._market_z = _rng("MARKET").standard_normal(max(n, 4000))
        return self._market_z[:n]

    def _daily_for(self, asset: Asset) -> _Daily:
        days = self._days()
        key = (asset.symbol, days[-1])
        hit = self._daily.get(key)
        if hit is not None:
            self._daily.move_to_end(key)
            return hit
        n = len(days)
        sigma = asset.vol / math.sqrt(252)
        a = self._anchor_index(days)
        members = [BY_SYMBOL[m] for m in INDEX_CONSTITUENTS.get(asset.symbol, []) if m in BY_SYMBOL]
        comp_open: np.ndarray | None = None
        if members:
            # Index = cap-weighted constituents (weights fixed at the anchor date) plus a small tracking difference,
            # so NIFTY, the sector indices, the heatmap, breadth and the screener always tell the same story.
            wts = np.array([m.mcap_cr or 1.0 for m in members], dtype=float)
            wts /= wts.sum()
            dailies = [self._daily_for(m) for m in members]
            rel_c = np.vstack([d.close / d.close[a] for d in dailies])
            rel_o = np.vstack([d.open / d.close[a] for d in dailies])
            track_sd = sigma * (0.06 if len(members) >= 10 else 0.25)
            e = np.cumsum(_rng("TRACK", asset.symbol).standard_normal(n) * track_sd)
            e -= e[a]
            close = asset.price * np.exp(np.log(wts @ rel_c) + e)
            comp_open = asset.price * np.exp(np.log(wts @ rel_o) + np.concatenate([[e[0]], e[:-1]]))
        else:
            if asset.symbol.endswith("INDIAVIX"):
                rho = -0.75
            elif asset.kind == "commodity":
                rho = 0.15
            elif asset.kind == "equity":
                # market loading rises with beta; with the sector factor this gives realistic pairwise correlations
                # (~0.3-0.5) and an index volatility near NIFTY's (~11-12%) from ~25%-vol stocks
                rho = max(0.15, min(0.7, 0.2 + 0.28 * asset.beta))
            else:
                rho = 0.85
            z_m = self._market_shocks(n)
            z_i = _rng("IDIO", asset.symbol).standard_normal(n)
            if asset.kind == "equity" and asset.sector:
                s_load = min(0.42, math.sqrt(max(0.0, 0.95 - rho * rho)))
                z_s = _rng("SECTOR", asset.sector).standard_normal(n)
                z = rho * z_m + s_load * z_s + math.sqrt(max(0.0, 1 - rho * rho - s_load * s_load)) * z_i
            else:
                z = rho * z_m + math.sqrt(max(0.0, 1 - rho * rho)) * z_i
            steps = z * sigma
            logp = np.empty(n)
            w = np.cumsum(steps[: a + 1])
            w = w - w[0]
            t = np.arange(a + 1) / max(a, 1)
            logp[: a + 1] = math.log(asset.p0) + t * (math.log(asset.price) - math.log(asset.p0)) + (w - t * w[-1])
            if n > a + 1:  # continuation after the anchor date
                logp[a + 1 :] = logp[a] + np.cumsum(steps[a + 1 :])
            close = np.exp(logp)

        # Older history: vectorised gap / range model (fast). The most recent
        # FULL_PATH_DAYS use the exact minute path so 1m and 1D candles agree.
        prev = np.concatenate([[close[0] * 0.995], close[:-1]])
        rv = _rng("OLD", asset.symbol).standard_normal((n, 4))
        opens = prev * np.exp(rv[:, 0] * sigma * 0.3) if comp_open is None else comp_open.copy()
        hi_ext = np.abs(rv[:, 1]) * sigma * 0.45 + sigma * 0.15
        lo_ext = np.abs(rv[:, 2]) * sigma * 0.45 + sigma * 0.15
        highs = np.maximum(opens, close) * np.exp(hi_ext)
        lows = np.minimum(opens, close) * np.exp(-lo_ext)
        move = np.abs(np.log(close / prev)) / sigma
        vols = asset.base_volume * np.exp(rv[:, 3] * 0.25) * (0.8 + 0.35 * move)
        for i in range(max(0, n - FULL_PATH_DAYS), n):
            d = days[i]
            r = _rng("DAY", asset.symbol, d.toordinal())
            gap = r.normal(0, sigma * 0.3)  # always drawn: keeps the stream aligned with _path
            o = prev[i] * math.exp(gap) if comp_open is None else float(comp_open[i])
            opens[i] = o
            path = self._bridge(r, o, close[i], sigma, MINUTES)
            highs[i] = max(path.max(), o)
            lows[i] = min(path.min(), o)
        daily = _Daily(days, opens, highs, lows, close, vols)
        self._daily[key] = daily
        if len(self._daily) > 256:
            self._daily.popitem(last=False)
        return daily

    @staticmethod
    def _bridge(r: np.random.Generator, start: float, end: float, daily_sigma: float, steps: int) -> np.ndarray:
        """Minute-resolution log-price bridge from start to end (values at end of each minute)."""
        # U-shaped intraday volatility (higher at open and close), normalised so the session carries its share
        # of the day's variance (the rest is the overnight gap), consistent with option pricing in business time.
        u = np.linspace(-1, 1, steps)
        shape = 0.75 + 0.6 * u * u
        s = daily_sigma / math.sqrt(steps) * math.sqrt(0.91 / float(np.mean(shape * shape)))
        inc = r.standard_normal(steps) * s * shape
        w = np.cumsum(inc)
        t = np.arange(1, steps + 1) / steps
        logp = math.log(start) + t * (math.log(end) - math.log(start)) + (w - t * w[-1])
        return np.exp(logp)

    def _path(self, asset: Asset, d: date) -> np.ndarray | None:
        key = (asset.symbol, d)
        hit = self._paths.get(key)
        if hit is not None:
            return hit
        daily = self._daily_for(asset)
        i = daily.index_of(d)
        if i is None:
            return None
        r = _rng("DAY", asset.symbol, d.toordinal())
        r.normal(0, 1)  # consume the gap draw (keeps the stream aligned with _daily_for)
        sigma = asset.vol / math.sqrt(252)
        path = self._bridge(r, daily.open[i], daily.close[i], sigma, MINUTES)
        if i < len(daily.dates) - FULL_PATH_DAYS:
            # older day: squeeze the path into the (approximate) daily range
            path = np.clip(path, daily.low[i], daily.high[i])
        self._paths[key] = path
        if len(self._paths) > 2048:
            self._paths.popitem(last=False)
        return path

    # ------------------------------------------------------------------ spot prices
    def _asset(self, symbol: str) -> Asset:
        p = parse(symbol)
        if p.is_derivative and p.underlying:
            a = BY_SYMBOL.get(underlying_spot_symbol(p.underlying))
        else:
            a = BY_SYMBOL.get(symbol)
            if a is None and p.exchange == "BSE":  # BSE dual listing of an NSE stock
                a = BY_SYMBOL.get(f"NSE:{p.tradingsymbol}")
        if a is None:
            raise KeyError(f"unknown symbol {symbol}")
        return a

    def _minute_index(self, now: datetime) -> int:
        open_dt = datetime.combine(now.date(), NSE_OPEN, tzinfo=IST)
        return int((now - open_dt).total_seconds() // 60)

    def spot_at(self, asset: Asset, at: datetime) -> float:
        """Underlying price at an instant (past or present)."""
        at = at.astimezone(IST)
        daily = self._daily_for(asset)
        d = at.date()
        i = daily.index_of(d)
        if i is None:
            # weekend / holiday -> last close before
            j = len([x for x in daily.dates if x <= d]) - 1
            return float(daily.close[max(j, 0)])
        m = self._minute_index(at)
        if m < 0:
            return float(daily.close[i - 1]) if i else float(daily.open[i])
        if m >= MINUTES:
            return float(daily.close[i])
        path = self._path(asset, d)
        assert path is not None
        frac = (at.second + at.microsecond / 1e6) / 60.0
        prev = daily.open[i] if m == 0 else path[m - 1]
        return float(prev + (path[m] - prev) * frac)

    def _live_spot(self, asset: Asset) -> tuple[float, float]:
        """(ltp, previous close) right now."""
        now = now_ist()
        daily = self._daily_for(asset)
        d = now.date()
        i = daily.index_of(d)
        open_now = is_market_open(now, "MCX" if asset.kind == "commodity" else "NSE")
        if i is not None and open_now and asset.kind != "commodity":
            px = self.spot_at(asset, now)
            prev_close = float(daily.close[i - 1]) if i else px
        else:
            last = i if (i is not None and self._minute_index(now) >= MINUTES) else (
                (i - 1) if i is not None else len([x for x in daily.dates if x <= d]) - 1
            )
            last = max(0, last)
            px = float(daily.close[last])
            prev_close = float(daily.close[last - 1]) if last else px
        if not open_now:
            # Outside trading hours the last traded price is the close: nothing moves (like a real terminal).
            self._noise.pop(asset.symbol, None)
            return px, prev_close
        # Micro-noise between the minute-path points (mean reverting, bounded). It advances at most once per
        # tick interval so concurrent reads (chain + quote) agree.
        mono = _time.monotonic()
        n, last = self._noise.get(asset.symbol, (0.0, 0.0))
        if mono - last >= self._tick_interval * 0.9:
            sigma = asset.vol / math.sqrt(252 * 375 * 60) * 3
            n = max(-0.0025, min(0.0025, 0.92 * n + random.gauss(0, sigma)))
            self._noise[asset.symbol] = (n, mono)
        return px * (1 + n), prev_close

    # ------------------------------------------------------------------ derivatives pricing
    def iv_for(self, underlying: str, strike: float, spot: float, t_years: float, at: datetime | None = None) -> float:
        und = underlying.upper()
        at = at or now_ist()
        a = BY_SYMBOL.get(underlying_spot_symbol(und))
        if und in BASE_IV:
            base = BASE_IV[und]
            vix = BY_SYMBOL["NSE_INDEX:INDIAVIX"]
            base *= max(0.6, min(2.5, self.spot_at(vix, at) / vix.price))
        else:
            # implied trades above realised vol (variance risk premium)
            base = (a.vol if a else 0.3) * 1.08
        if a is None or a.kind != "commodity":
            # business-time variance quoted as a calendar-time IV (see market_data.options.business_variance_ratio)
            base *= math.sqrt(business_variance_ratio(at, t_years))
        m = math.log(strike / spot) if spot > 0 and strike > 0 else 0.0
        scale = math.sqrt(max(t_years, 1 / 365) * 12)  # wings flatten with maturity
        smile = 1 - 1.4 * m / scale + 9.0 * (m / scale) ** 2
        term = 1 + 0.08 * math.exp(-t_years * 365 / 5)  # weekly expiries carry a small premium
        noise = 1 + (_seed("IV", und, round(strike, 2)) % 1000 - 500) / 50_000
        return float(max(base * 0.6, min(base * 3.0, base * smile * term * noise)))

    def _expiry_dt(self, d: date, exchange: str = "NSE") -> datetime:
        close = time(23, 30) if exchange == "MCX" else time(15, 30)
        return datetime.combine(d, close, tzinfo=IST)

    def price_derivative(self, p: ParsedSymbol, spot: float, at: datetime) -> tuple[float, Greeks | None]:
        assert p.expiry is not None and p.underlying is not None
        t = max(0.0, (self._expiry_dt(p.expiry, p.exchange) - at.astimezone(IST)).total_seconds() / (365 * 86400))
        if p.is_future:
            basis = 1 + ((_seed("BASIS", p.tradingsymbol, at.date().toordinal()) % 1000) - 500) / 2_000_000
            return spot * math.exp(RISK_FREE * t) * basis, None
        assert p.strike is not None
        iv = self.iv_for(p.underlying, p.strike, spot * math.exp(RISK_FREE * t), t, at)
        g = bs_greeks(spot, p.strike, t, iv, call=p.option_type == "CE")
        price = max(0.05, round(g.price / 0.05) * 0.05)
        return price, Greeks(delta=g.delta, gamma=g.gamma, theta=g.theta, vega=g.vega, rho=g.rho, iv=round(iv * 100, 2))

    def _oi(self, und: str, expiry: date, strike: float, spot: float, step: float, opt: str, d: date) -> tuple[float, float]:
        a = BY_SYMBOL.get(underlying_spot_symbol(und))
        lots = a.lot_size if a and a.lot_size else 1
        dist = (strike - spot) / (step * 6)
        # calls build above spot (resistance), puts below (support)
        skew = 1.6 if (opt == "CE" and strike >= spot) or (opt == "PE" and strike <= spot) else 0.55
        bell = math.exp(-0.5 * dist * dist) * skew
        roundness = 1.8 if strike % (step * 10) == 0 else (1.3 if strike % (step * 2) == 0 else 1.0)
        liquidity = 4_000 if und in BASE_IV else 600
        noise = 0.75 + (_seed("OI", und, expiry, strike, opt, d.toordinal()) % 1000) / 2000
        oi = liquidity * lots * bell * roundness * noise + lots * 20
        chg = oi * (((_seed("OIC", und, expiry, strike, opt, d.toordinal()) % 1000) - 380) / 1500)
        return round(oi / lots) * lots, round(chg / lots) * lots

    # ------------------------------------------------------------------ instruments
    async def instruments(self, exchange: str | None = None) -> list[Instrument]:
        if self._instruments is None:
            self._instruments = self._build_instruments()
            self._by_symbol = {i.symbol: i for i in self._instruments}
        if exchange:
            return [i for i in self._instruments if i.exchange.value == exchange.upper()]
        return self._instruments

    async def instrument(self, symbol: str) -> Instrument | None:
        await self.instruments()
        hit = self._by_symbol.get(symbol)
        if hit is not None:
            return hit
        p = parse(symbol)
        if p.is_derivative:
            return self._derivative_instrument(p)
        return None

    def _spot_instrument(self, a: Asset) -> Instrument:
        ex = Exchange(a.exchange)
        kind = InstrumentType.INDEX if a.kind == "index" else InstrumentType.EQ
        seg = {"NSE_INDEX": "NSE_INDEX", "BSE_INDEX": "BSE_INDEX", "NSE": "NSE_EQ", "MCX": "MCX_FO"}.get(a.exchange, a.exchange)
        return Instrument(
            symbol=a.symbol, instrument_key=f"{seg}|{a.tradingsymbol}", exchange=ex, tradingsymbol=a.tradingsymbol,
            name=a.name, instrument_type=kind, segment=seg, lot_size=1, tick_size=0.05 if a.kind != "index" else 0.01,
            sector=a.sector, industry=a.industry, market_cap_cr=a.mcap_cr,
        )

    def _derivative_instrument(self, p: ParsedSymbol) -> Instrument | None:
        a = BY_SYMBOL.get(underlying_spot_symbol(p.underlying or ""))
        if a is None or not a.lot_size:
            return None
        ex = Exchange(p.exchange)
        seg = {"NFO": "NSE_FO", "BFO": "BSE_FO", "MCX": "MCX_FO"}[p.exchange]
        itype = InstrumentType.FUT if p.is_future else InstrumentType(p.option_type)
        name = f"{p.underlying} {p.expiry:%d %b %y}" + ("" if p.is_future else f" {p.strike:g} {p.option_type}")
        return Instrument(
            symbol=f"{p.exchange}:{p.tradingsymbol}", instrument_key=f"{seg}|{p.tradingsymbol}", exchange=ex,
            tradingsymbol=p.tradingsymbol, name=name, instrument_type=itype, segment=seg,
            underlying=a.symbol, expiry=p.expiry, strike=p.strike, lot_size=a.lot_size,
            tick_size=0.05 if p.exchange != "MCX" else 1.0, freeze_qty=a.freeze_qty or a.lot_size * 30,
            sector=a.sector,
        )

    def _build_instruments(self) -> list[Instrument]:
        out = [self._spot_instrument(a) for a in ALL_ASSETS]
        # BSE dual listings
        for a in EQUITIES[:40]:
            ins = self._spot_instrument(a)
            out.append(ins.model_copy(update={
                "symbol": f"BSE:{a.tradingsymbol}", "exchange": Exchange.BSE, "segment": "BSE_EQ",
                "instrument_key": f"BSE_EQ|{a.tradingsymbol}",
            }))
        daily_cache: dict[str, float] = {}
        for und in DERIVATIVE_UNDERLYINGS:
            a = BY_SYMBOL.get(underlying_spot_symbol(und))
            if a is None or not a.lot_size:
                continue
            exch = "BSE" if und in ("SENSEX", "BANKEX") else ("MCX" if und in COMMODITIES else "NSE")
            ref = expiry_from_date(now_ist(), exch)
            monthly = upcoming_expiries("_MONTHLY_", ref, 3, exch)
            for e in monthly:
                ins = self._derivative_instrument(parse(future_symbol(und, e)))
                if ins:
                    out.append(ins)
            if und in COMMODITIES:
                continue
            spot = daily_cache.setdefault(und, float(self._daily_for(a).close[-1]))
            step = strike_step(und, spot)
            atm = atm_strike(spot, step)
            n = 15 if und in BASE_IV else 8
            for e in upcoming_expiries(und, ref, 2, exch):
                for k in range(-n, n + 1):
                    for opt in ("CE", "PE"):
                        ins = self._derivative_instrument(parse(option_symbol(und, e, atm + k * step, opt)))
                        if ins:
                            out.append(ins)
        return out

    # ------------------------------------------------------------------ candles
    async def candles(self, symbol: str, interval: Interval, start: datetime, end: datetime) -> list[Candle]:
        return await asyncio.to_thread(self._candles_sync, symbol, interval, start, end)

    def _candles_sync(self, symbol: str, interval: Interval, start: datetime, end: datetime) -> list[Candle]:
        p = parse(symbol)
        asset = self._asset(symbol)
        start, end = start.astimezone(IST), min(end.astimezone(IST), now_ist())
        if p.is_derivative and p.expiry:
            end = min(end, self._expiry_dt(p.expiry, p.exchange))
        bse_factor = 1.0
        if p.exchange == "BSE" and not p.is_derivative:
            bse_factor = 1 + ((_seed("BSEDIFF", p.tradingsymbol, now_ist().date()) % 1000) - 500) / 1_000_000
        if interval in (Interval.D1, Interval.W1):
            spot = self._daily_candles(asset, start.date(), end.date())
            if interval == Interval.W1:
                spot = self._resample_weekly(spot)
        else:
            spot = self._intraday_candles(asset, interval, start, end)
        if not p.is_derivative:
            if bse_factor != 1.0:
                return [c.model_copy(update={k: getattr(c, k) * bse_factor for k in ("open", "high", "low", "close")}) for c in spot]
            return spot
        out: list[Candle] = []
        for c in spot:
            at = c.ts if interval not in (Interval.D1, Interval.W1) else datetime.combine(c.ts.astimezone(IST).date(), time(15, 29), tzinfo=IST)
            vals = []
            for px in (c.open, c.high, c.low, c.close):
                v, _ = self.price_derivative(p, px, at)
                vals.append(v)
            hi, lo = max(vals), min(vals)
            oi, _ = (0.0, 0.0)
            if p.is_option and p.strike is not None and p.expiry:
                step = strike_step(p.underlying or "", c.close)
                oi, _ = self._oi(p.underlying or "", p.expiry, p.strike, c.close, step, p.option_type or "CE", at.date())
            vol = c.volume * 0.05 if c.volume else (oi * 3.0 * interval.minutes / MINUTES if oi else 0.0)
            out.append(Candle(ts=c.ts, open=round(vals[0], 2), high=round(hi, 2), low=round(lo, 2), close=round(vals[3], 2),
                              volume=round(vol), oi=oi or None))
        return out

    def _daily_candles(self, asset: Asset, start: date, end: date) -> list[Candle]:
        d = self._daily_for(asset)
        now = now_ist()
        out = []
        for i, day in enumerate(d.dates):
            if day < start or day > end:
                continue
            o, h, lo, c, v = d.open[i], d.high[i], d.low[i], d.close[i], d.volume[i]
            if day == now.date() and self._minute_index(now) < MINUTES and asset.kind != "commodity":
                m = self._minute_index(now)
                if m < 0:
                    continue
                path = self._path(asset, day)
                assert path is not None
                seg = path[: m + 1]
                c = self.spot_at(asset, now)
                h, lo = max(o, seg.max(), c), min(o, seg.min(), c)
                v = v * (m + 1) / MINUTES
            ts = datetime.combine(day, time(9, 15), tzinfo=IST).astimezone(UTC)
            out.append(Candle(ts=ts, open=round(o, 2), high=round(h, 2), low=round(lo, 2), close=round(c, 2), volume=round(v)))
        return out

    @staticmethod
    def _resample_weekly(daily: list[Candle]) -> list[Candle]:
        out: list[Candle] = []
        for c in daily:
            wk = c.ts.astimezone(IST).isocalendar()[:2]
            if out and out[-1].ts.astimezone(IST).isocalendar()[:2] == wk:
                last = out[-1]
                out[-1] = last.model_copy(update={
                    "high": max(last.high, c.high), "low": min(last.low, c.low), "close": c.close,
                    "volume": last.volume + c.volume,
                })
            else:
                out.append(c.model_copy())
        return out

    def _intraday_candles(self, asset: Asset, interval: Interval, start: datetime, end: datetime) -> list[Candle]:
        step = interval.minutes
        daily = self._daily_for(asset)
        out: list[Candle] = []
        now = now_ist()
        sigma_min = asset.vol / math.sqrt(252 * MINUTES)
        for day in daily.dates:
            if day < start.date() or day > end.date():
                continue
            i = daily.index_of(day)
            path = self._path(asset, day)
            if path is None or i is None:
                continue
            limit = MINUTES
            if day == now.date():
                limit = max(0, min(MINUTES, self._minute_index(now)))
            vol_profile = 0.6 + 1.4 * np.linspace(-1, 1, MINUTES) ** 2
            vol_profile = vol_profile / vol_profile.sum() * daily.volume[i]
            r = _rng("WICK", asset.symbol, day.toordinal())
            wick = np.abs(r.standard_normal((MINUTES, 2))) * sigma_min * 0.6
            for b in range(0, limit, step):
                e = min(b + step, limit)
                o = daily.open[i] if b == 0 else path[b - 1]
                seg = path[b:e]
                c = seg[-1]
                h = max(o, seg.max()) * (1 + wick[b:e, 0].max())
                lo = min(o, seg.min()) * (1 - wick[b:e, 1].max())
                ts = datetime.combine(day, NSE_OPEN, tzinfo=IST) + timedelta(minutes=b)
                if ts < start or ts > end:
                    continue
                out.append(Candle(
                    ts=ts.astimezone(UTC), open=round(float(o), 2), high=round(float(h), 2), low=round(float(lo), 2),
                    close=round(float(c), 2), volume=round(float(vol_profile[b:e].sum())),
                ))
        return out

    # ------------------------------------------------------------------ quotes
    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for s in symbols:
            try:
                out[s] = self._quote(s)
            except KeyError:
                continue
        return out

    def _quote(self, symbol: str, with_depth: bool = True) -> Quote:
        p = parse(symbol)
        asset = self._asset(symbol)
        now = now_ist()
        spot, prev_spot = self._live_spot(asset)
        daily = self._daily_for(asset)
        i = daily.index_of(now.date())
        if i is None or (self._minute_index(now) < 0 and asset.kind != "commodity"):
            last = len([x for x in daily.dates if x <= now.date()]) - 1
            if i is not None:
                last = i - 1
            o, h, lo = daily.open[last], daily.high[last], daily.low[last]
            vol = daily.volume[last]
        else:
            o, h, lo = daily.open[i], daily.high[i], daily.low[i]
            m = self._minute_index(now)
            if 0 <= m < MINUTES:
                path = self._path(asset, now.date())
                assert path is not None
                seg = path[: m + 1]
                h, lo = max(o, seg.max(), spot), min(o, seg.min(), spot)
                vol = daily.volume[i] * (m + 1) / MINUTES
            else:
                vol = daily.volume[i]
        greeks = None
        name = asset.name
        oi = None
        if p.is_derivative:
            ltp, greeks = self.price_derivative(p, spot, now)
            prev, _ = self.price_derivative(p, prev_spot, now - timedelta(days=1))
            o_, _ = self.price_derivative(p, o, now)
            h_, _ = self.price_derivative(p, h if p.option_type != "PE" else lo, now)
            l_, _ = self.price_derivative(p, lo if p.option_type != "PE" else h, now)
            o, h, lo = o_, max(h_, ltp, o_), min(l_, ltp, o_)
            vol = vol * 0.05
            name = f"{p.underlying} {p.expiry:%d %b}" + (f" {p.strike:g} {p.option_type}" if p.is_option else " FUT")
            if p.is_option and p.expiry and p.strike is not None:
                oi, _ = self._oi(p.underlying or "", p.expiry, p.strike, spot, strike_step(p.underlying or "", spot), p.option_type or "CE", now.date())
            else:
                oi = (asset.lot_size or 1) * 60_000
        else:
            ltp, prev = spot, prev_spot
            if p.exchange == "BSE":
                f = 1 + ((_seed("BSEDIFF", p.tradingsymbol, now.date()) % 1000) - 500) / 1_000_000
                ltp, prev, o, h, lo = ltp * f, prev * f, o * f, h * f, lo * f
        tick = 0.05
        ltp = round(round(ltp / tick) * tick, 2)
        change = ltp - prev
        bids: list[DepthLevel] = []
        asks: list[DepthLevel] = []
        if with_depth and asset.kind != "index":
            spread = max(tick, round(ltp * 0.0002 / tick) * tick)
            for k in range(5):
                qty = int(abs(random.gauss(1, 0.5)) * (asset.lot_size or 50) * (k + 1) * 3) + 1
                bids.append(DepthLevel(price=round(ltp - spread * (k + 1), 2), quantity=qty, orders=max(1, qty // 40)))
                asks.append(DepthLevel(price=round(ltp + spread * (k + 1), 2), quantity=qty, orders=max(1, qty // 40)))
        hist = daily.close[-252:]
        return Quote(
            symbol=symbol, name=name, ts=now.astimezone(UTC), ltp=ltp, open=round(o, 2), high=round(max(h, ltp), 2),
            low=round(min(lo, ltp), 2), close=round(prev, 2), change=round(change, 2),
            change_pct=round(change / prev * 100, 2) if prev else 0.0, volume=round(vol), oi=oi,
            bid=bids[0].price if bids else None, ask=asks[0].price if asks else None, bids=bids, asks=asks,
            greeks=greeks, avg_price=round((o + h + lo + ltp) / 4, 2),
            upper_circuit=round(prev * 1.2, 2) if not p.is_derivative else None,
            lower_circuit=round(prev * 0.8, 2) if not p.is_derivative else None,
            week52_high=round(float(hist.max()), 2) if not p.is_derivative else None,
            week52_low=round(float(hist.min()), 2) if not p.is_derivative else None,
            total_buy_qty=float(sum(b.quantity for b in bids)) or None,
            total_sell_qty=float(sum(a.quantity for a in asks)) or None,
        )

    # ------------------------------------------------------------------ options
    async def expiries(self, underlying: str) -> list[date]:
        und = underlying.upper()
        exch = "BSE" if und in ("SENSEX", "BANKEX") else ("MCX" if und in COMMODITIES else "NSE")
        return upcoming_expiries(und, expiry_from_date(now_ist(), exch), 6, exch)

    async def option_chain(self, underlying: str, expiry: date | None = None, strikes: int = 20) -> OptionChain:
        return await asyncio.to_thread(self._chain_sync, underlying, expiry, strikes, None)

    def chain_at(self, underlying: str, expiry: date, at: datetime, strikes: int = 20) -> OptionChain:
        """Historical (synthetic) option chain - used by options backtests."""
        return self._chain_sync(underlying, expiry, strikes, at)

    def _chain_sync(self, underlying: str, expiry: date | None, strikes: int, at: datetime | None) -> OptionChain:
        und = underlying.upper()
        asset = BY_SYMBOL.get(underlying_spot_symbol(und))
        if asset is None or not asset.lot_size:
            raise KeyError(f"no derivatives for {underlying}")
        now = at or now_ist()
        exch = "BSE" if und in ("SENSEX", "BANKEX") else ("MCX" if und in COMMODITIES else "NSE")
        expiries = upcoming_expiries(und, expiry_from_date(now, exch), 6, exch)
        exp = expiry if expiry is not None else expiries[0]
        spot = self.spot_at(asset, now) if at is not None else self._live_spot(asset)[0]
        step = strike_step(und, spot)
        atm = atm_strike(spot, step)
        rows: list[OptionChainRow] = []
        t = max(0.0, (self._expiry_dt(exp, exch) - now.astimezone(IST)).total_seconds() / (365 * 86400))
        fwd = spot * math.exp(RISK_FREE * t)
        tot_c = tot_p = 0.0
        for k in range(-strikes, strikes + 1):
            strike = atm + k * step
            if strike <= 0:
                continue
            legs: dict[str, Leg] = {}
            for opt in ("CE", "PE"):
                iv = self.iv_for(und, strike, fwd, t, now)
                g = bs_greeks(spot, strike, t, iv, call=opt == "CE")
                px = max(0.05, round(g.price / 0.05) * 0.05)
                oi, chg = self._oi(und, exp, strike, spot, step, opt, now.date())
                spread = max(0.05, round(px * 0.004 / 0.05) * 0.05)
                vol = oi * (1.5 + 2.5 * math.exp(-abs(strike - spot) / (step * 4))) * (1.5 if t < 3 / 365 else 1.0)
                legs[opt] = Leg(
                    symbol=option_symbol(und, exp, strike, opt), ltp=round(px, 2), bid=round(max(0.05, px - spread), 2),
                    ask=round(px + spread, 2), volume=round(vol), oi=oi, oi_change=chg, iv=round(iv * 100, 2),
                    greeks=Greeks(delta=round(g.delta, 4), gamma=round(g.gamma, 6), theta=round(g.theta, 3),
                                  vega=round(g.vega, 3), rho=round(g.rho, 3), iv=round(iv * 100, 2)),
                )
            tot_c += legs["CE"].oi
            tot_p += legs["PE"].oi
            rows.append(OptionChainRow(
                strike=strike, expiry=exp, call=legs["CE"], put=legs["PE"],
                pcr=round(legs["PE"].oi / legs["CE"].oi, 2) if legs["CE"].oi else None,
            ))
        return OptionChain(
            underlying=und, spot=round(spot, 2), expiry=exp, expiries=expiries, lot_size=asset.lot_size,
            atm_strike=atm, rows=rows, pcr=round(tot_p / tot_c, 3) if tot_c else None, max_pain=max_pain(rows),
            total_call_oi=tot_c, total_put_oi=tot_p, ts=now.astimezone(UTC),
        )

    # ------------------------------------------------------------------ calendar
    async def market_status(self) -> list[MarketStatus]:
        now = now_ist()
        out = []
        for ex in ("NSE", "BSE", "NFO", "MCX"):
            open_ = is_market_open(now, ex)
            if open_:
                status = "open"
            elif not is_trading_day(now.date()):
                status = "closed (holiday/weekend)"
            elif now.time() < (time(9, 0) if ex == "MCX" else time(9, 15)):
                status = "pre-open" if now.time() >= time(9, 0) else "closed"
            else:
                status = "closed"
            out.append(MarketStatus(exchange=ex, status=status, is_open=open_, ts=now.astimezone(UTC)))
        return out

    async def holidays(self, year: int | None = None) -> list[dict[str, str]]:
        y = year or now_ist().year
        return [{"date": d.isoformat(), "description": "Exchange holiday (mock calendar)", "exchange": "NSE,BSE"}
                for d in sorted(MOCK_HOLIDAYS) if d.year == y]

    # ------------------------------------------------------------------ streaming
    async def stream(self, demand: DemandFn) -> AsyncIterator[list[Tick]]:  # type: ignore[override]
        while True:
            symbols = demand()
            batch: list[Tick] = []
            for s in symbols:
                try:
                    q = self._quote(s, with_depth=False)
                except (KeyError, ValueError):
                    continue
                batch.append(Tick(
                    symbol=s, ts=q.ts, ltp=q.ltp, volume=q.volume, oi=q.oi, open=q.open, high=q.high, low=q.low,
                    close=q.close, change=q.change, change_pct=q.change_pct, greeks=q.greeks,
                ))
            if batch:
                yield batch
            await asyncio.sleep(self._tick_interval)

    # ------------------------------------------------------------------ helpers for analytics
    def daily_closes(self, symbol: str) -> tuple[list[date], np.ndarray]:
        d = self._daily_for(self._asset(symbol))
        return d.dates, d.close


def max_pain(rows: list[OptionChainRow]) -> float | None:
    if not rows:
        return None
    strikes = np.array([r.strike for r in rows])
    call_oi = np.array([r.call.oi if r.call else 0 for r in rows])
    put_oi = np.array([r.put.oi if r.put else 0 for r in rows])
    pain = [
        float(np.sum(call_oi * np.maximum(0, k - strikes)) + np.sum(put_oi * np.maximum(0, strikes - k)))
        for k in strikes
    ]
    return float(strikes[int(np.argmin(pain))])


def bs_vec(s: np.ndarray, k: float, t: np.ndarray, sigma: np.ndarray, call: bool, r: float = RISK_FREE) -> np.ndarray:
    """Fully vectorised BS over arrays of spot / time / vol (used by options backtests)."""
    t = np.maximum(t, 1e-9)
    sq = np.sqrt(t)
    d1 = (np.log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * sq)
    d2 = d1 - sigma * sq
    if call:
        return s * norm.cdf(d1) - k * np.exp(-r * t) * norm.cdf(d2)
    return k * np.exp(-r * t) * norm.cdf(-d2) - s * norm.cdf(-d1)


__all__ = ["COMMODITY_ASSETS", "MockProvider", "bs_vec", "max_pain", "year_fraction"]
