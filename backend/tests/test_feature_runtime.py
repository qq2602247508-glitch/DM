from __future__ import annotations

import json
from pathlib import Path
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
)
from dnd_dm_assistant.domain.feature_runtime import (
    FEATURE_RUNTIME_SCHEMA_VERSION,
    apply_initiative_start_resource_recovery,
    compile_feature_runtime_registry,
    feature_runtime_action_projections,
    feature_runtime_definition,
    resolve_feature_speed,
    resolve_unarmored_defense_ac,
)
from dnd_dm_assistant.domain.rests import RestResource, resolve_long_rest, resolve_short_rest
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
    tactical_mind = next(item for item in fighter["dm_only"] if item["name"] == "战术思维")
    assert tactical_mind["automation_status"] == "dm_only"
    assert tactical_mind["requires_dm_adjudication"] is True


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
    assert lay_on_hands["actions"]["lay_on_hands"]["resource_cost_mode"] == "amount"
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
    assert inspiration["automation_status"] == "partial"
    assert inspiration["runtime_execution"] == {
        "status": "ready",
        "consumer": "combat_feature_action",
        "effect_kinds": ["grant_roll_die"],
        "remaining_dm_boundaries": [
            "target_range_visibility_and_audibility",
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
            "snapshot_json": {"feature_runtime": registry},
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
    assert result["actor"]["snapshot_json"]["feature_dice"] == {
        "bardic_inspiration_die": {
            "source": "吟游诗人激励",
            "value": "D6",
            "target_combatant_id": ally["id"],
            "available": True,
        }
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
        and event.get("requires_dm_adjudication") is True
        for event in perfect_focus["recovery_events"]
    )

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

    sorcerous_restoration = progression_resource_updates(rules["术士"], 5)
    assert sorcerous_restoration["sorcery_restoration"]["max"] == 1
    assert sorcerous_restoration["sorcery_restoration"]["requires_dm_adjudication"] is True

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
    assert ranger_resources["tireless"]["requires_dm_adjudication"] is True
    assert ranger_resources["nature_veil"]["requires_dm_adjudication"] is False
    assert ranger_resources["nature_veil"]["automation_status"] == "full"


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
    assert saving_aura["requires_dm_adjudication"] is True
    courage = compile_feature_runtime_registry(
        core_feature_grants(rules["圣武士"], 10),
        resources=progression_resource_updates(rules["圣武士"], 10),
    )
    assert courage["combat_start"]["defenses"][0]["condition"] == "frightened"

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


    martial_arts = _registry(rules["武僧"])
    martial_die = next(
        item
        for item in martial_arts["combat_start"]["modifiers"]
        if item["id"] == "martial_arts:damage_die"
    )
    assert martial_die["scaling_key"] == "martial_arts_die"
    assert martial_die["value"] == "1d12"
    assert martial_die["requires_dm_adjudication"] is True

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
        "consumer": "combat_feature_action",
        "effect_kinds": ["temporary_healing"],
    }
    assert registry["actions"]["tireless"]["automation_status"] == "partial"
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
    assert countercharm["automation_status"] == "partial"
    assert countercharm["effects"][0]["kind"] == "requires_dm_choice"

    deflect = monk["actions"]["deflect_attacks"]
    assert deflect["name"] == "拨挡能量"
    assert deflect["action_cost"] == "reaction"
    assert deflect["eligible_damage_types"] == "all"
    assert deflect["redirect_resource_key"] == "focus"
    assert deflect["automation_status"] == "partial"

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
        "remaining_dm_boundaries": ["hide_requires_explicit_outcome"],
    }
    assert action["automation_status"] == "partial"
    assert action["requires_dm_adjudication"] is True

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
        "status": "implemented",
        "consumer": "combat_feature_action",
    }
    assert uncanny_dodge["automation_status"] == "implemented"
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
        "status": "partial",
        "consumer": "combat_feature_action",
        "consumer_steps": [
            "focus_consumption",
            "target_selection_within_range",
            "dexterity_save",
            "redirect_damage",
        ],
    }
    assert "deflect_attacks" not in {
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
    assert stroke_action["automation_status"] == "partial"
    assert stroke_action["requires_dm_adjudication"] is True

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
    assert precise["automation_status"] == "partial"

    rider = next(
        item
        for item in ranger["attack_riders"]
        if item["id"] == "foe_slayer:hunter_mark_damage"
    )
    assert rider == {
        **rider,
        "value": "1d10",
        "damage_type": "force",
        "frequency": "each_eligible_hit",
        "automation_status": "partial",
        "requires_dm_adjudication": True,
    }

    actor = Combatant(
        id="ranger",
        entity_type="character",
        snapshot_json={"feature_runtime": ranger},
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
            "attack_rider_eligibility": {"foe_slayer:hunter_mark_damage": True},
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
        }
    ]


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
    assert uncanny_dodge["effects"][0]["kind"] == "requires_dm_choice"

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
    assert relentless_rage["saving_throw"] == {
        "ability": "constitution",
        "initial_dc": 10,
        "increase_after_each_success": 5,
        "reset": "short_or_long_rest",
    }
    assert relentless_rage["hit_points_on_success"] == "2*barbarian_level"
    assert relentless_rage["automation_status"] == "partial"

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
