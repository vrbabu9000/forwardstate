"""One error shape for every failure: ``{"detail": {"code", "message", "field"}}`` (docs/api.md)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("forwardstate.api")


class ApiError(Exception):
    """Raise from any route to return ``status`` with the standard error body."""

    def __init__(self, status: int, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field


def not_found(what: str, ident: str, field: str | None = None) -> ApiError:
    return ApiError(404, "not_found", f"Unknown {what} '{ident}'.", field)


def invalid(message: str, field: str | None = None, code: str = "invalid_input") -> ApiError:
    return ApiError(422, code, message, field)


def _body(code: str, message: str, field: str | None) -> dict:
    return {"detail": {"code": code, "message": message, "field": field}}


def _loc_to_field(loc: tuple | list) -> str | None:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts) or None


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=_body(exc.code, exc.message, exc.field))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = _loc_to_field(first.get("loc", ()))
        msg = "; ".join(
            f"{_loc_to_field(e.get('loc', ())) or 'request'}: {e.get('msg', 'invalid')}"
            for e in errors[:5]
        )
        return JSONResponse(status_code=422, content=_body("validation_error", msg, field))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail), None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled API error")
        return JSONResponse(
            status_code=500,
            content=_body("internal_error", f"{type(exc).__name__}: {exc}", None),
        )
