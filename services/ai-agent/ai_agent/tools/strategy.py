"""Strategy tools: generate (DSL JSON only), backtest (same job path as the Build page) and deploy (confirmation card only)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from ai_agent.drafts import draft_from_description
from ai_agent.tools.registry import ToolContext, ToolResult, tool
from algo_common.settings import get_settings
from algo_common.timeutils import now_ist
from algo_db.audit import audit
from algo_db.models import Backtest, Strategy, StrategyVersion
from algo_db.session import session_scope
from strategy_engine.dsl import validate_dsl

DSL_GUIDE = (
    "Optional full AlgoDesk StrategyDSL JSON. Shape: {dsl_version:'1.0', name, description, kind:'equity'|'options'|'pair', "
    "universe:{symbols:['NSE:RELIANCE']} or {underlying:'NIFTY'}, timeframe:'1m'|'3m'|'5m'|'15m'|'30m'|'1h'|'1d', "
    "product:'MIS'|'CNC'|'NRML', indicators:[{id, kind:'EMA'|'SMA'|'RSI'|'MACD'|'BBANDS'|'SUPERTREND'|'ADX'|'VWAP'|'ATR'|..., "
    "params:{period:..}}], entry:{long:{kind:'all'|'any', conditions:[{kind:'compare', left:{type:'indicator', ref:'ema_fast'}, "
    "op:'>'|'<'|'>='|'<='|'crosses_above'|'crosses_below', right:{type:'indicator'|'price'|'const', ...}}]}, short:{...}}, "
    "exit:{long:{...}, short:{...}, stop_loss:{type:'percent'|'points'|'atr', value}, target:{...}, trailing_sl:{...}}, "
    "legs (options):[{id, action:'BUY'|'SELL', option_type:'CE'|'PE', strike:{mode:'ATM_OFFSET', offset:0}|{mode:'DELTA', delta:0.2}, "
    "expiry:'current'|'next'|'monthly', lots, stop_loss_pct}], options_exit:{combined_stop_loss_pct, combined_target_pct}, "
    "pair:{leg_a, leg_b, lookback, entry_z, exit_z}, sizing:{mode:'capital_pct'|'fixed_qty'|'fixed_lots', value}, "
    "schedule:{entry_after:'09:20', entry_before:'15:00', square_off:'15:15'}, risk:{max_loss_per_day}}. "
    "Omit to let the platform draft one from the description."
)


class GenArgs(BaseModel):
    description: str = Field(min_length=3, max_length=2000, description="What the strategy should do, in plain English")
    dsl: dict[str, Any] | None = Field(default=None, description=DSL_GUIDE)


def _validate(dsl: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    model, errors = validate_dsl(dsl)
    return (model.model_dump(mode="json") if model else dsl), errors


@tool("generate_strategy", "Draft a trading strategy as AlgoDesk DSL JSON (never code). Returns the validated DSL, any "
      "validation errors to fix, and a plain-English explanation. Does not save or run anything.", GenArgs, category="strategy")
async def generate_strategy(ctx: ToolContext, a: GenArgs) -> ToolResult:
    if a.dsl:
        dsl, errors = _validate(a.dsl)
        explanation = a.dsl.get("description") or a.description
    else:
        draft, explanation = draft_from_description(a.description)
        dsl, errors = _validate(draft)
    data = {"dsl": dsl, "valid": not errors, "errors": errors[:8], "explanation": explanation}
    return ToolResult(data, {"type": "strategy", **data}, ok=not errors)


class BacktestArgs(BaseModel):
    strategy_id: int | None = Field(default=None, description="a saved strategy (yours or a template)")
    dsl: dict[str, Any] | None = Field(default=None, description="or an unsaved DSL, e.g. from generate_strategy")
    period_days: int = Field(default=365, ge=30, le=3650)
    initial_capital: float = Field(default=1_000_000, gt=0, le=1e10)


def _downsample(curve: list[Any], n: int = 80) -> list[Any]:
    if len(curve) <= n:
        return curve
    step = len(curve) / n
    return [curve[int(i * step)] for i in range(n)] + [curve[-1]]


@tool("run_backtest", "Backtest a saved strategy or DSL over the last N days with Indian costs (STT, exchange, GST, stamp, "
      "brokerage) and slippage. Returns key metrics and warnings.", BacktestArgs, category="strategy", timeout_s=150.0)
async def run_backtest(ctx: ToolContext, a: BacktestArgs) -> ToolResult:
    from algo_jobs.queue import enqueue

    if a.strategy_id is None and not a.dsl:
        return ToolResult({"error": "provide strategy_id or dsl"}, ok=False)
    if ctx.quota is not None:
        await ctx.quota("backtest")
    async with session_scope() as db:
        strategy = None
        if a.strategy_id is not None:
            strategy = await db.get(Strategy, a.strategy_id)
            if strategy is None or (strategy.user_id != ctx.user_id and not strategy.is_template):
                return ToolResult({"error": f"strategy {a.strategy_id} not found"}, ok=False)
            raw = strategy.dsl
        else:
            raw = a.dsl or {}
        dsl, errors = _validate(raw)
        if errors:
            return ToolResult({"error": "DSL is invalid", "errors": errors[:5]}, ok=False)
        end = now_ist().replace(hour=15, minute=30, second=0, microsecond=0)
        start = end - timedelta(days=a.period_days)
        bt = Backtest(user_id=ctx.user_id, strategy_id=strategy.id if strategy else None,
                      strategy_version=strategy.version if strategy else None, kind="backtest", dsl=dsl, status="queued",
                      params={"start": start.isoformat(), "end": end.isoformat(), "initial_capital": a.initial_capital,
                              "broker": "zerodha", "slippage_bps": 5, "fill": "next_open", "mode": "event", "options": {},
                              "source": "copilot"})
        db.add(bt)
        await db.flush()
        bt_id = bt.id
    await enqueue("run_backtest", backtest_id=bt_id)
    deadline = asyncio.get_running_loop().time() + 140
    while True:
        await asyncio.sleep(0.5)
        async with session_scope() as db:
            bt = await db.get(Backtest, bt_id)
            assert bt is not None
            status, metrics, equity, extra, error = bt.status, bt.metrics, bt.equity_curve, bt.extra, bt.error
        if status in ("completed", "failed") or asyncio.get_running_loop().time() > deadline:
            break
    period = f"{start.date()} → {end.date()}"
    if status == "failed":
        return ToolResult({"error": f"backtest failed: {error}", "backtest_id": bt_id}, ok=False)
    if status != "completed":
        return ToolResult({"status": status, "backtest_id": bt_id, "note": "still running; results will appear on the Build page"},
                          {"type": "backtest", "backtest_id": bt_id, "status": status, "name": dsl.get("name")})
    keys = ("net_pnl", "total_return_pct", "cagr_pct", "sharpe", "sortino", "max_drawdown_pct", "trades", "win_rate_pct",
            "profit_factor", "expectancy", "total_charges", "benchmark_return_pct", "exposure_pct")
    m = {k: metrics.get(k) for k in keys}
    warnings = (extra or {}).get("warnings", [])[:4]
    data = {"backtest_id": bt_id, "name": dsl.get("name"), "period": period, "metrics": m, "warnings": warnings,
            "data_source": (extra or {}).get("data_source")}
    card = {"type": "backtest", **data, "status": "completed", "strategy_id": a.strategy_id, "equity": _downsample(equity),
            "dsl": dsl if a.strategy_id is None else None}
    return ToolResult(data, card)


class DeployArgs(BaseModel):
    strategy_id: int | None = None
    dsl: dict[str, Any] | None = Field(default=None, description="unsaved DSL; it will be saved to the user's strategies first")
    mode: Literal["paper", "live", "notify"] = "paper"
    capital: float = Field(default=1_000_000, gt=0)
    multiplier: int = Field(default=1, ge=1, le=50)


@tool("deploy_strategy", "PREPARE a deployment for the user to confirm in the UI. It never starts trading by itself: the user must "
      "press Confirm (and enter a 2FA code for live mode).", DeployArgs, category="strategy")
async def deploy_strategy(ctx: ToolContext, a: DeployArgs) -> ToolResult:
    async with session_scope() as db:
        if a.strategy_id is not None:
            s = await db.get(Strategy, a.strategy_id)
            if s is None or s.user_id != ctx.user_id:
                return ToolResult({"error": f"strategy {a.strategy_id} not found in your strategies"}, ok=False)
        elif a.dsl:
            dsl, errors = _validate(a.dsl)
            if errors:
                return ToolResult({"error": "DSL is invalid", "errors": errors[:5]}, ok=False)
            existing = (await db.execute(select(Strategy).where(Strategy.user_id == ctx.user_id, Strategy.name == dsl["name"],
                                                                Strategy.source == "ai"))).scalars().first()
            if existing is not None and existing.dsl == dsl:
                s = existing
            else:
                s = Strategy(user_id=ctx.user_id, name=dsl["name"], description=dsl.get("description", ""), dsl=dsl,
                             kind=dsl.get("kind", "equity"), source="ai", tags=dsl.get("tags", []), version=1)
                db.add(s)
                await db.flush()
                db.add(StrategyVersion(strategy_id=s.id, version=1, dsl=dsl, note="created by copilot"))
                await audit(db, "strategy.create", user_id=ctx.user_id, entity_type="strategy", entity_id=s.id,
                            payload={"name": s.name, "kind": s.kind, "source": "ai"})
        else:
            return ToolResult({"error": "provide strategy_id or dsl"}, ok=False)
        prefix = get_settings().algo_id_prefix
        info = {"strategy_id": s.id, "name": s.name, "kind": s.kind, "version": s.version, "mode": a.mode, "capital": a.capital,
                "multiplier": a.multiplier, "requires_2fa": a.mode == "live", "algo_id_preview": f"{prefix}-S{s.id}",
                "risk_limits": {"max_loss_per_day": 10000, "max_orders_per_min": 30, "max_position_value": 500000, "max_lots": 5}}
    data = {"status": "awaiting_user_confirmation", **info,
            "note": "Nothing has been deployed. The user must confirm on the card (2FA required for live)."}
    return ToolResult(data, {"type": "deploy_confirm", **info})
