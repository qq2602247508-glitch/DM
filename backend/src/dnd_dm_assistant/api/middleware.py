from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from dnd_dm_assistant.application.reliability import ReliabilityService


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class ReadOnlySafeModeMiddleware(BaseHTTPMiddleware):
    """Reject mutations while retaining the local switch used to leave safe mode."""

    _methods = {"POST", "PUT", "PATCH", "DELETE"}
    _allowed_paths = {"/api/v1/system/safe-mode"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in self._methods or request.url.path in self._allowed_paths:
            return await call_next(request)
        try:
            service = ReliabilityService(
                request.app.state.database_engine, request.app.state.settings
            )  # type: ignore[arg-type]
            enabled = service.is_read_only()
        except Exception:
            enabled = bool(getattr(request.app.state.settings, "read_only_safe_mode", False))
        if enabled:
            return JSONResponse(
                status_code=423,
                content={
                    "code": "read_only_safe_mode",
                    "message": "写入已被只读安全模式阻止",
                    "details": {"path": request.url.path},
                    "request_id": str(getattr(request.state, "request_id", "unknown")),
                },
            )
        return await call_next(request)
