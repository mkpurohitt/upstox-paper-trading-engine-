"""Backtest jobs (queued to workers, progress streamed over WebSocket)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from algo_db.models import Backtest, BacktestTrade, Strategy
from algo_jobs.queue import enqueue
from app.core.deps import DB, CurrentUser
from app.schemas.common import Message
from app.schemas.strategy import BacktestIn, BacktestOut, BacktestSummary, BacktestTradeOut
from app.services.quotas import enforce

router = APIRouter(prefix="/api/backtests", tags=["backtests"])


@router.post("", response_model=BacktestSummary, status_code=202)
async def create(body: BacktestIn, user: CurrentUser, db: DB) -> BacktestSummary:
    await enforce(db, user.id, "backtest")
    strategy = None
    if body.strategy_id is not None:
        strategy = await db.get(Strategy, body.strategy_id)
        if strategy is None or (strategy.user_id != user.id and not strategy.is_template):
            raise HTTPException(404, "Strategy not found")
    dsl = body.dsl.model_dump(mode="json") if body.dsl else (strategy.dsl if strategy else None)
    if dsl is None:
        raise HTTPException(422, "Provide strategy_id or dsl")
    if body.params.end <= body.params.start:
        raise HTTPException(422, "end must be after start")
    if body.kind in ("optimise", "walk_forward") and not body.params.options.get("space"):
        raise HTTPException(422, "options.space (parameter ranges) is required")
    bt = Backtest(
        user_id=user.id, strategy_id=strategy.id if strategy else None, strategy_version=strategy.version if strategy else None,
        kind=body.kind, dsl=dsl, params=body.params.model_dump(mode="json"), status="queued",
    )
    db.add(bt)
    await db.flush()
    await db.commit()
    await enqueue("run_backtest", backtest_id=bt.id)
    out = BacktestSummary.model_validate(bt)
    out.name = dsl.get("name")
    return out


@router.get("", response_model=list[BacktestSummary])
async def list_backtests(user: CurrentUser, db: DB, strategy_id: int | None = None, limit: int = Query(30, le=200)) -> list[BacktestSummary]:
    q = select(Backtest).where(Backtest.user_id == user.id)
    if strategy_id is not None:
        q = q.where(Backtest.strategy_id == strategy_id)
    rows = (await db.execute(q.order_by(Backtest.id.desc()).limit(limit))).scalars().all()
    out = []
    for r in rows:
        s = BacktestSummary.model_validate(r)
        s.name = r.dsl.get("name")
        out.append(s)
    return out


@router.get("/{backtest_id}", response_model=BacktestOut)
async def get(backtest_id: int, user: CurrentUser, db: DB) -> BacktestOut:
    bt = await db.get(Backtest, backtest_id)
    if bt is None or bt.user_id != user.id:
        raise HTTPException(404, "Backtest not found")
    out = BacktestOut.model_validate(bt)
    out.name = bt.dsl.get("name")
    return out


@router.get("/{backtest_id}/trades", response_model=list[BacktestTradeOut])
async def trades(backtest_id: int, user: CurrentUser, db: DB, limit: int = Query(500, le=5000), offset: int = 0) -> list[BacktestTrade]:
    bt = await db.get(Backtest, backtest_id)
    if bt is None or bt.user_id != user.id:
        raise HTTPException(404, "Backtest not found")
    q = select(BacktestTrade).where(BacktestTrade.backtest_id == backtest_id).order_by(BacktestTrade.entry_ts).offset(offset).limit(limit)
    return list((await db.execute(q)).scalars())


@router.delete("/{backtest_id}", response_model=Message)
async def delete(backtest_id: int, user: CurrentUser, db: DB) -> Message:
    bt = await db.get(Backtest, backtest_id)
    if bt is None or bt.user_id != user.id:
        raise HTTPException(404, "Backtest not found")
    await db.delete(bt)
    return Message(message="Deleted")
