"""Generic, source-bound illusion lifecycle and inspection contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

ILLUSION_SCHEMA = "spell.illusion.lifecycle.v1"


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class TypedSpellIllusionSpec:
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    source_id: str
    target_id: str
    target_scope: str
    duration_unit: str
    duration_value: int
    height_delta_ft: int
    body_shape: str
    limb_arrangement: str
    carried_envelope: tuple[str, ...]
    area_scope: str
    physical_inspection: str
    research_action: str
    investigation_skill: str
    save_dc: int

    def __post_init__(self) -> None:
        for field in ("content_id", "source_record_id", "clause_id", "source_id", "target_id"):
            if not str(getattr(self, field)).strip():
                raise ValueError(f"illusion {field} is required")
        if len(self.source_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.source_fingerprint.lower()
        ):
            raise ValueError("illusion source_fingerprint must be sha256")
        if self.target_scope != "self":
            raise ValueError("illusion target_scope must be self")
        if self.duration_unit != "hours" or self.duration_value != 1:
            raise ValueError("illusion duration must be one hour")
        if isinstance(self.height_delta_ft, bool) or self.height_delta_ft not in {-1, 0, 1}:
            raise ValueError("illusion height_delta_ft must be between -1 and 1")
        if not self.body_shape.strip():
            raise ValueError("illusion body_shape is required")
        if self.limb_arrangement != "preserve":
            raise ValueError("illusion limb arrangement must be preserved")
        if set(self.carried_envelope) != {"clothing", "armor", "weapons"}:
            raise ValueError("illusion carried envelope must cover clothing, armor, and weapons")
        if not self.area_scope.strip():
            raise ValueError("illusion area_scope is required")
        if self.physical_inspection != "passes_through":
            raise ValueError("illusion physical inspection must pass through")
        if (
            self.research_action != "research"
            or self.investigation_skill != "intelligence_investigation"
        ):
            raise ValueError("illusion inspection protocol is incomplete")
        if (
            isinstance(self.save_dc, bool)
            or not isinstance(self.save_dc, int)
            or not 1 <= self.save_dc <= 50
        ):
            raise ValueError("illusion save_dc is invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "target_scope": self.target_scope,
            "duration_unit": self.duration_unit,
            "duration_value": self.duration_value,
            "height_delta_ft": self.height_delta_ft,
            "body_shape": self.body_shape,
            "limb_arrangement": self.limb_arrangement,
            "carried_envelope": list(self.carried_envelope),
            "area_scope": self.area_scope,
            "physical_inspection": self.physical_inspection,
            "research_action": self.research_action,
            "investigation_skill": self.investigation_skill,
            "save_dc": self.save_dc,
        }


@dataclass(frozen=True, slots=True)
class TypedSpellIllusionReceipt:
    schema: str
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    illusion_id: str
    expires_at: str
    state_version_before: int
    state_version_after: int
    request_fingerprint: str
    physical_inspection_result: str
    termination: str | None = None
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "illusion_id": self.illusion_id,
            "expires_at": self.expires_at,
            "state_version_before": self.state_version_before,
            "state_version_after": self.state_version_after,
            "request_fingerprint": self.request_fingerprint,
            "physical_inspection_result": self.physical_inspection_result,
            "termination": self.termination,
            "replayed": self.replayed,
        }


def apply_typed_spell_illusion(
    spec: TypedSpellIllusionSpec,
    *,
    state: dict[str, Any],
    expected_version: int,
    now: datetime,
    prior_receipt: TypedSpellIllusionReceipt | None = None,
) -> tuple[dict[str, Any], TypedSpellIllusionReceipt]:
    version = state.get("version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version != expected_version:
        raise ValueError("illusion state version is stale or invalid")
    started_at = _utc(now)
    expires_at = started_at + timedelta(hours=1)
    request_fingerprint = _fingerprint(
        {"spec": spec.as_dict(), "started_at": started_at.isoformat()}
    )
    if prior_receipt is not None:
        if prior_receipt.request_fingerprint != request_fingerprint:
            raise ValueError("illusion replay payload does not match")
        return dict(state), TypedSpellIllusionReceipt(
            **{**prior_receipt.as_dict(), "replayed": True}
        )
    illusion_id = f"{spec.source_id}:{spec.target_id}"
    envelopes = state.get("illusion_envelopes", [])
    if not isinstance(envelopes, list) or any(not isinstance(item, Mapping) for item in envelopes):
        raise ValueError("illusion state is invalid")
    updated_envelopes = [dict(item) for item in envelopes if item.get("illusion_id") != illusion_id]
    updated_envelopes.append(
        {
            "illusion_id": illusion_id,
            **spec.as_dict(),
            "started_at": started_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "physical_inspection_result": "passes_through",
            "termination": None,
        }
    )
    updated = {"version": version + 1, "illusion_envelopes": updated_envelopes}
    receipt = TypedSpellIllusionReceipt(
        schema=ILLUSION_SCHEMA,
        content_id=spec.content_id,
        source_record_id=spec.source_record_id,
        source_fingerprint=spec.source_fingerprint,
        clause_id=spec.clause_id,
        illusion_id=illusion_id,
        expires_at=expires_at.isoformat(),
        state_version_before=version,
        state_version_after=version + 1,
        request_fingerprint=request_fingerprint,
        physical_inspection_result="passes_through",
    )
    return updated, receipt


def inspect_typed_spell_illusion(
    state: Mapping[str, Any],
    *,
    illusion_id: str,
    research_action: str,
    investigation_total: int,
    now: datetime,
) -> dict[str, Any]:
    envelopes = state.get("illusion_envelopes", [])
    if not isinstance(envelopes, list):
        raise ValueError("illusion state is invalid")
    illusion = next(
        (
            item
            for item in envelopes
            if isinstance(item, Mapping) and item.get("illusion_id") == illusion_id
        ),
        None,
    )
    if illusion is None:
        raise ValueError("illusion is not active")
    expiry = datetime.fromisoformat(str(illusion["expires_at"]))
    if _utc(now) >= _utc(expiry):
        raise ValueError("illusion has expired")
    if research_action != "research":
        raise ValueError("illusion inspection requires research action")
    if isinstance(investigation_total, bool) or not isinstance(investigation_total, int):
        raise ValueError("illusion investigation total is invalid")
    dc = int(illusion["save_dc"])
    return {
        "illusion_id": illusion_id,
        "physical_inspection_result": "passes_through",
        "research_action": "research",
        "skill": "intelligence_investigation",
        "investigation_total": investigation_total,
        "save_dc": dc,
        "discerned": investigation_total >= dc,
        "checked_at": _utc(now).isoformat(),
    }


def terminate_typed_spell_illusion(
    state: Mapping[str, Any],
    *,
    expected_version: int,
    illusion_id: str,
    reason: str,
) -> dict[str, Any]:
    version = state.get("version", 0)
    if version != expected_version:
        raise ValueError("illusion termination state version is stale")
    if reason not in {"expiry", "terminate"}:
        raise ValueError("illusion termination reason is unsupported")
    envelopes = state.get("illusion_envelopes", [])
    if not isinstance(envelopes, list):
        raise ValueError("illusion state is invalid")
    found = False
    updated: list[dict[str, Any]] = []
    for item in envelopes:
        if isinstance(item, Mapping) and item.get("illusion_id") == illusion_id:
            found = True
            row = dict(item)
            row["termination"] = reason
            updated.append(row)
        else:
            updated.append(dict(item))
    if not found:
        raise ValueError("illusion is not active")
    return {"version": version + 1, "illusion_envelopes": updated}
