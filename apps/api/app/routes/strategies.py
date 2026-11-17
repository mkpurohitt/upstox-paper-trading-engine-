"""Strategy CRUD, versioning, DSL validation, code-mode compilation, templates."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_, select

from algo_db.audit import audit
from algo_db.models import Backtest, Strategy, StrategyVersion
from app.core.deps import DB, CurrentUser
from app.schemas.common import Message
from app.schemas.strategy import (
    CompileCodeIn,
    CompileCodeOut,
    IndicatorCatalogItem,
    ListingIn,
    StrategyIn,
    StrategyOut,
    StrategyVersionOut,
    ValidateOut,
)
from strategy_engine.dsl import dsl_json_schema, validate_dsl
from strategy_engine.indicators import catalog
from strategy_engine.sandbox import CODE_TEMPLATE, SandboxError, compile_strategy_code
from strategy_engine.templates import TEMPLATES

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


async def _get_owned(db: DB, user_id: int, strategy_id: int, allow_public: bool = False) -> Strategy:
    s = await db.get(Strategy, strategy_id)
    if s is None:
        raise HTTPException(404, "Strategy not found")
    if s.user_id != user_id and not (allow_public and (s.is_template or s.visibility == "marketplace")):
        raise HTTPException(404, "Strategy not found")
    return s


async def _out(db: DB, s: Strategy) -> StrategyOut:
    out = StrategyOut.model_validate(s)
    bt = (await db.execute(
        select(Backtest).where(Backtest.strategy_id == s.id, Backtest.kind == "backtest", Backtest.status == "completed")
        .order_by(Backtest.id.desc()).limit(1)
    )).scalar_one_or_none()
    if bt:
        m = bt.metrics
        out.last_backtest = {"id": bt.id, "net_pnl": m.get("net_pnl"), "sharpe": m.get("sharpe"),
                             "max_drawdown_pct": m.get("max_drawdown_pct"), "win_rate_pct": m.get("win_rate_pct"),
                             "trades": m.get("trades"), "finished_at": bt.finished_at.isoformat() if bt.finished_at else None,
                             "spark": [p["value"] for p in bt.equity_curve[:: max(1, len(bt.equity_curve) // 40)]]}
    return out


@router.get("", response_model=list[StrategyOut])
async def list_strategies(user: CurrentUser, db: DB, scope: str = "mine") -> list[StrategyOut]:
    q = select(Strategy)
    if scope == "marketplace":
        q = q.where(Strategy.visibility == "marketplace", or_(Strategy.box_type == "white_box", Strategy.ra_status == "approved"))
    elif scope == "templates":
        q = q.where(Strategy.is_template.is_(True))
    else:
        q = q.where(Strategy.user_id == user.id)
    rows = (await db.execute(q.order_by(Strategy.updated_at.desc()).limit(200))).scalars().all()
    return [await _out(db, s) for s in rows]


@router.get("/templates", response_model=list[dict[str, Any]])
async def templates(_: CurrentUser) -> list[dict[str, Any]]:
    return TEMPLATES


@router.get("/indicators", response_model=list[IndicatorCatalogItem])
async def indicators(_: CurrentUser) -> list[dict[str, Any]]:
    return catalog()


@router.get("/dsl/schema")
async def schema(_: CurrentUser) -> dict[str, Any]:
    return dsl_json_schema()


@router.get("/code-template", response_model=dict[str, str])
async def code_template(_: CurrentUser) -> dict[str, str]:
    return {"code": CODE_TEMPLATE}


@router.post("/validate", response_model=ValidateOut)
async def validate(body: dict[str, Any], _: CurrentUser) -> ValidateOut:
    model, errors = validate_dsl(body)
    return ValidateOut(valid=model is not None, errors=errors, dsl=model)


@router.post("/compile-code", response_model=CompileCodeOut)
async def compile_code(body: CompileCodeIn, _: CurrentUser) -> CompileCodeOut:
    try:
        dsl, stdout = await asyncio.to_thread(compile_strategy_code, body.code)
    except SandboxError as exc:
        return CompileCodeOut(ok=False, errors=[{"path": "code", "message": str(exc)}])
    model, errors = validate_dsl(dsl)
    return CompileCodeOut(ok=model is not None, dsl=model.model_dump(mode="json") if model else dsl, errors=errors, stdout=stdout)


@router.post("", response_model=StrategyOut, status_code=201)
async def create(body: StrategyIn, user: CurrentUser, db: DB) -> StrategyOut:
    dsl = body.dsl.model_dump(mode="json")
    s = Strategy(user_id=user.id, name=body.dsl.name, description=body.dsl.description, dsl=dsl, kind=body.dsl.kind,
                 source=body.source, code=body.code, graph=body.graph, tags=body.dsl.tags, version=1)
    db.add(s)
    await db.flush()
    db.add(StrategyVersion(strategy_id=s.id, version=1, dsl=dsl, note=body.note or "created"))
    await audit(db, "strategy.create", user_id=user.id, entity_type="strategy", entity_id=s.id,
                payload={"name": s.name, "kind": s.kind, "source": s.source})
    return await _out(db, s)


@router.get("/{strategy_id}", response_model=StrategyOut)
async def get(strategy_id: int, user: CurrentUser, db: DB) -> StrategyOut:
    return await _out(db, await _get_owned(db, user.id, strategy_id, allow_public=True))


@router.put("/{strategy_id}", response_model=StrategyOut)
async def update(strategy_id: int, body: StrategyIn, user: CurrentUser, db: DB) -> StrategyOut:
    s = await _get_owned(db, user.id, strategy_id)
    dsl = body.dsl.model_dump(mode="json")
    if dsl != s.dsl:
        s.version += 1
        db.add(StrategyVersion(strategy_id=s.id, version=s.version, dsl=dsl, note=body.note or f"v{s.version}"))
    s.dsl, s.name, s.description, s.kind, s.tags = dsl, body.dsl.name, body.dsl.description, body.dsl.kind, body.dsl.tags
    s.source, s.code, s.graph = body.source, body.code, body.graph
    await audit(db, "strategy.update", user_id=user.id, entity_type="strategy", entity_id=s.id, payload={"version": s.version})
    await db.flush()
    return await _out(db, s)


@router.delete("/{strategy_id}", response_model=Message)
async def delete(strategy_id: int, user: CurrentUser, db: DB) -> Message:
    s = await _get_owned(db, user.id, strategy_id)
    from algo_db.models import Deployment

    running = (await db.execute(select(Deployment.id).where(
        Deployment.strategy_id == s.id, Deployment.status.in_(("running", "paused", "pending"))))).first()
    if running:
        raise HTTPException(409, "Stop the strategy's running deployments first")
    await db.delete(s)
    await audit(db, "strategy.delete", user_id=user.id, entity_type="strategy", entity_id=strategy_id)
    return Message(message="Strategy deleted")


@router.get("/{strategy_id}/versions", response_model=list[StrategyVersionOut])
async def versions(strategy_id: int, user: CurrentUser, db: DB) -> list[StrategyVersion]:
    await _get_owned(db, user.id, strategy_id)
    q = select(StrategyVersion).where(StrategyVersion.strategy_id == strategy_id).order_by(StrategyVersion.version.desc())
    return list((await db.execute(q)).scalars())


@router.post("/{strategy_id}/clone", response_model=StrategyOut, status_code=201)
async def clone(strategy_id: int, user: CurrentUser, db: DB) -> StrategyOut:
    src = await _get_owned(db, user.id, strategy_id, allow_public=True)
    if src.box_type == "black_box" and src.user_id != user.id:
        raise HTTPException(403, "Black-box strategies cannot be cloned; subscribe to deploy them instead")
    dsl = {**src.dsl, "name": f"{src.name} (copy)"}
    s = Strategy(user_id=user.id, name=dsl["name"], description=src.description, dsl=dsl, kind=src.kind, source=src.source,
                 code=src.code, graph=src.graph, tags=src.tags, version=1)
    db.add(s)
    await db.flush()
    db.add(StrategyVersion(strategy_id=s.id, version=1, dsl=dsl, note=f"cloned from #{src.id}"))
    return await _out(db, s)


@router.patch("/{strategy_id}/listing", response_model=StrategyOut)
async def listing(strategy_id: int, body: ListingIn, user: CurrentUser, db: DB) -> StrategyOut:
    """Marketplace listing. Black-box listings require a SEBI RA registration
    number and stay hidden until an admin approves them."""
    s = await _get_owned(db, user.id, strategy_id)
    if body.box_type == "black_box" and not body.provider_ra_number:
        raise HTTPException(422, "Black-box strategies require the provider's SEBI Research Analyst registration number")
    s.visibility, s.box_type = body.visibility, body.box_type
    s.provider_ra_number = body.provider_ra_number
    s.ra_status = "pending" if body.box_type == "black_box" else "none"
    await audit(db, "strategy.listing", user_id=user.id, entity_type="strategy", entity_id=s.id,
                payload=body.model_dump())
    return await _out(db, s)
