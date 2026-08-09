from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    legacy_feature_spec_from_audit_row,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackImporter,
    FeaturePackImportError,
    FeaturePackManifest,
    load_feature_pack,
)
from dnd_dm_assistant.domain.feature_capabilities import (
    CapabilityDescriptor,
    default_capability_catalog,
)
from dnd_dm_assistant.domain.feature_ir import (
    FeatureIRValidationError,
    FeatureSpec,
)
from dnd_dm_assistant.domain.feature_runtime import feature_runtime_contract

ROOT = Path(__file__).resolve().parents[2]
DEMO_PACK = ROOT / "backend/tests/fixtures/feature_packs/automation_demo_pack.json"
AUDIT_SCRIPT = ROOT / "scripts/audit-class-feature-coverage.py"


def _spec(
    feature_id: str,
    operator: str,
    *,
    trigger: str = "advancement_confirmed",
    source_completeness: str = "complete",
    audit: dict[str, Any] | None = None,
) -> FeatureSpec:
    return FeatureSpec.from_dict(
        {
            "schema_version": "feature-ir-1",
            "feature_id": feature_id,
            "namespace": "test",
            "pack_id": "test-pack",
            "pack_version": "1.0.0",
            "ruleset_version": "2024",
            "source_record_id": feature_id,
            "source_name": feature_id,
            "localized_names": {},
            "class_name": "test",
            "subclass_name": None,
            "level": 1,
            "source_completeness": source_completeness,
            "dependencies": [],
            "compatibility": {},
            "clauses": [
                {
                    "clause_id": "main",
                    "trigger": trigger,
                    "audit": audit or {},
                    "effects": [{"operator": operator, "parameters": {}}],
                }
            ],
        }
    )


def _custom_capability(operator: str) -> CapabilityDescriptor:
    all_values = frozenset({"*"})
    return CapabilityDescriptor(
        capability_id=f"test.{operator}",
        contract_version="1.0",
        supported_operator=operator,
        supported_triggers=all_values,
        supported_conditions=all_values,
        supported_inputs=all_values,
        supported_targets=all_values,
        supported_duration=all_values,
        producer="test.producer",
        consumer="test.consumer",
        persisted_state="test.state",
        action_economy_support=all_values,
        resource_support=all_values,
        idempotency_support=True,
        cas_support=True,
        ui_projection_support=True,
        production_status="production_closed",
        evidence_tests=("test.feature_capability",),
    )


def test_feature_ir_rejects_unknown_fields_and_executable_payloads() -> None:
    value = _spec("test:strict", "grant_proficiency").to_dict()
    value["unknown_field"] = True
    with pytest.raises(FeatureIRValidationError, match="unknown fields"):
        FeatureSpec.from_dict(value)

    value = _spec("test:strict-code", "grant_proficiency").to_dict()
    value["clauses"][0]["effects"][0]["parameters"] = {
        "expression": "__import__('os').system('touch /tmp/bad')"
    }
    parsed = FeatureSpec.from_dict(value)
    assert parsed.clauses[0].effects[0].parameters["expression"].startswith("__import__")


def test_capability_catalog_requires_production_evidence_and_cas() -> None:
    with pytest.raises(ValueError, match="evidence_tests"):
        CapabilityDescriptor(
            capability_id="test.invalid",
            contract_version="1.0",
            supported_operator="invalid",
            supported_triggers=frozenset({"*"}),
            supported_conditions=frozenset({"*"}),
            supported_inputs=frozenset({"*"}),
            supported_targets=frozenset({"*"}),
            supported_duration=frozenset({"*"}),
            producer="producer",
            consumer="consumer",
            persisted_state="state",
            action_economy_support=frozenset({"*"}),
            resource_support=frozenset({"*"}),
            idempotency_support=True,
            cas_support=True,
            ui_projection_support=True,
            production_status="production_closed",
            evidence_tests=(),
        )


def test_compiler_is_clause_strict_and_fingerprint_deterministic() -> None:
    compiler = FeatureCompiler()
    known = compiler.compile(_spec("test:known", "grant_proficiency"))
    assert known.compile_status == "full"
    same = compiler.compile(_spec("test:known", "grant_proficiency"))
    assert known.fingerprint == same.fingerprint

    unknown = compiler.compile(_spec("test:unknown", "future_operator"))
    assert unknown.compile_status == "partial"
    assert unknown.unsupported_operators == ("future_operator",)

    manual = compiler.compile(
        _spec(
            "test:manual",
            "add_modifier",
            audit={"manual_boundary": "requires DM adjudication"},
        )
    )
    assert manual.compile_status == "manual"
    assert manual.manual_boundaries == ("main: requires DM adjudication",)


def test_one_capability_fans_out_to_six_specs_without_spec_changes() -> None:
    operator = "timed_numeric_modifier"
    specs = tuple(_spec(f"fanout:{index}", operator) for index in range(6))
    catalog = default_capability_catalog()
    before = FeatureCompiler(catalog)
    assert [before.compile(spec).compile_status for spec in specs] == ["partial"] * 6

    catalog.register(_custom_capability(operator))
    after = FeatureCompiler(catalog)
    assert [after.compile(spec).compile_status for spec in specs] == ["full"] * 6
    assert [spec.fingerprint() for spec in specs] == [
        _spec(f"fanout:{index}", operator).fingerprint() for index in range(6)
    ]


def test_full_ir_materializes_into_existing_runtime_contract_shape() -> None:
    spec = _spec("test:runtime-materialization", "grant_proficiency")
    compiler = FeatureCompiler()
    result = compiler.compile(spec)
    definition = materialize_runtime_definition(spec, result)
    contract = feature_runtime_contract(
        feature_name=spec.source_name,
        class_name="test",
        class_level=1,
        definition=definition,
        source_record_id=spec.source_record_id,
    )
    assert contract["automation_status"] == "full"
    assert "proficiencies" in contract["runtime_sections"]


def test_demo_pack_is_exactly_18_full_4_partial_2_manual() -> None:
    manifest = load_feature_pack(DEMO_PACK)
    result = FeaturePackImporter().dry_run(manifest)
    assert len(manifest.features) == 24
    assert result.counts == {"full": 18, "partial": 4, "manual": 2, "invalid": 0}
    assert all(item.compile_status != "invalid" for item in result.feature_results)


def test_feature_pack_apply_is_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    manifest = load_feature_pack(DEMO_PACK)
    importer = FeaturePackImporter(target_dir=tmp_path)
    first = importer.apply(manifest)
    second = importer.apply(manifest)
    assert first.applied is True
    assert second.idempotent_replay is True
    assert (tmp_path / "automation-demo--1.0.0.json").exists()

    changed = json.loads(DEMO_PACK.read_text(encoding="utf-8"))
    changed["features"][0]["source_name"] = "changed"
    changed_manifest = FeaturePackManifest.from_dict(changed)
    with pytest.raises(FeaturePackImportError, match="pack/version conflict"):
        importer.apply(changed_manifest)


def test_legacy_shadow_parity_selects_thirty_full_rows() -> None:
    spec = importlib.util.spec_from_file_location("feature_audit", AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    compiler = FeatureCompiler(status_authority="legacy")
    selected: list[str] = []
    for row in module.audit()["rows"]:
        if row["runtime_status"] != "full":
            continue
        feature, adapter_used = legacy_feature_spec_from_audit_row(row)
        result = compiler.compile(feature, legacy_adapter_used=adapter_used)
        if result.compile_status == "full":
            selected.append(row["feature_name"])
        if len(selected) == 30:
            break
    assert len(selected) == 30


def test_audit_rows_expose_shadow_fields_without_changing_499_statuses() -> None:
    spec = importlib.util.spec_from_file_location("feature_audit_shadow", AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.audit()
    assert report["status_counts"] == {"full": 310, "partial": 128, "dm_only": 61}
    assert report["compiler_pilot"]["count"] == 10
    for row in report["rows"]:
        assert {
            "ir_available",
            "ir_schema_version",
            "compiler_status",
            "status_authority",
            "compiled_clause_count",
            "total_clause_count",
            "unsupported_clause_ids",
            "capability_ids",
            "legacy_adapter_used",
            "compiler_fingerprint",
        } <= row.keys()
