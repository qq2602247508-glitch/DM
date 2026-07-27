from __future__ import annotations

from dnd_dm_assistant.domain.advancement import ClassLevel, ClassProgression
from dnd_dm_assistant.domain.advancement_choices import (
    CORE_CLASSES_2024,
    advancement_choice_requirements,
    maximum_class_spell_level,
    progression_resource_updates,
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
        "recovery": "long_rest",
        "source": "战士 4级成长表",
    }
