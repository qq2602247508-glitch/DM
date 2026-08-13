"""Source-bound typed spell target fan-out contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TypedSpellTargetSpec:
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    target_kind: str
    base_target_count: int
    range_ft: int | None
    source_slot_level: int
    target_count_increment: int
    max_target_count: int = 64

    def __post_init__(self) -> None:
        if not self.content_id.strip():
            raise ValueError("typed spell target content_id is required")
        if not self.source_record_id.strip():
            raise ValueError("typed spell target source_record_id is required")
        if len(self.source_fingerprint.strip()) < 32:
            raise ValueError("typed spell target source_fingerprint is required")
        if not self.clause_id.strip():
            raise ValueError("typed spell target clause_id is required")
        if self.target_kind != "one_creature":
            raise ValueError("typed spell target fan-out requires one_creature source target")
        if self.base_target_count < 1:
            raise ValueError("typed spell target base_target_count must be positive")
        if self.source_slot_level < 0:
            raise ValueError("typed spell target source_slot_level must be non-negative")
        if self.target_count_increment < 0:
            raise ValueError("typed spell target increment must be non-negative")
        if self.range_ft is not None and self.range_ft < 0:
            raise ValueError("typed spell target range must be non-negative")
        if self.base_target_count > self.max_target_count:
            raise ValueError("typed spell target base count exceeds maximum")

    def as_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "target_kind": self.target_kind,
            "base_target_count": self.base_target_count,
            "range_ft": self.range_ft,
            "source_slot_level": self.source_slot_level,
            "target_count_increment": self.target_count_increment,
            "max_target_count": self.max_target_count,
        }


@dataclass(frozen=True)
class TypedSpellTargetReceipt:
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    slot_level: int
    maximum_target_count: int
    target_ids: tuple[str, ...]
    request_fingerprint: str
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "spell.target.fanout.v1",
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "slot_level": self.slot_level,
            "maximum_target_count": self.maximum_target_count,
            "target_ids": list(self.target_ids),
            "request_fingerprint": self.request_fingerprint,
            "replayed": self.replayed,
        }


def resolve_typed_spell_targets(
    spec: TypedSpellTargetSpec,
    *,
    slot_level: int,
    target_ids: tuple[str, ...] | list[str],
    prior_receipt: TypedSpellTargetReceipt | None = None,
) -> TypedSpellTargetReceipt:
    """Resolve target cardinality and return a deterministic producer receipt."""

    if slot_level < spec.source_slot_level:
        raise ValueError("typed spell target slot_level is below source level")
    normalized = tuple(str(item).strip() for item in target_ids)
    if not normalized or any(not item for item in normalized):
        raise ValueError("typed spell target ids must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("typed spell target ids must be unique")
    maximum = min(
        spec.max_target_count,
        spec.base_target_count
        + max(0, slot_level - spec.source_slot_level) * spec.target_count_increment,
    )
    if len(normalized) > maximum:
        raise ValueError(f"typed spell target count exceeds maximum {maximum}")
    if len(normalized) < spec.base_target_count:
        raise ValueError("typed spell target count is below the source minimum")
    request_fingerprint = _fingerprint(
        {"spec": spec.as_dict(), "slot_level": slot_level, "target_ids": normalized}
    )
    if prior_receipt is not None:
        if prior_receipt.request_fingerprint != request_fingerprint:
            raise ValueError("typed spell target replay payload does not match")
        return TypedSpellTargetReceipt(
            content_id=prior_receipt.content_id,
            source_record_id=prior_receipt.source_record_id,
            source_fingerprint=prior_receipt.source_fingerprint,
            clause_id=prior_receipt.clause_id,
            slot_level=prior_receipt.slot_level,
            maximum_target_count=prior_receipt.maximum_target_count,
            target_ids=prior_receipt.target_ids,
            request_fingerprint=prior_receipt.request_fingerprint,
            replayed=True,
        )
    return TypedSpellTargetReceipt(
        content_id=spec.content_id,
        source_record_id=spec.source_record_id,
        source_fingerprint=spec.source_fingerprint,
        clause_id=spec.clause_id,
        slot_level=slot_level,
        maximum_target_count=maximum,
        target_ids=normalized,
        request_fingerprint=request_fingerprint,
    )
