"""Price alerts created from the chart: fire once when the last traded price reaches the level.

Each alert stores ``condition = {"op": "above" | "below", "value": level}``; the direction is fixed when the alert is
created (relative to the price at that moment), so an alert never fires immediately. Evaluation runs every couple of
seconds in the market-data process (or inside the API with embedded workers); a fired alert becomes ``triggered`` and
the user gets an in-app notification (plus email/Telegram/WhatsApp according to their preferences).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from algo_common.logging import get_logger
from algo_common.timeutils import utcnow
from algo_db.models import Alert
from algo_db.session import session_scope
from broker_gateway.notify import notify
from market_data.registry import get_provider

log = get_logger("jobs.price_alerts")
POLL_SECONDS = 2.0


def crossed(op: str, level: float, ltp: float) -> bool:
    return (op == "above" and ltp >= level) or (op == "below" and ltp <= level)


def _fmt(x: float) -> str:
    return f"{x:,.2f}"


async def evaluate_once() -> int:
    async with session_scope() as db:
        alerts = (await db.execute(select(Alert).where(Alert.kind == "price", Alert.status == "active"))).scalars().all()
        if not alerts:
            return 0
        symbols = sorted({a.symbol for a in alerts if a.symbol})
        quotes = await get_provider().quotes(symbols)
        fired = 0
        for a in alerts:
            q = quotes.get(a.symbol or "")
            cond = a.condition or {}
            try:
                level = float(cond.get("value"))
            except (TypeError, ValueError):
                continue
            op = str(cond.get("op", "above"))
            if q is None or not q.ltp or not crossed(op, level, q.ltp):
                continue
            a.status, a.triggered_at = "triggered", utcnow()
            short = (a.symbol or "").split(":", 1)[-1]
            title = f"{short} {'crossed above' if op == 'above' else 'fell below'} {_fmt(level)}"
            body = (a.message + " · " if a.message else "") + f"Last price {_fmt(q.ltp)}"
            await notify(db, a.user_id, title, body, kind="alert",
                         data={"alert_id": a.id, "symbol": a.symbol, "level": level, "price": q.ltp, "op": op})
            fired += 1
        return fired


async def run_forever() -> None:
    while True:
        try:
            n = await evaluate_once()
            if n:
                log.info("price_alerts.fired", count=n)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("price_alerts.evaluation_failed", error=str(exc))
        await asyncio.sleep(POLL_SECONDS)
