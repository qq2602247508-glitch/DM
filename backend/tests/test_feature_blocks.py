from __future__ import annotations

from dnd_dm_assistant.domain.feature_blocks import (
    feature_action_block_errors,
    feature_action_block_ready,
    resource_lifecycle_block_ready,
    resource_recovery_block_ready,
    structured_target_save_status,
)
from dnd_dm_assistant.domain.feature_runtime import resolve_resource_lifecycle_value
from dnd_dm_assistant.domain.roll_intervention import (
    apply_roll_intervention,
    resolve_roll_intervention,
)


def test_action_trigger_resource_target_contract_is_feature_id_agnostic() -> None:
    first = {
        "id": "fixture:push",
        "kind": "feature_action",
        "action_cost": "reaction",
        "activation_window": "after_hit",
        "resource_key": "focus",
        "resource_cost": 1,
        "target_policy": {"mode": "enemy", "range_ft": 30},
        "saving_throw": {"ability": "strength", "initial_dc": 14},
        "effects": [{"kind": "condition", "condition": "prone"}],
    }
    second = {
        **first,
        "id": "another:push",
        "target_policy": {"mode": "ally_or_self", "range_ft": 10},
        "saving_throw": {"ability": "wisdom", "dc_source": "proficiency_plus_ability"},
    }
    assert feature_action_block_ready(first)
    assert feature_action_block_ready(second)
    assert feature_action_block_errors(first) == ()
    assert structured_target_save_status(first)
    assert structured_target_save_status(second)


def test_resource_recovery_contract_fails_closed_for_ambiguous_recovery() -> None:
    assert resource_recovery_block_ready(
        {
            "recovery_events": [
                {"rest": "short_rest", "operation": "restore", "amount": 1},
                {"rest": "long_rest", "operation": "set_to_max"},
            ]
        }
    )
    assert not resource_recovery_block_ready(
        {"recovery_events": [{"rest": "short_rest", "operation": "restore"}]}
    )
    assert not feature_action_block_ready(
        {"kind": "feature_action", "action_cost": "reaction", "resource_cost": 1}
    )


def test_resource_lifecycle_is_generic_and_applies_typed_events() -> None:
    lifecycle = {
        "key": "fixture_pool",
        "lifecycle_events": [
            {"trigger": "short_rest", "operation": "restore", "amount": 1},
            {"trigger": "long_rest", "operation": "set_to_max"},
            {
                "trigger": "initiative_start",
                "operation": "set_to_minimum",
                "minimum": 2,
            },
        ],
    }
    assert resource_lifecycle_block_ready(lifecycle)
    assert resolve_resource_lifecycle_value(
        0,
        maximum=4,
        event={"trigger": "short_rest", "operation": "restore", "amount": 1},
    ) == 1
    assert resolve_resource_lifecycle_value(
        0,
        maximum=4,
        event={
            "trigger": "initiative_start",
            "operation": "set_to_minimum",
            "minimum": 2,
        },
        condition="current_below_2",
    ) == 2
    assert resolve_resource_lifecycle_value(
        3,
        maximum=4,
        event={"trigger": "initiative_start", "operation": "set_to_minimum", "minimum": 2},
        condition="current_below_2",
    ) is None
    assert not resource_lifecycle_block_ready(
        {
            "key": "fixture_pool",
            "lifecycle_events": [
                {"trigger": "dawn", "operation": "restore", "amount": 1}
            ],
        }
    )


def test_roll_intervention_reuses_resource_lifecycle_and_dynamic_die_config() -> None:
    spec = {
        "id": "fixture:peerless",
        "kind": "roll_intervention",
        "trigger": "after_failed_d20_test",
        "eligibility": {
            "test_kinds": ["ability_check"],
            "resource": {"key": "bardic_inspiration", "minimum": 1, "value_bind_as": "die_sides"},
        },
        "operation": {
            "kind": "add_die",
            "input_key": "die_roll",
            "die_sides_expression": "die_sides",
        },
        "input_requirements": [{"key": "die_roll", "kind": "integer"}],
        "resource": {"key": "bardic_inspiration", "cost": 1},
    }
    resolved = resolve_roll_intervention(
        [spec],
        trigger="after_failed_d20_test",
        context={
            "test_kind": "ability_check",
            "resources": {"bardic_inspiration": {"current": 1, "value": "D8"}},
        },
    )
    assert resolved is not None
    result = apply_roll_intervention(
        resolved,
        roll_total=12,
        inputs={"die_roll": 6},
        dc=15,
        operation_id="fixture-roll-1",
    )
    assert result["effective_total"] == 18
    assert result["success"] is True
    assert result["resource_should_consume"] is True
