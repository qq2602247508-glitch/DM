from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from dnd_dm_assistant.api.dependencies import get_compendium_service
from dnd_dm_assistant.api.schemas import (
    CompendiumEntryCreate,
    CompendiumGenerateConfirmRequest,
    CompendiumGenerateRequest,
    CompendiumInstantiateRequest,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.infrastructure.database.compendium_service import CompendiumService

router = APIRouter(prefix="/campaigns/{campaign_id}/compendium", tags=["compendium"])


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_entries(
    campaign_id: str,
    service: Annotated[CompendiumService, Depends(get_compendium_service)],
    entry_type: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    text: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    return {
        "items": _call(
            lambda: service.list(
                campaign_id,
                entry_type=entry_type,
                source_kind=source_kind,
                text=text,
            )
        )
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_entry(
    campaign_id: str,
    body: CompendiumEntryCreate,
    request: Request,
    service: Annotated[CompendiumService, Depends(get_compendium_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.create(
            campaign_id,
            body.model_dump(mode="json"),
            request_id=_request_id(request),
        )
    )


@router.post("/generate/preview")
def generate_preview(body: CompendiumGenerateRequest) -> dict[str, Any]:
    return _call(
        lambda: CompendiumService.generate_preview(body.model_dump(mode="json"))
    )


@router.post("/generate/confirm", status_code=status.HTTP_201_CREATED)
def confirm_generated(
    campaign_id: str,
    body: CompendiumGenerateConfirmRequest,
    request: Request,
    service: Annotated[CompendiumService, Depends(get_compendium_service)],
) -> dict[str, Any]:
    return {
        "items": _call(
            lambda: service.confirm_generated(
                campaign_id,
                body.preview,
                request_id=_request_id(request),
            )
        )
    }


@router.post("/{entry_id}/instantiate", status_code=status.HTTP_201_CREATED)
def instantiate_entry(
    campaign_id: str,
    entry_id: str,
    body: CompendiumInstantiateRequest,
    request: Request,
    service: Annotated[CompendiumService, Depends(get_compendium_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.instantiate(
            campaign_id,
            entry_id,
            body.model_dump(mode="json"),
            request_id=_request_id(request),
        )
    )
