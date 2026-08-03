from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.character_creation import (
    validate_ability_generation,
    validate_character_state,
    validate_languages,
)


def test_standard_array_is_checked_before_background_origin_increases() -> None:
    scores = validate_ability_generation(
        "standard_array",
        {
            "strength": 8,
            "dexterity": 14,
            "constitution": 13,
            "intelligence": 17,
            "wisdom": 13,
            "charisma": 10,
        },
        origin_ability_increases={"intelligence": 2, "wisdom": 1},
        allowed_origin_abilities=("constitution", "intelligence", "wisdom"),
    )

    assert scores["intelligence"] == 17
    assert scores["wisdom"] == 13


def test_point_buy_and_rolled_scores_are_both_auditable() -> None:
    point_buy = validate_ability_generation(
        "point_buy",
        {
            "strength": 15,
            "dexterity": 14,
            "constitution": 13,
            "intelligence": 14,
            "wisdom": 11,
            "charisma": 8,
        },
        origin_ability_increases={"intelligence": 2, "wisdom": 1},
        allowed_origin_abilities=("constitution", "intelligence", "wisdom"),
    )
    rolled = validate_ability_generation(
        "rolled_4d6_drop_lowest",
        {
            "strength": 18,
            "dexterity": 15,
            "constitution": 14,
            "intelligence": 14,
            "wisdom": 12,
            "charisma": 9,
        },
        origin_ability_increases={"intelligence": 2, "wisdom": 1},
        allowed_origin_abilities=("constitution", "intelligence", "wisdom"),
        ability_rolls={
            "strength": [6, 6, 6, 1],
            "dexterity": [6, 5, 4, 1],
            "constitution": [5, 5, 4, 1],
            "intelligence": [4, 4, 4, 1],
            "wisdom": [4, 4, 3, 1],
            "charisma": [3, 3, 3, 1],
        },
    )

    assert point_buy["intelligence"] == 14
    assert rolled["strength"] == 18


def test_rejects_forged_rolls_and_invalid_language_choices() -> None:
    with pytest.raises(ValueError, match="不一致"):
        validate_ability_generation(
            "rolled_4d6_drop_lowest",
            {
                "strength": 18,
                "dexterity": 15,
                "constitution": 14,
                "intelligence": 15,
                "wisdom": 12,
                "charisma": 9,
            },
            origin_ability_increases={"intelligence": 2, "wisdom": 1},
            allowed_origin_abilities=("constitution", "intelligence", "wisdom"),
            ability_rolls={
                "strength": [6, 6, 6, 1],
                "dexterity": [6, 5, 4, 1],
                "constitution": [5, 5, 4, 1],
                "intelligence": [4, 4, 4, 1],
                "wisdom": [4, 4, 3, 1],
                "charisma": [3, 3, 3, 1],
            },
        )

    assert validate_languages(["精灵语", "龙语"]) == ("通用语", "精灵语", "龙语")
    with pytest.raises(ValueError, match="通用语"):
        validate_languages(["通用语", "精灵语"])


def test_shared_character_state_normalizes_classes_and_rejects_invalid_totals() -> None:
    normalized = validate_character_state(
        {
            "level": 5,
            "class_name": "法师",
            "ability_scores": {"intelligence": 16},
            "hp": 24,
            "max_hp": 24,
            "resources": {
                "spell_slots_3": {"current": 1, "maximum": 2},
            },
        }
    )
    assert normalized["class_levels"] == {"法师": 5}

    with pytest.raises(ValueError, match="职业等级之和"):
        validate_character_state(
            {
                "level": 5,
                "class_name": "法师",
                "class_levels": {"法师": 4},
            }
        )
