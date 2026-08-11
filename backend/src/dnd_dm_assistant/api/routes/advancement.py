from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from dnd_dm_assistant.api.dependencies import (
    get_advancement_service,
    get_campaign_service,
    get_character_catalog,
)
from dnd_dm_assistant.api.schemas import (
    AdvancementBatchConfirmRequest,
    AdvancementBatchPreviewRequest,
    AdvancementConfirmRequest,
    AdvancementPreviewRequest,
    CharacterSheetOcrRequest,
    CompanionCreate,
    CompanionPatch,
    RuleBlockCompileRequest,
)
from dnd_dm_assistant.application.character_catalog import CharacterCatalog
from dnd_dm_assistant.application.character_ocr import recognize_character_sheet
from dnd_dm_assistant.application.rule_block_compiler import compile_rule_blocks
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.rule_blocks import build_execution_plan
from dnd_dm_assistant.domain.rule_extensions import list_rule_extensions
from dnd_dm_assistant.infrastructure.database.advancement_service import (
    AdvancementService,
)

router = APIRouter(tags=["character-advancement"])


def _safe_call[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _version(if_match: str | None, explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    if if_match:
        try:
            return int(if_match.strip().removeprefix("W/").strip('"'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid If-Match version") from None
    raise HTTPException(status_code=428, detail="If-Match or body version is required")


@router.get("/rules/character-options")
def character_options(
    catalog: Annotated[CharacterCatalog, Depends(get_character_catalog)],
    campaign_service: Annotated[Any, Depends(get_campaign_service)],
    campaign_id: str | None = Query(default=None, min_length=1, max_length=36),
) -> dict[str, Any]:
    enabled_content_packs: list[str] = []
    enabled: list[str] = []
    allow_legacy = False
    if campaign_id:
        campaign = campaign_service.get("campaign", campaign_id)
        enabled = [str(value) for value in campaign.get("enabled_rule_extensions", [])]
        enabled_content_packs = [
            str(value) for value in campaign.get("enabled_content_packs", [])
        ]
        allow_legacy = bool(campaign.get("allow_legacy", False))
    result = catalog.options(
        enabled_content_packs=enabled_content_packs,
        allow_legacy=allow_legacy,
    )
    result["allow_legacy"] = allow_legacy
    result["enabled_rule_extensions"] = enabled
    result["rule_extensions"] = [
        item for item in list_rule_extensions() if item["key"] in set(enabled)
    ]
    return result


@router.post("/rules/blocks/compile")
def compile_rule_plan(body: RuleBlockCompileRequest) -> dict[str, Any]:
    def compile_value() -> dict[str, Any]:
        plan = compile_rule_blocks(body.source, source_kind=body.source_kind)
        execution = build_execution_plan(plan)
        return {
            "rule_plan": plan.model_dump(mode="json"),
            "execution_plan": execution.model_dump(mode="json"),
        }

    return _safe_call(compile_value)


@router.post("/rules/character-sheet/ocr")
def character_sheet_ocr(body: CharacterSheetOcrRequest) -> dict[str, Any]:
    script = Path(__file__).resolve().parents[5] / "scripts" / "character-sheet-ocr.swift"
    return _safe_call(
        lambda: recognize_character_sheet(
            body.image_base64,
            filename=body.filename,
            script_path=script,
        )
    )


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/advancement/preview"
)
def preview_advancement(
    campaign_id: str,
    character_id: str,
    body: AdvancementPreviewRequest,
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.preview(
            campaign_id,
            character_id,
            body.model_dump(mode="json"),
        )
    )


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/advancement/confirm"
)
def confirm_advancement(
    campaign_id: str,
    character_id: str,
    body: AdvancementConfirmRequest,
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.confirm(
            campaign_id,
            character_id,
            body.model_dump(mode="json"),
        )
    )


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/advancement/batch/preview"
)
def preview_batch_advancement(
    campaign_id: str,
    character_id: str,
    body: AdvancementBatchPreviewRequest,
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.preview_batch(
            campaign_id,
            character_id,
            body.model_dump(mode="json"),
        )
    )


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/advancement/batch/confirm"
)
def confirm_batch_advancement(
    campaign_id: str,
    character_id: str,
    body: AdvancementBatchConfirmRequest,
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.confirm_batch(
            campaign_id,
            character_id,
            body.model_dump(mode="json"),
        )
    )


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/advancement/downgrade/preview"
)
def preview_downgrade(
    campaign_id: str,
    character_id: str,
    body: dict[str, Any],
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.preview_downgrade(campaign_id, character_id, body))


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/advancement/downgrade/confirm"
)
def confirm_downgrade(
    campaign_id: str,
    character_id: str,
    body: dict[str, Any],
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.confirm_downgrade(campaign_id, character_id, body))


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/content-pack-pin"
)
def pin_character_content_packs(
    campaign_id: str,
    character_id: str,
    body: dict[str, Any],
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
) -> dict[str, Any]:
    return _safe_call(lambda: service.pin_content_packs(campaign_id, character_id, body))


@router.get("/campaigns/{campaign_id}/characters/{character_id}/advancement")
def advancement_history(
    campaign_id: str,
    character_id: str,
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
) -> dict[str, Any]:
    return {"items": _safe_call(lambda: service.list_history(campaign_id, character_id))}


@router.get("/campaigns/{campaign_id}/companions")
def list_companions(
    campaign_id: str,
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
    owner_character_id: str | None = Query(default=None),
) -> dict[str, Any]:
    return {
        "items": _safe_call(
            lambda: service.list_companions(campaign_id, owner_character_id)
        )
    }


@router.post(
    "/campaigns/{campaign_id}/companions",
    status_code=status.HTTP_201_CREATED,
)
def create_companion(
    campaign_id: str,
    body: CompanionCreate,
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
) -> dict[str, Any]:
    return _safe_call(
        lambda: service.create_companion(
            campaign_id,
            body.model_dump(mode="json"),
        )
    )


@router.patch("/campaigns/{campaign_id}/companions/{companion_id}")
def update_companion(
    campaign_id: str,
    companion_id: str,
    body: CompanionPatch,
    service: Annotated[AdvancementService, Depends(get_advancement_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if not data:
        raise HTTPException(status_code=400, detail="Patch must include a field")
    return _safe_call(
        lambda: service.update_companion(
            campaign_id,
            companion_id,
            data,
            _version(if_match, body.version),
        )
    )
