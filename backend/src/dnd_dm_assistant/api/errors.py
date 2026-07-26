from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from dnd_dm_assistant.api.schemas import ErrorEnvelope


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _safe_details(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe_details(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_details(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any,
    request: Request,
) -> JSONResponse:
    body = ErrorEnvelope(
        code=code,
        message=message,
        details=details,
        request_id=_request_id(request),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        message = detail if isinstance(detail, str) else "Request failed"
        return _response(
            status_code=exc.status_code,
            code=f"http_{exc.status_code}",
            message=message,
            details=None if isinstance(detail, str) else detail,
            request=request,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _response(
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details=_safe_details(exc.errors()),
            request=request,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _exc: Exception) -> JSONResponse:
        return _response(
            status_code=500,
            code="internal_error",
            message="An unexpected error occurred",
            details=None,
            request=request,
        )
