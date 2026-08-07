from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.attack_rider import (
    post_hit_effects_as_rule_blocks,
    post_hit_rider_input_requirements,
    resolve_post_hit_rider,
)


def _actor(*, conditions: list[str], focus: int = 2) -> tuple[dict[str, object], dict[str, object]]:
    return (
        {
            "id": "actor",
            "entity_type": "character",
            "faction": "allies",
            "conditions": conditions,
            "class_levels": {"fixture_class": 9},
        },
        {"focus": {"current": focus}},
    )


def _target() -> dict[str, object]:
    return {
        "id": "target",
        "entity_type": "creature",
        "faction": "enemies",
        "relation": "enemy",
        "conditions": [],
    }


def test_two_unrelated_post_hit_configurations_share_one_executor() -> None:
    push_config = {
        "id": "fixture:crusher-push",
        "kind": "post_hit_rider",
        "trigger": "after_hit",
        "frequency": "once_per_turn",
        "eligibility": {
            "actor_entity_types": ["character"],
            "actor_conditions_all": ["battle_trance"],
            "action_tags_all": ["melee", "weapon"],
            "attack_abilities": ["strength"],
            "target_relations": ["enemy"],
            "actor_level": {"class_names": ["fixture_class"], "minimum": 9},
        },
        "resource": {"key": "focus", "amount": 1},
        "damage": {
            "id": "impact",
            "expression": "1d10",
            "damage_type": "force",
            "input_key": "impact_total",
        },
        "saving_throw": {"ability": "strength", "dc": 14, "input_key": "resist_push"},
        "on_save_failure": [
            {
                "kind": "move",
                "distance_ft": 15,
                "movement_type": "forced",
                "direction": "push",
            }
        ],
    }
    dread_config = {
        "id": "fixture:dread-mark",
        "kind": "post_hit_rider",
        "trigger": "after_hit",
        "frequency": "once_per_attack",
        "eligibility": {
            "actor_entity_types": ["character"],
            "action_tags_any": ["arcane", "ranged"],
            "target_conditions_none": ["immune_to_fear"],
            "target_relations": ["enemy"],
        },
        "saving_throw": {
            "ability": "wisdom",
            "dc_source": "feature_dc",
            "input_key": "resist_dread",
        },
        "on_save_failure": [
            {
                "kind": "condition",
                "condition": "frightened",
                "duration": {"unit": "round", "value": 1},
            },
            {
                "kind": "modifier",
                "stat": "speed_ft",
                "operation": "add",
                "value": -10,
            },
        ],
    }
    actor, resources = _actor(conditions=["battle_trance"])

    push = resolve_post_hit_rider(
        push_config,
        hit=True,
        actor=actor,
        target=_target(),
        action={"tags": ["melee", "weapon"], "attack_ability": "strength"},
        resources=resources,
        event_id="attack-1",
        turn_id="2:4",
        inputs={"impact_total": 8, "resist_push": 11},
    )
    dread = resolve_post_hit_rider(
        dread_config,
        hit=True,
        actor=actor,
        target=_target(),
        action={"tags": ["arcane"], "attack_ability": "charisma"},
        resources=resources,
        event_id="attack-2",
        inputs={"resist_dread": 12},
        bindings={"feature_dc": 15},
    )

    assert push is not None
    assert push["status"] == "resolved"
    assert push["damage"] == [
        {
            "id": "impact",
            "expression": "1d10",
            "damage_type": "force",
            "input_key": "impact_total",
            "minimum": 1,
            "maximum": 10,
            "critical_doubles_dice": True,
            "reported_total": 8,
        }
    ]
    assert push["effects"] == [
        {
            "id": "fixture:crusher-push:on-save-failure:1",
            "kind": "move",
            "distance_ft": 15,
            "movement_type": "forced",
            "direction": "push",
        }
    ]
    assert push["commit"] == {
        "idempotency_key": "post-hit:attack-1:fixture:crusher-push",
        "usage_token": "post-hit:fixture:crusher-push:turn:2:4",
        "resource_spends": [{"key": "focus", "amount": 1}],
    }

    assert dread is not None
    assert dread["status"] == "resolved"
    assert dread["damage"] == []
    assert dread["saving_throw"] == {
        "ability": "wisdom",
        "dc": 15,
        "input_key": "resist_dread",
        "reported_total": 12,
        "success": False,
    }
    assert [effect["kind"] for effect in dread["effects"]] == ["condition", "modifier"]
    assert dread["effects"][0]["condition"] == "frightened"
    assert dread["effects"][1]["value"] == -10


def test_post_hit_rider_opens_choice_then_save_without_spending_until_resolved() -> None:
    config = {
        "id": "fixture:choice-rider",
        "kind": "post_hit_rider",
        "trigger": "after_hit",
        "frequency": "once_per_target_per_turn",
        "eligibility": {"action_tags_all": ["weapon"], "target_relations": ["enemy"]},
        "resource": {"key": "focus", "amount": 1},
        "choice": {
            "input_key": "rider_mode",
            "options": [
                {
                    "key": "slow",
                    "label": "减速",
                    "effects": [
                        {
                            "kind": "modifier",
                            "stat": "speed_ft",
                            "operation": "add",
                            "value": -15,
                        }
                    ],
                },
                {
                    "key": "fear",
                    "label": "恐慌",
                    "effects": [{"kind": "condition", "condition": "frightened"}],
                },
            ],
        },
        "saving_throw": {"ability": "constitution", "dc": 13, "input_key": "resist_mode"},
        "on_save_success": [{"kind": "condition", "condition": "shaken"}],
    }
    actor, resources = _actor(conditions=[])
    base = dict(
        hit=True,
        actor=actor,
        target=_target(),
        action={"tags": ["weapon"]},
        resources=resources,
        event_id="attack-3",
        turn_id="3:1",
    )

    choice = resolve_post_hit_rider(config, **base)
    assert choice == {
        "status": "pending_choice",
        "rider_id": "fixture:choice-rider",
        "resolution_key": "post-hit:attack-3:fixture:choice-rider",
        "usage_token": "post-hit:fixture:choice-rider:turn:3:1:target:target",
        "choice": {
            "input_key": "rider_mode",
            "options": [{"key": "slow", "label": "减速"}, {"key": "fear", "label": "恐慌"}],
        },
        "commit": None,
    }

    pending_save = resolve_post_hit_rider(config, **base, inputs={"rider_mode": "slow"})
    assert pending_save is not None
    assert pending_save["status"] == "pending_save"
    assert pending_save["selected_choice"] == "slow"
    assert pending_save["saving_throw"] == {
        "ability": "constitution",
        "dc": 13,
        "input_key": "resist_mode",
    }
    assert pending_save["commit"] is None

    resolved = resolve_post_hit_rider(
        config,
        **base,
        inputs={"rider_mode": "slow", "resist_mode": 15},
    )
    assert resolved is not None
    assert resolved["status"] == "resolved"
    assert [effect["kind"] for effect in resolved["effects"]] == ["modifier", "condition"]
    assert resolved["commit"]["resource_spends"] == [{"key": "focus", "amount": 1}]

    replay = resolve_post_hit_rider(
        config,
        **base,
        inputs={"rider_mode": "slow", "resist_mode": 15},
        used_tokens=[resolved["usage_token"]],
    )
    assert replay == {
        "status": "already_used",
        "rider_id": "fixture:choice-rider",
        "resolution_key": "post-hit:attack-3:fixture:choice-rider",
        "usage_token": "post-hit:fixture:choice-rider:turn:3:1:target:target",
    }


def test_post_hit_rider_requirements_adapter_and_fail_closed_boundaries() -> None:
    config = {
        "id": "fixture:stun-like",
        "kind": "post_hit_rider",
        "trigger": "after_hit",
        "frequency": "each_eligible_hit",
        "eligibility": {"action_tags_all": ["unarmed"], "target_relations": ["enemy"]},
        "damage": {
            "expression": "1d6+@bonus",
            "damage_type": "psychic",
            "input_key": "rider_damage",
        },
        "saving_throw": {"ability": "constitution", "dc": 14, "input_key": "rider_save"},
        "on_save_failure": [
            {
                "id": "stun-effect",
                "kind": "condition",
                "condition": "stunned",
                "duration": {"unit": "round", "value": 1},
            }
        ],
    }
    # The prompt refuses to invent a class-derived bonus. Once the caller
    # supplies that authoritative binding, it exposes the critical-hit bounds.
    with pytest.raises(ValueError, match="damage binding is missing"):
        post_hit_rider_input_requirements(config)
    requirements = post_hit_rider_input_requirements(
        config,
        bindings={"bonus": 2},
        critical_hit=True,
    )
    assert requirements == [
        {
            "key": "rider_damage",
            "kind": "damage_total",
            "expression": "1d6+@bonus",
            "minimum": 4,
            "maximum": 14,
        },
        {
            "key": "rider_save",
            "kind": "saving_throw_total",
            "ability": "constitution",
            "dc": 14,
        },
    ]

    actor, resources = _actor(conditions=[])
    not_eligible = resolve_post_hit_rider(
        config,
        hit=True,
        actor=actor,
        target=_target(),
        action={"tags": ["weapon"]},
        resources=resources,
        event_id="attack-4",
        inputs={"rider_damage": 8, "rider_save": 4},
        bindings={"bonus": 2},
    )
    assert not_eligible is None

    resolved = resolve_post_hit_rider(
        config,
        hit=True,
        actor=actor,
        target=_target(),
        action={"tags": ["unarmed"]},
        resources=resources,
        event_id="attack-4",
        inputs={"rider_damage": 8, "rider_save": 4},
        bindings={"bonus": 2},
        critical_hit=True,
    )
    assert resolved is not None
    assert resolved["damage"][0]["minimum"] == 4
    assert resolved["damage"][0]["maximum"] == 14
    blocks = post_hit_effects_as_rule_blocks(resolved["effects"])
    assert blocks == [
        {"id": "stun-effect:duration", "kind": "duration", "unit": "round", "value": 1},
        {
            "id": "stun-effect",
            "kind": "condition",
            "operation": "apply",
            "condition": "stunned",
            "duration_block_id": "stun-effect:duration",
        },
    ]


def test_optional_post_hit_rider_waits_then_declines_without_commit() -> None:
    config = {
        "id": "optional-save-rider",
        "kind": "post_hit_rider",
        "trigger": "after_hit",
        "frequency": "once_per_turn",
        "activation": {"input_key": "activate", "label": "发动效果"},
        "saving_throw": {"ability": "constitution", "dc": 15},
        "resource": {"key": "focus", "amount": 1},
        "on_save_failure": [
            {
                "id": "optional-save-rider:stunned",
                "kind": "condition",
                "condition": "stunned",
                "duration": {"unit": "until_source_turn_start"},
            }
        ],
    }
    common = {
        "hit": True,
        "actor": {"id": "a", "entity_type": "character"},
        "target": {"id": "t", "entity_type": "monster"},
        "action": {},
        "resources": {"focus": {"current": 2}},
        "event_id": "attack-1",
        "turn_id": "turn-1",
    }

    pending = resolve_post_hit_rider(config, **common)
    assert pending is not None
    assert pending["status"] == "pending_activation"
    assert pending["commit"] is None

    declined = resolve_post_hit_rider(config, **common, inputs={"activate": False})
    assert declined is not None
    assert declined["status"] == "declined"
    assert declined["commit"] is None

    save = resolve_post_hit_rider(config, **common, inputs={"activate": True})
    assert save is not None
    assert save["status"] == "pending_save"


def test_level_bound_damage_and_choice_are_resolved_by_generic_rider() -> None:
    config = {
        "id": "fixture:level-bound-rider",
        "kind": "post_hit_rider",
        "trigger": "after_hit",
        "frequency": "once_per_turn",
        "eligibility": {
            "actor_conditions_all": ["raging"],
            "target_relations": ["enemy"],
            "action_tags_any": ["weapon", "unarmed"],
        },
        "choice": {
            "input_key": "damage_type_choice",
            "options": [
                {"key": "radiant", "label": "光耀"},
                {"key": "necrotic", "label": "暗蚀"},
            ],
        },
        "damage": {
            "id": "level-bound-damage",
            "expression": "1d6+@class_level_half",
            "damage_type": "radiant",
            "damage_type_source": "damage_type_choice",
            "damage_type_options": ["radiant", "necrotic"],
            "input_key": "damage_total",
        },
    }
    actor, resources = _actor(conditions=["raging"])
    actor["class_levels"] = {"fixture_class": 9}
    pending = resolve_post_hit_rider(
        config,
        hit=True,
        actor=actor,
        target=_target(),
        action={"tags": ["weapon"]},
        resources=resources,
        event_id="attack-level-bound",
        turn_id="1:1",
        bindings={"class_level_half": 4},
    )
    assert pending is not None and pending["status"] == "pending_choice"
    resolved = resolve_post_hit_rider(
        config,
        hit=True,
        actor=actor,
        target=_target(),
        action={"tags": ["weapon"]},
        resources=resources,
        event_id="attack-level-bound",
        turn_id="1:1",
        bindings={"class_level_half": 4},
        inputs={"damage_type_choice": "necrotic", "damage_total": 8},
    )
    assert resolved is not None and resolved["status"] == "resolved"
    assert resolved["damage"][0]["damage_type"] == "necrotic"
    assert resolved["damage"][0]["minimum"] == 5
    assert resolved["damage"][0]["maximum"] == 10
