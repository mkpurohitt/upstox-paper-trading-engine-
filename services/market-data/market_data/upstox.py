"""Upstox market data provider (API v2 / v3, analytics token).

* Instrument master: https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz
  (refreshed daily; NSE, BSE, NFO(NSE_FO), BFO(BSE_FO), MCX_FO, indices)
* Historical candles: GET /v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}
* Intraday candles:   GET /v3/historical-candle/intraday/{key}/{unit}/{interval}
* Quotes / LTP / OHLC: GET /v3/market-quote/quotes | ltp | ohlc, /v3/market-quote/option-greek
* Option chain:        GET /v2/option/chain?instrument_key=..&expiry_date=..
* Contracts/expiries:  GET /v2/option/contract?instrument_key=..
* Market status:       GET /v2/market/status/{exchange}, holidays: GET /v2/market/holidays
* Live feed:           GET /v3/feed/market-data-feed/authorize -> wss (protobuf FeedResponse)

All responses are normalised to `algo_common.schemas.market`.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote as urlquote

import httpx

from algo_common.errors import NotConfiguredError, ProviderError, RateLimitedError
from algo_common.logging import get_logger
from algo_common.metrics import TICKS_PUBLISHED
from algo_common.ratelimit import TokenBucket
from algo_common.retry import retry_async
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
    OptionLeg,
    Quote,
    Tick,
)
from algo_common.settings import get_settings
from algo_common.timeutils import IST, now_ist
from market_data.base import DemandFn, MarketDataProvider
from market_data.mock import max_pain
from market_data.options import atm_strike, strike_step
from market_data.symbols import future_symbol, option_symbol, underlying_spot_symbol

log = get_logger("upstox")

SEGMENT_TO_EXCHANGE = {
    "NSE_EQ": "NSE", "BSE_EQ": "BSE", "NSE_FO": "NFO", "BSE_FO": "BFO", "MCX_FO": "MCX",
    "NSE_INDEX": "NSE_INDEX", "BSE_INDEX": "BSE_INDEX", "NCD_FO": "CDS",
}
INDEX_ALIASES = {
    "NSE_INDEX|Nifty 50": "NSE_INDEX:NIFTY",
    "NSE_INDEX|Nifty Bank": "NSE_INDEX:BANKNIFTY",
    "NSE_INDEX|Nifty Fin Service": "NSE_INDEX:FINNIFTY",
    "NSE_INDEX|NIFTY MID SELECT": "NSE_INDEX:MIDCPNIFTY",
    "NSE_INDEX|India VIX": "NSE_INDEX:INDIAVIX",
    "NSE_INDEX|Nifty IT": "NSE_INDEX:NIFTYIT",
    "NSE_INDEX|Nifty Pharma": "NSE_INDEX:NIFTYPHARMA",
    "NSE_INDEX|Nifty Auto": "NSE_INDEX:NIFTYAUTO",
    "NSE_INDEX|Nifty FMCG": "NSE_INDEX:NIFTYFMCG",
    "NSE_INDEX|Nifty Metal": "NSE_INDEX:NIFTYMETAL",
    "NSE_INDEX|Nifty Realty": "NSE_INDEX:NIFTYREALTY",
    "NSE_INDEX|Nifty Energy": "NSE_INDEX:NIFTYENERGY",
    "BSE_INDEX|SENSEX": "BSE_INDEX:SENSEX",
    "BSE_INDEX|BANKEX": "BSE_INDEX:BANKEX",
}
_INTERVALS: dict[Interval, tuple[str, str]] = {
    Interval.M1: ("minutes", "1"), Interval.M3: ("minutes", "3"), Interval.M5: ("minutes", "5"),
    Interval.M15: ("minutes", "15"), Interval.M30: ("minutes", "30"), Interval.H1: ("hours", "1"),
    Interval.D1: ("days", "1"), Interval.W1: ("weeks", "1"),
}
POLL_SECONDS = 2.0  # REST polling interval when the WebSocket feed is not available for the token
# Upstox v3 history depth per unit (chunk size when paging large ranges)
_CHUNK_DAYS = {"minutes": 30, "hours": 90, "days": 3650, "weeks": 3650}


def instrument_from_upstox(row: dict[str, Any]) -> Instrument | None:
    """Map one instrument-master row to the canonical Instrument."""
    seg = row.get("segment", "")
    exch = SEGMENT_TO_EXCHANGE.get(seg)
    if exch is None:
        return None
    key = row["instrument_key"]
    itype = (row.get("instrument_type") or "").upper()
    ts = (row.get("trading_symbol") or row.get("tradingsymbol") or "").upper()
    expiry = None
    if row.get("expiry"):
        expiry = datetime.fromtimestamp(int(row["expiry"]) / 1000, tz=IST).date()
    strike = float(row["strike_price"]) if row.get("strike_price") else None
    underlying = (row.get("underlying_symbol") or row.get("name") or "").upper().replace(" ", "")
    if seg.endswith("_INDEX"):
        symbol = INDEX_ALIASES.get(key, f"{exch}:{ts.replace(' ', '')}")
        kind = InstrumentType.INDEX
    elif itype in ("CE", "PE") and expiry and strike is not None:
        symbol = option_symbol(underlying, expiry, strike, itype, exchange=exch)
        kind = InstrumentType(itype)
    elif itype in ("FUT", "FUTIDX", "FUTSTK", "FUTCOM") and expiry:
        symbol = future_symbol(underlying, expiry, exchange=exch)
        kind = InstrumentType.FUT
    else:
        symbol = f"{exch}:{ts}"
        kind = InstrumentType.EQ
    return Instrument(
        symbol=symbol, instrument_key=key, exchange=Exchange(exch), tradingsymbol=symbol.split(":", 1)[1],
        name=row.get("name") or ts, instrument_type=kind, segment=seg,
        underlying=underlying_spot_symbol(underlying) if kind in (InstrumentType.FUT, InstrumentType.CE, InstrumentType.PE) else None,
        expiry=expiry, strike=strike, lot_size=int(row.get("lot_size") or 1),
        tick_size=float(row.get("tick_size") or 5) / (100 if float(row.get("tick_size") or 5) >= 1 else 1),
        freeze_qty=int(row["freeze_quantity"]) if row.get("freeze_quantity") else None, isin=row.get("isin"),
    )


class UpstoxProvider(MarketDataProvider):
    name = "upstox"

    def __init__(self, token: str | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        token = token or (s.upstox_analytics_token.get_secret_value() if s.upstox_analytics_token else None)
        if not token:
            raise NotConfiguredError("UPSTOX_ANALYTICS_TOKEN is not set")
        self._token = token
        self._http = httpx.AsyncClient(
            base_url=s.upstox_base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=transport,
        )
        self._bucket = TokenBucket(s.upstox_rate_limit_per_sec, capacity=s.upstox_rate_limit_per_sec)
        self._instruments: list[Instrument] | None = None
        self._loaded_at: datetime | None = None
        self._by_symbol: dict[str, Instrument] = {}
        self._by_key: dict[str, Instrument] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ http
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async def call() -> Any:
            await self._bucket.acquire()
            r = await self._http.get(path, params=params)
            if r.status_code == 429:
                raise RateLimitedError("Upstox rate limit")
            if r.status_code >= 500:
                raise ProviderError(f"Upstox {r.status_code}")
            body = r.json() if r.content else {}
            if r.status_code >= 400 or body.get("status") == "error":
                errs = body.get("errors") or [{}]
                raise ProviderError(f"Upstox error: {errs[0].get('message', r.text[:200])}",
                                    details={"status": r.status_code, "code": errs[0].get("errorCode")})
            return body.get("data")

        return await retry_async(
            call, attempts=4, retry_on=(RateLimitedError, ProviderError, httpx.TransportError),
            should_retry=lambda e: not (isinstance(e, ProviderError) and (e.details or {}).get("status", 500) < 500),
        )

    # ------------------------------------------------------------------ instruments
    async def instruments(self, exchange: str | None = None) -> list[Instrument]:
        async with self._lock:
            stale = self._loaded_at is None or (now_ist() - self._loaded_at) > timedelta(hours=20)
            if self._instruments is None or stale:
                await self._load_master()
        items = self._instruments or []
        if exchange:
            return [i for i in items if i.exchange.value == exchange.upper()]
        return items

    async def _load_master(self) -> None:
        url = get_settings().upstox_instruments_url
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(url)
            r.raise_for_status()
        rows = json.loads(gzip.decompress(r.content))
        out: list[Instrument] = []
        for row in rows:
            ins = instrument_from_upstox(row)
            if ins is not None:
                out.append(ins)
        self._instruments = out
        self._by_symbol = {i.symbol: i for i in out}
        self._by_key = {i.instrument_key: i for i in out}
        self._loaded_at = now_ist()
        log.info("upstox.instruments_loaded", count=len(out))

    def load_instruments(self, items: list[Instrument]) -> None:
        """Inject an instrument list (tests / DB cache)."""
        self._instruments = items
        self._by_symbol = {i.symbol: i for i in items}
        self._by_key = {i.instrument_key: i for i in items}
        self._loaded_at = now_ist()

    async def _key(self, symbol: str) -> str:
        if not self._by_symbol:
            await self.instruments()
        ins = self._by_symbol.get(symbol)
        if ins is None:
            raise ProviderError(f"Unknown symbol for Upstox: {symbol}", code="unknown_symbol")
        return ins.instrument_key

    def _symbol_for_key(self, key: str) -> str:
        ins = self._by_key.get(key)
        return ins.symbol if ins else key

    async def instrument(self, symbol: str) -> Instrument | None:
        await self.instruments()
        return self._by_symbol.get(symbol)

    # ------------------------------------------------------------------ candles
    @staticmethod
    def _parse_candles(rows: list[list[Any]]) -> list[Candle]:
        out = []
        for r in rows:
            out.append(Candle(
                ts=datetime.fromisoformat(r[0]).astimezone(UTC), open=float(r[1]), high=float(r[2]),
                low=float(r[3]), close=float(r[4]), volume=float(r[5] or 0),
                oi=float(r[6]) if len(r) > 6 and r[6] else None,
            ))
        out.sort(key=lambda c: c.ts)
        return out

    async def candles(self, symbol: str, interval: Interval, start: datetime, end: datetime) -> list[Candle]:
        key = urlquote(await self._key(symbol), safe="")
        unit, n = _INTERVALS[interval]
        candles: dict[datetime, Candle] = {}
        today = now_ist().date()
        if unit in ("minutes", "hours") and end.astimezone(IST).date() >= today:
            data = await self._get(f"/v3/historical-candle/intraday/{key}/{unit}/{n}")
            for c in self._parse_candles((data or {}).get("candles", [])):
                candles[c.ts] = c
        chunk = timedelta(days=_CHUNK_DAYS[unit])
        cur_end = min(end.astimezone(IST).date(), today)
        start_d = start.astimezone(IST).date()
        while cur_end >= start_d:
            cur_start = max(start_d, cur_end - chunk)
            data = await self._get(f"/v3/historical-candle/{key}/{unit}/{n}/{cur_end}/{cur_start}")
            for c in self._parse_candles((data or {}).get("candles", [])):
                candles.setdefault(c.ts, c)
            cur_end = cur_start - timedelta(days=1)
        return [c for ts, c in sorted(candles.items()) if start <= ts <= end]

    # ------------------------------------------------------------------ quotes
    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        keys: dict[str, str] = {}
        for s in symbols:
            with contextlib.suppress(ProviderError):
                keys[await self._key(s)] = s
        out: dict[str, Quote] = {}
        items = list(keys)
        for i in range(0, len(items), 450):  # API limit 500 keys per call
            chunk = items[i : i + 450]
            data = await self._get("/v3/market-quote/quotes", {"instrument_key": ",".join(chunk)}) or {}
            for row in data.values():
                sym = keys.get(row.get("instrument_token", ""))
                if sym:
                    out[sym] = self._quote_from(sym, row)
        return out

    @staticmethod
    def _quote_from(symbol: str, q: dict[str, Any]) -> Quote:
        ohlc = q.get("ohlc") or {}
        depth = q.get("depth") or {}
        bids = [DepthLevel(price=d.get("price", 0), quantity=d.get("quantity", 0), orders=d.get("orders", 0))
                for d in depth.get("buy", []) if d.get("price")]
        asks = [DepthLevel(price=d.get("price", 0), quantity=d.get("quantity", 0), orders=d.get("orders", 0))
                for d in depth.get("sell", []) if d.get("price")]
        ltp = float(q.get("last_price") or 0)
        # Previous close: explicit field when present, else last price - net_change (Upstox documents net_change as
        # the change from yesterday's close); the quote's ohlc.close is today's running close, not yesterday's.
        if q.get("prev_close_price"):
            prev: float | None = float(q["prev_close_price"])
        elif q.get("net_change") is not None and ltp:
            prev = ltp - float(q["net_change"])
        elif q.get("cp"):
            prev = float(q["cp"])
        else:
            prev = float(ohlc.get("close") or 0) or None
        chg = (ltp - prev) if prev else None
        ts = q.get("timestamp") or q.get("last_trade_time")
        try:
            tsv = datetime.fromtimestamp(int(ts) / 1000, tz=UTC) if ts and str(ts).isdigit() else datetime.now(tz=UTC)
        except (TypeError, ValueError):
            tsv = datetime.now(tz=UTC)
        return Quote(
            symbol=symbol, ts=tsv, ltp=ltp, open=ohlc.get("open"), high=ohlc.get("high"), low=ohlc.get("low"),
            close=prev, change=chg, change_pct=(chg / prev * 100) if prev and chg is not None else None,
            volume=q.get("volume"), oi=q.get("oi"), avg_price=q.get("average_price"),
            upper_circuit=q.get("upper_circuit_limit"), lower_circuit=q.get("lower_circuit_limit"),
            total_buy_qty=q.get("total_buy_quantity"), total_sell_qty=q.get("total_sell_quantity"),
            bids=bids, asks=asks, bid=bids[0].price if bids else None, ask=asks[0].price if asks else None,
        )

    # ------------------------------------------------------------------ options
    def _underlying_key(self, underlying: str) -> str:
        spot = underlying_spot_symbol(underlying)
        for k, v in INDEX_ALIASES.items():
            if v == spot:
                return k
        ins = self._by_symbol.get(spot)
        if ins is None:
            raise ProviderError(f"Unknown underlying {underlying}")
        return ins.instrument_key

    async def expiries(self, underlying: str) -> list[date]:
        await self.instruments()
        data = await self._get("/v2/option/contract", {"instrument_key": self._underlying_key(underlying)}) or []
        exps = sorted({date.fromisoformat(r["expiry"]) for r in data if r.get("expiry")})
        return [e for e in exps if e >= now_ist().date()]

    async def option_chain(self, underlying: str, expiry: date | None = None, strikes: int = 20) -> OptionChain:
        await self.instruments()
        expiries = await self.expiries(underlying)
        if not expiries:
            raise ProviderError(f"No expiries for {underlying}")
        exp = expiry or expiries[0]
        data = await self._get("/v2/option/chain", {"instrument_key": self._underlying_key(underlying),
                                                     "expiry_date": exp.isoformat()}) or []
        spot = float(data[0].get("underlying_spot_price", 0)) if data else 0.0
        step = strike_step(underlying, spot)
        atm = atm_strike(spot, step)
        rows: list[OptionChainRow] = []
        tot_c = tot_p = 0.0

        def leg(d: dict[str, Any] | None) -> OptionLeg | None:
            if not d:
                return None
            md, g = d.get("market_data") or {}, d.get("option_greeks") or {}
            oi = float(md.get("oi") or 0)
            return OptionLeg(
                symbol=self._symbol_for_key(d.get("instrument_key", "")), ltp=float(md.get("ltp") or 0),
                bid=md.get("bid_price"), ask=md.get("ask_price"), volume=float(md.get("volume") or 0), oi=oi,
                oi_change=oi - float(md.get("prev_oi") or oi), iv=g.get("iv"),
                greeks=Greeks(delta=g.get("delta") or 0, gamma=g.get("gamma") or 0, theta=g.get("theta") or 0,
                              vega=g.get("vega") or 0, iv=g.get("iv")),
            )

        for r in sorted(data, key=lambda x: x["strike_price"]):
            k = float(r["strike_price"])
            if abs(k - atm) > strikes * step:
                continue
            c, p = leg(r.get("call_options")), leg(r.get("put_options"))
            tot_c += c.oi if c else 0
            tot_p += p.oi if p else 0
            rows.append(OptionChainRow(strike=k, expiry=exp, call=c, put=p, pcr=r.get("pcr")))
        lot = next((i.lot_size for i in self._instruments or [] if i.underlying == underlying_spot_symbol(underlying)), 1)
        return OptionChain(
            underlying=underlying.upper(), spot=spot, expiry=exp, expiries=expiries, lot_size=lot, atm_strike=atm,
            rows=rows, pcr=round(tot_p / tot_c, 3) if tot_c else None, max_pain=max_pain(rows),
            total_call_oi=tot_c, total_put_oi=tot_p, ts=datetime.now(tz=UTC),
        )

    # ------------------------------------------------------------------ calendar
    async def market_status(self) -> list[MarketStatus]:
        out = []
        for ex in ("NSE", "BSE", "NFO", "MCX"):
            data = await self._get(f"/v2/market/status/{ex}") or {}
            status = str(data.get("status", "unknown"))
            out.append(MarketStatus(exchange=ex, status=status.lower(), is_open="OPEN" in status.upper() and "PRE" not in status.upper(),
                                    ts=datetime.now(tz=UTC)))
        return out

    async def holidays(self, year: int | None = None) -> list[dict[str, str]]:
        data = await self._get("/v2/market/holidays") or []
        return [{"date": h["date"], "description": h.get("description", ""), "exchange": ",".join(h.get("closed_exchanges", []))}
                for h in data if not year or h["date"].startswith(str(year))]

    # ------------------------------------------------------------------ streaming
    async def stream(self, demand: DemandFn) -> AsyncIterator[list[Tick]]:  # type: ignore[override]
        from market_data.upstox_feed import FeedNotAuthorized, UpstoxFeed

        await self.instruments()
        feed = UpstoxFeed(self._http, self._by_symbol, self._by_key)
        try:
            async for batch in feed.run(demand):
                TICKS_PUBLISHED.labels("upstox").inc(len(batch))
                yield batch
        except FeedNotAuthorized as exc:
            # Some tokens (e.g. read-only ones without the feed scope) can call the REST market-data APIs but not
            # open the WebSocket feed: keep prices moving by polling quotes instead of going silent.
            from market_data.registry import note_provider_error

            log.warning("upstox.feed_not_authorized_polling", error=str(exc))
            note_provider_error("This Upstox token cannot open the live WebSocket feed; prices update by polling every "
                                f"{POLL_SECONDS:g} s instead ({exc}).")
            async for batch in self.poll(demand):
                yield batch

    async def poll(self, demand: DemandFn, every: float | None = None) -> AsyncIterator[list[Tick]]:
        """REST fallback for the live feed: quotes for the demanded symbols every couple of seconds."""
        every = every or POLL_SECONDS
        while True:
            symbols = sorted(demand())[:450]
            batch: list[Tick] = []
            if symbols:
                try:
                    quotes = await self.quotes(symbols)
                except Exception as exc:
                    log.warning("upstox.poll_failed", error=str(exc))
                    quotes = {}
                for sym, q in quotes.items():
                    batch.append(Tick(symbol=sym, ts=q.ts, ltp=q.ltp, volume=q.volume, oi=q.oi, open=q.open, high=q.high,
                                      low=q.low, close=q.close, change=q.change, change_pct=q.change_pct, bid=q.bid, ask=q.ask))
            if batch:
                TICKS_PUBLISHED.labels("upstox").inc(len(batch))
                yield batch
            await asyncio.sleep(every)

    async def close(self) -> None:
        await self._http.aclose()


def subscription_message(keys: list[str], method: str = "sub", mode: str = "full") -> bytes:
    msg: dict[str, Any] = {"guid": uuid.uuid4().hex[:20], "method": method, "data": {"instrumentKeys": keys}}
    if method == "sub":
        msg["data"]["mode"] = mode
    return json.dumps(msg).encode()
