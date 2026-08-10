from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackImporter,
    FeaturePackManifest,
    FeaturePackRegistry,
    load_feature_pack,
)
from dnd_dm_assistant.application.feature_semantic_parity import formal_semantic_parity
from dnd_dm_assistant.domain.feature_blocks import feature_trigger_block_errors
from dnd_dm_assistant.domain.feature_capabilities import (
    CapabilityCatalog,
    default_capability_catalog,
)
from dnd_dm_assistant.domain.feature_ir import FeatureIRValidationError, FeatureSpec
from dnd_dm_assistant.domain.feature_operators import default_operator_contracts
from dnd_dm_assistant.domain.feature_runtime import (
    compile_feature_runtime_registry,
    feature_runtime_contract,
)

ROOT = Path(__file__).resolve().parents[2]
DEMO_PACK = ROOT / "backend/tests/fixtures/feature_packs/automation_demo_pack.json"


def _spec(
    feature_id: str,
    operator: str,
    parameters: dict[str, object],
    *,
    trigger: str = "advancement_confirmed",
) -> FeatureSpec:
    return FeatureSpec.from_dict(
        {
            "schema_version": "feature-ir-1",
            "feature_id": feature_id,
            "namespace": "hardening",
            "pack_id": "hardening",
            "pack_version": "1.0.0",
            "ruleset_version": "2024",
            "source_record_id": feature_id,
            "source_name": feature_id,
            "source_trust": "authored_ir",
            "localized_names": {},
            "class_name": "游侠",
            "subclass_name": None,
            "level": 1,
            "source_completeness": "complete",
            "clauses": [
                {
                    "clause_id": "main",
                    "trigger": trigger,
                    "activation": "automatic",
                    "action_economy": "none",
                    "targeting": {"kind": "self", "parameters": {}},
                    "effects": [{"operator": operator, "parameters": parameters}],
                }
            ],
            "dependencies": [],
            "compatibility": {},
        }
    )


def test_every_production_closed_capability_is_contract_backed_and_non_wildcard() -> None:
    catalog = default_capability_catalog()
    assert catalog.validation_errors() == ()
    contracts = default_operator_contracts()
    assert len(contracts) >= 28
    for descriptor in catalog.descriptors():
        if descriptor.production_status != "production_closed":
            continue
        assert descriptor.supported_operator in contracts
        assert "*" not in descriptor.supported_triggers
        assert "*" not in descriptor.supported_conditions
        assert "*" not in descriptor.supported_inputs
        assert "*" not in descriptor.supported_targets
        assert "*" not in descriptor.supported_duration
        assert "*" not in descriptor.action_economy_support
        assert "*" not in descriptor.resource_support
        assert descriptor.materializer_id


@pytest.mark.parametrize(
    ("operator", "parameters"),
    [
        (
            "grant_proficiency",
            {"proficiency_kind": "skill", "asset_id": "stealth", "operation": "grant"},
        ),
        ("grant_language", {"language_id": "elvish", "operation": "grant"}),
        (
            "grant_spell",
            {
                "spell_id": "shield",
                "source_class": "wizard",
                "casting_ability": "intelligence",
                "grant_mode": "known",
            },
        ),
        (
            "prepare_spell",
            {"spell_id": "mage_armor", "source_class": "wizard", "preparation_mode": "prepared"},
        ),
        ("restore_resource", {"resource_key": "charge", "operation": "set_to_max", "amount": 1}),
        (
            "add_modifier",
            {
                "stat": "speed_ft",
                "operation": "add",
                "value": 1,
                "scope": "self",
                "applies_when": "always",
            },
        ),
        ("grant_movement_mode", {"mode": "climb", "speed_source": "current_speed"}),
        ("grant_sight_mode", {"mode": "blindsight", "range_ft": 30}),
        (
            "zero_hp_intervention",
            {
                "trigger": "would_drop_to_zero_hit_points",
                "replacement_hp": "3*paladin_level",
                "resource_key": "sentinel",
                "eligibility": {"minimum_level": 15},
                "reset": "long_rest",
            },
        ),
    ],
)
def test_minimal_valid_operator_materializes(operator: str, parameters: dict[str, object]) -> None:
    spec = _spec(
        f"hardening:{operator}",
        operator,
        parameters,
        trigger="damage_before_apply"
        if operator == "zero_hp_intervention"
        else "advancement_confirmed",
    )
    result = FeatureCompiler().compile(spec)
    assert result.compile_status == "full", result.to_dict()
    definition = materialize_runtime_definition(spec, result)
    assert any(value for value in definition.values())


def test_empty_unknown_and_executable_operator_parameters_fail_closed() -> None:
    empty = _spec("hardening:empty", "grant_proficiency", {})
    result = FeatureCompiler().compile(empty)
    assert result.compile_status == "invalid"
    assert any("invalid_parameters" in item for item in result.blockers)

    executable = _spec(
        "hardening:exec",
        "grant_language",
        {"language_id": "elvish", "operation": "grant", "module": "os"},
    )
    result = FeatureCompiler().compile(executable)
    assert result.compile_status == "invalid"
    assert any("executable" in item for item in result.blockers)


def test_formal_and_verified_mappings_have_parity_and_authority() -> None:
    report = formal_semantic_parity()
    assert report["feature_count"] == 33
    assert report["all_passed"] is True
    assert all(
        row["status"] in {"exact", "equivalent", "authored"}
        for row in report["rows"]
    )


def test_real_capability_fanout_uses_runtime_registry_and_two_projections() -> None:
    base = default_capability_catalog()
    without = CapabilityCatalog(
        item for item in base.descriptors() if item.capability_id != "modifier.passive.v2"
    )
    specs = [
        _spec(
            f"hardening:fanout:{index}",
            "grant_passive_modifier",
            {
                "stat": "speed_ft",
                "operation": "add",
                "value": index + 1,
                "scope": "self",
                "applies_when": "always",
            },
        )
        for index in range(6)
    ]
    assert all(FeatureCompiler(without).compile(spec).compile_status == "partial" for spec in specs)
    without.register(base.get("modifier.passive.v2"))
    compiler = FeatureCompiler(without)
    results = [compiler.compile(spec) for spec in specs]
    assert all(result.compile_status == "full" for result in results)
    grants = []
    for spec, result in zip(specs, results, strict=True):
        runtime = materialize_runtime_definition(spec, result, catalog=without)
        grants.append(
            {
                "name": spec.source_name,
                "class_name": spec.class_name,
                "class_level": spec.level,
                "source_record_id": spec.source_record_id,
                "runtime": {"registry": runtime},
            }
        )
    registry = compile_feature_runtime_registry(feature_grants=grants, resources={})
    assert len(registry["combat_start"]["modifiers"]) == 6
    assert len(registry["feature_contracts"]) == 6
    assert {
        item["runtime_execution"]["consumer"] for item in registry["combat_start"]["modifiers"]
    } == {"feature_runtime_registry.combat_start_modifiers"}


def test_pack_registry_trust_pin_and_real_clause_diff(tmp_path: Path) -> None:
    manifest = load_feature_pack(DEMO_PACK)
    importer = FeaturePackImporter(target_dir=tmp_path)
    applied = importer.apply(manifest)
    assert applied.applied is True
    registry = FeaturePackRegistry(tmp_path)
    registry.reload()
    assert registry.lookup("demo:proficiency") is not None
    registry.pin_character("character-1", manifest.pack_id, manifest.pack_version)
    assert registry.character_pin("character-1") == {
        "pack_id": manifest.pack_id,
        "pack_version": manifest.pack_version,
    }

    changed = json.loads(DEMO_PACK.read_text(encoding="utf-8"))
    changed["pack_version"] = "1.1.0"
    for feature in changed["features"]:
        feature["pack_version"] = "1.1.0"
    changed["features"][0]["clauses"][0]["effects"][0]["parameters"]["asset_id"] = "acrobatics"
    changed_manifest = FeaturePackManifest.from_dict(changed)
    dry = FeaturePackImporter(target_dir=tmp_path).dry_run(changed_manifest)
    assert dry.migration_plan["kind"] == "version_update"
    assert dry.migration_plan["changed_features"]

    draft = dict(changed)
    draft["pack_id"] = "draft-pack"
    draft["namespace"] = "draft"
    draft["source_trust"] = "generated_draft"
    for feature in draft["features"]:
        feature["pack_id"] = "draft-pack"
        feature["namespace"] = "draft"
        feature["pack_version"] = "1.1.0"
        feature["source_trust"] = "generated_draft"
    draft_manifest = FeaturePackManifest.from_dict(draft)
    draft_result = FeaturePackImporter().dry_run(draft_manifest)
    assert all(item.compile_status != "full" for item in draft_result.feature_results)
    assert all(
        "source_trust_not_verified" in item.blockers for item in draft_result.feature_results
    )


def test_all_demo_fulls_enter_existing_feature_runtime_consumer() -> None:
    manifest = load_feature_pack(DEMO_PACK)
    results = FeaturePackImporter().compile(manifest)
    contracts = []
    for feature, result in zip(
        sorted(manifest.features, key=lambda item: item.feature_id),
        results,
        strict=True,
    ):
        if result.compile_status != "full":
            continue
        definition = materialize_runtime_definition(feature, result)
        contracts.append(
            feature_runtime_contract(
                feature_name=feature.source_name,
                class_name=feature.class_name or "unclassified",
                class_level=feature.level or 0,
                definition=definition,
                source_record_id=feature.source_record_id,
            )
        )
    assert len(contracts) == 18
    assert all(contract["automation_status"] == "full" for contract in contracts)
    assert {section for contract in contracts for section in contract["runtime_sections"]} >= {
        "proficiencies",
        "advancement",
        "resources",
        "combat_modifiers",
        "movement_modes",
        "combat_defenses",
        "attack_riders",
    }


def test_feature_spec_rejects_unknown_top_level_fields() -> None:
    value = _spec(
        "hardening:strict",
        "grant_language",
        {"language_id": "elvish", "operation": "grant"},
    ).to_dict()
    value["python"] = "import os"
    with pytest.raises(FeatureIRValidationError, match="unknown fields"):
        FeatureSpec.from_dict(value)


def test_vengeance_mapping_closes_existing_trigger_effect_contract() -> None:
    from dnd_dm_assistant.domain.advancement_choices import SUBCLASS_FEATURE_RUNTIME_CONFIGS

    vow_trigger = SUBCLASS_FEATURE_RUNTIME_CONFIGS["仇敌誓言"]["triggers"][0]
    assert feature_trigger_block_errors(vow_trigger) == ()
    vengeance_trigger = SUBCLASS_FEATURE_RUNTIME_CONFIGS["复仇之魂"]["triggers"][0]
    assert vengeance_trigger["event"] == "after_enemy_attack"
    assert vengeance_trigger["required_actor_state_key"] == "vow_of_enmity_target_id"
    assert vengeance_trigger["automation_status"] == "full"
