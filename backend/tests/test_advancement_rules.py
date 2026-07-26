from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.advancement import (
    average_hp_gain,
    merge_spell_slot_resources,
    multiclass_caster_level,
    multiclass_spell_slots,
    parse_progression_table,
    validate_multiclass_prerequisites,
)


def test_parse_complete_class_progression_table() -> None:
    rows = "\n".join(
        f"| {level} | +{2 + (level - 1) // 4} | "
        f"{'子职特性，属性值提升' if level == 4 else f'{level}级特性'} | {level} |"
        for level in range(1, 21)
    )
    markdown = f"""
| 等级 | 熟练加值(PB) | 职业特性 | 资源 |
| --- | --- | --- | --- |
{rows}
"""
    parsed = parse_progression_table(markdown)
    assert len(parsed) == 20
    assert parsed[3].features == ("子职特性", "属性值提升")
    assert parsed[19].proficiency_bonus == 6
    assert parsed[19].progression == {"资源": "20"}


def test_progression_rejects_incomplete_table() -> None:
    with pytest.raises(ValueError, match="complete 1-20"):
        parse_progression_table(
            "| 等级 | 职业特性 |\n|---|---|\n| 1 | 一级特性 |"
        )


def test_average_hp_gain_uses_fixed_value_and_minimum_one() -> None:
    assert average_hp_gain(10, 2) == 8
    assert average_hp_gain(6, -10) == 1
    with pytest.raises(ValueError):
        average_hp_gain(20, 0)


def test_multiclass_prerequisites_support_single_and_dual_abilities() -> None:
    assert validate_multiclass_prerequisites(
        "武僧", {"dexterity": 13, "wisdom": 12}
    ) == ("wisdom 13",)
    assert validate_multiclass_prerequisites(
        "战士", {"strength": 8, "dexterity": 14}
    ) == ()


def test_multiclass_spell_slots_use_2024_rounding_and_keep_pact_magic_separate() -> None:
    levels = {"法师": 3, "圣武士": 3, "游侠": 2, "魔契师": 5}
    assert multiclass_caster_level(levels) == 6
    assert multiclass_spell_slots(levels) == (4, 3, 3)


def test_third_casters_only_count_with_their_spellcasting_subclass() -> None:
    levels = {"战士": 6, "游荡者": 3}
    assert multiclass_caster_level(levels) == 0
    assert multiclass_caster_level(
        levels, {"战士": "奥法骑士", "游荡者": "诡术师"}
    ) == 3


def test_slot_resource_merge_preserves_spent_slots_and_other_resources() -> None:
    resources = {
        "spell_slots_1": {
            "label": "1环法术位",
            "current": 1,
            "max": 2,
            "recovery": "long_rest",
        },
        "pact_slots": {"current": 0, "max": 2, "recovery": "short_rest"},
    }
    merged = merge_spell_slot_resources(resources, {"法师": 2})
    assert merged["spell_slots_1"]["current"] == 2
    assert merged["spell_slots_1"]["max"] == 3
    assert merged["pact_slots"] == resources["pact_slots"]
