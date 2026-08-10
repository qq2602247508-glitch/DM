"""Deterministic production-harvest planning for authored Feature IR."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.harvest_feature_specs import harvest_feature_specs
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

HARVEST_PLAN_SCHEMA_VERSION = "feature-ir-production-harvest-plan-1"


def _audit_row_for_spec(
    spec: FeatureSpec,
    rows: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    candidates = [
        row
        for row in rows
        if row.get("class_name") == spec.class_name
        and row.get("subclass_name") == spec.subclass_name
        and int(row.get("level") or 0) == int(spec.level or 0)
        and row.get("source_record_id") == spec.source_record_id
        and hashlib.sha256(
            str(row.get("source_description") or "").encode("utf-8")
        ).hexdigest()
        == spec.compatibility.get("source_excerpt_sha256")
    ]
    return candidates[0] if len(candidates) == 1 else None


def build_production_harvest_plan(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    audit_rows = list(rows)
    compiler = FeatureCompiler(status_authority="compiler")
    candidates: list[dict[str, Any]] = []
    for spec in sorted(harvest_feature_specs(), key=lambda item: item.feature_id):
        row = _audit_row_for_spec(spec, audit_rows)
        result = compiler.compile(spec)
        materialized = None
        materializer_error = None
        if result.compile_status == "full":
            try:
                materialized = materialize_runtime_definition(
                    spec,
                    result,
                    catalog=compiler.catalog,
                )
            except (TypeError, ValueError) as exc:
                materializer_error = str(exc)
        capability_ids = sorted(
            {
                capability_id
                for clause in result.clause_results
                for capability_id in clause.capability_ids
            }
        )
        descriptors = [
            compiler.catalog.get(capability_id)
            for capability_id in capability_ids
        ]
        descriptors = [item for item in descriptors if item is not None]
        ready = (
            row is not None
            and row.get("runtime_status") in {"partial", "full"}
            and result.compile_status == "full"
            and materialized is not None
            and materializer_error is None
            and spec.source_trust == "authored_ir"
        )
        candidates.append(
            {
                "feature_id": spec.feature_id,
                "source_record_id": spec.source_record_id,
                "class_name": spec.class_name,
                "subclass_name": spec.subclass_name,
                "level": spec.level,
                "source_fingerprint": spec.fingerprint(),
                "source_runtime_status": row.get("runtime_status") if row else None,
                "clause_count": len(spec.clauses),
                "clause_contract_summary": [
                    {
                        "clause_id": clause.clause_id,
                        "trigger": clause.trigger,
                        "action_economy": clause.action_economy,
                        "target": clause.targeting.kind if clause.targeting else None,
                        "operators": [effect.operator for effect in clause.effects],
                    }
                    for clause in spec.clauses
                ],
                "existing_capability_ids": capability_ids,
                "existing_materializer_ids": sorted(
                    {item.materializer_id for item in descriptors}
                ),
                "existing_producers": sorted({item.producer for item in descriptors}),
                "existing_consumers": sorted({item.consumer for item in descriptors}),
                "persistence_requirements": sorted(
                    {item.persisted_state for item in descriptors}
                ),
                "cas_requirements": sorted(
                    {
                        "compare_and_swap"
                        for item in descriptors
                        if item.cas_support
                    }
                ),
                "idempotency_requirements": sorted(
                    {
                        "idempotent_replay"
                        for item in descriptors
                        if item.idempotency_support
                    }
                ),
                "ui_requirements": list(result.required_ui),
                "compiler_status": result.compile_status,
                "compiler_blockers": list(result.blockers),
                "materializer_error": materializer_error,
                "harvest_ready": ready,
                "eligibility_reason": (
                    "all clauses compile and materialize through production_closed capabilities"
                    if ready
                    else "source row, compiler or materializer gate is not production ready"
                ),
                "expected_status_after_authored_ir": "full" if ready else "partial",
                "portable_external_pack": ready,
            }
        )
    return {
        "schema_version": HARVEST_PLAN_SCHEMA_VERSION,
        "candidate_count": len(candidates),
        "harvest_ready_count": sum(item["harvest_ready"] for item in candidates),
        "selected_feature_ids": [
            item["feature_id"] for item in candidates if item["harvest_ready"]
        ],
        "candidates": candidates,
    }
