from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from dnd_dm_assistant.domain.rule_blocks import (
    ChoiceBlock,
    ChoiceOption,
    ConditionBlock,
    DamageBlock,
    DurationBlock,
    HealBlock,
    MoveBlock,
    NarrativeBlock,
    RepeatBlock,
    ResourceBlock,
    RollBlock,
    RuleBlock,
    RulePlan,
    SaveBlock,
    SummonBlock,
    TargetBlock,
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
    "钝击": "bludgeoning",
    "寒冷": "cold",
    "火焰": "fire",
    "力场": "force",
    "闪电": "lightning",
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
_AREA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
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
    combined = f"{raw_range} {description}"
    range_ft: int | None
    if "自身" in raw_range or raw_range.lower() == "self":
        mode = "self"
        range_ft = 0
    elif "接触" in raw_range or raw_range.lower() == "touch":
        mode = "single"
        range_ft = 5
    else:
        match = _RANGE.search(raw_range)
        range_ft = int(match.group(1)) if match else None
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
    return TargetBlock(
        id=block_id,
        mode=mode,  # type: ignore[arg-type]
        disposition="self" if mode == "self" else "any",
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
    allowed_kinds = {"spell", "action", "feature", "item", "monster_action", "unknown"}
    if inferred_kind not in allowed_kinds:
        raise ValueError("unsupported source_kind")

    blocks: list[RuleBlock] = []
    roots: list[str] = []
    warnings: list[str] = []

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

    raw_damage = data.get("damage_expression") or data.get("damage")
    damage_text = _text(raw_damage)
    resolution_kind = _text(data.get("resolution_kind")).lower()
    damage_expression = _dice_expression(raw_damage)
    damage_type = _damage_type(data.get("damage_type"), damage_text)
    is_healing = resolution_kind == "heal" or damage_text.startswith("治疗")
    if is_healing and damage_expression:
        add(
            HealBlock(
                id=_identifier(len(blocks), "heal"),
                expression=damage_expression,
                target_block_id=target.id,
            )
        )
    elif damage_expression and damage_type and resolution_kind != "narrative":
        attack_roll: RollBlock | None = None
        if save is None:
            attack_roll = RollBlock(
                id=_identifier(len(blocks), "roll"),
                roll_type="attack",
                ability=None,
                target_defense="ac",
                target_block_id=target.id,
            )
            add(attack_roll)
        add(
            DamageBlock(
                id=_identifier(len(blocks), "damage"),
                expression=damage_expression,
                damage_type=damage_type,
                applies_on="save_failure" if save else "hit" if attack_roll else "always",
                shared_roll=bool(data.get("shared_damage_roll", True)),
                save_block_id=save.id if save else None,
                target_block_id=target.id,
            )
        )
    elif raw_damage and resolution_kind != "narrative":
        warnings.append("伤害字段无法安全编译，已转为DM文字裁定")
    elif resolution_kind == "damage":
        warnings.append("标记为伤害规则但缺少可验证伤害骰，未生成伤害积木")

    for raw_condition in data.get("conditions") or ():
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
            )
        )

    summon = data.get("summon")
    if isinstance(summon, Mapping):
        count = summon.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool):
            raise ValueError("summon.count must be an integer")
        add(
            SummonBlock(
                id=_identifier(len(blocks), "summon"),
                creature_ref=_text(summon.get("creature_ref")),
                count=count,
                controller=_text(summon.get("controller") or "caster"),  # type: ignore[arg-type]
                duration_block_id=duration.id if duration else None,
            )
        )

    repeat = data.get("repeat")
    if isinstance(repeat, Mapping):
        child = NarrativeBlock(
            id=_identifier(len(blocks) + 1, "repeat-effect"),
            text=_text(repeat.get("effect") or description or name),
        )
        repeat_block = RepeatBlock(
            id=_identifier(len(blocks), "repeat"),
            block_ids=(child.id,),
            count=repeat.get("count") if isinstance(repeat.get("count"), int) else None,
            count_expression=(
                _text(repeat.get("count_expression"))
                if repeat.get("count_expression") is not None
                else None
            ),
            timing=_text(repeat.get("timing") or "turn_end"),  # type: ignore[arg-type]
        )
        add(repeat_block)
        add(child, root=False)

    choices = data.get("choices")
    if isinstance(choices, list) and len(choices) >= 2:
        option_blocks: list[NarrativeBlock] = []
        options: list[ChoiceOption] = []
        for index, raw in enumerate(choices):
            if not isinstance(raw, Mapping):
                raise ValueError("each choice must be an object")
            child = NarrativeBlock(
                id=_identifier(len(blocks) + 1 + index, f"choice-{index + 1}"),
                text=_text(raw.get("description") or raw.get("label")),
            )
            option_blocks.append(child)
            options.append(
                ChoiceOption(
                    key=f"option-{index + 1}",
                    label=_text(raw.get("label")),
                    block_ids=(child.id,),
                )
            )
        choice = ChoiceBlock(
            id=_identifier(len(blocks), "choice"),
            prompt=_text(data.get("choice_prompt") or "选择一项效果"),
            options=tuple(options),
            minimum_choices=1,
            maximum_choices=1,
        )
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

    effect_kinds = {"damage", "heal", "condition", "move", "summon", "repeat", "choice", "trigger"}
    if not any(block.kind in effect_kinds for block in blocks):
        add(
            NarrativeBlock(
                id=_identifier(len(blocks), "narrative"),
                text=description or f"{name}需要DM依据规则原文裁定。",
            )
        )

    effect_kinds_present = {
        block.kind for block in blocks
    } & {"damage", "heal", "condition", "move", "summon"}
    has_manual_blocks = any(
        isinstance(block, NarrativeBlock) and block.requires_dm_adjudication
        for block in blocks
    )
    unresolved_reasons = list(warnings)
    if has_manual_blocks:
        unresolved_reasons.append("规则包含需要DM裁定的文字效果")
    automation_ready = bool(effect_kinds_present) and not unresolved_reasons
    confidence = (
        "exact"
        if automation_ready
        else "partial"
        if effect_kinds_present
        else "manual"
    )
    return RulePlan(
        source_kind=inferred_kind,  # type: ignore[arg-type]
        source_name=name,
        source_ref=_text(data.get("source_record_id") or data.get("source_path")) or None,
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
