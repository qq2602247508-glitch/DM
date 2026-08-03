from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from dnd_dm_assistant.api.dependencies import (
    get_player_room_service,
    get_simulation_service,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.infrastructure.database.player_room_service import PlayerRoomService
from dnd_dm_assistant.infrastructure.database.simulation_service import SimulationService

router = APIRouter(prefix="/simulations", tags=["simulations"])


def _safe(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _with_player_room(
    state: dict[str, Any],
    room_service: PlayerRoomService,
    *,
    reopen: bool,
) -> dict[str, Any]:
    campaign_id = str(state["campaign"]["id"])
    if reopen:
        room = room_service.open_room(campaign_id, hours=12)
        join_code = room.get("join_code")
        room = room_service.set_live_state(
            campaign_id,
            str(state["scene"]["id"]),
            str(state["combat"]["id"]),
            room["version"],
        )
        return {
            **state,
            "player_room": room,
            "player_join_code": join_code,
        }
    return {**state, "player_room": room_service.room_status(campaign_id)}


@router.get("/current")
def current_simulation(
    service: Annotated[SimulationService, Depends(get_simulation_service)],
    room_service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: _with_player_room(service.current(), room_service, reopen=False))


@router.post("/prepare")
def prepare_simulation(
    service: Annotated[SimulationService, Depends(get_simulation_service)],
    room_service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: _with_player_room(service.prepare(), room_service, reopen=True))


@router.post("/reset")
def reset_simulation(
    service: Annotated[SimulationService, Depends(get_simulation_service)],
    room_service: Annotated[PlayerRoomService, Depends(get_player_room_service)],
) -> dict[str, Any]:
    return _safe(lambda: _with_player_room(service.prepare(reset=True), room_service, reopen=True))
