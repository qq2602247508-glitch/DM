from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from dnd_dm_assistant.api.dependencies import get_combat_engine_service
from dnd_dm_assistant.api.schemas import (
    CombatActionCommand,
    CombatEffectCommand,
    CombatEffectEndCommand,
    CombatResetCommand,
    CombatSettlementCommand,
    ConcentrationCheckCommand,
    DeathConfirmationCommand,
    DeathSaveCommand,
    PlayerRollPromptCommand,
    PlayerRollResolutionCommand,
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


@router.post("/actions/player-rolls/pending")
def create_pending_player_roll(
    campaign_id: str,
    combat_id: str,
    body: PlayerRollPromptCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.create_player_roll_prompt(
            campaign_id,
            combat_id,
            body,
            idempotency_key=request_id,
        )
    )


@router.post("/actions/player-rolls/{action_id}/preview")
def preview_player_roll(
    campaign_id: str,
    combat_id: str,
    action_id: str,
    body: PlayerRollResolutionCommand,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.preview_player_roll(
            campaign_id,
            combat_id,
            action_id,
            body,
        )
    )


@router.post("/actions/player-rolls/{action_id}/confirm")
def confirm_player_roll(
    campaign_id: str,
    combat_id: str,
    action_id: str,
    body: PlayerRollResolutionCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.confirm_player_roll(
            campaign_id,
            combat_id,
            action_id,
            body,
            idempotency_key=request_id,
        )
    )


@router.get("/end-condition")
def get_combat_end_condition(
    campaign_id: str,
    combat_id: str,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.get_end_condition(campaign_id, combat_id))


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


@router.post("/reset")
def reset_combat(
    campaign_id: str,
    combat_id: str,
    body: CombatResetCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.reset_combat(
            campaign_id,
            combat_id,
            body,
            idempotency_key=request_id,
        )
    )


@router.post("/effects/preview")
def preview_effect(
    campaign_id: str,
    combat_id: str,
    body: CombatEffectCommand,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.preview_effect(campaign_id, combat_id, body)
    )


@router.post("/effects/confirm")
def confirm_effect(
    campaign_id: str,
    combat_id: str,
    body: CombatEffectCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.confirm_effect(
            campaign_id,
            combat_id,
            body,
            idempotency_key=request_id,
        )
    )


@router.get("/effects")
def list_effects(
    campaign_id: str,
    combat_id: str,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    return {"items": _safe_call(lambda: service.list_effects(campaign_id, combat_id))}


@router.post("/concentration/confirm")
def confirm_concentration_check(
    campaign_id: str,
    combat_id: str,
    body: ConcentrationCheckCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.confirm_concentration_check(
            campaign_id,
            combat_id,
            body,
            idempotency_key=request_id,
        )
    )


@router.post("/effects/{effect_id}/end")
def end_effect(
    campaign_id: str,
    combat_id: str,
    effect_id: str,
    body: CombatEffectEndCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.end_effect(
            campaign_id,
            combat_id,
            effect_id,
            body,
            idempotency_key=request_id,
        )
    )


@router.post("/settlement/preview")
def preview_settlement(
    campaign_id: str,
    combat_id: str,
    body: CombatSettlementCommand,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.preview_settlement(campaign_id, combat_id, body)
    )


@router.post("/settlement/confirm")
def confirm_settlement(
    campaign_id: str,
    combat_id: str,
    body: CombatSettlementCommand,
    request: Request,
    service: Annotated[CombatEngineService, Depends(get_combat_engine_service)],
) -> dict[str, Any]:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return _safe_call(
        lambda: service.confirm_settlement(
            campaign_id,
            combat_id,
            body,
            idempotency_key=request_id,
        )
    )
