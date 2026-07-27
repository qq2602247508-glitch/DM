from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints

from dnd_dm_assistant.api.dependencies import (
    get_player_room_service,
    get_player_rules_search,
)
from dnd_dm_assistant.application.player_rules_search import PlayerRulesSearch
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.player_room_service import (
    PlayerPrincipal,
    PlayerRoomService,
)

PLAYER_SESSION_COOKIE = "dnd_player_session"
_join_failures: dict[str, list[float]] = {}
_join_lock = threading.Lock()
_JOIN_WINDOW_SECONDS = 60.0
_JOIN_MAX_FAILURES = 5

admin_player_room_router = APIRouter(
    prefix="/campaigns/{campaign_id}/player-room",
    tags=["player-room-admin"],
)
public_player_room_router = APIRouter(prefix="/player-room", tags=["player-room"])


class OpenRoomInput(BaseModel):
    hours: int = Field(default=12, ge=1, le=24)


class LiveStateInput(BaseModel):
    scene_id: str | None = Field(default=None, max_length=36)
    combat_id: str | None = Field(default=None, max_length=36)


class AssignCharacterInput(BaseModel):
    character_id: str = Field(min_length=1, max_length=36)


class JoinInput(BaseModel):
    join_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=8)]
    display_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
    ]


class CharacterCreateInput(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    race: str = Field(min_length=1, max_length=100)
    class_name: str = Field(min_length=1, max_length=100)
    background: str = Field(min_length=1, max_length=100)
    ability_scores: dict[str, int]
    equipment: list[str] = Field(default_factory=list, max_length=50)
    skill_proficiencies: list[str] = Field(default_factory=list, max_length=4)
    spells: list[dict[str, Any]] = Field(default_factory=list, max_length=30)


class ActionRequestInput(BaseModel):
    action_type: str = Field(min_length=1, max_length=80)
    message: str | None = Field(default=None, max_length=4000)
    payload_json: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=120)


class NoncombatActionPlanInput(BaseModel):
    action_id: str = Field(min_length=1, max_length=200)
    target_type: Literal["self", "npc", "monster", "object", "area"]
    target_id: str | None = Field(default=None, max_length=36)
    message: str | None = Field(default=None, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=120)


class NoncombatRollInput(BaseModel):
    version: int = Field(ge=1)
    raw_roll: int = Field(ge=1, le=20)


class DmNoncombatActionPlanInput(NoncombatActionPlanInput):
    character_id: str = Field(min_length=1, max_length=36)


class DmNoncombatRollInput(NoncombatRollInput):
    character_id: str = Field(min_length=1, max_length=36)


class MoveInput(BaseModel):
    row: int = Field(ge=1, le=100)
    col: int = Field(ge=1, le=100)
    combatant_version: int = Field(ge=1)


class AttackInput(BaseModel):
    target_combatant_id: str = Field(min_length=1, max_length=36)
    target_combatant_ids: list[str] = Field(default_factory=list, max_length=30)
    action_name: str = Field(min_length=1, max_length=200)
    attack_total: int = Field(ge=-100, le=1000)
    damage_total: int = Field(ge=0, le=100_000)
    end_turn_after: bool = False
    idempotency_key: str = Field(min_length=8, max_length=120)


class RollInput(BaseModel):
    action_version: int = Field(ge=1)
    roll_total: int = Field(ge=-100, le=1000)
    idempotency_key: str = Field(min_length=8, max_length=120)


class EndTurnInput(BaseModel):
    combat_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


class RuleSearchInput(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    limit: int = Field(default=8, ge=1, le=20)


class PlayerEquipmentInput(BaseModel):
    equipment_id: str = Field(min_length=1, max_length=36)
    operation: Literal["equip", "unequip", "attune", "unattune"]
    slot: Literal["armor", "main_hand", "off_hand", "focus", "worn"] | None = None
    preview_token: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


def _safe[T](fn: Callable[[], T]) -> T:
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


def _join_rate_key(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _join_rate_limited(key: str) -> bool:
    cutoff = time.monotonic() - _JOIN_WINDOW_SECONDS
    with _join_lock:
        recent = [value for value in _join_failures.get(key, []) if value >= cutoff]
        _join_failures[key] = recent
        return len(recent) >= _JOIN_MAX_FAILURES


def _record_join_failure(key: str) -> None:
    with _join_lock:
        _join_failures.setdefault(key, []).append(time.monotonic())


def _clear_join_failures(key: str) -> None:
    with _join_lock:
        _join_failures.pop(key, None)


def get_player_principal(
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
    session_token: Annotated[str | None, Cookie(alias=PLAYER_SESSION_COOKIE)] = None,
) -> PlayerPrincipal:
    try:
        return service.authenticate(session_token)
    except (StateNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="player session is invalid or expired") from exc


@admin_player_room_router.post("/open")
def open_room(
    campaign_id: str,
    body: OpenRoomInput,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.open_room(campaign_id, hours=body.hours))


@admin_player_room_router.get("")
def room_status(
    campaign_id: str,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.room_status(campaign_id))


@admin_player_room_router.post("/close")
def close_room(
    campaign_id: str,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.close_room(campaign_id))


@admin_player_room_router.post("/live-state")
def set_live_state(
    campaign_id: str,
    body: LiveStateInput,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.set_live_state(campaign_id, body.scene_id, body.combat_id))


@admin_player_room_router.get("/dm/noncombat-actions/{character_id}")
def dm_noncombat_actions(
    campaign_id: str,
    character_id: str,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.dm_noncombat_snapshot(campaign_id, character_id))


@admin_player_room_router.post("/dm/noncombat-actions/plan")
def dm_plan_noncombat_action(
    campaign_id: str,
    body: DmNoncombatActionPlanInput,
    request: Request,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.dm_plan_noncombat_action(
            campaign_id,
            body.character_id,
            body.model_dump(exclude={"character_id"}),
            _request_id(request),
        )
    )


@admin_player_room_router.post("/dm/noncombat-actions/{action_request_id}/roll")
def dm_roll_noncombat_action(
    campaign_id: str,
    action_request_id: str,
    body: DmNoncombatRollInput,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.dm_roll_noncombat_action(
            campaign_id,
            body.character_id,
            action_request_id,
            body.version,
            body.raw_roll,
        )
    )


@admin_player_room_router.post("/members/{member_id}/kick")
def kick_member(
    campaign_id: str,
    member_id: str,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.kick(campaign_id, member_id))


@admin_player_room_router.post("/members/{member_id}/assign-character")
def assign_character(
    campaign_id: str,
    member_id: str,
    body: AssignCharacterInput,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.assign_character(campaign_id, member_id, body.character_id))


@public_player_room_router.post("/join", status_code=status.HTTP_201_CREATED)
def join_room(
    body: JoinInput,
    response: Response,
    request: Request,
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    rate_key = _join_rate_key(request)
    if _join_rate_limited(rate_key):
        raise HTTPException(status_code=429, detail="too many failed room join attempts")
    try:
        token, payload = service.join(body.join_code, body.display_name)
    except ValueError as exc:
        _record_join_failure(rate_key)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _clear_join_failures(rate_key)
    settings = request.app.state.settings
    max_age = int(payload.pop("session_max_age_seconds"))
    response.set_cookie(
        key=PLAYER_SESSION_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=False,  # LAN gateway is HTTP; production HTTPS deployments must set this True.
        samesite="strict",
        path=f"{settings.api_prefix}/player-room",
    )
    return payload


@public_player_room_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    request: Request,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> None:
    _safe(lambda: service.logout(principal))
    response.delete_cookie(
        PLAYER_SESSION_COOKIE,
        path=f"{request.app.state.settings.api_prefix}/player-room",
        httponly=True,
        samesite="strict",
    )


@public_player_room_router.get("/me")
def me(
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.snapshot(principal))


@public_player_room_router.post("/me/characters", status_code=status.HTTP_201_CREATED)
def create_character(
    body: CharacterCreateInput,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.create_character(principal, body.model_dump()))


@public_player_room_router.post("/me/bind-character")
def bind_character(
    body: AssignCharacterInput,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.bind_character(principal, body.character_id))


@public_player_room_router.post("/me/equipment/preview")
def preview_equipment(
    body: PlayerEquipmentInput,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.preview_equipment(principal, body.model_dump()))


@public_player_room_router.post("/me/equipment/confirm")
def confirm_equipment(
    body: PlayerEquipmentInput,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    if not body.preview_token or not body.idempotency_key:
        raise HTTPException(422, "preview_token and idempotency_key required")
    return _safe(lambda: service.confirm_equipment(principal, body.model_dump()))


@public_player_room_router.post("/me/action-requests", status_code=status.HTTP_201_CREATED)
def submit_action_request(
    body: ActionRequestInput,
    request: Request,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.submit_request(
            principal,
            body.action_type,
            body.message or "",
            body.payload_json,
            body.idempotency_key,
            _request_id(request),
        )
    )


@public_player_room_router.post(
    "/me/noncombat-actions/plan", status_code=status.HTTP_201_CREATED
)
def plan_noncombat_action(
    body: NoncombatActionPlanInput,
    request: Request,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.plan_noncombat_action(
            principal, body.model_dump(), _request_id(request)
        )
    )


@public_player_room_router.post("/me/noncombat-actions/{action_request_id}/roll")
def roll_noncombat_action(
    action_request_id: str,
    body: NoncombatRollInput,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.roll_noncombat_action(
            principal,
            action_request_id,
            body.version,
            body.raw_roll,
        )
    )


@public_player_room_router.post("/me/combat/move")
def move(
    body: MoveInput,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: service.move(principal, body.row, body.col, body.combatant_version))


@public_player_room_router.post("/me/combat/attack")
def attack(
    body: AttackInput,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.attack(
            principal,
            body.target_combatant_id,
            body.target_combatant_ids,
            body.action_name,
            body.attack_total,
            body.damage_total,
            body.end_turn_after,
            body.idempotency_key,
        )
    )


@public_player_room_router.post("/me/combat/player-rolls/{action_id}")
def confirm_roll(
    action_id: str,
    body: RollInput,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.confirm_roll(
            principal,
            action_id,
            body.action_version,
            body.roll_total,
            body.idempotency_key,
        )
    )


@public_player_room_router.post("/me/combat/end-turn")
def end_turn(
    body: EndTurnInput,
    principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(
        lambda: service.end_turn(
            principal,
            body.combat_version,
            body.idempotency_key,
        )
    )


@public_player_room_router.post("/me/rules/search")
def rules_search(
    body: RuleSearchInput,
    _principal: Annotated[PlayerPrincipal, Depends(get_player_principal)],
    search: Annotated[PlayerRulesSearch, Depends(get_player_rules_search)],
) -> dict[str, Any]:
    return {"items": _safe(lambda: search.search(body.text, limit=body.limit))}
