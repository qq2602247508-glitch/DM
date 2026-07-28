from __future__ import annotations

from typing import cast

from fastapi import Request
from sqlalchemy.engine import Engine

from dnd_dm_assistant.application.agent import AgentOrchestrator
from dnd_dm_assistant.application.campaigns import CampaignService
from dnd_dm_assistant.application.character_catalog import CharacterCatalog
from dnd_dm_assistant.application.health import HealthService
from dnd_dm_assistant.application.player_rules_search import PlayerRulesSearch
from dnd_dm_assistant.application.reliability import ReliabilityService
from dnd_dm_assistant.application.world_generation import WorldGenerationService
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database.advancement_service import (
    AdvancementService,
)
from dnd_dm_assistant.infrastructure.database.agent_service import (
    SqlAlchemyAgentPersistence,
)
from dnd_dm_assistant.infrastructure.database.campaign_service import (
    SqlAlchemyCampaignStateGateway,
)
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.encounter_service import EncounterAdjustmentService
from dnd_dm_assistant.infrastructure.database.exploration_service import ExplorationService
from dnd_dm_assistant.infrastructure.database.narrative_service import NarrativeService
from dnd_dm_assistant.infrastructure.database.player_room_service import PlayerRoomService
from dnd_dm_assistant.infrastructure.database.player_service import PlayerService
from dnd_dm_assistant.infrastructure.database.prep_import_service import PrepImportService
from dnd_dm_assistant.infrastructure.database.rest_service import RestService
from dnd_dm_assistant.infrastructure.database.session_checkpoint_service import (
    SessionCheckpointService,
)
from dnd_dm_assistant.infrastructure.database.site_service import SiteService
from dnd_dm_assistant.infrastructure.database.spell_economy_service import SpellEconomyService
from dnd_dm_assistant.infrastructure.database.world_service import WorldService
from dnd_dm_assistant.integrations.runtime import RuntimeIntegrations


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_health_service(request: Request) -> HealthService:
    return HealthService(cast(Engine, request.app.state.database_engine))


def get_reliability_service(request: Request) -> ReliabilityService:
    return ReliabilityService(
        cast(Engine, request.app.state.database_engine), get_app_settings(request)
    )


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


def get_site_service(request: Request) -> SiteService:
    return SiteService(cast(Engine, request.app.state.database_engine))


def get_exploration_service(request: Request) -> ExplorationService:
    return ExplorationService(cast(Engine, request.app.state.database_engine))


def get_encounter_adjustment_service(request: Request) -> EncounterAdjustmentService:
    return EncounterAdjustmentService(cast(Engine, request.app.state.database_engine))


def get_combat_engine_service(request: Request) -> CombatEngineService:
    return CombatEngineService(cast(Engine, request.app.state.database_engine))


def get_rest_service(request: Request) -> RestService:
    return RestService(cast(Engine, request.app.state.database_engine))


def get_session_checkpoint_service(request: Request) -> SessionCheckpointService:
    return SessionCheckpointService(cast(Engine, request.app.state.database_engine))


def get_spell_economy_service(request: Request) -> SpellEconomyService:
    return SpellEconomyService(cast(Engine, request.app.state.database_engine))


def get_narrative_service(request: Request) -> NarrativeService:
    return NarrativeService(cast(Engine, request.app.state.database_engine))


def get_character_catalog(request: Request) -> CharacterCatalog:
    settings = get_app_settings(request)
    return CharacterCatalog(settings.rag_corpus_json_root)


def get_advancement_service(request: Request) -> AdvancementService:
    return AdvancementService(
        cast(Engine, request.app.state.database_engine),
        get_character_catalog(request),
    )


def get_world_generation_service(request: Request) -> WorldGenerationService:
    return WorldGenerationService(get_runtime_integrations(request))


def get_player_service(request: Request) -> PlayerService:
    return PlayerService(cast(Engine, request.app.state.database_engine))


def get_player_room_service(request: Request) -> PlayerRoomService:
    return PlayerRoomService(cast(Engine, request.app.state.database_engine))


def get_prep_import_service(request: Request) -> PrepImportService:
    return PrepImportService(cast(Engine, request.app.state.database_engine))


def get_player_rules_search(request: Request) -> PlayerRulesSearch:
    return PlayerRulesSearch(get_app_settings(request).rag_corpus_json_root)
