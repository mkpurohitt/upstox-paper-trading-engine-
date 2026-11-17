"""Market data tools: quotes, candles/technicals, option chain, Greeks/payoff, fundamentals, news."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from ai_agent import nlu
from ai_agent.tools.registry import ToolContext, ToolResult, tool
from algo_db.models import NewsItem
from algo_db.session import session_scope
from market_data import news as news_mod
from market_data.registry import get_provider
from strategy_engine.analytics import fundamentals, technical
from strategy_engine.analytics import options as opt


def resolve(sym: str) -> str:
    s = sym.strip()
    if ":" in s:
        return s.upper()
    found = nlu.find_symbols(s)
    return found[0] if found else f"NSE:{s.upper().replace(' ', '')}"


def _round(v: Any, d: int = 2) -> Any:
    return round(v, d) if isinstance(v, float) else v


class QuoteArgs(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=10, description="Symbols like NSE:RELIANCE, NSE_INDEX:NIFTY or plain tickers")


@tool("get_quote", "Live quote (LTP, change, OHLC, volume, 52-week range) for up to 10 instruments.", QuoteArgs)
async def get_quote(ctx: ToolContext, a: QuoteArgs) -> ToolResult:
    syms = [resolve(s) for s in a.symbols]
    quotes = await get_provider().quotes(syms)
    rows = []
    for s in syms:
        q = quotes.get(s)
        if q is None:
            rows.append({"symbol": s, "error": "not found"})
            continue
        rows.append({"symbol": s, "name": q.name, "ltp": q.ltp, "change": _round(q.change), "change_pct": _round(q.change_pct),
                     "open": q.open, "high": q.high, "low": q.low, "prev_close": q.close, "volume": q.volume,
                     "week52_high": q.week52_high, "week52_low": q.week52_low, "ts": q.ts.isoformat()})
    ok = [r for r in rows if "error" not in r]
    return ToolResult({"quotes": rows}, {"type": "quotes", "quotes": ok}, ok=bool(ok))


class CandleArgs(BaseModel):
    symbol: str
    interval: Literal["5m", "15m", "30m", "1h", "1d", "1w"] = "1d"
    bars: int = Field(default=120, ge=20, le=500)


@tool("get_candles", "OHLCV candles plus a technical summary (trend score, EMA20/50, RSI, ADX, Supertrend), support/resistance "
      "levels and recent candlestick patterns.", CandleArgs)
async def get_candles(ctx: ToolContext, a: CandleArgs) -> ToolResult:
    sym = resolve(a.symbol)
    d = await technical.technical_dashboard(get_provider(), sym, a.interval, ["EMA:20", "EMA:50", "RSI"])
    candles = d["candles"][-a.bars:]
    first, last = candles[0]["close"], candles[-1]["close"]
    data = {"symbol": sym, "interval": a.interval, "summary": d["summary"], "mtf": d["mtf"], "levels": d["levels"],
            "patterns": d["patterns"][-5:], "period_change_pct": round((last / first - 1) * 100, 2),
            "last_bars": [{k: c[k] for k in ("ts", "open", "high", "low", "close", "volume")} for c in candles[-5:]]}
    ema = {o["id"]: [p for p in o["series"][-a.bars:]] for o in d["overlays"] if o["id"] in ("EMA(20)", "EMA(50)")}
    card = {"type": "chart", "symbol": sym, "interval": a.interval, "candles": candles, "overlays": ema,
            "summary": d["summary"], "levels": d["levels"][:6]}
    return ToolResult(data, card)


class ChainArgs(BaseModel):
    underlying: str = Field(description="Index or F&O stock: NIFTY, BANKNIFTY, FINNIFTY, SENSEX, RELIANCE, …")
    expiry: date | None = Field(default=None, description="YYYY-MM-DD; nearest expiry if omitted")


@tool("get_option_chain", "Option chain summary: spot, PCR, max pain, ATM IV and straddle, expected range, OI support/resistance, "
      "OI buildup and strikes around ATM.", ChainArgs)
async def get_option_chain(ctx: ToolContext, a: ChainArgs) -> ToolResult:
    p = get_provider()
    und = nlu.underlying_of(resolve(a.underlying)) if ":" in a.underlying or len(a.underlying) > 12 else a.underlying.upper()
    chain = await p.option_chain(und, a.expiry, 20)
    quotes = await p.quotes([leg.symbol for r in chain.rows for leg in (r.call, r.put) if leg])
    an = opt.chain_analytics(chain, {s: q.change or 0.0 for s, q in quotes.items()})
    near = sorted(chain.rows, key=lambda r: abs(r.strike - chain.atm_strike))[:11]
    near.sort(key=lambda r: r.strike)
    rows = [{"strike": r.strike, "call_ltp": r.call.ltp if r.call else None, "call_oi": r.call.oi if r.call else None,
             "call_oi_change": r.call.oi_change if r.call else None, "call_iv": r.call.iv if r.call else None,
             "put_ltp": r.put.ltp if r.put else None, "put_oi": r.put.oi if r.put else None,
             "put_oi_change": r.put.oi_change if r.put else None, "put_iv": r.put.iv if r.put else None} for r in near]
    summary = {k: an[k] for k in ("atm_iv", "atm_straddle", "expected_move", "expected_range", "days_to_expiry", "resistance",
                                  "support", "oi_change_pcr")}
    data = {"underlying": chain.underlying, "expiry": chain.expiry.isoformat(), "spot": chain.spot, "lot_size": chain.lot_size,
            "atm_strike": chain.atm_strike, "pcr": chain.pcr, "max_pain": chain.max_pain, "analytics": summary, "strikes": rows}
    return ToolResult(data, {"type": "option_chain", **data})


class LegArg(BaseModel):
    action: Literal["BUY", "SELL"]
    option_type: Literal["CE", "PE", "FUT"]
    strike: float | None = None
    offset: int | None = Field(default=None, description="strikes from ATM when strike is omitted")
    lots: int = Field(default=1, ge=1, le=50)


class GreeksArgs(BaseModel):
    underlying: str = "NIFTY"
    structure: Literal["long_straddle", "short_straddle", "short_strangle", "long_strangle", "long_call_butterfly", "iron_fly",
                       "iron_condor", "bull_call_spread", "bear_put_spread"] | None = None
    legs: list[LegArg] = Field(default_factory=list, max_length=8)
    expiry: date | None = None
    width: int | None = Field(default=None, ge=1, le=20, description="short strikes from ATM (condor/strangle)")
    wing: int | None = Field(default=None, ge=1, le=20, description="wing width in strikes")


@tool("get_greeks", "Price a multi-leg options position off the live chain: payoff, breakevens, max profit/loss, probability of "
      "profit and net Greeks. Give a named structure or explicit legs.", GreeksArgs)
async def get_greeks(ctx: ToolContext, a: GreeksArgs) -> ToolResult:
    und = a.underlying.upper().split(":")[-1]
    specs = [leg.model_dump() for leg in a.legs] if a.legs else opt.structure_specs(a.structure or "short_straddle", a.width, a.wing)
    chain, legs = await opt.legs_from_chain(get_provider(), und, a.expiry, specs)
    res = opt.payoff(chain.spot, legs, chain.lot_size, expiry=chain.expiry)
    pts = res["points"][::3]
    data = {"underlying": und, "structure": a.structure or "custom", "expiry": chain.expiry.isoformat(), "spot": chain.spot,
            "lot_size": chain.lot_size, "legs": [{k: leg.get(k) for k in ("action", "option_type", "strike", "premium", "iv", "lots", "symbol")}
                                                 for leg in legs],
            **{k: res[k] for k in ("net_premium", "max_profit", "max_loss", "breakevens", "pop", "greeks", "days_to_expiry")}}
    return ToolResult(data, {"type": "payoff", **data, "points": pts})


class FundArgs(BaseModel):
    symbol: str


@tool("get_fundamentals", "Company fundamentals: valuation and quality ratios, annual financials, peers, shareholding and "
      "corporate actions.", FundArgs)
async def get_fundamentals(ctx: ToolContext, a: FundArgs) -> ToolResult:
    sym = resolve(a.symbol)
    q = (await get_provider().quotes([sym])).get(sym)
    d = await fundamentals.fundamental_dashboard(sym, q.ltp if q else None)
    data = {k: d[k] for k in ("symbol", "name", "sector", "industry", "price", "ratios", "shareholding", "source")}
    data["annual"] = d["annual"][-3:]
    data["peers"] = [{k: p.get(k) for k in ("symbol", "name", "pe", "roe_pct", "market_cap_cr")} for p in d["peers"][:6]]
    return ToolResult(data, {"type": "fundamentals", **data, "annual": d["annual"]})


class NewsArgs(BaseModel):
    symbol: str | None = Field(default=None, description="filter by company; omit for market news")
    limit: int = Field(default=8, ge=1, le=20)


@tool("get_news", "Latest market or company news with sentiment and tagged tickers.", NewsArgs)
async def get_news(ctx: ToolContext, a: NewsArgs) -> ToolResult:
    sym = resolve(a.symbol) if a.symbol else None
    items: list[dict[str, Any]] = []
    async with session_scope() as db:
        q = select(NewsItem).order_by(desc(NewsItem.published_at)).limit(200)
        since = date.today() - timedelta(days=7)
        for n in (await db.execute(q)).scalars():
            if n.published_at.date() < since:
                continue
            if sym and sym not in (n.tickers or []):
                continue
            items.append({"title": n.title, "source": n.source, "url": n.url, "published_at": n.published_at.isoformat(),
                          "sentiment": n.sentiment, "summary": (n.ai_summary or n.summary or "")[:300], "tickers": n.tickers})
            if len(items) >= a.limit:
                break
    source = "db"
    if not items:
        items = [x.as_dict() for x in news_mod.mock_articles(sym, a.limit)]
        source = "sample"
    from ai_agent.guardrails import neutralise

    for it in items:  # headlines are third-party text: defang embedded instructions
        it["title"], it["summary"] = neutralise(it["title"]), neutralise(it.get("summary", ""))
    return ToolResult({"symbol": sym, "items": items, "source": source}, {"type": "news", "items": items, "source": source})
