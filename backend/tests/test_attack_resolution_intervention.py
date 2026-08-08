from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.attack_resolution_intervention import (
    apply_attack_resolution_intervention,
    validate_attack_resolution_input,
)


def _ac_spec() -> dict[str, object]:
    return {
        "kind": "attack_resolution_intervention",
        "phase": "after_provisional_hit",
        "operation": {
            "kind": "add_to_target_ac",
            "amount": "max(1, charisma_modifier)",
            "minimum": 1,
        },
        "input_requirements": [],
        "follow_up": {
            "kind": "triggered_attack_on_miss",
            "parent_action_part": True,
            "attack_profile": {"mode": "weapon_only"},
            "target_policy": {"mode": "event_actor", "range_ft": "weapon_reach"},
        },
    }


def test_add_to_target_ac_can_turn_hit_into_miss() -> None:
    result = apply_attack_resolution_intervention(
        attack_roll_total=16,
        base_armor_class=15,
        cover_bonus=0,
        spec=_ac_spec(),
        bindings={"charisma_modifier": 2},
    )
    assert result["hit"] is False
    assert result["effective_armor_class"] == 17
    assert result["ac_bonus"] == 2
    assert result["became_miss"] is True


def test_add_to_target_ac_still_hit_when_bonus_is_not_enough() -> None:
    result = apply_attack_resolution_intervention(
        attack_roll_total=20,
        base_armor_class=15,
        cover_bonus=0,
        spec=_ac_spec(),
        bindings={"charisma_modifier": 2},
    )
    assert result["hit"] is True
    assert result["effective_armor_class"] == 17
    assert result["became_miss"] is False


def test_subtract_from_attack_total_requires_declared_die_input() -> None:
    spec = {
        "kind": "attack_resolution_intervention",
        "phase": "after_provisional_hit",
        "operation": {"kind": "subtract_from_attack_total", "amount": "bardic_die"},
        "input_requirements": [
            {"key": "bardic_die", "kind": "die_roll", "die_sides": 8},
        ],
    }
    with pytest.raises(ValueError, match="缺少输入"):
        validate_attack_resolution_input(spec, {})
    result = apply_attack_resolution_intervention(
        attack_roll_total=18,
        base_armor_class=15,
        spec=spec,
        inputs={"bardic_die": 4},
    )
    assert result["effective_attack_total"] == 14
    assert result["hit"] is False


def test_impose_disadvantage_uses_lower_of_two_real_d20s() -> None:
    spec = {
        "kind": "attack_resolution_intervention",
        "phase": "before_attack_roll_resolution",
        "operation": {"kind": "impose_disadvantage"},
        "input_requirements": [],
    }
    result = apply_attack_resolution_intervention(
        attack_roll_total=17,
        base_armor_class=14,
        attack_roll_mode="normal",
        attack_rolls=[12, 5],
        spec=spec,
    )
    assert result["imposed_disadvantage"] is True
    assert result["selected_d20"] == 5
    assert result["effective_attack_total"] == 10
    assert result["hit"] is False
