"""Generic, provenance-bound extradimensional vessel containment state machine.

This module is intentionally persistence agnostic.  It validates source-bound
facts and returns immutable transition receipts for an application materializer
to persist with the existing operation transaction/CAS boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

VESSEL_SPACE_SCHEMA = "vessel.space.v1"
VesselEvent = Literal[
    "create",
    "enter",
    "exit",
    "eject",
    "destroy",
    "owner_death",
    "long_rest",
]
VESSEL_EVENTS = frozenset(
    {"create", "enter", "exit", "eject", "destroy", "owner_death", "long_rest"}
)
VESSEL_APPEARANCES = frozenset(
    {"oil_lamp", "urn", "ring", "stoppered_bottle", "hollow_figurine", "lantern"}
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: object) -> str:
    return str(value or "").strip()


def _require_bool(facts: Mapping[str, Any], key: str) -> None:
    if facts.get(key) is not True:
        raise ValueError(f"vessel space requires authoritative fact: {key}")


@dataclass(frozen=True, slots=True)
class VesselSpaceSpec:
    vessel_id: str
    source_id: str
    source_fingerprint: str
    max_occupants: int
    duration_hours: int
    exit_size_cells: int = 1

    def __post_init__(self) -> None:
        if any(
            not _text(value)
            for value in (self.vessel_id, self.source_id, self.source_fingerprint)
        ):
            raise ValueError("vessel space identity and source provenance are required")
        if isinstance(self.max_occupants, bool) or self.max_occupants < 1:
            raise ValueError("vessel space max_occupants must be positive")
        if isinstance(self.duration_hours, bool) or self.duration_hours < 1:
            raise ValueError("vessel space duration_hours must be positive")
        if isinstance(self.exit_size_cells, bool) or self.exit_size_cells < 1:
            raise ValueError("vessel space exit_size_cells must be positive")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": VESSEL_SPACE_SCHEMA,
            "vessel_id": self.vessel_id,
            "source_id": self.source_id,
            "source_fingerprint": self.source_fingerprint,
            "max_occupants": self.max_occupants,
            "duration_hours": self.duration_hours,
            "exit_size_cells": self.exit_size_cells,
        }


@dataclass(frozen=True, slots=True)
class VesselSpaceResult:
    state: dict[str, Any]
    replayed: bool = False
    ejected_occupants: tuple[str, ...] = ()
    ejected_items: tuple[str, ...] = ()


def _validate_state(state: Mapping[str, Any], spec: VesselSpaceSpec) -> None:
    for key, expected in (
        ("schema", VESSEL_SPACE_SCHEMA),
        ("vessel_id", spec.vessel_id),
        ("source_id", spec.source_id),
        ("source_fingerprint", spec.source_fingerprint),
    ):
        if state.get(key) != expected:
            raise ValueError(f"vessel space {key} does not match the spec")
    if state.get("status") not in {"outside", "inside", "destroyed", "removed"}:
        raise ValueError("vessel space status is invalid")
    if not isinstance(state.get("version"), int) or isinstance(state.get("version"), bool):
        raise ValueError("vessel space version is invalid")
    occupants = state.get("occupants")
    items = state.get("items")
    if not isinstance(occupants, list) or not all(
        isinstance(item, str) and item for item in occupants
    ):
        raise ValueError("vessel space occupants are invalid")
    if len(occupants) > spec.max_occupants:
        raise ValueError("vessel space occupants exceed source-bound capacity")
    if not isinstance(items, list) or not all(isinstance(item, str) and item for item in items):
        raise ValueError("vessel space items are invalid")
    if state.get("appearance") not in VESSEL_APPEARANCES:
        raise ValueError("vessel space appearance is invalid")


def _request_fingerprint(
    spec: VesselSpaceSpec,
    *,
    event: str,
    subject_ids: Sequence[str],
    facts: Mapping[str, Any],
) -> str:
    return _fingerprint(
        {
            "schema": VESSEL_SPACE_SCHEMA,
            "spec": spec.as_dict(),
            "event": event,
            "subject_ids": list(subject_ids),
            "facts": dict(facts),
        }
    )


def transition_vessel_space(
    spec: VesselSpaceSpec,
    state: Mapping[str, Any] | None,
    *,
    event: VesselEvent,
    operation_id: str,
    expected_version: int | None,
    subject_ids: Sequence[str] = (),
    facts: Mapping[str, Any] | None = None,
    appearance: str | None = None,
) -> VesselSpaceResult:
    """Validate one vessel transition; persistence belongs to the caller."""

    event = _text(event).casefold()
    operation_id = _text(operation_id)
    if event not in VESSEL_EVENTS:
        raise ValueError("vessel space event is invalid")
    if not operation_id:
        raise ValueError("vessel space operation_id is required")
    normalized_ids = tuple(dict.fromkeys(_text(item) for item in subject_ids if _text(item)))
    normalized_facts = dict(facts or {})
    request_fingerprint = _request_fingerprint(
        spec, event=event, subject_ids=normalized_ids, facts=normalized_facts
    )

    if state is None:
        if event != "create" or expected_version not in (None, 0):
            raise ValueError("vessel space must be created from an empty state")
        chosen_appearance = _text(appearance)
        if chosen_appearance not in VESSEL_APPEARANCES:
            raise ValueError("vessel space appearance must be selected from the source table")
        return VesselSpaceResult(
            state={
                "schema": VESSEL_SPACE_SCHEMA,
                "vessel_id": spec.vessel_id,
                "source_id": spec.source_id,
                "source_fingerprint": spec.source_fingerprint,
                "status": "outside",
                "version": 1,
                "appearance": chosen_appearance,
                "vessel_size": {"kind": "tiny"},
                "interior": {
                    "shape": "cylinder",
                    "radius_ft": 20,
                    "height_ft": 20,
                    "temperature": "comfortable",
                    "furnishings": ["comfortable_cushions", "tea_table"],
                },
                "duration_hours": spec.duration_hours,
                "occupants": [],
                "items": [],
                "entry_used_since_long_rest": False,
                "last_operation_id": operation_id,
                "last_operation_fingerprint": request_fingerprint,
            }
        )

    current = dict(state)
    _validate_state(current, spec)
    if expected_version != current["version"]:
        raise ValueError(
            "vessel space version conflict: "
            f"expected {expected_version}, actual {current['version']}"
        )
    if current.get("last_operation_id") == operation_id:
        if current.get("last_operation_fingerprint") != request_fingerprint:
            raise ValueError("vessel space replay payload does not match")
        return VesselSpaceResult(state=current, replayed=True)

    status = current["status"]
    occupants = list(current["occupants"])
    items = list(current["items"])
    ejected_occupants: tuple[str, ...] = ()
    ejected_items: tuple[str, ...] = ()

    if event == "long_rest":
        if status in {"destroyed", "removed"}:
            raise ValueError("vessel space is no longer available")
        current["entry_used_since_long_rest"] = False
    elif event == "enter":
        _require_bool(normalized_facts, "vessel_touched")
        _require_bool(normalized_facts, "source_owner")
        _require_bool(normalized_facts, "entry_action_available")
        if current.get("entry_used_since_long_rest"):
            raise ValueError("vessel entry is unavailable until a long rest")
        if status == "inside":
            raise ValueError("vessel space cannot be entered recursively")
        if status in {"destroyed", "removed"}:
            raise ValueError("vessel space is unavailable")
        if not normalized_ids:
            raise ValueError("vessel entry requires at least one creature")
        if any(item in occupants for item in normalized_ids):
            raise ValueError("vessel entry cannot duplicate an occupant")
        if len(occupants) + len(normalized_ids) > spec.max_occupants:
            raise ValueError("vessel entry exceeds source-bound capacity")
        _require_bool(normalized_facts, "all_creatures_voluntary")
        _require_bool(normalized_facts, "all_creatures_visible")
        current["status"] = "inside"
        occupants.extend(normalized_ids)
        current["entry_used_since_long_rest"] = True
    elif event in {"exit", "eject", "destroy", "owner_death"}:
        if event in {"exit", "eject"} and status != "inside":
            raise ValueError("vessel exit requires occupants inside")
        if event in {"exit", "eject"}:
            selected = normalized_ids or tuple(occupants)
            if any(item not in occupants for item in selected):
                raise ValueError("vessel exit subject is not inside")
            _require_bool(normalized_facts, "destination_nearest_unoccupied")
            occupants = [item for item in occupants if item not in selected]
            if not occupants:
                current["status"] = "outside"
        else:
            ejected_occupants = tuple(occupants)
            ejected_items = tuple(items)
            occupants = []
            items = []
            current["status"] = "removed" if event == "owner_death" else "destroyed"
            current["termination_reason"] = (
                "owner_died" if event == "owner_death" else "source_object_destroyed"
            )
            _require_bool(normalized_facts, "nearest_unoccupied_for_occupants")
            _require_bool(normalized_facts, "nearest_unoccupied_for_items")
    current.update(
        {
            "version": int(current["version"]) + 1,
            "occupants": occupants,
            "items": items,
            "last_operation_id": operation_id,
            "last_operation_fingerprint": request_fingerprint,
        }
    )
    return VesselSpaceResult(
        state=current,
        ejected_occupants=ejected_occupants,
        ejected_items=ejected_items,
    )
