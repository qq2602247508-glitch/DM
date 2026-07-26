from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from dnd_dm_assistant.api.dependencies import get_narrative_service
from dnd_dm_assistant.api.schemas import NarrativeTransactionRequest
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.narrative_service import NarrativeService

router = APIRouter(
    prefix="/campaigns/{campaign_id}/narrative", tags=["narrative-transactions"]
)


def _call(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/preview")
def preview(
    campaign_id: str,
    body: NarrativeTransactionRequest,
    service: Annotated[NarrativeService, Depends(get_narrative_service)],
) -> dict[str, Any]:
    return _call(lambda: service.preview(campaign_id, body.model_dump(mode="json")))


@router.post("/confirm")
def confirm(
    campaign_id: str,
    body: NarrativeTransactionRequest,
    service: Annotated[NarrativeService, Depends(get_narrative_service)],
) -> dict[str, Any]:
    return _call(lambda: service.confirm(campaign_id, body.model_dump(mode="json")))
