from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from dnd_dm_assistant.api.dependencies import get_combat_engine_service
from dnd_dm_assistant.api.schemas import (
    CombatActionCommand,
    DeathConfirmationCommand,
    DeathSaveCommand,
    TurnAdvanceCommand,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService

router = APIRouter(prefix="/campaigns/{campaign_id}/combats/{combat_id}", tags=["combat-engine"])


def _safe_call(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/actions/preview")
def preview_combat_action(
    campaign_id: str,
    combat_id: str,
    body: CombatActionCommand,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.preview(campaign_id, combat_id, body))


@router.post("/actions/confirm")
def confirm_combat_action(
    campaign_id: str,
    combat_id: str,
    body: CombatActionCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.confirm(
            campaign_id,
            combat_id,
            body,
            idempotency_key=request_id,
        )
    )


@router.get("/actions")
def list_combat_actions(
    campaign_id: str,
    combat_id: str,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    return {"items": _safe_call(lambda: service.list_actions(campaign_id, combat_id))}


@router.get("/combatants/{combatant_id}/death-save")
def get_death_save(
    campaign_id: str,
    combat_id: str,
    combatant_id: str,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.get_death_save(campaign_id, combat_id, combatant_id)
    )


@router.post("/combatants/{combatant_id}/death-save/confirm")
def confirm_death_save(
    campaign_id: str,
    combat_id: str,
    combatant_id: str,
    body: DeathSaveCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.confirm_death_save(
            campaign_id,
            combat_id,
            combatant_id,
            body,
            idempotency_key=request_id,
        )
    )


@router.post("/combatants/{combatant_id}/death-save/confirm-death")
def confirm_death(
    campaign_id: str,
    combat_id: str,
    combatant_id: str,
    body: DeathConfirmationCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.confirm_death(
            campaign_id,
            combat_id,
            combatant_id,
            body,
            idempotency_key=request_id,
        )
    )


@router.post("/turns/advance")
def advance_turn(
    campaign_id: str,
    combat_id: str,
    body: TurnAdvanceCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.advance_turn(
            campaign_id,
            combat_id,
            body,
            idempotency_key=request_id,
        )
    )
