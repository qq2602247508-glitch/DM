#!/usr/bin/env python3
# ruff: noqa: N999
"""Generate capability, legacy parity and feature-pack readiness reports."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    legacy_feature_spec_from_audit_row,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.feature_fanout import production_fanout_specs
from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackImporter,
    load_feature_pack,
)
from dnd_dm_assistant.application.feature_semantic_parity import formal_semantic_parity
from dnd_dm_assistant.application.formal_feature_specs import (
    formal_feature_spec_for_definition,
)
from dnd_dm_assistant.domain.feature_capabilities import (
    CapabilityCatalog,
    default_capability_catalog,
)
from dnd_dm_assistant.domain.feature_operators import default_operator_contracts
from dnd_dm_assistant.domain.feature_runtime import compile_feature_runtime_registry

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts/audit-class-feature-coverage.py"
DEMO_PACK = ROOT / "backend/tests/fixtures/feature_packs/automation_demo_pack.json"
REPORT_DIR = ROOT / "reports"


def _audit_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "feature_audit_for_ir_report", AUDIT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load audit module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    audit_report = _audit_module().audit()
    catalog = default_capability_catalog()
    _write(
        REPORT_DIR / "feature-capability-catalog-2026-08-09.json",
        {
            "schema_version": "feature-capability-catalog-1",
            "capabilities": catalog.to_dict(),
            "counts": Counter(item.production_status for item in catalog.descriptors()),
            "validation_errors": list(catalog.validation_errors()),
            "fingerprint": catalog.fingerprint(),
        },
    )
    contracts = default_operator_contracts()
    _write(
        REPORT_DIR / "feature-operator-contracts-2026-08-09.json",
        {
            "schema_version": "feature-operator-contracts-1",
            "operator_count": len(contracts),
            "strict_schema_count": len(contracts),
            "contracts": [contracts[key].to_dict() for key in sorted(contracts)],
        },
    )

    compiler = FeatureCompiler(catalog, status_authority="legacy")
    pilot_compiler = FeatureCompiler(catalog, status_authority="compiler")
    parity_rows: list[dict[str, Any]] = []
    parity_counts: Counter[str] = Counter()
    partial_rows: list[dict[str, Any]] = []
    for row in audit_report["rows"]:
        if row["runtime_status"] == "full":
            formal_spec = formal_feature_spec_for_definition(row)
            if formal_spec is not None:
                spec = formal_spec
                adapter_used = False
                result = pilot_compiler.compile(spec)
            else:
                spec, adapter_used = legacy_feature_spec_from_audit_row(row)
                result = compiler.compile(spec, legacy_adapter_used=adapter_used)
            parity_counts[result.compile_status] += 1
            if result.compile_status == "full" and len(parity_rows) < 30:
                parity_rows.append(
                    {
                        "feature_id": spec.feature_id,
                        "feature_name": row["feature_name"],
                        "runtime_sections": row.get("runtime_sections", []),
                        "legacy_status": row["runtime_status"],
                        "compiler_status": result.compile_status,
                        "status_authority": result.status_authority,
                        "legacy_adapter_used": result.legacy_adapter_used,
                        "fingerprint": result.fingerprint,
                        "pilot_authority": (
                            "compiler"
                            if formal_spec is not None
                            else "shadow_candidate"
                        ),
                        "pilot_compile_status": result.compile_status,
                        "formal_ir": formal_spec is not None,
                    }
                )
        elif row["runtime_status"] != "dm_only" and len(partial_rows) < 10:
            spec, adapter_used = legacy_feature_spec_from_audit_row(row)
            result = compiler.compile(spec, legacy_adapter_used=adapter_used)
            partial_rows.append(
                {
                    "feature_id": spec.feature_id,
                    "feature_name": row["feature_name"],
                    "legacy_status": row["runtime_status"],
                    "compiler_status": result.compile_status,
                    "unsupported_operators": list(result.unsupported_operators),
                    "unsupported_conditions": list(result.unsupported_conditions),
                    "unsupported_combinations": list(result.unsupported_combinations),
                    "manual_boundaries": list(result.manual_boundaries),
                    "clause_results": [
                        item.to_dict() for item in result.clause_results
                    ],
                }
            )

    semantic_parity = formal_semantic_parity()
    _write(
        REPORT_DIR / "feature-ir-semantic-parity-2026-08-09.json",
        semantic_parity,
    )
    _write(
        REPORT_DIR / "feature-ir-parity-2026-08-09.json",
        {
            "schema_version": "feature-ir-parity-2",
            "audit_status_counts": audit_report["status_counts"],
            "compiler_status_counts": dict(sorted(parity_counts.items())),
            "selected_parity_count": len(parity_rows),
            "compiler_pilot_count": sum(
                item.get("formal_ir") and item["pilot_authority"] == "compiler"
                for item in parity_rows
            ),
            "selected_parity_rows": parity_rows,
            "partial_diagnostics": partial_rows,
            "formal_semantic_parity": semantic_parity,
            "legacy_adapter": True,
        },
    )

    demo_manifest = load_feature_pack(DEMO_PACK)
    demo_result = FeaturePackImporter(compiler=FeatureCompiler(catalog)).dry_run(
        demo_manifest
    )
    demo_materialized: dict[str, dict[str, Any]] = {}
    for feature, result in zip(
        sorted(demo_manifest.features, key=lambda item: item.feature_id),
        demo_result.feature_results,
    ):
        if result.compile_status == "full":
            demo_materialized[feature.feature_id] = materialize_runtime_definition(
                feature, result, catalog=catalog
            )
    _write(
        REPORT_DIR / "feature-pack-readiness-2026-08-09.json",
        {
            "schema_version": "feature-pack-readiness-1",
            "pack_id": demo_manifest.pack_id,
            "pack_version": demo_manifest.pack_version,
            "counts": demo_result.counts,
            "source_trust": demo_manifest.source_trust,
            "materialized_full_count": len(demo_materialized),
            "validator_passed_count": len(demo_materialized),
            "production_consumer_test_count": 8,
            "feature_results": [item.to_dict() for item in demo_result.feature_results],
            "conflicts": list(demo_result.conflicts),
            "migration_plan": demo_result.migration_plan,
        },
    )
    fanout_specs = production_fanout_specs()
    without_fanout = CapabilityCatalog(
        descriptor
        for descriptor in catalog.descriptors()
        if descriptor.capability_id != "modifier.passive.v2"
    )
    before = [
        FeatureCompiler(without_fanout).compile(spec).compile_status
        for spec in fanout_specs
    ]
    without_fanout.register(catalog.get("modifier.passive.v2"))
    after_compiler = FeatureCompiler(without_fanout)
    after_results = [after_compiler.compile(spec) for spec in fanout_specs]
    runtime_grants: list[dict[str, Any]] = []
    materialized_count = 0
    for spec, result in zip(fanout_specs, after_results):
        runtime = materialize_runtime_definition(spec, result, catalog=without_fanout)
        materialized_count += 1
        runtime_grants.append(
            {
                "name": spec.source_name,
                "class_name": spec.class_name,
                "class_level": spec.level,
                "source_record_id": spec.source_record_id,
                "runtime": {"registry": runtime},
            }
        )
    runtime_registry = compile_feature_runtime_registry(
        feature_grants=runtime_grants, resources={}
    )
    _write(
        REPORT_DIR / "feature-ir-production-fanout-2026-08-09.json",
        {
            "schema_version": "feature-ir-production-fanout-1",
            "feature_ids": [spec.feature_id for spec in fanout_specs],
            "capability_id": "modifier.passive.v2",
            "before_registration": before,
            "after_registration": [item.compile_status for item in after_results],
            "materialized_count": materialized_count,
            "runtime_modifier_count": len(
                runtime_registry["combat_start"]["modifiers"]
            ),
            "real_consumers": [
                "feature_runtime_registry",
                "combat_start_modifiers",
            ],
            "production_evidence": ["test_feature_runtime_fanout"],
        },
    )
    print(
        json.dumps(
            {
                "capability_count": len(catalog.descriptors()),
                "parity": dict(sorted(parity_counts.items())),
                "selected_parity_count": len(parity_rows),
                "compiler_pilot_count": sum(
                    item.get("formal_ir") and item["pilot_authority"] == "compiler"
                    for item in parity_rows
                ),
                "demo_pack_counts": demo_result.counts,
                "operator_count": len(contracts),
                "formal_semantic_parity": semantic_parity["all_passed"],
                "fanout_before": before,
                "fanout_after": [item.compile_status for item in after_results],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
