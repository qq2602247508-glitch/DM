from __future__ import annotations

from typing import cast

from fastapi import Request
from sqlalchemy.engine import Engine

from dnd_dm_assistant.application.agent import AgentOrchestrator
from dnd_dm_assistant.application.campaigns import CampaignService
from dnd_dm_assistant.application.health import HealthService
from dnd_dm_assistant.application.world_generation import WorldGenerationService
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database.agent_service import (
    SqlAlchemyAgentPersistence,
)
from dnd_dm_assistant.infrastructure.database.campaign_service import (
    SqlAlchemyCampaignStateGateway,
)
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.encounter_service import EncounterAdjustmentService
from dnd_dm_assistant.infrastructure.database.rest_service import RestService
from dnd_dm_assistant.infrastructure.database.world_service import WorldService
from dnd_dm_assistant.infrastructure.database.exploration_service import ExplorationService
from dnd_dm_assistant.integrations.runtime import RuntimeIntegrations


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_health_service(request: Request) -> HealthService:
    return HealthService(cast(Engine, request.app.state.database_engine))


def get_runtime_integrations(request: Request) -> RuntimeIntegrations:
    return cast(RuntimeIntegrations, request.app.state.runtime_integrations)


def get_campaign_service(request: Request) -> CampaignService:
    gateway = SqlAlchemyCampaignStateGateway(cast(Engine, request.app.state.database_engine))
    return CampaignService(gateway)


def get_agent_persistence(request: Request) -> SqlAlchemyAgentPersistence:
    return SqlAlchemyAgentPersistence(cast(Engine, request.app.state.database_engine))


def get_agent_orchestrator(request: Request) -> AgentOrchestrator:
    runtime = get_runtime_integrations(request)
    engine = cast(Engine, request.app.state.database_engine)
    state = SqlAlchemyCampaignStateGateway(engine)
    persistence = SqlAlchemyAgentPersistence(engine)
    return AgentOrchestrator(
        planner=runtime.agent_planner,
        hint_generator=runtime.dm_hint_generator,
        knowledge=runtime,
        state=state,
        persistence=persistence,
    )


def get_world_service(request: Request) -> WorldService:
    return WorldService(cast(Engine, request.app.state.database_engine))


def get_exploration_service(request: Request) -> ExplorationService:
    return ExplorationService(cast(Engine, request.app.state.database_engine))


def get_encounter_adjustment_service(request: Request) -> EncounterAdjustmentService:
    return EncounterAdjustmentService(cast(Engine, request.app.state.database_engine))


def get_combat_engine_service(request: Request) -> CombatEngineService:
    return CombatEngineService(cast(Engine, request.app.state.database_engine))


def get_rest_service(request: Request) -> RestService:
    return RestService(cast(Engine, request.app.state.database_engine))


def get_world_generation_service(request: Request) -> WorldGenerationService:
    return WorldGenerationService(get_runtime_integrations(request))
