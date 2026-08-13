"""Source-bound, persistent timed spell modifier seam.

The contract is deliberately spell-name agnostic.  A reviewed Content IR
producer supplies the source identity, target, typed modifier, and duration;
this module owns only validation, replacement, expiry, CAS, and replay.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class TypedSpellTimedModifierSpec:
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    source_id: str
    target_id: str
    stat: str
    operation: str
    value: int
    duration_unit: str
    duration_value: int
    stacking: str = "replace_source"

    def __post_init__(self) -> None:
        for field in (
            "content_id",
            "source_record_id",
            "clause_id",
            "source_id",
            "target_id",
        ):
            if not str(getattr(self, field)).strip():
                raise ValueError(f"typed spell timed modifier {field} is required")
        fingerprint = self.source_fingerprint.strip()
        if len(fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in fingerprint.lower()
        ):
            raise ValueError("typed spell timed modifier source_fingerprint must be sha256")
        if self.stat not in {"speed_ft", "jump_distance_ft"}:
            raise ValueError("typed spell timed modifier stat is unsupported")
        if self.operation != "add":
            raise ValueError("typed spell timed modifier operation must be add")
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value == 0:
            raise ValueError("typed spell timed modifier value must be a non-zero integer")
        if self.duration_unit not in {"minutes", "hours"}:
            raise ValueError("typed spell timed modifier duration unit is unsupported")
        if (
            isinstance(self.duration_value, bool)
            or not isinstance(self.duration_value, int)
            or self.duration_value < 1
        ):
            raise ValueError("typed spell timed modifier duration must be positive")
        if self.stacking != "replace_source":
            raise ValueError("typed spell timed modifier stacking must replace_source")

    def as_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "stat": self.stat,
            "operation": self.operation,
            "value": self.value,
            "duration_unit": self.duration_unit,
            "duration_value": self.duration_value,
            "stacking": self.stacking,
        }


@dataclass(frozen=True)
class TypedSpellTimedModifierReceipt:
    schema: str
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    source_id: str
    target_id: str
    modifier_id: str
    expires_at: str
    state_version_before: int
    state_version_after: int
    request_fingerprint: str
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "modifier_id": self.modifier_id,
            "expires_at": self.expires_at,
            "state_version_before": self.state_version_before,
            "state_version_after": self.state_version_after,
            "request_fingerprint": self.request_fingerprint,
            "replayed": self.replayed,
        }


def apply_typed_spell_timed_modifier(
    spec: TypedSpellTimedModifierSpec,
    *,
    state: dict[str, Any],
    expected_version: int,
    now: datetime,
    prior_receipt: TypedSpellTimedModifierReceipt | None = None,
) -> tuple[dict[str, Any], TypedSpellTimedModifierReceipt]:
    """Apply one source-bound modifier to a JSON state snapshot.

    The function is a persistence seam: callers can store the returned state
    in an authoritative combatant snapshot inside their existing transaction.
    """

    current_version = state.get("version", 0)
    if isinstance(current_version, bool) or not isinstance(current_version, int):
        raise ValueError("typed spell timed modifier state version is invalid")
    if current_version != expected_version:
        raise ValueError("typed spell timed modifier state version is stale")
    started_at = _utc(now)
    expires_at = started_at + timedelta(
        hours=spec.duration_value if spec.duration_unit == "hours" else 0,
        minutes=spec.duration_value if spec.duration_unit == "minutes" else 0,
    )
    modifier_id = f"{spec.source_id}:{spec.target_id}"
    request_fingerprint = _fingerprint(
        {"spec": spec.as_dict(), "now": started_at.isoformat()}
    )
    if prior_receipt is not None:
        if prior_receipt.request_fingerprint != request_fingerprint:
            raise ValueError("typed spell timed modifier replay payload does not match")
        return dict(state), TypedSpellTimedModifierReceipt(
            **{**prior_receipt.as_dict(), "replayed": True}
        )

    modifiers = state.get("timed_spell_modifiers", [])
    if not isinstance(modifiers, list) or any(not isinstance(item, dict) for item in modifiers):
        raise ValueError("typed spell timed modifier state is invalid")
    updated = [dict(item) for item in modifiers if item.get("modifier_id") != modifier_id]
    updated.append(
        {
            "modifier_id": modifier_id,
            "content_id": spec.content_id,
            "source_record_id": spec.source_record_id,
            "source_fingerprint": spec.source_fingerprint,
            "clause_id": spec.clause_id,
            "source_id": spec.source_id,
            "target_id": spec.target_id,
            "modifier": {
                "stat": spec.stat,
                "operation": spec.operation,
                "value": spec.value,
            },
            "stacking": spec.stacking,
            "started_at": started_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    )
    after_version = current_version + 1
    updated_state = {**state, "version": after_version, "timed_spell_modifiers": updated}
    receipt = TypedSpellTimedModifierReceipt(
        schema="spell.timed_modifier.v1",
        content_id=spec.content_id,
        source_record_id=spec.source_record_id,
        source_fingerprint=spec.source_fingerprint,
        clause_id=spec.clause_id,
        source_id=spec.source_id,
        target_id=spec.target_id,
        modifier_id=modifier_id,
        expires_at=expires_at.isoformat(),
        state_version_before=current_version,
        state_version_after=after_version,
        request_fingerprint=request_fingerprint,
    )
    return updated_state, receipt
