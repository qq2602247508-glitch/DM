from __future__ import annotations

from dnd_dm_assistant.domain.feature_blocks import (
    feature_action_block_errors,
    feature_action_block_ready,
    resource_recovery_block_ready,
    structured_target_save_status,
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
