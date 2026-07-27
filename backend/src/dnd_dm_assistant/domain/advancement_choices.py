from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from dnd_dm_assistant.domain.advancement import ClassProgression

CORE_CLASSES_2024 = (
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
)

CLASS_ALIASES = {"邪术师": "魔契师"}

FULL_CASTERS = {"吟游诗人", "牧师", "德鲁伊", "术士", "法师"}
HALF_CASTERS = {"圣武士", "游侠"}

# These counts are stated by the named 2024 feature, rather than guessed from
# prose. Option membership still comes from the local rule corpus/DM review.
FEATURE_CHOICE_COUNTS: dict[str, tuple[str, int]] = {
    "战斗风格": ("fighting_style", 1),
    "原初职能": ("primal_order", 1),
    "圣职": ("divine_order", 1),
    "元素之怒": ("elemental_fury", 1),
    "元素狂怒": ("elemental_fury_improvement", 1),
    "受祝击": ("blessed_strikes", 1),
    "专精": ("expertise", 2),
    "魔法奥秘": ("magical_secrets", 2),
    "法术精通": ("spell_mastery", 2),
    "招牌法术": ("signature_spells", 2),
}

# The table reports the total number known. A level that raises this total
# creates exactly the delta in new selections.
PROGRESSION_CHOICE_COLUMNS: dict[str, str] = {
    "武器精通": "weapon_mastery",
    "魔能祈唤": "eldritch_invocation",
}

RESOURCE_COLUMNS: dict[str, tuple[str, str]] = {
    "狂暴": ("rage", "狂暴"),
    "回气": ("second_wind", "回气"),
    "功力": ("focus_points", "功力点"),
    "术法点": ("sorcery_points", "术法点"),
    "引导神力": ("channel_divinity", "引导神力"),
    "荒野变形": ("wild_shape", "荒野变形"),
    "宿敌": ("favored_enemy", "宿敌"),
}


@dataclass(frozen=True, slots=True)
class ChoiceRequirement:
    key: str
    kind: str
    minimum: int
    maximum: int
    strict: bool
    options_source: str
    reason: str
    target_total: int | None = None
    maximum_spell_level: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_class_name(class_name: str) -> str:
    return CLASS_ALIASES.get(class_name, class_name)


def _number(raw: str | None) -> int | None:
    if raw is None or raw.strip() in {"", "—", "-", "无"}:
        return None
    match = re.search(r"\d+", raw)
    return int(match.group()) if match else None


def _progression_number(rule: ClassProgression, level: int, column: str) -> int | None:
    if not 1 <= level <= 20:
        return None
    return _number(rule.levels[level - 1].progression.get(column))


def maximum_class_spell_level(class_name: str, class_level: int) -> int:
    """Highest spell level learnable/preparable from this class.

    This intentionally uses class level, not the shared multiclass slot table:
    higher shared slots never permit learning a higher-level class spell.
    """

    name = canonical_class_name(class_name)
    if name in FULL_CASTERS:
        return min(9, (class_level + 1) // 2)
    if name in HALF_CASTERS:
        return min(5, (class_level + 3) // 4)
    if name == "魔契师":
        return min(5, (class_level + 1) // 2)
    return 0


def advancement_choice_requirements(
    rule: ClassProgression,
    target_class_level: int,
) -> tuple[ChoiceRequirement, ...]:
    """Compile a class-table row into generic level-up choice requirements."""

    if not 1 <= target_class_level <= 20:
        raise ValueError("target class level must be between 1 and 20")
    level_rule = rule.levels[target_class_level - 1]
    previous_level = target_class_level - 1
    requirements: list[ChoiceRequirement] = []

    if any("子职" in feature or "子职业" in feature for feature in level_rule.features):
        requirements.append(
            ChoiceRequirement(
                key="subclass",
                kind="subclass",
                minimum=1,
                maximum=1,
                strict=True,
                options_source="class.subclasses",
                reason="该职业等级授予子职选择。",
            )
        )
    if any("属性值提升" in feature for feature in level_rule.features):
        requirements.append(
            ChoiceRequirement(
                key="asi_or_feat",
                kind="exclusive_choice",
                minimum=1,
                maximum=1,
                strict=True,
                options_source="ability_scores|feats",
                reason="属性值提升等级必须选择属性提升或一个合法专长。",
            )
        )

    for feature in level_rule.features:
        matched = next(
            (
                (label, key, count)
                for label, (key, count) in FEATURE_CHOICE_COUNTS.items()
                if label in feature
            ),
            None,
        )
        if matched is None:
            continue
        label, key, count = matched
        requirements.append(
            ChoiceRequirement(
                key=key,
                kind="feature_option",
                minimum=count,
                maximum=count,
                strict=False,
                options_source=f"feature:{label}",
                reason=(
                    f"{feature}包含{count}项选择；本地成长表能确认数量，"
                    "但选项前置条件需要规则条目或DM复核。"
                ),
            )
        )

    for column, key in PROGRESSION_CHOICE_COLUMNS.items():
        target = _progression_number(rule, target_class_level, column)
        previous = _progression_number(rule, previous_level, column)
        if target is None:
            continue
        delta = max(0, target - (previous or 0))
        if delta:
            requirements.append(
                ChoiceRequirement(
                    key=key,
                    kind="feature_option",
                    minimum=delta,
                    maximum=delta,
                    strict=False,
                    options_source=f"progression:{column}",
                    reason=(
                        f"{column}总数由{previous or 0}增至{target}；"
                        "具体选项的前置条件需要规则条目或DM复核。"
                    ),
                    target_total=target,
                )
            )

    cantrips = _progression_number(rule, target_class_level, "戏法")
    previous_cantrips = _progression_number(rule, previous_level, "戏法") or 0
    if cantrips is not None:
        delta = max(0, cantrips - previous_cantrips)
        requirements.append(
            ChoiceRequirement(
                key="cantrips",
                kind="spell_selection",
                minimum=delta,
                maximum=delta,
                strict=True,
                options_source=f"spells:{rule.name}:0",
                reason=f"职业成长表规定本级戏法总数为{cantrips}。",
                target_total=cantrips,
                maximum_spell_level=0,
            )
        )

    prepared = _progression_number(rule, target_class_level, "准备法术")
    previous_prepared = _progression_number(rule, previous_level, "准备法术") or 0
    if prepared is not None:
        requirements.append(
            ChoiceRequirement(
                key="prepared_spells",
                kind="spell_preparation",
                minimum=prepared,
                maximum=prepared,
                strict=True,
                options_source=(
                    f"spells:{rule.name}:1-"
                    f"{maximum_class_spell_level(rule.name, target_class_level)}"
                ),
                reason=f"职业成长表规定本级准备法术总数为{prepared}。",
                target_total=prepared,
                maximum_spell_level=maximum_class_spell_level(
                    rule.name, target_class_level
                ),
            )
        )
        if rule.name != "法师":
            delta = max(0, prepared - previous_prepared)
            if delta:
                requirements.append(
                    ChoiceRequirement(
                        key="new_prepared_spells",
                        kind="spell_selection",
                        minimum=delta,
                        maximum=delta,
                        strict=True,
                        options_source=f"spells:{rule.name}",
                        reason=f"准备法术上限从{previous_prepared}增至{prepared}。",
                        target_total=prepared,
                        maximum_spell_level=maximum_class_spell_level(
                            rule.name, target_class_level
                        ),
                    )
                )

    # 2024 Wizard adds two spells to the spellbook whenever gaining a Wizard
    # level after level 1. This is separate from its prepared-spell total.
    if rule.name == "法师" and target_class_level > 1:
        requirements.append(
            ChoiceRequirement(
                key="spellbook_additions",
                kind="spell_selection",
                minimum=2,
                maximum=2,
                strict=True,
                options_source="spells:法师",
                reason="法师每获得一个法师等级，将两个合法法师法术加入法术书。",
                maximum_spell_level=maximum_class_spell_level(
                    rule.name, target_class_level
                ),
            )
        )

    return tuple(requirements)


def progression_resource_updates(
    rule: ClassProgression,
    target_class_level: int,
) -> dict[str, dict[str, Any]]:
    """Compile consumable totals from a class table without restoring spent uses."""

    updates: dict[str, dict[str, Any]] = {}
    progression = rule.levels[target_class_level - 1].progression
    for column, (key, label) in RESOURCE_COLUMNS.items():
        maximum = _number(progression.get(column))
        if maximum is None:
            continue
        updates[key] = {
            "label": label,
            "max": maximum,
            "recovery": "long_rest",
            "source": f"{rule.name} {target_class_level}级成长表",
        }
    return updates
