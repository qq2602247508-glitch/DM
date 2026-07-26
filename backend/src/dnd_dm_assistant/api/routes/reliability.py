from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from dnd_dm_assistant.api.dependencies import get_reliability_service, get_runtime_integrations
from dnd_dm_assistant.api.schemas import (
    BackupCreateRequest,
    HouseRuleOverrideRequest,
    RestoreConfirmRequest,
    SafeModeRequest,
)
from dnd_dm_assistant.application.reliability import ReliabilityError, ReliabilityService
from dnd_dm_assistant.integrations.runtime import RuntimeIntegrations

router = APIRouter(prefix="/system", tags=["reliability"])


def _service_call(fn: Any) -> Any:
    try:
        return fn()
    except ReliabilityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


@router.get("/diagnostics")
async def diagnostics(
    service: Annotated[ReliabilityService, Depends(get_reliability_service)],
    runtime: Annotated[RuntimeIntegrations, Depends(get_runtime_integrations)],
) -> dict[str, Any]:
    runtime_index = await runtime.status()
    index = {
        "state": runtime_index.state,
        "available": runtime_index.available,
        "reason": runtime_index.reason,
        "points_count": runtime_index.points_count,
    }
    models = (await runtime.model_status()).model_dump(mode="json")
    return service.diagnostics(index, models)


@router.get("/safe-mode")
def safe_mode(
    service: Annotated[ReliabilityService, Depends(get_reliability_service)],
) -> dict[str, Any]:
    return {"enabled": service.is_read_only()}


@router.post("/safe-mode")
def set_safe_mode(
    body: SafeModeRequest,
    request: Request,
    service: Annotated[ReliabilityService, Depends(get_reliability_service)],
) -> dict[str, Any]:
    return _service_call(
        lambda: service.set_read_only(body.enabled, body.reason or "", _request_id(request))
    )


@router.get("/recovery-points")
def recovery_points(
    service: Annotated[ReliabilityService, Depends(get_reliability_service)],
) -> dict[str, Any]:
    return {"items": service.list_recovery_points()}


@router.post("/recovery-points")
def create_recovery_point(
    body: BackupCreateRequest,
    request: Request,
    service: Annotated[ReliabilityService, Depends(get_reliability_service)],
) -> dict[str, Any]:
    return _service_call(lambda: service.create_backup(body.label, _request_id(request)))


@router.post("/recovery-points/{point_id}/preview-restore")
def preview_restore(
    point_id: str, service: Annotated[ReliabilityService, Depends(get_reliability_service)]
) -> dict[str, Any]:
    return _service_call(lambda: service.preview_restore(point_id))


@router.post("/recovery-points/{point_id}/restore")
def restore(
    point_id: str,
    body: RestoreConfirmRequest,
    request: Request,
    service: Annotated[ReliabilityService, Depends(get_reliability_service)],
) -> dict[str, Any]:
    return _service_call(
        lambda: service.confirm_restore(
            point_id, body.confirm_token, body.confirmation, _request_id(request)
        )
    )


@router.get("/audit")
def audit(
    service: Annotated[ReliabilityService, Depends(get_reliability_service)],
    campaign_id: str | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return service.audit(campaign_id, limit, offset)


@router.get("/campaigns/{campaign_id}/house-rules")
def house_rules(
    campaign_id: str, service: Annotated[ReliabilityService, Depends(get_reliability_service)]
) -> dict[str, Any]:
    return {"items": service.list_house_rules(campaign_id)}


@router.put("/campaigns/{campaign_id}/house-rules")
def save_house_rule(
    campaign_id: str,
    body: HouseRuleOverrideRequest,
    request: Request,
    service: Annotated[ReliabilityService, Depends(get_reliability_service)],
) -> dict[str, Any]:
    return _service_call(
        lambda: service.save_house_rule(campaign_id, body.model_dump(), _request_id(request))
    )
