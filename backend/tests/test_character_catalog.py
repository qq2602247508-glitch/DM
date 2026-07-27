from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.character_catalog import CharacterCatalog


def test_spell_options_expose_structured_combat_and_narrative_metadata(
    tmp_path: Path,
) -> None:
    spells = tmp_path / "spells"
    spells.mkdir()
    records = [
        {
            "stable_id": "fireball",
            "name": "火球术",
            "edition": "2024",
            "officiality": "official",
            "source_relative_path": "玩家手册2024/法术详述/3环.htm",
            "content_plain_text": (
                "施法距离内一点爆炸。半径20尺内每个生物进行敏捷豁免，"
                "失败受到8d6火焰伤害，成功则只受一半伤害。"
            ),
            "spell": {
                "level": 3,
                "classes": ["术士", "法师"],
                "school": "塑能",
                "casting_time": "动作",
                "range": "150尺",
                "components": "V、S、M",
                "duration": "立即",
                "concentration": False,
                "ritual": False,
                "damage_expression": "8d6",
                "damage_type": "火焰",
                "save": "敏捷豁免",
            },
        },
        {
            "stable_id": "mage-hand",
            "name": "法师之手",
            "edition": "2024",
            "officiality": "official",
            "source_relative_path": "玩家手册2024/法术详述/0环.htm",
            "content_plain_text": "创造一只幽灵手搬动物品。",
            "spell": {
                "level": None,
                "classes": ["法师"],
                "casting_time": "动作",
                "range": "30尺",
                "damage_expression": None,
            },
        },
        {
            "stable_id": "detect-magic",
            "name": "侦测魔法",
            "edition": "2024",
            "officiality": "official",
            "source_relative_path": "玩家手册2024/法术详述/1环.htm",
            "content_markdown": (
                "#### 侦测魔法｜Detect Magic\n\n你感知附近的魔法。\n"
                "#### 后续法术\n\n目标受到3d6心灵伤害并进行感知豁免。"
            ),
            "spell": {
                "level": 1,
                "classes": ["法师"],
                "casting_time": "动作",
                "range": "自身",
                "damage_expression": "3d6",
                "damage_type": "心灵",
                "save": "感知豁免",
            },
        },
    ]
    for record in records:
        (spells / f"{record['stable_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False),
            encoding="utf-8",
        )

    options = CharacterCatalog(tmp_path).options()["spells"]
    fireball = next(item for item in options if item["name"] == "火球术")
    mage_hand = next(item for item in options if item["name"] == "法师之手")
    detect_magic = next(item for item in options if item["name"] == "侦测魔法")

    assert fireball["damage_expression"] == "8d6"
    assert fireball["save_ability"] == "敏捷"
    assert fireball["half_damage_on_save"] is True
    assert fireball["resource_key"] == "spell_slots_3"
    assert fireball["resolution_kind"] == "damage"
    assert fireball["rule_plan"]["automation_ready"] is True
    fireball_target = fireball["rule_plan"]["blocks"][0]
    assert fireball_target["mode"] == "area"
    assert fireball_target["shape"] == "sphere"
    assert fireball_target["range_ft"] == 150
    assert fireball_target["size_ft"] == 20
    assert any(
        block["kind"] == "damage" and block["expression"] == "8d6"
        for block in fireball["rule_plan"]["blocks"]
    )
    assert mage_hand["level"] == 0
    assert mage_hand["resource_key"] is None
    assert mage_hand["resolution_kind"] == "narrative"
    assert detect_magic["damage_expression"] is None
    assert detect_magic["save_ability"] is None
    assert "后续法术" not in detect_magic["description"]
    assert detect_magic["rule_plan"]["automation_confidence"] == "manual"
    assert all(
        block["kind"] != "damage"
        for block in detect_magic["rule_plan"]["blocks"]
    )
