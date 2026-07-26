from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from dnd_dm_assistant.api.dependencies import get_encounter_adjustment_service
from dnd_dm_assistant.api.schemas import (
    EncounterAdjustmentCreate,
    EncounterAdjustmentPatch,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.encounters import EncounterAdjustmentDraft
from dnd_dm_assistant.infrastructure.database.encounter_service import (
    EncounterAdjustmentService,
)

router = APIRouter(prefix="/campaigns/{campaign_id}/encounter-adjustments", tags=["encounters"])


def _version(if_match: str | None, explicit: int | None = None) -> int:
    header_version: int | None = None
    if if_match:
        token = if_match.strip().removeprefix("W/").strip('"')
        try:
            header_version = int(token)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid If-Match version") from None
    if explicit is not None and header_version is not None and explicit != header_version:
        raise HTTPException(status_code=400, detail="If-Match and body version disagree")
    version = explicit if explicit is not None else header_version
    if version is None:
        raise HTTPException(status_code=428, detail="If-Match or body version is required")
    return version


def _safe_call(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_encounter_adjustments(
    campaign_id: str,
    service: Annotated[EncounterAdjustmentService, Depends(get_encounter_adjustment_service)],
    scene_id: str | None = None,
    proposal_status: str | None = Query(default=None, alias="status"),
) -> dict[str, Any]:
    return {
        "items": _safe_call(
            lambda: service.list(
                campaign_id,
                scene_id=scene_id,
                status=proposal_status,
            )
        )
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_encounter_adjustment(
    campaign_id: str,
    body: EncounterAdjustmentCreate,
    service: Annotated[EncounterAdjustmentService, Depends(get_encounter_adjustment_service)],
) -> dict[str, Any]:
    draft = EncounterAdjustmentDraft.model_validate(
        {
            **body.model_dump(exclude={"scene_id", "combat_id", "source_event_id", "operations"}),
            "operations": tuple(body.operations),
        }
    )
    return _safe_call(
        lambda: service.create(
            campaign_id,
            scene_id=body.scene_id,
            combat_id=body.combat_id,
            source_event_id=body.source_event_id,
            draft=draft,
        )
    )


@router.patch("/{proposal_id}")
def patch_encounter_adjustment(
    campaign_id: str,
    proposal_id: str,
    body: EncounterAdjustmentPatch,
    service: Annotated[EncounterAdjustmentService, Depends(get_encounter_adjustment_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if not data:
        raise HTTPException(status_code=400, detail="Patch must include at least one field")
    return _safe_call(
        lambda: service.update_pending(
            campaign_id,
            proposal_id,
            data=data,
            expected_version=_version(if_match, body.version),
        )
    )


@router.post("/{proposal_id}/reject")
def reject_encounter_adjustment(
    campaign_id: str,
    proposal_id: str,
    service: Annotated[EncounterAdjustmentService, Depends(get_encounter_adjustment_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.reject(
            campaign_id,
            proposal_id,
            expected_version=_version(if_match),
        )
    )


@router.post("/{proposal_id}/apply")
def apply_encounter_adjustment(
    campaign_id: str,
    proposal_id: str,
    request: Request,
    service: Annotated[EncounterAdjustmentService, Depends(get_encounter_adjustment_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.apply(
            campaign_id,
            proposal_id,
            expected_version=_version(if_match),
            idempotency_key=request_id,
        )
    )


@router.post("/{proposal_id}/revert")
def revert_encounter_adjustment(
    campaign_id: str,
    proposal_id: str,
    request: Request,
    service: Annotated[EncounterAdjustmentService, Depends(get_encounter_adjustment_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.revert(
            campaign_id,
            proposal_id,
            expected_version=_version(if_match),
            idempotency_key=request_id,
        )
    )
