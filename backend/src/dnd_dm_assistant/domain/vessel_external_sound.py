"""Fail-closed, hearing-only external sound bridge for an active vessel."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

VESSEL_EXTERNAL_SOUND_SCHEMA = "vessel.external_sound.v1"


@dataclass(frozen=True, slots=True)
class VesselExternalSoundReceipt:
    vessel_id: str
    owner_character_id: str
    inside_occupant_id: str
    scene_id: str
    combat_id: str
    vessel_entity_id: str
    channel: str
    status: str
    blocked_reason: str | None
    event_id: str | None = None
    source_producer: str | None = None
    sound_events: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": VESSEL_EXTERNAL_SOUND_SCHEMA,
            "vessel_id": self.vessel_id,
            "owner_character_id": self.owner_character_id,
            "inside_occupant_id": self.inside_occupant_id,
            "scene_id": self.scene_id,
            "combat_id": self.combat_id,
            "vessel_entity_id": self.vessel_entity_id,
            "channel": self.channel,
            "status": self.status,
            "blocked_reason": self.blocked_reason,
            "event_id": self.event_id,
            "source_producer": self.source_producer,
            "sound_events": [dict(event) for event in self.sound_events],
            "state_mutated": False,
        }


def resolve_vessel_external_sound(
    vessel_state: Mapping[str, Any],
    *,
    vessel_id: str,
    owner_character_id: str,
    inside_occupant_id: str,
    scene_id: str,
    combat_id: str,
    vessel_entity_id: str,
    channel: str,
    event_id: str | None = None,
    source_producer: str | None = None,
) -> VesselExternalSoundReceipt:
    """Resolve only the bridge authorization; never invent sound events."""

    if channel != "hearing":
        raise ValueError("vessel external sound supports the hearing channel only")
    if vessel_state.get("status") != "inside":
        raise ValueError("vessel external sound requires an active inside vessel")
    occupants = vessel_state.get("occupants")
    if not isinstance(occupants, list) or inside_occupant_id not in occupants:
        raise ValueError("vessel external sound occupant is not inside the active vessel")
    if vessel_state.get("owner_character_id") != owner_character_id:
        raise ValueError("vessel external sound owner binding does not match")
    if not vessel_id or not owner_character_id or not inside_occupant_id:
        raise ValueError("vessel external sound bindings are required")
    if event_id and source_producer:
        return VesselExternalSoundReceipt(
            vessel_id=vessel_id,
            owner_character_id=owner_character_id,
            inside_occupant_id=inside_occupant_id,
            scene_id=scene_id,
            combat_id=combat_id,
            vessel_entity_id=vessel_entity_id,
            channel="hearing",
            status="resolved",
            blocked_reason=None,
            event_id=event_id,
            source_producer=source_producer,
            sound_events=({"event_id": event_id},),
        )
    return VesselExternalSoundReceipt(
        vessel_id=vessel_id,
        owner_character_id=owner_character_id,
        inside_occupant_id=inside_occupant_id,
        scene_id=scene_id,
        combat_id=combat_id,
        vessel_entity_id=vessel_entity_id,
        channel="hearing",
        status="blocked",
        blocked_reason="no authoritative sound event producer or event_id receipt",
    )
