# ruff: noqa: E501, E701

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, StringConstraints

from dnd_dm_assistant.api.dependencies import get_player_service
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.player_service import PlayerService

player_router = APIRouter(prefix="/player/campaigns/{campaign_id}", tags=["player-view"])
dm_router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["player-management"])


class HandoutInput(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    body: str = Field(min_length=1, max_length=50_000)
    published: bool = False
    sort_order: int = Field(default=0, ge=-10_000, le=10_000)


class HandoutPatch(BaseModel):
    title: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    body: str | None = Field(default=None, min_length=1, max_length=50_000)
    published: bool | None = None
    sort_order: int | None = Field(default=None, ge=-10_000, le=10_000)
    version: int = Field(ge=1)


class PlayerActionInput(BaseModel):
    character_id: str
    character_version: int = Field(ge=1)
    player_key: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    action_type: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    message: str | None = Field(default=None, max_length=4000)
    payload_json: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Annotated[str, StringConstraints(min_length=8, max_length=120)]


class ResolveActionInput(BaseModel):
    version: int = Field(ge=1)
    dm_note: str | None = Field(default=None, max_length=4000)
    attack_total: int | None = Field(default=None, ge=-100, le=1000)
    damage_total: int | None = Field(default=None, ge=0, le=100000)
    critical_hit: bool = False


class ResolvePostHitRiderInput(BaseModel):
    version: int = Field(ge=1)
    inputs: dict[str, Any] = Field(default_factory=dict, max_length=30)


def _safe(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


@player_router.get("/view")
def player_view(
    campaign_id: str, service: Annotated[PlayerService, Depends(get_player_service)]
) -> dict[str, Any]:
    return _safe(lambda: service.player_view(campaign_id))


@player_router.get("/characters/{character_id}")
def player_character(
    campaign_id: str,
    character_id: str,
    service: Annotated[PlayerService, Depends(get_player_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.character_view(campaign_id, character_id))


@player_router.post("/action-requests", status_code=status.HTTP_201_CREATED)
def submit_player_action(
    campaign_id: str,
    body: PlayerActionInput,
    request: Request,
    service: Annotated[PlayerService, Depends(get_player_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.submit_action(campaign_id, body.model_dump(), _request_id(request))
    )


@dm_router.get("/handouts")
def list_handouts(
    campaign_id: str, service: Annotated[PlayerService, Depends(get_player_service)]
) -> dict[str, Any]:
    return {"items": _safe(lambda: service.list_handouts(campaign_id))}


@dm_router.post("/handouts", status_code=status.HTTP_201_CREATED)
def create_handout(
    campaign_id: str,
    body: HandoutInput,
    service: Annotated[PlayerService, Depends(get_player_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.create_handout(campaign_id, body.model_dump()))


@dm_router.patch("/handouts/{handout_id}")
def patch_handout(
    campaign_id: str,
    handout_id: str,
    body: HandoutPatch,
    service: Annotated[PlayerService, Depends(get_player_service)],
) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True, exclude={"version"})
    if not values:
        raise HTTPException(status_code=400, detail="Patch must include at least one field")
    return _safe(lambda: service.update_handout(campaign_id, handout_id, values, body.version))


@dm_router.get("/player-action-requests")
def list_player_actions(
    campaign_id: str,
    service: Annotated[PlayerService, Depends(get_player_service)],
    status_filter: Literal["pending", "accepted", "rejected", "stale"] | None = Query(
        default=None, alias="status"
    ),
) -> dict[str, Any]:
    return {"items": _safe(lambda: service.list_requests(campaign_id, status_filter))}


@dm_router.post("/player-action-requests/{action_request_id}/accept")
def accept_player_action(
    campaign_id: str,
    action_request_id: str,
    body: ResolveActionInput,
    request: Request,
    service: Annotated[PlayerService, Depends(get_player_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.resolve_action(
            campaign_id,
            action_request_id,
            body.version,
            "accepted",
            body.dm_note,
            _request_id(request),
            attack_total=body.attack_total,
            damage_total=body.damage_total,
            critical_hit=body.critical_hit,
        )
    )


@dm_router.post("/player-action-requests/{action_request_id}/reject")
def reject_player_action(
    campaign_id: str,
    action_request_id: str,
    body: ResolveActionInput,
    request: Request,
    service: Annotated[PlayerService, Depends(get_player_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.resolve_action(
            campaign_id,
            action_request_id,
            body.version,
            "rejected",
            body.dm_note,
            _request_id(request),
        )
    )


@dm_router.post("/post-hit-rider-requests/{action_request_id}/resolve")
def resolve_post_hit_rider_request(
    campaign_id: str,
    action_request_id: str,
    body: ResolvePostHitRiderInput,
    service: Annotated[PlayerService, Depends(get_player_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.resolve_post_hit_rider(
            campaign_id,
            action_request_id,
            body.version,
            body.inputs,
        )
    )
