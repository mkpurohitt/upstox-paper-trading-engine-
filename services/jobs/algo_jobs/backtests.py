"""Backtest / optimisation / walk-forward / Monte Carlo jobs."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from sqlalchemy import insert

from algo_common.bus import get_bus
from algo_common.logging import get_logger
from algo_common.metrics import BACKTESTS
from algo_common.timeutils import utcnow
from algo_db.models import Backtest, BacktestTrade
from algo_db.session import session_scope
from algo_jobs.registry import job
from market_data.registry import get_provider
from strategy_engine.backtest.engine import BacktestParams
from strategy_engine.data import clamp_range, load_frames
from strategy_engine.dsl import StrategyDSL
from strategy_engine.runner import run_backtest_sync

log = get_logger("jobs.backtest")


def _params(raw: dict[str, Any]) -> BacktestParams:
    return BacktestParams(
        start=datetime.fromisoformat(raw["start"]), end=datetime.fromisoformat(raw["end"]),
        initial_capital=float(raw.get("initial_capital", 1_000_000)), broker=raw.get("broker", "zerodha"),
        slippage_bps=float(raw.get("slippage_bps", 5)), fill=raw.get("fill", "next_open"),
        mode=raw.get("mode", "event"),
    )


def _ts(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


@job("run_backtest")
async def run_backtest(ctx: dict[str, Any], backtest_id: int) -> dict[str, Any]:
    bus = get_bus()
    channel = f"backtest:{backtest_id}"
    loop = asyncio.get_running_loop()
    async with session_scope() as db:
        bt = await db.get(Backtest, backtest_id)
        if bt is None:
            return {"error": "not found"}
        bt.status, bt.started_at, bt.progress = "running", utcnow(), 0.0
        dsl_raw, params_raw, kind = bt.dsl, bt.params, bt.kind
    await bus.publish(channel, {"id": backtest_id, "status": "running", "progress": 0.0, "message": "loading data"})
    started = time.perf_counter()
    try:
        dsl = StrategyDSL.model_validate(dsl_raw)
        params = _params(params_raw)
        start, end, clip_warning = clamp_range(dsl.timeframe, params.start, params.end)
        provider = get_provider()
        async with session_scope() as db:
            frames = await load_frames(provider, dsl.symbols, dsl.timeframe, start, end, db)
        if not frames or all(f.empty for f in frames.values()):
            raise ValueError("no market data for the selected symbols / range")
        last_pub = [0.0]

        def progress(frac: float, msg: str) -> None:
            if frac - last_pub[0] >= 0.03 or frac >= 1:
                last_pub[0] = frac
                loop.call_soon_threadsafe(asyncio.ensure_future, bus.publish(
                    channel, {"id": backtest_id, "status": "running", "progress": round(0.05 + frac * 0.9, 3), "message": msg}))

        options = params_raw.get("options", {})
        result = await asyncio.to_thread(run_backtest_sync, kind, dsl, params, frames, options, progress,
                                         provider.name == "mock")
        if clip_warning:
            result["extra"].setdefault("warnings", []).insert(0, clip_warning)
        result["extra"]["runtime_s"] = round(time.perf_counter() - started, 2)
        result["extra"]["data_source"] = provider.name
        async with session_scope() as db:
            bt = await db.get(Backtest, backtest_id)
            assert bt is not None
            bt.metrics, bt.equity_curve, bt.drawdown_curve = result["metrics"], result["equity_curve"], result["drawdown_curve"]
            bt.monthly_returns, bt.extra = result["monthly_returns"], result["extra"]
            bt.status, bt.progress, bt.finished_at = "completed", 1.0, utcnow()
            rows = [{
                "backtest_id": backtest_id, "symbol": t["symbol"][:64], "leg": t.get("leg"), "side": t["side"][:16],
                "quantity": int(t.get("quantity") or 0), "entry_ts": _ts(t["entry_ts"]),
                "entry_price": float(t.get("entry_price") or 0), "exit_ts": _ts(t.get("exit_ts")),
                "exit_price": t.get("exit_price"), "gross_pnl": t.get("gross_pnl", 0.0), "charges": t.get("charges", 0.0),
                "net_pnl": t.get("net_pnl", 0.0), "exit_reason": t.get("exit_reason"),
                "meta": {k: v for k, v in t.items() if k in ("legs", "bars_held", "charges_breakdown")},
            } for t in result["trades"][:5000]]
            if rows:
                await db.execute(insert(BacktestTrade), rows)
        BACKTESTS.labels(kind, "completed").inc()
        await bus.publish(channel, {"id": backtest_id, "status": "completed", "progress": 1.0, "metrics": result["metrics"]})
        return {"status": "completed"}
    except Exception as exc:
        log.warning("backtest.failed", id=backtest_id, error=str(exc))
        async with session_scope() as db:
            bt = await db.get(Backtest, backtest_id)
            if bt is not None:
                bt.status, bt.error, bt.finished_at = "failed", str(exc)[:2000], utcnow()
        BACKTESTS.labels(kind, "failed").inc()
        await bus.publish(channel, {"id": backtest_id, "status": "failed", "error": str(exc)[:500]})
        return {"status": "failed", "error": str(exc)}
