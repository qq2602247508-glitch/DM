from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from dnd_dm_assistant.api.errors import install_error_handlers
from dnd_dm_assistant.api.middleware import RequestIdMiddleware
from dnd_dm_assistant.api.routes.player_rooms import public_player_room_router
from dnd_dm_assistant.config import Settings, get_settings
from dnd_dm_assistant.infrastructure.database import create_database_engine


def _default_static_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "frontend" / "dist"


def create_player_gateway(
    settings: Settings | None = None,
    *,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create the LAN-facing app with no DM routes or model integrations."""

    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(app_settings.database_url)
        app.state.database_engine = engine
        yield
        engine.dispose()

    app = FastAPI(
        title="Local D&D Player Gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = app_settings
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    @app.middleware("http")
    async def player_security_headers(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith(app_settings.api_prefix):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get(f"{app_settings.api_prefix}/health")
    def gateway_health() -> dict[str, str]:
        return {"status": "ok", "service": "player-gateway"}

    app.include_router(public_player_room_router, prefix=app_settings.api_prefix)

    @app.api_route(
        f"{app_settings.api_prefix}/{{unmatched_path:path}}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def reject_non_player_api(unmatched_path: str) -> None:
        del unmatched_path
        raise HTTPException(status_code=404, detail="Not Found")

    built_frontend = static_dir or _default_static_dir()
    if built_frontend.is_dir():
        app.mount("/", StaticFiles(directory=built_frontend, html=True), name="player-frontend")
    else:
        message = (
            "玩家前端尚未构建。请从项目根目录运行 "
            "npm --prefix frontend run build，或使用 ./scripts/player-gateway.sh。"
        )

        @app.get("/", response_class=HTMLResponse)
        def missing_frontend() -> str:
            return f"<h1>Local D&amp;D Player Gateway</h1><p>{message}</p>"

    return app


app = create_player_gateway()
