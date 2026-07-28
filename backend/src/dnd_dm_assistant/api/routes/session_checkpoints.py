from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from dnd_dm_assistant.api.dependencies import get_session_checkpoint_service
from dnd_dm_assistant.api.session_checkpoint_schemas import (
    SessionCheckpointArchiveRequest,
    SessionCheckpointCreateRequest,
    SessionCheckpointRestoreRequest,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.session_checkpoint_service import (
    CheckpointConflictError,
    SessionCheckpointService,
)

router = APIRouter(
    prefix="/campaigns/{campaign_id}/session-checkpoints",
    tags=["session-checkpoints"],
)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _call(fn: Any) -> Any:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CheckpointConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "conflicts": exc.conflicts},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_session_checkpoints(
    campaign_id: str,
    service: Annotated[SessionCheckpointService, Depends(get_session_checkpoint_service)],
    include_archived: bool = Query(default=False),
) -> dict[str, Any]:
    return {
        "checkpoints": _call(
            lambda: service.list_checkpoints(
                campaign_id, include_archived=include_archived
            )
        )
    }


@router.get("/current-state")
def get_current_session_state(
    campaign_id: str,
    service: Annotated[SessionCheckpointService, Depends(get_session_checkpoint_service)],
) -> dict[str, Any]:
    return _call(lambda: service.current_state(campaign_id))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session_checkpoint(
    campaign_id: str,
    body: SessionCheckpointCreateRequest,
    service: Annotated[SessionCheckpointService, Depends(get_session_checkpoint_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.create(
            campaign_id,
            name=body.name,
            scene_id=body.scene_id,
            active_combat_id=body.active_combat_id,
            entries=body.entries,
            expected_campaign_version=body.expected_campaign_version,
            notes=body.notes,
        )
    )


@router.get("/{checkpoint_id}")
def get_session_checkpoint(
    campaign_id: str,
    checkpoint_id: str,
    service: Annotated[SessionCheckpointService, Depends(get_session_checkpoint_service)],
) -> dict[str, Any]:
    return _call(lambda: service.get(campaign_id, checkpoint_id))


@router.post("/{checkpoint_id}/restore-preview")
def preview_session_checkpoint_restore(
    campaign_id: str,
    checkpoint_id: str,
    body: SessionCheckpointRestoreRequest,
    service: Annotated[SessionCheckpointService, Depends(get_session_checkpoint_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.preview_restore(
            campaign_id,
            checkpoint_id,
            expected_campaign_version=body.expected_campaign_version,
            force=body.force,
        )
    )


@router.post("/{checkpoint_id}/restore")
def restore_session_checkpoint(
    campaign_id: str,
    checkpoint_id: str,
    body: SessionCheckpointRestoreRequest,
    request: Request,
    service: Annotated[SessionCheckpointService, Depends(get_session_checkpoint_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.restore(
            campaign_id,
            checkpoint_id,
            expected_campaign_version=body.expected_campaign_version,
            force=body.force,
            idempotency_key=body.idempotency_key or _request_id(request),
        )
    )


@router.post("/{checkpoint_id}/archive")
def archive_session_checkpoint(
    campaign_id: str,
    checkpoint_id: str,
    body: SessionCheckpointArchiveRequest,
    service: Annotated[SessionCheckpointService, Depends(get_session_checkpoint_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.archive(
            campaign_id,
            checkpoint_id,
            expected_version=body.version,
        )
    )
