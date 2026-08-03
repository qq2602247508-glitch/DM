from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_ABILITY_KEYS = {
    "力量": "strength",
    "敏捷": "dexterity",
    "体质": "constitution",
    "智力": "intelligence",
    "感知": "wisdom",
    "魅力": "charisma",
}
_ABILITY_LABELS = tuple(_ABILITY_KEYS)
_DAMAGE_TYPES = (
    "强酸",
    "酸蚀",
    "钝击",
    "寒冷",
    "火焰",
    "力场",
    "闪电",
    "暗蚀",
    "黯蚀",
    "穿刺",
    "毒素",
    "心灵",
    "光耀",
    "挥砍",
    "雷鸣",
)
_CHINESE_NUMBERS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_DICE = re.compile(
    r"(?<![A-Za-z0-9_])((?:\d+)?d\d+(?:\s*[+-]\s*(?:\d+|力量|敏捷|体质|智力|感知|魅力))*)",
    re.IGNORECASE,
)
_DAMAGE_TYPE_PATTERN = "|".join(
    re.escape(value) for value in sorted(_DAMAGE_TYPES, key=len, reverse=True)
)
_DAMAGE_COMPONENT = re.compile(
    rf"(?P<expression>(?:\d+)?d\d+(?:\s*[+-]\s*(?:\d+|力量|敏捷|体质|智力|感知|魅力))*|[1-9]\d{{0,3}})"
    rf"(?:\s*(?:[+-]|加)\s*(?:你(?:的)?)?施法属性调整值(?:总和)?(?:的)?)?"
    rf"\s*点?\s*(?P<damage_type>{_DAMAGE_TYPE_PATTERN})\s*伤害",
    re.IGNORECASE,
)
_CONDITION_PATTERNS = {
    "倒地": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*倒地",
    "失能": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*失能",
    "受惊": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*受惊",
    "恐慌": r"(?:陷入|变为|处于|使[^。；]{0,20}|对[^。；]{0,20})\s*恐慌",
    "束缚": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*束缚",
    "擒抱": r"(?:陷入|变为|处于|被|使[^。；]{0,20})\s*擒抱",
    "隐形": r"(?:获得|变为|处于|进入|使[^。；]{0,20})\s*隐形",
    "中毒": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*中毒",
    "目盲": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*目盲",
    "耳聋": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*耳聋",
    "魅惑": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*魅惑",
    "麻痹": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*麻痹",
    "石化": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*石化",
    "震慑": r"(?:陷入|变为|处于|使[^。；]{0,20})\s*震慑",
    "发光": r"(?:发出光|被光线勾勒|发光|轮廓清晰)",
}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _number(value: str) -> int | None:
    value = value.strip()
    if value.isdigit():
        return int(value)
    return _CHINESE_NUMBERS.get(value)


def _spell_body(record: Mapping[str, Any]) -> str:
    """Return only this spell's description, not the rest of a source page.

    The generated corpus contains both atomic spell pages and legacy index pages.
    Atomic pages expose a markdown heading for the spell followed by optional
    stat-block headings.  The flattened plain-text field loses those boundaries
    and can make one spell inherit the next spell's dice, range, or summon text.
    Prefer the matching markdown heading and stop at the next heading, which also
    excludes an appended summoned-creature stat block.  Keep the plain-text
    fallback for records that are not atomic spell pages.
    """
    markdown = str(record.get("content_markdown") or "")
    name = _text(record.get("name"))
    headings = list(re.finditer(r"(?m)^(#{4,6})\s+(.+?)\s*$", markdown))
    if headings and name:
        matching = next(
            (
                heading
                for heading in headings
                if name in re.sub(r"[|｜].*$", "", _text(heading.group(2)))
            ),
            None,
        )
        if matching:
            start = matching.start()
            next_heading = next(
                (heading for heading in headings if heading.start() > start),
                None,
            )
            end = next_heading.start() if next_heading else len(markdown)
            return _text(markdown[start:end])
    return _text(record.get("content_plain_text") or record.get("description"))


def _labeled_value(text: str, *labels: str) -> str | None:
    labels_re = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{labels_re})\s*[:：]\s*(.+?)(?=\s*(?:施法时间|施法距离|射程|法术成分|成分|持续时间)\s*[:：]|$)",
        text,
        re.IGNORECASE,
    )
    return _text(match.group(1)) if match else None


def _area(text: str) -> tuple[str, int] | None:
    patterns = (
        ("cylinder", r"半径\s*(\d+)\s*尺[^。；]{0,12}(?:柱状区域|柱形区域|圆柱)"),
        ("sphere", r"(\d+)\s*尺\s*(?:光环|光环区域|区域|范围)"),
        ("sphere", r"(?:半径\s*)?(\d+)\s*尺\s*(?:半径)?\s*(?:球形|球状|球)") ,
        ("sphere", r"(?:球形|球状|球)\s*(?:区域)?\s*(?:半径\s*)?(\d+)\s*尺"),
        ("cube", r"(\d+)\s*尺\s*(?:立方|方状|方形|正方形)"),
        ("cone", r"(\d+)\s*尺\s*(?:锥形|锥状)"),
        ("line", r"(\d+)\s*尺\s*(?:长的?\s*)?(?:线状|直线)"),
        ("cylinder", r"(\d+)\s*尺\s*(?:圆柱|圆柱形)"),
    )
    for shape, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return shape, int(match.group(1))
    return None


def _delayed_damage_clause(text: str, start: int, end: int) -> bool:
    sentence_start = max(text.rfind("。", 0, start), text.rfind("；", 0, start)) + 1
    sentence_end_candidates = [
        index for index in (text.find("。", end), text.find("；", end)) if index >= 0
    ]
    sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(text)
    clause = text[sentence_start:sentence_end]
    return any(token in clause for token in ("开始其回合", "开始它的回合", "进入", "通过", "燃烧"))


def _damage_components(text: str) -> list[dict[str, str]]:
    """Extract each immediate, explicitly typed damage clause in source order."""

    result: list[dict[str, str]] = []
    for match in _DAMAGE_COMPONENT.finditer(text):
        if _delayed_damage_clause(text, match.start(), match.end()):
            continue
        result.append(
            {
                "expression": re.sub(r"\s+", "", match.group("expression")),
                "damage_type": match.group("damage_type"),
            }
        )
    return result


def _damage(text: str) -> tuple[str | None, str | None]:
    components = _damage_components(text)
    if not components:
        return None, None
    return components[0]["expression"], components[0]["damage_type"]


def _healing(text: str) -> tuple[str, bool] | None:
    for match in _DICE.finditer(text):
        window = text[max(0, match.start() - 100) : min(len(text), match.end() + 80)]
        if any(token in window for token in ("治疗", "恢复生命", "恢复量", "生命值")):
            if "伤害" not in window[max(0, window.find(match.group(1)) - 10) :]:
                return (
                    re.sub(r"\s+", "", match.group(1)),
                    "临时生命" in window,
                )
    fixed_temporary = re.search(r"([1-9]\d{0,3})\s*点?\s*临时生命(?:值)?", text)
    if fixed_temporary:
        return fixed_temporary.group(1), True
    fixed = re.search(r"(?:恢复|治疗|生命值)[^。；]{0,20}?([1-9]\d{0,3})\s*点", text)
    if fixed:
        window = text[max(0, fixed.start() - 80) : min(len(text), fixed.end() + 40)]
        return fixed.group(1), "临时生命" in window
    return None


def _save_ability(text: str) -> str | None:
    match = re.search(rf"({'|'.join(_ABILITY_LABELS)})\s*豁免", text)
    return _ABILITY_KEYS[match.group(1)] if match else None


def _conditions(text: str) -> list[str]:
    return [name for name, pattern in _CONDITION_PATTERNS.items() if re.search(pattern, text)]


def _movement(text: str) -> dict[str, Any] | None:
    patterns = (
        ("away", r"(?:推离|推开|远离)[^。；]{0,20}?(\d+)\s*尺"),
        ("toward", r"(?:拉向|向其移动)[^。；]{0,20}?(\d+)\s*尺"),
        ("push", r"(?:推至|推向)[^。；]{0,20}?(\d+)\s*尺"),
    )
    for direction, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return {"distance_ft": int(match.group(1)), "type": "forced", "direction": direction}
    return None


def _teleport(text: str) -> dict[str, Any] | None:
    """Extract only explicit destination semantics from a teleport spell."""

    if "传送" not in text and "瞬移" not in text:
        return None
    if not any(token in text for token in ("传送", "瞬移")):
        return None
    if any(token in text for token in ("已知地点", "熟悉地点", "永久传送门")):
        destination_kind = "known_location"
    elif any(token in text for token in ("传送门", "门的另一侧")):
        destination_kind = "object"
    elif any(token in text for token in ("某个生物", "另一个生物", "目标生物")):
        destination_kind = "creature"
    else:
        destination_kind = "chosen_space"
    range_match = re.search(
        r"(?:距离|范围|半径|不超过|至多)\s*(\d+)\s*(?:尺|英尺|ft\.?)",
        text,
        re.IGNORECASE,
    )
    return {
        "destination_kind": destination_kind,
        "max_distance_ft": int(range_match.group(1)) if range_match else None,
        "requires_destination_choice": True,
        "can_take_creatures": any(token in text for token in ("自愿生物", "携带", "带着")),
    }


def _transformation(text: str) -> dict[str, Any] | None:
    """Expose form-change spells as a choice, without inventing the chosen form."""

    if not any(token in text for token in ("变形", "变身", "形态", "化身")):
        return None
    if not any(token in text for token in ("变成", "变为", "形态", "外貌")):
        return None
    mode = "shapechange" if "变身" in text or "化身" in text else "polymorph"
    if "外貌" in text and "战斗" not in text:
        mode = "disguise"
    return {
        "mode": mode,
        "form_ref": "dm_chosen_form",
        "requires_form_choice": True,
        "reversible": any(token in text for token in ("结束", "恢复", "返回", "终止")),
    }


def _creation(text: str) -> dict[str, Any] | None:
    """Extract explicit creation semantics while leaving template/count as choices."""

    if not any(token in text for token in ("创造", "制造", "生成")):
        return None
    if not any(token in text for token in ("物件", "物品", "物体", "物质", "门", "墙", "地形")):
        return None
    creation_kind = "portal" if "传送门" in text else "terrain" if any(
        token in text for token in ("墙", "地形")
    ) else "item"
    count_match = re.search(r"(?:最多|共|创造)\s*(\d+)\s*(?:个|件|枚)", text)
    return {
        "creation_kind": creation_kind,
        "template_ref": "dm_chosen_template",
        "count": int(count_match.group(1)) if count_match else None,
        "requires_template_choice": True,
    }


def _dispel(text: str) -> dict[str, Any] | None:
    if "驱散" in text:
        return {
            "mode": "dispel",
            "effect_types": ("spell", "magical_effect"),
            "check_required": "高于" in text or "检定" in text,
            "check_dc_source": "法术等级" if "高于" in text else None,
        }
    if "反制法术" in text or "反制一个法术" in text:
        return {
            "mode": "counterspell",
            "effect_types": ("spell",),
            "check_required": "高于" in text or "检定" in text,
            "check_dc_source": "法术等级" if "高于" in text else None,
        }
    return None


def _upcast_increment(
    expressions: list[str],
    base_expression: object,
) -> int | None:
    """Return a homogeneous dice increment that can safely scale one effect block."""

    if len(expressions) != 1:
        return None
    base_match = re.search(r"(?:\d+)?d(\d+)", _text(base_expression), re.IGNORECASE)
    increment_match = re.fullmatch(r"(\d*)d(\d+)", expressions[0], re.IGNORECASE)
    if not base_match or not increment_match or base_match.group(1) != increment_match.group(2):
        return None
    return int(increment_match.group(1) or "1")


def _upcast(
    text: str,
    *,
    damage_expression: object,
    healing_expression: object,
) -> tuple[int | None, int | None]:
    upcast_text = text[text.find("升环") :] if "升环" in text else ""
    if not upcast_text or not re.search(r"每[^。；]{0,50}高\s*(?:一|1)\s*环", upcast_text):
        return None, None
    damage = re.findall(
        r"伤害[^。；，,]{0,40}(?:增加|提高)[^。；，,]{0,20}?((?:\d+)?d\d+)",
        upcast_text,
    )
    healing = re.findall(
        r"(?:治疗|治疗量)[^。；，,]{0,40}(?:增加|提高)[^。；，,]{0,20}?((?:\d+)?d\d+)",
        upcast_text,
    )
    return (
        _upcast_increment(damage, damage_expression),
        _upcast_increment(healing, healing_expression),
    )


def _max_targets(text: str) -> int | None:
    match = re.search(
        r"(?:至多|最多)\s*([零一二两三四五六七八九十\d]+)"
        r"\s*(?:个|名|只|条)?\s*(?:其他)?\s*(?:生物|目标)",
        text,
    )
    return _number(match.group(1)) if match else None


def _target_disposition(text: str) -> str | None:
    if re.search(
        r"(?:目标可以是|目标可为).{0,24}(?:生物|物件).{0,24}"
        r"(?:或|及|和).{0,24}(?:生物|物件)",
        text,
    ):
        return "any"
    if any(token in text for token in ("友方", "盟友", "自愿生物")):
        return "ally"
    if any(token in text for token in ("敌人", "敌方", "敌对生物")):
        return "enemy"
    if "物件" in text and "生物" not in text:
        return "object"
    if "生物" in text:
        return "creature"
    return None


def _secondary_targets(text: str) -> dict[str, int] | None:
    match = re.search(
        r"(?:该|首个|初始)目标\s*(\d+)\s*尺内\s*(?:至多|最多)\s*"
        r"([零一二两三四五六七八九十\d]+)\s*(?:个|名|只|条)?\s*其他目标",
        text,
    )
    count = _number(match.group(2)) if match else None
    if match is None or count is None:
        return None
    return {
        "secondary_range_ft": int(match.group(1)),
        "secondary_max_targets": count,
        "max_targets": count + 1,
    }


def _repeat(text: str) -> dict[str, Any] | None:
    """Extract an explicit recurring timing without guessing its duration.

    This only records the timing phrase.  The combat engine does not yet execute
    recurring rule blocks, so callers must keep the resulting plan manual until
    that executor exists.
    """

    patterns = (
        ("turn_start", r"(?:每(?:个)?|其|该生物的?)回合(?:开始|起始)"),
        ("turn_end", r"(?:每(?:个)?|其|该生物的?)回合(?:结束|末)"),
        ("round_start", r"(?:每(?:个)?|该)轮(?:开始|起始)"),
        ("round_end", r"(?:每(?:个)?|该)轮(?:结束|末)"),
    )
    for timing, pattern in patterns:
        if re.search(pattern, text):
            return {
                "timing": timing,
                "count_expression": "duration",
                "source": "explicit_timing",
            }
    return None


def _summon_fields(name: str, text: str) -> dict[str, Any] | None:
    """Extract a creature/effect summon without treating every "召唤" as a creature.

    Spell pages in the local corpus append the summoned creature's stat block to
    the spell description.  The stat block can contain attacks, saves, and area
    sizes; those are not mechanics of the spell action itself.  Keep the summon
    as a first-class block and let a separately verified companion template carry
    the creature's combat actions.
    """

    if name == "法师之手":
        return {
            "creature_ref": "法师之手（幽灵手）",
            "count": 1,
            "controller": "caster",
            "enters_combat": False,
        }
    if name == "隐形仆役":
        return {
            "creature_ref": "隐形仆役",
            "count": 1,
            "controller": "caster",
            "enters_combat": False,
        }
    if name == "寻获魔宠":
        return {
            "creature_ref": "魔宠（所选形态）",
            "count": 1,
            "controller": "caster",
            "enters_combat": True,
            "initiative_mode": "independent",
        }
    if name == "寻获坐骑":
        return {
            "creature_ref": "异界坐骑",
            "count": 1,
            "controller": "caster",
            "enters_combat": True,
            "initiative_mode": "shared_with_source",
        }
    if name == "寻获高等坐骑":
        return {
            "creature_ref": "高等坐骑（所选形态）",
            "count": 1,
            "controller": "caster",
            "enters_combat": True,
            "initiative_mode": "shared_with_source",
        }
    if name == "高阶恶魔召唤术":
        return {
            "creature_ref": "恶魔（挑战等级5或更低）",
            "count": 1,
            "controller": "caster",
            "enters_combat": True,
            "initiative_mode": "independent",
        }
    if name == "低阶恶魔召唤术":
        return {
            "creature_ref": "恶魔（DM选择种类）",
            "count_expression": "1d6：2/4/8只（按法术表决定；整体共用一次先攻）",
            "controller": "independent",
            "enters_combat": True,
            "initiative_mode": "independent",
        }

    # A creature summon either provides a stat block or explicitly says that it
    # appears in combat.  This excludes portals, webs, weapons, and other area or
    # object effects whose prose merely happens to contain "召唤".
    has_stat_block_reference = bool(
        re.search(
            r"(?:其|这一实体|该生物).{0,30}?使用\s*(?:下文|下面)?\s*(?:的\s*)?.{1,100}?(?:数据|数值)",
            text,
        )
        or re.search(r"(?:魔宠|坐骑).{0,100}(?:生物属性|战斗|先攻)", text)
    )
    has_explicit_initiative = bool(
        re.search(r"在战斗中.{0,80}(?:使用你的先攻|共用你的先攻|先攻)", text)
        or re.search(r"(?:自己的回合|各自的回合|整体视作一组).{0,50}投掷先攻", text)
    )
    if not has_stat_block_reference and not has_explicit_initiative:
        return None
    reference = None
    match = re.search(
        r"(?:其|这一实体|该生物).{0,30}?使用\s*(?:下文|下面)?\s*(?:的\s*)?(.{1,100}?)(?:的数据|的数值)",
        text,
    )
    if match:
        reference = _text(match.group(1)).replace("**", "").strip(" ：:，,")
    if not reference:
        reference = name
    shared_initiative = bool(re.search(r"(?:使用|共用)你的先攻|共用.*?先攻", text))
    result: dict[str, Any] = {
        "creature_ref": reference,
        "count": 1,
        "controller": "caster",
        "enters_combat": True,
        "initiative_mode": "shared_with_source" if shared_initiative else "independent",
    }
    return result


def spell_rule_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    """Derive only explicit mechanics from a normalized spell record.

    This function is deliberately conservative.  It can recover fields that the
    HTML label parser missed, but it never supplies a range, damage die, or DC
    from a spell name or a generic D&D default.
    """

    raw_spell = record.get("spell")
    source = dict(raw_spell) if isinstance(raw_spell, Mapping) else {}
    body = _spell_body(record)
    spell_name = _text(record.get("name"))
    summon = _summon_fields(spell_name, body)
    result: dict[str, Any] = {
        key: value for key, value in source.items() if value not in (None, "")
    }
    if not result.get("casting_time"):
        value = _labeled_value(body, "施法时间")
        if value:
            result["casting_time"] = value
    if not result.get("range"):
        value = _labeled_value(body, "施法距离", "射程")
        if value:
            result["range"] = value
    if not result.get("duration"):
        value = _labeled_value(body, "持续时间")
        if value:
            result["duration"] = value
    area = _area(f"{_text(result.get('range'))} {body}") if summon is None else None
    if area:
        result.setdefault("area_shape", area[0])
        result.setdefault("area_size_ft", area[1])
    if summon is not None:
        # A summon spell's appended creature stat block is not the spell's own
        # damage/save/area.  Remove stale parser output before compiling blocks.
        for key in (
            "damage_expression",
            "damage_type",
            "healing",
            "save",
            "area_shape",
            "area_size_ft",
            "conditions",
            "movement",
            "reaction",
            "half_damage_on_save",
            "max_targets",
            "resolution_kind",
        ):
            # Keep an explicit null so callers that merge the derived fields on
            # top of the raw parser output cannot resurrect stat-block values.
            result[key] = None
        result["summon"] = summon
        result["resolution_kind"] = "narrative" if not summon["enters_combat"] else "summon"
    if summon is None:
        save_ability = result.get("save")
        if not save_ability:
            save_ability = _save_ability(body)
            if save_ability:
                result["save"] = f"{save_ability}豁免"
        elif _save_ability(body) is None:
            # Legacy index pages occasionally attach the next spell's save to
            # this record.  The current spell body is authoritative.
            result["save"] = None
        damage_components = _damage_components(body)
        damage_expression, damage_type = _damage(body)
        healing = _healing(body)
        if healing:
            healing_expression, temporary_hp = healing
            result.pop("damage_expression", None)
            result.pop("damage_type", None)
            result["healing"] = healing_expression
            if temporary_hp:
                result["temporary_hp"] = True
            result["resolution_kind"] = "heal"
        elif damage_expression:
            result["damage_expression"] = damage_expression
            if damage_type:
                result["damage_type"] = damage_type
            if len(damage_components) > 1:
                result["damage_components"] = damage_components
            result["resolution_kind"] = "damage"
        else:
            # Do not carry a stale damage field from a neighboring spell or an
            # old parser projection into a non-damaging exploration spell.
            result["damage_expression"] = None
            result["damage_type"] = None
            result.pop("damage_components", None)
        conditions = _conditions(body)
        if conditions:
            result["conditions"] = conditions
            result.setdefault("resolution_kind", "control")
        movement = _movement(body)
        if movement:
            result["movement"] = movement
        teleport = _teleport(body)
        if teleport:
            result["teleport"] = teleport
        transformation = _transformation(body)
        if transformation:
            result["transformation"] = transformation
        creation = _creation(body)
        if creation:
            result["creation"] = creation
        dispel = _dispel(body)
        if dispel:
            result["dispel"] = dispel
        if "豁免成功" in body and any(token in body for token in ("减半", "一半", "半伤")):
            result["half_damage_on_save"] = True
        target_disposition = _target_disposition(body)
        if target_disposition:
            result["target_disposition"] = target_disposition
        secondary_targets = _secondary_targets(body)
        if secondary_targets:
            result.update(secondary_targets)
        else:
            max_targets = _max_targets(body)
            if max_targets:
                result["max_targets"] = max_targets
        repeat = _repeat(body)
        if repeat:
            result["repeat"] = repeat
    if "专注" in str(result.get("duration") or "") or "专注" in body:
        result["concentration"] = True
    if summon is None:
        result.pop("upcast_damage_dice", None)
        result.pop("upcast_healing_dice", None)
        upcast_damage, upcast_healing = _upcast(
            body,
            damage_expression=result.get("damage_expression"),
            healing_expression=result.get("healing"),
        )
        if upcast_damage and len(result.get("damage_components") or []) <= 1:
            result["upcast_damage_dice"] = upcast_damage
        if upcast_healing:
            result["upcast_healing_dice"] = upcast_healing
        if "反应" in body and any(
            token in body for token in ("远离", "立即执行其反应", "使用反应")
        ):
            result["reaction"] = {
                "event": "规则描述触发后",
                "timing": "when",
                "effect": "目标按法术原文执行反应；没有明确距离时由 DM 裁定。",
            }
    return result
