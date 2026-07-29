from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from dnd_dm_assistant.api.dependencies import get_merchant_service
from dnd_dm_assistant.api.schemas import MerchantConfirmRequest, MerchantGenerateRequest
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.infrastructure.database.merchant_service import MerchantService

router = APIRouter(prefix="/campaigns/{campaign_id}/merchants", tags=["merchants"])


def _call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_merchants(
    campaign_id: str,
    service: Annotated[MerchantService, Depends(get_merchant_service)],
) -> dict[str, Any]:
    return {"items": _call(lambda: service.list(campaign_id))}


@router.post("/generate/preview")
def preview_merchant(
    campaign_id: str,
    body: MerchantGenerateRequest,
    service: Annotated[MerchantService, Depends(get_merchant_service)],
) -> dict[str, Any]:
    return _call(lambda: service.preview(campaign_id, body.model_dump(mode="json")))


@router.post("/generate/confirm", status_code=status.HTTP_201_CREATED)
def confirm_merchant(
    campaign_id: str,
    body: MerchantConfirmRequest,
    request: Request,
    service: Annotated[MerchantService, Depends(get_merchant_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.confirm(
            campaign_id,
            body.preview,
            request_id=str(getattr(request.state, "request_id", "unknown")),
        )
    )
