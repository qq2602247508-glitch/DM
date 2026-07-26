from dnd_dm_assistant.application.character_ocr import character_draft_from_text


def test_character_sheet_text_becomes_reviewable_draft() -> None:
    draft = character_draft_from_text(
        "角色姓名：阿莱娜\n种族：精灵\n职业：法师\n背景：学者\n"
        "等级：3\n护甲等级：13\n最大生命值：18\n力量 8\n敏捷 14\n智力 17"
    )
    assert draft["name"] == "阿莱娜"
    assert draft["race"] == "精灵"
    assert draft["class_name"] == "法师"
    assert draft["level"] == 3
    assert draft["max_hp"] == 18
    assert draft["ability_scores"] == {
        "strength": 8,
        "dexterity": 14,
        "intelligence": 17,
    }
