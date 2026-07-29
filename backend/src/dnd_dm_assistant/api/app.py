from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dnd_dm_assistant.api.errors import install_error_handlers
from dnd_dm_assistant.api.middleware import ReadOnlySafeModeMiddleware, RequestIdMiddleware
from dnd_dm_assistant.api.routes.advancement import router as advancement_router
from dnd_dm_assistant.api.routes.assistant import router as assistant_router
from dnd_dm_assistant.api.routes.campaigns import router as campaigns_router
from dnd_dm_assistant.api.routes.combat_engine import router as combat_engine_router
from dnd_dm_assistant.api.routes.compendium import router as compendium_router
from dnd_dm_assistant.api.routes.encounters import router as encounters_router
from dnd_dm_assistant.api.routes.health import router as health_router
from dnd_dm_assistant.api.routes.knowledge import router as knowledge_router
from dnd_dm_assistant.api.routes.merchants import router as merchants_router
from dnd_dm_assistant.api.routes.narrative import router as narrative_router
from dnd_dm_assistant.api.routes.player import dm_router as player_dm_router
from dnd_dm_assistant.api.routes.player import player_router
from dnd_dm_assistant.api.routes.player_rooms import (
    admin_player_room_router,
    public_player_room_router,
)
from dnd_dm_assistant.api.routes.prep_imports import router as prep_imports_router
from dnd_dm_assistant.api.routes.realtime import router as realtime_router
from dnd_dm_assistant.api.routes.reliability import router as reliability_router
from dnd_dm_assistant.api.routes.rests import router as rests_router
from dnd_dm_assistant.api.routes.session_checkpoints import router as session_checkpoints_router
from dnd_dm_assistant.api.routes.spells_economy import router as spells_economy_router
from dnd_dm_assistant.api.routes.world import router as world_router
from dnd_dm_assistant.config import Settings, get_settings
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.integrations.runtime import RuntimeIntegrations


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(app_settings.database_url)
        app.state.database_engine = engine
        app.state.runtime_integrations = RuntimeIntegrations(app_settings)
        yield
        await app.state.runtime_integrations.close()
        engine.dispose()

    app = FastAPI(
        title="Local D&D DM Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(ReadOnlySafeModeMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[app_settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "If-Match", "X-Request-ID"],
    )
    install_error_handlers(app)
    app.include_router(health_router, prefix=app_settings.api_prefix)
    app.include_router(reliability_router, prefix=app_settings.api_prefix)
    app.include_router(realtime_router, prefix=app_settings.api_prefix)
    app.include_router(advancement_router, prefix=app_settings.api_prefix)
    app.include_router(knowledge_router, prefix=app_settings.api_prefix)
    app.include_router(campaigns_router, prefix=app_settings.api_prefix)
    app.include_router(combat_engine_router, prefix=app_settings.api_prefix)
    app.include_router(compendium_router, prefix=app_settings.api_prefix)
    app.include_router(merchants_router, prefix=app_settings.api_prefix)
    app.include_router(encounters_router, prefix=app_settings.api_prefix)
    app.include_router(rests_router, prefix=app_settings.api_prefix)
    app.include_router(session_checkpoints_router, prefix=app_settings.api_prefix)
    app.include_router(spells_economy_router, prefix=app_settings.api_prefix)
    app.include_router(narrative_router, prefix=app_settings.api_prefix)
    app.include_router(assistant_router, prefix=app_settings.api_prefix)
    app.include_router(world_router, prefix=app_settings.api_prefix)
    app.include_router(prep_imports_router, prefix=app_settings.api_prefix)
    app.include_router(player_router, prefix=app_settings.api_prefix)
    app.include_router(player_dm_router, prefix=app_settings.api_prefix)
    app.include_router(admin_player_room_router, prefix=app_settings.api_prefix)
    app.include_router(public_player_room_router, prefix=app_settings.api_prefix)
    return app


app = create_app()
