from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints

from dnd_dm_assistant.api.dependencies import get_monster_ai_service
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.monster_ai_service import MonsterAIService

router = APIRouter(
    prefix="/campaigns/{campaign_id}/combats/{combat_id}/monster-ai",
    tags=["monster-ai"],
)


class MonsterAIPlanRequest(BaseModel):
    actor_combatant_id: str = Field(min_length=1, max_length=36)
    actor_version: int | None = Field(default=None, ge=1)
    phase: Literal["turn", "reaction", "legendary", "lair"] = "turn"
    tactics: Literal["instinctive", "standard", "smart", "tactical"] = "standard"
    recharge_available: dict[str, bool] | None = None
    reaction_event: Literal[
        "leaves_reach",
        "enters_reach",
        "takes_damage",
        "hit_by_attack",
        "casts_spell",
        "turn_end",
    ] | None = None


class MonsterAITacticsRequest(BaseModel):
    actor_combatant_id: str = Field(min_length=1, max_length=36)
    actor_version: int = Field(ge=1)
    strategy: Literal[
        "adaptive", "focus_fire", "protect_leader", "control", "retreat"
    ] = "adaptive"
    focus_target_id: str | None = Field(default=None, min_length=1, max_length=36)
    leader_id: str | None = Field(default=None, min_length=1, max_length=36)
    retreat_threshold_pct: int | None = Field(default=None, ge=1, le=100)
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ]


class MonsterAIRetreatRequest(BaseModel):
    actor_combatant_id: str = Field(min_length=1, max_length=36)
    actor_version: int = Field(ge=1)


@router.post("/preview")
def preview_monster_ai(
    campaign_id: str,
    combat_id: str,
    body: MonsterAIPlanRequest,
    service: Annotated[MonsterAIService, Depends(get_monster_ai_service)],
) -> dict[str, Any]:
    try:
        return service.preview(
            campaign_id,
            combat_id,
            body.actor_combatant_id,
            actor_version=body.actor_version,
            phase=body.phase,
            tactics=body.tactics,
            recharge_available=body.recharge_available,
            reaction_event=body.reaction_event,
        )
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/retreat/confirm")
def confirm_monster_ai_retreat(
    campaign_id: str,
    combat_id: str,
    body: MonsterAIRetreatRequest,
    request: Request,
    service: Annotated[MonsterAIService, Depends(get_monster_ai_service)],
) -> dict[str, Any]:
    try:
        return service.confirm_retreat(
            campaign_id,
            combat_id,
            body.actor_combatant_id,
            actor_version=body.actor_version,
            idempotency_key=str(getattr(request.state, "request_id", "unknown")),
        )
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tactics/confirm")
def confirm_monster_ai_tactics(
    campaign_id: str,
    combat_id: str,
    body: MonsterAITacticsRequest,
    request: Request,
    service: Annotated[MonsterAIService, Depends(get_monster_ai_service)],
) -> dict[str, Any]:
    try:
        return service.configure_tactics(
            campaign_id,
            combat_id,
            body.actor_combatant_id,
            actor_version=body.actor_version,
            strategy=body.strategy,
            focus_target_id=body.focus_target_id,
            leader_id=body.leader_id,
            retreat_threshold_pct=body.retreat_threshold_pct,
            reason=body.reason,
            idempotency_key=str(getattr(request.state, "request_id", "unknown")),
        )
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
