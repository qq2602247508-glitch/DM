from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from dnd_dm_assistant.domain.rule_blocks import (
    AreaEffectBlock,
    ChoiceBlock,
    ChoiceOption,
    ConditionBlock,
    CreationBlock,
    DamageBlock,
    DefenseBlock,
    DispelBlock,
    DurationBlock,
    ExplorationEffectBlock,
    HealBlock,
    ModifierBlock,
    MoveBlock,
    NarrativeBlock,
    ObjectStateBlock,
    RepeatBlock,
    ResourceBlock,
    RollBlock,
    RuleBlock,
    RulePlan,
    SaveBlock,
    SpellSlotScaling,
    SummonBlock,
    TargetBlock,
    TeleportBlock,
    TransformationBlock,
    TriggerBlock,
)

_ABILITY_KEYS = {
    "力量": "strength",
    "敏捷": "dexterity",
    "体质": "constitution",
    "智力": "intelligence",
    "感知": "wisdom",
    "魅力": "charisma",
}
_DAMAGE_TYPES = {
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
_DICE = re.compile(
    r"(?<![\w])(\+?\d*d\d+(?:\s*[+-]\s*(?:\d+|力量|敏捷|体质|智力|感知|魅力))*)",
    re.I,
)
_FIXED = re.compile(r"^\s*(\d+)\s*$")
_RANGE = re.compile(r"(\d+)\s*(?:尺|英尺|ft\.?)", re.I)
_LINE_DIMENSIONS = re.compile(
    r"(\d+)\s*(?:尺|英尺|ft\.?)\s*长(?:的)?"
    r"(?:\s*[，、,]\s*(\d+)\s*(?:尺|英尺|ft\.?)\s*宽)?",
    re.I,
)
_LINE_WIDTH = re.compile(r"(?:[，、,]\s*)?(\d+)\s*(?:尺|英尺|ft\.?)\s*宽", re.I)
_TARGET_DISPOSITIONS = {
    "self": "self",
    "自身": "self",
    "自己": "self",
    "ally": "ally",
    "allies": "ally",
    "友方": "ally",
    "盟友": "ally",
    "enemy": "enemy",
    "enemies": "enemy",
    "敌人": "enemy",
    "敌方": "enemy",
    "敌对": "enemy",
    "creature": "creature",
    "creatures": "creature",
    "生物": "creature",
    "object": "object",
    "objects": "object",
    "物件": "object",
    "物体": "object",
    "any": "any",
    "任意": "any",
}
_AREA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "cylinder",
        re.compile(
            r"半径\s*(\d+)\s*(?:尺|英尺|ft\.?)\s*[^。；]{0,12}(?:柱状区域|柱形区域|圆柱)",
            re.I,
        ),
    ),
    ("sphere", re.compile(r"(\d+)\s*(?:尺|英尺|ft\.?)\s*(?:光环|光环区域|区域|范围)", re.I)),
    ("sphere", re.compile(r"(\d+)\s*(?:尺|英尺|ft\.?)\s*(?:半径|radius)", re.I)),
    ("sphere", re.compile(r"(?:半径|radius)\s*(\d+)\s*(?:尺|英尺|ft\.?)", re.I)),
    ("cone", re.compile(r"(\d+)\s*(?:尺|英尺|ft\.?)\s*(?:锥形|锥状|cone)", re.I)),
    (
        "line",
        re.compile(
            r"(\d+)\s*(?:尺|英尺|ft\.?)\s*长(?:的)?"
            r"(?:\s*[，、,]\s*\d+\s*(?:尺|英尺|ft\.?)\s*宽(?:的)?)?"
            r"\s*(?:线状|直线|line)",
            re.I,
        ),
    ),
    ("line", re.compile(r"(\d+)\s*(?:尺|英尺|ft\.?)\s*(?:线状|直线|line)", re.I)),
    ("cube", re.compile(r"(\d+)\s*(?:尺|英尺|ft\.?)\s*(?:立方|cube)", re.I)),
    ("cylinder", re.compile(r"(\d+)\s*(?:尺|英尺|ft\.?)\s*(?:圆柱|cylinder)", re.I)),
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _identifier(index: int, kind: str) -> str:
    return f"b{index:03d}-{kind}"


def _dice_expression(value: object) -> str | None:
    text = _text(value).replace("治疗", "")
    fixed = _FIXED.fullmatch(text)
    if fixed:
        return fixed.group(1)
    match = _DICE.search(text)
    if not match:
        return None
    expression = re.sub(r"\s+", "", match.group(1)).lstrip("+")
    for label, key in _ABILITY_KEYS.items():
        expression = expression.replace(label, f"@{key}")
    return expression


def _damage_type(value: object, damage_text: str) -> str | None:
    explicit = _text(value).lower()
    if explicit:
        return _DAMAGE_TYPES.get(explicit, explicit)
    return next(
        (canonical for label, canonical in _DAMAGE_TYPES.items() if label in damage_text),
        None,
    )


def _target_block(block_id: str, data: Mapping[str, Any], description: str) -> TargetBlock:
    raw_range = _text(data.get("range") or data.get("range_ft"))
    # Imported Chinese stat blocks may separate digits while decoding, e.g.
    # ``1 0 尺宽``.  Normalize only the parser input so geometry extraction
    # cannot capture the trailing zero as a width or area size.
    combined = re.sub(r"(?<=\d)\s+(?=\d)", "", f"{raw_range} {description}")
    range_ft: int | None
    if "自身" in raw_range or raw_range.lower() == "self":
        mode = "self"
        range_ft = 0
    elif any(token in raw_range for token in ("接触", "触碰")) or raw_range.lower() == "touch":
        mode = "single"
        # D&D's Touch range is a rule-defined 5 ft reach, not a generic
        # fallback.  Keep unknown/special ranges as None below.
        range_ft = 5
    else:
        match = _RANGE.search(raw_range)
        if match:
            range_ft = int(match.group(1))
        else:
            mile_match = re.fullmatch(r"\s*(\d+)\s*(?:里|英里|miles?|mi\.?)\s*", raw_range, re.I)
            if mile_match:
                miles = int(mile_match.group(1))
                range_ft = miles * 5_280 if miles * 5_280 <= 10_000 else None
            else:
                range_ft = None
        mode = "single"

    explicit_shape = _text(data.get("area_shape")).lower()
    explicit_size = data.get("area_size_ft")
    shape: str | None = explicit_shape or None
    size_ft = (
        int(explicit_size)
        if isinstance(explicit_size, int) and not isinstance(explicit_size, bool)
        else None
    )
    if shape is None or size_ft is None:
        for candidate, pattern in _AREA_PATTERNS:
            match = pattern.search(combined)
            if match:
                shape = candidate
                size_ft = int(match.group(1))
                break
    if shape is not None and size_ft is not None:
        mode = "area"
    max_targets = data.get("max_targets")
    secondary_max_targets = data.get("secondary_max_targets")
    secondary_range_ft = data.get("secondary_range_ft")
    if (
        isinstance(secondary_max_targets, int)
        and not isinstance(secondary_max_targets, bool)
        and secondary_max_targets > 0
        and not isinstance(max_targets, int)
    ):
        max_targets = secondary_max_targets + 1
    if (
        mode != "area"
        and isinstance(max_targets, int)
        and not isinstance(max_targets, bool)
        and max_targets > 1
    ):
        mode = "multiple"
    explicit_width = data.get("line_width_ft", data.get("width_ft"))
    width_ft = (
        int(explicit_width)
        if isinstance(explicit_width, int) and not isinstance(explicit_width, bool)
        else None
    )
    explicit_height = data.get("area_height_ft", data.get("height_ft"))
    height_ft = (
        int(explicit_height)
        if isinstance(explicit_height, int)
        and not isinstance(explicit_height, bool)
        and explicit_height > 0
        else None
    )
    raw_anchor_height = data.get("area_anchor_height_ft", data.get("anchor_height_ft", 0))
    if not isinstance(raw_anchor_height, int) or isinstance(raw_anchor_height, bool):
        raise ValueError("area_anchor_height_ft must be an integer")
    requires_explicit_elevation = data.get("requires_explicit_elevation", False)
    if not isinstance(requires_explicit_elevation, bool):
        raise ValueError("requires_explicit_elevation must be a boolean")
    if shape == "line" and width_ft is None:
        line = _LINE_DIMENSIONS.search(combined)
        if line and line.group(2):
            width_ft = int(line.group(2))
        else:
            width = _LINE_WIDTH.search(combined)
            if width:
                width_ft = int(width.group(1))
    raw_disposition = _text(data.get("target_disposition")).lower()
    if raw_disposition and raw_disposition not in _TARGET_DISPOSITIONS:
        raise ValueError("target_disposition is not a supported target category")
    requires_line_of_sight = data.get("requires_line_of_sight", True)
    if not isinstance(requires_line_of_sight, bool):
        raise ValueError("requires_line_of_sight must be a boolean")
    return TargetBlock(
        id=block_id,
        mode=mode,  # type: ignore[arg-type]
        disposition=(
            "self" if mode == "self" else _TARGET_DISPOSITIONS.get(raw_disposition, "any")
        ),  # type: ignore[arg-type]
        range_ft=range_ft,
        max_targets=(
            int(max_targets)
            if (
                isinstance(max_targets, int)
                and not isinstance(max_targets, bool)
                and max_targets > 0
            )
            else None
        ),
        shape=shape,  # type: ignore[arg-type]
        size_ft=size_ft,
        width_ft=width_ft,
        height_ft=height_ft,
        anchor_height_ft=raw_anchor_height,
        requires_explicit_elevation=requires_explicit_elevation,
        secondary_range_ft=(
            int(secondary_range_ft)
            if (
                isinstance(secondary_range_ft, int)
                and not isinstance(secondary_range_ft, bool)
                and secondary_range_ft > 0
            )
            else None
        ),
        secondary_max_targets=(
            int(secondary_max_targets)
            if (
                isinstance(secondary_max_targets, int)
                and not isinstance(secondary_max_targets, bool)
                and secondary_max_targets > 0
            )
            else None
        ),
        requires_line_of_sight=requires_line_of_sight,
    )


def _duration(block_id: str, raw: object, concentration: bool) -> DurationBlock | None:
    text = _text(raw)
    lowered = text.lower()
    if not text and not concentration:
        return None
    if not text or "专注" in text or "concentration" in lowered:
        return DurationBlock(
            id=block_id,
            unit="until_removed",
            concentration=concentration or "专注" in text or "concentration" in lowered,
        )
    if any(token in text for token in ("立即", "瞬间")) or "instant" in lowered:
        return DurationBlock(id=block_id, unit="instant", concentration=False)
    units = (
        ("round", ("轮", "round")),
        ("minute", ("分钟", "minute")),
        ("hour", ("小时", "hour")),
        ("day", ("天", "day")),
    )
    number = re.search(r"(\d+)", text)
    for unit, tokens in units:
        if any(token in lowered for token in tokens):
            if number:
                return DurationBlock(
                    id=block_id,
                    unit=unit,  # type: ignore[arg-type]
                    value=int(number.group(1)),
                    concentration=concentration,
                )
            return None
    return DurationBlock(id=block_id, unit="until_removed", concentration=concentration)


def _add_named_effects(
    name: str,
    description: str,
    target: TargetBlock,
    duration: DurationBlock | None,
    add: Any,
) -> int:
    """Compile conservative, well-known named effects missing from table fields.

    These are not name-based guesses of numbers: every value below is a fixed
    rule value from the corresponding spell text, and only effects with a
    deterministic executor are included.  The caller still keeps complex prose
    as DM adjudication.
    """

    count = 0

    def modifier(
        stat: str,
        operation: str,
        *,
        value: int | None = None,
        expression: str | None = None,
        scope: str = "all",
        skill: str | None = None,
        source: str | None = None,
    ) -> None:
        nonlocal count
        add(
            ModifierBlock(
                id=_identifier(100 + count, "modifier"),
                stat=stat,  # type: ignore[arg-type]
                operation=operation,  # type: ignore[arg-type]
                value=value,
                expression=expression,
                scope=scope,  # type: ignore[arg-type]
                skill=skill,
                source=source,
                target_block_id=target.id,
                duration_block_id=duration.id if duration else None,
            )
        )
        count += 1

    def condition(value: str) -> None:
        nonlocal count
        add(
            ConditionBlock(
                id=_identifier(100 + count, "condition"),
                operation="apply",
                condition=value,
                target_block_id=target.id,
                duration_block_id=duration.id if duration else None,
            )
        )
        count += 1

    def defense(operation: str, types: tuple[str, ...]) -> None:
        nonlocal count
        add(
            DefenseBlock(
                id=_identifier(100 + count, "defense"),
                operation=operation,  # type: ignore[arg-type]
                damage_types=types,
            )
        )
        count += 1

    def exploration(
        operation: str,
        *,
        radius_ft: int | None = None,
        details: str | None = None,
        adjudication: bool = False,
    ) -> None:
        nonlocal count
        add(
            ExplorationEffectBlock(
                id=_identifier(100 + count, "exploration"),
                operation=operation,  # type: ignore[arg-type]
                target_block_id=target.id,
                duration_block_id=duration.id if duration else None,
                radius_ft=radius_ft,
                details=details,
                requires_dm_adjudication=adjudication,
            )
        )
        count += 1

    def object_state(
        state: str,
        object_types: tuple[str, ...],
        *,
        adjudication: bool = False,
    ) -> None:
        nonlocal count
        add(
            ObjectStateBlock(
                id=_identifier(100 + count, "object-state"),
                operation="set",
                state=state,  # type: ignore[arg-type]
                target_block_id=target.id,
                object_types=object_types,
                requires_dm_adjudication=adjudication,
            )
        )
        count += 1

    # Combat: persistent modifiers and defenses with unambiguous values.
    if name == "树肤术":
        modifier("armor_class", "set", value=17, source="AC低于17时变为17")
    elif name in {"大步奔行", "长腿奔行"}:
        modifier("speed_ft", "add", value=10, source="速度+10尺")
    elif name == "加速术":
        modifier("speed_ft", "add", value=20, source="速度+20尺")
        modifier("saving_throw", "advantage", source="敏捷豁免具有优势")
        modifier("action", "grant", source="额外动作：仅限攻击一次、疾走、撤离、躲藏或使用物件")
    elif name == "石肤术":
        defense("resistance", ("bludgeoning", "piercing", "slashing"))
    elif name == "行动无踪":
        modifier("skill_check", "add", value=10, skill="隐匿", source="隐匿检定+10")
    elif name == "护盾术":
        modifier("armor_class", "add", value=5, scope="incoming", source="触发攻击前AC+5")
    elif name == "防护毒素":
        defense("resistance", ("poison",))
        modifier("saving_throw", "advantage", source="对抗中毒的豁免具有优势")
    elif name == "剑刃防护":
        defense("resistance", ("bludgeoning", "piercing", "slashing"))
    elif name == "朦胧术":
        modifier(
            "attack_roll",
            "disadvantage",
            scope="incoming",
            source="对目标发动的攻击检定具有劣势",
        )
    elif name == "高等隐形术" and "具有隐形状态" in description:
        condition("隐形")
    elif name == "妖火" and "10尺半径的微光" in description:
        condition("发光")
    elif name == "油腻术" and "失足倒地" in description:
        condition("倒地")
    elif name == "英雄气概":
        condition("恐慌免疫")
    elif name == "低等复原术":
        condition("移除：目盲/耳聋/麻痹/中毒（选择一项）")
    elif name == "次等复原术":
        condition("移除：目盲/耳聋/麻痹/中毒（选择一项）")
    # PR/exploration: deterministic scene queries and object transitions.
    elif name in {"光亮术", "不灭明焰"}:
        exploration(
            "light",
            radius_ft=40,
            details="明亮光照20尺，外加微光光照20尺；施法者选择颜色。",
        )
    elif name == "昼明术":
        exploration(
            "light",
            radius_ft=120,
            details="明亮光照60尺，外加微光光照60尺；可附着于物件。",
        )
    elif name == "黑暗术":
        exploration("darkness", radius_ft=15, details="半径15尺的魔法黑暗区域。")
    elif name == "舞光术":
        exploration("light", radius_ft=20, details="最多四个光源，每个明亮10尺、微光10尺。")
    elif name == "侦测魔法":
        exploration("detect_magic", radius_ft=30, details="感测30尺内魔法，并可辨认所属学派。")
    elif name == "寻找陷阱":
        exploration("detect_trap", radius_ft=120, details="感测视线范围内的陷阱，不直接解除。")
    elif name in {"物件定位术", "生物定位术", "动植物定位术"}:
        exploration("locate", details="回传最近匹配目标的方向与距离；找不到时返回明确结果。")
    elif name in {"通晓语言", "巧言术"}:
        exploration(
            "grant_language",
            details="目标获得理解/被理解语言的能力，持续时间由法术持续块控制。",
        )
    elif name in {"动物交谈", "植物交谈"}:
        exploration(
            "communicate",
            details="建立与对应生物类别的结构化交流窗口；不自动制造其态度或答案。",
        )
    elif name in {"传讯术", "短讯术", "心灵感应", "拉瑞心灵联结", "动物信使"}:
        exploration(
            "communicate",
            details="建立一条可审计的通信请求；目标是否回应仍由 DM/目标决定。",
        )
    elif name == "敲击术":
        object_state("open", ("door", "container", "treasure", "portal"))
    elif name == "秘法锁":
        object_state("locked", ("door", "container", "treasure"))
    elif name == "修复术":
        object_state("repaired", ("door", "container", "furniture", "portal", "object"))
    elif name in {"造粮术", "造水术", "造水/枯水术", "神莓术"}:
        exploration("create_supply", details="创建/恢复的补给数量按法术原文记录，不从名称推导。")
    return count


def compile_rule_blocks(
    data: Mapping[str, Any],
    *,
    source_kind: str | None = None,
) -> RulePlan:
    """Compile the current spell/action dictionary into deterministic rule blocks.

    This compiler is intentionally conservative: prose can clarify targeting, but it
    never creates damage or healing numbers unless a structured field contains a
    valid dice/fixed expression.
    """

    name = _text(data.get("name"))
    if not name:
        raise ValueError("rule source requires a name")
    inferred_kind = source_kind or ("spell" if "spell_level" in data else "action")
    allowed_kinds = {
        "spell",
        "action",
        "feature",
        "item",
        "monster",
        "monster_action",
        "rule",
        "unknown",
    }
    if inferred_kind not in allowed_kinds:
        raise ValueError("unsupported source_kind")

    raw_spell_level = data.get("spell_level")
    if raw_spell_level is None and inferred_kind == "spell":
        raw_spell_level = data.get("level")
    if raw_spell_level is None:
        spell_level: int | None = None
    elif (
        not isinstance(raw_spell_level, int)
        or isinstance(raw_spell_level, bool)
        or not 0 <= raw_spell_level <= 9
    ):
        raise ValueError("spell_level must be an integer between 0 and 9")
    else:
        spell_level = raw_spell_level
    if inferred_kind != "spell" and spell_level is not None:
        raise ValueError("spell_level is only valid for spell sources")

    blocks: list[RuleBlock] = []
    roots: list[str] = []
    warnings: list[str] = []

    def applies_on(value: object, *, field_name: str) -> str | None:
        if value is None or value == "":
            return None
        normalized = _text(value)
        allowed = {"always", "hit", "miss", "save_success", "save_failure"}
        if normalized not in allowed:
            raise ValueError(f"{field_name} must be one of {', '.join(sorted(allowed))}")
        return normalized

    def damage_tags(value: object, *, field_name: str) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple, set)):
            raise ValueError(f"{field_name} must be a list of strings")
        tags: list[str] = []
        for tag in value:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError(f"{field_name} must contain non-empty strings")
            normalized = tag.strip()
            if normalized not in tags:
                tags.append(normalized)
        return tuple(tags)

    def add(block: RuleBlock, *, root: bool = True) -> None:
        blocks.append(block)
        if root:
            roots.append(block.id)

    description = _text(data.get("description"))
    target = _target_block(_identifier(len(blocks), "target"), data, description)
    add(target)

    resource_key = _text(data.get("resource_key") or data.get("resource"))
    resource_cost = data.get("resource_cost", 1 if resource_key else 0)
    if resource_key:
        if (
            not isinstance(resource_cost, int)
            or isinstance(resource_cost, bool)
            or resource_cost < 0
        ):
            raise ValueError("resource_cost must be a non-negative integer")
        add(
            ResourceBlock(
                id=_identifier(len(blocks), "resource"),
                resource_key=resource_key,
                operation="spend",
                amount=resource_cost,
                minimum_required=resource_cost,
            )
        )

    duration = _duration(
        _identifier(len(blocks), "duration"),
        data.get("duration"),
        bool(data.get("concentration")),
    )
    if duration is not None:
        add(duration)

    save_ability = _text(data.get("save_ability")).removesuffix("豁免")
    save: SaveBlock | None = None
    if save_ability:
        raw_dc = data.get("save_dc")
        if raw_dc is not None and (
            not isinstance(raw_dc, int) or isinstance(raw_dc, bool) or not 0 <= raw_dc <= 100
        ):
            raise ValueError("save_dc must be an integer between 0 and 100")
        save = SaveBlock(
            id=_identifier(len(blocks), "save"),
            ability=_ABILITY_KEYS.get(save_ability, save_ability.lower()),
            dc=raw_dc,
            dc_source=None if raw_dc is not None else "source_spell_save_dc",
            on_success="half" if bool(data.get("half_damage_on_save")) else "none",
            target_block_id=target.id,
        )
        add(save)

    resolution_kind = _text(data.get("resolution_kind")).lower()
    if resolution_kind in {"ability_check", "skill_check"} or data.get("skill"):
        raw_dc = data.get("dc")
        if raw_dc is not None and (
            not isinstance(raw_dc, int) or isinstance(raw_dc, bool) or not 0 <= raw_dc <= 100
        ):
            raise ValueError("dc must be an integer between 0 and 100")
        ability = _text(data.get("ability")) or None
        modifier = data.get("modifier")
        if modifier is not None and (
            not isinstance(modifier, int)
            or isinstance(modifier, bool)
            or not -100 <= modifier <= 100
        ):
            raise ValueError("modifier must be an integer between -100 and 100")
        add(
            RollBlock(
                id=_identifier(len(blocks), "roll"),
                roll_type="ability_check",
                ability=ability,
                skill=_text(data.get("skill")) or None,
                modifier=modifier,
                target_defense="dc",
                dc=raw_dc,
                dc_source=None if raw_dc is not None else "dm_chosen_dc",
                target_block_id=target.id,
            )
        )

    raw_damage_components = data.get("damage_components")
    if raw_damage_components is not None and not isinstance(raw_damage_components, (list, tuple)):
        raise ValueError("damage_components must be a list of typed damage components")
    component_sources = (
        list(raw_damage_components) if isinstance(raw_damage_components, (list, tuple)) else []
    )
    raw_damage = data.get("damage_expression") or data.get("damage") or data.get("healing")
    damage_text = _text(raw_damage)
    damage_expression = _dice_expression(raw_damage)
    damage_type = _damage_type(data.get("damage_type"), damage_text)
    top_level_damage_tags = damage_tags(data.get("damage_tags"), field_name="damage_tags")
    damage_components: list[tuple[str, str, bool, str | None, tuple[str, ...]]] = []
    if component_sources:
        for raw_component in component_sources:
            if not isinstance(raw_component, Mapping):
                raise ValueError("each damage component must be an object")
            raw_expression = (
                raw_component.get("expression")
                or raw_component.get("damage_expression")
                or raw_component.get("damage")
            )
            expression = _dice_expression(raw_expression)
            component_type = _damage_type(
                raw_component.get("damage_type"),
                _text(raw_expression),
            )
            shared_roll = raw_component.get("shared_roll", True)
            if not isinstance(shared_roll, bool):
                raise ValueError("damage component shared_roll must be a boolean")
            if expression is None or component_type is None:
                warnings.append("伤害组成字段无法安全编译，已转为DM文字裁定")
                continue
            damage_components.append(
                (
                    expression,
                    component_type,
                    shared_roll,
                    applies_on(
                        raw_component.get("applies_on"),
                        field_name="damage component applies_on",
                    ),
                    damage_tags(
                        raw_component.get("damage_tags"),
                        field_name="damage component damage_tags",
                    ),
                )
            )
    elif damage_expression is not None and damage_type is not None:
        damage_components.append(
            (
                damage_expression,
                damage_type,
                bool(data.get("shared_damage_roll", True)),
                applies_on(data.get("damage_applies_on"), field_name="damage_applies_on"),
                top_level_damage_tags,
            )
        )
    raw_upcast_damage = data.get("upcast_damage_dice")
    raw_upcast_healing = data.get("upcast_healing_dice")
    for key, value in (
        ("upcast_damage_dice", raw_upcast_damage),
        ("upcast_healing_dice", raw_upcast_healing),
    ):
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100
        ):
            raise ValueError(f"{key} must be an integer between 1 and 100")
    if (raw_upcast_damage is not None or raw_upcast_healing is not None) and (
        inferred_kind != "spell" or spell_level is None or spell_level <= 0
    ):
        warnings.append("升环增量缺少明确的基础法术环阶，未绑定效果积木")

    def spell_slot_scaling(raw_increment: object) -> SpellSlotScaling | None:
        if (
            isinstance(raw_increment, int)
            and not isinstance(raw_increment, bool)
            and spell_level is not None
            and spell_level > 0
        ):
            return SpellSlotScaling(
                base_spell_level=spell_level,
                dice_per_level=raw_increment,
            )
        return None

    is_healing = (
        bool(data.get("healing"))
        or resolution_kind in {"heal", "healing"}
        or damage_text.startswith("治疗")
    )
    if is_healing and damage_expression:
        add(
            HealBlock(
                id=_identifier(len(blocks), "heal"),
                expression=damage_expression,
                temporary_hp=bool(data.get("temporary_hp")),
                target_block_id=target.id,
                spell_slot_scaling=spell_slot_scaling(raw_upcast_healing),
            )
        )
    elif damage_components and resolution_kind != "narrative":
        attack_roll: RollBlock | None = None
        if save is None:
            attack_bonus = data.get("attack_bonus")
            if attack_bonus is not None and (
                not isinstance(attack_bonus, int)
                or isinstance(attack_bonus, bool)
                or not -100 <= attack_bonus <= 100
            ):
                raise ValueError("attack_bonus must be an integer between -100 and 100")
            attack_roll = RollBlock(
                id=_identifier(len(blocks), "roll"),
                roll_type="attack",
                ability=None,
                modifier=attack_bonus,
                target_defense="ac",
                target_block_id=target.id,
            )
            add(attack_roll)
        if raw_upcast_damage is not None and len(damage_components) != 1:
            warnings.append("升环伤害增量对应多个伤害组成，未自动绑定")
        for (
            expression,
            component_type,
            shared_roll,
            explicit_applies_on,
            component_damage_tags,
        ) in damage_components:
            add(
                DamageBlock(
                    id=_identifier(len(blocks), "damage"),
                    expression=expression,
                    damage_type=component_type,
                    damage_tags=list(component_damage_tags),
                    applies_on=(
                        explicit_applies_on
                        or ("save_failure" if save else "hit" if attack_roll else "always")
                    ),
                    shared_roll=shared_roll,
                    save_block_id=save.id if save else None,
                    target_block_id=target.id,
                    spell_slot_scaling=(
                        spell_slot_scaling(raw_upcast_damage)
                        if len(damage_components) == 1
                        else None
                    ),
                )
            )
    elif (raw_damage or component_sources) and resolution_kind != "narrative":
        warnings.append("伤害字段无法安全编译，已转为DM文字裁定")
    elif resolution_kind == "damage":
        warnings.append("标记为伤害规则但缺少可验证伤害骰，未生成伤害积木")
    if raw_upcast_damage is not None and not any(block.kind == "damage" for block in blocks):
        warnings.append("升环伤害增量缺少可绑定的伤害积木")
    if raw_upcast_healing is not None and not any(block.kind == "heal" for block in blocks):
        warnings.append("升环治疗增量缺少可绑定的治疗积木")

    for operation, key in (
        ("resistance", "damage_resistances"),
        ("vulnerability", "damage_vulnerabilities"),
        ("immunity", "damage_immunities"),
    ):
        raw_types = data.get(key) or ()
        if isinstance(raw_types, str):
            raw_types = re.split(r"[,，、/；;\s]+", raw_types)
        types = (
            tuple(_text(value) for value in raw_types if _text(value))
            if isinstance(raw_types, (list, tuple, set))
            else ()
        )
        if types:
            add(
                DefenseBlock(
                    id=_identifier(len(blocks), "defense"),
                    operation=operation,  # type: ignore[arg-type]
                    damage_types=types,
                )
            )

    raw_conditional_defenses = data.get("conditional_defenses") or ()
    if isinstance(raw_conditional_defenses, Mapping):
        raw_conditional_defenses = (raw_conditional_defenses,)
    if not isinstance(raw_conditional_defenses, (list, tuple)):
        raise ValueError("conditional_defenses must be a list of explicit defenses")
    for raw_defense in raw_conditional_defenses:
        if not isinstance(raw_defense, Mapping):
            raise ValueError("each conditional defense must be an object")
        raw_types = raw_defense.get("damage_types") or ()
        if isinstance(raw_types, str):
            raw_types = tuple(filter(None, re.split(r"[,，、/；;\s]+", raw_types)))
        if not isinstance(raw_types, (list, tuple, set)):
            raise ValueError("conditional defense damage_types must be a list")
        types = tuple(_text(value) for value in raw_types if _text(value))
        condition = _text(raw_defense.get("condition"))
        if not types or not condition:
            raise ValueError(
                "conditional defenses require explicit damage_types and an activation condition"
            )
        add(
            DefenseBlock(
                id=_identifier(len(blocks), "defense"),
                operation=_text(raw_defense.get("operation")),  # type: ignore[arg-type]
                damage_types=types,
                condition=condition,
                applies_on=applies_on(
                    raw_defense.get("applies_on"),
                    field_name="conditional defense applies_on",
                ),
            )
        )

    raw_modifiers = data.get("modifiers") or ()
    if isinstance(raw_modifiers, Mapping):
        raw_modifiers = (raw_modifiers,)
    if not isinstance(raw_modifiers, (list, tuple)):
        raise ValueError("modifiers must be a list of explicit modifier objects")
    for raw_modifier in raw_modifiers:
        if not isinstance(raw_modifier, Mapping):
            raise ValueError("each modifier must be an object")
        value = raw_modifier.get("value")
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError("modifier.value must be an integer")
        expression = _text(raw_modifier.get("expression")) or None
        add(
            ModifierBlock(
                id=_identifier(len(blocks), "modifier"),
                stat=_text(raw_modifier.get("stat")),  # type: ignore[arg-type]
                operation=_text(raw_modifier.get("operation")),  # type: ignore[arg-type]
                value=value,
                expression=expression,
                scope=_text(raw_modifier.get("scope") or "all"),  # type: ignore[arg-type]
                skill=_text(raw_modifier.get("skill")) or None,
                target_block_id=target.id,
                duration_block_id=duration.id if duration else None,
                source=_text(raw_modifier.get("source")) or None,
                applies_on=applies_on(
                    raw_modifier.get("applies_on"), field_name="modifier applies_on"
                ),
            )
        )

    raw_conditions = data.get("conditions") or ()
    if isinstance(raw_conditions, str):
        raw_conditions = (raw_conditions,)
    for raw_condition in raw_conditions:
        if isinstance(raw_condition, str) and raw_condition.strip():
            add(
                ConditionBlock(
                    id=_identifier(len(blocks), "condition"),
                    operation="apply",
                    condition=raw_condition.strip(),
                    target_block_id=target.id,
                    duration_block_id=duration.id if duration else None,
                )
            )
        elif isinstance(raw_condition, Mapping):
            condition = _text(raw_condition.get("condition"))
            if not condition:
                raise ValueError("structured conditions require a condition value")
            add(
                ConditionBlock(
                    id=_identifier(len(blocks), "condition"),
                    operation=_text(raw_condition.get("operation") or "apply"),  # type: ignore[arg-type]
                    condition=condition,
                    target_block_id=target.id,
                    duration_block_id=duration.id if duration else None,
                    save_ends=bool(raw_condition.get("save_ends", False)),
                    applies_on=applies_on(
                        raw_condition.get("applies_on"), field_name="condition applies_on"
                    ),
                )
            )
        else:
            raise ValueError("each condition must be a string or an explicit condition object")

    movement = data.get("movement")
    if isinstance(movement, Mapping):
        distance = movement.get("distance_ft")
        if not isinstance(distance, int) or isinstance(distance, bool):
            raise ValueError("movement.distance_ft must be an integer")
        add(
            MoveBlock(
                id=_identifier(len(blocks), "move"),
                distance_ft=distance,
                movement_type=_text(movement.get("type") or "forced"),  # type: ignore[arg-type]
                direction=_text(movement.get("direction") or "chosen"),  # type: ignore[arg-type]
                target_block_id=target.id,
                applies_on=applies_on(movement.get("applies_on"), field_name="movement applies_on"),
            )
        )

    teleport = data.get("teleport")
    if isinstance(teleport, Mapping):
        destination_kind = _text(teleport.get("destination_kind") or "chosen_space")
        max_distance = teleport.get("max_distance_ft")
        if max_distance is not None and (
            not isinstance(max_distance, int) or isinstance(max_distance, bool) or max_distance < 0
        ):
            raise ValueError("teleport.max_distance_ft must be a non-negative integer")
        add(
            TeleportBlock(
                id=_identifier(len(blocks), "teleport"),
                destination_kind=destination_kind,  # type: ignore[arg-type]
                max_distance_ft=max_distance,
                destination_ref=_text(teleport.get("destination_ref")) or None,
                target_block_id=target.id,
                can_take_creatures=bool(teleport.get("can_take_creatures")),
                requires_destination_choice=bool(teleport.get("requires_destination_choice", True)),
            )
        )

    transformation = data.get("transformation")
    if isinstance(transformation, Mapping):
        form_ref = _text(transformation.get("form_ref") or "dm_chosen_form")
        if not form_ref:
            raise ValueError("transformation.form_ref is required")
        add(
            TransformationBlock(
                id=_identifier(len(blocks), "transformation"),
                mode=_text(transformation.get("mode") or "polymorph"),  # type: ignore[arg-type]
                form_ref=form_ref,
                target_block_id=target.id,
                preserve_personality=bool(transformation.get("preserve_personality", True)),
                reversible=bool(transformation.get("reversible", True)),
                requires_form_choice=bool(transformation.get("requires_form_choice", True)),
            )
        )

    creation = data.get("creation")
    if isinstance(creation, Mapping):
        template_ref = _text(creation.get("template_ref") or creation.get("object_ref"))
        if not template_ref:
            raise ValueError("creation.template_ref is required")
        count = creation.get("count")
        if count is not None and (
            not isinstance(count, int) or isinstance(count, bool) or count < 1
        ):
            raise ValueError("creation.count must be a positive integer")
        count_expression = _text(creation.get("count_expression")) or None
        if count is not None and count_expression is not None:
            raise ValueError("creation.count and creation.count_expression cannot both be explicit")
        add(
            CreationBlock(
                id=_identifier(len(blocks), "creation"),
                creation_kind=_text(creation.get("creation_kind") or "object"),  # type: ignore[arg-type]
                template_ref=template_ref,
                count=count,
                count_expression=count_expression,
                target_block_id=target.id,
                duration_block_id=duration.id if duration else None,
                requires_template_choice=bool(creation.get("requires_template_choice", True)),
            )
        )

    dispel = data.get("dispel")
    if isinstance(dispel, Mapping):
        effect_types = dispel.get("effect_types") or ()
        if isinstance(effect_types, str):
            effect_types = tuple(filter(None, re.split(r"[,，、/；;\s]+", effect_types)))
        if not isinstance(effect_types, (list, tuple, set)):
            raise ValueError("dispel.effect_types must be a list")
        add(
            DispelBlock(
                id=_identifier(len(blocks), "dispel"),
                mode=_text(dispel.get("mode") or "dispel"),  # type: ignore[arg-type]
                target_block_id=target.id,
                effect_types=tuple(_text(value) for value in effect_types if _text(value)),
                check_required=bool(dispel.get("check_required")),
                check_dc_source=_text(dispel.get("check_dc_source")) or None,
            )
        )

    if resolution_kind != "narrative":
        _add_named_effects(
            name,
            description,
            target,
            duration,
            add,
        )

    reaction = data.get("reaction")
    if isinstance(reaction, Mapping):
        reaction_event = _text(reaction.get("event"))
        reaction_effect = _text(reaction.get("effect"))
        if reaction_event and reaction_effect:
            child_id = _identifier(len(blocks) + 1, "reaction-effect")
            child: RuleBlock
            reaction_movement = reaction.get("movement")
            if isinstance(reaction_movement, Mapping):
                distance = reaction_movement.get("distance_ft")
                if not isinstance(distance, int) or isinstance(distance, bool):
                    raise ValueError("reaction.movement.distance_ft must be an integer")
                child = MoveBlock(
                    id=child_id,
                    distance_ft=distance,
                    movement_type=_text(reaction_movement.get("type") or "forced"),  # type: ignore[arg-type]
                    direction=_text(reaction_movement.get("direction") or "away"),  # type: ignore[arg-type]
                    target_block_id=target.id,
                )
            else:
                child = NarrativeBlock(id=child_id, text=reaction_effect)
            add(
                TriggerBlock(
                    id=_identifier(len(blocks), "reaction"),
                    event=reaction_event,
                    timing="when",
                    block_ids=(child_id,),
                    once=False,
                )
            )
            add(child, root=False)

    summon = data.get("summon")
    if isinstance(summon, Mapping):
        count_expression = summon.get("count_expression")
        count = summon.get("count", 1)
        if count_expression is not None:
            if count not in (None, 1):
                raise ValueError("summon.count and summon.count_expression cannot both be explicit")
            count = None
        elif not isinstance(count, int) or isinstance(count, bool):
            raise ValueError("summon.count must be an integer")
        creature_ref = _text(summon.get("creature_ref"))
        if not creature_ref:
            raise ValueError("summon.creature_ref is required")
        controller = _text(summon.get("controller") or "caster")
        enemy_ai_mode = _text(summon.get("enemy_ai_mode")) or (
            "dm_only" if controller == "dm" else "not_applicable"
        )
        add(
            SummonBlock(
                id=_identifier(len(blocks), "summon"),
                creature_ref=creature_ref,
                count=count,
                count_expression=_text(count_expression) if count_expression is not None else None,
                controller=controller,  # type: ignore[arg-type]
                enters_combat=bool(summon.get("enters_combat", True)),
                initiative_mode=_text(
                    summon.get(
                        "initiative_mode",
                        "independent" if summon.get("enters_combat", True) else "not_applicable",
                    )
                ),  # type: ignore[arg-type]
                duration_block_id=duration.id if duration else None,
                template_ref=_text(summon.get("template_ref")) or None,
                requires_template_choice=bool(summon.get("requires_template_choice", True)),
                enemy_ai_mode=enemy_ai_mode,  # type: ignore[arg-type]
            )
        )

    raw_area_effects = data.get("area_effects")
    if raw_area_effects is None and data.get("area_effect") is not None:
        raw_area_effects = (data.get("area_effect"),)
    if raw_area_effects is not None:
        if isinstance(raw_area_effects, Mapping):
            raw_area_effects = (raw_area_effects,)
        if not isinstance(raw_area_effects, (list, tuple)):
            raise ValueError("area_effects must be a list of explicit area objects")
        for raw_area in raw_area_effects:
            if not isinstance(raw_area, Mapping):
                raise ValueError("each area effect must be an object")
            shape = _text(raw_area.get("shape"))
            size_ft = raw_area.get("size_ft")
            width_ft = raw_area.get("width_ft")
            height_ft = raw_area.get("height_ft")
            anchor_height_ft = raw_area.get("anchor_height_ft", 0)
            requires_explicit_elevation = raw_area.get("requires_explicit_elevation", False)
            origin = _text(raw_area.get("origin") or "chosen_point")
            trigger_timing = _text(raw_area.get("trigger_timing"))
            raw_effect_ids = raw_area.get("effect_block_ids")
            if not isinstance(raw_effect_ids, (list, tuple)) or not raw_effect_ids:
                raise ValueError("area effects require explicit effect_block_ids")
            effect_ids = tuple(
                str(value) for value in raw_effect_ids if isinstance(value, str) and value
            )
            if len(effect_ids) != len(raw_effect_ids):
                raise ValueError("area effect_block_ids must be non-empty strings")
            known_blocks = {block.id: block for block in blocks}
            unknown = [block_id for block_id in effect_ids if block_id not in known_blocks]
            if unknown:
                raise ValueError("area effect_block_ids must reference already compiled blocks")
            unsupported_children = [
                block_id
                for block_id in effect_ids
                if known_blocks[block_id].kind
                not in {"damage", "heal", "condition", "modifier", "defense", "move"}
            ]
            if unsupported_children:
                raise ValueError("area effects may only own executable combat-effect blocks")
            if not isinstance(size_ft, int) or isinstance(size_ft, bool) or size_ft <= 0:
                raise ValueError("area_effect.size_ft must be a positive integer")
            if width_ft is not None and (
                not isinstance(width_ft, int) or isinstance(width_ft, bool) or width_ft <= 0
            ):
                raise ValueError("area_effect.width_ft must be a positive integer")
            if height_ft is not None and (
                not isinstance(height_ft, int) or isinstance(height_ft, bool) or height_ft <= 0
            ):
                raise ValueError("area_effect.height_ft must be a positive integer")
            if not isinstance(anchor_height_ft, int) or isinstance(anchor_height_ft, bool):
                raise ValueError("area_effect.anchor_height_ft must be an integer")
            if not isinstance(requires_explicit_elevation, bool):
                raise ValueError("area_effect.requires_explicit_elevation must be a boolean")
            area = AreaEffectBlock(
                id=_identifier(len(blocks), "area-effect"),
                shape=shape,  # type: ignore[arg-type]
                size_ft=size_ft,
                width_ft=width_ft,
                height_ft=height_ft,
                anchor_height_ft=anchor_height_ft,
                requires_explicit_elevation=requires_explicit_elevation,
                origin=origin,  # type: ignore[arg-type]
                effect_block_ids=effect_ids,
                target_block_id=target.id,
                duration_block_id=duration.id if duration else None,
                trigger_timing=trigger_timing,  # type: ignore[arg-type]
                requires_origin_choice=bool(
                    raw_area.get("requires_origin_choice", origin != "self")
                ),
            )
            roots[:] = [root_id for root_id in roots if root_id not in effect_ids]
            add(area)

    repeat = data.get("repeat")
    if isinstance(repeat, Mapping):
        raw_repeat_ids = repeat.get("block_ids")
        if raw_repeat_ids is not None:
            if not isinstance(raw_repeat_ids, (list, tuple)) or not raw_repeat_ids:
                raise ValueError("repeat.block_ids must be a non-empty list")
            repeatable_ids = [value for value in raw_repeat_ids if isinstance(value, str) and value]
            if len(repeatable_ids) != len(raw_repeat_ids):
                raise ValueError("repeat.block_ids must contain non-empty strings")
            known_ids = {block.id for block in blocks}
            if any(block_id not in known_ids for block_id in repeatable_ids):
                raise ValueError("repeat.block_ids must reference already compiled blocks")
        else:
            repeatable_ids = [
                block.id
                for block in blocks
                if block.kind in {"damage", "heal", "condition", "modifier", "defense", "move"}
            ]
        if repeatable_ids:
            child_ids = tuple(repeatable_ids)
        else:
            child = NarrativeBlock(
                id=_identifier(len(blocks) + 1, "repeat-effect"),
                text=_text(repeat.get("effect") or description or name),
            )
            add(child, root=False)
            child_ids = (child.id,)
        repeat_block = RepeatBlock(
            id=_identifier(len(blocks), "repeat"),
            block_ids=child_ids,
            count=repeat.get("count") if isinstance(repeat.get("count"), int) else None,
            count_expression=(
                None
                if isinstance(repeat.get("count"), int)
                else (
                    _text(repeat.get("count_expression"))
                    if repeat.get("count_expression") is not None
                    else "duration"
                )
            ),
            timing=_text(repeat.get("timing") or "turn_end"),  # type: ignore[arg-type]
        )
        roots[:] = [root_id for root_id in roots if root_id not in child_ids]
        add(repeat_block)
        # Explicit recurring damage/healing is now persisted as a CombatEffect and
        # applied by CombatEngineService at the declared turn boundary. Keep the
        # warning only for repeat children that the executor cannot tick yet.
        repeatable_blocks = [block for block in blocks if block.id in child_ids]
        runtime_repeat_kinds = {"damage", "heal"}
        if not repeatable_blocks or any(
            block.kind not in runtime_repeat_kinds for block in repeatable_blocks
        ):
            warnings.append("重复效果已结构化，但仍包含尚未接入回合执行器的效果")

    choices = data.get("choices")
    if isinstance(choices, list) and len(choices) >= 2:
        option_blocks: list[NarrativeBlock] = []
        options: list[ChoiceOption] = []
        selected_child_ids: list[str] = []
        for index, raw in enumerate(choices):
            if not isinstance(raw, Mapping):
                raise ValueError("each choice must be an object")
            raw_block_ids = raw.get("block_ids")
            if raw_block_ids is not None:
                if not isinstance(raw_block_ids, (list, tuple)) or not raw_block_ids:
                    raise ValueError("choice.block_ids must be a non-empty list")
                child_ids = tuple(
                    value for value in raw_block_ids if isinstance(value, str) and value
                )
                if len(child_ids) != len(raw_block_ids):
                    raise ValueError("choice.block_ids must contain non-empty strings")
                known_ids = {block.id for block in blocks}
                if any(block_id not in known_ids for block_id in child_ids):
                    raise ValueError("choice.block_ids must reference already compiled blocks")
                selected_child_ids.extend(child_ids)
            else:
                child = NarrativeBlock(
                    id=_identifier(len(blocks) + 1 + index, f"choice-{index + 1}"),
                    text=_text(raw.get("description") or raw.get("label")),
                )
                option_blocks.append(child)
                child_ids = (child.id,)
            key = _text(raw.get("key")) or f"option-{index + 1}"
            label = _text(raw.get("label"))
            if not label:
                raise ValueError("each choice requires a label")
            options.append(
                ChoiceOption(
                    key=key,
                    label=label,
                    block_ids=child_ids,
                )
            )
        minimum_choices = data.get("minimum_choices", 1)
        maximum_choices = data.get("maximum_choices", 1)
        if (
            not isinstance(minimum_choices, int)
            or isinstance(minimum_choices, bool)
            or not isinstance(maximum_choices, int)
            or isinstance(maximum_choices, bool)
        ):
            raise ValueError("choice limits must be integers")
        choice = ChoiceBlock(
            id=_identifier(len(blocks), "choice"),
            prompt=_text(data.get("choice_prompt") or "选择一项效果"),
            options=tuple(options),
            minimum_choices=minimum_choices,
            maximum_choices=maximum_choices,
        )
        roots[:] = [root_id for root_id in roots if root_id not in selected_child_ids]
        add(choice)
        for child in option_blocks:
            add(child, root=False)

    trigger = data.get("trigger")
    if isinstance(trigger, Mapping):
        child = NarrativeBlock(
            id=_identifier(len(blocks) + 1, "trigger-effect"),
            text=_text(trigger.get("effect") or description or name),
        )
        trigger_block = TriggerBlock(
            id=_identifier(len(blocks), "trigger"),
            event=_text(trigger.get("event")),
            timing=_text(trigger.get("timing") or "when"),  # type: ignore[arg-type]
            block_ids=(child.id,),
            once=bool(trigger.get("once")),
        )
        add(trigger_block)
        add(child, root=False)

    effect_kinds = {
        "damage",
        "defense",
        "modifier",
        "heal",
        "condition",
        "move",
        "area_effect",
        "teleport",
        "transformation",
        "creation",
        "dispel",
        "summon",
        "repeat",
        "choice",
        "trigger",
        "object_state",
        "exploration_effect",
    }
    if not any(block.kind in effect_kinds for block in blocks):
        add(
            NarrativeBlock(
                id=_identifier(len(blocks), "narrative"),
                text=description or f"{name}需要DM依据规则原文裁定。",
            )
        )

    effect_kinds_present = {block.kind for block in blocks} & {
        "damage",
        "defense",
        "modifier",
        "heal",
        "condition",
        "move",
        "area_effect",
        "teleport",
        "transformation",
        "creation",
        "dispel",
        "summon",
        "object_state",
        "exploration_effect",
    }
    has_manual_blocks = any(
        isinstance(block, NarrativeBlock) and block.requires_dm_adjudication for block in blocks
    )
    unresolved_reasons = list(warnings)
    if has_manual_blocks:
        unresolved_reasons.append("规则包含需要DM裁定的文字效果")
    automation_ready = bool(effect_kinds_present) and not unresolved_reasons
    confidence = "exact" if automation_ready else "partial" if effect_kinds_present else "manual"
    return RulePlan(
        source_kind=inferred_kind,  # type: ignore[arg-type]
        source_name=name,
        source_ref=_text(data.get("source_record_id") or data.get("source_path")) or None,
        spell_level=spell_level,
        blocks=tuple(blocks),
        root_block_ids=tuple(roots),
        automation_confidence=confidence,  # type: ignore[arg-type]
        automation_ready=automation_ready,
        unresolved_reasons=tuple(dict.fromkeys(unresolved_reasons)),
        warnings=tuple(warnings),
    )


def compile_rule_blocks_dict(
    data: Mapping[str, Any],
    *,
    source_kind: str | None = None,
) -> dict[str, Any]:
    """Return the versioned plan as a JSON-ready dictionary for API embedding."""

    return compile_rule_blocks(data, source_kind=source_kind).model_dump(mode="json")
