from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from algo_common.errors import AlgoError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AlgoError)
    async def _algo(_: Request, exc: AlgoError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}, "detail": exc.message},
            status_code=exc.status_code,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # `detail` may be a dict ({"message": ..., **context}): keep the message human-readable and move the
        # rest into `details` instead of stringifying the whole dict.
        detail = exc.detail
        details = None
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            message = detail["message"]
            details = {k: v for k, v in detail.items() if k != "message"} or None
        else:
            message = str(detail)
        return JSONResponse(
            {"error": {"code": f"http_{exc.status_code}", "message": message, "details": details}, "detail": detail},
            status_code=exc.status_code, headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        first = errors[0] if errors else None
        where = ".".join(str(x) for x in (first or {}).get("loc", []) if x not in ("body", "query", "path"))
        message = f"Invalid request: {where + ': ' if where else ''}{first['msg']}" if first else "Invalid request"
        return JSONResponse(
            {"error": {"code": "validation_failed", "message": message, "details": {"errors": errors}},
             "detail": errors},
            status_code=422,
        )
