# ruff: noqa: E501
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from dnd_dm_assistant.api.dependencies import get_spell_economy_service
from dnd_dm_assistant.api.schemas import (
    CommerceRequest,
    CurrencySplitRequest,
    EquipmentInstanceCreate,
    EquipmentOperationRequest,
    KnownSpellCreate,
    ShopInventoryCreate,
    SpellCastRequest,
    WalletCreate,
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


@router.get("/characters/{character_id}/assets")
def character_assets(
    campaign_id: str,
    character_id: str,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.character_assets(campaign_id, character_id))


@router.get("/shop-inventory")
def shop_inventory(
    campaign_id: str,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return {"items": call(lambda: service.shop_inventory(campaign_id))}


@router.post("/characters/assets/spells", status_code=201)
def create_known_spell(
    campaign_id: str,
    body: KnownSpellCreate,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.create_known_spell(campaign_id, body.model_dump()))


@router.post("/characters/assets/equipment", status_code=201)
def create_equipment(
    campaign_id: str,
    body: EquipmentInstanceCreate,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.create_equipment(campaign_id, body.model_dump()))


@router.post("/characters/assets/wallets", status_code=201)
def create_wallet(
    campaign_id: str,
    body: WalletCreate,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.create_wallet(campaign_id, body.model_dump()))


@router.post("/shop-inventory", status_code=201)
def create_shop_inventory(
    campaign_id: str,
    body: ShopInventoryCreate,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.create_shop_inventory(campaign_id, body.model_dump()))


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


@router.post("/equipment/confirm")
def equipment_confirm(
    campaign_id: str,
    body: EquipmentOperationRequest,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    if not body.preview_token or not body.idempotency_key:
        raise HTTPException(422, "preview_token and idempotency_key required")
    return call(lambda: service.equipment_confirm(campaign_id, body.model_dump()))


@router.post("/commerce/preview")
def commerce_preview(
    campaign_id: str,
    body: CommerceRequest,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.commerce_preview(campaign_id, body.model_dump()))


@router.post("/commerce/confirm")
def commerce_confirm(
    campaign_id: str,
    body: CommerceRequest,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    if not body.preview_token or not body.idempotency_key:
        raise HTTPException(422, "preview_token and idempotency_key required")
    return call(lambda: service.commerce_confirm(campaign_id, body.model_dump()))


@router.post("/currency/split/preview")
def split_preview(
    campaign_id: str,
    body: CurrencySplitRequest,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    return call(lambda: service.split_preview(campaign_id, body.model_dump()))


@router.post("/currency/split/confirm")
def split_confirm(
    campaign_id: str,
    body: CurrencySplitRequest,
    service: Annotated[SpellEconomyService, Depends(get_spell_economy_service)],
):
    if not body.preview_token or not body.idempotency_key:
        raise HTTPException(422, "preview_token and idempotency_key required")
    return call(lambda: service.split_confirm(campaign_id, body.model_dump()))
