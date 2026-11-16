"""HTTP middleware: request context, metrics, security headers, global rate limit."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from algo_common.logging import get_logger
from algo_common.metrics import HTTP_LATENCY, HTTP_REQUESTS
from algo_common.ratelimit import SlidingWindowLimiter
from algo_common.settings import get_settings

log = get_logger("http")

_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'"
)


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("http.unhandled", path=request.url.path)
            response = JSONResponse({"error": {"code": "internal", "message": "Internal server error"}}, 500)
        elapsed = time.perf_counter() - start
        route = _route_label(request)
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, route).observe(elapsed)
        response.headers["x-request-id"] = request_id
        if not request.url.path.startswith(("/metrics", "/api/health")):
            log.info(
                "http.request", method=request.method, path=request.url.path, status=response.status_code,
                ms=round(elapsed * 1000, 1),
            )
        structlog.contextvars.unbind_contextvars("request_id")
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(self)")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault(
            "Content-Security-Policy", DOCS_CSP if request.url.path.startswith(_DOCS_PATHS) else API_CSP
        )
        if get_settings().cookie_secure:
            h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
        return response


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """Coarse per-client limiter protecting every API route (OWASP API4)."""

    def __init__(self, app, limit_per_min: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.limiter = SlidingWindowLimiter(limit_per_min, 60.0, prefix="rl:api")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith("/api/") and request.method != "OPTIONS":
            ident = request.headers.get("authorization", "")[-24:] or (
                request.client.host if request.client else "anon"
            )
            ok, _ = await self.limiter.hit(ident)
            if not ok:
                return JSONResponse(
                    {"error": {"code": "rate_limited", "message": "Too many requests"}},
                    status_code=429, headers={"Retry-After": "30"},
                )
        return await call_next(request)
