from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from dnd_dm_assistant.domain.advancement import (
    ClassProgression,
    class_progression_from_record,
    merge_spell_slot_resources,
)
from dnd_dm_assistant.domain.advancement_choices import (
    CORE_CLASSES_2024,
    core_class_level_runtime_contract,
    core_feature_grants,
    core_runtime_actions,
    progression_resource_updates,
    progression_scaling_updates,
    subclass_feature_runtime_definition,
    subclass_runtime_grants,
)
from dnd_dm_assistant.domain.feature_runtime import (
    FEATURE_RUNTIME_SCHEMA_VERSION,
    apply_initiative_start_resource_recovery,
    compile_feature_runtime_registry,
    feature_block_payloads,
    feature_condition_runtime_spec,
    feature_runtime_action_projections,
    feature_runtime_contract,
    feature_runtime_definition,
    resolve_feature_speed,
    resolve_unarmored_defense_ac,
)
from dnd_dm_assistant.domain.rests import RestResource, resolve_long_rest, resolve_short_rest
from dnd_dm_assistant.domain.zero_hp_intervention import (
    adapt_legacy_zero_hp_intervention,
)
from dnd_dm_assistant.infrastructure.database.advancement_service import AdvancementService
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import Combatant
from dnd_dm_assistant.infrastructure.database.player_room_service import PlayerRoomService

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CLASS_RECORD_ROOT = REPOSITORY_ROOT / "data/generated-content/dnd5e_chm/json/classes"


def _core_rules() -> dict[str, ClassProgression]:
    rules: dict[str, ClassProgression] = {}
    for path in CLASS_RECORD_ROOT.glob("*.json"):
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        name = str(record.get("name") or "")
        source_path = str(record.get("source_relative_path") or "")
        if (
            name in CORE_CLASSES_2024
            and record.get("edition") == "2024"
            and source_path.endswith(f"/{name}.htm")
        ):
            rules[name] = class_progression_from_record(record)
    assert set(rules) == set(CORE_CLASSES_2024)
    return rules


def _all_grants(rule: ClassProgression) -> list[dict[str, Any]]:
    return [
        grant
        for level in range(1, 21)
        for grant in core_feature_grants(rule, level)
    ]


def _registry(rule: ClassProgression) -> dict[str, Any]:
    return compile_feature_runtime_registry(
        _all_grants(rule),
        resources=progression_resource_updates(rule, 20),
        scalings=progression_scaling_updates(rule, 20),
        actions=(
            action
            for level in range(1, 21)
            for action in core_runtime_actions(rule, level)
        ),
    )


def _registry_at(rule: ClassProgression, level: int) -> dict[str, Any]:
    return compile_feature_runtime_registry(
        [
            grant
            for current_level in range(1, level + 1)
            for grant in core_feature_grants(rule, current_level)
        ],
        resources=progression_resource_updates(rule, level),
        scalings=progression_scaling_updates(rule, level),
        class_levels={rule.name: level},
        total_level=level,
    )


def test_movement_feature_contracts_are_full_and_typed() -> None:
    cases = {"奥能冲锋": "teleport", "月光飞步": "moonlight_step"}
    for name, marker in cases.items():
        runtime = subclass_feature_runtime_definition(
            {"name": name, "class_name": "fixture", "class_level": 10}
        )
        assert runtime is not None
        contract = feature_runtime_contract(
            feature_name=name,
            class_name="fixture",
            class_level=10,
            definition=runtime,
            kind="subclass_feature",
        )
        assert contract["automation_status"] == "full"

        payload = json.dumps(runtime, ensure_ascii=False)
        assert marker in payload

    moonlight = subclass_feature_runtime_definition(
        {"name": "月光飞步", "class_name": "德鲁伊", "class_level": 10}
    )
    assert moonlight is not None
    moonlight_action = moonlight["actions"]["moonlight_step"]
    assert moonlight_action["resource_key"] == "moonlight_step"
    assert [effect["kind"] for effect in moonlight_action["effects"]] == [
        "teleport",
        "activate_timed_condition",
    ]

    soul_blades = subclass_feature_runtime_definition(
        {"name": "灵魂之刃", "class_name": "fixture", "class_level": 9}
    )
    assert soul_blades is not None
    soul_contract = feature_runtime_contract(
        feature_name="灵魂之刃",
        class_name="fixture",
        class_level=9,
        definition=soul_blades,
        kind="subclass_feature",
    )
    assert soul_contract["automation_status"] == "partial"
    assert soul_blades["actions"]["psychic_teleportation"]["runtime_execution"][
        "consumer"
    ] == "combat_feature_action"


def test_draconic_resilience_has_unarmored_charisma_ac_and_hp_scaling_contract() -> None:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "龙族体魄 Draconic Resilience",
            "class_name": "术士",
            "class_level": 3,
        }
    )
    assert runtime is not None
    modifier = runtime["combat_start"]["modifiers"][0]
    assert modifier["formula"] == "10+dexterity_modifier+charisma_modifier"
    assert {
        key: runtime["advancement"][key]
        for key in (
            "kind",
            "minimum_class_level",
            "initial_bonus",
            "per_level_bonus",
            "runtime_execution",
            "automation_status",
            "requires_dm_adjudication",
        )
    } == {
        "kind": "hit_points_by_class_level",
        "minimum_class_level": 3,
        "initial_bonus": 3,
        "per_level_bonus": 1,
        "runtime_execution": {
            "status": "ready",
            "consumer": "advancement_service",
        },
        "automation_status": "full",
        "requires_dm_adjudication": False,
    }
    ac, details = resolve_unarmored_defense_ac(
        12,
        {"dexterity": 16, "charisma": 18},
        {"combat_start": {"modifiers": [modifier]}},
        equipment_state_authoritative=True,
        wearing_armor=False,
        wielding_shield=False,
    )
    assert ac == 17
    assert details["formula"] == "10+dexterity_modifier+charisma_modifier"


def test_otherworldly_glamour_closes_charisma_bonus_and_skill_choice() -> None:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "妖冶娴都 Otherworldly Glamour",
            "class_name": "游侠",
            "class_level": 3,
        }
    )
    assert runtime is not None
    modifier = runtime["combat_start"]["modifiers"][0]
    assert modifier["stat"] == "ability_check"
    assert modifier["ability"] == "charisma"
    assert modifier["value_source"] == "wisdom_modifier"
    assert modifier["applies_when"] == "every_charisma_ability_check"
    assert runtime["advancement"]["choice_requirement"]["minimum"] == 1
    assert runtime["advancement"]["choice_requirement"]["maximum"] == 1
    assert runtime["automation_status"] == "full"


def test_illusory_self_has_full_reaction_and_spell_slot_reset_contract() -> None:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "幻影化形",
            "class_name": "游荡者",
            "class_level": 3,
        }
    )
    assert runtime is not None
    resource = runtime["resources"]["illusory_self"]
    action = runtime["actions"]["illusory_self"]
    assert resource["reset_options"] == {
        "kind": "spell_slot",
        "minimum_level": 2,
        "cost": 1,
    }
    assert resource["automation_status"] == "full"
    assert action["runtime_execution"]["consumer"] == "pre_damage_reaction_window"
    assert action["pre_damage_intervention"]["damage_transform"] == {"operation": "set_zero"}
    assert action["automation_status"] == "full"


def test_dragon_wings_has_flight_lifecycle_and_sorcery_point_reset() -> None:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "龙翼",
            "class_name": "术士",
            "class_level": 14,
        }
    )
    assert runtime is not None
    assert runtime["combat_start"]["movement_modes"][0]["mode"] == "fly"
    assert runtime["actions"]["dragon_wings"]["effects"] == [
        {
            "kind": "activate_duration_condition",
            "condition": "dragon_wings",
            "duration_unit": "minutes",
            "duration_value": 60,
        }
    ]
    assert runtime["actions"]["reset_dragon_wings"]["effects"] == [
        {
            "kind": "restore_resource",
            "resource_key": "dragon_wings",
            "operation": "set_to_max",
        }
    ]


def test_heroic_warrior_has_turn_start_inspiration_and_d20_reroll() -> None:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "勇战英豪",
            "class_name": "战士",
            "class_level": 10,
        }
    )
    assert runtime is not None
    action = runtime["actions"]["heroic_inspiration"]
    assert action["operation"] == {"kind": "reroll", "selection": "replacement"}
    assert action["eligibility"]["state"] == {"key": "heroic_inspiration"}
    assert runtime["triggers"][0]["event"] == "turn_start"
    assert runtime["triggers"][0]["effects"] == [
        {"kind": "grant_feature_state_if_missing", "state_key": "heroic_inspiration"}
    ]


def test_turn_refresh_consumes_first_turn_and_conditional_movement_modes() -> None:
    actor = Combatant(
        combat_id="combat",
        display_name="Scout",
        entity_type="character",
        speed_ft=30,
        movement_remaining_ft=0,
        conditions=["elemental_attunement"],
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "first_turn_movement": [{"amount_ft": 10}],
                    "movement_modes": [
                        {
                            "mode": "fly",
                            "speed_source": "current_speed",
                            "applies_when": "elemental_attunement",
                        },
                        {
                            "mode": "swim",
                            "speed_ft": 20,
                            "applies_when": "not_active",
                        },
                    ],
                }
            }
        },
    )

    CombatEngineService._refresh_new_turn_resources(actor, round_number=1)

    assert actor.movement_remaining_ft == 40
    assert actor.snapshot_json["active_movement_modes"] == {"fly": 30}


def test_all_core_class_grants_compile_for_levels_one_through_twenty() -> None:
    rules = _core_rules()
    for class_name in CORE_CLASSES_2024:
        rule = rules[class_name]
        for level in range(1, 21):
            grants = core_feature_grants(rule, level)
            assert all(
                grant["runtime"]["automation_status"] in {"full", "partial", "dm_only"}
                and grant["runtime"]["requires_dm_adjudication"]
                == grant["runtime"]["contract"]["requires_dm_adjudication"]
                and grant["runtime"]["registry"]
                and grant["runtime"]["contract"]["class_level"] == level
                for grant in grants
            )
            registry = compile_feature_runtime_registry(
                grants,
                resources=progression_resource_updates(rule, level),
                scalings=progression_scaling_updates(rule, level),
                actions=core_runtime_actions(rule, level),
            )
            assert registry["schema_version"] == FEATURE_RUNTIME_SCHEMA_VERSION
            assert registry["combat_start"]["attack_action_count"] >= 1
            assert isinstance(registry["dm_only"], list)
            assert len(registry["feature_contracts"]) == len(grants)


def test_feature_runtime_compiles_one_stable_canonical_block_set() -> None:
    registry = _registry(_core_rules()["圣武士"])
    rebuilt = _registry(_core_rules()["圣武士"])

    blocks = registry["feature_blocks"]
    assert blocks
    assert {item["kind"] for item in blocks} == {"class_feature"}
    assert {item["block_type"] for item in blocks} >= {
        "modifier",
        "defense",
        "resource",
        "action",
        "attack_rider",
    }
    assert [item["id"] for item in blocks] == [item["id"] for item in rebuilt["feature_blocks"]]
    assert all(
        not (item["automation_status"] == "full" and item["requires_dm_adjudication"])
        for item in blocks
    )
    assert any(
        item.get("id") == "radiant_strikes:bonus_damage"
        for item in feature_block_payloads(registry, "attack_rider")
    )


def test_feature_condition_lifecycle_spec_is_shared_and_fail_closed() -> None:
    timed = feature_condition_runtime_spec("activate_timed_condition", "steady_aim")
    assert timed == {
        "state_name": "steady_aim",
        "expires": ["turn_start", "turn_end"],
    }
    assert feature_condition_runtime_spec(
        "activate_timed_condition", "unstructured_condition"
    ) is None
    assert feature_condition_runtime_spec(
        "activate_duration_condition", "raging"
    ) == {
        "state_name": "feature_raging",
        "duration_units": ["rounds", "minutes"],
    }
    assert feature_condition_runtime_spec(
        "activate_duration_condition", "starry_form"
    ) == {
        "state_name": "feature_starry_form",
        "duration_units": ["minutes"],
    }


def test_level_by_level_contract_covers_every_named_core_feature() -> None:
    for rule in _core_rules().values():
        for level_rule in rule.levels:
            contract = core_class_level_runtime_contract(rule, level_rule.level)
            assert contract["schema_version"] == FEATURE_RUNTIME_SCHEMA_VERSION
            assert contract["proficiency_bonus"] == level_rule.proficiency_bonus
            assert [item["name"] for item in contract["feature_contracts"]] == list(
                level_rule.features
            )
            assert sum(contract["automation_summary"].values()) == len(
                level_rule.features
            )
            assert all(
                item["automation_status"] in {"full", "partial", "dm_only"}
                and isinstance(item["reasons"], list)
                for item in contract["feature_contracts"]
            )


def test_runtime_progression_includes_current_resources_proficiency_and_spell_slots() -> None:
    wizard = _core_rules()["法师"]
    resources = {
        **merge_spell_slot_resources({}, {"法师": 17}),
        **progression_resource_updates(wizard, 17),
    }
    registry = compile_feature_runtime_registry(
        [
            grant
            for level in range(1, 18)
            for grant in core_feature_grants(wizard, level)
        ],
        resources=resources,
        scalings=progression_scaling_updates(wizard, 17),
        class_levels={"法师": 17},
        total_level=17,
    )

    assert registry["progression"] == {
        **registry["progression"],
        "class_levels": {"法师": 17},
        "total_level": 17,
        "proficiency_bonus": 6,
    }
    assert registry["resources"]["spell_slots_9"] == {
        **registry["resources"]["spell_slots_9"],
        "current": 1,
        "max": 1,
    }
    assert registry["progression"]["spell_slots"]["spell_slots_5"]["max"] == 2


def test_spellcasting_capability_block_uses_existing_spell_economy_consumer() -> None:
    definition = feature_runtime_definition(
        feature_name="施法",
        class_name="法师",
        class_level=1,
    )
    contract = feature_runtime_contract(
        feature_name="施法",
        class_name="法师",
        class_level=1,
        definition=definition,
    )
    assert contract["automation_status"] == "full"
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "施法",
                "kind": "class_feature",
                "class_name": "法师",
                "class_level": 1,
                "runtime": {"registry": definition},
            }
        ],
        class_levels={"法师": 1},
        total_level=1,
    )
    assert registry["spellcasting"][0]["consumer"] == "spell_economy_service"


def test_survivor_contract_covers_death_saves_and_bloodied_turn_healing() -> None:
    runtime = feature_runtime_definition(
        feature_name="百折不挠",
        class_name="战士",
        class_level=18,
        resources={},
        tracked_resource_keys=(),
    )
    defenses = runtime["combat_start"]["defenses"]
    assert {item["kind"] for item in defenses} == {
        "death_save_advantage",
        "death_save_success_threshold",
    }
    trigger = runtime["triggers"][0]
    assert trigger["event"] == "turn_start"
    assert trigger["effects"][0]["kind"] == "restore_hit_points_if_bloodied"
    contract = feature_runtime_contract(
        feature_name="百折不挠",
        class_name="战士",
        class_level=18,
        definition=runtime,
        kind="feature",
    )
    assert contract["automation_status"] == "full"


def test_structured_recovery_events_restore_one_use_on_short_rest_and_full_on_long_rest() -> None:
    rage = progression_resource_updates(_core_rules()["野蛮人"], 15)["rage"]
    exhausted = RestResource(
        "rage",
        current=0,
        maximum=int(rage["max"]),
        recovery="long_rest",
        recovery_events=tuple(rage["recovery_events"]),
    )

    short = resolve_short_rest(
        current_hp=10,
        max_hp=10,
        constitution_modifier=0,
        hit_dice={},
        spends=(),
        resources=(exhausted,),
    )
    assert short.resources[0].current == 1
    long = resolve_long_rest(
        current_hp=10,
        max_hp=10,
        fatigue=0,
        resources=(short.resources[0],),
    )
    assert long.resources[0].current == int(rage["max"])


def test_resource_lifecycle_roll_feature_configs_are_reusable_without_feature_branches() -> None:
    dark = subclass_feature_runtime_definition(
        {
            "name": "黑暗强运 Dark One's Own Luck",
            "class_name": "魔契师",
            "class_level": 6,
            "description": "你可以使用此特性的次数等于你的魅力调整值，完成长休恢复所有次数。",
        }
    )
    assert dark is not None
    dark_action = dark["actions"]["dark_ones_own_luck"]
    assert dark_action["kind"] == "roll_intervention"
    assert dark_action["resource_lifecycle"]["events"] == [
        {"trigger": "long_rest", "operation": "set_to_max"}
    ]

    bard_subclass = {
        "name": "逸闻学院",
        "feature_definitions": [
            {
                "id": "lore:14:peerless",
                "name": "超凡技艺 Peerless Skill",
                "class_level": 14,
                "description": "你可以消耗一次诗人激励使用次数，投掷诗人激励骰并加到失败的检定。",
                "source_record_id": "fixture",
            }
        ],
    }
    grants = subclass_runtime_grants(
        bard_subclass,
        class_name="吟游诗人",
        target_class_level=14,
    )
    assert grants["grants"][0]["runtime"]["automation_status"] == "full"
    runtime_action = grants["grants"][0]["runtime"]["registry"]["actions"]["peerless_skill"]
    assert runtime_action["resource"]["key"] == "bardic_inspiration"
    assert runtime_action["operation"]["die_sides_expression"] == "die_sides"


def test_generic_healing_formula_bounds_bind_die_and_ability_modifier() -> None:
    actor = SimpleNamespace(snapshot_json={"ability_scores": {"wisdom": 16}})
    action = {
        "healing_formula": "martial_arts_die+wisdom_modifier",
        "dice": "D6",
        "minimum_healing": 1,
    }
    assert CombatEngineService._feature_healing_total_bounds(
        action,
        actor=actor,
        character=None,
    ) == (4, 9)


def test_fighter_registry_exposes_attack_count_second_wind_and_action_surge() -> None:
    fighter = _core_rules()["战士"]
    registry = _registry(fighter)

    assert registry["combat_start"]["attack_action_count"] == 4
    assert registry["resources"]["second_wind"]["max"] == 4
    assert registry["resources"]["action_surge"]["max"] == 2
    assert registry["actions"]["second_wind"] == {
        **registry["actions"]["second_wind"],
        "action_cost": "bonus_action",
        "resource_key": "second_wind",
        "resource_cost": 1,
        "target": "self",
        "resolution_kind": "healing",
        "healing_formula": "1d10+class_level",
        "healing": "1d10+20",
    }
    assert registry["actions"]["second_wind"]["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action",
        "effect_kinds": ["healing"],
    }
    assert registry["actions"]["second_wind"]["automation_status"] == "full"
    surge = registry["actions"]["action_surge"]
    assert surge["resource_key"] == "action_surge"
    assert surge["effects"] == [
        {"kind": "grant_action_budget", "amount": 1, "excludes": ["magic_action"]}
    ]
    tactical = registry["actions"]["tactical_mind"]
    assert tactical["kind"] == "roll_intervention"
    assert tactical["trigger"] == "after_failed_d20_test"
    assert tactical["operation"]["kind"] == "failure_recovery"
    assert tactical["operation"]["consume_when"] == "on_success"
    assert tactical["resource"] == {"key": "second_wind", "cost": 1}
    assert tactical["automation_status"] == "full"


def test_rage_and_sneak_attack_keep_exact_scaling_and_conditions() -> None:
    rules = _core_rules()
    barbarian = _registry(rules["野蛮人"])
    rogue = _registry(rules["游荡者"])

    assert barbarian["resources"]["rage"]["max"] == 6
    assert barbarian["actions"]["rage"]["resource_cost"] == 1
    rage_defense = next(
        item
        for item in barbarian["combat_start"]["defenses"]
        if item["id"] == "rage:physical_resistance"
    )
    assert rage_defense["damage_types"] == ["bludgeoning", "piercing", "slashing"]
    assert rage_defense["applies_when"] == "raging"
    assert rage_defense["required_conditions"] == ["raging"]
    rage_damage = next(
        item for item in barbarian["attack_riders"] if item["id"] == "rage:bonus_damage"
    )
    assert rage_damage["value"] == "+4"
    assert rage_damage["applies_when"] == "raging_strength_attack"
    rage_save = next(
        item
        for item in barbarian["combat_start"]["modifiers"]
        if item["id"] == "rage:strength_saving_throw_advantage"
    )
    assert rage_save["automation_status"] == "full"

    sneak_attack = next(
        item for item in rogue["attack_riders"] if item["id"] == "sneak_attack:bonus_damage"
    )
    assert sneak_attack["value"] == "10d6"
    assert sneak_attack["frequency"] == "once_per_turn"
    assert sneak_attack["damage_type"] == "weapon_damage_type"


def test_executable_partial_actions_project_without_claiming_full_automation() -> None:
    rules = _core_rules()
    fighter_2 = _registry_at(rules["战士"], 2)
    fighter_17 = _registry_at(rules["战士"], 17)
    barbarian = _registry_at(rules["野蛮人"], 1)

    surge = fighter_2["actions"]["action_surge"]
    assert surge["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action",
        "effect_kinds": ["grant_action_budget"],
        "remaining_dm_boundaries": [],
    }
    assert fighter_2["resources"]["action_surge"]["max"] == 1
    assert fighter_17["resources"]["action_surge"]["max"] == 2
    assert fighter_17["actions"]["action_surge"]["limits"] == ["once_per_turn"]

    rage = barbarian["actions"]["rage"]
    assert rage["runtime_execution"]["status"] == "ready"
    assert rage["runtime_execution"]["consumer"] == "combat_feature_action"
    assert rage["automation_status"] == "full"
    assert rage["requires_dm_adjudication"] is False

    projected_fighter = {
        item["feature_id"]: item
        for item in feature_runtime_action_projections(fighter_17)
    }
    projected_barbarian = {
        item["feature_id"]: item
        for item in feature_runtime_action_projections(barbarian)
    }
    assert projected_fighter["action_surge"]["runtime_feature"] is True
    assert projected_fighter["action_surge"]["automation_status"] == "full"
    assert projected_barbarian["rage"]["runtime_feature"] is True
    assert projected_barbarian["rage"]["automation_status"] == "full"

    contracts = {item["name"]: item for item in fighter_17["feature_contracts"]}
    assert contracts["动作如潮（两次）"]["automation_status"] == "full"
    assert contracts["动作如潮（两次）"]["requires_dm_adjudication"] is False


def test_rage_runtime_scaling_tracks_current_level_without_freezing_level_one() -> None:
    barbarian = _core_rules()["野蛮人"]
    expected = {
        1: (2, "+2"),
        9: (4, "+3"),
        16: (5, "+4"),
        20: (6, "+4"),
    }

    for level, (rage_uses, rage_damage) in expected.items():
        registry = _registry_at(barbarian, level)
        rider = next(
            item
            for item in registry["attack_riders"]
            if item["id"] == "rage:bonus_damage"
        )
        assert registry["resources"]["rage"]["max"] == rage_uses
        assert rider["value"] == rage_damage
        assert rider["runtime_execution"] == {
            "status": "ready",
            "consumer": "attack_rider_resolver",
        }


def test_defense_style_is_exact_only_after_the_choice_is_known() -> None:
    generic = compile_feature_runtime_registry(
        [
            {
                "name": "战斗风格",
                "kind": "class_feature",
                "class_name": "战士",
                "class_level": 1,
                "runtime": {"automation_status": "dm_only"},
            }
        ]
    )
    assert generic["combat_start"]["modifiers"] == []
    assert generic["dm_only"][0]["name"] == "战斗风格"

    defense = compile_feature_runtime_registry(
        [
            {
                "name": "防御",
                "kind": "feature_choice",
                "class_name": "战士",
                "class_level": 1,
                "runtime": {"automation_status": "dm_only"},
            }
        ]
    )
    assert defense["dm_only"] == []
    assert defense["combat_start"]["modifiers"] == [
        {
            **defense["combat_start"]["modifiers"][0],
            "stat": "armor_class",
            "operation": "add",
            "value": 1,
            "applies_when": "wearing_armor",
        }
    ]


def test_channel_divinity_focus_and_unknown_features_preserve_their_contracts() -> None:
    rules = _core_rules()
    cleric = _registry(rules["牧师"])
    monk = _registry(rules["武僧"])
    fighter = _registry(rules["战士"])

    assert cleric["resources"]["channel_divinity"] == {
        **cleric["resources"]["channel_divinity"],
        "key": "channel_divinity",
        "max": 4,
        "recovery": "short_rest",
    }
    assert monk["resources"]["focus"] == {
        **monk["resources"]["focus"],
        "key": "focus",
        "max": 20,
        "recovery": "short_rest",
    }
    tactical_mind = fighter["actions"]["tactical_mind"]
    assert tactical_mind["kind"] == "roll_intervention"
    assert tactical_mind["automation_status"] == "full"
    assert tactical_mind["requires_dm_adjudication"] is False


def test_common_feature_contracts_expose_typed_effects_and_passive_defense() -> None:
    lay_on_hands = compile_feature_runtime_registry(
        [
            {
                "name": "圣疗",
                "kind": "class_feature",
                "class_name": "圣武士",
                "class_level": 1,
                "runtime": {
                    "tracked_resource_keys": ["lay_on_hands"],
                },
            }
        ],
        resources={"lay_on_hands": {"label": "圣疗", "max": 5}},
    )
    assert lay_on_hands["actions"]["lay_on_hands"]["resource_cost_mode"] == "amount_or_condition"
    assert lay_on_hands["actions"]["lay_on_hands"]["action_cost"] == "bonus_action"
    assert lay_on_hands["actions"]["lay_on_hands"]["target"] == "ally_or_self"

    indomitable = compile_feature_runtime_registry(
        [
            {
                "name": "不屈",
                "kind": "class_feature",
                "class_name": "战士",
                "class_level": 9,
                "runtime": {"tracked_resource_keys": ["indomitable"]},
            }
        ],
        resources={"indomitable": {"label": "不屈", "max": 1}},
    )
    assert indomitable["actions"]["indomitable"]["resolution_kind"] == "saving_throw_reroll"
    assert indomitable["actions"]["indomitable"]["effects"] == [
        {"kind": "grant_saving_throw_reroll", "scope": "self"}
    ]
    assert indomitable["actions"]["indomitable"]["automation_status"] == "full"
    assert indomitable["actions"]["indomitable"]["requires_dm_adjudication"] is False
    assert feature_runtime_action_projections(indomitable) == []

    evasion = compile_feature_runtime_registry(
        [
            {
                "name": "反射闪避",
                "kind": "class_feature",
                "class_name": "游荡者",
                "class_level": 7,
                "runtime": {},
            }
        ]
    )
    assert any(item["kind"] == "evasion" for item in evasion["combat_start"]["defenses"])


def test_psychic_defenses_consumes_resistance_and_condition_save_advantage() -> None:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "心灵防御 Psychic Defenses",
            "class_name": "术士",
            "class_level": 6,
            "source_record_id": "fixture:psychic-defenses",
        }
    )
    assert runtime is not None
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "心灵防御 Psychic Defenses",
                "kind": "subclass_feature",
                "class_name": "术士",
                "class_level": 6,
                "runtime": {"registry": runtime},
            }
        ]
    )
    target = Combatant(
        id="psychic-defender",
        entity_type="character",
        snapshot_json={"feature_runtime": registry},
    )
    assert CombatEngineService._feature_rule_modifiers(
        target,
        stat="saving_throw",
        condition_names=("charmed",),
    )
    assert not CombatEngineService._feature_rule_modifiers(
        target,
        stat="saving_throw",
        condition_names=("poisoned",),
    )
    defenses = CombatEngineService._damage_defenses(
        target,
        SimpleNamespace(is_magical=False, damage_tags=[], dm_override=False),
        ["psychic"],
    )
    assert "psychic" in defenses[0]


def test_level_twenty_fixed_ability_adjustments_are_typed_and_capped() -> None:
    rules = _core_rules()
    barbarian_grant = next(
        item for item in core_feature_grants(rules["野蛮人"], 20) if item["name"] == "原初斗士"
    )
    monk_grant = next(
        item for item in core_feature_grants(rules["武僧"], 20) if item["name"] == "天人合一"
    )
    assert barbarian_grant["runtime"]["automation_status"] == "full"
    assert monk_grant["runtime"]["automation_status"] == "full"
    assert barbarian_grant["runtime"]["registry"]["advancement"] == {
        "kind": "fixed_ability_score_adjustment",
        "adjustments": {"strength": 4, "constitution": 4},
        "caps": {"strength": 25, "constitution": 25},
        "runtime_execution": {"status": "ready", "consumer": "advancement_service"},
        "automation_status": "full",
        "requires_dm_adjudication": False,
    }
    updated, applied = AdvancementService._apply_fixed_ability_score_adjustments(
        [barbarian_grant],
        ability_scores={
            "strength": 23,
            "dexterity": 10,
            "constitution": 18,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 10,
        },
    )
    assert updated["strength"] == 25
    assert updated["constitution"] == 22
    assert applied == {"strength": 2, "constitution": 4}


def test_table_scalars_include_bardic_die_and_chinese_pact_slot_level() -> None:
    bard = _core_rules()["吟游诗人"]
    pact = _core_rules()["魔契师"]

    assert progression_scaling_updates(bard, 20)["bardic_inspiration_die"] == {
        "label": "诗人激励骰",
        "value": "D12",
        "value_kind": "die",
        "source": "吟游诗人 20级成长表",
        "automation_status": "partial",
        "requires_dm_adjudication": True,
    }
    assert progression_resource_updates(pact, 1)["pact_slots"]["slot_level"] == 1
    assert progression_resource_updates(pact, 17)["pact_slots"]["slot_level"] == 5

    registry = _registry(bard)
    assert registry["resources"]["bardic_inspiration_die"]["value"] == "D12"
    assert registry["actions"]["bardic_inspiration"]["dice"] == "D12"


def test_bardic_inspiration_projection_consumes_resource_and_records_granted_die(
    campaign_client: TestClient,
) -> None:
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "吟游诗人激励",
                "kind": "class_feature",
                "class_name": "吟游诗人",
                "class_level": 1,
                "runtime": {
                    "tracked_resource_keys": ["bardic_inspiration"],
                    "tracked_scaling_keys": ["bardic_inspiration_die"],
                },
            }
        ],
        resources={
            "bardic_inspiration": {
                "label": "吟游诗人激励",
                "current": 2,
                "max": 2,
                "recovery": "long_rest",
            }
        },
        scalings={
            "bardic_inspiration_die": {
                "label": "诗人激励骰",
                "value": "D6",
                "value_kind": "die",
            }
        },
        class_levels={"吟游诗人": 1},
        total_level=1,
    )

    inspiration = registry["actions"]["bardic_inspiration"]
    assert inspiration["automation_status"] == "full"
    assert inspiration["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action_and_player_roll_resolution",
        "effect_kinds": ["grant_roll_die"],
        "window": {
            "phase": "after_failed_d20_test",
            "expires": "duration_end",
            "duration_unit": "hours",
            "duration_value": 1,
        },
        "covered_rules": [
            "target_range_visibility_or_audibility",
            "one_die_per_target",
            "failed_d20_consumption_window",
        ],
    }
    projections = {
        action["feature_id"]: action
        for action in feature_runtime_action_projections(registry)
    }
    assert projections["bardic_inspiration"]["runtime_feature"] is True

    campaign_response = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "吟游诗人激励运行时"},
    )
    assert campaign_response.status_code == 201, campaign_response.text
    campaign = campaign_response.json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "激励者",
            "class_name": "吟游诗人",
            "hp": 20,
            "max_hp": 20,
            "resources": {"bardic_inspiration": {"current": 2, "max": 2}},
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    combat_response = campaign_client.post(
        f"{base}/combats",
        json={"name": "激励骰战斗"},
    )
    assert combat_response.status_code == 201, combat_response.text
    combat = combat_response.json()
    combat_root = f"{base}/combats/{combat['id']}"
    bard_response = campaign_client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "激励者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 1},
                "feature_runtime": registry,
            },
        },
    )
    assert bard_response.status_code == 201, bard_response.text
    bard = bard_response.json()
    ally_response = campaign_client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "受激励盟友",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 2},
            },
        },
    )
    assert ally_response.status_code == 201, ally_response.text
    ally = ally_response.json()

    confirmed = campaign_client.post(
        f"{combat_root}/feature-actions/confirm",
        headers={"X-Request-ID": "bardic-inspiration-runtime"},
        json={
            "actor_combatant_id": bard["id"],
            "actor_version": bard["version"],
            "feature_id": "bardic_inspiration",
            "target_combatant_id": ally["id"],
            "target_version": ally["version"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["result"]["resource_before"] == 2
    assert result["result"]["resource_after"] == 1
    assert result["result"]["roll_die_granted"] == {
        "die_key": "bardic_inspiration_die",
        "value": "D6",
    }
    assert result["actor"]["bonus_action_available"] is False
    assert "feature_dice" not in result["actor"]["snapshot_json"]
    granted_die = result["target"]["snapshot_json"]["feature_dice"][
        "bardic_inspiration_die"
    ]
    assert granted_die == {
        "source": "吟游诗人激励",
        "value": "D6",
        "target_combatant_id": ally["id"],
        "available": True,
        "granted_at": granted_die["granted_at"],
        "expires_at": granted_die["expires_at"],
    }
    persisted = campaign_client.get(f"{base}/characters/{character['id']}")
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["resources"]["bardic_inspiration"]["current"] == 1


def test_resource_recovery_contracts_distinguish_one_use_and_full_pool() -> None:
    def events(key: str, recovery: str) -> list[dict[str, Any]]:
        return compile_feature_runtime_registry(
            [],
            resources={key: {"label": key, "max": 5, "recovery": recovery}},
        )["resources"][key]["recovery_events"]

    one_on_short = [
        {"rest": "short_rest", "operation": "restore", "amount": 1},
        {"rest": "long_rest", "operation": "set_to_max"},
    ]
    all_on_short = [
        {"rest": "short_rest", "operation": "set_to_max"},
        {"rest": "long_rest", "operation": "set_to_max"},
    ]
    assert events("rage", "long_rest") == one_on_short
    assert events("second_wind", "short_rest") == one_on_short
    assert events("channel_divinity", "short_rest") == one_on_short
    assert events("wild_shape", "short_rest") == one_on_short
    assert events("focus", "short_rest") == all_on_short
    assert events("pact_slots", "short_rest") == all_on_short
    assert events("bardic_inspiration", "long_rest") == [
        {"rest": "long_rest", "operation": "set_to_max"}
    ]
    assert events("bardic_inspiration", "short_rest") == all_on_short


def test_feature_extensions_keep_base_resources_without_inventing_actions() -> None:
    rules = _core_rules()

    persistent_rage = compile_feature_runtime_registry(
        core_feature_grants(rules["野蛮人"], 15),
        resources=progression_resource_updates(rules["野蛮人"], 15),
    )
    assert persistent_rage["resources"]["rage"]["recovery_events"] == [
        {"rest": "short_rest", "operation": "set_to_max"},
        {"rest": "long_rest", "operation": "set_to_max"},
    ]
    assert "rage" not in persistent_rage["actions"]

    superior_inspiration = _registry(rules["吟游诗人"])["resources"]["bardic_inspiration"]
    assert {
        "trigger": "initiative_start",
        "operation": "set_to_minimum",
        "minimum": 2,
        "condition": "current_below_2",
    } in superior_inspiration["recovery_events"]

    perfect_focus = compile_feature_runtime_registry(
        core_feature_grants(rules["武僧"], 15),
        resources=progression_resource_updates(rules["武僧"], 15),
    )["resources"]["focus"]
    assert any(
        event.get("trigger") == "initiative_start"
        and event.get("value") == 4
        and event.get("condition") == "current_at_most_3"
        for event in perfect_focus["recovery_events"]
    )
    focus_registry = compile_feature_runtime_registry(
        core_feature_grants(rules["武僧"], 15),
        resources=progression_resource_updates(rules["武僧"], 15),
    )
    focus_contracts = [
        item
        for item in focus_registry["feature_contracts"]
        if item.get("name") == "明镜止水"
    ]
    assert focus_contracts and focus_contracts[0]["automation_status"] == "full"

    archdruid = compile_feature_runtime_registry(
        core_feature_grants(rules["德鲁伊"], 20),
        resources=progression_resource_updates(rules["德鲁伊"], 20),
    )["resources"]["wild_shape"]
    assert {
        "trigger": "initiative_start",
        "operation": "restore",
        "amount": 1,
        "condition": "current_zero",
    } in archdruid["recovery_events"]


def test_choice_bound_feature_actions_are_partial_and_explicit() -> None:
    rules = _core_rules()

    wild_shape = compile_feature_runtime_registry(
        core_feature_grants(rules["德鲁伊"], 2),
        resources=progression_resource_updates(rules["德鲁伊"], 2),
    )["actions"]["wild_shape"]
    assert wild_shape["action_cost"] == "bonus_action"
    assert wild_shape["resolution_kind"] == "choice_required"
    assert wild_shape["effects"] == [
        {
            "kind": "requires_dm_choice",
            "reason": "荒野变形的形态、临时生命值与动作选项需要 DM 选择",
        }
    ]

    divine_intervention = compile_feature_runtime_registry(
        core_feature_grants(rules["牧师"], 10),
        resources=progression_resource_updates(rules["牧师"], 10),
    )
    assert divine_intervention["resources"]["divine_intervention"]["max"] == 1
    assert divine_intervention["actions"]["divine_intervention"]["resolution_kind"] == (
        "choice_required"
    )
    assert divine_intervention["actions"]["divine_intervention"]["resource_cost"] == 1

    lay_on_hands = _registry_at(rules["圣武士"], 5)["actions"]["lay_on_hands"]
    assert lay_on_hands["resolution_kind"] == "healing"
    assert lay_on_hands["resource_cost_mode"] == "amount_or_condition"
    assert lay_on_hands["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action",
        "effect_kinds": ["healing", "condition_cure"],
        "remaining_dm_boundaries": ["contact_distance_requires_authoritative_position"],
    }
    assert lay_on_hands["automation_status"] == "full"

    sorcerous_restoration = progression_resource_updates(rules["术士"], 5)
    assert sorcerous_restoration["sorcery_restoration"]["max"] == 1
    assert sorcerous_restoration["sorcery_restoration"]["requires_dm_adjudication"] is False
    assert sorcerous_restoration["sorcery_restoration"]["automation_status"] == "full"

    magical_cunning = progression_resource_updates(rules["魔契师"], 2)
    assert magical_cunning["magical_cunning"]["max"] == 1
    assert magical_cunning["magical_cunning"]["recovery"] == "long_rest"

    ranger_resources = progression_resource_updates(
        rules["游侠"],
        14,
        ability_scores={"wisdom": 16},
    )
    assert ranger_resources["tireless"]["max"] == 3
    assert ranger_resources["nature_veil"]["max"] == 3
    assert ranger_resources["tireless"]["requires_dm_adjudication"] is False
    assert ranger_resources["tireless"]["automation_status"] == "full"
    assert ranger_resources["nature_veil"]["requires_dm_adjudication"] is False
    assert ranger_resources["nature_veil"]["automation_status"] == "full"


def test_paladin_restoring_touch_extends_lay_on_hands_condition_contract() -> None:
    rules = _core_rules()
    registry = _registry_at(rules["圣武士"], 14)
    action = registry["actions"]["lay_on_hands"]
    assert action["condition_cure_options"] == [
        "blinded",
        "charmed",
        "deafened",
        "frightened",
        "paralyzed",
        "poisoned",
        "stunned",
    ]
    contract = next(
        item for item in registry["feature_contracts"] if item["name"] == "复原之触"
    )
    assert contract["automation_status"] == "full"
    assert contract["requires_dm_adjudication"] is False


def test_new_passive_and_attack_contracts_are_typed_but_not_automatic() -> None:
    rules = _core_rules()

    aura = _registry(rules["圣武士"])
    saving_aura = next(
        item
        for item in aura["combat_start"]["modifiers"]
        if item["id"] == "aura_of_protection:saving_throw"
    )
    assert saving_aura["value_source"] == "charisma_modifier"
    assert saving_aura["minimum"] == 1
    assert saving_aura["automation_status"] == "full"
    assert saving_aura["requires_dm_adjudication"] is False
    assert saving_aura["runtime_execution"] == {
        "status": "ready",
        "consumer": "saving_throw_resolution",
    }
    assert saving_aura["ranged_passive"] == {
        "range_group": "paladin_aura_radius",
        "stacking_group": "aura_of_protection_saving_throw",
        "source_scope": "self",
        "target_relation": "self_and_allies",
        "range_ft": 10,
        "requires_grid_position_for_others": True,
        "source_forbidden_conditions": ["incapacitated"],
        "stacking": "best",
        "effect_kind": "numeric_modifier",
    }
    courage = compile_feature_runtime_registry(
        core_feature_grants(rules["圣武士"], 10),
        resources=progression_resource_updates(rules["圣武士"], 10),
    )
    courage_immunity = next(
        item
        for item in courage["combat_start"]["defenses"]
        if item["id"] == "aura_of_courage:frightened_immunity"
    )
    assert courage_immunity["condition"] == "frightened"
    assert courage_immunity["automation_status"] == "full"
    assert courage_immunity["requires_dm_adjudication"] is False
    assert courage_immunity["runtime_execution"] == {
        "status": "ready",
        "consumer": "condition_immunity_resolution",
    }
    assert courage_immunity["ranged_passive"]["range_group"] == "paladin_aura_radius"

    expanded = compile_feature_runtime_registry(
        core_feature_grants(rules["圣武士"], 18),
        resources=progression_resource_updates(rules["圣武士"], 18),
    )
    override = next(
        item
        for item in expanded["combat_start"]["defenses"]
        if item["kind"] == "ranged_passive_range_override"
    )
    assert override["applies_to"] == "range_group"
    assert override["target_range_group"] == "paladin_aura_radius"
    assert override["range_ft"] == 30
    assert override["automation_status"] == "full"

    jack = compile_feature_runtime_registry(core_feature_grants(rules["吟游诗人"], 2))
    assert jack["combat_start"]["modifiers"] == [
        {
            **jack["combat_start"]["modifiers"][0],
            "stat": "ability_check",
            "operation": "add",
            "value_source": "half_proficiency_bonus",
            "applies_when": "ability_check_without_proficiency",
        }
    ]
    jack_modifier = jack["combat_start"]["modifiers"][0]
    assert jack_modifier["automation_status"] == "full"
    assert jack_modifier["requires_dm_adjudication"] is False
    assert jack_modifier["runtime_execution"] == {
        "status": "ready",
        "consumer": "player_roll_resolution",
    }


    martial_arts = _registry(rules["武僧"])
    martial_die = next(
        item
        for item in martial_arts["combat_start"]["modifiers"]
        if item["id"] == "martial_arts:damage_die"
    )
    assert martial_die["scaling_key"] == "martial_arts_die"
    assert martial_die["value"] == "1d12"
    assert martial_die["requires_dm_adjudication"] is True

    radiant_strikes = next(
        item
        for item in _registry(rules["圣武士"])["attack_riders"]
        if item["id"] == "radiant_strikes:bonus_damage"
    )
    assert radiant_strikes["automation_status"] == "full"
    assert radiant_strikes["requires_dm_adjudication"] is False
    assert radiant_strikes["runtime_execution"] == {
        "status": "ready",
        "consumer": "attack_damage_resolution",
    }

    paladin_rider = _registry(rules["圣武士"])["attack_riders"]
    assert next(item for item in paladin_rider if item["id"] == "radiant_strikes:bonus_damage") == {
        **next(item for item in paladin_rider if item["id"] == "radiant_strikes:bonus_damage"),
        "value": "1d8",
        "damage_type": "radiant",
        "frequency": "once_per_turn",
    }
    barbarian_rider = compile_feature_runtime_registry(
        core_feature_grants(rules["野蛮人"], 9),
        resources=progression_resource_updates(rules["野蛮人"], 9),
        scalings=progression_scaling_updates(rules["野蛮人"], 9),
    )["attack_riders"]
    brutal = next(item for item in barbarian_rider if item["id"] == "brutal_strike:bonus_damage")
    assert brutal["value"] == "1d10"
    assert brutal["applies_when"] == "brutal_strike_eligible"


def test_ranger_tireless_and_nature_veil_have_executable_runtime_contracts() -> None:
    registry = _registry(_core_rules()["游侠"])
    assert registry["actions"]["tireless"]["resolution_kind"] == "temporary_healing"
    assert registry["actions"]["tireless"]["resource_cost"] == 1
    assert registry["actions"]["tireless"]["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action_and_rest_resolution",
        "effect_kinds": ["temporary_healing", "reduce_exhaustion"],
    }
    assert registry["actions"]["tireless"]["automation_status"] == "full"
    assert registry["actions"]["tireless"]["rest_effects"] == [
        {"kind": "reduce_exhaustion", "rest": "short_rest", "amount": 1}
    ]
    assert registry["actions"]["nature_veil"]["effects"] == [
        {
            "kind": "activate_timed_condition",
            "condition": "隐形",
            "expires": "turn_start",
        }
    ]
    assert registry["actions"]["nature_veil"]["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action",
        "effect_kinds": ["activate_timed_condition"],
    }
    assert registry["actions"]["nature_veil"]["automation_status"] == "full"


def test_base_rage_contract_does_not_leak_into_named_rage_upgrades() -> None:
    rules = _core_rules()["野蛮人"]
    registry = compile_feature_runtime_registry(
        [*core_feature_grants(rules, 1), *core_feature_grants(rules, 11)],
        resources=progression_resource_updates(rules, 11),
        scalings=progression_scaling_updates(rules, 11),
        actions=[*core_runtime_actions(rules, 1), *core_runtime_actions(rules, 11)],
    )
    assert registry["actions"]["rage"]["name"] == "狂暴"
    assert not any(
        item["id"] == "rage:physical_resistance"
        and item["feature_name"] == "坚韧狂暴"
        for item in registry["combat_start"]["defenses"]
    )


def test_feral_instinct_publishes_executable_initiative_advantage() -> None:
    rules = _core_rules()["野蛮人"]
    registry = _registry_at(rules, 7)
    modifier = next(
        item
        for item in registry["combat_start"]["modifiers"]
        if item["id"] == "feral_instinct:initiative_advantage"
    )
    assert modifier["stat"] == "initiative"
    assert modifier["operation"] == "advantage"
    assert modifier["automation_status"] == "full"
    assert modifier["requires_dm_adjudication"] is False


def test_initiative_start_resource_recovery_applies_only_exact_conditions() -> None:
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "先发激励",
                "class_name": "吟游诗人",
                "class_level": 18,
                "runtime": {
                    "registry": {
                        "combat_start": {"modifiers": [], "defenses": []},
                        "resources": {
                            "bardic_inspiration": {
                                "recovery_events": [
                                    {
                                        "trigger": "initiative_start",
                                        "operation": "set_to_minimum",
                                        "minimum": 2,
                                        "condition": "current_below_2",
                                    }
                                ]
                            },
                            "unknown": {
                                "recovery_events": [
                                    {
                                        "trigger": "initiative_start",
                                        "operation": "restore",
                                        "amount": 99,
                                        "condition": "dm_judgment",
                                    }
                                ]
                            },
                        },
                    },
                    "automation_status": "full",
                },
            }
        ]
    )
    updated, applied = apply_initiative_start_resource_recovery(
        {
            "bardic_inspiration": {"current": 0, "max": 5},
            "unknown": {"current": 0, "max": 5},
        },
        registry,
    )
    assert updated["bardic_inspiration"]["current"] == 2
    assert updated["unknown"]["current"] == 0
    assert applied == [
        {
            "resource_key": "bardic_inspiration",
            "before": 0,
            "after": 2,
            "operation": "set_to_minimum",
            "condition": "current_below_2",
        }
    ]


def test_unarmored_defense_formulas_are_class_specific_and_explicitly_partial() -> None:
    rules = _core_rules()
    barbarian = _registry(rules["野蛮人"])
    monk = _registry(rules["武僧"])

    barbarian_ac = next(
        item
        for item in barbarian["combat_start"]["modifiers"]
        if item["id"] == "野蛮人:unarmored_defense"
    )
    assert barbarian_ac["formula"] == "10+dexterity_modifier+constitution_modifier"
    assert barbarian_ac["requirements"] == ["not_wearing_armor"]
    assert barbarian_ac["shield_allowed"] is True
    assert barbarian_ac["automation_status"] == "full"
    assert barbarian_ac["requires_dm_adjudication"] is False

    monk_ac = next(
        item
        for item in monk["combat_start"]["modifiers"]
        if item["id"] == "武僧:unarmored_defense"
    )
    assert monk_ac["formula"] == "10+dexterity_modifier+wisdom_modifier"
    assert monk_ac["requirements"] == ["not_wearing_armor", "not_wielding_shield"]
    assert monk_ac["shield_allowed"] is False
    assert monk_ac["automation_status"] == "full"


def test_unarmored_defense_resolves_only_with_authoritative_equipment_state() -> None:
    rules = _core_rules()
    barbarian = _registry_at(rules["野蛮人"], 1)
    resolved, details = resolve_unarmored_defense_ac(
        10,
        {"dexterity": 16, "constitution": 18},
        barbarian,
        equipment_state_authoritative=True,
        wearing_armor=False,
        wielding_shield=True,
    )
    assert resolved == 19
    assert details is not None
    assert details["mode"] == "unarmored_defense"
    assert details["wielding_shield"] is True

    unchanged, no_details = resolve_unarmored_defense_ac(
        16,
        {"dexterity": 16, "constitution": 18},
        barbarian,
        equipment_state_authoritative=False,
        wearing_armor=False,
        wielding_shield=False,
    )
    assert unchanged == 16
    assert no_details is None


def test_speed_features_resolve_only_from_explicit_equipment_state() -> None:
    fast_movement = feature_runtime_definition(
        feature_name="快速移动",
        class_name="野蛮人",
        class_level=5,
        modifiers=[
            {
                "stat": "speed_ft",
                "operation": "add",
                "scope": "self",
                "value": 10,
                "applies_when": "not_wearing_heavy_armor",
            }
        ],
    )
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "快速移动",
                "class_name": "野蛮人",
                "class_level": 5,
                "runtime": {"registry": fast_movement},
            }
        ]
    )

    resolved, details = resolve_feature_speed(
        30,
        registry,
        equipment_state_authoritative=True,
        wearing_armor=False,
        wielding_shield=False,
        wearing_heavy_armor=False,
    )
    assert resolved == 40
    assert details is not None
    assert [item["source"] for item in details["applied"]] == ["快速移动"]

    heavy, heavy_details = resolve_feature_speed(
        30,
        registry,
        equipment_state_authoritative=True,
        wearing_armor=True,
        wielding_shield=False,
        wearing_heavy_armor=True,
    )
    assert heavy == 30
    assert heavy_details is not None
    assert heavy_details["skipped"][0]["reason"] == "wearing_heavy_armor"

    unknown, unknown_details = resolve_feature_speed(
        30,
        registry,
        equipment_state_authoritative=False,
        wearing_armor=False,
        wielding_shield=False,
    )
    assert unknown == 30
    assert unknown_details is not None
    assert unknown_details["skipped"][0]["reason"] == "equipment_state_not_authoritative"


def test_unarmored_movement_requires_no_armor_and_no_shield() -> None:
    definition = feature_runtime_definition(
        feature_name="无甲移动",
        class_name="武僧",
        class_level=2,
        modifiers=[
            {
                "stat": "speed_ft",
                "operation": "add",
                "scope": "self",
                "value": 10,
                "applies_when": "unarmored_and_not_using_shield",
            }
        ],
    )
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "无甲移动",
                "class_name": "武僧",
                "class_level": 2,
                "runtime": {"registry": definition},
            }
        ]
    )
    assert resolve_feature_speed(
        30,
        registry,
        equipment_state_authoritative=True,
        wearing_armor=False,
        wielding_shield=False,
        wearing_heavy_armor=False,
    )[0] == 40
    shielded, details = resolve_feature_speed(
        30,
        registry,
        equipment_state_authoritative=True,
        wearing_armor=False,
        wielding_shield=True,
        wearing_heavy_armor=False,
    )
    assert shielded == 30
    assert details is not None
    assert details["skipped"][0]["reason"] == "wearing_armor_or_wielding_shield"


def test_reactions_and_monk_defenses_publish_typed_contracts() -> None:
    rules = _core_rules()
    bard = _registry(rules["吟游诗人"])
    monk = _registry(rules["武僧"])

    countercharm = bard["actions"]["countercharm"]
    assert countercharm["action_cost"] == "reaction"
    assert countercharm["trigger"]["conditions"] == ["charmed", "frightened"]
    assert countercharm["reroll_mode"] == "advantage"
    assert countercharm["resolution_kind"] == "saving_throw_reroll"
    assert countercharm["activation_window"] == "after_failed_saving_throw"
    assert countercharm["runtime_execution"] == {
        "status": "ready",
        "consumer": "saving_throw_reaction_window",
        "effect_kinds": ["saving_throw_reroll"],
    }
    assert countercharm["automation_status"] == "full"
    assert countercharm["requires_dm_adjudication"] is False
    assert "effects" not in countercharm

    deflect = monk["actions"]["deflect_attacks"]
    assert deflect["name"] == "拨挡能量"
    assert deflect["action_cost"] == "reaction"
    assert deflect["eligible_damage_types"] == "all"
    assert deflect["redirect_resource_key"] == "focus"
    assert deflect["automation_status"] == "full"
    assert deflect["requires_dm_adjudication"] is False

    survivor = monk["actions"]["disciplined_survivor"]
    assert survivor["resource_key"] == "focus"
    assert survivor["resource_cost"] == 1
    assert survivor["effects"] == [
        {"kind": "grant_saving_throw_reroll", "scope": "self"}
    ]
    assert survivor["automation_status"] == "full"
    assert survivor["requires_dm_adjudication"] is False
    assert survivor["runtime_execution"] == {
        "status": "ready",
        "consumer": "saving_throw_resolution",
        "effect_kinds": ["grant_saving_throw_reroll"],
        "remaining_dm_boundaries": [],
    }

    superior = next(
        item
        for item in monk["combat_start"]["defenses"]
        if item["id"] == "superior_defense:all_except_force_resistance"
    )
    assert superior["operation"] == "resistance"
    assert "force" not in superior["damage_types"]
    assert {"bludgeoning", "fire", "psychic", "radiant"} <= set(
        superior["damage_types"]
    )
    assert superior["applies_when"] == "superior_defense_active"
    assert superior["required_conditions"] == ["superior_defense"]
    assert superior["automation_status"] == "full"
    assert superior["requires_dm_adjudication"] is False

    action = monk["actions"]["superior_defense"]
    assert action["resolution_kind"] == "condition"
    assert action["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action",
        "effect_kinds": ["activate_duration_condition"],
    }
    assert action["automation_status"] == "full"
    assert action["requires_dm_adjudication"] is False


def test_rogue_and_monk_event_bound_features_keep_explicit_dm_boundaries() -> None:
    rules = _core_rules()
    rogue = _registry_at(rules["游荡者"], 7)
    monk_3 = _registry_at(rules["武僧"], 3)
    monk_13 = _registry_at(rules["武僧"], 13)

    action = rogue["actions"]["cunning_action"]
    assert action["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action",
        "effect_kinds": ["cunning_action_choice"],
    }
    assert action["automation_status"] == "full"
    assert action["requires_dm_adjudication"] is False

    steady_aim = rogue["actions"]["steady_aim"]
    assert steady_aim["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action",
        "effect_kinds": ["activate_timed_condition"],
    }
    assert steady_aim["automation_status"] == "full"
    assert steady_aim["requires_dm_adjudication"] is False

    uncanny_dodge = rogue["actions"]["uncanny_dodge"]
    assert uncanny_dodge["runtime_execution"] == {
        "status": "ready",
        "consumer": "pre_damage_reaction_window",
    }
    assert uncanny_dodge["automation_status"] == "full"
    assert uncanny_dodge["requires_dm_adjudication"] is False

    rogue_projections = {
        item["feature_id"] for item in feature_runtime_action_projections(rogue)
    }
    assert "cunning_action" in rogue_projections
    assert "steady_aim" in rogue_projections

    evasion = next(
        item
        for item in rogue["combat_start"]["defenses"]
        if item["id"] == "evasion"
    )
    assert evasion["success_damage_multiplier"] == 0
    assert evasion["failure_damage_multiplier"] == 0.5
    assert evasion["runtime_execution"] == {
        "status": "ready",
        "consumer": "saving_throw_damage_resolution",
    }
    assert evasion["automation_status"] == "full"

    early_deflect = monk_3["actions"]["deflect_attacks"]
    energy_deflect = monk_13["actions"]["deflect_attacks"]
    assert early_deflect["eligible_damage_types"] == [
        "bludgeoning",
        "piercing",
        "slashing",
    ]
    assert early_deflect["damage_reduction"] == "1d10+dexterity_modifier+3"
    assert energy_deflect["eligible_damage_types"] == "all"
    assert energy_deflect["damage_reduction"] == "1d10+dexterity_modifier+13"
    assert energy_deflect["runtime_execution"] == {
        "status": "ready",
        "consumer": "pre_damage_reaction_window",
        "consumer_steps": [
            "focus_consumption",
            "target_selection_within_range",
            "dexterity_save",
            "redirect_damage",
        ],
    }
    assert energy_deflect["automation_status"] == "full"
    assert energy_deflect["requires_dm_adjudication"] is False
    assert "deflect_attacks" in {
        item["feature_id"] for item in feature_runtime_action_projections(monk_13)
    }


def test_fixed_feature_resources_expose_recovery_without_claiming_full_automation() -> None:
    rules = _core_rules()
    sorcerer = _registry(rules["术士"])
    rogue = _registry(rules["游荡者"])

    innate = sorcerer["resources"]["innate_sorcery"]
    assert innate["max"] == 2
    assert innate["recovery_events"] == [
        {"rest": "long_rest", "operation": "set_to_max"}
    ]
    assert innate["automation_status"] == "full"
    assert sorcerer["actions"]["innate_sorcery"]["effects"] == [
        {
            "kind": "activate_duration_condition",
            "condition": "innate_sorcery",
            "duration_unit": "minutes",
            "duration_value": 1,
        }
    ]
    assert sorcerer["actions"]["innate_sorcery"]["automation_status"] == "full"
    assert sorcerer["actions"]["innate_sorcery"]["runtime_execution"]["status"] == "ready"
    projected = {
        item["feature_id"]: item
        for item in feature_runtime_action_projections(sorcerer)
    }
    assert projected["innate_sorcery"]["runtime_feature"] is True

    stroke = rogue["resources"]["stroke_of_luck"]
    assert stroke["max"] == 1
    assert stroke["recovery_events"] == [
        {"rest": "short_rest", "operation": "set_to_max"},
        {"rest": "long_rest", "operation": "set_to_max"},
    ]
    stroke_action = rogue["actions"]["stroke_of_luck"]
    assert stroke_action["replacement"] == {"d20_roll": 20}
    assert stroke_action["automation_status"] == "full"
    assert stroke_action["requires_dm_adjudication"] is False
    assert stroke_action["runtime_execution"] == {
        "status": "ready",
        "consumer": "player_roll_resolution",
        "effect_kinds": ["replace_d20_roll"],
        "remaining_dm_boundaries": [],
    }

    slippery = next(
        item
        for item in rogue["combat_start"]["modifiers"]
        if item["id"] == "slippery_mind:saving_throw_proficiencies"
    )
    assert slippery["abilities"] == ["wisdom", "charisma"]
    elusive = next(
        item
        for item in rogue["combat_start"]["defenses"]
        if item["id"] == "elusive:suppress_incoming_advantage"
    )
    assert elusive["automation_status"] == "full"
    assert elusive["runtime_execution"] == {
        "status": "ready",
        "consumer": "attack_context_resolver",
    }


def test_ranger_hunters_mark_upgrades_require_explicit_state_and_feed_attack_riders() -> None:
    ranger = _registry(_core_rules()["游侠"])

    precise = next(
        item
        for item in ranger["combat_start"]["modifiers"]
        if item["id"] == "precise_hunter:marked_target_advantage"
    )
    assert precise["operation"] == "advantage"
    assert precise["automation_status"] == "full"
    assert precise["requires_dm_adjudication"] is False
    assert precise["runtime_execution"] == {
        "status": "ready",
        "consumer": "attack_context_resolver",
        "eligibility": "actor_state_target_id",
    }

    rider = next(
        item
        for item in ranger["attack_riders"]
        if item["id"] == "foe_slayer:hunter_mark_damage"
    )
    assert rider["kind"] == "post_hit_rider"
    assert rider["trigger"] == "after_hit"
    assert rider["damage"] == {
        "id": "hunter_mark_damage",
        "expression": "1d10",
        "damage_type": "force",
        "input_key": "foe_slayer_total",
    }
    assert rider["eligibility"]["actor_state_target_id_keys"] == [
        "current_hunters_mark_target_id"
    ]

    actor = Combatant(
        id="ranger",
        entity_type="character",
        snapshot_json={
            "feature_runtime": ranger,
            "current_hunters_mark_target_id": "marked",
        },
    )
    resolved = PlayerRoomService._eligible_attack_riders(
        actor,
        {
            "name": "长弓",
            "description": "远程武器攻击",
            "damage": "1d8+敏捷 穿刺",
            "is_weapon_attack": True,
        },
        Combatant(id="marked", entity_type="monster"),
        special_inputs={
            "attack_rider_totals": {"foe_slayer:hunter_mark_damage": 8},
        },
        critical_hit=False,
        used_this_turn=set(),
    )
    assert resolved == [
        {
            "rider_id": "foe_slayer:hunter_mark_damage",
            "expression": "1d10",
            "reported_total": 8,
            "dice": True,
            "total": 8,
            "source": "屠灭众敌",
            "damage_type": "force",
            "frequency": "each_eligible_hit",
            "target_combatant_id": "marked",
                "post_hit_resolution_key": (
                    "post-hit:attack:ranger:marked:foe_slayer:hunter_mark_damage"
                ),
                "resource_spends": [],
            }
        ]


def test_stunning_strike_uses_generic_persisted_post_hit_contract() -> None:
    monk = _registry_at(_core_rules()["武僧"], 5)
    contract = next(
        item for item in monk["feature_contracts"] if item["name"] == "震慑拳"
    )
    assert contract["automation_status"] == "full"
    rider = next(
        item
        for item in monk["attack_riders"]
        if item["id"] == "stunning_strike:post_hit_save"
    )
    assert rider["kind"] == "post_hit_rider"
    assert rider["runtime_execution"] == {
        "status": "ready",
        "consumer": "post_hit_rider_follow_up",
    }
    actor = Combatant(
        id="monk",
        entity_type="character",
        snapshot_json={
            "ability_scores": {"wisdom": 16},
            "feature_runtime": monk,
        },
    )
    target = Combatant(id="enemy", entity_type="monster")
    pending = PlayerRoomService._eligible_attack_riders(
        actor,
        {
            "name": "徒手打击",
            "description": "近战攻击",
            "is_unarmed_attack": True,
        },
        target,
        special_inputs={},
        critical_hit=False,
        used_this_turn=set(),
        event_id="attack-stunning-1",
        turn_id="round-1-turn-0",
    )
    assert len(pending) == 1
    assert pending[0]["post_hit_status"] == "pending_activation"
    assert pending[0]["post_hit_bindings"] == {
        "feature_save_dc": 14,
        "wisdom_modifier": 3,
    }
    assert rider["frequency"] == "once_per_turn"
    assert rider["automation_status"] == "full"
    assert rider["requires_dm_adjudication"] is False


def test_mercy_harm_rider_binds_die_modifier_and_physician_overlay() -> None:
    harm = subclass_feature_runtime_definition(
        {
            "name": "夺命之手 Hand of Harm",
            "class_name": "武僧",
            "class_level": 3,
            "source_record_id": "mercy-harm",
        }
    )
    touch = subclass_feature_runtime_definition(
        {
            "name": "生死之触 Physician's Touch",
            "class_name": "武僧",
            "class_level": 6,
            "source_record_id": "mercy-touch",
        }
    )
    assert harm is not None and touch is not None
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "夺命之手 Hand of Harm",
                "class_name": "武僧",
                "class_level": 3,
                "runtime": {
                    "registry": harm,
                    "tracked_scaling_keys": ["martial_arts_die"],
                },
            },
            {
                "name": "生死之触 Physician's Touch",
                "class_name": "武僧",
                "class_level": 6,
                "runtime": {"registry": touch},
            },
        ],
        resources={"focus": {"current": 2, "max": 6}},
        scalings={"martial_arts_die": {"value": "d8"}},
        class_levels={"武僧": 6},
        total_level=6,
    )
    rider = next(
        item
        for item in registry["attack_riders"]
        if item["id"] == "hand_of_harm:bonus_damage"
    )
    assert rider["damage"]["expression"] == "@martial_arts_die+@wisdom_modifier"
    assert rider["on_hit"][0]["condition"] == "poisoned"
    contracts = {item["name"]: item for item in registry["feature_contracts"]}
    assert contracts["夺命之手 Hand of Harm"]["automation_status"] == "full"
    assert contracts["生死之触 Physician's Touch"]["automation_status"] == "partial"

def test_choice_bound_blessed_and_elemental_fury_features_remain_dm_only() -> None:
    rules = _core_rules()
    cleric = _registry(rules["牧师"])
    druid = _registry(rules["德鲁伊"])

    assert {"受祝击", "精通受祝击"} <= {
        item["name"] for item in cleric["dm_only"]
    }
    assert {"元素之怒", "元素狂怒"} <= {
        item["name"] for item in druid["dm_only"]
    }
    assert not any(
        item["feature_name"] in {"受祝击", "精通受祝击"}
        for item in cleric["attack_riders"]
    )
    assert not any(
        item["feature_name"] in {"元素之怒", "元素狂怒"}
        for item in druid["attack_riders"]
    )


def test_divine_fury_and_dreadful_strikes_use_persisted_rider_consumer() -> None:
    divine = subclass_feature_runtime_definition(
        {
            "name": "神性之怒 Divine Fury",
            "class_name": "野蛮人",
            "class_level": 3,
            "source_record_id": "zealot-divine-fury",
        }
    )
    dreadful = subclass_feature_runtime_definition(
        {
            "name": "哀惧灵袭 Dreadful Strikes",
            "class_name": "游侠",
            "class_level": 3,
            "source_record_id": "fey-dreadful-strikes",
        }
    )
    assert divine is not None and dreadful is not None
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "神性之怒 Divine Fury",
                "class_name": "野蛮人",
                "class_level": 3,
                "runtime": {"registry": divine},
            },
            {
                "name": "哀惧灵袭 Dreadful Strikes",
                "class_name": "游侠",
                "class_level": 3,
                "runtime": {"registry": dreadful},
            },
        ],
        class_levels={"野蛮人": 3, "游侠": 11},
        total_level=14,
    )
    riders = {item["id"]: item for item in registry["attack_riders"]}
    assert riders["divine_fury:bonus_damage"]["damage"]["damage_type_source"] == (
        "divine_fury_damage_type"
    )
    assert riders["dreadful_strikes:bonus_damage"]["damage"]["expression"] == (
        "@dreadful_strikes_die"
    )
    contracts = {item["name"]: item for item in registry["feature_contracts"]}
    assert contracts["神性之怒 Divine Fury"]["automation_status"] == "full"
    assert contracts["哀惧灵袭 Dreadful Strikes"]["automation_status"] == "full"


def test_2024_deterministic_feature_contracts_are_explicit_but_partial_when_events_are_missing(
) -> None:
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "鲁莽攻击",
                "kind": "class_feature",
                "class_name": "野蛮人",
                "class_level": 2,
                "runtime": {},
            },
            {
                "name": "危机感应",
                "kind": "class_feature",
                "class_name": "野蛮人",
                "class_level": 2,
                "runtime": {},
            },
            {
                "name": "坚韧狂暴",
                "kind": "class_feature",
                "class_name": "野蛮人",
                "class_level": 11,
                "runtime": {},
            },
            {
                "name": "灵巧动作",
                "kind": "class_feature",
                "class_name": "游荡者",
                "class_level": 2,
                "runtime": {},
            },
            {
                "name": "稳定瞄准",
                "kind": "class_feature",
                "class_name": "游荡者",
                "class_level": 3,
                "runtime": {},
            },
            {
                "name": "直觉闪避",
                "kind": "class_feature",
                "class_name": "游荡者",
                "class_level": 5,
                "runtime": {},
            },
            {
                "name": "可靠才能",
                "kind": "class_feature",
                "class_name": "游荡者",
                "class_level": 7,
                "runtime": {},
            },
            {
                "name": "圣武斩",
                "kind": "class_feature",
                "class_name": "圣武士",
                "class_level": 5,
                "runtime": {},
            },
            {
                "name": "不屈勇武",
                "kind": "class_feature",
                "class_name": "野蛮人",
                "class_level": 18,
                "runtime": {},
            },
            {
                "name": "不屈耐力",
                "kind": "species_feature",
                "class_name": "",
                "class_level": 0,
                "runtime": {},
            },
        ]
    )

    reckless = registry["actions"]["reckless_attack"]
    assert reckless["kind"] == "feature_action"
    assert reckless["effects"] == [
        {
            "kind": "activate_timed_condition",
            "condition": "reckless_attack",
            "expires": "turn_start",
        }
    ]
    assert reckless["automation_status"] == "full"
    assert reckless["requires_dm_adjudication"] is False
    assert reckless["runtime_execution"]["consumer"] == "combat_feature_action"

    cunning = registry["actions"]["cunning_action"]
    assert cunning["kind"] == "feature_action"
    assert cunning["allowed_actions"] == ["dash", "disengage", "hide"]
    assert cunning["effects"][0]["kind"] == "cunning_action_choice"

    steady_aim = registry["actions"]["steady_aim"]
    assert steady_aim["requirements"] == ["not_moved_this_turn"]
    assert steady_aim["movement_after_use"] == 0
    assert steady_aim["attack_advantage"]["frequency"] == "next_attack"

    uncanny_dodge = registry["actions"]["uncanny_dodge"]
    assert uncanny_dodge["action_cost"] == "reaction"
    assert uncanny_dodge["damage_multiplier"] == 0.5
    assert uncanny_dodge["effects"] == []

    danger_sense = next(
        item
        for item in registry["combat_start"]["modifiers"]
        if item["id"] == "danger_sense:dexterity_saving_throw_advantage"
    )
    assert danger_sense["operation"] == "advantage"
    assert danger_sense["ability"] == "dexterity"
    assert danger_sense["automation_status"] == "full"

    reliable_talent = next(
        item
        for item in registry["combat_start"]["modifiers"]
        if item["id"] == "reliable_talent:proficient_ability_check_floor"
    )
    assert reliable_talent["operation"] == "set_minimum_d20"
    assert reliable_talent["minimum"] == 10

    divine_smite = next(
        item
        for item in registry["attack_riders"]
        if item["id"] == "divine_smite:bonus_damage"
    )
    assert divine_smite["kind"] == "bonus_damage"
    assert divine_smite["damage_type"] == "radiant"
    assert divine_smite["requires_player_input"] == [
        {
            "key": "spell_slot_level",
            "kind": "select",
            "minimum": 1,
            "label": "消耗的法术位环阶",
        },
        {
            "key": "damage_total",
            "kind": "roll_total",
            "label": "圣武斩伤害骰总值",
        },
    ]
    assert divine_smite["automation_status"] == "full"

    relentless_rage = next(
        item
        for item in registry["combat_start"]["defenses"]
        if item["id"] == "relentless_rage:zero_hit_points_save"
    )
    assert relentless_rage["kind"] == "zero_hp_intervention"
    assert relentless_rage["trigger"] == "would_drop_to_zero_hit_points"
    assert relentless_rage["eligibility"] == {
        "entity_types": ["character"],
        "required_conditions": ["raging"],
        "level": {
            "class_names": ["野蛮人", "barbarian"],
            "minimum": 1,
            "bind_as": "barbarian_level",
        },
    }
    assert relentless_rage["saving_throw"] == {
        "ability": "constitution",
        "initial_dc": 10,
        "increase_after_success": 5,
    }
    assert relentless_rage["success"] == {
        "kind": "restore_hit_points",
        "amount": "2*barbarian_level",
    }
    assert relentless_rage["failure"] == {
        "kind": "continue_zero_hp_lifecycle"
    }
    assert relentless_rage["exceptions"] == ["outright_death"]
    assert relentless_rage["automation_status"] == "full"
    assert relentless_rage["requires_dm_adjudication"] is False

    relentless_endurance = registry["resources"]["relentless_endurance"]
    assert relentless_endurance["max"] == 1
    assert relentless_endurance["automation_status"] == "full"
    assert relentless_endurance["requires_dm_adjudication"] is False
    assert relentless_endurance["recovery_events"] == [
        {"rest": "long_rest", "operation": "set_to_max"}
    ]

    relentless_endurance_defense = next(
        item
        for item in registry["combat_start"]["defenses"]
        if item["id"] == "relentless_endurance:drop_to_one_hit_point"
    )
    assert relentless_endurance_defense["automation_status"] == "full"
    assert relentless_endurance_defense["requires_dm_adjudication"] is False

    indomitable_might = next(
        item
        for item in registry["combat_start"]["modifiers"]
        if item["id"] == "indomitable_might:strength_check_floor"
    )
    assert indomitable_might["operation"] == "set_minimum_total_from_ability"
    assert indomitable_might["ability"] == "strength"
    assert indomitable_might["automation_status"] == "full"
    assert indomitable_might["requires_dm_adjudication"] is False

    projections = {
        item["feature_id"]: item for item in feature_runtime_action_projections(registry)
    }
    assert "reckless_attack" in projections
    assert "steady_aim" in projections
    partial_contracts = {
        item["name"]: item for item in registry["feature_contracts"]
    }
    assert partial_contracts["鲁莽攻击"]["automation_status"] == "full"
    assert partial_contracts["稳定瞄准"]["automation_status"] == "full"


def test_legacy_zero_hp_save_snapshot_is_only_a_compatibility_adapter() -> None:
    adapted = adapt_legacy_zero_hp_intervention(
        {
            "id": "legacy:any-id",
            "kind": "zero_hit_points_save",
            "trigger": "self_would_drop_to_zero_hit_points_while_raging",
            "saving_throw": {
                "ability": "constitution",
                "initial_dc": 10,
                "increase_after_each_success": 5,
            },
            "hit_points_on_success": "2*barbarian_level",
        }
    )
    assert adapted["id"] == "legacy:any-id"
    assert adapted["kind"] == "zero_hp_intervention"
    assert adapted["trigger"] == "would_drop_to_zero_hit_points"
    assert adapted["saving_throw"] == {
        "ability": "constitution",
        "initial_dc": 10,
        "increase_after_success": 5,
    }
    assert adapted["failure"] == {"kind": "continue_zero_hp_lifecycle"}


def test_self_restoration_is_an_executable_turn_end_condition_choice() -> None:
    registry = feature_runtime_definition(
        feature_name="返本还元",
        class_name="武僧",
        class_level=10,
    )
    action = registry["actions"]["self_restoration"]
    assert action["activation_window"] == "turn_end"
    assert action["allowed_conditions"] == ["charmed", "frightened", "poisoned"]
    assert action["automation_status"] == "full"
    assert action["runtime_execution"]["effect_kinds"] == ["condition_removal"]
    projection = feature_runtime_action_projections(registry)
    assert any(item["feature_id"] == "self_restoration" for item in projection)
    contract = feature_runtime_contract(
        feature_name="返本还元",
        class_name="武僧",
        class_level=10,
        definition=registry,
    )
    assert contract["automation_status"] == "full"
    assert contract["requires_dm_adjudication"] is False
    assert contract["reasons"] == []


def test_attack_riders_require_explicit_dice_and_are_not_reused_in_same_turn() -> None:
    actor = Combatant(
        id="barbarian",
        entity_type="character",
        conditions=["狂暴"],
        snapshot_json={
            "feature_runtime": {
                "attack_riders": [
                    {
                        "id": "rage:bonus_damage",
                        "value": "+4",
                        "feature_name": "狂暴",
                        "applies_when": "raging_strength_attack",
                        "frequency": "each_eligible_hit",
                    },
                    {
                        "id": "sneak_attack:bonus_damage",
                        "value": "1d6",
                        "feature_name": "偷袭",
                        "applies_when": "sneak_attack_eligible",
                        "frequency": "once_per_turn",
                    },
                ]
            }
        },
    )
    target = Combatant(id="goblin", entity_type="monster")
    action = {
        "name": "巨斧",
        "description": "近战武器攻击",
        "damage": "1d12+力量 挥砍",
        "is_weapon_attack": True,
    }

    first = PlayerRoomService._eligible_attack_riders(
        actor,
        action,
        target,
        special_inputs={
            "attack_rider_eligibility": {"sneak_attack": True},
            "attack_rider_totals": {"sneak_attack:bonus_damage": 6},
        },
        critical_hit=False,
        used_this_turn=set(),
    )
    assert {item["rider_id"] for item in first} == {
        "rage:bonus_damage",
        "sneak_attack:bonus_damage",
    }
    assert sum(int(item["total"]) for item in first) == 10

    second = PlayerRoomService._eligible_attack_riders(
        actor,
        action,
        target,
        special_inputs={
            "attack_rider_eligibility": {"sneak_attack": True},
            "attack_rider_totals": {"sneak_attack:bonus_damage": 6},
        },
        critical_hit=False,
        used_this_turn={"sneak_attack:bonus_damage"},
    )
    assert [item["rider_id"] for item in second] == ["rage:bonus_damage"]

    try:
        PlayerRoomService._eligible_attack_riders(
            actor,
            action,
            target,
            special_inputs={"attack_rider_eligibility": {"sneak_attack": True}},
            critical_hit=False,
            used_this_turn=set(),
        )
    except ValueError as exc:
        assert "攻击附伤 sneak_attack:bonus_damage" in str(exc)
    else:
        raise AssertionError("a Sneak Attack dice rider must require a reported total")


def test_frenzy_rider_binds_rage_damage_and_reckless_first_hit() -> None:
    runtime = subclass_feature_runtime_definition(
        {"name": "狂怒 Frenzy", "class_name": "野蛮人", "class_level": 3}
    )
    assert runtime is not None
    rider = runtime["attack_riders"][0]
    assert rider["dice_count_source"] == "rage_damage"
    assert rider["applies_when"] == "raging_reckless_strength_weapon_attack"
    assert rider["damage_type"] == "weapon_damage_type"
    assert rider["frequency"] == "once_per_turn"
    assert rider["automation_status"] == "full"


def test_frenzy_rider_requires_raging_reckless_strength_attack_and_reports_d6_total() -> None:
    actor = Combatant(
        id="frenzy-barbarian",
        entity_type="character",
        conditions=["raging", "reckless_attack"],
        snapshot_json={
            "feature_runtime": {
                "attack_riders": [
                    {
                        "id": "rage:bonus_damage",
                        "value": "+3",
                        "applies_when": "raging_strength_attack",
                    },
                    {
                        "id": "frenzy:bonus_damage",
                        "value": "1d6",
                        "dice_count_source": "rage_damage",
                        "damage_type": "weapon_damage_type",
                        "applies_when": "raging_reckless_strength_weapon_attack",
                        "frequency": "once_per_turn",
                    },
                ]
            }
        },
    )
    target = Combatant(id="frenzy-target", entity_type="monster")
    riders = PlayerRoomService._eligible_attack_riders(
        actor,
        {
            "name": "巨斧",
            "description": "力量近战武器攻击",
            "is_weapon_attack": True,
            "attack_ability": "strength",
        },
        target,
        special_inputs={"attack_rider_totals": {"frenzy:bonus_damage": 9}},
        critical_hit=False,
        used_this_turn=set(),
    )
    frenzy = next(item for item in riders if item["rider_id"] == "frenzy:bonus_damage")
    assert frenzy["total"] == 9
    assert frenzy["damage_type"] == "weapon_damage_type"
