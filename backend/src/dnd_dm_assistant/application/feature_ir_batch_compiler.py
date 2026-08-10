"""Deterministic batch compilation for real feature-audit rows.

This layer normalizes the audit corpus and optionally compiles explicitly
authored FeatureSpec values.  It is deliberately conservative: an audit row
without an explicit typed spec is a partial candidate, never an executable
runtime definition.  The compiler is therefore useful for previewing a pack
and proving stable fingerprints before any production consumer is changed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from dnd_dm_assistant.application.feature_compiler import FeatureCompiler
from dnd_dm_assistant.domain.feature_ir import FeatureIRValidationError, FeatureSpec

BATCH_SCHEMA_VERSION = "feature-ir-batch-1"
TRUSTED_SOURCE_TRUSTS = frozenset({"authored_ir", "verified_mapping"})


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def stable_feature_id(row: Mapping[str, Any]) -> str:
    explicit = row.get("feature_id") or row.get("stable_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    identity = {
        "scope": row.get("scope"),
        "class_name": row.get("class_name"),
        "subclass_name": row.get("subclass_name"),
        "level": row.get("level"),
        "feature_name": row.get("feature_name"),
        "source_record_id": row.get("source_record_id"),
    }
    return "class-feature:" + _fingerprint(identity)[:16]


def normalize_audit_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stable source record used for preview and diffing."""

    feature_id = stable_feature_id(row)
    normalized = {
        "feature_id": feature_id,
        "class_name": row.get("class_name"),
        "subclass_name": row.get("subclass_name"),
        "level": row.get("level"),
        "feature_name": row.get("feature_name"),
        "source_record_id": row.get("source_record_id"),
        "source_trust": row.get("source_trust") or "generated_draft",
        "source_parse": row.get("source_parse"),
        "source_completeness": row.get("source_completeness"),
        "trigger": row.get("trigger"),
        "conditions": row.get("conditions") or [],
        "activation": row.get("activation"),
        "action_economy": row.get("action_economy"),
        "target_policy": row.get("target_policy"),
        "input_requirements": row.get("input_requirements") or [],
        "resource": row.get("resource") or row.get("resource_key"),
        "frequency": row.get("frequency"),
        "duration": row.get("duration"),
        "expiry": row.get("expiry"),
        "effect_operator": row.get("effect_operator") or row.get("effects") or [],
        "producer": row.get("producer"),
        "consumer": row.get("consumer"),
        "persisted_state": row.get("persisted_state"),
        "cas_support": row.get("cas_support"),
        "idempotency_support": row.get("idempotency_support"),
        "materializer": row.get("materializer"),
        "validator": row.get("validator"),
        "production_evidence": row.get("production_evidence") or [],
        "remaining_blocker": row.get("remaining_blocker")
        or row.get("blocker")
        or row.get("readiness_status"),
        "runtime_status": row.get("runtime_status"),
    }
    source_payload = dict(normalized)
    source_payload.pop("runtime_status", None)
    normalized["source_fingerprint"] = _fingerprint(source_payload)
    return normalized


@dataclass(frozen=True)
class BatchFeatureResult:
    feature_id: str
    source_fingerprint: str
    spec_fingerprint: str | None
    compiler_status: str
    status_authority: str
    blockers: tuple[str, ...]
    materialized: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "source_fingerprint": self.source_fingerprint,
            "spec_fingerprint": self.spec_fingerprint,
            "compiler_status": self.compiler_status,
            "status_authority": self.status_authority,
            "blockers": list(self.blockers),
            "materialized": self.materialized,
        }


def _spec_by_id(
    specs: Iterable[FeatureSpec],
) -> dict[str, FeatureSpec]:
    result: dict[str, FeatureSpec] = {}
    for spec in specs:
        if spec.feature_id in result:
            raise ValueError(f"duplicate batch FeatureSpec: {spec.feature_id}")
        result[spec.feature_id] = spec
    return result


def compile_audit_batch(
    rows: Iterable[Mapping[str, Any]],
    *,
    specs: Iterable[FeatureSpec] = (),
    compiler: FeatureCompiler | None = None,
    mode: str = "preview",
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile a real corpus slice without mutating the formal audit.

    ``specs`` must be explicit authored/verified IR.  Rows without a matching
    spec remain partial with ``missing_typed_spec``.  ``mode`` is metadata only
    (``dry-run``, ``preview``, ``apply`` or ``replay``); applying a batch still
    requires the normal FeaturePackImporter/production path.
    """

    if mode not in {"dry-run", "preview", "apply", "replay"}:
        raise ValueError(f"unsupported batch mode: {mode}")
    normalized_rows = sorted(
        (normalize_audit_row(row) for row in rows),
        key=lambda item: item["feature_id"],
    )
    spec_map = _spec_by_id(specs)
    active_compiler = compiler or FeatureCompiler(status_authority="compiler")
    existing_by_id = {
        str(item.get("feature_id")): item
        for item in (existing or {}).get("features", [])
        if isinstance(item, Mapping)
    }
    results: list[BatchFeatureResult] = []
    conflicts: list[str] = []
    for row in normalized_rows:
        feature_id = str(row["feature_id"])
        spec = spec_map.get(feature_id)
        spec_fingerprint: str | None = None
        if spec is None:
            status = "partial"
            authority = "none"
            blockers = ("missing_typed_spec",)
            materialized = False
        else:
            spec_fingerprint = _fingerprint(spec.to_dict())
            if spec.source_trust not in TRUSTED_SOURCE_TRUSTS:
                status = "partial"
                authority = "none"
                blockers = ("untrusted_source",)
                materialized = False
            else:
                compiled = active_compiler.compile(spec)
                status = compiled.compile_status
                authority = (
                    "compiler"
                    if status == "full"
                    else "none"
                )
                blockers = tuple(compiled.blockers)
                materialized = status == "full"
        previous = existing_by_id.get(feature_id)
        if previous is not None:
            previous_fp = str(previous.get("source_fingerprint") or "")
            if previous_fp and previous_fp != row["source_fingerprint"]:
                conflicts.append(f"{feature_id}: source fingerprint conflict")
            previous_spec_fp = str(previous.get("spec_fingerprint") or "")
            if previous_spec_fp and previous_spec_fp != str(spec_fingerprint or ""):
                conflicts.append(f"{feature_id}: spec fingerprint conflict")
        results.append(
            BatchFeatureResult(
                feature_id=feature_id,
                source_fingerprint=str(row["source_fingerprint"]),
                spec_fingerprint=spec_fingerprint,
                compiler_status=status,
                status_authority=authority,
                blockers=tuple(dict.fromkeys(blockers)),
                materialized=materialized,
            )
        )
    counts: dict[str, int] = {"full": 0, "partial": 0, "manual": 0, "invalid": 0}
    for item in results:
        counts[item.compiler_status] = counts.get(item.compiler_status, 0) + 1
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "mode": mode,
        "audit_total": len(normalized_rows),
        "candidate_feature_count": len(normalized_rows),
        "compiler_status_counts": counts,
        "direct_ir_authority_count": sum(
            item.status_authority == "compiler" for item in results
        ),
        "materialized_count": sum(item.materialized for item in results),
        "conflicts": sorted(set(conflicts)),
        "rollback_plan": {
            "required": bool(conflicts),
            "strategy": "discard artifact and restore pinned pack version",
            "runtime_status_mutated": False,
        },
        "features": [item.to_dict() for item in results],
    }


def parse_feature_specs(raw_specs: Iterable[object]) -> tuple[FeatureSpec, ...]:
    """Parse explicit specs for CLI callers and fail closed on schema errors."""

    parsed: list[FeatureSpec] = []
    for index, raw in enumerate(raw_specs):
        try:
            parsed.append(FeatureSpec.from_dict(raw, f"batch.features[{index}]"))
        except FeatureIRValidationError as exc:
            raise ValueError(str(exc)) from exc
    return tuple(parsed)
