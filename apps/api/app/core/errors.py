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
        return JSONResponse(
            {"error": {"code": f"http_{exc.status_code}", "message": str(exc.detail)}, "detail": exc.detail},
            status_code=exc.status_code, headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(
            {"error": {"code": "validation_failed", "message": "Invalid request", "details": {"errors": errors}},
             "detail": errors},
            status_code=422,
        )
