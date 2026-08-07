import pytest

from dnd_dm_assistant.domain.roll_intervention import (
    apply_roll_intervention,
    resolve_roll_interventions,
)


def test_generic_executor_applies_reroll_add_die_and_failure_recovery_without_feature_ids() -> None:
    reroll = {
        "id": "fixture:resilient-reroll",
        "kind": "roll_intervention",
        "trigger": "after_failed_save",
        "operation": {"kind": "reroll"},
        "resource": {"key": "fixture_uses", "cost": 1},
        "idempotency": {"prefix": "fixture-reroll"},
    }
    recovery = {
        "id": "fixture:tactical-recovery",
        "kind": "roll_intervention",
        "trigger": "after_failed_d20_test",
        "input_requirements": [
            {"key": "tactical_die", "kind": "die_roll", "die_sides": 10}
        ],
        "operation": {
            "kind": "failure_recovery",
            "recovery": {"kind": "add_die", "input_key": "tactical_die", "die_sides": 10},
            "consume_when": "on_success",
        },
        "resource": {"key": "second_wind", "cost": 1},
    }

    rerolled = apply_roll_intervention(
        reroll,
        roll_total=5,
        roll_totals=[5, 16],
        operation_id="save-action-1",
    )
    recovered = apply_roll_intervention(
        recovery,
        roll_total=12,
        dc=15,
        inputs={"tactical_die": 4},
    )

    assert rerolled["effective_total"] == 16
    assert rerolled["resource_should_consume"] is True
    assert rerolled["idempotency_key"] == "fixture-reroll:save-action-1"
    assert recovered["effective_total"] == 16
    assert recovered["failure_recovered"] is True
    assert recovered["resource_should_consume"] is True
    assert recovered["details"]["recovery_operation"] == "add_die"


def test_generic_executor_covers_add_advantage_disadvantage_and_minimum_d20() -> None:
    add = {
        "id": "fixture:flat-bonus",
        "kind": "roll_intervention",
        "trigger": "after_roll",
        "operation": {"kind": "add", "amount": "proficiency_bonus+1"},
    }
    advantage = {
        "id": "fixture:advantage",
        "kind": "roll_intervention",
        "trigger": "before_roll",
        "operation": {"kind": "advantage"},
    }
    disadvantage = {
        "id": "fixture:disadvantage",
        "kind": "roll_intervention",
        "trigger": "before_roll",
        "operation": {"kind": "disadvantage"},
    }
    floor = {
        "id": "fixture:floor",
        "kind": "roll_intervention",
        "trigger": "after_roll",
        "input_requirements": [{"key": "d20_roll", "kind": "d20_roll"}],
        "operation": {"kind": "set_minimum", "minimum": 10, "basis": "d20"},
    }

    assert apply_roll_intervention(add, roll_total=8, bindings={"proficiency_bonus": 3})[
        "effective_total"
    ] == 12
    advantage_result = apply_roll_intervention(advantage, roll_total=7, roll_totals=[7, 16])
    disadvantage_result = apply_roll_intervention(
        disadvantage,
        roll_total=7,
        roll_totals=[7, 16],
    )
    assert advantage_result["effective_total"] == 16
    assert disadvantage_result["effective_total"] == 7
    minimum = apply_roll_intervention(floor, roll_total=8, inputs={"d20_roll": 3})
    assert minimum["effective_total"] == 15
    assert minimum["details"]["natural_roll_after"] == 10


def test_generic_resolver_uses_structured_eligibility_instead_of_feature_ids() -> None:
    wrong_faction = {
        "id": "fixture:enemy-only",
        "kind": "roll_intervention",
        "trigger": "after_failed_d20_test",
        "eligibility": {"factions": ["enemy"]},
        "operation": {"kind": "add", "amount": 1},
    }
    qualified = {
        "id": "fixture:level-and-resource",
        "kind": "roll_intervention",
        "trigger": "after_failed_d20_test",
        "eligibility": {
            "entity_types": ["character"],
            "factions": ["ally"],
            "test_kinds": ["ability_check"],
            "required_conditions": ["focused"],
            "level": {
                "class_names": ["fighter", "战士"],
                "minimum": 2,
                "bind_as": "fighter_level",
            },
            "resource": {"key": "second_wind", "minimum": 1, "bind_as": "uses_left"},
        },
        "operation": {"kind": "add", "amount": "fighter_level+uses_left"},
    }

    resolved = resolve_roll_interventions(
        [wrong_faction, qualified],
        trigger="after_failed_d20_test",
        context={
            "entity_type": "character",
            "faction": "ally",
            "test_kind": "ability_check",
            "conditions": ["focused"],
            "class_levels": {"战士": 5},
            "resources": {"second_wind": {"current": 2}},
        },
    )

    assert [item["id"] for item in resolved] == ["fixture:level-and-resource"]
    assert resolved[0]["resolved_bindings"] == {"fighter_level": 5, "uses_left": 2}
    assert apply_roll_intervention(resolved[0], roll_total=9)["effective_total"] == 16


def test_generic_executor_fails_closed_on_missing_or_invalid_reported_input() -> None:
    add_die = {
        "id": "fixture:add-die",
        "kind": "roll_intervention",
        "trigger": "after_roll",
        "input_requirements": [{"key": "die", "kind": "die_roll", "die_sides": 6}],
        "operation": {"kind": "add_die", "input_key": "die", "die_sides": 6},
    }
    failed_recovery = {
        "id": "fixture:failed-recovery",
        "kind": "roll_intervention",
        "trigger": "after_failed_d20_test",
        "input_requirements": [{"key": "die", "kind": "die_roll", "die_sides": 6}],
        "operation": {
            "kind": "failure_recovery",
            "recovery": {"kind": "add_die", "input_key": "die", "die_sides": 6},
            "consume_when": "on_success",
        },
        "resource": {"key": "fixture", "cost": 1},
    }

    with pytest.raises(ValueError, match="骰子输入超出范围"):
        apply_roll_intervention(add_die, roll_total=9, inputs={"die": 7})
    with pytest.raises(ValueError, match="未声明输入"):
        apply_roll_intervention(add_die, roll_total=9, inputs={"die": 3, "extra": 1})
    with pytest.raises(ValueError, match="优势或劣势需要"):
        apply_roll_intervention(
            {
                "id": "fixture:advantage",
                "kind": "roll_intervention",
                "trigger": "before_roll",
                "operation": {"kind": "advantage"},
            },
            roll_total=9,
        )
    failed = apply_roll_intervention(failed_recovery, roll_total=8, dc=15, inputs={"die": 2})
    assert failed["success"] is False
    assert failed["resource_should_consume"] is False
