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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=40, ge=1, le=100),
    class_name: str | None = Query(default=None, max_length=100),
    spell_level: str | None = Query(default=None, max_length=10),
    monster_type: str | None = Query(default=None, max_length=100),
    challenge_rating: str | None = Query(default=None, max_length=20),
    slot: str | None = Query(default=None, max_length=50),
    rarity: str | None = Query(default=None, max_length=50),
    category: str | None = Query(default=None, max_length=50),
    attunement: str | None = Query(default=None, max_length=50),
    edition: str | None = Query(default=None, max_length=50),
    content_type: str | None = Query(default=None, max_length=50),
    feature_kind: str | None = Query(default=None, max_length=50),
    item_function: str | None = Query(default=None, max_length=50),
    item_kind: str | None = Query(default=None, max_length=50),
    content_pack: str | None = Query(default=None, max_length=50),
    include_legacy: bool = Query(default=False),
    sort_by: str = Query(
        default="default",
        pattern="^(default|name|level|strength|class|category)$",
    ),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    return _call(
        lambda: service.catalog(
            campaign_id,
            entry_type=entry_type,
            source_kind=source_kind,
            text=text,
            page=page,
            page_size=page_size,
            filters={
                key: value
                for key, value in {
                    "class_name": class_name,
                    "spell_level": spell_level,
                    "monster_type": monster_type,
                    "challenge_rating": challenge_rating,
                    "slot": slot,
                    "rarity": rarity,
                    "category": category,
                    "attunement": attunement,
                    "edition": edition,
                    "content_type": content_type,
                    "feature_kind": feature_kind,
                    "item_function": item_function,
                    "item_kind": item_kind,
                    "content_pack_key": content_pack,
                }.items()
                if value
            },
            include_legacy=include_legacy,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


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
    return _call(lambda: CompendiumService.generate_preview(body.model_dump(mode="json")))


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
