from __future__ import annotations

from types import SimpleNamespace

import pytest

from dnd_dm_assistant.domain.advancement import ClassLevel, ClassProgression
from dnd_dm_assistant.domain.advancement_choices import (
    CORE_CLASSES_2024,
    _subclass_resource_update,
    advancement_choice_requirements,
    core_feature_grants,
    maximum_class_spell_level,
    progression_resource_updates,
    subclass_feature_runtime_definition,
    subclass_runtime_grants,
)
from dnd_dm_assistant.domain.noncombat_actions import skill_modifier
from dnd_dm_assistant.infrastructure.database.advancement_service import (
    AdvancementService,
    _fixed_subclass_feature_spell_additions,
    _selected_core_spell_additions,
    _selected_subclass_spell_additions,
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


def test_third_caster_subclass_spellcasting_uses_existing_spell_economy_contract() -> None:
    for class_name, feature_name in (
        ("战士", "施法 Spellcasting"),
        ("游荡者", "施法 Spellcasting"),
    ):
        runtime = subclass_feature_runtime_definition(
            {
                "name": feature_name,
                "class_name": class_name,
                "class_level": 3,
                "source_record_id": f"fixture:{class_name}:spellcasting",
            }
        )
        assert runtime is not None
        assert runtime["spellcasting"] == {
            "kind": "spellcasting_capability",
            "consumer": "spell_economy_service",
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "class_name": class_name,
            "class_level": 3,
            "source_record_id": f"fixture:{class_name}:spellcasting",
        }


def test_lore_bonus_proficiencies_are_persisted_into_skill_check_state() -> None:
    feature_id = "lore:3:bonus-proficiencies"
    runtime = subclass_runtime_grants(
        {
            "name": "逸闻学院",
            "feature_definitions": [
                {
                    "id": feature_id,
                    "name": "附赠熟练 Bonus Proficiencies",
                    "class_level": 3,
                    "source_record_id": "fixture:lore:bonus-proficiencies",
                    "description": "你获得三项由你选择的技能的熟练。",
                }
            ],
        },
        class_name="吟游诗人",
        target_class_level=3,
        selected_choices={feature_id: ["奥秘", "历史", "洞悉"]},
    )
    grant = runtime["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    assert runtime["choice_requirements"] == [
        {
            "feature_id": feature_id,
            "key": "subclass_skill_proficiency",
            "minimum": 3,
            "maximum": 3,
            "strict": True,
            "options_source": "supported_skill_registry",
            "requires_dm_selection": False,
            "reason": "逸闻学院附赠熟练要求选择三项技能熟练。",
        }
    ]
    skills = AdvancementService._apply_subclass_proficiency_choices(
        runtime["grants"],
        selected_choices={feature_id: ["奥秘", "历史", "洞悉"]},
        skills={},
    )
    assert all(skills[name]["proficient"] is True for name in ("奥秘", "历史", "洞悉"))
    character = SimpleNamespace(
        ability_scores={"intelligence": 14},
        skills=skills,
        level=3,
    )
    assert skill_modifier(character, "奥秘", "intelligence")[0] == 4
    with pytest.raises(ValueError, match="不能重复"):
        AdvancementService._apply_subclass_proficiency_choices(
            runtime["grants"],
            selected_choices={feature_id: ["奥秘", "奥秘", "洞悉"]},
            skills={},
        )


def test_student_of_war_typed_skill_and_tool_choices_are_persisted() -> None:
    feature_id = "battle-master:3:student-of-war"
    runtime = subclass_runtime_grants(
        {
            "name": "战斗大师",
            "feature_definitions": [
                {
                    "id": feature_id,
                    "name": "战争学者 Student of War",
                    "class_level": 3,
                    "source_record_id": "fixture:battle-master:student-of-war",
                    "description": (
                        "你选择一种工匠工具并获得其熟练。此外，你选择一项战士1级可用的技能，"
                        "并获得该技能的熟练。"
                    ),
                }
            ],
        },
        class_name="战士",
        target_class_level=3,
        selected_choices={feature_id: ["skill:洞悉", "tool:铁匠工具"]},
    )
    grant = runtime["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    skills, proficiencies = AdvancementService._apply_subclass_typed_proficiency_choices(
        runtime["grants"],
        selected_choices={feature_id: ["skill:洞悉", "tool:铁匠工具"]},
        skills={},
        proficiencies=[],
    )
    assert skills == {"洞悉": {"proficient": True}}
    assert proficiencies == ["铁匠工具"]
    with pytest.raises(ValueError, match="不允许的tool"):
        AdvancementService._apply_subclass_typed_proficiency_choices(
            runtime["grants"],
            selected_choices={feature_id: ["skill:洞悉", "tool:盗贼工具"]},
            skills={},
            proficiencies=[],
        )


def test_iron_mind_persists_replacement_save_and_narrows_runtime_modifier() -> None:
    feature_id = "gloom-stalker:7:iron-mind"
    definition = {
        "id": feature_id,
        "name": "钢铁意志 Iron Mind",
        "class_level": 7,
        "source_record_id": "fixture:gloom-stalker:iron-mind",
        "description": "你获得感知豁免熟练；如果已经拥有，则改选智力或魅力豁免熟练。",
    }
    runtime = subclass_runtime_grants(
        {"name": "幽域追猎者", "feature_definitions": [definition]},
        class_name="游侠",
        target_class_level=7,
        selected_choices={feature_id: ["save:intelligence"]},
    )
    grant = runtime["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    modifier = grant["runtime"]["registry"]["combat_start"]["modifiers"][0]
    assert modifier["abilities"] == ["intelligence"]
    _, proficiencies = AdvancementService._apply_subclass_typed_proficiency_choices(
        runtime["grants"],
        selected_choices={feature_id: ["save:intelligence"]},
        skills={},
        proficiencies=["感知豁免"],
    )
    assert proficiencies == ["感知豁免", "智力豁免"]
    with pytest.raises(ValueError, match="只能选择感知"):
        AdvancementService._apply_subclass_typed_proficiency_choices(
            runtime["grants"],
            selected_choices={feature_id: ["save:intelligence"]},
            skills={},
            proficiencies=[],
        )
    _, proficiencies = AdvancementService._apply_subclass_typed_proficiency_choices(
        runtime["grants"],
        selected_choices={feature_id: ["save:wisdom"]},
        skills={},
        proficiencies=[],
    )
    assert proficiencies == ["感知豁免"]


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


def test_full_of_stars_uses_starry_form_condition_contract() -> None:
    starry = subclass_feature_runtime_definition(
        {
            "name": "星耀形态 Starry Form",
            "class_name": "德鲁伊",
            "class_level": 3,
        }
    )
    assert starry is not None
    action = starry["actions"]["starry_form"]
    assert action["resource_key"] == "wild_shape"
    assert action["effects"] == [
        {
            "kind": "activate_duration_condition",
            "condition": "starry_form",
            "duration_unit": "minutes",
            "duration_value": 10,
        }
    ]

    full_of_stars = subclass_runtime_grants(
        {
            "name": "星辰结社",
            "feature_definitions": [
                {
                    "id": "full-of-stars",
                    "name": "灿若繁星 Full of Stars",
                    "class_level": 14,
                    "description": "星耀形态期间获得钝击、穿刺与挥砍伤害的抗性。",
                    "source_record_id": "stars-druid",
                }
            ],
        },
        class_name="德鲁伊",
        target_class_level=14,
    )
    grant = full_of_stars["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    defense = grant["runtime"]["registry"]["combat_start"]["defenses"][0]
    assert defense["required_conditions"] == ["starry_form"]
    assert defense["damage_types"] == ["bludgeoning", "piercing", "slashing"]


def test_guarded_mind_binds_psionic_dice_and_turn_start_condition_action() -> None:
    parent = {
        "name": "灵能力量 Psionic Power",
        "class_name": "战士",
        "class_level": 3,
        "description": "你拥有灵能骰，骰池在短休恢复一个，长休恢复全部。",
        "source_record_id": "psi-power",
    }
    child = {
        "id": "guarded-mind",
        "name": "意念守护 Guarded Mind",
        "class_level": 10,
        "description": (
            "你获得心灵伤害抗性。如果你在回合开始时处于魅惑或恐慌，"
            "可消耗一个灵能骰结束状态。"
        ),
        "source_record_id": "guarded-mind",
    }
    parent_key, parent_resource = _subclass_resource_update(
        parent,
        ability_scores=None,
        current_class_level=10,
    ) or (None, None)
    child["class_name"] = "战士"
    child_key, child_resource = _subclass_resource_update(
        child,
        ability_scores=None,
        current_class_level=10,
    ) or (None, None)
    assert parent_key == child_key == "psionic_dice:战士"
    assert parent_resource is not None and child_resource is not None
    assert parent_resource["max"] == child_resource["max"] == 8
    assert parent_resource["die_size"] == child_resource["die_size"] == 8

    result = subclass_runtime_grants(
        {
            "name": "灵能武士",
            "feature_definitions": [child],
        },
        class_name="战士",
        target_class_level=10,
        current_class_level=10,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    action = grant["runtime"]["registry"]["actions"]["guarded_mind_clear"]
    assert action["resource_key"] == "psionic_dice:战士"
    assert action["activation_window"] == "turn_start"
    assert action["condition_removal_options"] == ["charmed", "frightened"]


@pytest.mark.parametrize(
    ("class_name", "subclass_name"),
    [("战士", "灵能武士"), ("游荡者", "魂刃")],
)
def test_psionic_power_persists_typed_pool_contract_for_each_owner_class(
    class_name: str,
    subclass_name: str,
) -> None:
    result = subclass_runtime_grants(
        {
            "name": subclass_name,
            "feature_definitions": [
                {
                    "id": f"{class_name}-psionic-power",
                    "name": "灵能力量 Psionic Power",
                    "class_level": 3,
                    "description": "你拥有灵能骰，骰池在短休恢复一个，长休恢复全部。",
                    "source_record_id": f"{class_name}-psionic-power",
                }
            ],
        },
        class_name=class_name,
        target_class_level=3,
        current_class_level=3,
    )
    grant = result["grants"][0]
    runtime = grant["runtime"]
    assert runtime["automation_status"] == "full"
    assert runtime["tracked_resource_keys"] == [f"psionic_dice:{class_name}"]
    resource = runtime["registry"]["resources"][f"psionic_dice:{class_name}"]
    assert resource["max"] == 4
    assert resource["die_size"] == 6
    assert resource["recovery_events"] == [
        {"rest": "short_rest", "operation": "restore", "amount": 1},
        {"rest": "long_rest", "operation": "set_to_max"},
    ]


def test_war_gods_blessing_binds_wisdom_pool_and_attack_roll_reaction() -> None:
    result = subclass_runtime_grants(
        {
            "name": "战争领域",
            "feature_definitions": [
                {
                    "id": "war-gods-blessing",
                    "name": "战神祝福 War God's Blessing",
                    "class_level": 6,
                    "description": "你可以使用此特性，次数等于你的感知调整值，长休恢复全部。",
                    "source_record_id": "war-gods-blessing",
                }
            ],
        },
        class_name="牧师",
        target_class_level=6,
        ability_scores={"wisdom": 18},
        current_class_level=6,
    )
    grant = result["grants"][0]
    runtime = grant["runtime"]
    assert runtime["automation_status"] == "full"
    assert runtime["tracked_resource_keys"] == ["war_gods_blessing"]
    resource = runtime["registry"]["resources"]["war_gods_blessing"]
    assert resource["max"] == 4
    action = runtime["registry"]["actions"]["war_gods_blessing"]
    assert action["resource"]["key"] == "war_gods_blessing"
    assert action["eligibility"]["resource"]["key"] == "war_gods_blessing"
    assert action["eligibility"]["test_kinds"] == ["armor_class"]
    assert action["action_cost"] == "reaction"


def test_elemental_affinity_binds_selected_damage_type_and_validates_choice_options() -> None:
    result = subclass_runtime_grants(
        {
            "name": "龙族术法",
            "feature_definitions": [
                {
                    "id": "elemental-affinity",
                    "name": "元素亲和 Elemental Affinity",
                    "class_level": 6,
                    "description": "选择酸、寒冷、火焰、闪电或毒素伤害类型并获得抗性。",
                    "source_record_id": "elemental-affinity",
                }
            ],
        },
        class_name="术士",
        target_class_level=6,
        selected_choices={"elemental-affinity": ["damage_type:fire"]},
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    assert result["choice_requirements"][0]["options"] == [
        "damage_type:acid",
        "damage_type:cold",
        "damage_type:fire",
        "damage_type:lightning",
        "damage_type:poison",
    ]
    defense = grant["runtime"]["registry"]["combat_start"]["defenses"][0]
    assert defense["damage_types"] == ["fire"]
    rider = grant["runtime"]["registry"]["attack_riders"][0]
    assert rider["selected_damage_type"] == "fire"


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
                        "你获得一个有着4枚d12的治疗池。以一个附赠动作，你可以消耗骰子恢复生命值。"
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

    warrior_action = warrior["grants"][0]["runtime"]["registry"]["actions"]["warrior_of_the_gods"]
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


def test_choice_bound_subclass_spell_list_uses_typed_selected_spell_grant() -> None:
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
    assert result["grants"][0]["runtime"]["automation_status"] == "full"
    registry = result["grants"][0]["runtime"]["registry"]
    assert registry["advancement"]["kind"] == "selected_spell_grant"
    assert result["choice_requirements"][0]["minimum"] == 2
    assert result["prepared_spell_features"] == []


def test_selected_spell_grant_validates_source_school_and_cumulative_school_count() -> None:
    result = subclass_runtime_grants(
        {
            "name": "塑能师",
            "feature_definitions": [
                {
                    "id": "evocation-savant",
                    "name": "塑能学者",
                    "class_level": 3,
                    "description": "从法师法术列表中选择两道不高于二环的塑能学派法术。",
                    "source_record_id": "evocation-savant",
                }
            ],
        },
        class_name="法师",
        target_class_level=3,
        current_class_level=5,
        selected_choices={"evocation-savant": ["燃烧之手", "火球术", "闪电束"]},
    )
    assert result["choice_requirements"][0]["minimum"] == 3
    additions = _selected_subclass_spell_additions(
        result["grants"],
        selected_choices={"evocation-savant": ["燃烧之手", "火球术", "闪电束"]},
        spell_catalog=(
            {
                "name": "燃烧之手",
                "source_record_id": "burning-hands",
                "level": 1,
                "school": "塑能",
                "classes": ["法师"],
            },
            {
                "name": "火球术",
                "source_record_id": "fireball",
                "level": 3,
                "school": "塑能",
                "classes": ["法师"],
            },
            {
                "name": "闪电束",
                "source_record_id": "lightning-bolt",
                "level": 3,
                "school": "塑能",
                "classes": ["法师"],
            },
        ),
        owner_class="法师",
        owner_level=5,
    )
    assert [spell["name"] for spell in additions] == ["燃烧之手", "火球术", "闪电束"]
    assert all(spell["spellbook"] is True for spell in additions)


def test_mystic_arcanum_choice_becomes_free_cast_spell_access() -> None:
    additions = _selected_core_spell_additions(
        {"mystic_arcanum_6": ["秘法眼"]},
        spell_catalog=(
            {
                "name": "秘法眼",
                "source_record_id": "arcane-eye",
                "level": 6,
                "classes": ["魔契师"],
            },
        ),
        owner_class="魔契师",
    )
    assert additions == [
        {
            "name": "秘法眼",
            "source_record_id": "arcane-eye",
            "level": 6,
            "classes": ["魔契师"],
            "spell_level": 6,
            "class_name": "魔契师",
            "prepared": True,
            "always_prepared": True,
            "resource_key": "mystic_arcanum_6",
            "resource_cost": 1,
            "source_feature_id": "mystic_arcanum_6",
            "source_feature_name": "mystic_arcanum_6",
            "granted_spell_access": True,
            "does_not_count_toward_level_learning": True,
        }
    ]


def test_fixed_subclass_spell_grant_persists_its_casting_ability() -> None:
    grants = subclass_runtime_grants(
        {
            "name": "四象武者",
            "feature_definitions": [
                {
                    "id": "manipulate-elements",
                    "name": "掌控元素 Manipulate Elements",
                    "class_level": 3,
                    "description": "你习得戏法四象法门，其施法属性为感知。",
                }
            ],
        },
        class_name="武僧",
        target_class_level=3,
    )["grants"]
    additions = _fixed_subclass_feature_spell_additions(
        grants,
        spell_catalog=(
            {
                "name": "四象法门",
                "source_record_id": "elementalism",
                "level": 0,
                "classes": ["法师"],
            },
        ),
        owner_class="武僧",
    )
    assert additions[0]["class_name"] == "武僧"
    assert additions[0]["spellcasting_ability"] == "wisdom"
    assert additions[0]["prepared"] is True


def test_ritual_only_subclass_spell_grants_are_typed_and_full() -> None:
    result = subclass_runtime_grants(
        {
            "name": "兽心道途",
            "feature_definitions": [
                {
                    "id": "animal-speaker",
                    "name": "动物语者",
                    "class_level": 3,
                    "description": "你可以施展法术野兽感官与动物交谈，仅限仪式施展。",
                    "source_record_id": "animal-speaker",
                }
            ],
        },
        class_name="野蛮人",
        target_class_level=3,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    assert grant["runtime"]["registry"]["advancement"]["ritual_only"] is True
    additions = _fixed_subclass_feature_spell_additions(
        result["grants"],
        spell_catalog=(
            {
                "name": "野兽感官",
                "source_record_id": "beast-sense",
                "level": 2,
                "classes": ["德鲁伊"],
            },
            {
                "name": "动物交谈",
                "source_record_id": "speak-with-animals",
                "level": 1,
                "classes": ["吟游诗人"],
            },
        ),
        owner_class="野蛮人",
    )
    assert {item["name"] for item in additions} == {"野兽感官", "动物交谈"}
    assert all(item["ritual_only"] is True for item in additions)


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
    defenses = grant["runtime"]["registry"]["combat_start"]["defenses"]
    assert {item["condition"] for item in defenses} == {"charmed", "frightened"}
    assert all(item["required_conditions"] == ["raging"] for item in defenses)
    assert grant["runtime"]["registry"]["triggers"][0]["action_id"] == "rage"


def test_natures_ward_declares_long_rest_land_choice_and_all_defenses() -> None:
    result = subclass_runtime_grants(
        {
            "name": "大地结社",
            "feature_definitions": [
                {
                    "id": "natures-ward",
                    "name": "自然守御 Nature's Ward",
                    "class_level": 10,
                    "description": "你免疫中毒状态，并具有所选地形相关伤害类型的抗性。",
                    "source_record_id": "natures-ward",
                }
            ],
        },
        class_name="德鲁伊",
        target_class_level=10,
    )
    grant = result["grants"][0]
    assert grant["runtime"]["automation_status"] == "full"
    registry = grant["runtime"]["registry"]
    action = registry["actions"]["terrain_choice"]
    assert action["kind"] == "rest_choice"
    assert action["trigger"] == "long_rest"
    assert action["choice_key"] == "circle_land_terrain"
    defenses = registry["combat_start"]["defenses"]
    assert {item["kind"] for item in defenses} == {"condition_immunity", "damage_resistance"}


def test_combat_inspiration_declares_both_persisted_die_spending_modes() -> None:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "战斗激励 Combat Inspiration",
            "class_name": "吟游诗人",
            "class_level": 3,
            "description": "命中后可将诗人激励骰用于防御或进攻。",
        }
    )
    assert runtime is not None
    action = runtime["actions"]["combat_inspiration"]
    assert action["runtime_execution"]["consumer"] == "player_attack_resolver"
    assert action["modes"] == ["defense", "offense"]
    assert action["automation_status"] == "full"
