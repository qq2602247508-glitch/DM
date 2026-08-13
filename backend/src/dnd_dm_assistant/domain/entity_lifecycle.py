"""Generic, provenance-bound lifecycle contract for runtime entities.

The contract is deliberately persistence-agnostic.  A materializer owns the
transaction that stores the returned state; this module owns only the closed
world state machine, source identity, optimistic version check, and replay
semantics shared by vessel/object/entity consumers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

ENTITY_LIFECYCLE_SCHEMA = "entity.lifecycle.v1"
ENTITY_LIFECYCLE_STATES = frozenset({"created", "entered", "exited", "expired", "terminated"})
ENTITY_LIFECYCLE_EVENTS = frozenset({"create", "enter", "exit", "expire", "terminate"})
ENTITY_TERMINATION_REASONS = frozenset(
    {"dispel_magic", "source_object_destroyed", "owner_died", "owner_dismissed", "distance_expired"}
)
EntityLifecycleState = Literal["created", "entered", "exited", "expired", "terminated"]

_TRANSITIONS: dict[str, frozenset[str]] = {
    "create": frozenset({"created"}),
    "enter": frozenset({"entered"}),
    "exit": frozenset({"exited"}),
    "expire": frozenset({"expired"}),
    "terminate": frozenset({"terminated"}),
}
_ALLOWED_FROM: dict[str, frozenset[str] | None] = {
    "create": None,
    "enter": frozenset({"created", "entered", "exited"}),
    "exit": frozenset({"entered"}),
    "expire": frozenset({"created", "entered", "exited"}),
    "terminate": frozenset({"created", "entered", "exited"}),
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True, slots=True)
class EntityLifecycleSpec:
    """Closed-world metadata required by every entity lifecycle consumer."""

    entity_type: str
    source_id: str
    source_fingerprint: str
    max_entries: int | None = None
    expires_on_owner_death: bool = False
    initial_placement: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not _text(self.entity_type):
            raise ValueError("entity lifecycle entity_type is required")
        if not _text(self.source_id):
            raise ValueError("entity lifecycle source_id is required")
        if not _text(self.source_fingerprint):
            raise ValueError("entity lifecycle source_fingerprint is required")
        if self.max_entries is not None and (
            isinstance(self.max_entries, bool) or self.max_entries < 1
        ):
            raise ValueError("entity lifecycle max_entries must be a positive integer")
        if self.initial_placement is not None:
            if not isinstance(self.initial_placement, Mapping):
                raise ValueError("entity lifecycle initial_placement must be an object")
            max_distance = self.initial_placement.get("max_distance_ft")
            if (
                not isinstance(max_distance, int)
                or isinstance(max_distance, bool)
                or max_distance < 1
            ):
                raise ValueError("entity lifecycle initial_placement max_distance_ft is invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": ENTITY_LIFECYCLE_SCHEMA,
            "entity_type": self.entity_type,
            "source_id": self.source_id,
            "source_fingerprint": self.source_fingerprint,
            "max_entries": self.max_entries,
            "expires_on_owner_death": self.expires_on_owner_death,
            "initial_placement": (
                dict(self.initial_placement) if self.initial_placement is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class EntityLifecycleResult:
    """The state transition a persistence materializer must apply."""

    state: dict[str, Any]
    replayed: bool = False


def _validate_state(state: Mapping[str, Any], spec: EntityLifecycleSpec) -> None:
    if _text(state.get("schema")) != ENTITY_LIFECYCLE_SCHEMA:
        raise ValueError("entity lifecycle state schema is invalid")
    if _text(state.get("entity_type")) != spec.entity_type:
        raise ValueError("entity lifecycle entity_type does not match the spec")
    for key in ("source_id", "source_fingerprint"):
        if _text(state.get(key)) != _text(getattr(spec, key)):
            raise ValueError(f"entity lifecycle {key} does not match the spec")
    if _text(state.get("status")) not in ENTITY_LIFECYCLE_STATES:
        raise ValueError("entity lifecycle state status is invalid")
    version = state.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("entity lifecycle state version is invalid")
    active_entries = state.get("active_entries")
    if (
        not isinstance(active_entries, int)
        or isinstance(active_entries, bool)
        or active_entries < 0
    ):
        raise ValueError("entity lifecycle active_entries is invalid")
    if spec.max_entries is not None and active_entries > spec.max_entries:
        raise ValueError("entity lifecycle active_entries exceeds max_entries")
    if _text(state.get("status")) == "terminated" and _text(
        state.get("termination_reason")
    ) not in ENTITY_TERMINATION_REASONS:
        raise ValueError("entity lifecycle termination_reason is invalid")


def _request_fingerprint(
    spec: EntityLifecycleSpec,
    *,
    event: str,
    metadata: Mapping[str, Any] | None,
) -> str:
    return _fingerprint(
        {
            "schema": ENTITY_LIFECYCLE_SCHEMA,
            "spec": spec.as_dict(),
            "event": event,
            "metadata": dict(metadata or {}),
        }
    )


def transition_entity_lifecycle(
    spec: EntityLifecycleSpec,
    state: Mapping[str, Any] | None,
    *,
    event: str,
    operation_id: str,
    expected_version: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> EntityLifecycleResult:
    """Validate and materialize one lifecycle transition.

    ``state=None`` is valid only for ``create``.  Every non-replay transition
    advances the version exactly once.  A matching operation ID and request
    fingerprint returns the prior state without another transition; reusing
    an operation ID for different input is rejected.
    """

    event = _text(event).casefold()
    operation_id = _text(operation_id)
    if event not in ENTITY_LIFECYCLE_EVENTS:
        raise ValueError("entity lifecycle event is invalid")
    if not operation_id:
        raise ValueError("entity lifecycle operation_id is required")
    normalized_metadata = dict(metadata or {})
    termination_reason = _text(normalized_metadata.pop("termination_reason", ""))
    if event == "expire":
        termination_reason = termination_reason or "distance_expired"
    if event == "terminate" and termination_reason not in ENTITY_TERMINATION_REASONS:
        raise ValueError("entity lifecycle terminate requires a typed termination_reason")
    request_fingerprint = _request_fingerprint(
        spec,
        event=event,
        metadata={**normalized_metadata, "termination_reason": termination_reason}
        if termination_reason
        else normalized_metadata,
    )

    if state is None:
        if event != "create":
            raise ValueError("entity lifecycle can only create from an empty state")
        if expected_version not in (None, 0):
            raise ValueError("entity lifecycle create expected_version must be empty or zero")
        if spec.initial_placement is not None:
            placement = normalized_metadata.get("initial_placement")
            if not isinstance(placement, Mapping):
                raise ValueError("entity lifecycle initial placement facts are required")
            max_distance = int(spec.initial_placement["max_distance_ft"])
            distance = placement.get("distance_from_owner_ft")
            if (
                not isinstance(distance, int)
                or isinstance(distance, bool)
                or distance < 0
                or distance > max_distance
            ):
                raise ValueError("entity lifecycle initial placement exceeds range")
            for fact in ("destination_unoccupied", "source_object_held"):
                if spec.initial_placement.get(fact, False) and placement.get(fact) is not True:
                    raise ValueError(f"entity lifecycle initial placement requires {fact}")
        return EntityLifecycleResult(
            state={
                "schema": ENTITY_LIFECYCLE_SCHEMA,
                "entity_type": spec.entity_type,
                "source_id": spec.source_id,
                "source_fingerprint": spec.source_fingerprint,
                "status": "created",
                "active_entries": 0,
                "version": 1,
                "last_operation_id": operation_id,
                "last_operation_fingerprint": request_fingerprint,
                "metadata": normalized_metadata,
            }
        )

    current = dict(state)
    _validate_state(current, spec)
    if expected_version is None:
        raise ValueError("entity lifecycle expected_version is required for an existing state")
    if expected_version != current["version"]:
        raise ValueError(
            f"entity lifecycle version conflict: expected {expected_version}, "
            f"actual {current['version']}"
        )

    prior_operation = _text(current.get("last_operation_id"))
    prior_fingerprint = _text(current.get("last_operation_fingerprint"))
    if prior_operation == operation_id:
        if prior_fingerprint != request_fingerprint:
            raise ValueError("entity lifecycle operation replay payload does not match")
        return EntityLifecycleResult(state=current, replayed=True)

    current_status = _text(current["status"])
    allowed_from = _ALLOWED_FROM[event]
    if allowed_from is None or current_status not in allowed_from:
        raise ValueError(
            f"entity lifecycle cannot {event} from status {current_status}"
        )

    active_entries = int(current["active_entries"])
    if event == "enter" and spec.max_entries is not None and active_entries >= spec.max_entries:
        raise ValueError("entity lifecycle max_entries exceeded")
    if event == "exit" and active_entries < 1:
        raise ValueError("entity lifecycle cannot exit with no active entries")
    if event == "expire" and active_entries:
        raise ValueError("entity lifecycle cannot expire with active entries")

    next_state = {
        **current,
        "status": next(iter(_TRANSITIONS[event])),
        "active_entries": (
            0
            if event == "terminate"
            else active_entries + (1 if event == "enter" else -1 if event == "exit" else 0)
        ),
        "version": int(current["version"]) + 1,
        "last_operation_id": operation_id,
        "last_operation_fingerprint": request_fingerprint,
        "metadata": normalized_metadata or dict(current.get("metadata") or {}),
    }
    if event in {"expire", "terminate"}:
        next_state["termination_reason"] = termination_reason
    return EntityLifecycleResult(state=next_state)
