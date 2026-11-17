"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from algo_common.logging import configure_logging, get_logger
from algo_common.settings import get_settings
from algo_db.session import create_all, dispose_engine, session_scope
from app.core.errors import install_error_handlers
from app.core.middleware import GlobalRateLimitMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.telemetry import init_otel, init_sentry
from app.routes import auth, health, users
from app.runtime import runtime
from app.ws import gateway

log = get_logger("api")

API_DESCRIPTION = """
AlgoDesk API - AI-first algorithmic trading for NSE, BSE and MCX.

**Disclaimer:** Analytics and AI output are educational. Nothing here is investment advice.
Trading in securities and derivatives involves substantial risk of loss.
"""

ROUTERS = [health.router, auth.router, users.router]


def _register_optional_routers(app: FastAPI) -> None:
    """Routers added by later phases register here (import errors are fatal by design)."""
    import importlib

    for name in (
        "market", "strategies", "backtests", "brokers", "orders", "deployments", "risk",
        "analysis", "ai", "rag", "news", "portfolio", "billing", "account", "admin", "watchlists",
    ):
        try:
            module = importlib.import_module(f"app.routes.{name}")
        except ModuleNotFoundError as exc:
            if exc.name == f"app.routes.{name}":
                continue
            raise
        app.include_router(module.router)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    if s.is_sqlite:
        await create_all()
    async with session_scope() as db:
        from app.services.users import ensure_plans

        await ensure_plans(db)
    await runtime.start()
    log.info("api.started", data_mode=s.data_mode, environment=s.environment)
    try:
        yield
    finally:
        await runtime.stop()
        await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level, s.log_json, service="api")
    init_sentry()
    app = FastAPI(
        title="AlgoDesk API",
        version="0.1.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        # one schema per model (input mode): fields with defaults stay optional in the TS client
        separate_input_output_schemas=False,
    )
    app.add_middleware(GlobalRateLimitMiddleware, limit_per_min=s.api_rate_limit_per_min)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID", "X-Idempotency-Key"],
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    for r in ROUTERS:
        app.include_router(r)
    _register_optional_routers(app)
    app.include_router(gateway.router)
    init_otel(app)
    return app


app = create_app()
