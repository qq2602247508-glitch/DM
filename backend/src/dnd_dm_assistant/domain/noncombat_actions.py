from __future__ import annotations

import math
import random
import re
from collections.abc import Callable
from typing import Any

ABILITY_LABELS = {
    "strength": "力量",
    "dexterity": "敏捷",
    "constitution": "体质",
    "intelligence": "智力",
    "wisdom": "感知",
    "charisma": "魅力",
}

SKILL_RULES: dict[str, tuple[str, int, str]] = {
    "调查": ("intelligence", 12, "寻找线索、机关或隐藏结构"),
    "察觉": ("wisdom", 12, "发现附近可见或可听见的异常"),
    "洞悉": ("wisdom", 12, "判断目标的意图或情绪"),
    "欺瞒": ("charisma", 12, "以谎言影响一个能理解你的目标"),
    "游说": ("charisma", 12, "以理由或善意影响一个能理解你的目标"),
    "威吓": ("charisma", 12, "以威胁迫使目标让步"),
    "潜行": ("dexterity", 12, "避开附近生物的注意"),
    "巧手": ("dexterity", 12, "进行精细手部操作或藏取物品"),
    "运动": ("strength", 12, "攀爬、跳跃、游泳或用蛮力处理障碍"),
    "杂技": ("dexterity", 12, "保持平衡或完成敏捷动作"),
    "医药": ("wisdom", 10, "稳定伤者或判断伤势"),
    "生存": ("wisdom", 12, "追踪、辨向或处理野外环境"),
    "奥秘": ("intelligence", 12, "回忆或分析魔法知识"),
    "历史": ("intelligence", 12, "回忆历史知识"),
    "自然": ("intelligence", 12, "回忆自然知识"),
    "宗教": ("intelligence", 12, "回忆宗教知识"),
}

SOCIAL_SKILLS = {"洞悉", "欺瞒", "游说", "威吓"}
OBJECT_SKILLS = {"调查", "察觉", "巧手", "运动", "奥秘", "历史", "自然", "宗教"}


def ability_modifier(score: int) -> int:
    return math.floor((score - 10) / 2)


def proficiency_bonus(level: int) -> int:
    return 2 + max(0, level - 1) // 4


def skill_modifier(character: Any, skill: str, ability: str) -> tuple[int, list[str]]:
    total = ability_modifier(int((character.ability_scores or {}).get(ability, 10)))
    reasons = [f"{ABILITY_LABELS[ability]}调整值 {total:+d}"]
    skill_data = (character.skills or {}).get(skill)
    proficient = False
    expertise = False
    if isinstance(skill_data, dict):
        proficient = bool(skill_data.get("proficient"))
        expertise = bool(skill_data.get("expertise"))
    if proficient:
        multiplier = 2 if expertise else 1
        bonus = proficiency_bonus(int(character.level)) * multiplier
        total += bonus
        reasons.append(f"{'专精' if expertise else '熟练'} {bonus:+d}")
    return total, reasons


def parse_range_ft(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    if "self" in lowered or "自身" in value or "触及" in value or "touch" in lowered:
        return 0 if "self" in lowered or "自身" in value else 5
    match = re.search(r"(\d+)\s*(?:ft|feet|foot|尺)", lowered)
    return int(match.group(1)) if match else None


def grid_range_ft(
    actor: dict[str, int] | None,
    target: dict[str, int] | None,
    cell_size_ft: int,
) -> int | None:
    if actor is None or target is None:
        return None
    return max(
        abs(int(actor["row"]) - int(target["row"])),
        abs(int(actor["col"]) - int(target["col"])),
    ) * cell_size_ft


def roll_save(
    ability_scores: dict[str, int],
    ability: str,
    dc: int,
    roller: Callable[[int, int], int] = random.randint,
) -> dict[str, Any]:
    raw = roller(1, 20)
    modifier = ability_modifier(int(ability_scores.get(ability, 10)))
    total = raw + modifier
    return {
        "owner": "system",
        "ability": ability,
        "ability_label": ABILITY_LABELS.get(ability, ability),
        "formula": f"1d20{modifier:+d}",
        "raw_roll": raw,
        "modifier": modifier,
        "total": total,
        "dc": dc,
        "success": total >= dc,
        "note": "未记录专门豁免熟练，按目标属性调整值计算；DM 可复核。",
    }


def public_cells(layers_json: dict[str, object]) -> list[dict[str, Any]]:
    raw = layers_json.get("cells", [])
    if not isinstance(raw, list):
        return []
    result = []
    for cell in raw[:1000]:
        if not isinstance(cell, dict):
            continue
        try:
            row, col = int(cell["row"]), int(cell["col"])
        except (KeyError, TypeError, ValueError):
            continue
        result.append(
            {
                "row": row,
                "col": col,
                "kind": str(cell.get("kind") or "floor"),
                "label": str(cell.get("label") or ""),
            }
        )
    return result


def json_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
