from __future__ import annotations

from dnd_dm_assistant.domain.advancement import ClassLevel, ClassProgression
from dnd_dm_assistant.domain.advancement_choices import (
    CORE_CLASSES_2024,
    advancement_choice_requirements,
    core_feature_grants,
    maximum_class_spell_level,
    progression_resource_updates,
    subclass_runtime_grants,
)


def _rule(name: str) -> ClassProgression:
    levels = []
    for level in range(1, 21):
        features: tuple[str, ...] = ()
        if level == 3:
            features = (f"{name}子职",)
        elif level == 4:
            features = ("属性值提升",)
        progression: dict[str, str] = {}
        if name in {"吟游诗人", "牧师", "德鲁伊", "术士", "法师"}:
            progression = {
                "戏法": str(2 + int(level >= 4)),
                "准备法术": str(3 + level),
            }
        if name == "战士":
            progression = {"回气": str(2 + int(level >= 4)), "武器精通": "3"}
        levels.append(ClassLevel(level, 2 + (level - 1) // 4, features, progression))
    return ClassProgression(
        name=name,
        source_record_id=f"{name}-2024",
        source_path=f"玩家手册2024/角色职业/{name}/{name}.htm",
        hit_die=10,
        levels=tuple(levels),
        subclasses=({"name": f"{name}测试子职"},),
    )


def test_all_twelve_core_classes_have_a_twenty_level_choice_baseline() -> None:
    assert len(CORE_CLASSES_2024) == 12
    for class_name in CORE_CLASSES_2024:
        rule = _rule(class_name)
        for level in range(1, 21):
            requirements = advancement_choice_requirements(rule, level)
            assert isinstance(requirements, tuple)


def test_progression_compiles_subclass_asi_and_spell_totals() -> None:
    wizard = _rule("法师")
    subclass = advancement_choice_requirements(wizard, 3)
    assert next(item for item in subclass if item.key == "subclass").strict is True

    asi = advancement_choice_requirements(wizard, 4)
    assert next(item for item in asi if item.key == "asi_or_feat").minimum == 1
    assert next(item for item in asi if item.key == "cantrips").target_total == 3
    assert next(item for item in asi if item.key == "prepared_spells").target_total == 7
    spellbook = next(item for item in asi if item.key == "spellbook_additions")
    assert (spellbook.minimum, spellbook.maximum) == (2, 2)


def test_spell_level_uses_class_level_not_shared_multiclass_slots() -> None:
    assert maximum_class_spell_level("法师", 5) == 3
    assert maximum_class_spell_level("圣武士", 5) == 2
    assert maximum_class_spell_level("魔契师", 17) == 5
    assert maximum_class_spell_level("战士", 20) == 0


def test_resource_progression_is_compiled_from_the_class_table() -> None:
    fighter = _rule("战士")
    assert progression_resource_updates(fighter, 4)["second_wind"] == {
        "label": "回气",
        "max": 3,
        "recovery": "short_rest",
        "source": "战士 4级成长表",
        "recovery_events": [
            {"rest": "short_rest", "operation": "restore", "amount": 1},
            {"rest": "long_rest", "operation": "set_to_max"},
        ],
    }


def test_runtime_grants_keep_unstructured_effects_in_dm_adjudication() -> None:
    monk = _rule("武僧")
    monk_level_two = monk.levels[1]
    monk = ClassProgression(
        name=monk.name,
        source_record_id=monk.source_record_id,
        source_path=monk.source_path,
        hit_die=monk.hit_die,
        levels=(
            monk.levels[0],
            ClassLevel(
                monk_level_two.level,
                monk_level_two.proficiency_bonus,
                ("功力", "偏转攻击"),
                {"功力": "2"},
            ),
            *monk.levels[2:],
        ),
        subclasses=monk.subclasses,
    )

    updates = progression_resource_updates(monk, 2)
    assert updates["focus"] == {
        "label": "功力点",
        "max": 2,
        "recovery": "short_rest",
        "source": "武僧 2级成长表",
        "recovery_events": [
            {"rest": "short_rest", "operation": "set_to_max"},
            {"rest": "long_rest", "operation": "set_to_max"},
        ],
    }
    grants = core_feature_grants(monk, 2)
    tracked = next(item for item in grants if item["name"] == "功力")
    structured = next(item for item in grants if item["name"] == "偏转攻击")
    assert tracked["runtime"]["automation_status"] == "full"
    assert tracked["runtime"]["tracked_resource_keys"] == ["focus"]
    assert structured["runtime"]["automation_status"] == "full"
    assert structured["runtime"]["requires_dm_adjudication"] is False


def test_subclass_typed_defense_grant_uses_generic_resistance_consumer() -> None:
    result = subclass_runtime_grants(
        {
            "name": "战争领域",
            "feature_definitions": [
                {
                    "id": "war-avatar",
                    "name": "战争化身 Avatar of",
                    "class_level": 17,
                    "description": "你获得对钝击、穿刺、挥砍伤害的抗性。",
                    "source_record_id": "war-domain",
                }
            ],
        },
        class_name="牧师",
        target_class_level=17,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    assert grant["runtime"]["requires_dm_adjudication"] is False
    assert grant["runtime"]["registry"]["combat_start"]["defenses"][0]["kind"] == (
        "damage_resistance"
    )


def test_subclass_aura_immunity_uses_ranged_passive_consumer() -> None:
    result = subclass_runtime_grants(
        {
            "name": "奉献之誓",
            "feature_definitions": [
                {
                    "id": "devotion-aura",
                    "name": "奉献灵光 Aura of Devotion",
                    "class_level": 7,
                    "description": "你与位于灵光内的盟友具有魅惑免疫。",
                    "source_record_id": "devotion-aura",
                }
            ],
        },
        class_name="圣武士",
        target_class_level=7,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    defense = grant["runtime"]["registry"]["combat_start"]["defenses"][0]
    assert defense["ranged_passive"]["effect_kind"] == "condition_immunity"


def test_subclass_aura_resistance_uses_ranged_damage_consumer() -> None:
    result = subclass_runtime_grants(
        {
            "name": "古贤之誓",
            "feature_definitions": [
                {
                    "id": "warding-aura",
                    "name": "守御灵光 Aura of Warding",
                    "class_level": 7,
                    "description": "你和灵光内的盟友获得对暗蚀、心灵以及光耀伤害的抗性。",
                    "source_record_id": "warding-aura",
                }
            ],
        },
        class_name="圣武士",
        target_class_level=7,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    defense = grant["runtime"]["registry"]["combat_start"]["defenses"][0]
    assert defense["ranged_passive"]["effect_kind"] == "damage_resistance"


def test_fixed_subclass_tool_proficiency_uses_typed_sheet_consumer() -> None:
    result = subclass_runtime_grants(
        {
            "name": "刺客",
            "feature_definitions": [
                {
                    "id": "assassin-tools",
                    "name": "刺客工具 Assassin's Tools",
                    "class_level": 3,
                    "description": "你获得一套易容工具和一套毒药工具，并获得这些工具的熟练。",
                    "source_record_id": "assassin-tools",
                }
            ],
        },
        class_name="游荡者",
        target_class_level=3,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    assert [item["name"] for item in grant["runtime"]["registry"]["proficiencies"]] == [
        "易容工具",
        "毒药工具",
    ]


def test_fixed_mercy_proficiencies_reuse_the_same_typed_consumer() -> None:
    result = subclass_runtime_grants(
        {
            "name": "命流武者",
            "feature_definitions": [
                {
                    "id": "mercy-implements",
                    "name": "操命本事 Implements of Mercy",
                    "class_level": 3,
                    "description": "你获得洞悉和医药的熟练，并且获得草药工具的熟练。",
                    "source_record_id": "mercy-implements",
                }
            ],
        },
        class_name="武僧",
        target_class_level=3,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    assert [item["name"] for item in grant["runtime"]["registry"]["proficiencies"]] == [
        "洞悉",
        "医药",
        "草药工具",
    ]


def test_superior_critical_reuses_generic_critical_threshold_consumer() -> None:
    result = subclass_runtime_grants(
        {
            "name": "勇士",
            "feature_definitions": [
                {
                    "id": "superior-critical",
                    "name": "高效重击 Superior Critical",
                    "class_level": 15,
                    "description": "你的攻击检定在掷出18-20时造成重击。",
                    "source_record_id": "superior-critical",
                }
            ],
        },
        class_name="战士",
        target_class_level=15,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    modifier = grant["runtime"]["registry"]["combat_start"]["modifiers"][0]
    assert modifier["stat"] == "attack_critical_threshold"
    assert modifier["value"] == 18


def test_subclass_extra_attack_reuses_attack_action_count_consumer() -> None:
    result = subclass_runtime_grants(
        {
            "name": "勇气学院",
            "feature_definitions": [
                {
                    "id": "college-extra-attack",
                    "name": "额外攻击 Extra Attack",
                    "class_level": 6,
                    "description": "你可以在执行攻击动作时攻击两次，而非一次。",
                    "source_record_id": "college-extra-attack",
                }
            ],
        },
        class_name="吟游诗人",
        target_class_level=6,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    registry = grant["runtime"]["registry"]
    assert registry["combat_start"]["attack_action_count"] == 2


def test_open_hand_wholeness_uses_generic_healing_and_lifecycle_blocks() -> None:
    result = subclass_runtime_grants(
        {
            "name": "散打武者",
            "feature_definitions": [
                {
                    "id": "open-hand-wholeness",
                    "name": "混元体 Wholeness of Body",
                    "class_level": 6,
                    "description": (
                        "你可以使用这个特性的次数相当于你的感知调整值（至少一次），"
                        "在你完成一次长休时，你重获全部已消耗使用次数。"
                    ),
                    "source_record_id": "open-hand",
                }
            ],
        },
        class_name="武僧",
        target_class_level=6,
        ability_scores={"wisdom": 16},
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    action = grant["runtime"]["registry"]["actions"]["wholeness_of_body"]
    resource_key = next(iter(result["resources"]))
    assert action["resource_key"] == resource_key
    assert action["resource_lifecycle"]["key"] == resource_key
    assert result["resources"][resource_key]["max"] == 3


def test_healing_dice_pool_configs_are_reusable_and_level_bound() -> None:
    warrior = subclass_runtime_grants(
        {
            "name": "狂热者道途",
            "feature_definitions": [
                {
                    "id": "warrior-of-gods",
                    "name": "神之勇者",
                    "class_level": 3,
                    "description": (
                        "你获得一个有着4枚d12的治疗池。以一个附赠动作，"
                        "你可以消耗骰子恢复生命值。"
                    ),
                    "source_record_id": "warrior-of-gods",
                }
            ],
        },
        class_name="野蛮人",
        target_class_level=3,
    )
    light = subclass_runtime_grants(
        {
            "name": "天界宗主",
            "feature_definitions": [
                {
                    "id": "healing-light",
                    "name": "治疗之光",
                    "class_level": 3,
                    "description": (
                        "你获得一个有着1+你的魔契师等级枚d6骰的骰池。"
                        "以一个附赠动作，你可以消耗骰子治疗。"
                    ),
                    "source_record_id": "healing-light",
                }
            ],
        },
        class_name="魔契师",
        target_class_level=3,
        current_class_level=10,
    )

    warrior_action = warrior["grants"][0]["runtime"]["registry"]["actions"][
        "warrior_of_the_gods"
    ]
    light_action = light["grants"][0]["runtime"]["registry"]["actions"]["healing_light"]
    assert warrior["grants"][0]["runtime"]["automation_status"] == "full"
    assert warrior_action["resource_cost_mode"] == "dice_count"
    assert warrior_action["healing_dice"] == {"die_size": 12, "max_dice": 4}
    resource = next(iter(light["resources"].values()))
    assert resource["max"] == 11
    assert resource["die_size"] == 6
    assert light_action["target_policy"]["range_ft"] == 60
    assert light_action["healing_dice"]["max_dice_formula"] == "max(1, charisma_modifier)"


def test_spell_resistance_config_covers_magical_saves_and_damage() -> None:
    result = subclass_runtime_grants(
        {
            "name": "防护师",
            "feature_definitions": [
                {
                    "id": "spell-resistance",
                    "name": "法术抗性 Spell Resistance",
                    "class_level": 14,
                    "description": "抵抗法术时豁免具有优势且对法术伤害具有抗性。",
                    "source_record_id": "spell-resistance",
                }
            ],
        },
        class_name="法师",
        target_class_level=14,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    defenses = grant["runtime"]["registry"]["combat_start"]["defenses"]
    assert {item["kind"] for item in defenses} == {
        "saving_throw_advantage",
        "damage_resistance",
    }


def test_fixed_subclass_spell_list_is_a_generic_always_prepared_block() -> None:
    result = subclass_runtime_grants(
        {
            "name": "荣耀之誓",
            "feature_definitions": [
                {
                    "id": "glory-spells",
                    "name": "荣耀之誓法术 Oath of Glory Spells",
                    "class_level": 3,
                    "description": (
                        "你誓言具有的魔法使你始终准备着表中对应的法术。"
                        "| 圣武士等级 | 准备法术 |\n"
                        "| 3 | 光导箭Guiding Bolt，英雄气概Heroism |"
                    ),
                    "source_record_id": "glory-spells",
                }
            ],
        },
        class_name="圣武士",
        target_class_level=3,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    assert grant["runtime"]["registry"]["prepared_spell_list"]["kind"] == (
        "always_prepared_spell_list"
    )
    assert result["prepared_spell_features"][0]["feature_id"] == "glory-spells"


def test_choice_bound_subclass_spell_list_does_not_become_always_prepared() -> None:
    result = subclass_runtime_grants(
        {
            "name": "逸闻学院",
            "feature_definitions": [
                {
                    "id": "magical-discoveries",
                    "name": "魔法探秘 Magical Discoveries",
                    "class_level": 6,
                    "description": "你习得两道自选法术，并始终准备着你选择的这些法术。",
                    "source_record_id": "magical-discoveries",
                }
            ],
        },
        class_name="吟游诗人",
        target_class_level=6,
    )
    assert result["grants"][0]["runtime"]["automation_status"] == "dm_only"
    assert result["prepared_spell_features"] == []


def test_mindless_rage_declares_conditional_immunity_and_clear_trigger() -> None:
    result = subclass_runtime_grants(
        {
            "name": "狂战士道途",
            "feature_definitions": [
                {
                    "id": "mindless-rage",
                    "name": "无我狂暴 Mindless Rage",
                    "class_level": 6,
                    "description": "狂暴激活期间，你具有魅惑与恐慌状态的免疫。",
                    "source_record_id": "mindless-rage",
                }
            ],
        },
        class_name="野蛮人",
        target_class_level=6,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    assert grant["runtime"]["registry"]["triggers"][0]["action_id"] == "rage"
