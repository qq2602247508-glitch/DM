from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from dnd_dm_assistant.api.dependencies import get_prep_import_service
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.domain.prep_draft import (
    PrepDraftValidationRequest,
    PrepDraftValidationResponse,
    PrepImportConfirmRequest,
    PrepImportConfirmResponse,
    PrepImportPreviewResponse,
)
from dnd_dm_assistant.infrastructure.database.prep_import_service import PrepImportService

router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["preparation-imports"])


def _safe_call(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Preparation import conflicted with current campaign state",
        ) from exc


@router.post("/prep-drafts/validate", response_model=PrepDraftValidationResponse)
def validate_prep_draft(
    campaign_id: str,
    body: PrepDraftValidationRequest,
    service: Annotated[PrepImportService, Depends(get_prep_import_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.validate(campaign_id, body.draft, body.duplicate_strategy)
    )


@router.post("/prep-imports/preview", response_model=PrepImportPreviewResponse)
def preview_prep_import(
    campaign_id: str,
    body: PrepDraftValidationRequest,
    service: Annotated[PrepImportService, Depends(get_prep_import_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.preview(campaign_id, body.draft, body.duplicate_strategy)
    )


@router.post(
    "/prep-imports/confirm",
    response_model=PrepImportConfirmResponse,
    status_code=status.HTTP_201_CREATED,
)
def confirm_prep_import(
    campaign_id: str,
    body: PrepImportConfirmRequest,
    service: Annotated[PrepImportService, Depends(get_prep_import_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.confirm(
            campaign_id,
            body.draft,
            body.duplicate_strategy,
            preview_token=body.preview_token,
            idempotency_key=body.idempotency_key,
        )
    )

