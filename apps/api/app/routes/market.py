"""Market data REST endpoints (normalised across providers)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from algo_common.errors import ProviderError
from algo_common.schemas.market import Candle, Instrument, Interval, MarketStatus, OptionChain, Quote
from algo_common.timeutils import utcnow
from app.core.deps import CurrentUser
from app.schemas.market import McpToolOut, OverviewOut, ProviderInfo
from market_data.nse_mcp import call_nse_tool, get_nse_tools
from market_data.overview import market_overview
from market_data.registry import get_provider, provider_info
from market_data.universe import UNIVERSES

router = APIRouter(prefix="/api/market", tags=["market"])

MAX_SYMBOLS = 500


def _split(symbols: str) -> list[str]:
    out = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(out) > MAX_SYMBOLS:
        raise HTTPException(422, f"At most {MAX_SYMBOLS} symbols per request")
    return out


@router.get("/provider", response_model=ProviderInfo)
async def provider(_: CurrentUser) -> dict[str, Any]:
    return provider_info()


@router.get("/search", response_model=list[Instrument])
async def search(_: CurrentUser, q: str = Query(min_length=1, max_length=40), limit: int = Query(20, le=50)) -> list[Instrument]:
    return await get_provider().search(q, limit)


@router.get("/instruments/{symbol:path}", response_model=Instrument)
async def instrument(symbol: str, _: CurrentUser) -> Instrument:
    ins = await get_provider().instrument(symbol)
    if ins is None:
        raise HTTPException(404, f"Unknown instrument {symbol}")
    return ins


@router.get("/universes", response_model=dict[str, list[str]])
async def universes(_: CurrentUser) -> dict[str, list[str]]:
    return UNIVERSES


@router.get("/quotes", response_model=list[Quote])
async def quotes(_: CurrentUser, symbols: str = Query(..., description="Comma separated canonical symbols")) -> list[Quote]:
    syms = _split(symbols)
    data = await get_provider().quotes(syms)
    return [data[s] for s in syms if s in data]


@router.get("/quote/{symbol:path}", response_model=Quote)
async def quote(symbol: str, _: CurrentUser) -> Quote:
    data = await get_provider().quotes([symbol])
    if symbol not in data:
        raise HTTPException(404, f"No quote for {symbol}")
    return data[symbol]


@router.get("/candles", response_model=list[Candle])
async def candles(
    _: CurrentUser,
    symbol: str,
    interval: Interval = Interval.D1,
    days: int = Query(365, ge=1, le=3650),
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Candle]:
    end = end or utcnow()
    start = start or end - timedelta(days=days)
    if interval not in (Interval.D1, Interval.W1) and (end - start).days > 120:
        start = end - timedelta(days=120)
    try:
        return await get_provider().candles(symbol, interval, start, end)
    except KeyError:
        raise HTTPException(404, f"Unknown symbol {symbol}")


@router.get("/expiries", response_model=list[date])
async def expiries(_: CurrentUser, underlying: str) -> list[date]:
    return await get_provider().expiries(underlying)


@router.get("/option-chain", response_model=OptionChain)
async def option_chain(
    _: CurrentUser, underlying: str, expiry: date | None = None, strikes: int = Query(20, ge=3, le=60)
) -> OptionChain:
    try:
        return await get_provider().option_chain(underlying, expiry, strikes)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ProviderError as exc:
        raise HTTPException(502, exc.message)


@router.get("/status", response_model=list[MarketStatus])
async def status(_: CurrentUser) -> list[MarketStatus]:
    return await get_provider().market_status()


@router.get("/holidays", response_model=list[dict[str, str]])
async def holidays(_: CurrentUser, year: int | None = None) -> list[dict[str, str]]:
    return await get_provider().holidays(year)


@router.get("/overview", response_model=OverviewOut)
async def overview(_: CurrentUser) -> dict[str, Any]:
    return await market_overview(get_provider())


@router.get("/nse/tools", response_model=list[McpToolOut])
async def nse_tools(_: CurrentUser) -> list[dict[str, Any]]:
    return [dict(t) for t in await get_nse_tools().list_tools()]


@router.post("/nse/tools/{name}")
async def nse_tool_call(name: str, _: CurrentUser, arguments: dict[str, Any] | None = None) -> Any:
    tools = {t["name"] for t in await get_nse_tools().list_tools()}
    if name not in tools:
        raise HTTPException(404, f"Unknown NSE tool {name}")
    return await call_nse_tool(name, arguments or {})
