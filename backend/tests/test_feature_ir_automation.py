from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackImporter,
    FeaturePackImportError,
    FeaturePackManifest,
    FeaturePackRegistry,
    load_feature_pack,
)
from dnd_dm_assistant.application.formal_feature_specs import (
    formal_feature_spec_for_definition,
)
from dnd_dm_assistant.domain.feature_capabilities import (
    CapabilityCatalog,
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
    params: dict[str, Any] = {
        "grant_proficiency": {
            "proficiency_kind": "skill",
            "asset_id": "stealth",
            "operation": "grant",
        },
        "grant_language": {"language_id": "elvish", "operation": "grant"},
        "grant_spell": {
            "spell_id": "shield",
            "source_class": "wizard",
            "casting_ability": "intelligence",
            "grant_mode": "known",
        },
        "prepare_spell": {
            "spell_id": "mage_armor",
            "source_class": "wizard",
            "preparation_mode": "prepared",
        },
        "grant_passive_modifier": {
            "stat": "speed_ft",
            "operation": "add",
            "value": 1,
            "scope": "self",
            "applies_when": "always",
        },
        "add_modifier": {
            "stat": "speed_ft",
            "operation": "add",
            "value": 1,
            "scope": "self",
            "applies_when": "always",
        },
    }.get(operator, {})
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
            "source_trust": "authored_ir",
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
                    "effects": [{"operator": operator, "parameters": params}],
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
    result = FeatureCompiler().compile(parsed)
    assert result.compile_status == "invalid"
    assert any("executable" in item for item in result.blockers)


def test_capability_catalog_requires_production_evidence_and_cas() -> None:
    with pytest.raises(ValueError, match="wildcard"):
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
    operator = "grant_passive_modifier"
    specs = tuple(_spec(f"fanout:{index}", operator) for index in range(6))
    base_catalog = default_capability_catalog()
    catalog = CapabilityCatalog(
        descriptor
        for descriptor in base_catalog.descriptors()
        if descriptor.capability_id != "modifier.passive.v2"
    )
    before = FeatureCompiler(catalog)
    assert [before.compile(spec).compile_status for spec in specs] == ["partial"] * 6

    catalog.register(default_capability_catalog().get("modifier.passive.v2"))
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
    registry = FeaturePackRegistry(tmp_path)
    assert registry.lookup("demo:proficiency") is not None
    assert registry.lookup("demo:unknown-1") is None
    registry.pin_character("character-1", "automation-demo", "1.0.0")
    assert registry.character_pin("character-1") == {
        "pack_id": "automation-demo",
        "pack_version": "1.0.0",
    }

    changed = json.loads(DEMO_PACK.read_text(encoding="utf-8"))
    changed["features"][0]["source_name"] = "changed"
    changed_manifest = FeaturePackManifest.from_dict(changed)
    with pytest.raises(FeaturePackImportError, match="pack/version conflict"):
        importer.apply(changed_manifest)


def test_legacy_shadow_parity_selects_formal_and_verified_rows() -> None:
    spec = importlib.util.spec_from_file_location("feature_audit", AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.audit()
    formal = [row for row in report["rows"] if row.get("formal_ir")]
    assert len(formal) == 33
    assert sum(row["source_trust"] == "authored_ir" for row in formal) == 29
    assert sum(row["source_trust"] == "verified_mapping" for row in formal) == 4
    assert {
        row["status_authority"] for row in formal
    } == {"compiler", "verified_mapping"}


def test_audit_rows_expose_shadow_fields_without_changing_499_statuses() -> None:
    spec = importlib.util.spec_from_file_location("feature_audit_shadow", AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.audit()
    assert report["status_counts"] == {"full": 328, "partial": 110, "dm_only": 61}
    assert report["compiler_pilot"]["count"] == 33
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


def test_combat_inspiration_materializes_to_real_attack_intervention_contract() -> None:
    spec = importlib.util.spec_from_file_location(
        "formal_feature_specs_for_test",
        ROOT / "backend/src/dnd_dm_assistant/application/formal_feature_specs.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definition = {
        "name": "战斗激励Combat Inspiration",
        "class_name": "吟游诗人",
        "subclass_name": "勇气学院",
        "class_level": 3,
        "source_record_id": "2709144090ad73a4c316bfe6",
    }
    feature = module.formal_feature_spec_for_definition(definition)
    assert feature is not None
    result = FeatureCompiler().compile(feature)
    assert result.compile_status == "full"
    runtime = materialize_runtime_definition(feature, result)
    action = runtime["actions"]["combat_inspiration"]
    assert action["kind"] == "attack_roll_intervention"
    assert action["source_die_key"] == "bardic_inspiration_die"
    assert action["modes"] == ["defense", "offense"]
    assert action["runtime_execution"]["consumer"] == "player_attack_resolution"


@pytest.mark.parametrize(
    ("definition", "expected_section"),
    [
        (
            {
                "name": "心灵防御 Psychic",
                "class_name": "术士",
                "subclass_name": "畸变术法",
                "class_level": 6,
            },
            "combat_start",
        ),
        (
            {
                "name": "高效重击 Superior",
                "class_name": "战士",
                "subclass_name": "勇士",
                "class_level": 15,
            },
            "combat_start",
        ),
        (
            {
                "name": "操命本事 Implements of",
                "class_name": "武僧",
                "subclass_name": "命流武者",
                "class_level": 3,
            },
            "proficiencies",
        ),
        (
            {
                "name": "刺客工具 Assassin's",
                "class_name": "游荡者",
                "subclass_name": "刺客",
                "class_level": 3,
            },
            "proficiencies",
        ),
        (
            {
                "name": "法术抗性 Spell Resistance",
                "class_name": "法师",
                "subclass_name": "防护师",
                "class_level": 14,
            },
            "combat_start",
        ),
        (
            {
                "name": "灵能力量 Psionic",
                "class_name": "战士",
                "subclass_name": "灵能武士",
                "class_level": 3,
            },
            "resources",
        ),
        (
            {
                "name": "灵能力量 Psionic",
                "class_name": "游荡者",
                "subclass_name": "魂刃",
                "class_level": 3,
            },
            "resources",
        ),
    ],
)
def test_new_authored_ir_slice_materializes_against_existing_full_consumers(
    definition: dict[str, Any],
    expected_section: str,
) -> None:
    feature = formal_feature_spec_for_definition(definition)
    assert feature is not None
    result = FeatureCompiler().compile(feature)
    assert result.compile_status == "full"
    runtime = materialize_runtime_definition(feature, result)
    assert runtime["automation_status"] == "full"
    section = runtime[expected_section]
    assert section
    if isinstance(section, dict):
        entries = [
            entry
            for value in section.values()
            for entry in (
                value if isinstance(value, list) else [value]
            )
            if isinstance(entry, dict)
        ]
    else:
        entries = list(section)
    assert all(
        isinstance(entry, dict)
        and entry.get("runtime_execution", {}).get("status") == "ready"
        for entry in entries
    )


def test_resource_profile_materializer_preserves_partial_short_rest_recovery() -> None:
    definition = {
        "name": "灵能力量 Psionic",
        "class_name": "战士",
        "subclass_name": "灵能武士",
        "class_level": 3,
    }
    feature = formal_feature_spec_for_definition(definition)
    assert feature is not None
    result = FeatureCompiler().compile(feature)
    runtime = materialize_runtime_definition(feature, result)
    profile = runtime["resources"]["$feature_resource"]
    assert profile["resource_kind"] == "psionic_dice"
    assert profile["recovery"] == "custom"
    assert profile["recovery_events"] == [
        {"rest": "short_rest", "operation": "restore", "amount": 1},
        {"rest": "long_rest", "operation": "set_to_max"},
    ]
