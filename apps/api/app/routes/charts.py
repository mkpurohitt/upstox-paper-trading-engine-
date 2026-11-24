"""Charts terminal API: bars for any timeframe (with history paging), the data source, and saved chart layouts.

Bars come from the active market-data provider: live Upstox data when an access token is configured (Admin ->
Market data, or the environment), otherwise the built-in simulated market. Responses say which, so the UI never
presents simulated prices as live ones.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from algo_common.errors import ProviderError
from algo_common.timeutils import IST, utcnow
from algo_db.models import ChartLayout
from app.core.deps import DB, CurrentUser
from market_data.bars import exchange_of, lookback, parse_timeframe, resample
from market_data.registry import get_provider, note_provider_error, provider_info

router = APIRouter(prefix="/api/charts", tags=["charts"])

MAX_LAYOUTS = 50
MAX_STATE_BYTES = 512_000
EARLIEST = {"mock": datetime(2019, 1, 1, tzinfo=UTC), "upstox": datetime(2000, 1, 1, tzinfo=UTC)}
EARLIEST_INTRADAY = {"mock": datetime(2019, 1, 1, tzinfo=UTC), "upstox": datetime(2022, 1, 1, tzinfo=UTC)}


def _source() -> dict[str, Any]:
    info = provider_info()
    live = bool(info["live"])
    return {
        "provider": info["name"], "live": live, "source": info.get("source"),
        "label": "Live · Upstox" if live else "Simulated market data",
        "detail": None if live else "Connect an Upstox access token in Admin → Market data for live prices.",
        "last_error": info.get("last_error"),
    }


def _provider_error(exc: ProviderError) -> HTTPException:
    status = (exc.details or {}).get("status")
    msg = str(exc)
    if status in (401, 403):
        msg = ("Upstox rejected the access token (it may have expired — daily tokens expire at 3:30 AM). "
               "Paste a new token in Admin → Market data.")
    note_provider_error(msg)
    return HTTPException(502, msg)


@router.get("/source")
async def source(_: CurrentUser) -> dict[str, Any]:
    return _source()


@router.get("/bars")
async def bars(
    _: CurrentUser,
    symbol: str,
    tf: str = Query("D", description="Minutes (1, 3, 5, 15, 45, 60, 120, 240 …) or D, W, M"),
    count: int = Query(500, ge=10, le=5000),
    to: datetime | None = Query(None, description="Return bars strictly before this instant (history paging)"),
) -> dict[str, Any]:
    try:
        frame = parse_timeframe(tf)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    provider = get_provider()
    exchange = exchange_of(symbol)
    end = (to or utcnow() + timedelta(minutes=1)).astimezone(UTC)
    name = provider.name if provider.name in EARLIEST else "upstox"
    floor = (EARLIEST_INTRADAY if frame.intraday else EARLIEST)[name]
    span = lookback(frame, count, exchange)
    out: list[Any] = []
    try:
        for _attempt in range(3):  # widen the window over long holidays / thin history
            start = max(floor, end - span)
            base = await provider.candles(symbol, frame.base, start, end)
            base = [c for c in base if c.ts < end] if to else base
            out = resample(base, frame, exchange)
            if len(out) >= count or start <= floor:
                break
            span *= 2
    except ProviderError as exc:
        if exc.code == "unknown_symbol":
            raise HTTPException(404, f"Unknown symbol {symbol}") from exc
        raise _provider_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(404, f"Unknown symbol {symbol}") from exc
    has_more = len(out) > count or (bool(out) and out[0].ts > floor + timedelta(days=3))
    out = out[-count:]
    rows = []
    for c in out:
        row: dict[str, Any] = {"t": int(c.ts.timestamp()), "o": c.open, "h": c.high, "l": c.low, "c": c.close,
                               "v": c.volume or 0}
        if c.oi:
            row["oi"] = c.oi
        if not frame.intraday:
            row["d"] = c.ts.astimezone(IST).date().isoformat()
        rows.append(row)
    return {
        "symbol": symbol, "tf": frame.code, "label": frame.label, "intraday": frame.intraday, "exchange": exchange,
        "timezone": "Asia/Kolkata", "bars": rows, "has_more": has_more and bool(rows),
        "next_to": datetime.fromtimestamp(rows[0]["t"], tz=UTC).isoformat() if rows else None,
        **{"source": _source()},
    }


# ------------------------------------------------------------------ layouts
class LayoutIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    state: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class LayoutPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    state: dict[str, Any] | None = None
    is_default: bool | None = None


def _layout_out(row: ChartLayout, with_state: bool = True) -> dict[str, Any]:
    out = {"id": row.id, "name": row.name, "is_default": row.is_default,
           "updated_at": row.updated_at.isoformat() if row.updated_at else None}
    if with_state:
        out["state"] = row.state or {}
    return out


def _check_size(state: dict[str, Any]) -> None:
    if len(json.dumps(state, default=str)) > MAX_STATE_BYTES:
        raise HTTPException(413, "Chart layout is too large (remove some drawings)")


async def _owned(db: DB, user_id: int, layout_id: int) -> ChartLayout:
    row = await db.get(ChartLayout, layout_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(404, "Layout not found")
    return row


async def _clear_default(db: DB, user_id: int, keep: int | None) -> None:
    for r in (await db.execute(select(ChartLayout).where(ChartLayout.user_id == user_id, ChartLayout.is_default.is_(True)))).scalars():
        if r.id != keep:
            r.is_default = False


@router.get("/layouts")
async def list_layouts(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.execute(select(ChartLayout).where(ChartLayout.user_id == user.id)
                             .order_by(ChartLayout.is_default.desc(), ChartLayout.updated_at.desc()))).scalars()
    return [_layout_out(r, with_state=False) for r in rows]


@router.post("/layouts", status_code=201)
async def create_layout(body: LayoutIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    n = (await db.execute(select(func.count()).select_from(ChartLayout).where(ChartLayout.user_id == user.id))).scalar_one()
    if n >= MAX_LAYOUTS:
        raise HTTPException(409, f"You can keep up to {MAX_LAYOUTS} chart layouts; delete one first")
    _check_size(body.state)
    first = n == 0
    row = ChartLayout(user_id=user.id, name=body.name, state=body.state, is_default=body.is_default or first)
    db.add(row)
    await db.flush()
    if row.is_default:
        await _clear_default(db, user.id, row.id)
    await db.commit()
    return _layout_out(row)


@router.get("/layouts/{layout_id}")
async def get_layout(layout_id: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    return _layout_out(await _owned(db, user.id, layout_id))


@router.put("/layouts/{layout_id}")
async def update_layout(layout_id: int, body: LayoutPatch, user: CurrentUser, db: DB) -> dict[str, Any]:
    row = await _owned(db, user.id, layout_id)
    if body.name is not None:
        row.name = body.name
    if body.state is not None:
        _check_size(body.state)
        row.state = body.state
    if body.is_default is not None:
        row.is_default = body.is_default
        if body.is_default:
            await _clear_default(db, user.id, row.id)
    row.updated_at = utcnow()
    await db.commit()
    return _layout_out(row, with_state=False)


@router.delete("/layouts/{layout_id}")
async def delete_layout(layout_id: int, user: CurrentUser, db: DB) -> dict[str, str]:
    row = await _owned(db, user.id, layout_id)
    await db.delete(row)
    await db.commit()
    return {"message": "deleted"}
