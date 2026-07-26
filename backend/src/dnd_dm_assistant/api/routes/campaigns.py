from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from dnd_dm_assistant.api.dependencies import get_campaign_service
from dnd_dm_assistant.api.schemas import (
    CampaignBackup,
    CampaignCreate,
    CampaignImportRequest,
    CampaignPatch,
    CampaignResponse,
    CharacterCreate,
    CharacterPatch,
    CharacterResponse,
    ClueCreate,
    CluePatch,
    CombatantCreate,
    CombatantPatch,
    CombatCreate,
    CombatPatch,
    ConditionCreate,
    ConditionPatch,
    ConnectionCreate,
    ConnectionPatch,
    EventCreate,
    EventPatch,
    LocationCreate,
    LocationPatch,
    NarrativeCreate,
    NarrativePatch,
    NPCCreate,
    NPCPatch,
    NPCResponse,
    QuestCreate,
    QuestPatch,
    StateSnapshot,
)
from dnd_dm_assistant.application.campaigns import CampaignService, NotFoundError
from dnd_dm_assistant.domain.campaign_state import VersionConflict

router = APIRouter(prefix="/campaigns", tags=["campaign-state"])


def _version(if_match: str | None, explicit: int | None) -> int:
    header_version: int | None = None
    if if_match:
        token = if_match.strip().removeprefix("W/").strip('"')
        try:
            header_version = int(token)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid If-Match version") from None
    if explicit is not None and header_version is not None and explicit != header_version:
        raise HTTPException(status_code=400, detail="If-Match and body version disagree")
    if explicit is not None:
        return explicit
    if header_version is not None:
        return header_version
    raise HTTPException(status_code=428, detail="If-Match or body version is required")


def _safe_call(fn: Any) -> Any:
    try:
        return fn()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=422, detail="State constraints were violated") from exc


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CampaignResponse)
def create_campaign(
    body: CampaignCreate,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.create(
            "campaign", body.model_dump(exclude_unset=True), request_id=_request_id(request)
        )
    )


@router.get("")
def list_campaigns(
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return {
        "items": service.list("campaign", campaign_id=None, limit=limit, offset=offset),
        "limit": limit,
        "offset": offset,
    }


@router.post("/import-backup", status_code=status.HTTP_201_CREATED, response_model=CampaignResponse)
def import_campaign_backup(
    body: CampaignImportRequest,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.import_backup(
            body.backup.model_dump(mode="json"),
            name=body.name,
            request_id=_request_id(request),
        )
    )


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(
    campaign_id: str,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.get("campaign", campaign_id))


@router.patch("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(
    campaign_id: str,
    body: CampaignPatch,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    expected = _version(if_match, body.version)
    values = body.model_dump(exclude_unset=True, exclude={"version"})
    if not values:
        raise HTTPException(status_code=400, detail="Patch must include at least one field")
    return _safe_call(
        lambda: service.update(
            "campaign",
            campaign_id,
            values,
            expected_version=expected,
            request_id=_request_id(request),
        )
    )


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: str,
    request: Request,
    response: Response,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    version: int | None = Query(None, ge=1),
) -> None:
    _safe_call(
        lambda: service.delete(
            "campaign",
            campaign_id,
            expected_version=_version(if_match, version),
            request_id=_request_id(request),
        )
    )
    response.status_code = status.HTTP_204_NO_CONTENT


@router.get("/{campaign_id}/state", response_model=StateSnapshot)
def campaign_state(
    campaign_id: str,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    limit: int = Query(100, ge=1, le=200),
) -> StateSnapshot:
    state = _safe_call(lambda: service.state(campaign_id, limit=limit))
    return (
        StateSnapshot(**state.__dict__)
        if hasattr(state, "__dict__")
        else StateSnapshot(
            campaign=state.campaign,
            characters=state.characters,
            npcs=state.npcs,
            locations=state.locations,
            quests=state.quests,
            open_clues=state.open_clues,
            active_combats=state.active_combats,
            as_of=state.as_of,
        )
    )


@router.get("/{campaign_id}/export", response_model=CampaignBackup)
def export_campaign_backup(
    campaign_id: str,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.export_backup(campaign_id))


def _crud_routes(
    *,
    resource: str,
    create_model: type[BaseModel],
    patch_model: type[BaseModel],
    singular: str,
    response_model: type[BaseModel] | None = None,
) -> None:
    nested = APIRouter(prefix="/{campaign_id}/" + resource, tags=["campaign-state"])

    @nested.post("", status_code=201, response_model=response_model)
    def create(
        campaign_id: str,
        body: create_model,  # type: ignore[valid-type]
        request: Request,
        service: Annotated[CampaignService, Depends(get_campaign_service)],
    ) -> dict[str, Any]:
        return _safe_call(
            lambda: service.create(
                singular,
                body.model_dump(exclude_unset=True),  # type: ignore[attr-defined]
                campaign_id=campaign_id,
                request_id=_request_id(request),
            )
        )

    @nested.get("")
    def list_items(
        campaign_id: str,
        service: Annotated[CampaignService, Depends(get_campaign_service)],
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        _safe_call(lambda: service.get("campaign", campaign_id))
        return {
            "items": service.list(singular, campaign_id=campaign_id, limit=limit, offset=offset),
            "limit": limit,
            "offset": offset,
        }

    @nested.get("/{entity_id}", response_model=response_model)
    def get_item(
        campaign_id: str,
        entity_id: str,
        service: Annotated[CampaignService, Depends(get_campaign_service)],
    ) -> dict[str, Any]:
        return _safe_call(lambda: service.get(singular, entity_id, campaign_id=campaign_id))

    @nested.patch("/{entity_id}", response_model=response_model)
    def patch_item(
        campaign_id: str,
        entity_id: str,
        body: patch_model,  # type: ignore[valid-type]
        request: Request,
        service: Annotated[CampaignService, Depends(get_campaign_service)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        expected = _version(if_match, getattr(body, "version", None))
        values = body.model_dump(  # type: ignore[attr-defined]
            exclude_unset=True, exclude={"version"}
        )
        if not values:
            raise HTTPException(status_code=400, detail="Patch must include at least one field")
        return _safe_call(
            lambda: service.update(
                singular,
                entity_id,
                values,
                campaign_id=campaign_id,
                expected_version=expected,
                request_id=_request_id(request),
            )
        )

    @nested.delete("/{entity_id}", status_code=204)
    def delete_item(
        campaign_id: str,
        entity_id: str,
        request: Request,
        response: Response,
        service: Annotated[CampaignService, Depends(get_campaign_service)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        version: int | None = Query(None, ge=1),
    ) -> None:
        _safe_call(
            lambda: service.delete(
                singular,
                entity_id,
                campaign_id=campaign_id,
                expected_version=_version(if_match, version),
                request_id=_request_id(request),
            )
        )
        response.status_code = 204

    router.include_router(nested)


_crud_routes(
    resource="characters",
    create_model=CharacterCreate,
    patch_model=CharacterPatch,
    singular="character",
    response_model=CharacterResponse,
)
_crud_routes(
    resource="npcs",
    create_model=NPCCreate,
    patch_model=NPCPatch,
    singular="npc",
    response_model=NPCResponse,
)
_crud_routes(
    resource="locations",
    create_model=LocationCreate,
    patch_model=LocationPatch,
    singular="location",
)
_crud_routes(resource="quests", create_model=QuestCreate, patch_model=QuestPatch, singular="quest")
_crud_routes(resource="clues", create_model=ClueCreate, patch_model=CluePatch, singular="clue")
_crud_routes(resource="events", create_model=EventCreate, patch_model=EventPatch, singular="event")
_crud_routes(
    resource="story-beats",
    create_model=NarrativeCreate,
    patch_model=NarrativePatch,
    singular="story_beat",
)
_crud_routes(
    resource="quest-objectives",
    create_model=NarrativeCreate,
    patch_model=NarrativePatch,
    singular="quest_objective",
)
_crud_routes(
    resource="npc-memories",
    create_model=NarrativeCreate,
    patch_model=NarrativePatch,
    singular="npc_memory",
)
_crud_routes(
    resource="faction-reputations",
    create_model=NarrativeCreate,
    patch_model=NarrativePatch,
    singular="faction_reputation",
)
_crud_routes(
    resource="clue-discoveries",
    create_model=NarrativeCreate,
    patch_model=NarrativePatch,
    singular="clue_discovery",
)
_crud_routes(
    resource="downtime-activities",
    create_model=NarrativeCreate,
    patch_model=NarrativePatch,
    singular="downtime_activity",
)
_crud_routes(
    resource="combats", create_model=CombatCreate, patch_model=CombatPatch, singular="combat"
)


@router.post("/{campaign_id}/characters/{character_id}/conditions", status_code=201)
def create_condition(
    campaign_id: str,
    character_id: str,
    body: ConditionCreate,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    data["character_id"] = character_id
    return _safe_call(
        lambda: service.create(
            "condition", data, campaign_id=campaign_id, request_id=_request_id(request)
        )
    )


@router.get("/{campaign_id}/characters/{character_id}/conditions")
def list_conditions(
    campaign_id: str,
    character_id: str,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    _safe_call(lambda: service.get("character", character_id, campaign_id=campaign_id))
    return {
        "items": service.list(
            "condition", campaign_id=campaign_id, limit=limit, parent_id=character_id
        )
    }


@router.get("/{campaign_id}/characters/{character_id}/conditions/{condition_id}")
def get_condition(
    campaign_id: str,
    character_id: str,
    condition_id: str,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
) -> dict[str, Any]:
    _safe_call(lambda: service.get("character", character_id, campaign_id=campaign_id))
    item = _safe_call(lambda: service.get("condition", condition_id, campaign_id=campaign_id))
    if item["character_id"] != character_id:
        raise HTTPException(status_code=404, detail="condition not found")
    return item


@router.patch("/{campaign_id}/characters/{character_id}/conditions/{condition_id}")
def patch_condition(
    campaign_id: str,
    character_id: str,
    condition_id: str,
    body: ConditionPatch,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    get_condition(campaign_id, character_id, condition_id, service)
    values = body.model_dump(exclude_unset=True, exclude={"version"})
    if not values:
        raise HTTPException(status_code=400, detail="Patch must include at least one field")
    return _safe_call(
        lambda: service.update(
            "condition",
            condition_id,
            values,
            campaign_id=campaign_id,
            expected_version=_version(if_match, body.version),
            request_id=_request_id(request),
        )
    )


@router.delete(
    "/{campaign_id}/characters/{character_id}/conditions/{condition_id}", status_code=204
)
def delete_condition(
    campaign_id: str,
    character_id: str,
    condition_id: str,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    version: int | None = Query(None, ge=1),
) -> None:
    get_condition(campaign_id, character_id, condition_id, service)
    _safe_call(
        lambda: service.delete(
            "condition",
            condition_id,
            campaign_id=campaign_id,
            expected_version=_version(if_match, version),
            request_id=_request_id(request),
        )
    )


@router.post("/{campaign_id}/combats/{combat_id}/combatants", status_code=201)
def create_combatant(
    campaign_id: str,
    combat_id: str,
    body: CombatantCreate,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
) -> dict[str, Any]:
    # Combatants have rules-significant defaults (entity type, action economy,
    # movement, and defensive traits). Persist the complete validated snapshot
    # so database rows never depend on a caller spelling those defaults out.
    data = body.model_dump()
    snapshot = dict(data["snapshot_json"])
    snapshot.setdefault(
        "combat_start_state",
        {
            "hp": data["hp"],
            "temporary_hp": data["temporary_hp"],
            "max_hp_reduction": data["max_hp_reduction"],
            "conditions": list(data["conditions"]),
            "concentration": dict(data["concentration"]),
            "is_active": data["is_active"],
        },
    )
    data["snapshot_json"] = snapshot
    data["combat_id"] = combat_id
    return _safe_call(
        lambda: service.create(
            "combatant", data, campaign_id=campaign_id, request_id=_request_id(request)
        )
    )


@router.get("/{campaign_id}/combats/{combat_id}/combatants")
def list_combatants(
    campaign_id: str,
    combat_id: str,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    _safe_call(lambda: service.get("combat", combat_id, campaign_id=campaign_id))
    return {
        "items": service.list(
            "combatant", campaign_id=campaign_id, limit=limit, parent_id=combat_id
        )
    }


@router.get("/{campaign_id}/combats/{combat_id}/combatants/{combatant_id}")
def get_combatant(
    campaign_id: str,
    combat_id: str,
    combatant_id: str,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
) -> dict[str, Any]:
    _safe_call(lambda: service.get("combat", combat_id, campaign_id=campaign_id))
    item = _safe_call(lambda: service.get("combatant", combatant_id, campaign_id=campaign_id))
    if item["combat_id"] != combat_id:
        raise HTTPException(status_code=404, detail="combatant not found")
    return item


@router.patch("/{campaign_id}/combats/{combat_id}/combatants/{combatant_id}")
def patch_combatant(
    campaign_id: str,
    combat_id: str,
    combatant_id: str,
    body: CombatantPatch,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    get_combatant(campaign_id, combat_id, combatant_id, service)
    values = body.model_dump(exclude_unset=True, exclude={"version"})
    if not values:
        raise HTTPException(status_code=400, detail="Patch must include at least one field")
    return _safe_call(
        lambda: service.update(
            "combatant",
            combatant_id,
            values,
            campaign_id=campaign_id,
            expected_version=_version(if_match, body.version),
            request_id=_request_id(request),
        )
    )


@router.delete("/{campaign_id}/combats/{combat_id}/combatants/{combatant_id}", status_code=204)
def delete_combatant(
    campaign_id: str,
    combat_id: str,
    combatant_id: str,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    version: int | None = Query(None, ge=1),
) -> None:
    get_combatant(campaign_id, combat_id, combatant_id, service)
    _safe_call(
        lambda: service.delete(
            "combatant",
            combatant_id,
            campaign_id=campaign_id,
            expected_version=_version(if_match, version),
            request_id=_request_id(request),
        )
    )


@router.post("/{campaign_id}/locations/{location_id}/connections", status_code=201)
def create_connection(
    campaign_id: str,
    location_id: str,
    body: ConnectionCreate,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    data["from_location_id"] = location_id
    return _safe_call(
        lambda: service.create(
            "connection", data, campaign_id=campaign_id, request_id=_request_id(request)
        )
    )


@router.get("/{campaign_id}/locations/{location_id}/connections")
def list_connections(
    campaign_id: str,
    location_id: str,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    _safe_call(lambda: service.get("location", location_id, campaign_id=campaign_id))
    return {
        "items": service.list(
            "connection", campaign_id=campaign_id, limit=limit, parent_id=location_id
        )
    }


@router.patch("/{campaign_id}/locations/{location_id}/connections/{connection_id}")
def patch_connection(
    campaign_id: str,
    location_id: str,
    connection_id: str,
    body: ConnectionPatch,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    item = _safe_call(lambda: service.get("connection", connection_id, campaign_id=campaign_id))
    if item["from_location_id"] != location_id:
        raise HTTPException(status_code=404, detail="connection not found")
    values = body.model_dump(exclude_unset=True, exclude={"version"})
    if not values:
        raise HTTPException(status_code=400, detail="Patch must include at least one field")
    return _safe_call(
        lambda: service.update(
            "connection",
            connection_id,
            values,
            campaign_id=campaign_id,
            expected_version=_version(if_match, body.version),
            request_id=_request_id(request),
        )
    )


@router.delete(
    "/{campaign_id}/locations/{location_id}/connections/{connection_id}", status_code=204
)
def delete_connection(
    campaign_id: str,
    location_id: str,
    connection_id: str,
    request: Request,
    service: Annotated[CampaignService, Depends(get_campaign_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    version: int | None = Query(None, ge=1),
) -> None:
    item = _safe_call(lambda: service.get("connection", connection_id, campaign_id=campaign_id))
    if item["from_location_id"] != location_id:
        raise HTTPException(status_code=404, detail="connection not found")
    _safe_call(
        lambda: service.delete(
            "connection",
            connection_id,
            campaign_id=campaign_id,
            expected_version=_version(if_match, version),
            request_id=_request_id(request),
        )
    )
