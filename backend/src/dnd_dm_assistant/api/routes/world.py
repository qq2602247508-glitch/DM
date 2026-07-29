from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError

from dnd_dm_assistant.api.dependencies import (
    get_campaign_service,
    get_exploration_service,
    get_site_service,
    get_world_generation_service,
    get_world_service,
)
from dnd_dm_assistant.api.schemas import (
    ExplorationConfirmRequest,
    ExplorationPreviewRequest,
    ItemPickupRequest,
    LocationGenerationConfirmRequest,
    LocationGenerationRequest,
    MonsterCreate,
    NPCGenerationRequest,
    SceneCombatStartRequest,
    SceneCreate,
    SceneGridCreate,
    SceneObjectCreate,
    SceneParticipantCreate,
    SceneTokenCreate,
    SiteGenerationConfirmRequest,
    SiteGenerationRequest,
    SiteRoomVisibilityRequest,
    TravelConfirmRequest,
    TravelPreviewRequest,
    WorldItemCreate,
)
from dnd_dm_assistant.application.campaigns import CampaignService, NotFoundError
from dnd_dm_assistant.application.rag import RuntimeUnavailableError
from dnd_dm_assistant.application.world_generation import WorldGenerationService
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.world import LocationGenerationPreview, NPCGenerationPreview
from dnd_dm_assistant.infrastructure.database.exploration_service import ExplorationService
from dnd_dm_assistant.infrastructure.database.site_service import SiteService
from dnd_dm_assistant.infrastructure.database.world_service import WorldService

router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["world"])


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _safe_call(fn: Any) -> Any:
    try:
        return fn()
    except (NotFoundError, StateNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=422, detail="World constraints were violated") from exc


@router.post("/generate/npc", response_model=NPCGenerationPreview)
async def generate_npc(
    campaign_id: str,
    body: NPCGenerationRequest,
    campaign_service: Annotated[CampaignService, Depends(get_campaign_service)],
    generator: Annotated[WorldGenerationService, Depends(get_world_generation_service)],
) -> NPCGenerationPreview:
    campaign = _safe_call(lambda: campaign_service.get("campaign", campaign_id))
    try:
        return await generator.generate_npc(
            campaign=campaign,
            mode=body.mode,
            brief=body.brief,
            answers=body.answers,
        )
    except RuntimeUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/generate/location", response_model=LocationGenerationPreview)
async def generate_location(
    campaign_id: str,
    body: LocationGenerationRequest,
    campaign_service: Annotated[CampaignService, Depends(get_campaign_service)],
    generator: Annotated[WorldGenerationService, Depends(get_world_generation_service)],
) -> LocationGenerationPreview:
    campaign = _safe_call(lambda: campaign_service.get("campaign", campaign_id))
    try:
        return await generator.generate_location(
            campaign=campaign,
            brief=body.brief,
            maximum_depth=body.maximum_depth,
            scale=body.scale,
        )
    except RuntimeUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/generate/location/confirm", status_code=status.HTTP_201_CREATED)
def confirm_location_generation(
    campaign_id: str,
    body: LocationGenerationConfirmRequest,
    request: Request,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.confirm_location_tree(
            campaign_id,
            body.preview.root,
            maximum_depth=body.preview.maximum_depth,
            request_id=_request_id(request),
        )
    )


@router.post("/sites/generate/preview")
def preview_site_generation(
    campaign_id: str,
    body: SiteGenerationRequest,
    service: Annotated[SiteService, Depends(get_site_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.preview(campaign_id, body.model_dump()))


@router.post("/sites/generate/confirm", status_code=status.HTTP_201_CREATED)
def confirm_site_generation(
    campaign_id: str,
    body: SiteGenerationConfirmRequest,
    request: Request,
    service: Annotated[SiteService, Depends(get_site_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.confirm(campaign_id, body.preview, request_id=_request_id(request))
    )


@router.get("/region-maps")
def list_region_maps(
    campaign_id: str,
    service: Annotated[SiteService, Depends(get_site_service)],
) -> dict[str, Any]:
    return {"region_maps": _safe_call(lambda: service.list_region_maps(campaign_id))}


@router.get("/sites")
def list_adventure_sites(
    campaign_id: str,
    service: Annotated[SiteService, Depends(get_site_service)],
) -> dict[str, Any]:
    return {"sites": _safe_call(lambda: service.list_sites(campaign_id))}


@router.post("/sites/repair-scene-atoms")
def repair_site_scene_atoms(
    campaign_id: str,
    service: Annotated[SiteService, Depends(get_site_service)],
) -> dict[str, int]:
    return _safe_call(lambda: service.repair_generated_scene_atoms(campaign_id))


@router.get("/sites/{site_id}")
def get_adventure_site(
    campaign_id: str,
    site_id: str,
    service: Annotated[SiteService, Depends(get_site_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.get(campaign_id, site_id))


@router.put("/sites/{site_id}/levels/{level_index}/rooms/{room_index}/visibility")
def set_site_room_visibility(
    campaign_id: str,
    site_id: str,
    level_index: int,
    room_index: int,
    body: SiteRoomVisibilityRequest,
    request: Request,
    service: Annotated[SiteService, Depends(get_site_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.set_room_visibility(
            campaign_id,
            site_id,
            level_index,
            room_index,
            visible=body.visible,
            request_id=_request_id(request),
        )
    )


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_adventure_site(
    campaign_id: str,
    site_id: str,
    request: Request,
    response: Response,
    service: Annotated[SiteService, Depends(get_site_service)],
    version: int = Query(ge=1),
) -> None:
    _safe_call(
        lambda: service.delete(
            campaign_id,
            site_id,
            expected_version=version,
            request_id=_request_id(request),
        )
    )
    response.status_code = status.HTTP_204_NO_CONTENT


@router.get("/items")
def list_items(
    campaign_id: str,
    service: Annotated[WorldService, Depends(get_world_service)],
    location_id: str | None = None,
    owner_character_id: str | None = None,
) -> dict[str, Any]:
    return {
        "items": _safe_call(
            lambda: service.list_items(
                campaign_id,
                location_id=location_id,
                owner_character_id=owner_character_id,
            )
        )
    }


@router.post("/items", status_code=status.HTTP_201_CREATED)
def create_item(
    campaign_id: str,
    body: WorldItemCreate,
    request: Request,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.create_item(
            campaign_id,
            body.model_dump(exclude_unset=True),
            request_id=_request_id(request),
        )
    )


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    campaign_id: str,
    item_id: str,
    request: Request,
    response: Response,
    service: Annotated[WorldService, Depends(get_world_service)],
    version: int = Query(ge=1),
) -> None:
    _safe_call(
        lambda: service.delete_item(
            campaign_id,
            item_id,
            expected_version=version,
            request_id=_request_id(request),
        )
    )
    response.status_code = status.HTTP_204_NO_CONTENT


@router.post("/items/{item_id}/pickup")
def pickup_item(
    campaign_id: str,
    item_id: str,
    body: ItemPickupRequest,
    request: Request,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    moved, inventory = _safe_call(
        lambda: service.pickup_item(
            campaign_id,
            item_id,
            character_id=body.character_id,
            quantity=body.quantity,
            expected_version=body.version,
            request_id=_request_id(request),
        )
    )
    return {"item": moved, "inventory": inventory}


@router.get("/characters/{character_id}/inventory")
def get_inventory(
    campaign_id: str,
    character_id: str,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.inventory(campaign_id, character_id))


@router.get("/monsters")
def list_monsters(
    campaign_id: str,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return {"items": _safe_call(lambda: service.list_monsters(campaign_id))}


@router.post("/monsters", status_code=status.HTTP_201_CREATED)
def create_monster(
    campaign_id: str,
    body: MonsterCreate,
    request: Request,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.create_monster(
            campaign_id,
            body.model_dump(exclude_unset=True),
            request_id=_request_id(request),
        )
    )


@router.get("/scenes")
def list_scenes(
    campaign_id: str,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return {"items": _safe_call(lambda: service.list_scenes(campaign_id))}


@router.post("/scenes", status_code=status.HTTP_201_CREATED)
def create_scene(
    campaign_id: str,
    body: SceneCreate,
    request: Request,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.create_scene(
            campaign_id,
            body.model_dump(exclude_unset=True),
            request_id=_request_id(request),
        )
    )


@router.get("/scenes/{scene_id}/grid")
def get_scene_grid(
    campaign_id: str,
    scene_id: str,
    service: Annotated[ExplorationService, Depends(get_exploration_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.grid(campaign_id, scene_id))


@router.post("/scenes/{scene_id}/grid", status_code=status.HTTP_201_CREATED)
def create_scene_grid(
    campaign_id: str,
    scene_id: str,
    body: SceneGridCreate,
    service: Annotated[ExplorationService, Depends(get_exploration_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.create_grid(campaign_id, scene_id, body.model_dump()))


@router.post("/scenes/{scene_id}/tokens", status_code=status.HTTP_201_CREATED)
def create_scene_token(
    campaign_id: str,
    scene_id: str,
    body: SceneTokenCreate,
    service: Annotated[ExplorationService, Depends(get_exploration_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.add_token(campaign_id, scene_id, body.model_dump()))


@router.post("/scenes/{scene_id}/objects", status_code=status.HTTP_201_CREATED)
def create_scene_object(
    campaign_id: str,
    scene_id: str,
    body: SceneObjectCreate,
    service: Annotated[ExplorationService, Depends(get_exploration_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.add_object(campaign_id, scene_id, body.model_dump()))


@router.post("/scenes/{scene_id}/exploration/preview")
def preview_exploration(
    campaign_id: str,
    scene_id: str,
    body: ExplorationPreviewRequest,
    service: Annotated[ExplorationService, Depends(get_exploration_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.preview_exploration(campaign_id, scene_id, body.model_dump()))


@router.post("/scenes/{scene_id}/exploration/confirm")
def confirm_exploration(
    campaign_id: str,
    scene_id: str,
    body: ExplorationConfirmRequest,
    service: Annotated[ExplorationService, Depends(get_exploration_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.confirm_exploration(campaign_id, scene_id, body.model_dump()))


@router.post("/travel/preview")
def preview_travel(
    campaign_id: str,
    body: TravelPreviewRequest,
    service: Annotated[ExplorationService, Depends(get_exploration_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.preview_travel(campaign_id, body.model_dump()))


@router.post("/travel/confirm")
def confirm_travel(
    campaign_id: str,
    body: TravelConfirmRequest,
    service: Annotated[ExplorationService, Depends(get_exploration_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.confirm_travel(campaign_id, body.model_dump()))


@router.get("/scenes/{scene_id}/participants")
def list_scene_participants(
    campaign_id: str,
    scene_id: str,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return {"items": _safe_call(lambda: service.list_participants(campaign_id, scene_id))}


@router.post("/scenes/{scene_id}/participants", status_code=status.HTTP_201_CREATED)
def add_scene_participant(
    campaign_id: str,
    scene_id: str,
    body: SceneParticipantCreate,
    request: Request,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.add_participant(
            campaign_id,
            scene_id,
            body.model_dump(exclude_unset=True),
            request_id=_request_id(request),
        )
    )


@router.delete(
    "/scenes/{scene_id}/participants/{participant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_scene_participant(
    campaign_id: str,
    scene_id: str,
    participant_id: str,
    request: Request,
    response: Response,
    service: Annotated[WorldService, Depends(get_world_service)],
    version: int = Query(ge=1),
) -> None:
    _safe_call(
        lambda: service.remove_participant(
            campaign_id,
            scene_id,
            participant_id,
            expected_version=version,
            request_id=_request_id(request),
        )
    )
    response.status_code = status.HTTP_204_NO_CONTENT


@router.post("/scenes/{scene_id}/start-combat", status_code=status.HTTP_201_CREATED)
def start_scene_combat(
    campaign_id: str,
    scene_id: str,
    body: SceneCombatStartRequest,
    request: Request,
    service: Annotated[WorldService, Depends(get_world_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.start_combat(
            campaign_id,
            scene_id,
            name=body.name,
            request_id=_request_id(request),
        )
    )
