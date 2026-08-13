"""Provenance-bound movement and separation semantics for runtime entities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from dnd_dm_assistant.domain.rules_kernel_protocol import KernelPosition

ENTITY_SPATIAL_SCHEMA = "entity.spatial.v1"
EntitySpatialEvent = Literal["move", "check_separation"]


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: object) -> str:
    return str(value or "").strip()


def _position(value: object, *, field: str) -> KernelPosition:
    if isinstance(value, KernelPosition):
        return value
    if not isinstance(value, Mapping):
        raise ValueError(f"entity spatial {field} position is required")
    try:
        return KernelPosition(
            row=int(value["row"]),
            col=int(value["col"]),
            elevation_ft=int(value.get("elevation_ft", 0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"entity spatial {field} position is invalid") from exc


def _distance(first: KernelPosition, second: KernelPosition, *, cell_size_ft: int) -> int:
    if cell_size_ft < 1:
        raise ValueError("entity spatial cell_size_ft must be positive")
    horizontal = max(abs(first.row - second.row), abs(first.col - second.col)) * cell_size_ft
    return max(horizontal, abs(first.elevation_ft - second.elevation_ft))


@dataclass(frozen=True, slots=True)
class EntitySpatialSpec:
    entity_id: str
    source_id: str
    source_fingerprint: str
    max_move_ft: int = 30
    expiry_distance_ft: int = 300
    cell_size_ft: int = 5

    def __post_init__(self) -> None:
        if any(
            not _text(value)
            for value in (self.entity_id, self.source_id, self.source_fingerprint)
        ):
            raise ValueError("entity spatial entity and source provenance are required")
        for name, value in (
            ("max_move_ft", self.max_move_ft),
            ("expiry_distance_ft", self.expiry_distance_ft),
            ("cell_size_ft", self.cell_size_ft),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"entity spatial {name} must be a positive integer")
        if self.max_move_ft > self.expiry_distance_ft:
            raise ValueError("entity spatial max_move_ft cannot exceed expiry distance")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": ENTITY_SPATIAL_SCHEMA,
            "entity_id": self.entity_id,
            "source_id": self.source_id,
            "source_fingerprint": self.source_fingerprint,
            "max_move_ft": self.max_move_ft,
            "expiry_distance_ft": self.expiry_distance_ft,
            "cell_size_ft": self.cell_size_ft,
        }


@dataclass(frozen=True, slots=True)
class EntitySpatialResult:
    state: dict[str, Any]
    replayed: bool = False
    expired: bool = False
    distance_ft: int = 0


def _validate_state(state: Mapping[str, Any], spec: EntitySpatialSpec) -> None:
    if _text(state.get("schema")) != ENTITY_SPATIAL_SCHEMA:
        raise ValueError("entity spatial state schema is invalid")
    for key, expected in (
        ("entity_id", spec.entity_id),
        ("source_id", spec.source_id),
        ("source_fingerprint", spec.source_fingerprint),
    ):
        if _text(state.get(key)) != expected:
            raise ValueError(f"entity spatial {key} does not match the spec")
    if _text(state.get("status")) not in {"active", "expired"}:
        raise ValueError("entity spatial state status is invalid")
    version = state.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("entity spatial state version is invalid")
    _position(state.get("position"), field="state")
    _position(state.get("owner_position"), field="owner")


def _request_fingerprint(
    spec: EntitySpatialSpec,
    *,
    event: EntitySpatialEvent,
    entity_position: KernelPosition,
    owner_position: KernelPosition,
    destination: KernelPosition | None,
    spatial_facts: Mapping[str, Any] | None,
) -> str:
    return _fingerprint(
        {
            "schema": ENTITY_SPATIAL_SCHEMA,
            "spec": spec.as_dict(),
            "event": event,
            "entity_position": entity_position,
            "owner_position": owner_position,
            "destination": destination,
            "spatial_facts": dict(spatial_facts or {}),
        }
    )


def transition_entity_spatial(
    spec: EntitySpatialSpec,
    state: Mapping[str, Any] | None,
    *,
    event: EntitySpatialEvent,
    operation_id: str,
    expected_version: int | None,
    entity_position: KernelPosition | Mapping[str, Any],
    owner_position: KernelPosition | Mapping[str, Any],
    destination: KernelPosition | Mapping[str, Any] | None = None,
    spatial_facts: Mapping[str, Any] | None = None,
) -> EntitySpatialResult:
    """Apply one movement/separation check with CAS and idempotent replay."""

    event = _text(event).casefold()
    operation_id = _text(operation_id)
    if event not in {"move", "check_separation"}:
        raise ValueError("entity spatial event is invalid")
    if not operation_id:
        raise ValueError("entity spatial operation_id is required")
    current_position = _position(entity_position, field="entity")
    current_owner_position = _position(owner_position, field="owner")
    next_position = (
        _position(destination, field="destination")
        if destination is not None
        else current_position
    )
    request_fingerprint = _request_fingerprint(
        spec,
        event=event, entity_position=current_position, owner_position=current_owner_position,
        destination=next_position if event == "move" else None, spatial_facts=spatial_facts,
    )

    if state is None:
        if event != "move":
            raise ValueError("entity spatial can only initialize with move")
        if expected_version not in (None, 0):
            raise ValueError("entity spatial create expected_version must be empty or zero")
        facts = dict(spatial_facts or {})
        if facts.get("visible_to_owner") is not True:
            raise ValueError("entity spatial movement requires owner visibility")
        if facts.get("destination_unoccupied") is not True:
            raise ValueError("entity spatial movement requires an unoccupied destination")
        if facts.get("path_clear_of_objects") is not True:
            raise ValueError("entity spatial movement cannot pass through objects")
        if (
            _distance(current_position, next_position, cell_size_ft=spec.cell_size_ft)
            > spec.max_move_ft
        ):
            raise ValueError("entity spatial movement exceeds the per-action limit")
        state = {
            "schema": ENTITY_SPATIAL_SCHEMA,
            "entity_id": spec.entity_id,
            "source_id": spec.source_id,
            "source_fingerprint": spec.source_fingerprint,
            "status": "active",
            "position": next_position,
            "owner_position": current_owner_position,
            "version": 1,
            "last_operation_id": operation_id,
            "last_operation_fingerprint": request_fingerprint,
        }
        distance = _distance(
            next_position, current_owner_position, cell_size_ft=spec.cell_size_ft
        )
        if distance > spec.expiry_distance_ft:
            state = {**state, "status": "expired"}
        return EntitySpatialResult(
            dict(state), distance_ft=distance, expired=state["status"] == "expired"
        )

    current = dict(state)
    _validate_state(current, spec)
    if expected_version != current["version"]:
        raise ValueError(
            "entity spatial version conflict: "
            f"expected {expected_version}, actual {current['version']}"
        )
    if _text(current.get("last_operation_id")) == operation_id:
        if _text(current.get("last_operation_fingerprint")) != request_fingerprint:
            raise ValueError("entity spatial operation replay payload does not match")
        distance = _distance(
            current_position, current_owner_position, cell_size_ft=spec.cell_size_ft
        )
        return EntitySpatialResult(
            current,
            replayed=True,
            expired=current["status"] == "expired",
            distance_ft=distance,
        )
    if current["status"] == "expired":
        raise ValueError("entity spatial entity is expired")

    facts = dict(spatial_facts or {})
    if event == "move":
        if facts.get("visible_to_owner") is not True:
            raise ValueError("entity spatial movement requires owner visibility")
        if facts.get("destination_unoccupied") is not True:
            raise ValueError("entity spatial movement requires an unoccupied destination")
        if facts.get("path_clear_of_objects") is not True:
            raise ValueError("entity spatial movement cannot pass through objects")
        move_distance = _distance(current_position, next_position, cell_size_ft=spec.cell_size_ft)
        if move_distance > spec.max_move_ft:
            raise ValueError("entity spatial movement exceeds the per-action limit")
    distance = _distance(
        next_position if event == "move" else current_position,
        current_owner_position,
        cell_size_ft=spec.cell_size_ft,
    )
    next_state = {
        **current,
        "status": "expired" if distance > spec.expiry_distance_ft else "active",
        "position": next_position if event == "move" else current_position,
        "owner_position": current_owner_position,
        "version": int(current["version"]) + 1,
        "last_operation_id": operation_id,
        "last_operation_fingerprint": request_fingerprint,
    }
    return EntitySpatialResult(
        next_state,
        expired=next_state["status"] == "expired",
        distance_ft=distance,
    )
