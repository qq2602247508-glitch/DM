from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from dnd_dm_assistant.api.dependencies import get_rules_kernel_service
from dnd_dm_assistant.application.rules_kernel import RulesKernelService
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict

router = APIRouter(prefix="/rules-kernel", tags=["rules-kernel"])


def _safe_call(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/preview")
def preview_rules_kernel(
    body: dict[str, Any],
    service: Annotated[RulesKernelService, Depends(get_rules_kernel_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.preview(body))


@router.post("/confirm")
def confirm_rules_kernel(
    body: dict[str, Any],
    service: Annotated[RulesKernelService, Depends(get_rules_kernel_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.confirm(body))


@router.get("/results/{command_id}")
def get_rules_kernel_result(
    campaign_id: str,
    command_id: str,
    service: Annotated[RulesKernelService, Depends(get_rules_kernel_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.result(campaign_id, command_id))


@router.post("/choices/{window_id}/resolve")
def resolve_rules_kernel_choice(
    campaign_id: str,
    window_id: str,
    body: dict[str, Any],
    service: Annotated[RulesKernelService, Depends(get_rules_kernel_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.resolve_choice(campaign_id, window_id, body))


@router.post("/adjudications/{adjudication_id}/resolve")
def resolve_rules_kernel_adjudication(
    campaign_id: str,
    adjudication_id: str,
    body: dict[str, Any],
    service: Annotated[RulesKernelService, Depends(get_rules_kernel_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.resolve_adjudication(campaign_id, adjudication_id, body))


@router.get("/scene-deltas")
def get_rules_kernel_scene_deltas(
    campaign_id: str,
    service: Annotated[RulesKernelService, Depends(get_rules_kernel_service)],
    scene_id: str | None = None,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.scene_deltas(
            campaign_id,
            scene_id=scene_id,
            after=after,
            limit=limit,
        )
    )


@router.post("/scene-query")
def query_rules_kernel_scene(
    campaign_id: str,
    body: dict[str, Any],
    service: Annotated[RulesKernelService, Depends(get_rules_kernel_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.query_scene(campaign_id, body))
