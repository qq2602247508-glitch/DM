from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from dnd_dm_assistant.api.dependencies import get_content_ir_runtime_service
from dnd_dm_assistant.api.schemas import ContentIRRuntimeRequest
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict

router = APIRouter(prefix="/campaigns/{campaign_id}/content-ir", tags=["content-ir-runtime"])


def _safe_call(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runtime/preview")
def preview_content_runtime(
    campaign_id: str,
    body: ContentIRRuntimeRequest,
    service: Annotated[ContentIRRuntimeService, Depends(get_content_ir_runtime_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.preview(campaign_id, body.model_dump(mode="json")))


@router.post("/runtime/confirm")
def confirm_content_runtime(
    campaign_id: str,
    body: ContentIRRuntimeRequest,
    service: Annotated[ContentIRRuntimeService, Depends(get_content_ir_runtime_service)],
) -> dict[str, Any]:
    if not body.preview_token or not body.idempotency_key:
        raise HTTPException(status_code=422, detail="preview_token and idempotency_key required")
    return _safe_call(lambda: service.confirm(campaign_id, body.model_dump(mode="json")))
