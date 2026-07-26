from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from dnd_dm_assistant.api.dependencies import (
    get_app_settings,
    get_health_service,
    get_runtime_integrations,
)
from dnd_dm_assistant.api.schemas import HealthResponse, ReadinessResponse
from dnd_dm_assistant.application.health import HealthService
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.runtime_status import RuntimeModelStatus
from dnd_dm_assistant.integrations.runtime import RuntimeIntegrations

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(
    service: Annotated[HealthService, Depends(get_health_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> HealthResponse:
    status = service.check()
    return HealthResponse(
        status=status.status,
        database=status.database,
        environment=settings.environment,
    )


@router.get("/runtime/models", response_model=RuntimeModelStatus)
async def runtime_models(
    runtime: Annotated[RuntimeIntegrations, Depends(get_runtime_integrations)],
) -> RuntimeModelStatus:
    return await runtime.model_status()


@router.get("/readiness", response_model=ReadinessResponse)
async def readiness(
    service: Annotated[HealthService, Depends(get_health_service)],
    runtime: Annotated[RuntimeIntegrations, Depends(get_runtime_integrations)],
) -> ReadinessResponse:
    database = service.check()
    index = await runtime.status()
    models = await runtime.model_status()
    required_models_ready = all(
        item.installed for item in models.models if item.configured
    )
    return ReadinessResponse(
        ready=(
            database.status == "ok"
            and index.available
            and models.ollama_available
            and required_models_ready
        ),
        database=database.database,
        knowledge_index=index.state,
        models=models,
    )
