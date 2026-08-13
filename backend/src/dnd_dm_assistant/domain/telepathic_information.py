"""Source-bound telepathic sensory sharing for an authorized entity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dnd_dm_assistant.domain.entity_senses import resolve_entity_senses
from dnd_dm_assistant.domain.spatial_authority import SpatialAuthority

TELEPATHIC_INFORMATION_SCHEMA = "telepathic.information.v1"


@dataclass(frozen=True, slots=True)
class TelepathicInformationResult:
    owner_id: str
    entity_id: str
    target_id: str
    channels: tuple[str, ...]
    action_economy: str
    language_required: bool
    response_required: bool
    source_provenance: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": TELEPATHIC_INFORMATION_SCHEMA,
            "owner_id": self.owner_id,
            "entity_id": self.entity_id,
            "target_id": self.target_id,
            "channels": list(self.channels),
            "action_economy": self.action_economy,
            "language_required": self.language_required,
            "response_required": self.response_required,
            "source_provenance": dict(self.source_provenance),
        }


def share_authorized_sensory_information(
    channel_block: Mapping[str, Any],
    senses_block: Mapping[str, Any],
    lifecycle_record: Mapping[str, Any],
    *,
    owner_id: str,
    target_id: str,
    spatial: SpatialAuthority,
) -> TelepathicInformationResult:
    if channel_block.get("action_economy") != "none":
        raise ValueError("telepathic information channel must use no action")
    if channel_block.get("visibility") != "owner":
        raise ValueError("telepathic information channel is owner-only")
    if channel_block.get("language_required") is not False:
        raise ValueError("telepathic information channel does not require language")
    if channel_block.get("response_required") is not False:
        raise ValueError("telepathic information channel does not require a response")
    resolution = resolve_entity_senses(
        senses_block,
        lifecycle_record,
        owner_id=owner_id,
        target_id=target_id,
        spatial=spatial,
        maximum_information_range_ft=int(channel_block.get("range_ft") or 300),
    )
    return TelepathicInformationResult(
        owner_id=owner_id,
        entity_id=resolution.entity_id,
        target_id=target_id,
        channels=resolution.channels,
        action_economy="none",
        language_required=False,
        response_required=False,
        source_provenance=resolution.source_provenance,
    )
