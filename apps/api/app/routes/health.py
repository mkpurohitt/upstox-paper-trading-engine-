from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from algo_common.settings import get_settings
from algo_db.session import get_engine

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health() -> dict[str, Any]:
    s = get_settings()
    db_ok = True
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    redis_ok: bool | None = None
    if s.redis_url:
        try:
            from algo_common.kv import get_kv

            await get_kv().set("health:ping", "1", ttl=5)
            redis_ok = True
        except Exception:
            redis_ok = False
    return {
        "status": "ok" if db_ok and redis_ok is not False else "degraded",
        "db": db_ok,
        "redis": redis_ok,
        "data_mode": s.data_mode,
        "environment": s.environment,
        "embedded_workers": s.embedded_workers,
        "providers": {
            "upstox": s.upstox_configured,
            "nse_mcp": bool(s.nse_mcp_url),
            "llm": s.llm_configured,
            "razorpay": s.razorpay_configured,
            "google_oauth": s.google_oauth_configured,
        },
    }


@router.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)
