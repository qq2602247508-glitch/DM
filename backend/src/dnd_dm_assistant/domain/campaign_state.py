from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class CampaignState:
    """Bounded, read-only aggregate used as structured DM context."""

    campaign: dict[str, Any]
    characters: tuple[dict[str, Any], ...]
    npcs: tuple[dict[str, Any], ...]
    locations: tuple[dict[str, Any], ...]
    quests: tuple[dict[str, Any], ...]
    open_clues: tuple[dict[str, Any], ...]
    active_combats: tuple[dict[str, Any], ...]
    as_of: datetime


@dataclass(frozen=True, slots=True)
class VersionConflict(Exception):
    entity_type: str
    entity_id: str
    expected: int
    actual: int | None

    def __str__(self) -> str:
        return (
            f"{self.entity_type} {self.entity_id} version conflict: "
            f"expected {self.expected}, actual {self.actual}"
        )


class StateNotFoundError(LookupError):
    pass
