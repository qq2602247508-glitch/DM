"""Tests for the batch assembly layer (feature_batch_declarations)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from dnd_dm_assistant.domain.advancement_choices import (
    subclass_feature_automation_status,
    subclass_feature_runtime_definition,
)
from dnd_dm_assistant.domain.feature_batch_declarations import (
    BATCH_BUFF_FEATURES,
    batch_runtime_configs,
)

ROOT = Path(__file__).resolve().parents[2]
CENSUS_SCRIPT = ROOT / "scripts" / "feature-ir-semantic-cluster-census.py"


def test_batch_declarations_generate_typed_registries() -> None:
    configs = batch_runtime_configs()
    assert set(configs) == {"神之狂暴", "炫目舞步"}
    divine_rage = configs["神之狂暴"]
    assert divine_rage["automation_status"] == "full"
    action_id = "野蛮人:狂热者道途:divine_rage"
    action = divine_rage["actions"][action_id]
    assert action["kind"] == "feature_action"
    assert action["resource_key"] == "$feature_resource"
    assert action["resource_cost"] == 1
    assert action["effects"][0]["kind"] == "activate_duration_condition"
    assert action["effects"][0]["condition"] == "divine_rage"
    assert divine_rage["combat_start"]["movement_modes"][0]["mode"] == "fly"
    assert divine_rage["combat_start"]["defenses"][0]["kind"] == "damage_resistance"
    assert divine_rage["combat_start"]["defenses"][0]["required_conditions"] == [
        "divine_rage"
    ]

    dance = configs["炫目舞步"]
    assert dance["actions"] == {}
    ac_modifier = dance["combat_start"]["modifiers"][0]
    assert ac_modifier["stat"] == "armor_class"
    assert ac_modifier["operation"] == "set_base_formula"
    assert ac_modifier["formula"] == "10+dexterity_modifier+charisma_modifier"


def test_batch_features_audit_as_full_and_pass_prefix_alias() -> None:
    for definition in (
        {
            "name": "神之狂暴 Rage of the Gods",
            "class_name": "野蛮人",
            "subclass_name": "狂热者道途",
            "class_level": 14,
        },
        {
            "name": "炫目舞步",
            "class_name": "吟游诗人",
            "subclass_name": "舞蹈学院",
            "class_level": 3,
        },
    ):
        runtime = subclass_feature_runtime_definition(definition)
        assert runtime is not None
        assert runtime["automation_status"] == "full"
        assert subclass_feature_automation_status(definition) == "full"


def test_batch_declarations_are_disjoint_from_handwritten_registries() -> None:
    for feature in BATCH_BUFF_FEATURES:
        config = batch_runtime_configs()[feature.name]
        action_id = f"{feature.class_name}:{feature.subclass_name}:{feature.key}"
        if feature.resource_key:
            assert action_id in config["actions"]
        else:
            assert config["actions"] == {}


def test_census_proves_partial_corpus_has_no_large_homogeneous_cluster() -> None:
    spec = importlib.util.spec_from_file_location("feature_audit_census", CENSUS_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.census()
    assert report["audit_total"] == 499
    assert report["status_counts"] == {"full": 317, "partial": 121, "dm_only": 61}
    assert report["partial_total"] == 121
    largest = report["largest_partial_clusters"][0]
    assert largest["member_count"] <= 2
