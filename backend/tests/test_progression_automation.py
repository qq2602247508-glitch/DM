from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from dnd_dm_assistant.domain.advancement import ClassProgression, class_progression_from_record
from dnd_dm_assistant.domain.advancement_choices import (
    CORE_CLASSES_2024,
    advancement_choice_requirements,
    core_class_level_runtime_contract,
)
from dnd_dm_assistant.domain.feature_runtime import compile_feature_runtime_registry
from dnd_dm_assistant.domain.progression_automation import (
    apply_progression_choice_grants,
    assign_progression_choices,
    progression_acceptance_matrix,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CLASS_RECORD_ROOT = REPOSITORY_ROOT / "data/generated-content/dnd5e_chm/json/classes"
TARGET_KEYS = {
    "asi_or_feat",
    "epic_boon",
    "fighting_style",
    "weapon_mastery",
    "expertise",
}


def _core_rules() -> list[ClassProgression]:
    rules: list[ClassProgression] = []
    for path in CLASS_RECORD_ROOT.glob("*.json"):
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        name = str(record.get("name") or "")
        source_path = str(record.get("source_relative_path") or "")
        if (
            name in CORE_CLASSES_2024
            and record.get("edition") == "2024"
            and source_path.endswith(f"/{name}.htm")
        ):
            rules.append(class_progression_from_record(record))
    assert {rule.name for rule in rules} == set(CORE_CLASSES_2024)
    return rules


def test_classifier_migration_table_and_acceptance_matrix_are_complete() -> None:
    rules = _core_rules()
    matrix = progression_acceptance_matrix(rules)
    assert len(matrix) == 77
    assert Counter(item["feature_name"] for item in matrix) == {
        "属性值提升": 51,
        "传奇恩惠": 12,
        "武器精通": 5,
        "专精": 5,
        "学者": 1,
        "战斗风格": 3,
    }
    assert Counter(item["overall_status"] for item in matrix) == {
        "full": 57,
        "partial": 20,
    }
    assert all(
        item["executor_kind"] == "advancement_choice_grant"
        and item["config_present"]
        and item["real_consumer"]
        and item["persisted_state"]
        for item in matrix
    )

    choice_slots: Counter[str] = Counter()
    for rule in rules:
        for level in range(1, 21):
            for requirement in advancement_choice_requirements(rule, level):
                if requirement.key in TARGET_KEYS:
                    choice_slots[requirement.key] += requirement.minimum
    assert choice_slots == {
        "asi_or_feat": 51,
        "epic_boon": 12,
        "fighting_style": 3,
        "weapon_mastery": 16,
        "expertise": 11,
    }
    assert sum(choice_slots.values()) == 93


def test_core_contract_counts_move_only_to_evidence_backed_statuses() -> None:
    status: Counter[str] = Counter()
    for rule in _core_rules():
        for level in range(1, 21):
            contract = core_class_level_runtime_contract(rule, level)
            status.update(
                item["automation_status"] for item in contract["feature_contracts"]
            )
    assert status == {"full": 124, "partial": 35, "dm_only": 99}
    assert sum(status.values()) == 258


def test_typed_choices_separate_same_level_requirements_and_apply_generic_grants() -> None:
    fighter = next(rule for rule in _core_rules() if rule.name == "战士")
    requirements = advancement_choice_requirements(fighter, 1)
    assigned, used_legacy = assign_progression_choices(
        requirements,
        choices_by_key={
            "fighting_style": ["防御"],
            "weapon_mastery": ["长剑", "战锤", "长弓"],
        },
    )
    assert used_legacy is False
    assert assigned == {
        "fighting_style": ["防御"],
        "weapon_mastery": ["长剑", "战锤", "长弓"],
    }
    result = apply_progression_choice_grants(
        choices_by_key=assigned,
        skills={"调查": {"proficient": True}},
        proficiencies=["军用武器"],
        class_name="战士",
        class_level=1,
        total_level=1,
        source_record_id="fighter-2024",
        rule_year=2024,
    )
    masteries = [
        item
        for item in result["proficiencies"]
        if isinstance(item, dict) and item.get("kind") == "weapon_mastery"
    ]
    assert [item["name"] for item in masteries] == ["长剑", "战锤", "长弓"]
    defense = next(item for item in result["grants"] if item["name"] == "防御")
    assert defense["runtime"]["execution"] == {
        "kind": "advancement_choice_grant",
        "consumer": "advancement_service",
        "status": "ready",
        "grant_status": "full",
        "effect_status": "full",
    }
    registry = compile_feature_runtime_registry(result["grants"])
    assert any(
        item["id"] == "fighting_style_defense:armor_class"
        and item["value"] == 1
        and item["applies_when"] == "wearing_armor"
        for item in registry["combat_start"]["modifiers"]
    )


def test_expertise_mutation_requires_proficiency_and_is_reusable() -> None:
    result = apply_progression_choice_grants(
        choices_by_key={"expertise": ["调查", "察觉"]},
        skills={
            "调查": {"proficient": True},
            "察觉": {"proficient": True, "source": "background"},
        },
        proficiencies=[],
        class_name="游荡者",
        class_level=1,
        total_level=1,
        source_record_id="rogue-2024",
        rule_year=2024,
    )
    assert result["skills"]["调查"]["expertise"] is True
    assert result["skills"]["察觉"] == {
        "proficient": True,
        "source": "background",
        "expertise": True,
    }
    assert all(
        item["runtime"]["automation_status"] == "full"
        for item in result["grants"]
    )
