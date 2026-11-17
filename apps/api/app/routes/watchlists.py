from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from algo_db.models import Watchlist
from app.core.deps import DB, CurrentUser
from app.schemas.common import ORM, Message

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    symbols: list[str] = Field(default_factory=list, max_length=100)


class WatchlistOut(ORM):
    id: int
    name: str
    symbols: list[str]


@router.get("", response_model=list[WatchlistOut])
async def lists(user: CurrentUser, db: DB) -> list[Watchlist]:
    return list((await db.execute(select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.sort_order, Watchlist.id))).scalars())


@router.post("", response_model=WatchlistOut, status_code=201)
async def create(body: WatchlistIn, user: CurrentUser, db: DB) -> Watchlist:
    w = Watchlist(user_id=user.id, name=body.name, symbols=list(dict.fromkeys(body.symbols)))
    db.add(w)
    await db.flush()
    return w


@router.put("/{wid}", response_model=WatchlistOut)
async def update(wid: int, body: WatchlistIn, user: CurrentUser, db: DB) -> Watchlist:
    w = await db.get(Watchlist, wid)
    if w is None or w.user_id != user.id:
        raise HTTPException(404, "Watchlist not found")
    w.name, w.symbols = body.name, list(dict.fromkeys(body.symbols))
    return w


@router.delete("/{wid}", response_model=Message)
async def delete(wid: int, user: CurrentUser, db: DB) -> Message:
    w = await db.get(Watchlist, wid)
    if w is None or w.user_id != user.id:
        raise HTTPException(404, "Watchlist not found")
    await db.delete(w)
    return Message(message="Deleted")
