from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from dnd_dm_assistant.api.dependencies import get_compendium_service
from dnd_dm_assistant.domain.rule_extensions import list_rule_extensions
from dnd_dm_assistant.infrastructure.database.compendium_service import CompendiumService

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("/extensions")
def get_rule_extensions() -> dict[str, object]:
    """Return the explicit opt-in rule modules available to a new campaign."""

    return {
        "items": list_rule_extensions(),
        "default_enabled": [],
        "policy": {
            "core": "D&D 5e 2024 core rules are always active.",
            "legacy": "Legacy and variant modules require allow_legacy=true.",
            "automation": (
                "partial/dm_only modules are stored as atoms and never guessed into numbers."
            ),
        },
    }


@router.get("/content-packs")
def get_content_packs(
    service: Annotated[CompendiumService, Depends(get_compendium_service)],
) -> dict[str, Any]:
    """List official local source books that a campaign may explicitly enable."""

    return {
        "items": service.content_packs(),
        "default_enabled": [],
        "policy": {
            "core": "D&D 5e 2024 core rules are always active.",
            "source_books": (
                "Supplement books are visible only after their content-pack key is enabled "
                "on the campaign."
            ),
            "normalization": (
                "Entries marked needs_normalization remain reference-safe and are never "
                "silently treated as complete character progression data."
            ),
        },
    }
