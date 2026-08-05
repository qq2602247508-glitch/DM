from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.rule_block_compiler import compile_rule_blocks_dict
from dnd_dm_assistant.application.rule_metadata import spell_rule_fields
from dnd_dm_assistant.domain.content_packs import (
    ContentPack,
    content_pack_for_record,
    is_spell_detail_record,
    list_content_packs,
    normalized_record_edition,
    validate_content_pack_compatibility,
)

CONTENT_ENTRY_TYPES = {
    "spells": "spell",
    "monsters": "monster",
    "equipment": "equipment",
    "items": "item",
    "classes": "feature",
    "subclasses": "feature",
    "feats": "feature",
    "backgrounds": "feature",
    "conditions": "feature",
    "actions": "feature",
    "rules": "rule",
}
CURRENT_EDITIONS = {"2024", "2025"}
SPELL_CLASS_NAMES = (
    "野蛮人",
    "吟游诗人",
    "牧师",
    "德鲁伊",
    "战士",
    "武僧",
    "圣武士",
    "游侠",
    "游荡者",
    "术士",
    "魔契师",
    "法师",
    "奇械师",
)
ABILITY_KEYS = {
    "力量": "strength",
    "敏捷": "dexterity",
    "体质": "constitution",
    "智力": "intelligence",
    "感知": "wisdom",
    "魅力": "charisma",
}
_DAMAGE_TYPE_ALIASES = {
    "强酸": "acid",
    "酸蚀": "acid",
    "钝击": "bludgeoning",
    "寒冷": "cold",
    "火焰": "fire",
    "力场": "force",
    "闪电": "lightning",
    "暗蚀": "necrotic",
    "黯蚀": "necrotic",
    "穿刺": "piercing",
    "毒素": "poison",
    "心灵": "psychic",
    "光耀": "radiant",
    "挥砍": "slashing",
    "雷鸣": "thunder",
}

def _feature_filters(data: dict[str, Any]) -> dict[str, Any]:
    content_type = str(data.get("content_type") or "")
    if content_type != "classes":
        return {"feature_kind": content_type.rstrip("s") or "feature"}
    name = _clean_name(str(data.get("name") or ""))
    heading_path = [
        _clean_name(str(value))
        for value in data.get("heading_path", [])
        if isinstance(value, str)
    ]
    class_name = next(
        (value for value in reversed(heading_path) if value in SPELL_CLASS_NAMES),
        name if name in SPELL_CLASS_NAMES else "",
    )
    feature_kind = "class" if name == class_name else "subclass"
    return {
        "class_name": class_name,
        "classes": [class_name] if class_name else [],
        "feature_kind": feature_kind,
        "recommended_level": 1 if feature_kind == "class" else 3,
    }


def _item_function(name: str) -> str:
    """Give mundane role-play gear a useful browsing category."""

    groups = (
        ("illumination", ("火把", "提灯", "灯", "灯油", "火绒")),
        (
            "consumable",
            (
                "口粮",
                "燃油",
                "强酸",
                "抗毒",
                "毒药",
                "圣水",
                "治疗药水",
                "医疗包",
                "治疗工具",
                "卷轴",
                "炽火胶",
                "滚珠",
                "铁蒺藜",
                "肥皂",
                "蜡烛",
            ),
        ),
        ("container", ("背包", "袋", "箱", "桶", "瓶", "水袋", "箭袋", "卷轴匣")),
        ("camping", ("铺盖", "帐篷", "毯", "炊具", "钓具")),
        ("exploration", ("绳", "抓钩", "铁钉", "撬棍", "梯", "望远镜", "放大镜")),
        ("restraint_security", ("锁", "镣铐", "链", "捕兽夹")),
        ("writing_navigation", ("纸", "墨", "笔", "地图", "指南针", "书", "信号哨")),
    )
    for category, keywords in groups:
        if any(keyword in name for keyword in keywords):
            return category
    return "miscellaneous"


def _adventuring_gear_classification(name: str) -> tuple[str, str, str]:
    """Keep combat consumables out of the narrative-prop item shelf."""

    if "卷轴" in name and "卷轴匣" not in name and "地图" not in name:
        return "equipment", "scroll", "magic_consumable"
    if name == "治疗药水":
        return "equipment", "potion", "magic_consumable"
    if name in {
        "强酸",
        "炽火胶",
        "抗毒剂",
        "基础毒药",
        "圣水",
        "铁蒺藜",
        "滚珠",
    }:
        return "equipment", "consumable", "mundane_equipment"
    return "item", "adventuring_gear", "mundane_item"


def _clean_name(value: str) -> str:
    chinese = re.match(r"^([\u3400-\u9fff·（）()、\s]+?)(?=[A-Za-z]|$)", value.strip())
    result = (chinese.group(1) if chinese else value).strip()
    return re.sub(r"\s+", " ", result)


def _plain_markdown(value: str) -> str:
    result = re.sub(r"(?m)^#{1,6}\s*", "", value)
    result = result.replace("**", "").replace("__", "").replace("*", "")
    result = re.sub(r"\s+", " ", result)
    return result.strip()


def _normalize_spell_classes(value: object) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    text = "、".join(str(item) for item in raw_values if item)
    return [class_name for class_name in SPELL_CLASS_NAMES if class_name in text]


def _spell_description(data: dict[str, Any]) -> str:
    markdown = str(data.get("content_markdown") or "")
    headings = list(re.finditer(r"(?m)^#{4,6}\s+.+?\s*$", markdown))
    if headings:
        start = headings[0].start()
        end = headings[1].start() if len(headings) > 1 else len(markdown)
        return _plain_markdown(markdown[start:end])[:1600]
    return str(data.get("content_plain_text") or "")[:1600]


def _number(text: str, pattern: str, default: int) -> int:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else default


def _price_cp(value: str) -> int:
    match = re.search(r"([\d,.]+)\s*(CP|SP|EP|GP|PP)", value, flags=re.IGNORECASE)
    if not match:
        return 0
    amount = float(match.group(1).replace(",", ""))
    multiplier = {"CP": 1, "SP": 10, "EP": 50, "GP": 100, "PP": 1000}[match.group(2).upper()]
    return round(amount * multiplier)


def _weight_lb(value: str) -> float:
    if "半磅" in value:
        return 0.5
    fraction = re.search(r"(\d+)\s*/\s*(\d+)\s*磅", value)
    if fraction:
        return int(fraction.group(1)) / int(fraction.group(2))
    match = re.search(r"([\d.]+)\s*磅", value)
    return float(match.group(1)) if match else 0


_MONSTER_ACTION_SECTIONS = {
    "动作": "action",
    "附赠动作": "bonus_action",
    "反应": "reaction",
    "传奇动作": "legendary_action",
    "巢穴动作": "lair_action",
    "施法": "spellcasting",
}


def _monster_action_sections(text: str) -> list[tuple[str, str]]:
    """Split a stat block without flattening reactions and legendary actions.

    The old parser only kept the first ``动作`` section, which made a monster
    look like it had no reactions, recharge moves, or legendary actions after
    instantiation.  Keep the section kind in the atom so a later executor can
    enforce the correct action economy instead of treating every line as a
    normal action.
    """

    heading = re.compile(
        r"(?m)^(动作|附赠动作|反应|传奇动作|巢穴动作|施法)(?:Actions)?\s*$"
    )
    matches = list(heading.finditer(text))
    if not matches:
        return [("action", text)]
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((_MONSTER_ACTION_SECTIONS[match.group(1)], text[match.end() : end]))
    return sections


def _monster_actions(text: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for action_type, raw in _monster_action_sections(text):
        legendary_pool = re.search(
            r"(?:每轮|每回合)?[^。\n]{0,30}?(?:可以|能|可)"
            r"(?:进行|执行|采取|使用)?\s*(一|二|两|三|四|五|六|\d+)\s*(?:个|次)?传奇动作",
            raw,
        )
        legendary_pool_max = (
            _chinese_count(legendary_pool.group(1)) if legendary_pool else None
        )
        for source_line in (part.strip(" *#") for part in raw.splitlines()):
            # A subset of imported Chinese stat blocks separates digits while
            # decoding (for example ``3 0 尺`` or ``1 0 d 6``).  Normalize the
            # parsing copy so an area regex cannot capture only the trailing
            # zero as its size.  The original line remains the audit text.
            line = re.sub(r"(?<=\d)\s+(?=\d)", "", source_line)
            if not line or not re.search(
                r"命中|攻击|伤害|豁免|多重攻击|充能|传奇动作|巢穴|施法|移动", line
            ):
                continue
            if (
                action_type == "legendary_action"
                and legendary_pool
                and legendary_pool.group(0) in line
                and not re.search(r"命中|伤害|豁免|攻击检定", line)
            ):
                continue
            name_match = re.match(r"([^。.：:（(]{2,40})(?:[。.：:（(])", line)
            damage = re.search(
                r"[（(]\s*(\d+d\d+(?:\s*[+-]\s*\d+)?)\s*[）)]"
                r"|(?:受到|造成)[^。；，]{0,24}?(\d+d\d+(?:\s*[+-]\s*\d+)?)",
                line,
            )
            bonus = re.search(
                r"(?:命中|攻击(?:检定)?)[：:]?\s*\+\s*(\d+)"
                r"|\+(\d+)\s*命中",
                line,
            )
            reach = re.search(r"(?:触及|射程)\s*(\d+)(?:\s*/\s*\d+)?\s*尺", line)
            save = re.search(r"DC\s*(\d+)\s*的?\s*(力量|敏捷|体质|智力|感知|魅力)\s*豁免", line)
            conditions = [
                condition
                for condition in (
                    "倒地", "失能", "受惊", "束缚", "擒抱", "隐形", "中毒", "目盲",
                    "耳聋", "魅惑", "麻痹", "石化", "震慑",
                )
                if condition in line and not re.search(rf"免疫[^。；]*{condition}", line)
            ]
            movement_match = re.search(r"(?:推开|推离|拉向)[^。；]{0,20}?(\d+)\s*尺", line)
            area_match = re.search(
                r"(\d+)\s*尺(?:长、?\s*\d+\s*尺宽的?)?\s*"
                r"(锥形|锥状|直线|线状|半径|球形|立方|圆柱)",
                line,
            ) or re.search(r"(半径)\s*(\d+)\s*尺", line)
            area_shape: str | None = None
            area_size_ft: int | None = None
            area_height_ft: int | None = None
            cylinder_match = re.search(
                r"(\d+)\s*尺\s*半径[^。；，]*?(\d+)\s*尺\s*(?:高|高度)[^。；，]*?圆柱",
                line,
            )
            if cylinder_match:
                area_shape = "cylinder"
                area_size_ft = int(cylinder_match.group(1))
                area_height_ft = int(cylinder_match.group(2))
            if area_match:
                if area_shape == "cylinder":
                    pass
                elif area_match.group(1) == "半径":
                    area_size_ft = int(area_match.group(2))
                    # Rule blocks use the 5e term ``sphere``; the renderer
                    # later projects it to a 2-D circle on a battle grid.
                    area_shape = "sphere"
                else:
                    area_size_ft = int(area_match.group(1))
                    area_shape = {
                        "锥形": "cone",
                        "锥状": "cone",
                        "直线": "line",
                        "线状": "line",
                        "半径": "sphere",
                        "球形": "sphere",
                        "立方": "cube",
                        "圆柱": "cylinder",
                    }[area_match.group(2)]
            area_width = re.search(r"(\d+)\s*尺宽", line)
            damage_type = next(
                (
                    damage_type
                    for damage_type in (
                        "强酸", "酸蚀", "钝击", "寒冷", "火焰", "力场", "闪电", "黯蚀",
                        "穿刺", "毒素", "心灵", "光耀", "挥砍", "雷鸣",
                    )
                    if damage_type in line
                ),
                None,
            )
            recharge_match = re.search(r"充能\s*(?:(\d+)\s*(?:[-–]\s*(\d+))?)?", line)
            legendary_cost = re.search(r"(?:消耗|花费)\s*(\d+)\s*(?:个)?传奇动作", line)
            multiattack_count = re.search(
                r"多重攻击.*?(?:进行|发动)\s*(两|三|四|五|\d+)次", line
            )
            count_text = multiattack_count.group(1) if multiattack_count else None
            multiattack_count_value = _chinese_count(count_text)
            conditions_on_failure = conditions if save else []
            conditions_on_hit = conditions if bonus and not save else []
            condition_duration = _monster_condition_duration(line)
            damage_expression = next(
                (group for group in damage.groups() if group),
                None,
            ) if damage else None
            actions.append(
                {
                    "name": (name_match.group(1) if name_match else line[:30]).strip(),
                    "description": source_line[:900],
                    "damage": damage_expression.replace(" ", "") if damage_expression else None,
                    "damage_type": damage_type,
                    "attack_bonus": int(bonus.group(1) or bonus.group(2)) if bonus else None,
                    "range_ft": int(reach.group(1)) if reach else None,
                    "range": f"{reach.group(1)}尺" if reach else None,
                    "area_shape": area_shape,
                    "area_size_ft": area_size_ft,
                    "area_width_ft": int(area_width.group(1)) if area_width else None,
                    "area_height_ft": area_height_ft,
                    "area_origin_self": bool(
                        area_shape and re.search(r"以自身|从(?:该生物|怪物|它)处|自身", line)
                    ),
                    "affects_multiple_targets": bool(
                        area_shape
                        or re.search(r"(?:范围内|区域内).{0,16}(?:每个|所有|任意)生物", line)
                    ),
                    "save_dc": int(save.group(1)) if save else None,
                    "save_ability": ABILITY_KEYS.get(save.group(2)) if save else None,
                    "half_damage_on_save": bool(
                        save and re.search(r"(?:成功|通过).*?(?:减半|一半|半伤)", line)
                    ),
                    "conditions": conditions,
                    "conditions_on_failure": conditions_on_failure,
                    "conditions_on_hit": conditions_on_hit,
                    "condition_duration": condition_duration,
                    "movement": (
                        {
                            "distance_ft": int(movement_match.group(1)),
                            "type": "forced",
                            "direction": "away",
                        }
                        if movement_match
                        else None
                    ),
                    "action_type": action_type,
                    "recharge": (
                        {
                            "minimum": int(recharge_match.group(1) or 6),
                            "maximum": int(recharge_match.group(2) or recharge_match.group(1) or 6),
                        }
                        if recharge_match
                        else None
                    ),
                    "legendary_cost": (
                        int(legendary_cost.group(1)) if legendary_cost else None
                    ),
                    "legendary_pool_max": (
                        legendary_pool_max if action_type == "legendary_action" else None
                    ),
                    "reaction_trigger": (
                        line[: line.find("，")].strip()
                        if action_type == "reaction" and "当" in line and "，" in line
                        else None
                    ),
                    "reaction_event": (
                        _monster_reaction_event(line) if action_type == "reaction" else None
                    ),
                    "multiattack": bool("多重攻击" in line),
                    "multiattack_count": multiattack_count_value,
                    "multiattack_components": [],
                    "auto_eligible": False,
                }
            )
            if len(actions) >= 24:
                break
        if len(actions) >= 24:
            break
    _link_monster_multiattacks(actions)
    for action in actions:
        action["auto_eligible"] = _monster_action_auto_eligible(action)
    return actions


def _chinese_count(value: str | None) -> int | None:
    if value is None:
        return None
    if value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
    }.get(value)


def _monster_condition_duration(text: str) -> str | None:
    patterns = (
        (r"直到(?:该生物|该怪物|它|攻击者|施法者)的?下个回合开始", "actor_turn_start"),
        (r"直到(?:该生物|该怪物|它|攻击者|施法者)的?下个回合结束", "actor_turn_end"),
        (r"直到(?:目标|受术者)的?下个回合开始", "target_turn_start"),
        (r"直到(?:目标|受术者)的?下个回合结束", "target_turn_end"),
    )
    return next((value for pattern, value in patterns if re.search(pattern, text)), None)


def _monster_reaction_event(text: str) -> str | None:
    """Map only unambiguous reaction prose to a closed event vocabulary."""

    if "离开" in text and any(value in text for value in ("触及范围", "近战范围", "威胁范围")):
        return "leaves_reach"
    if "进入" in text and any(value in text for value in ("触及范围", "近战范围", "威胁范围")):
        return "enters_reach"
    if "被命中" in text or "被攻击命中" in text:
        return "hit_by_attack"
    if "受到伤害" in text or "承受伤害" in text:
        return "takes_damage"
    if "施法" in text or "施展法术" in text:
        return "casts_spell"
    if "回合结束" in text:
        return "turn_end"
    return None


def _link_monster_multiattacks(actions: list[dict[str, Any]]) -> None:
    named_actions = [
        str(action.get("name") or "")
        for action in actions
        if not action.get("multiattack") and str(action.get("name") or "")
    ]
    for action in actions:
        if not action.get("multiattack"):
            continue
        description = str(action.get("description") or "")
        components: list[dict[str, Any]] = []
        for name in sorted(named_actions, key=len, reverse=True):
            match = re.search(
                rf"(一|二|两|三|四|五|六|\d+)\s*次(?:使用|发动|进行)?(?:其)?{re.escape(name)}",
                description,
            )
            if match:
                count = _chinese_count(match.group(1))
                if count:
                    components.append({"action_name": name, "count": count})
        expected = action.get("multiattack_count")
        if expected and sum(int(item["count"]) for item in components) == expected:
            action["multiattack_components"] = components


def _monster_action_auto_eligible(action: dict[str, Any]) -> bool:
    if action.get("multiattack"):
        return bool(action.get("multiattack_components"))
    action_type = str(action.get("action_type") or "action")
    if action_type == "reaction" and not action.get("reaction_trigger"):
        return False
    if action.get("conditions") and not action.get("condition_duration"):
        return False
    has_resolution = bool(action.get("damage") and action.get("damage_type"))
    has_roll = bool(
        action.get("attack_bonus") is not None
        or (action.get("save_dc") is not None and action.get("save_ability"))
    )
    has_range = bool(
        action.get("range_ft") is not None
        or action.get("area_size_ft") is not None
        or action.get("area_origin_self")
    )
    return has_resolution and has_roll and has_range


def _monster_defenses(text: str) -> dict[str, list[str]]:
    """Extract only typed damage defenses from a monster stat block.

    Keep the canonical English keys used by combat resolution while retaining
    the original source text separately for the rule plan.  Unknown phrases
    (for example, conditional resistance) are not turned into a blanket type.
    """

    result = {
        "damage_resistances": [],
        "damage_vulnerabilities": [],
        "damage_immunities": [],
        "condition_immunities": [],
    }
    section_end = (
        r"(?=伤害(?:抗性|易伤|免疫)|状态免疫|护甲等级|生命值|速度|力量|敏捷|"
        r"智力|感知|魅力|动作|反应|传奇动作|巢穴动作|$)"
    )
    for operation, label in (
        ("damage_resistances", "抗性"),
        ("damage_vulnerabilities", "易伤"),
        ("damage_immunities", "免疫"),
    ):
        match = re.search(rf"伤害{label}\s*[:：]?\s*(.+?){section_end}", text)
        if not match:
            continue
        source = match.group(1)
        result[operation] = sorted(
            {
                canonical
                for name, canonical in _DAMAGE_TYPE_ALIASES.items()
                if name in source
            }
        )
    # 2025 stat blocks shorten the same headings to “抗性 / 易伤 / 免疫”.
    # Keep this separate from the legacy parser so the condition list after
    # the semicolon is never promoted to a damage type.
    compact_damage_sections = (
        ("damage_resistances", r"(?<!伤害)抗性"),
        ("damage_vulnerabilities", r"(?<!伤害)易伤"),
    )
    for operation, heading in compact_damage_sections:
        match = re.search(
            rf"{heading}\s*[:：]?\s*(.+?)(?=免疫|状态免疫|感官|语言|挑战等级|特质|动作|反应|$)",
            text,
        )
        if not match:
            continue
        source = match.group(1)
        result[operation] = sorted(
            {
                canonical
                for name, canonical in _DAMAGE_TYPE_ALIASES.items()
                if name in source
            }
        )
    compact_immunity = re.search(
        r"(?<!伤害)(?<!状态)免疫\s*[:：]?\s*(.+?)(?=感官|语言|挑战等级|特质|动作|反应|$)",
        text,
    )
    if compact_immunity:
        damage_source, _, condition_source = compact_immunity.group(1).partition("；")
        result["damage_immunities"] = sorted(
            {
                canonical
                for name, canonical in _DAMAGE_TYPE_ALIASES.items()
                if name in damage_source
            }
        )
        condition_names = (
            "目盲", "魅惑", "耳聋", "恐慌", "擒抱", "失能", "隐形", "麻痹",
            "石化", "中毒", "倒地", "受惊", "束缚", "震慑", "力竭",
        )
        result["condition_immunities"] = sorted(
            {name for name in condition_names if name in condition_source}
        )
    condition_match = re.search(rf"状态免疫\s*[:：]?\s*(.+?){section_end}", text)
    if condition_match:
        condition_names = (
            "目盲", "魅惑", "耳聋", "恐慌", "擒抱", "失能", "隐形", "麻痹",
            "石化", "中毒", "倒地", "受惊", "束缚", "震慑",
        )
        result["condition_immunities"] = sorted(
            {name for name in condition_names if name in condition_match.group(1)}
        )
    return result


def _monster_fields(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    scores = {
        key: _number(text, rf"{label}\s*(\d{{1,2}})(?:\s|（|\()", 10)
        for label, key in ABILITY_KEYS.items()
    }
    cr_match = re.search(r"(?:\bCR|挑战等级)\s*(?:[：:|]\s*)?([0-9]+(?:/[0-9]+)?)", text)
    type_match = re.search(
        r"(?:微型|小型|中型|大型|巨型|超巨型)(?:\s*[\u3400-\u9fff]+)?"
        r"\s*(异怪|野兽|构装生物|龙|元素|妖精|邪魔|巨人|类人生物|怪兽|泥怪|植物|亡灵)",
        text,
    )
    filters = {
        "challenge_rating": cr_match.group(1) if cr_match else "未知",
        "monster_type": type_match.group(1) if type_match else "未分类",
    }
    defenses = _monster_defenses(text)
    rules = {
        "armor_class": _number(text, r"(?:\bAC|护甲等级)\s*(?:[：:|]\s*)?(\d+)", 10),
        "hp": _number(text, r"(?:\bHP|生命值)\s*(?:[：:|]\s*)?(\d+)", 1),
        "speed": _number(text, r"速度\s*(?:[：:|]\s*)?(\d+)\s*尺", 30),
        "ability_scores": scores,
        "actions": _monster_actions(text),
        **defenses,
    }
    return filters, rules


def _has_monster_stat_block(text: str) -> bool:
    """Require an actual stat block before promoting an unknown source page."""

    return all(
        re.search(pattern, text) is not None
        for pattern in (
            r"(?:\bAC\b|护甲等级)\s*(?:[：:|]\s*)?\d+",
            r"(?:\bHP\b|生命值)\s*(?:[：:|]\s*)?\d+",
            r"(?:\bCR\b|挑战等级)\s*(?:[：:|]\s*)?\d",
            r"(?:动作|Actions)",
        )
    )


def _is_directory_or_index_record(data: dict[str, Any]) -> bool:
    """Recognise navigation pages before they become narrative rule atoms."""

    name = str(data.get("name") or "")
    source_path = str(data.get("source_relative_path") or "")
    plain = str(data.get("content_plain_text") or "")
    if re.search(r"(?:目录|概述|索引|速查|列表|清单)$", name):
        return True
    if re.search(r"/(?:目录|概述|索引|速查|列表)\.html?$", source_path):
        return True
    # A short heading-only page is navigation, not a world rule.  The length
    # bound stops us from hiding a real concise magic-item description.
    return len(plain.strip()) < 80 and plain.count("\n") <= 3


def _looks_like_item_detail(data: dict[str, Any]) -> bool:
    """Promote only an explicitly described item page, never a book heading."""

    path = str(data.get("source_relative_path") or "")
    text = str(data.get("content_plain_text") or data.get("content_markdown") or "")
    return bool(
        re.search(r"(?:魔法物品|物品|装备)", path)
        and re.search(r"(?:神器|传说|极珍稀|非常稀有|珍稀|非普通|普通)", text)
        and len(text.strip()) >= 80
    )


def _content_pack_effective_type(data: dict[str, Any], pack: ContentPack | None) -> str:
    """Normalise trusted supplement shapes without promoting arbitrary prose."""

    declared = str(data.get("content_type") or "")
    if declared in CONTENT_ENTRY_TYPES:
        return declared
    if pack is None:
        return declared
    text = str(data.get("content_plain_text") or "")
    if _has_monster_stat_block(text):
        return "monsters"
    if _looks_like_item_detail(data):
        return "items"
    # A directory remains a non-instantiable rule reference with an explicit
    # status; narrative pages become DM-choice rule atoms instead of invisible
    # `unknown` records.
    return "rules"


def _content_pack_status(data: dict[str, Any], content_type: str) -> str:
    """Expose whether this atom was read directly or needed source normalisation."""

    declared = str(data.get("content_type") or "")
    if declared != content_type:
        if content_type == "rules":
            return "directory" if _is_directory_or_index_record(data) else "dm_choice"
        # A parsed stat block/item atom is usable, but it was promoted from an
        # untyped source and still needs provenance-level normalisation.  Do
        # not turn that status into a claim that the original source was clean.
        return "needs_normalization"
    if content_type in {"classes", "rules"}:
        # These are useful references, but their option/progression structures
        # need a source-specific normaliser before they can change a character.
        return "structured_reference"
    return "imported"


def _decorate_content_pack_entry(
    entry: dict[str, Any],
    *,
    data: dict[str, Any],
    pack: ContentPack | None,
    content_type: str,
) -> dict[str, Any]:
    if pack is None:
        return entry
    status = _content_pack_status(data, content_type)
    filters = {
        **dict(entry.get("filters_json") or {}),
        "content_pack_key": pack.key,
        "content_pack_label": pack.label,
        "content_pack_status": status,
        "source_book": pack.source_book,
        "edition": normalized_record_edition(data),
        "source_origin": "official_supplement",
        "requires_legacy": pack.requires_legacy,
        "instantiable": status != "directory",
    }
    rules = {
        **dict(entry.get("rules_json") or {}),
        "content_pack": {
            "key": pack.key,
            "label": pack.label,
            "status": status,
            "source_edition": normalized_record_edition(data),
            "requires_legacy": pack.requires_legacy,
        },
    }
    tags = [str(tag) for tag in entry.get("tags") or []]
    for tag in ("内容包", pack.label, status):
        if tag not in tags:
            tags.append(tag)
    return {
        **entry,
        "source_kind": "official",
        "source_name": pack.source_book,
        "tags": tags,
        "filters_json": filters,
        "rules_json": rules,
    }


def _atomic_monster_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Split legacy CR/type index pages into actual reusable monster atoms."""

    text = str(data.get("content_plain_text") or "")
    lines = text.splitlines()
    size_pattern = re.compile(r"^(微型|小型|中型|大型|巨型|超巨型)")
    starts: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        if not size_pattern.match(line.strip()) or index == 0:
            continue
        name_index = index - 1
        name_parts = [lines[name_index].strip()]
        if not re.search(r"[\u3400-\u9fff]", name_parts[0]) and name_index > 0:
            previous = lines[name_index - 1].strip()
            if re.search(r"[\u3400-\u9fff]", previous):
                name_index -= 1
                name_parts.insert(0, previous)
        raw_name = " ".join(part for part in name_parts if part)
        if not raw_name or not re.search(r"[\u3400-\u9fff]", raw_name):
            continue
        starts.append((name_index, index, raw_name))
    if len(starts) <= 1:
        return []
    stable_id = str(data["stable_id"])
    result: list[dict[str, Any]] = []
    for position, (name_index, _stat_index, raw_name) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        block = "\n".join(lines[name_index:end]).strip()
        name = _clean_name(raw_name)
        if not name or len(block) < 40:
            continue
        filters, rules = _monster_fields(block)
        suffix = hashlib.sha256(f"{stable_id}|{name}|{position}".encode()).hexdigest()[:12]
        result.append(
            {
                "id": f"official:{stable_id}:{suffix}",
                "version": 1,
                "campaign_id": "official",
                "entry_type": "monster",
                "name": name,
                "description": block[:1200],
                "source_kind": "official",
                "source_record_id": stable_id,
                "source_name": data.get("source_book"),
                "family_key": None,
                "tags": ["官方", str(data.get("edition") or "未知版本"), "怪物原子"],
                "filters_json": {
                    "content_type": "monsters",
                    "edition": data.get("edition"),
                    "source_book": data.get("source_book"),
                    **filters,
                },
                "rules_json": {
                    "canonical_url": data.get("canonical_url"),
                    "source_relative_path": data.get("source_relative_path"),
                    **rules,
                },
            }
        )
    return result


def _record_entry(
    data: dict[str, Any],
    *,
    content_type: str | None = None,
    content_pack: ContentPack | None = None,
) -> dict[str, Any] | None:
    content_type = content_type or str(data.get("content_type") or "")
    entry_type = CONTENT_ENTRY_TYPES.get(content_type)
    if entry_type is None or (
        data.get("officiality") != "official" and content_pack is None
    ):
        return None
    if content_pack is not None:
        if content_type == "spells" and not is_spell_detail_record(data):
            return None
        if content_type == "monsters" and not _has_monster_stat_block(
            str(data.get("content_plain_text") or "")
        ):
            return None
        # Item sections are atomised below.  Returning a section page here
        # would make a catalogue heading look like a usable magic item.
        if content_type == "items":
            return None
    stable_id = str(data["stable_id"])
    spell = data.get("spell") if isinstance(data.get("spell"), dict) else None
    filters: dict[str, Any] = {
        "content_type": content_type,
        "edition": data.get("edition"),
        "source_book": data.get("source_book"),
    }
    rules: dict[str, Any] = {
        "canonical_url": data.get("canonical_url"),
        "source_relative_path": data.get("source_relative_path"),
    }
    if spell:
        spell = {**spell, **spell_rule_fields(data)}
        classes = _normalize_spell_classes(spell.get("classes"))
        source_path = str(data.get("source_relative_path") or "")
        if "法术详述" not in source_path:
            return None
        raw_level = spell.get("level")
        spell_level = (
            int(raw_level)
            if isinstance(raw_level, (int, float, str)) and str(raw_level).isdigit()
            else 0  # The corpus uses null for cantrips.
        )
        filters.update(
            {
                "class_name": "、".join(str(value) for value in classes),
                "classes": [str(value) for value in classes],
                "spell_level": spell_level,
                "school": spell.get("school"),
                "casting_time": spell.get("casting_time"),
                "concentration": bool(spell.get("concentration")),
                "ritual": bool(spell.get("ritual")),
            }
        )
        rules.update(spell)
        rules["classes"] = classes
        rules["rule_plan"] = compile_rule_blocks_dict(
            {
                "name": str(data.get("name") or stable_id),
                **rules,
                "description": _spell_description(data),
                "spell_level": spell_level,
                "resource_key": f"spell_slots_{spell_level}" if spell_level > 0 else None,
                "resource_cost": 1 if spell_level > 0 else 0,
                "save_ability": str(spell.get("save") or "").removesuffix("豁免") or None,
                "damage_expression": spell.get("damage_expression"),
                "healing": spell.get("healing"),
            },
            source_kind="spell",
        )
    if entry_type == "monster":
        monster_filters, monster_rules = _monster_fields(str(data.get("content_plain_text") or ""))
        filters.update(monster_filters)
        rules.update(monster_rules)
        for action in rules.get("actions", []):
            if not isinstance(action, dict):
                continue
            action["rule_plan"] = compile_rule_blocks_dict(
                {
                    "name": str(action.get("name") or "怪物动作"),
                    **action,
                    "description": str(action.get("description") or ""),
                    "resolution_kind": "damage" if action.get("damage") else "control",
                },
                source_kind="monster_action",
            )
        if any(rules.get(key) for key in (
            "damage_resistances",
            "damage_vulnerabilities",
            "damage_immunities",
            "condition_immunities",
        )):
            rules["rule_plan"] = compile_rule_blocks_dict(
                {
                    "name": str(data.get("name") or stable_id),
                    "description": str(data.get("content_plain_text") or "")[:2_000],
                    "damage_resistances": rules.get("damage_resistances", []),
                    "damage_vulnerabilities": rules.get("damage_vulnerabilities", []),
                    "damage_immunities": rules.get("damage_immunities", []),
                },
                source_kind="monster",
            )
    if entry_type == "feature":
        feature_data = {**data, "content_type": content_type}
        feature_filters = _feature_filters(feature_data)
        if content_type == "classes" and not feature_filters.get("class_name"):
            return None
        filters.update(feature_filters)
    if entry_type == "rule":
        is_directory = _is_directory_or_index_record(data)
        filters.update(
            {
                "category": "directory" if is_directory else "narrative_reference",
                "source_record_name": str(data.get("name") or stable_id),
                "content_normalization": "directory" if is_directory else "dm_choice",
                "instantiable": False,
            }
        )
        rules["content_normalization"] = {
            "kind": "directory" if is_directory else "narrative",
            "automation_status": "dm_only",
            "requires_dm_choice": not is_directory,
            "choice_schema": (
                {
                    "kind": "narrative_outcome",
                    "required_fields": ["dm_choice", "adjudication_note"],
                }
                if not is_directory
                else None
            ),
        }
        rules["rule_plan"] = compile_rule_blocks_dict(
            {
                "name": str(data.get("name") or stable_id),
                "description": str(data.get("content_plain_text") or "")[:8_000],
                "source_record_id": stable_id,
            },
            source_kind="rule",
        )
    return {
        "id": f"official:{stable_id}",
        "version": 1,
        "campaign_id": "official",
        "entry_type": entry_type,
        "name": str(data.get("name") or stable_id),
        "description": (
            _spell_description(data) if spell else str(data.get("content_plain_text") or "")[:1200]
        ),
        "source_kind": "official",
        "source_record_id": stable_id,
        "source_name": data.get("source_book"),
        "family_key": None,
        "tags": ["官方", str(data.get("edition") or "未知版本"), content_type],
        "filters_json": filters,
        "rules_json": rules,
    }


def _table_rows(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        if not line.strip().startswith("|"):
            continue
        values = [part.strip() for part in line.strip().strip("|").split("|")]
        if not values or all(re.fullmatch(r"[-: ]+", value or "-") for value in values):
            continue
        rows.append(values)
    return rows


def _atomic_equipment_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    stable_id = str(data["stable_id"])
    name = str(data.get("name") or "")
    markdown = str(data.get("content_markdown") or "")
    rows = _table_rows(markdown)
    result: list[dict[str, Any]] = []

    def append_item(
        raw_name: str,
        *,
        category: str,
        slot: str,
        weight: str,
        price: str,
        rules: dict[str, Any],
    ) -> None:
        item_name = _clean_name(raw_name)
        if not item_name or item_name in {"名称", "护甲", "物品", "种类", "工具"}:
            return
        if not price or price in {"—", "多类"}:
            return
        entry_type = "equipment" if category in {"weapon", "armor", "shield"} else "item"
        item_kind = (
            "mundane_item" if category == "adventuring_gear" else "mundane_equipment"
        )
        if category == "adventuring_gear":
            entry_type, category, item_kind = _adventuring_gear_classification(item_name)
        suffix = hashlib.sha256(f"{stable_id}|{item_name}".encode()).hexdigest()[:12]
        category_label = {
            "weapon": "武器",
            "armor": "护甲",
            "shield": "盾牌",
            "adventuring_gear": "冒险装备",
        }.get(category, "物品")
        result.append(
            {
                "id": f"official:{stable_id}:{suffix}",
                "version": 1,
                "campaign_id": "official",
                "entry_type": entry_type,
                "name": item_name,
                "description": (
                    f"来自《{data.get('source_book') or 'D&D规则资料'}》的官方"
                    f"{category_label}条目。"
                ),
                "source_kind": "official",
                "source_record_id": stable_id,
                "source_name": data.get("source_book"),
                "family_key": None,
                "tags": ["官方", "2024", "原子条目", category],
                "filters_json": {
                    "category": category,
                    "item_function": (
                        _item_function(item_name)
                        if category == "adventuring_gear"
                        else category
                    ),
                    "item_kind": item_kind,
                    "slot": slot,
                    "rarity": "普通",
                    "recommended_level": 1,
                    "atomic_item": True,
                    "edition": data.get("edition"),
                    "source_book": data.get("source_book"),
                },
                "rules_json": {
                    "weight_lb": _weight_lb(weight),
                    "price_cp": _price_cp(price),
                    "canonical_url": data.get("canonical_url"),
                    **rules,
                },
            }
        )

    if name == "武器":
        for row in rows:
            if len(row) < 6 or not re.search(r"\d", row[1]):
                continue
            append_item(
                row[0],
                category="weapon",
                slot="main_hand",
                weight=row[4],
                price=row[5],
                rules={
                    "damage": row[1].split()[0],
                    "damage_type": row[1].split(maxsplit=1)[1] if " " in row[1] else None,
                    "properties": row[2],
                    "mastery": row[3],
                },
            )
    elif name == "护甲":
        armor_category = "armor"
        for row in rows:
            if len(row) < 6:
                continue
            if "轻甲" in row[0]:
                armor_category = "light_armor"
                continue
            if "中甲" in row[0]:
                armor_category = "medium_armor"
                continue
            if "重甲" in row[0]:
                armor_category = "heavy_armor"
                continue
            if "盾牌" in row[0] and not re.search(r"\d", row[1]):
                armor_category = "shield"
                continue
            if not re.search(r"\d", row[1]):
                continue
            row_category = "shield" if "盾牌" in row[0] else armor_category
            append_item(
                row[0],
                category=row_category,
                slot="off_hand" if row_category == "shield" else "armor",
                weight=row[4],
                price=row[5],
                rules={
                    "armor_class": row[1],
                    "strength_requirement": row[2],
                    "stealth": row[3],
                },
            )
    elif name == "冒险装备":
        for row in rows:
            if len(row) != 7:
                continue
            for offset in (0, 4):
                append_item(
                    row[offset],
                    category="adventuring_gear",
                    slot="inventory",
                    weight=row[offset + 1],
                    price=row[offset + 2],
                    rules={},
                )
    return result


def _item_category(data: dict[str, Any], metadata: str) -> str:
    path = " ".join(str(value) for value in data.get("heading_path", []))
    text = f"{path} {metadata}"
    categories = (
        ("护甲", "armor"),
        ("武器", "weapon"),
        ("戒指", "ring"),
        ("权杖", "rod"),
        ("法杖", "staff"),
        ("魔杖", "wand"),
        ("药水", "potion"),
        ("卷轴", "scroll"),
        ("弹药", "ammunition"),
        ("奇物", "wondrous"),
    )
    return next((value for label, value in categories if label in text), "magic_item")


def _item_rarity(data: dict[str, Any], metadata: str) -> str:
    rarities = ("神器", "传说", "极珍稀", "非常稀有", "珍稀", "非普通", "普通")
    record_name = str(data.get("name") or "")
    if record_name in rarities:
        return "极珍稀" if record_name == "非常稀有" else record_name
    metadata_match = re.search(
        r"(?:奇物|护甲|武器|戒指|权杖|法杖|魔杖|药水|卷轴|弹药)"
        r"[^。；]{0,50}?[，,]\s*(神器|传说|极珍稀|非常稀有|珍稀|非普通|普通)",
        metadata,
    )
    if metadata_match:
        rarity = metadata_match.group(1)
        return "极珍稀" if rarity == "非常稀有" else rarity
    return "未标注"


def _item_use_rule(
    *,
    name: str,
    description: str,
    category: str,
    charges: int | None,
) -> dict[str, Any]:
    """Compile only auditable item-use state; prose effects stay DM-routed."""

    action_cost = (
        "bonus_action"
        if "附赠动作" in description
        else "reaction"
        if "反应" in description
        else "action"
        if re.search(r"(?:作为|使用|花费).{0,16}?动作", description)
        else "none"
    )
    charge_cost_match = re.search(r"(?:消耗|花费)\s*(\d+)\s*(?:发)?充能", description)
    charge_cost = int(charge_cost_match.group(1)) if charge_cost_match else 0
    consumes_item = category in {"potion", "scroll"} or bool(
        re.search(r"(?:饮用|服用|消耗)后?(?:该|此)?物品", description)
    )
    recover_match = re.search(
        r"(?:每天|每个黎明|每次长休)[^。；]{0,48}?恢复\s*(\d+)\s*(?:发)?充能",
        description,
    )
    requires_dm_choice = bool(re.search(r"(?:选择|选取|择一|二选一|三选一)", description))
    mode = "charges" if charges is not None else "consumable" if consumes_item else "manual"
    result: dict[str, Any] = {
        "mode": mode,
        "action_cost": action_cost,
        "charge_cost": charge_cost,
        "consumes_item": consumes_item,
        "requires_dm_choice": requires_dm_choice,
        "automation_status": (
            "partial" if mode in {"charges", "consumable"} else "dm_only"
        ),
        "requires_dm_adjudication": True,
        "note": "仅自动改变物品数量/充能；目标、豁免、伤害和叙事后果由 DM 裁定。",
    }
    if charges is not None:
        result["max_charges"] = charges
    if recover_match:
        result["charge_recovery"] = {
            "amount": int(recover_match.group(1)),
            "timing": "long_rest" if "长休" in recover_match.group(0) else "daily",
        }
    result["rule_plan"] = compile_rule_blocks_dict(
        {
            "name": name,
            "description": description[:4_000],
            "action_cost": action_cost,
            "resource_cost": charge_cost,
            "resource_key": "item_charges" if charges is not None else None,
        },
        source_kind="item",
    )
    return result


def _legacy_item_blocks(markdown: str) -> list[tuple[str, str]]:
    """Use rarity metadata lines as boundaries even when legacy bold markup is broken."""

    lines = markdown.splitlines()
    starts: list[tuple[int, int, str]] = []
    metadata_pattern = re.compile(
        r"^\*+.*(?:奇物|护甲|武器|戒指|权杖|法杖|魔杖|药水|卷轴|弹药)"
        r".*(?:神器|传说|非常稀有|稀有|非普通|普通).*\*+\s*$"
    )
    for metadata_index, line in enumerate(lines):
        if not metadata_pattern.match(line.strip()):
            continue
        title_end = metadata_index - 1
        while title_end >= 0 and not lines[title_end].strip():
            title_end -= 1
        if title_end < 0:
            continue
        title_start = title_end
        while title_start > 0 and title_end - title_start < 2 and lines[title_start - 1].strip():
            title_start -= 1
        title_lines = lines[title_start : title_end + 1]
        if not any("**" in value for value in title_lines):
            continue
        raw_title = " ".join(value.strip().strip("*") for value in title_lines)
        starts.append((title_start, metadata_index, raw_title))
    result: list[tuple[str, str]] = []
    for index, (title_start, metadata_index, raw_title) in enumerate(starts):
        del title_start
        end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        result.append((raw_title, "\n".join(lines[metadata_index:end]).strip()))
    return result


def _atomic_item_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    markdown = str(data.get("content_markdown") or "")
    stable_id = str(data["stable_id"])
    blocks: list[tuple[str, str]] = []
    heading_matches = list(re.finditer(r"(?m)^#{4,6}\s+(.+?)\s*$", markdown))
    if heading_matches:
        for index, match in enumerate(heading_matches):
            end = (
                heading_matches[index + 1].start()
                if index + 1 < len(heading_matches)
                else len(markdown)
            )
            blocks.append((match.group(1), markdown[match.end() : end].strip()))
    else:
        blocks = _legacy_item_blocks(markdown)
    if not blocks:
        return []
    result: list[dict[str, Any]] = []
    for position, (raw_name, body) in enumerate(blocks):
        name = _clean_name(_plain_markdown(raw_name))
        description = _plain_markdown(body)
        metadata = description[:180]
        rarity = _item_rarity(data, metadata)
        if (
            not name
            or name in {"神器", "魔法物品", "魔法物品类别"}
            or name.endswith("增益词条")
            or name.endswith("减益词条")
            or rarity == "未标注"
            or len(description) < 10
        ):
            continue
        category = _item_category(data, metadata)
        charge_match = re.search(r"(?:具有|有)\s*(\d+)\s*(?:发)?充能", description)
        attunement_match = re.search(r"需([^（）()，,。]{0,30})同调", metadata)
        rarity_variants = re.findall(
            r"(神器|传说|极珍稀|非常稀有|珍稀|非普通|普通)\s*[（(]([+-]\d+)[）)]",
            metadata,
        )
        variants: list[tuple[str, str, int | None]]
        if name in {"武器", "护甲"} and len(rarity_variants) > 1:
            variants = [
                (
                    f"魔法{name} {bonus}",
                    "极珍稀" if variant_rarity == "非常稀有" else variant_rarity,
                    int(bonus),
                )
                for variant_rarity, bonus in rarity_variants
            ]
        else:
            variants = [(name, rarity, None)]
        for variant_name, variant_rarity, magic_bonus in variants:
            charges = int(charge_match.group(1)) if charge_match else None
            item_use = _item_use_rule(
                name=variant_name,
                description=description,
                category=category,
                charges=charges,
            )
            suffix = hashlib.sha256(f"{stable_id}|{variant_name}|{position}".encode()).hexdigest()[
                :12
            ]
            result.append(
                {
                    "id": f"official:{stable_id}:{suffix}",
                    "version": 1,
                    "campaign_id": "official",
                    "entry_type": "equipment",
                    "name": variant_name,
                    "description": description[:1600],
                    "source_kind": "official",
                    "source_record_id": stable_id,
                    "source_name": data.get("source_book"),
                    "family_key": None,
                    "tags": [
                        "官方",
                        str(data.get("edition") or "未知版本"),
                        variant_rarity,
                        category,
                    ],
                    "filters_json": {
                        "content_type": "items",
                        "edition": data.get("edition"),
                        "source_book": data.get("source_book"),
                        "category": category,
                        "item_kind": (
                            "magic_consumable"
                            if category in {"potion", "scroll"}
                            else "magic_equipment"
                        ),
                        "rarity": variant_rarity,
                        "attunement": "需同调" if "同调" in metadata else "无需同调",
                        "attunement_classes": (
                            attunement_match.group(1).strip() if attunement_match else ""
                        ),
                        "atomic_item": True,
                        "item_use_mode": item_use["mode"],
                        "automation_status": item_use["automation_status"],
                    },
                    "rules_json": {
                        "canonical_url": data.get("canonical_url"),
                        "source_relative_path": data.get("source_relative_path"),
                        "charges": charges,
                        "attunement": "同调" in metadata,
                        "magic_bonus": magic_bonus,
                        "item_use": item_use,
                        "rule_plan": item_use["rule_plan"],
                    },
                }
            )
    return result


@lru_cache(maxsize=4)
def _load_catalog(root_value: str) -> tuple[dict[str, Any], ...]:
    root = Path(root_value)
    entries: list[dict[str, Any]] = []
    if not root.exists():
        return ()
    # ``unknown`` is intentionally read only for registered content packs.
    # Bigby's and the Book of Many Things contain real stat blocks there, while
    # arbitrary unknown corpus records must remain out of the official catalogue.
    for directory_name in (*CONTENT_ENTRY_TYPES, "unknown"):
        directory = root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            content_pack = content_pack_for_record(data)
            effective_type = _content_pack_effective_type(data, content_pack)
            is_official = data.get("officiality") == "official"
            if not is_official and content_pack is None:
                continue
            if effective_type == "monsters":
                atomic_monsters = _atomic_monster_entries(data)
                if atomic_monsters:
                    entries.extend(
                        _decorate_content_pack_entry(
                            entry,
                            data=data,
                            pack=content_pack,
                            content_type=effective_type,
                        )
                        for entry in atomic_monsters
                    )
                    continue
            if effective_type == "equipment" and is_official:
                atomic_equipment = (
                    _atomic_equipment_entries(data) if data.get("edition") == "2024" else []
                )
                entries.extend(atomic_equipment)
                continue
            if effective_type == "items":
                atomic_items = _atomic_item_entries(data)
                if atomic_items:
                    entries.extend(
                        _decorate_content_pack_entry(
                            entry,
                            data=data,
                            pack=content_pack,
                            content_type=effective_type,
                        )
                        for entry in atomic_items
                    )
                else:
                    # A recognised item section without an atomic boundary is
                    # still useful source material, but must not masquerade as
                    # an instance the table can consume.
                    reference = _record_entry(
                        data,
                        content_type="rules",
                        content_pack=content_pack,
                    )
                    if reference is not None:
                        entries.append(
                            _decorate_content_pack_entry(
                                reference,
                                data=data,
                                pack=content_pack,
                                content_type="rules",
                            )
                        )
                continue
            entry = _record_entry(
                data,
                content_type=effective_type,
                content_pack=content_pack,
            )
            if entry is not None:
                entries.append(
                    _decorate_content_pack_entry(
                        entry,
                        data=data,
                        pack=content_pack,
                        content_type=effective_type,
                    )
                )
    return tuple(entries)


class OfficialCompendiumCatalog:
    """Read-only atom view over the already-ingested local D&D rule corpus."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def entries(self) -> tuple[dict[str, Any], ...]:
        return _load_catalog(str(self.root.resolve()))

    @staticmethod
    def _is_enabled_for_campaign(
        entry: dict[str, Any],
        enabled_content_packs: object,
        *,
        allow_legacy: bool = False,
    ) -> bool:
        pack_key = str(dict(entry.get("filters_json") or {}).get("content_pack_key") or "")
        selected = set(
            validate_content_pack_compatibility(
                enabled_content_packs,
                allow_legacy=allow_legacy,
            )
        )
        if pack_key:
            return pack_key in selected
        edition = str(dict(entry.get("filters_json") or {}).get("edition") or "")
        return edition in CURRENT_EDITIONS or allow_legacy

    def get(
        self,
        entry_id: str,
        *,
        enabled_content_packs: object = (),
        allow_legacy: bool = False,
    ) -> dict[str, Any] | None:
        return next(
            (
                entry
                for entry in self.entries
                if entry["id"] == entry_id
                and self._is_enabled_for_campaign(
                    entry,
                    enabled_content_packs,
                    allow_legacy=allow_legacy,
                )
            ),
            None,
        )

    def search(
        self,
        *,
        entry_type: str | None = None,
        text: str = "",
        filters: dict[str, str] | None = None,
        enabled_content_packs: object = (),
        allow_legacy: bool = False,
    ) -> list[dict[str, Any]]:
        query = text.strip().lower()
        return [
            entry
            for entry in self.entries
            if (not entry_type or entry["entry_type"] == entry_type)
            and self._is_enabled_for_campaign(
                entry,
                enabled_content_packs,
                allow_legacy=allow_legacy,
            )
            and (
                not query
                or query
                in " ".join(
                    [
                        str(entry["name"]),
                        str(entry.get("source_name") or ""),
                        " ".join(str(tag) for tag in entry.get("tags", [])),
                    ]
                ).lower()
            )
            and self.matches_filters(entry, filters or {})
        ]

    @staticmethod
    def matches_filters(entry: dict[str, Any], filters: dict[str, str]) -> bool:
        values = dict(entry.get("filters_json") or {})
        for key, expected in filters.items():
            if not expected:
                continue
            if key == "class_name":
                classes = values.get("classes", [])
                if isinstance(classes, list) and expected in {str(item) for item in classes}:
                    continue
                if expected not in str(values.get("class_name") or "").split("、"):
                    return False
                continue
            actual = values.get(key)
            if isinstance(actual, list):
                if expected not in {str(item) for item in actual}:
                    return False
            elif str(actual if actual is not None else "") != expected:
                return False
        return True

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            key = str(entry["entry_type"])
            counts[key] = counts.get(key, 0) + 1
        return counts

    def content_packs(self) -> tuple[dict[str, Any], ...]:
        """Add locally parsed entry counts to the stable content-pack registry."""

        result: list[dict[str, Any]] = []
        for pack in list_content_packs():
            key = str(pack["key"])
            matching = [
                entry
                for entry in self.entries
                if dict(entry.get("filters_json") or {}).get("content_pack_key") == key
            ]
            counts: dict[str, int] = {}
            status_counts = {
                "imported": 0,
                "needs_normalization": 0,
                "structured_reference": 0,
                "dm_choice": 0,
                "directory": 0,
            }
            for entry in matching:
                entry_type = str(entry.get("entry_type") or "unknown")
                counts[entry_type] = counts.get(entry_type, 0) + 1
                status_value = str(
                    dict(entry.get("filters_json") or {}).get("content_pack_status") or ""
                )
                if status_value in status_counts:
                    status_counts[status_value] += 1
            result.append(
                {
                    **pack,
                    "available_entries": len(matching),
                    "entry_counts": counts,
                    "status_counts": status_counts,
                }
            )
        return tuple(result)
