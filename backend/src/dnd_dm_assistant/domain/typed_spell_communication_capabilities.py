"""Source-bound, expiring spell communication capability seam."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

CAPABILITY_SCHEMA = "spell.communication.capability.v1"
INFLUENCE_ACTION_SKILLS = ("deception", "intimidation", "persuasion")


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TypedSpellCommunicationCapabilitySpec:
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    target_scope: str
    creature_kind: str
    duration_unit: str
    duration_value: int
    influence_action_skills: tuple[str, ...]
    information_scope: str
    recent_observation_hours: int

    def __post_init__(self) -> None:
        for field in ("content_id", "source_record_id", "clause_id", "target_scope"):
            if not str(getattr(self, field)).strip():
                raise ValueError(f"communication capability {field} is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_fingerprint):
            raise ValueError("communication capability source_fingerprint must be sha256")
        if self.target_scope != "self":
            raise ValueError("communication capability target_scope must be self")
        if self.clause_id != "communication_capability":
            raise ValueError("communication capability clause is unsupported")
        if self.creature_kind != "beast":
            raise ValueError("communication capability creature_kind must be beast")
        if self.duration_unit != "minutes" or self.duration_value != 10:
            raise ValueError("communication capability duration must be 10 minutes")
        if self.influence_action_skills != INFLUENCE_ACTION_SKILLS:
            raise ValueError("communication capability Influence skills are incomplete")
        if self.information_scope != "surroundings_and_monsters":
            raise ValueError("communication capability information scope is unsupported")
        if self.recent_observation_hours != 24:
            raise ValueError("communication capability recent boundary must be 24 hours")

    def as_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "target_scope": self.target_scope,
            "creature_kind": self.creature_kind,
            "duration_unit": self.duration_unit,
            "duration_value": self.duration_value,
            "influence_action_skills": list(self.influence_action_skills),
            "information_scope": self.information_scope,
            "recent_observation_hours": self.recent_observation_hours,
        }


def apply_typed_spell_communication_capability(
    spec: TypedSpellCommunicationCapabilitySpec,
    *,
    state: dict[str, Any],
    expected_version: int,
    now: datetime,
    prior_receipt: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    version = state.get("version", 0)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("communication capability state version is invalid")
    if version != expected_version:
        raise ValueError("communication capability state version is stale")
    started_at = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    expires_at = started_at + timedelta(minutes=spec.duration_value)
    request_fingerprint = _fingerprint(
        {"spec": spec.as_dict(), "started_at": started_at.isoformat()}
    )
    if prior_receipt is not None:
        if prior_receipt.get("request_fingerprint") != request_fingerprint:
            raise ValueError("communication capability replay payload does not match")
        return dict(state), {**prior_receipt, "replayed": True}
    capabilities = state.get("communication_capabilities", [])
    if not isinstance(capabilities, list) or any(
        not isinstance(item, dict) for item in capabilities
    ):
        raise ValueError("communication capability state is invalid")
    capability_id = f"{spec.content_id}:{spec.target_scope}:{spec.creature_kind}"
    updated_capabilities = [
        item for item in capabilities if item.get("capability_id") != capability_id
    ]
    updated_capabilities.append(
        {
            "capability_id": capability_id,
            **spec.as_dict(),
            "started_at": started_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    )
    updated = {
        **state,
        "version": version + 1,
        "communication_capabilities": updated_capabilities,
    }
    receipt = {
        "schema": CAPABILITY_SCHEMA,
        **spec.as_dict(),
        "capability_id": capability_id,
        "started_at": started_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "state_version_before": version,
        "state_version_after": version + 1,
        "request_fingerprint": request_fingerprint,
        "replayed": False,
    }
    return updated, receipt
