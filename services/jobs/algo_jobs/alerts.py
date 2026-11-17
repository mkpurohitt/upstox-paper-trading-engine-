"""Scheduled screen alerts: run saved screens with alerts on and notify about new matches."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select

from algo_common.logging import get_logger
from algo_common.timeutils import utcnow
from algo_db.models import Screen
from algo_db.session import session_scope
from algo_jobs.registry import cron, job
from broker_gateway.notify import notify
from market_data.registry import get_provider
from strategy_engine.analytics.screener import ScreenQuery, run_screen

log = get_logger("jobs.alerts")


@job("run_screen_alerts")
async def run_screen_alerts(ctx: dict[str, Any]) -> dict[str, int]:
    now = utcnow()
    fired = 0
    async with session_scope() as db:
        screens = (await db.execute(select(Screen).where(Screen.alert_enabled.is_(True)))).scalars().all()
        for s in screens:
            if s.last_run_at and s.last_run_at + timedelta(minutes=s.schedule_minutes) > now:
                continue
            res = await run_screen(get_provider(), ScreenQuery.model_validate(s.criteria))
            syms = [r["symbol"] for r in res["rows"]]
            new = sorted(set(syms) - set(s.last_results or []))
            s.last_run_at, s.last_results = now, syms
            if new:
                fired += 1
                await notify(db, s.user_id, f"Screen '{s.name}': {len(new)} new match(es)", ", ".join(new[:20]), kind="screen",
                             data={"screen_id": s.id, "symbols": new})
    return {"fired": fired}


cron("run_screen_alerts", minute=set(range(0, 60, 5)))
