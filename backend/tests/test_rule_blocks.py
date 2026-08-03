from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from dnd_dm_assistant.application.rule_block_compiler import (
    compile_rule_blocks,
    compile_rule_blocks_dict,
)
from dnd_dm_assistant.domain.rule_blocks import (
    ChoiceBlock,
    ChoiceOption,
    CreationBlock,
    DamageBlock,
    DefenseBlock,
    DispelBlock,
    ExplorationEffectBlock,
    HealBlock,
    ModifierBlock,
    NarrativeBlock,
    ObjectStateBlock,
    RulePlan,
    TargetBlock,
    TeleportBlock,
    TransformationBlock,
    build_execution_plan,
    validate_rule_plan,
)


def test_compiles_destination_sensitive_special_spell_blocks_without_guessing() -> None:
    plan = compile_rule_blocks(
        {
            "name": "传送与变形测试",
            "spell_level": 5,
            "range": "30尺",
            "description": "选择一个目标。",
            "teleport": {
                "destination_kind": "known_location",
                "max_distance_ft": 1_000,
                "can_take_creatures": True,
            },
            "transformation": {
                "mode": "polymorph",
                "form_ref": "dm_chosen_form",
            },
            "creation": {
                "creation_kind": "object",
                "template_ref": "dm_chosen_template",
                "count": 2,
            },
            "dispel": {
                "mode": "dispel",
                "effect_types": ["spell"],
                "check_required": True,
                "check_dc_source": "法术等级",
            },
        },
        source_kind="spell",
    )

    assert isinstance(
        next(block for block in plan.blocks if block.kind == "teleport"),
        TeleportBlock,
    )
    assert isinstance(
        next(block for block in plan.blocks if block.kind == "transformation"),
        TransformationBlock,
    )
    assert isinstance(
        next(block for block in plan.blocks if block.kind == "creation"),
        CreationBlock,
    )
    assert isinstance(
        next(block for block in plan.blocks if block.kind == "dispel"),
        DispelBlock,
    )


def test_compiles_area_save_damage_resource_and_duration() -> None:
    plan = compile_rule_blocks(
        {
            "name": "火球术",
            "source_record_id": "spell-fireball",
            "spell_level": 3,
            "range": "150尺",
            "description": "以射程内一点为中心，形成20尺半径球形区域。",
            "damage_expression": "8d6",
            "damage_type": "火焰",
            "save_ability": "敏捷",
            "save_dc": 17,
            "half_damage_on_save": True,
            "duration": "立即",
            "resource_key": "spell_slots_3",
            "resource_cost": 1,
            "resolution_kind": "damage",
        }
    )

    assert plan.schema_version == "1.0"
    assert [block.kind for block in plan.blocks] == [
        "target",
        "resource",
        "duration",
        "save",
        "damage",
    ]
    target = plan.blocks[0]
    damage = plan.blocks[-1]
    assert isinstance(target, TargetBlock)
    assert (target.mode, target.shape, target.range_ft, target.size_ft) == (
        "area",
        "sphere",
        150,
        20,
    )
    assert isinstance(damage, DamageBlock)
    assert damage.expression == "8d6"
    assert damage.damage_type == "fire"
    assert damage.shared_roll is True
    assert damage.applies_on == "save_failure"


@pytest.mark.parametrize(
    ("description", "shape", "size_ft"),
    [
        ("目标点周围半径20尺球状区域内的每个生物进行豁免。", "sphere", 20),
        ("一束100\n尺长，5尺宽的线状闪电从你的位置爆发。", "line", 100),
    ],
)
def test_compiles_area_shapes_from_canonical_chinese_word_order(
    description: str,
    shape: str,
    size_ft: int,
) -> None:
    plan = compile_rule_blocks(
        {
            "name": "区域法术",
            "range": "150尺",
            "description": description,
            "damage_expression": "8d6",
            "damage_type": "火焰",
            "save_ability": "敏捷",
            "resolution_kind": "damage",
        }
    )

    target = plan.blocks[0]
    assert isinstance(target, TargetBlock)
    assert (target.mode, target.shape, target.size_ft) == ("area", shape, size_ft)


def test_non_damage_spell_never_invents_damage_from_prose() -> None:
    plan = compile_rule_blocks(
        {
            "name": "侦测魔法",
            "spell_level": 1,
            "range": "自身",
            "description": "你感知30尺内的魔法。后续规则示例可能写有3d6，但这不是伤害。",
            "resource_key": "spell_slots_1",
            "resource_cost": 1,
            "resolution_kind": "narrative",
        }
    )

    assert not any(block.kind == "damage" for block in plan.blocks)
    narrative = next(block for block in plan.blocks if block.kind == "narrative")
    assert isinstance(narrative, NarrativeBlock)
    assert narrative.requires_dm_adjudication is True


def test_invalid_damage_is_rejected_and_downgraded_to_narrative() -> None:
    plan = compile_rule_blocks(
        {
            "name": "不完整攻击",
            "damage": "造成很多火焰伤害",
            "damage_type": "fire",
            "resolution_kind": "damage",
            "description": "规则来源没有给出伤害骰。",
        }
    )

    assert not any(block.kind == "damage" for block in plan.blocks)
    assert plan.warnings == ("伤害字段无法安全编译，已转为DM文字裁定",)
    assert any(block.kind == "narrative" for block in plan.blocks)
    assert plan.automation_confidence == "manual"
    assert plan.automation_ready is False
    assert plan.unresolved_reasons == (
        "伤害字段无法安全编译，已转为DM文字裁定",
        "规则包含需要DM裁定的文字效果",
    )


def test_compiles_weapon_modifier_and_healing_without_eval() -> None:
    attack = compile_rule_blocks(
        {
            "name": "长剑",
            "range": "5尺",
            "damage": "1d8+力量 挥砍",
            "damage_type": "挥砍",
        }
    )
    healing = compile_rule_blocks(
        {
            "name": "第二风息",
            "range": "自身",
            "damage": "治疗1d10+1",
            "resolution_kind": "heal",
        }
    )

    attack_damage = next(block for block in attack.blocks if block.kind == "damage")
    heal = next(block for block in healing.blocks if block.kind == "heal")
    assert isinstance(attack_damage, DamageBlock)
    assert attack_damage.expression == "1d8+@strength"
    assert heal.expression == "1d10+1"


def test_compiles_temporary_hit_points_as_a_distinct_heal_block() -> None:
    plan = compile_rule_blocks(
        {
            "name": "虚假生命",
            "range": "自身",
            "healing": "1d4+4",
            "temporary_hp": True,
            "resolution_kind": "heal",
        }
    )

    heal = next(block for block in plan.blocks if block.kind == "heal")
    assert isinstance(heal, HealBlock)
    assert heal.temporary_hp is True


def test_compiles_typed_damage_defenses_as_first_class_blocks() -> None:
    plan = compile_rule_blocks(
        {
            "name": "毒虫罗斯魔",
            "source_record_id": "monster-roth-moth",
            "damage_resistances": ["bludgeoning", "cold", "fire"],
            "damage_immunities": ["acid", "poison"],
            "damage_vulnerabilities": ["radiant"],
        },
        source_kind="monster",
    )

    defenses = [block for block in plan.blocks if block.kind == "defense"]
    assert len(defenses) == 3
    assert all(isinstance(block, DefenseBlock) for block in defenses)
    assert plan.automation_ready is True


def test_named_combat_and_exploration_effects_are_typed_not_plain_text() -> None:
    haste = compile_rule_blocks_dict(
        {
            "name": "加速术",
            "spell_level": 3,
            "range": "30尺",
            "duration": "1分钟",
            "description": "目标速度增加20尺，敏捷豁免具有优势，并获得额外动作。",
            "resolution_kind": "control",
        },
        source_kind="spell",
    )
    haste_blocks = haste["blocks"]
    assert sum(block["kind"] == "modifier" for block in haste_blocks) == 3
    assert sum(isinstance(block, ModifierBlock) for block in validate_rule_plan(haste).blocks) == 3
    assert haste["automation_ready"] is True

    knock = compile_rule_blocks_dict(
        {
            "name": "敲击术",
            "spell_level": 2,
            "range": "60尺",
            "description": "打开一个被锁住的门或物件。",
            "resolution_kind": "control",
        },
        source_kind="spell",
    )
    assert any(isinstance(block, ObjectStateBlock) for block in validate_rule_plan(knock).blocks)

    detect = compile_rule_blocks_dict(
        {
            "name": "侦测魔法",
            "spell_level": 1,
            "range": "自身",
            "description": "感知30尺内的魔法，并辨认其所属学派。",
            "resolution_kind": "control",
        },
        source_kind="spell",
    )
    assert any(
        isinstance(block, ExplorationEffectBlock)
        and block.operation == "detect_magic"
        for block in validate_rule_plan(detect).blocks
    )


def test_compiles_skill_check_without_inventing_a_dc() -> None:
    plan = compile_rule_blocks(
        {
            "name": "调查",
            "description": "寻找线索、机关或隐藏结构。",
            "ability": "intelligence",
            "skill": "调查",
            "resolution_kind": "skill_check",
        },
        source_kind="feature",
    )

    roll = next(block for block in plan.blocks if block.kind == "roll")
    assert roll.roll_type == "ability_check"
    assert roll.skill == "调查"
    assert roll.ability == "intelligence"
    assert roll.dc is None
    assert roll.dc_source == "dm_chosen_dc"
    assert plan.automation_ready is False


def test_compiles_explicit_monster_attack_without_defaulting_missing_range() -> None:
    plan = compile_rule_blocks(
        {
            "name": "多重攻击",
            "description": "该生物进行两次攻击。",
            "resolution_kind": "control",
        },
        source_kind="monster_action",
    )
    target = next(block for block in plan.blocks if block.kind == "target")
    assert target.range_ft is None
    assert not any(block.kind == "damage" for block in plan.blocks)


def test_structured_condition_move_summon_and_control_blocks_compile() -> None:
    plan = compile_rule_blocks(
        {
            "name": "复合规则",
            "range": "30尺",
            "description": "选择一种效果。",
            "duration": "2轮",
            "conditions": ["倒地"],
            "movement": {"distance_ft": 10, "type": "forced", "direction": "push"},
            "summon": {"creature_ref": "wolf", "count": 2, "controller": "caster"},
            "repeat": {"count": 2, "timing": "turn_end", "effect": "重复检定"},
            "choices": [
                {"label": "推开", "description": "目标被推开。"},
                {"label": "击倒", "description": "目标倒地。"},
            ],
            "trigger": {
                "event": "目标进入区域",
                "timing": "when",
                "effect": "应用区域效果",
                "once": True,
            },
        },
        source_kind="feature",
    )

    kinds = {block.kind for block in plan.blocks}
    assert {"condition", "move", "summon", "repeat", "choice", "trigger"} <= kinds
    execution = build_execution_plan(plan)
    assert len(execution.steps) == len(plan.blocks)
    assert any(
        any(guard.startswith("repeat:") for guard in step.guards)
        for step in execution.steps
    )
    assert any(
        guard.startswith("choice:")
        for step in execution.steps
        for guard in step.guards
    )
    assert any(
        guard.startswith("trigger:")
        for step in execution.steps
        for guard in step.guards
    )


def test_execution_plan_is_deterministic_and_contains_no_roll_results() -> None:
    plan = compile_rule_blocks(
        {
            "name": "闪电束",
            "spell_level": 3,
            "range": "自身",
            "description": "一道100尺长的线状闪电。",
            "damage_expression": "8d6",
            "damage_type": "闪电",
            "save_ability": "敏捷",
            "half_damage_on_save": True,
            "resolution_kind": "damage",
        }
    )

    first = build_execution_plan(plan)
    second = build_execution_plan(plan)
    assert first == second
    assert first.rule_plan_fingerprint == second.rule_plan_fingerprint
    serialized = first.model_dump_json()
    assert "roll_result" not in serialized
    assert "random" not in serialized


def test_execution_plan_resolves_verified_upcast_dice_and_slot_resource() -> None:
    plan = compile_rule_blocks(
        {
            "name": "火球术",
            "spell_level": 3,
            "range": "150尺",
            "damage_expression": "8d6",
            "damage_type": "火焰",
            "upcast_damage_dice": 1,
            "resource_key": "spell_slots_3",
            "resource_cost": 1,
            "resolution_kind": "damage",
        },
        source_kind="spell",
    )

    source_damage = next(block for block in plan.blocks if block.kind == "damage")
    assert isinstance(source_damage, DamageBlock)
    assert source_damage.expression == "8d6"
    assert source_damage.spell_slot_scaling is not None
    assert source_damage.spell_slot_scaling.base_spell_level == 3
    assert source_damage.spell_slot_scaling.dice_per_level == 1

    execution = build_execution_plan(plan, slot_level=5)
    resolved_damage = next(step.block for step in execution.steps if step.block.kind == "damage")
    resolved_resource = next(
        step.block for step in execution.steps if step.block.kind == "resource"
    )
    assert execution.selected_slot_level == 5
    assert resolved_damage.expression == "10d6"
    assert resolved_resource.resource_key == "spell_slots_5"
    assert source_damage.expression == "8d6"


def test_execution_plan_resolves_healing_modifiers_and_rejects_invalid_slots() -> None:
    plan = compile_rule_blocks(
        {
            "name": "治愈真言",
            "spell_level": 1,
            "range": "60尺",
            "healing": "2d4+3",
            "upcast_healing_dice": 2,
            "resource_key": "spell_slots_1",
            "resource_cost": 1,
            "resolution_kind": "heal",
        },
        source_kind="spell",
    )

    execution = build_execution_plan(plan, slot_level=3)
    resolved_heal = next(step.block for step in execution.steps if step.block.kind == "heal")
    assert resolved_heal.expression == "6d4+3"
    with pytest.raises(ValueError, match="integer between 1 and 9"):
        build_execution_plan(plan, slot_level=0)


def test_upcast_metadata_without_a_base_spell_level_stays_unresolved() -> None:
    plan = compile_rule_blocks(
        {
            "name": "缺少环阶的升环伤害",
            "damage_expression": "2d6",
            "damage_type": "火焰",
            "upcast_damage_dice": 1,
            "resolution_kind": "damage",
        },
        source_kind="spell",
    )

    damage = next(block for block in plan.blocks if block.kind == "damage")
    assert damage.spell_slot_scaling is None
    assert plan.automation_ready is False
    assert "升环增量缺少明确的基础法术环阶，未绑定效果积木" in plan.unresolved_reasons


def test_strict_validation_rejects_extra_fields_and_bad_dice() -> None:
    valid = compile_rule_blocks(
        {
            "name": "火焰箭",
            "damage": "1d10 火焰",
            "damage_type": "fire",
        }
    ).model_dump(mode="json")
    with_extra = copy.deepcopy(valid)
    with_extra["blocks"][0]["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        validate_rule_plan(with_extra)

    bad_damage = copy.deepcopy(valid)
    damage = next(block for block in bad_damage["blocks"] if block["kind"] == "damage")
    damage["expression"] = "__import__('os').system('bad')"
    with pytest.raises(ValidationError, match="deterministic dice notation"):
        validate_rule_plan(bad_damage)


def test_plan_rejects_unknown_references_cycles_and_unreachable_blocks() -> None:
    target = TargetBlock(id="target", mode="single")
    narrative = NarrativeBlock(id="effect", text="裁定效果")
    choice = ChoiceBlock(
        id="choice",
        prompt="选择",
        options=(
            ChoiceOption(key="one", label="一", block_ids=("effect",)),
            ChoiceOption(key="two", label="二", block_ids=("missing",)),
        ),
    )
    with pytest.raises(ValidationError, match="unknown block"):
        RulePlan(
            source_kind="feature",
            source_name="非法引用",
            blocks=(target, narrative, choice),
            root_block_ids=("target", "choice"),
            automation_confidence="manual",
            automation_ready=False,
        )

    with pytest.raises(ValidationError, match="unreachable"):
        RulePlan(
            source_kind="feature",
            source_name="孤立积木",
            blocks=(target, narrative),
            root_block_ids=("target",),
            automation_confidence="manual",
            automation_ready=False,
        )


def test_schema_is_versioned_and_strict_about_version() -> None:
    data = compile_rule_blocks(
        {"name": "协助", "description": "给予盟友下一次检定优势。"}
    ).model_dump(mode="json")
    data["schema_version"] = "2.0"
    with pytest.raises(ValidationError, match="Input should be '1.0'"):
        validate_rule_plan(data)


def test_json_round_trip_and_api_dictionary_preserve_automation_metadata() -> None:
    source = {
        "name": "火球术",
        "source_record_id": "spell-fireball",
        "spell_level": 3,
        "range": "150尺",
        "area_shape": "sphere",
        "area_size_ft": 20,
        "damage_expression": "8d6",
        "damage_type": "fire",
        "save_ability": "敏捷",
        "resolution_kind": "damage",
    }
    value = compile_rule_blocks_dict(source)
    restored = validate_rule_plan(value)

    assert restored == compile_rule_blocks(source)
    assert value["schema_version"] == "1.0"
    assert value["source_ref"] == "spell-fireball"
    assert value["automation_confidence"] == "exact"
    assert value["automation_ready"] is True
    assert value["unresolved_reasons"] == []
