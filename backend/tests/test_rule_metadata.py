from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.rule_block_compiler import compile_rule_blocks_dict
from dnd_dm_assistant.application.rule_metadata import spell_rule_fields
from dnd_dm_assistant.domain.spell_rules import enrich_spell_action

SPELL_DATA_ROOT = (
    Path(__file__).resolve().parents[2] / "data/generated-content/dnd5e_chm/json/spells"
)


def _database_spell(name: str, edition: str = "2024") -> dict[str, object]:
    for path in SPELL_DATA_ROOT.glob("*.json"):
        record = json.loads(path.read_text())
        if (
            record.get("name") == name
            and record.get("edition") == edition
            and "法术详述" in str(record.get("heading_path"))
        ):
            return record
    raise AssertionError(f"local spell record not found: {name} ({edition})")


def test_derives_healing_area_conditions_movement_and_upcast_from_explicit_text() -> None:
    fields = spell_rule_fields(
        {
            "spell": {
                "level": 1,
                "range": "60尺",
                "damage_expression": "2d4",
            },
            "content_plain_text": (
                "施法距离：60尺。目标恢复生命值，恢复量等于2d4+3。"
                "最多三个生物。升环施法。使用的法术位每比一环高一环，"
                "治疗量增加2d4。"
            ),
        }
    )

    assert fields["healing"] == "2d4+3"
    assert "damage_expression" not in fields
    assert fields["max_targets"] == 3
    assert fields["upcast_healing_dice"] == 2


def test_rejects_heterogeneous_or_multi_effect_upcast_scaling() -> None:
    different_damage_term = spell_rule_fields(
        {
            "name": "冰刃",
            "content_plain_text": (
                "命中时造成1d10穿刺伤害。升环施法。"
                "使用的法术位每比一环高一环，另一段寒冷伤害增加1d6。"
            ),
        }
    )
    multiple_damage_terms = spell_rule_fields(
        {
            "name": "双段冰墙",
            "content_plain_text": (
                "冰墙产生时造成10d6寒冷伤害。升环施法。"
                "使用的法术位每比六环高一环，初始伤害提高2d6，"
                "穿越墙体的伤害增加1d6。"
            ),
        }
    )

    assert different_damage_term["damage_expression"] == "1d10"
    assert "upcast_damage_dice" not in different_damage_term
    assert multiple_damage_terms["damage_expression"] == "10d6"
    assert "upcast_damage_dice" not in multiple_damage_terms


def test_marks_temporary_hit_points_without_treating_them_as_normal_healing() -> None:
    fields = spell_rule_fields(
        {
            "name": "虚假生命",
            "content_plain_text": "你获得1d4+4点临时生命值。",
        }
    )

    assert fields["healing"] == "1d4+4"
    assert fields["temporary_hp"] is True


def test_normalizes_touch_and_mile_ranges_without_inventing_special_ranges() -> None:
    touch = compile_rule_blocks_dict(
        {"name": "触碰效果", "range": "触碰", "description": "触碰一个生物。"}
    )
    mile = compile_rule_blocks_dict(
        {"name": "远程效果", "range": "1里", "description": "选择一个目标。"}
    )
    special = compile_rule_blocks_dict(
        {"name": "特殊效果", "range": "特殊", "description": "范围由规则原文决定。"}
    )

    assert next(block for block in touch["blocks"] if block["kind"] == "target")["range_ft"] == 5
    assert next(block for block in mile["blocks"] if block["kind"] == "target")["range_ft"] == 5280
    assert (
        next(block for block in special["blocks"] if block["kind"] == "target")["range_ft"]
        is None
    )


def test_derives_thunderwave_geometry_and_forced_movement_without_guessing() -> None:
    fields = spell_rule_fields(
        {
            "spell": {"range": "自身（15尺立方）", "damage_expression": "2d8"},
            "content_plain_text": (
                "以你为源点15尺立方区域内的每个生物进行体质豁免，"
                "失败受到2d8雷鸣伤害并被推离10尺。"
            ),
        }
    )

    assert fields["area_shape"] == "cube"
    assert fields["area_size_ft"] == 15
    assert fields["movement"] == {
        "distance_ft": 10,
        "type": "forced",
        "direction": "away",
    }


def test_extracts_special_spell_choices_as_typed_fields() -> None:
    fields = spell_rule_fields(
        {
            "name": "特殊规则法术",
            "content_plain_text": (
                "你传送到一个已知地点，距离不超过100尺。"
                "你可以将目标变成另一种形态。"
                "你创造一个物件，并可驱散一个法术。"
            ),
        }
    )

    assert fields["teleport"]["destination_kind"] == "known_location"
    assert fields["teleport"]["max_distance_ft"] == 100
    assert fields["transformation"]["requires_form_choice"] is True
    assert fields["creation"]["creation_kind"] == "item"
    assert fields["dispel"]["mode"] == "dispel"


def test_does_not_turn_unrelated_numbers_into_target_count() -> None:
    fields = spell_rule_fields(
        {
            "spell": {},
            "content_plain_text": "你可以至多2500金币购买材料。",
        }
    )
    assert "max_targets" not in fields


def test_extracts_explicit_recurring_timing_as_runtime_automation() -> None:
    fields = spell_rule_fields(
        {
            "name": "持续灼烧",
            "spell": {"damage_expression": "1d6", "damage_type": "火焰"},
            "content_plain_text": "目标在每个回合结束时受到1d6点火焰伤害。",
        }
    )

    assert fields["repeat"] == {
        "timing": "turn_end",
        "count_expression": "duration",
        "source": "explicit_timing",
    }
    plan = compile_rule_blocks_dict(
        {
            "name": "持续灼烧",
            **fields,
            "spell_level": 2,
            "resolution_kind": "damage",
        },
        source_kind="spell",
    )
    assert any(block["kind"] == "repeat" for block in plan["blocks"])
    assert plan["automation_ready"] is True
    assert not any("重复效果" in reason for reason in plan["unresolved_reasons"])


def test_maps_dark_damage_alias_to_a_damage_block() -> None:
    fields = spell_rule_fields(
        {
            "spell": {"damage_expression": "14d6", "save": "体质豁免"},
            "content_plain_text": "体质豁免失败受到14d6点暗蚀伤害，成功则伤害减半。",
        }
    )
    plan = compile_rule_blocks_dict(
        {
            "name": "重伤术",
            **fields,
            "spell_level": 6,
            "resolution_kind": "damage",
            "save_ability": fields["save"],
            "half_damage_on_save": True,
        },
        source_kind="spell",
    )
    assert plan["automation_ready"] is True
    damage = next(block for block in plan["blocks"] if block["kind"] == "damage")
    assert damage["damage_type"] == "necrotic"


def test_marks_mage_hand_as_a_caster_controlled_summoned_effect() -> None:
    fields = spell_rule_fields(
        {
            "name": "法师之手",
            "spell": {"range": "30尺"},
            "content_plain_text": "你创造一只幽灵手，持续1分钟。",
        }
    )
    assert fields["summon"] == {
        "creature_ref": "法师之手（幽灵手）",
        "count": 1,
        "controller": "caster",
        "enters_combat": False,
    }


def test_spellcasting_dc_is_only_attached_to_spells_with_an_explicit_save() -> None:
    mage_hand = enrich_spell_action(
        {"name": "法师之手"},
        spellcasting={"save_dc": 13},
    )
    thunderwave = enrich_spell_action(
        {"name": "雷鸣波"},
        spellcasting={"save_dc": 13},
    )

    assert "save_dc" not in mage_hand
    assert thunderwave["save_ability"] == "constitution"
    assert thunderwave["save_dc"] == 13


def test_local_spell_records_keep_summons_and_initiative_modes_separate() -> None:
    mage_hand = spell_rule_fields(_database_spell("法师之手"))
    unseen_servant = spell_rule_fields(_database_spell("隐形仆役"))
    familiar = spell_rule_fields(_database_spell("寻获魔宠"))
    elemental = spell_rule_fields(_database_spell("元素召唤术"))
    beast = spell_rule_fields(_database_spell("野兽召唤术"))

    assert mage_hand["summon"]["enters_combat"] is False
    assert unseen_servant["summon"]["enters_combat"] is False
    assert familiar["summon"]["initiative_mode"] == "independent"
    assert elemental["summon"]["initiative_mode"] == "shared_with_source"
    assert beast["summon"]["initiative_mode"] == "shared_with_source"
    assert elemental["damage_expression"] is None


def test_local_spell_boundaries_do_not_leak_following_spell_or_stat_block_rules() -> None:
    chain_lightning = spell_rule_fields(_database_spell("连锁闪电"))
    flame_blade = spell_rule_fields(_database_spell("火焰刀"))
    thunderwave = spell_rule_fields(_database_spell("雷鸣波"))
    web = spell_rule_fields(_database_spell("蛛网术"))
    conjure_fey = spell_rule_fields(_database_spell("咒唤妖精"))
    minor_elementals = spell_rule_fields(_database_spell("咒唤微元素群"))
    celestial_light = spell_rule_fields(_database_spell("咒唤圣光"))

    assert chain_lightning.get("summon") is None
    assert chain_lightning["damage_expression"] == "10d8"
    assert flame_blade["damage_expression"] == "3d6"
    assert thunderwave["area_shape"] == "cube"
    assert thunderwave["area_size_ft"] == 15
    assert thunderwave["movement"]["distance_ft"] == 10
    assert web["area_shape"] == "cube"
    assert web["area_size_ft"] == 20
    assert "束缚" in web["conditions"]
    assert conjure_fey.get("summon") is None
    assert conjure_fey["damage_expression"] == "3d12"
    assert "恐慌" in conjure_fey["conditions"]
    assert minor_elementals["area_shape"] == "sphere"
    assert minor_elementals["area_size_ft"] == 15
    assert celestial_light["area_shape"] == "cylinder"
    assert celestial_light["area_size_ft"] == 10


def test_local_upcast_scaling_keeps_multi_effect_damage_manual() -> None:
    fireball = spell_rule_fields(_database_spell("火球术"))
    ice_blade = spell_rule_fields(_database_spell("冰刃"))
    wall_of_ice = spell_rule_fields(_database_spell("冰墙术"))
    bigbys_hand = spell_rule_fields(_database_spell("毕格比之手"))

    assert fireball["upcast_damage_dice"] == 1
    assert "upcast_damage_dice" not in ice_blade
    assert "upcast_damage_dice" not in wall_of_ice
    assert "upcast_damage_dice" not in bigbys_hand
