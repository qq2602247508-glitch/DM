from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from dnd_dm_assistant.api.dependencies import get_spell_economy_service
from dnd_dm_assistant.api.schemas import (
    CommerceRequest,
    EquipmentOperationRequest,
    SpellCastRequest,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.spell_economy_service import SpellEconomyService

router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["spells-equipment-economy"])


def call(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except VersionConflict as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/spells/cast/preview")
def spell_preview(
    campaign_id: str,
    body: SpellCastRequest,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.spell_preview(campaign_id, body.model_dump()))


@router.post("/spells/cast/confirm")
def spell_confirm(
    campaign_id: str,
    body: SpellCastRequest,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    if not body.preview_token or not body.idempotency_key:
        raise HTTPException(422, "preview_token and idempotency_key required")
    return call(lambda: service.spell_confirm(campaign_id, body.model_dump()))


@router.post("/equipment/preview")
def equipment_preview(
    campaign_id: str,
    body: EquipmentOperationRequest,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.equipment_preview(campaign_id, body.model_dump()))


@router.post("/commerce/preview")
def commerce_preview(
    campaign_id: str,
    body: CommerceRequest,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.commerce_preview(campaign_id, body.model_dump()))
