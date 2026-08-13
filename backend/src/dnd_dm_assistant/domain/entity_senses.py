"""Provenance-bound sensory resolution for runtime entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dnd_dm_assistant.domain.spatial_authority import SpatialAuthority

ENTITY_SENSES_SCHEMA = "entity.senses.v1"


def _text(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True, slots=True)
class EntitySensesResolution:
    entity_id: str
    target_id: str
    channels: tuple[str, ...]
    distance_ft: int
    line_of_sight: bool
    lifecycle_status: str
    source_provenance: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": ENTITY_SENSES_SCHEMA,
            "entity_id": self.entity_id,
            "target_id": self.target_id,
            "channels": list(self.channels),
            "distance_ft": self.distance_ft,
            "line_of_sight": self.line_of_sight,
            "lifecycle_status": self.lifecycle_status,
            "source_provenance": dict(self.source_provenance),
        }


def resolve_entity_senses(
    senses_block: Mapping[str, Any],
    lifecycle_record: Mapping[str, Any],
    *,
    owner_id: str,
    target_id: str,
    spatial: SpatialAuthority,
    maximum_information_range_ft: int,
) -> EntitySensesResolution:
    """Resolve one read-only sensory observation from authoritative facts."""

    provenance = senses_block.get("source_provenance")
    lifecycle_provenance = lifecycle_record.get("source_provenance")
    if not isinstance(provenance, Mapping) or not isinstance(lifecycle_provenance, Mapping):
        raise ValueError("entity senses source provenance is required")
    for key in ("source_record_id", "source_fingerprint"):
        source_value = _text(provenance.get(key))
        if not source_value or source_value != _text(lifecycle_provenance.get(key)):
            raise ValueError("entity senses source provenance does not match lifecycle")

    entity_id = _text(lifecycle_record.get("entity_id"))
    if not entity_id or _text(senses_block.get("entity_binding")) != "entity_lifecycle":
        raise ValueError("entity senses entity binding is invalid")
    state = lifecycle_record.get("state")
    if not isinstance(state, Mapping) or _text(state.get("status")) != "entered":
        raise ValueError("entity senses requires an active entity lifecycle")
    if _text(state.get("termination_reason")):
        raise ValueError("entity senses rejects a terminated entity lifecycle")
    metadata = state.get("metadata")
    if not isinstance(metadata, Mapping) or _text(metadata.get("owner_character_id")) != owner_id:
        raise ValueError("entity senses owner authorization failed")
    if not target_id:
        raise ValueError("entity senses target is required")
    senses = senses_block.get("senses")
    if not isinstance(senses, Mapping):
        raise ValueError("entity senses profile is required")
    distance = spatial.distance_between(entity_id, target_id)
    if distance > maximum_information_range_ft:
        raise ValueError("entity senses target is outside information range")
    line_of_sight = spatial.has_line_of_sight(entity_id, target_id)
    channels: list[str] = []
    if senses.get("hearing") is True:
        channels.append("hearing")
    vision_range = max(
        int(senses.get("darkvision_ft") or 0),
        int(senses.get("light_radius_ft") or 0),
    )
    if vision_range >= distance and line_of_sight:
        channels.append("vision")
    if not channels:
        raise ValueError("entity senses cannot resolve target under authoritative conditions")
    return EntitySensesResolution(
        entity_id=entity_id,
        target_id=target_id,
        channels=tuple(channels),
        distance_ft=distance,
        line_of_sight=line_of_sight,
        lifecycle_status="entered",
        source_provenance={
            "source_record_id": _text(provenance.get("source_record_id")),
            "source_fingerprint": _text(provenance.get("source_fingerprint")),
        },
    )
