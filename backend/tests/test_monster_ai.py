from dnd_dm_assistant.domain.monster_ai import (
    available_monster_actions,
    choose_monster_action,
)


def test_recharge_action_is_initially_available_then_requires_explicit_recharge() -> None:
    actions = [
        {
            "name": "火焰吐息",
            "action_type": "action",
            "damage": "8d6",
            "recharge": {"minimum": 5, "maximum": 6},
        },
        {"name": "爪击", "action_type": "action", "damage": "1d6"},
    ]

    assert [item["name"] for item in available_monster_actions(actions)] == [
        "火焰吐息",
        "爪击",
    ]
    assert [
        item["name"]
        for item in available_monster_actions(actions, recharge_available={"火焰吐息": False})
    ] == ["爪击"]
    assert [
        item["name"]
        for item in available_monster_actions(actions, recharge_available={"火焰吐息": True})
    ] == ["火焰吐息", "爪击"]


def test_reaction_actions_are_filtered_by_explicit_event() -> None:
    actions = [
        {
            "name": "借机攻击",
            "action_type": "reaction",
            "reaction_event": "leaves_reach",
            "damage": "1d8",
        },
        {
            "name": "受击反击",
            "action_type": "reaction",
            "reaction_event": "takes_damage",
            "damage": "2d6",
        },
    ]

    assert [
        item["name"]
        for item in available_monster_actions(
            actions, phase="reaction", reaction_event="takes_damage"
        )
    ] == ["受击反击"]


def test_monster_planner_selects_nearest_enemy_without_resolving_damage() -> None:
    plan = choose_monster_action(
        {
            "id": "monster-1",
            "disposition": "enemy",
            "grid_position": {"row": 1, "col": 1},
            "actions": [
                {"name": "爪击", "action_type": "action", "damage": "1d6"},
            ],
        },
        [
            {"id": "far", "disposition": "ally", "grid_position": {"row": 5, "col": 5}, "hp": 10},
            {"id": "near", "disposition": "ally", "grid_position": {"row": 1, "col": 2}, "hp": 10},
        ],
    )

    assert plan is not None
    assert plan.target_ids == ("near",)
    assert plan.requires_dm_confirmation is True
    assert "伤害" not in plan.as_dict()


def test_monster_planner_expands_reliable_multiattack_and_filters_action_windows() -> None:
    actions = [
        {
            "name": "多重攻击",
            "action_type": "action",
            "multiattack": True,
            "multiattack_count": 3,
            "multiattack_components": [
                {"action_name": "啃咬", "count": 1},
                {"action_name": "爪击", "count": 2},
            ],
            "auto_eligible": True,
        },
        {
            "name": "啃咬",
            "action_type": "action",
            "damage": "1d10+4",
            "range_ft": 5,
        },
        {
            "name": "爪击",
            "action_type": "action",
            "damage": "2d6+4",
            "range_ft": 5,
        },
        {
            "name": "尾击",
            "action_type": "legendary_action",
            "damage": "2d8+4",
            "range_ft": 10,
            "legendary_cost": 2,
        },
    ]
    actor = {
        "id": "dragon",
        "disposition": "enemy",
        "actions": actions,
    }
    targets = [{"id": "hero", "disposition": "ally", "hp": 30}]

    turn_plan = choose_monster_action(actor, targets, tactics="tactical")
    assert turn_plan is not None
    assert turn_plan.action_name == "多重攻击"
    assert [step.action_name for step in turn_plan.steps] == ["啃咬", "爪击", "爪击"]

    legendary_plan = choose_monster_action(
        actor,
        targets,
        phase="legendary",
        legendary_actions_remaining=3,
    )
    assert legendary_plan is not None
    assert legendary_plan.action_name == "尾击"
    assert legendary_plan.legendary_cost == 2


def test_area_plan_keeps_all_candidates_and_requires_geometry_confirmation() -> None:
    plan = choose_monster_action(
        {
            "id": "dragon",
            "disposition": "enemy",
            "actions": [
                {
                    "name": "寒霜吐息",
                    "action_type": "action",
                    "damage": "8d8",
                    "range_ft": 60,
                    "area_shape": "cone",
                    "save_dc": 17,
                    "save_ability": "constitution",
                }
            ],
        },
        [
            {"id": "hero-a", "disposition": "ally", "hp": 30},
            {"id": "hero-b", "disposition": "ally", "hp": 20},
        ],
    )

    assert plan is not None
    assert plan.target_ids == ("hero-a", "hero-b")
    assert plan.requires_player_roll is True
    assert "区域覆盖需要地图几何确认" in plan.confirmation_reasons


def test_configured_focus_switches_when_target_is_no_longer_active() -> None:
    actor = {
        "id": "captain",
        "hp": 30,
        "max_hp": 30,
        "disposition": "enemy",
        "ai_tactics": {"strategy": "focus_fire", "focus_target_id": "wizard"},
        "actions": [
            {
                "name": "长弓",
                "action_type": "action",
                "damage": "1d8+3",
                "range_ft": 150,
            }
        ],
    }
    targets = [
        {"id": "fighter", "disposition": "ally", "hp": 20, "is_active": True},
        {"id": "wizard", "disposition": "ally", "hp": 4, "is_active": True},
    ]

    focused = choose_monster_action(actor, targets, tactics="tactical")
    assert focused is not None
    assert focused.focus_target_id == "wizard"

    targets[1]["is_active"] = False
    switched = choose_monster_action(actor, targets, tactics="tactical")
    assert switched is not None
    assert switched.focus_target_id == "fighter"


def test_control_and_retreat_tactics_change_the_plan() -> None:
    actor = {
        "id": "guardian",
        "hp": 5,
        "max_hp": 30,
        "disposition": "enemy",
        "actions": [
            {
                "name": "巨斧",
                "action_type": "action",
                "damage": "3d12",
                "range_ft": 5,
            },
            {
                "name": "恐惧凝视",
                "action_type": "action",
                "damage": "1d4",
                "range_ft": 30,
                "conditions_on_failure": ["受惊"],
                "condition_duration": "target_turn_end",
            },
        ],
        "ai_tactics": {"strategy": "control"},
    }
    targets = [{"id": "hero", "disposition": "ally", "hp": 20}]

    control = choose_monster_action(actor, targets, tactics="tactical")
    assert control is not None
    assert control.action_name == "恐惧凝视"
    assert control.tactical_intent == "control"

    actor["ai_tactics"] = {
        "strategy": "adaptive",
        "retreat_threshold_pct": 25,
    }
    actor["actions"] = []
    retreat = choose_monster_action(actor, targets, tactics="tactical")
    assert retreat is not None
    assert retreat.action_type == "disengage"
    assert retreat.movement_mode == "retreat"
    assert retreat.target_ids == ()

    actor["action_available"] = False
    assert choose_monster_action(actor, targets, tactics="tactical") is None


def test_protect_leader_targets_the_enemy_closest_to_the_leader() -> None:
    actor = {
        "id": "bodyguard",
        "hp": 30,
        "max_hp": 30,
        "disposition": "enemy",
        "grid_position": {"row": 1, "col": 1},
        "ai_tactics": {"strategy": "protect_leader", "leader_id": "boss"},
        "actions": [
            {
                "name": "拦截猛击",
                "action_type": "action",
                "damage": "1d6",
                "range_ft": 5,
                "conditions_on_hit": ["倒地"],
                "condition_duration": "target_turn_end",
            }
        ],
    }
    targets = [
        {
            "id": "boss",
            "disposition": "enemy",
            "grid_position": {"row": 5, "col": 5},
            "hp": 100,
        },
        {
            "id": "near-hero",
            "disposition": "ally",
            "grid_position": {"row": 5, "col": 4},
            "hp": 30,
        },
        {
            "id": "near-bodyguard",
            "disposition": "ally",
            "grid_position": {"row": 1, "col": 2},
            "hp": 10,
        },
    ]

    plan = choose_monster_action(actor, targets, tactics="tactical")

    assert plan is not None
    assert plan.focus_target_id == "near-hero"
    assert plan.tactical_intent == "protect_leader"
