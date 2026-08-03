"""Small canonical facts used to repair legacy character spell projections.

Some old characters stored only a spell name and damage expression.  The
combat UI must not turn those missing fields into a fake 5-foot attack, so
these facts are used only when the persisted spell metadata is incomplete.
"""

from __future__ import annotations

import re
from typing import Any

_SPELL_FACTS: dict[str, dict[str, Any]] = {
    "恶言相加": {
        "spell_level": 0,
        "range": "60尺",
        "description": "目标进行感知豁免；失败受到心灵伤害，并在其下一次攻击检定中承受劣势。",
        "save_ability": "wisdom",
        "damage_type": "psychic",
        "resolution_kind": "save_damage",
        "conditions": ["受惊（攻击检定劣势；不能主动靠近恐惧源）"],
    },
    "不谐低语": {
        "spell_level": 1,
        "resource_key": "spell_slots_1",
        "resource_cost": 1,
        "upcast_damage_dice": 1,
        "range": "60尺",
        "description": "目标进行感知豁免；失败受到心灵伤害，并必须立即用反应远离施法者。",
        "save_ability": "wisdom",
        "damage_type": "psychic",
        "resolution_kind": "save_damage",
        "reaction": {
            "event": "豁免失败后",
            "timing": "when",
            "effect": "目标必须立即使用反应移动，且尽可能远离施法者",
            "requires_reaction": True,
        },
    },
    "雷鸣波": {
        "spell_level": 1,
        "resource_key": "spell_slots_1",
        "resource_cost": 1,
        "upcast_damage_dice": 1,
        "range": "自身；15尺立方",
        "area": "15尺立方",
        "area_shape": "cube",
        "area_size_ft": 15,
        "description": (
            "以自身为起点的15尺立方区域；目标进行体质豁免，"
            "成功伤害减半，失败受到雷鸣伤害并被推开。"
        ),
        "save_ability": "constitution",
        "damage_type": "thunder",
        "half_damage_on_save": True,
        "resolution_kind": "area_damage",
        "movement": {"distance_ft": 10, "type": "forced", "direction": "away"},
    },
    "法师之手": {
        "spell_level": 0,
        "range": "30尺",
        "description": "操纵一个无人穿戴或持握的轻小物体；不能攻击或激活魔法物品。",
        "resolution_kind": "narrative",
    },
    "妖火": {
        "spell_level": 1,
        "resource_key": "spell_slots_1",
        "resource_cost": 1,
        "range": "60尺；20尺立方",
        "area": "20尺立方",
        "area_shape": "cube",
        "area_size_ft": 20,
        "description": "目标进行敏捷豁免；失败后发光，针对发光目标的攻击检定具有优势；需要专注。",
        "save_ability": "dexterity",
        "concentration": True,
        "resolution_kind": "area_condition",
        "conditions": ["发光（针对目标的攻击检定具有优势）"],
    },
    "治愈真言": {
        "spell_level": 1,
        "resource_key": "spell_slots_1",
        "resource_cost": 1,
        "upcast_healing_dice": 1,
        "range": "60尺",
        "description": "一个你看见的生物恢复生命值；使用附赠动作和法术位。",
        "healing": "2d4+3",
        "cost": "bonus_action",
        "resolution_kind": "healing",
    },
}


def canonical_spell_fields(
    name: str,
    *,
    spellcasting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return missing legacy fields without replacing explicit user data."""
    return dict(_SPELL_FACTS.get(name, {}))


def enrich_spell_action(
    action: dict[str, Any],
    *,
    spellcasting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = str(action.get("name") or "")
    facts = canonical_spell_fields(name, spellcasting=spellcasting)
    if not facts:
        return action
    merged = dict(action)
    for key, value in facts.items():
        if merged.get(key) in (None, ""):
            merged[key] = value
    if (
        spellcasting
        and spellcasting.get("save_dc") not in (None, "")
        and (merged.get("save_ability") or facts.get("save_ability"))
        and merged.get("save_dc") in (None, "")
    ):
        merged["save_dc"] = spellcasting["save_dc"]
    return merged


def upcast_spell_action(action: dict[str, Any], slot_level: int) -> dict[str, Any]:
    base_level = int(action.get("spell_level") or 0)
    if base_level <= 0 or slot_level < base_level:
        return action
    result = dict(action)
    for field, increment_key in (
        ("damage", "upcast_damage_dice"),
        ("healing", "upcast_healing_dice"),
    ):
        expression = result.get(field)
        extra_dice = int(result.get(increment_key) or 0)
        match = re.match(r"^(\d+)d(\d+)(.*)$", str(expression or ""), re.IGNORECASE)
        if match and extra_dice > 0:
            result[field] = (
                f"{int(match.group(1)) + (slot_level - base_level) * extra_dice}d"
                f"{match.group(2)}{match.group(3)}"
            )
    result["resource_key"] = f"spell_slots_{slot_level}"
    result["resource_cost"] = 1
    result["selected_slot_level"] = slot_level
    return result
