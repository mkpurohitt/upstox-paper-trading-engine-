"""Analysis dashboards API (options, scanners, technical, fundamentals, quant, pairs, screener)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from algo_common.kv import get_kv
from algo_db.models import Screen
from app.core.deps import DB, CurrentUser
from app.schemas.common import Message
from market_data.registry import get_provider
from strategy_engine.analytics import fundamentals, pairs, quant, screener, technical
from strategy_engine.analytics import options as opt

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


async def _cached(key: str, ttl: float, fn):  # type: ignore[no-untyped-def]
    return await get_kv().cached(f"an:{get_provider().name}:{key}", ttl, fn)


@router.get("/option-chain")
async def option_chain(_: CurrentUser, underlying: str = "NIFTY", expiry: date | None = None, strikes: int = Query(20, le=40)) -> dict[str, Any]:
    p = get_provider()
    try:
        chain = await p.option_chain(underlying, expiry, strikes)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    legs = [leg.symbol for r in chain.rows for leg in (r.call, r.put) if leg]
    quotes = await p.quotes(legs)
    changes = {s: q.change or 0.0 for s, q in quotes.items()}
    return {"chain": chain.model_dump(mode="json"), "analytics": opt.chain_analytics(chain, changes)}


@router.get("/arbitrage")
async def arbitrage(_: CurrentUser, cost_bps: float = Query(6.0, ge=0, le=100)) -> dict[str, Any]:
    return await _cached(f"arb:{cost_bps}", 5, lambda: opt.arbitrage_scan(get_provider(), cost_bps))


class RatioIn(BaseModel):
    underlying: str = "NIFTY"
    expiry: date | None = None
    kind: Literal["CE", "PE"] = "CE"
    ratios: list[int] = Field(default_factory=lambda: [2, 3])
    min_credit: float | None = None
    max_debit: float | None = 0.0
    delta_min: float = 0.05
    delta_max: float = 0.6
    limit: int = 25


@router.post("/ratio-spreads")
async def ratio_spreads(body: RatioIn, _: CurrentUser) -> dict[str, Any]:
    return await opt.ratio_spreads(get_provider(), body.underlying, body.expiry, kind=body.kind, ratios=tuple(body.ratios),
                                   min_credit=body.min_credit, max_debit=body.max_debit, delta_min=body.delta_min,
                                   delta_max=body.delta_max, limit=body.limit)


@router.get("/straddle")
async def straddle(_: CurrentUser, underlying: str = "NIFTY", expiry: date | None = None, otm_steps: int = Query(0, ge=0, le=20)) -> dict[str, Any]:
    return await opt.straddle_dashboard(get_provider(), underlying, expiry, otm_steps)


class LegIn(BaseModel):
    action: Literal["BUY", "SELL"]
    option_type: Literal["CE", "PE", "FUT"]
    strike: float | None = None
    offset: int | None = None
    lots: int = Field(default=1, ge=1, le=100)
    premium: float | None = None
    iv: float | None = None


class PayoffIn(BaseModel):
    underlying: str = "NIFTY"
    expiry: date | None = None
    legs: list[LegIn] = Field(default_factory=list, max_length=12)
    structure: str | None = Field(default=None, description=f"one of {sorted(opt.STRUCTURES)} (fills `legs`)")
    width: int | None = None
    wing: int | None = None
    days_forward: float = Field(default=0, ge=0)
    spot_shift_pct: float = Field(default=0, ge=-30, le=30)
    iv_shift: float = Field(default=0, ge=-50, le=100)


@router.post("/payoff")
async def payoff(body: PayoffIn, _: CurrentUser) -> dict[str, Any]:
    specs = [leg.model_dump() for leg in body.legs]
    if body.structure:
        if body.structure not in opt.STRUCTURES:
            raise HTTPException(422, f"unknown structure {body.structure}")
        specs = opt.structure_specs(body.structure, body.width, body.wing)
    if not specs:
        raise HTTPException(422, "provide legs or a structure")
    chain, legs = await opt.legs_from_chain(get_provider(), body.underlying, body.expiry, specs)
    res = opt.payoff(chain.spot, legs, chain.lot_size, expiry=chain.expiry, days_forward=body.days_forward, underlying=body.underlying,
                     spot_shift_pct=body.spot_shift_pct, iv_shift=body.iv_shift)
    return {**res, "underlying": body.underlying.upper(), "expiry": chain.expiry.isoformat(), "expiries": [e.isoformat() for e in chain.expiries],
            "legs": legs, "structures": sorted(opt.STRUCTURES)}


@router.get("/technical")
async def technical_dash(_: CurrentUser, symbol: str = "NSE:RELIANCE", interval: str = "1d",
                         indicators: str = "EMA:20,EMA:50,BBANDS,RSI,MACD") -> dict[str, Any]:
    if interval not in technical.LOOKBACK_DAYS:
        raise HTTPException(422, "unsupported interval")
    try:
        return await technical.technical_dashboard(get_provider(), symbol, interval, [s for s in indicators.split(",") if s])
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc))


@router.get("/fundamentals")
async def fundamentals_dash(_: CurrentUser, symbol: str = "NSE:RELIANCE") -> dict[str, Any]:
    q = (await get_provider().quotes([symbol])).get(symbol)
    try:
        return await fundamentals.fundamental_dashboard(symbol, q.ltp if q else None)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@router.get("/quant")
async def quant_dash(_: CurrentUser, symbol: str = "NSE:HDFCBANK", basket: str = "NSE:ICICIBANK,NSE:SBIN,NSE:KOTAKBANK,NSE:AXISBANK",
                     benchmark: str = "NSE_INDEX:NIFTY", days: int = Query(1095, ge=200, le=2500)) -> dict[str, Any]:
    b = [s for s in basket.split(",") if s][:12]
    return await _cached(f"quant:{symbol}:{','.join(b)}:{benchmark}:{days}", 60,
                         lambda: quant.quant_dashboard(get_provider(), symbol, b, benchmark, days))


@router.get("/pairs")
async def pairs_dash(_: CurrentUser, a: str = "NSE:HDFCBANK", b: str = "NSE:ICICIBANK", days: int = Query(730, ge=120, le=2500),
                     lookback: int = Query(60, ge=10, le=500)) -> dict[str, Any]:
    return await pairs.pair_dashboard(get_provider(), a, b, days, lookback)


@router.get("/pairs/scan")
async def pairs_scan(_: CurrentUser, sector: str | None = None) -> list[dict[str, Any]]:
    return await _cached(f"pscan:{sector}", 300, lambda: pairs.scan_pairs(get_provider(), sector))


@router.get("/screener/fields")
async def screener_fields(_: CurrentUser) -> dict[str, dict[str, str]]:
    return screener.FIELDS


@router.post("/screener/run")
async def screener_run(body: screener.ScreenQuery, _: CurrentUser) -> dict[str, Any]:
    bad = [c.field for c in body.conditions if c.field not in screener.FIELDS]
    if bad:
        raise HTTPException(422, f"unknown fields {bad}")
    return await _cached(f"screen:{body.model_dump_json()}", 30, lambda: screener.run_screen(get_provider(), body))


class ScreenIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: screener.ScreenQuery
    alert_enabled: bool = False
    schedule_minutes: int = Field(default=60, ge=5, le=1440)


class ScreenOut(BaseModel):
    id: int
    name: str
    query: dict[str, Any]
    alert_enabled: bool
    schedule_minutes: int
    last_run_at: str | None = None
    last_results: list[Any] = []


def _screen_out(s: Screen) -> ScreenOut:
    return ScreenOut(id=s.id, name=s.name, query=s.criteria, alert_enabled=s.alert_enabled, schedule_minutes=s.schedule_minutes,
                     last_run_at=s.last_run_at.isoformat() if s.last_run_at else None, last_results=s.last_results)


@router.get("/screens", response_model=list[ScreenOut])
async def list_screens(user: CurrentUser, db: DB) -> list[ScreenOut]:
    rows = (await db.execute(select(Screen).where(Screen.user_id == user.id).order_by(Screen.id.desc()))).scalars()
    return [_screen_out(s) for s in rows]


@router.post("/screens", response_model=ScreenOut, status_code=201)
async def save_screen(body: ScreenIn, user: CurrentUser, db: DB) -> ScreenOut:
    from app.services.quotas import plan_limits

    count = len((await db.execute(select(Screen.id).where(Screen.user_id == user.id))).all())
    if count >= int((await plan_limits(db, user.id)).get("screens", 3)):
        raise HTTPException(402, "Saved-screen limit reached for your plan")
    s = Screen(user_id=user.id, name=body.name, universe=body.query.universe, criteria=body.query.model_dump(),
               alert_enabled=body.alert_enabled, schedule_minutes=body.schedule_minutes)
    db.add(s)
    await db.flush()
    return _screen_out(s)


@router.put("/screens/{screen_id}", response_model=ScreenOut)
async def update_screen(screen_id: int, body: ScreenIn, user: CurrentUser, db: DB) -> ScreenOut:
    s = await db.get(Screen, screen_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Screen not found")
    s.name, s.criteria, s.universe = body.name, body.query.model_dump(), body.query.universe
    s.alert_enabled, s.schedule_minutes = body.alert_enabled, body.schedule_minutes
    return _screen_out(s)


@router.delete("/screens/{screen_id}", response_model=Message)
async def delete_screen(screen_id: int, user: CurrentUser, db: DB) -> Message:
    s = await db.get(Screen, screen_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Screen not found")
    await db.delete(s)
    return Message(message="Deleted")
