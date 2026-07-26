from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from dnd_dm_assistant.api.dependencies import get_rest_service
from dnd_dm_assistant.api.schemas import RestConfirmRequest, RestPreviewRequest
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.rest_service import RestService

router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["rests-and-resources"])


def _safe_call(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/resources")
def list_resources(
    campaign_id: str,
    service: Annotated[RestService, Depends(get_rest_service)],
    character_id: str | None = Query(default=None),
) -> dict[str, Any]:
    return {
        "items": _safe_call(
            lambda: service.list_resources(campaign_id, character_id=character_id)
        )
    }


@router.post("/rests/preview")
def preview_rest(
    campaign_id: str,
    body: RestPreviewRequest,
    service: Annotated[RestService, Depends(get_rest_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.preview(campaign_id, body.model_dump(mode="json"))
    )


@router.post("/rests/confirm")
def confirm_rest(
    campaign_id: str,
    body: RestConfirmRequest,
    service: Annotated[RestService, Depends(get_rest_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.confirm(campaign_id, body.model_dump(mode="json"))
    )
