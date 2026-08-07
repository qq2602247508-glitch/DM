from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from dnd_dm_assistant.domain.advancement import ClassProgression, merge_spell_slot_resources
from dnd_dm_assistant.domain.feature_runtime import (
    compile_feature_runtime_registry,
    feature_runtime_action_projections,
    feature_runtime_contract,
    feature_runtime_definition,
    resource_recovery_events,
)
from dnd_dm_assistant.domain.progression_automation import (
    progression_automation_profile,
)

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

CLASS_ALIASES = {
    "邪术师": "魔契师",
    "奇械师（旧版）": "奇械师",
    "奇械师(旧版)": "奇械师",
    "Artificer": "奇械师",
}

FULL_CASTERS = {"吟游诗人", "牧师", "德鲁伊", "术士", "法师"}
HALF_CASTERS = {"圣武士", "游侠", "奇械师"}

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
    "已知注法": "artificer_infusions",
    "注法": "artificer_infusions",
}

# Three 2024 class tables name Weapon Mastery but omit its total-count column.
# Their feature prose explicitly grants two initial choices.  This is data
# configuration for the same generic weapon_mastery choice executor, not a
# branch in that executor.
INITIAL_WEAPON_MASTERY_COUNTS: dict[str, int] = {
    "圣武士": 2,
    "游侠": 2,
    "游荡者": 2,
}

# The resource key is part of the persisted character-sheet contract.  In
# particular, PlayerRoomService has always used ``focus`` for a monk; using a
# second key here would silently split one pool into two as the character
# advances.
RESOURCE_COLUMNS: dict[str, tuple[str, str, str]] = {
    "狂暴": ("rage", "狂暴", "long_rest"),
    "回气": ("second_wind", "回气", "short_rest"),
    "功力": ("focus", "功力点", "short_rest"),
    "术法点": ("sorcery_points", "术法点", "long_rest"),
    "引导神力": ("channel_divinity", "引导神力", "short_rest"),
    "荒野变形": ("wild_shape", "荒野变形", "short_rest"),
    "宿敌": ("favored_enemy", "宿敌", "long_rest"),
}

RESOURCE_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "狂暴": ("狂暴次数",),
    "回气": ("回气次数",),
    "功力": ("功力点",),
    "术法点": ("术法点数",),
    "引导神力": ("引导神力次数",),
    "荒野变形": ("荒野变形次数",),
    "宿敌": ("宿敌次数",),
}

SCALING_COLUMNS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("rage_damage", ("狂暴伤害",), "狂暴伤害", "bonus_damage"),
    (
        "bardic_inspiration_die",
        ("诗人骰", "诗人激励骰", "激励骰"),
        "诗人激励骰",
        "die",
    ),
    ("martial_arts_die", ("武艺骰", "武术骰"), "武艺骰", "die"),
    ("unarmored_movement", ("无甲移动", "无甲移动加值"), "无甲移动", "speed_bonus"),
    ("sneak_attack", ("偷袭", "偷袭伤害"), "偷袭", "damage_dice"),
    ("pact_slot_level", ("法术位环阶", "契约法术位环阶"), "契约法术位环阶", "slot_level"),
)

FEATURE_RESOURCE_MARKERS: dict[str, str] = {
    "狂暴": "rage",
    "回气": "second_wind",
    "吟游诗人激励": "bardic_inspiration",
    "激励之源": "bardic_inspiration",
    "引导神力": "channel_divinity",
    "荒野变形": "wild_shape",
    # The imported 2024 table calls this ``动作如潮``; ``行动如潮`` is
    # retained for older sheets/source translations.
    "动作如潮": "action_surge",
    "行动如潮": "action_surge",
    "不屈": "indomitable",
    "武僧武功": "focus",
    "功力": "focus",
    "圣疗": "lay_on_hands",
    "宿敌": "favored_enemy",
    "持久狂暴": "rage",
    "先发激励": "bardic_inspiration",
    "明镜止水": "focus",
    "大德鲁伊": "wild_shape",
    "神圣干预": "divine_intervention",
    "进阶神圣干预": "divine_intervention",
    "术法复苏": "sorcery_restoration",
    "秘法回流": "magical_cunning",
    "不知疲倦": "tireless",
    "自然面纱": "nature_veil",
    "魔力泉涌": "sorcery_points",
    "术法点": "sorcery_points",
    "契约魔法": "pact_slots",
    "奥术回想": "arcane_recovery",
    "魔能恢复": "arcane_recovery",
    "幸运一击": "stroke_of_luck",
    "玄奥秘法（六环）": "mystic_arcanum_6",
    "玄奥秘法（七环）": "mystic_arcanum_7",
    "玄奥秘法（八环）": "mystic_arcanum_8",
    "玄奥秘法（九环）": "mystic_arcanum_9",
}

FEATURE_SCALING_MARKERS: dict[str, str] = {
    "狂暴": "rage_damage",
    "吟游诗人激励": "bardic_inspiration_die",
    "武艺骰": "martial_arts_die",
    "武艺": "martial_arts_die",
    "无甲移动": "unarmored_movement",
    "偷袭": "sneak_attack",
    "契约魔法": "pact_slot_level",
}

ABILITY_LABELS = {
    "力量": "strength",
    "敏捷": "dexterity",
    "体质": "constitution",
    "智力": "intelligence",
    "感知": "wisdom",
    "魅力": "charisma",
}

SPELLCASTING_CLASSES = {
    "吟游诗人",
    "牧师",
    "德鲁伊",
    "圣武士",
    "游侠",
    "术士",
    "魔契师",
    "法师",
    "奇械师",
}

# These are deliberately limited to modifiers that can be represented by the
# existing typed combat modifier grammar.  More involved features still receive
# a durable grant, but are not converted into a misleading pseudo-rule.
CORE_FEATURE_MODIFIER_PROFILES: dict[str, tuple[dict[str, Any], ...]] = {
    "危机感应": (
        {
            "stat": "saving_throw",
            "operation": "advantage",
            "scope": "self",
            "applies_when": "dexterity_save_and_not_incapacitated",
        },
    ),
    "无甲移动": (
        {
            "stat": "speed_ft",
            "operation": "add",
            "scope": "self",
            "scaling_key": "unarmored_movement",
            "applies_when": "unarmored_and_not_using_shield",
        },
    ),
    "快速移动": (
        {
            "stat": "speed_ft",
            "operation": "add",
            "value": 10,
            "scope": "self",
            "applies_when": "not_wearing_heavy_armor",
        },
    ),
    "狂暴": (
        {
            "stat": "damage_roll",
            "operation": "add",
            "scope": "outgoing",
            "scaling_key": "rage_damage",
            "applies_when": "raging_strength_melee_attack",
        },
    ),
}


def _feature_marker_matches(feature: str, marker: str) -> bool:
    """Match a known table marker without leaking base features into upgrades."""

    identity = re.sub(r"[\s_：:（）()\-]", "", feature).casefold()
    if marker == "狂暴":
        return identity in {"狂暴", "rage"}
    if marker == "不屈":
        return identity in {"不屈", "不屈一次", "不屈两次", "不屈三次", "indomitable"}
    return marker in feature


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


@dataclass(frozen=True, slots=True)
class FeatRule:
    name: str
    category: str
    prerequisite: str
    repeatable: bool
    source_record_id: str
    source_path: str
    rule_year: str = "2024"
    content_pack_key: str | None = None


def _feat_identity(value: str) -> str:
    return re.sub(r"[\s*＊]", "", value).casefold()


def core_feat_rules_from_records(records: Iterable[dict[str, Any]]) -> tuple[FeatRule, ...]:
    """Build core feat rules from the local 2024 overview and detail pages."""

    core_records = [
        record
        for record in records
        if str(record.get("source_relative_path") or "").startswith(
            "玩家手册2024/专长/"
        )
    ]
    overview = next(
        (
            record
            for record in core_records
            if str(record.get("source_relative_path") or "").endswith("专长概述.htm")
        ),
        None,
    )
    if overview is None:
        return ()
    markdown = str(overview.get("content_markdown") or "")
    table = re.search(
        r"\|\s*专长\s*\|\s*分类\s*\|.*?\n"
        r"\|[- |]+\|\n(?P<rows>(?:\|.*\|\n?)+)",
        markdown,
    )
    if table is None:
        return ()

    details: dict[str, tuple[str, str, str]] = {}
    detail_pattern = re.compile(
        r"^\*\*(?P<name>(?:(?!\*\*).)+?)\n\*\*\*"
        r"(?P<meta>[^\n]*(?:先决|Prerequisite)[^\n]*)\n\*",
        re.I | re.M | re.S,
    )
    for record in core_records:
        source_path = str(record.get("source_relative_path") or "")
        if source_path.endswith("专长概述.htm"):
            continue
        for match in detail_pattern.finditer(str(record.get("content_markdown") or "")):
            meta = re.sub(r"\s+", " ", match.group("meta")).strip()
            prerequisite_match = re.search(
                r"(?:先决|Prerequisite)\s*[：:]\s*(.+?)(?:[）)]|$)",
                meta,
                re.I,
            )
            details[_feat_identity(match.group("name"))] = (
                prerequisite_match.group(1).strip() if prerequisite_match else "",
                str(record.get("stable_id") or ""),
                source_path,
            )

    result: list[FeatRule] = []
    for row in table.group("rows").splitlines():
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) < 2 or not cells[0]:
            continue
        display_name = cells[0]
        detail = details.get(_feat_identity(display_name), ("", "", ""))
        result.append(
            FeatRule(
                name=display_name.replace("*", "").replace("＊", "").strip(),
                category=cells[1],
                prerequisite=detail[0],
                repeatable="*" in display_name or "＊" in display_name,
                source_record_id=detail[1] or str(overview.get("stable_id") or ""),
                source_path=detail[2]
                or str(overview.get("source_relative_path") or ""),
            )
        )
    return tuple(result)


def extension_feat_rules_from_records(
    records: Iterable[dict[str, Any]],
) -> tuple[FeatRule, ...]:
    """Normalise real extension-feat detail pages into the shared validator.

    A book index is not a feat.  This intentionally admits only a named page
    with prose and preserves the source record for later DM adjudication.  A
    prerequisite is parsed when present; otherwise it is explicitly an empty
    requirement instead of being guessed from a heading or a directory name.
    """

    result: list[FeatRule] = []
    known: set[tuple[str, str]] = set()
    for record in records:
        source_path = str(record.get("source_relative_path") or "")
        name = str(record.get("name") or "").replace("*", "").strip()
        markdown = str(record.get("content_markdown") or "")
        if (
            "专长" not in source_path
            or not name
            or name in {"专长", "专长概述", "本书速查"}
            or len(markdown.strip()) < 30
        ):
            continue
        if re.search(r"(?:目录|概述|速查|列表)$", name):
            continue
        identity = (_feat_identity(name), source_path)
        if identity in known:
            continue
        prerequisite_match = re.search(
            r"(?:先决|Prerequisite)\s*[：:]?\s*([^\n*#]{1,180})",
            markdown,
            re.I,
        )
        category_match = re.search(
            r"(?:分类|Category)\s*[：:]?\s*([^\n*#]{1,80})",
            markdown,
            re.I,
        )
        category = (
            category_match.group(1).strip(" ：:。")
            if category_match
            else "通用"
        )
        result.append(
            FeatRule(
                name=name,
                category=category,
                prerequisite=(
                    prerequisite_match.group(1).strip(" ：:。")
                    if prerequisite_match
                    else ""
                ),
                repeatable=bool(re.search(r"(?:可重复|Repeatable)", markdown, re.I)),
                source_record_id=str(record.get("stable_id") or ""),
                source_path=source_path,
                rule_year=str(
                    record.get("normalized_edition") or record.get("edition") or "2014"
                ),
                content_pack_key=(
                    str(record.get("content_pack_key"))
                    if record.get("content_pack_key")
                    else None
                ),
            )
        )
        known.add(identity)
    return tuple(result)


def find_feat_rule(rules: Iterable[FeatRule], choice: str) -> FeatRule | None:
    identity = _feat_identity(choice)
    return next((rule for rule in rules if _feat_identity(rule.name) == identity), None)


def validate_feat_prerequisites(
    rule: FeatRule,
    *,
    expected_category: str,
    total_level: int,
    ability_scores: dict[str, int],
    class_levels: dict[str, int],
    proficiencies: Iterable[object] = (),
    features: Iterable[object] = (),
) -> tuple[str, ...]:
    """Return unmet prerequisites that can be proven from persisted state."""

    failures: list[str] = []
    proficiency_values = tuple(proficiencies)
    feature_values = tuple(features)
    if rule.category != expected_category:
        failures.append(f"必须选择{expected_category}专长，不能选择{rule.category}专长")
    prerequisite = rule.prerequisite
    level_match = re.search(r"等级\s*(\d+)\+", prerequisite)
    if level_match and total_level < int(level_match.group(1)):
        failures.append(f"需要角色等级{level_match.group(1)}+")

    ability_pattern = "|".join(ABILITY_LABELS)
    for match in re.finditer(
        rf"(?P<abilities>(?:{ability_pattern})(?:(?:、|或)(?:{ability_pattern}))*)"
        r"\s*(?P<minimum>\d+)\+",
        prerequisite,
    ):
        abilities = re.findall(ability_pattern, match.group("abilities"))
        minimum = int(match.group("minimum"))
        if max(
            (int(ability_scores.get(ABILITY_LABELS[label], 0)) for label in abilities),
            default=0,
        ) < minimum:
            failures.append(match.group(0))

    for class_name in CORE_CLASSES_2024:
        if re.search(rf"{re.escape(class_name)}(?:职业)?(?:等级)?", prerequisite) and not int(
            class_levels.get(class_name, 0)
        ):
            failures.append(f"需要至少1级{class_name}")

    if re.search(r"施法|契约魔法", prerequisite) and not any(
        int(class_levels.get(name, 0)) > 0 for name in SPELLCASTING_CLASSES
    ):
        failures.append("需要施法或契约魔法能力")

    state_text = " ".join(
        str(item.get("name") or "") if isinstance(item, dict) else str(item)
        for item in (*proficiency_values, *feature_values)
    )
    for label in ("轻甲", "中甲", "重甲", "盾牌", "军用武器"):
        if label in prerequisite and label not in state_text:
            failures.append(f"需要{label}训练或熟练")

    existing_feat_names = [
        str(item.get("name") or "")
        for item in feature_values
        if isinstance(item, dict) and item.get("kind") == "feat"
    ]
    if not rule.repeatable and any(
        _feat_identity(name) == _feat_identity(rule.name) for name in existing_feat_names
    ):
        failures.append("该专长不可重复选择")
    return tuple(dict.fromkeys(failures))


def canonical_class_name(class_name: str) -> str:
    normalized = re.sub(r"\s+", " ", str(class_name).strip())
    return CLASS_ALIASES.get(normalized, normalized)


def _number(raw: str | None) -> int | None:
    if raw is None or raw.strip() in {"", "—", "-", "无"}:
        return None
    match = re.search(r"\d+", raw)
    if match:
        return int(match.group())
    chinese = re.search(r"[一二三四五六七八九十百]+", raw)
    if chinese is None:
        return None
    value = chinese.group()
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value in digits:
        return digits[value]
    if value == "十":
        return 10
    if value.startswith("十") and value[1:] in digits:
        return 10 + digits[value[1:]]
    if value.endswith("十") and value[:-1] in digits:
        return digits[value[:-1]] * 10
    if len(value) == 3 and value[0] in digits and value[1] == "十" and value[2] in digits:
        return digits[value[0]] * 10 + digits[value[2]]
    return None


def _progression_number(rule: ClassProgression, level: int, column: str) -> int | None:
    return _number(_progression_value(rule, level, (column,)))


def _progression_value(
    rule: ClassProgression,
    level: int,
    columns: Iterable[str],
) -> str | None:
    """Find a table cell while tolerating harmless header wording variants."""

    if not 1 <= level <= 20:
        return None
    progression = rule.levels[level - 1].progression
    for column in columns:
        value = progression.get(column)
        if value not in (None, "", "—", "-", "无"):
            return str(value)

    normalized_columns = {
        re.sub(r"[\s（）()]", "", str(key)): value
        for key, value in progression.items()
    }
    for column in columns:
        value = normalized_columns.get(re.sub(r"[\s（）()]", "", column))
        if value not in (None, "", "—", "-", "无"):
            return str(value)
    return None


def _ability_modifier(
    ability_scores: dict[str, int] | None,
    key: str,
) -> int | None:
    if ability_scores is None or key not in ability_scores:
        return None
    return (int(ability_scores[key]) - 10) // 2


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
    if any("传奇恩惠" in feature or "史诗恩惠" in feature for feature in level_rule.features):
        requirements.append(
            ChoiceRequirement(
                key="epic_boon",
                kind="feat",
                minimum=1,
                maximum=1,
                strict=True,
                options_source="feats:传奇恩惠",
                reason="该职业等级必须选择一个满足前置条件的传奇恩惠专长。",
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

    if (
        any("武器精通" in feature for feature in level_rule.features)
        and not any(item.key == "weapon_mastery" for item in requirements)
        and rule.name in INITIAL_WEAPON_MASTERY_COUNTS
    ):
        count = INITIAL_WEAPON_MASTERY_COUNTS[rule.name]
        requirements.append(
            ChoiceRequirement(
                key="weapon_mastery",
                kind="feature_option",
                minimum=count,
                maximum=count,
                strict=False,
                options_source="feature:武器精通",
                reason=(
                    f"{rule.name}的2024武器精通特性授予{count}项初始选择；"
                    "具体武器的熟练与词条效果分层验收。"
                ),
                target_total=count,
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
    *,
    ability_scores: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compile sheet resources from a 1–20 class table.

    The return value only contains independently tracked totals.  It deliberately
    does not turn prose-only feature effects into executable actions; callers can
    display those features as DM-adjudicated references instead.
    """

    updates: dict[str, dict[str, Any]] = {}
    for column, (key, label, recovery) in RESOURCE_COLUMNS.items():
        raw = _progression_value(
            rule,
            target_class_level,
            (column, *RESOURCE_COLUMN_ALIASES.get(column, ())),
        )
        maximum = _number(raw)
        if maximum is None:
            continue
        updates[key] = {
            "label": label,
            "max": maximum,
            "recovery": recovery,
            "source": f"{rule.name} {target_class_level}级成长表",
        }

    source = f"{rule.name} {target_class_level}级职业特性"
    if rule.name == "吟游诗人":
        charisma_modifier = _ability_modifier(ability_scores, "charisma")
        bardic = {
            "label": "吟游诗人激励",
            "recovery": "short_rest" if target_class_level >= 5 else "long_rest",
            "source": source,
            "max_formula": "max(1, charisma_modifier)",
        }
        if charisma_modifier is not None:
            bardic["max"] = max(1, charisma_modifier)
        updates["bardic_inspiration"] = bardic
    elif rule.name == "战士":
        if target_class_level >= 2:
            updates["action_surge"] = {
                "label": "行动如潮",
                "max": 2 if target_class_level >= 17 else 1,
                "recovery": "short_rest",
                "source": source,
            }
        if target_class_level >= 9:
            updates["indomitable"] = {
                "label": "不屈",
                "max": 3 if target_class_level >= 17 else 2 if target_class_level >= 13 else 1,
                "recovery": "long_rest",
                "source": source,
            }
    elif rule.name == "圣武士":
        updates["lay_on_hands"] = {
            "label": "圣疗",
            "max": target_class_level * 5,
            "recovery": "long_rest",
            "source": source,
        }
    elif rule.name == "牧师" and target_class_level >= 10:
        updates["divine_intervention"] = {
            "label": "神圣干预",
            "max": 1,
            "recovery": "long_rest",
            "source": source,
            "requires_dm_adjudication": True,
            "note": "只追踪使用次数；具体法术或祈愿术分支仍需 DM 选择。",
        }
    elif rule.name == "法师" and target_class_level >= 1:
        updates["arcane_recovery"] = {
            "label": "魔能恢复",
            "max": 1,
            "recovery": "long_rest",
            "source": source,
        }
    elif rule.name == "游荡者" and target_class_level >= 20:
        updates["stroke_of_luck"] = {
            "label": "幸运一击",
            "max": 1,
            "recovery": "short_rest",
            "source": source,
        }

    if rule.name == "术士" and target_class_level >= 5:
        updates["sorcery_restoration"] = {
            "label": "术法复苏",
            "max": 1,
            "recovery": "long_rest",
            "source": source,
            "requires_dm_adjudication": True,
            "note": "只追踪短休期间可用的一次恢复；恢复术法点的数量仍按职业等级裁定。",
        }
    if rule.name == "魔契师" and target_class_level >= 2:
        updates["magical_cunning"] = {
            "label": "秘法回流",
            "max": 1,
            "recovery": "long_rest",
            "source": source,
            "requires_dm_adjudication": True,
            "note": "只追踪一分钟仪式的每日使用次数；恢复法术位数量由 DM 按职业等级确认。",
        }
    if rule.name == "游侠":
        wisdom_modifier = _ability_modifier(ability_scores, "wisdom")
        if target_class_level >= 10:
            updates["tireless"] = {
                "label": "不知疲倦",
                "max_formula": "max(1, wisdom_modifier)",
                "recovery": "long_rest",
                "source": source,
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "note": "只追踪临时生命值使用次数；短休结束时力竭自动降低 1 级。",
            }
            if wisdom_modifier is not None:
                updates["tireless"]["max"] = max(1, wisdom_modifier)
        if target_class_level >= 14:
            updates["nature_veil"] = {
                "label": "自然面纱",
                "max_formula": "max(1, wisdom_modifier)",
                "recovery": "long_rest",
                "source": source,
                "requires_dm_adjudication": False,
                "automation_status": "full",
                "note": "隐形状态与下一回合开始的生命周期由战斗运行时真实执行。",
            }
            if wisdom_modifier is not None:
                updates["nature_veil"]["max"] = max(1, wisdom_modifier)

    if rule.name == "魔契师":
        pact_slots = _number(
            _progression_value(
                rule,
                target_class_level,
                ("法术位", "契约法术位", "法术位数量"),
            )
        )
        if pact_slots is not None:
            pact = {
                "label": "契约法术位",
                "max": pact_slots,
                "recovery": "short_rest",
                "source": f"{rule.name} {target_class_level}级成长表",
            }
            pact_ring = _number(
                _progression_value(
                    rule,
                    target_class_level,
                    ("法术位环阶", "契约法术位环阶"),
                )
            )
            if pact_ring is not None:
                pact["slot_level"] = pact_ring
            updates["pact_slots"] = pact
        for spell_level, minimum_level in ((6, 11), (7, 13), (8, 15), (9, 17)):
            if target_class_level >= minimum_level:
                updates[f"mystic_arcanum_{spell_level}"] = {
                    "label": f"秘法奥秘（{spell_level}环）",
                    "max": 1,
                    "recovery": "long_rest",
                    "source": source,
                    "requires_dm_adjudication": True,
                    "note": "只追踪每日使用次数；所选法术仍需 DM 依据来源条目裁定。",
                }
    for key, resource in updates.items():
        events = resource_recovery_events(key, resource)
        if events:
            resource["recovery_events"] = events
    return updates


def progression_scaling_updates(
    rule: ClassProgression,
    target_class_level: int,
) -> dict[str, dict[str, Any]]:
    """Return exact table values that belong on the character sheet.

    Values are kept as table text so dice expressions and signed bonuses stay
    auditable instead of being guessed into a combat implementation.
    """

    source = f"{rule.name} {target_class_level}级成长表"
    updates: dict[str, dict[str, Any]] = {}
    for key, columns, label, value_kind in SCALING_COLUMNS:
        value = _progression_value(rule, target_class_level, columns)
        if value is None:
            continue
        updates[key] = {
            "label": label,
            "value": value,
            "value_kind": value_kind,
            "source": source,
            "automation_status": "partial",
            "requires_dm_adjudication": True,
        }
    return updates


_SUBCLASS_HEADING = re.compile(
    r"(?m)^(?:#{2,6}\s+|\*\*)?\s*"
    r"(?P<level>\d{1,2})(?:级|st|nd|rd|th)"
    r"(?:\s*[：:.、-]\s*|\s+)"
    r"(?P<name>[^\n*#]{1,160}?)(?:\*\*)?\s*$",
    re.I,
)
_SUBCLASS_ITALIC_LEVEL = re.compile(
    r"(?m)^\*\*(?P<name>[^*\n]{1,160}?(?:\n[^*\n]{1,160}?)?)\*\*(?:[^\n]*)?\s*\n"
    r"\s*\*{1,3}\s*第(?P<level>\d{1,2})级[^\n*]*特性",
)
_SUBCLASS_ABILITY_NAMES = {
    "力量": "strength",
    "敏捷": "dexterity",
    "体质": "constitution",
    "智力": "intelligence",
    "感知": "wisdom",
    "魅力": "charisma",
}


def _strip_feature_title(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.replace("**", "")).strip()
    return re.sub(r"[。．.:：\s]+$", "", normalized)


def subclass_feature_definitions_from_record(
    record: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Extract explicit level headings from a subclass detail page.

    This parser deliberately accepts only explicit level headings.  It never
    infers a grant level from an index, a table of contents, or the order of
    prose paragraphs.  The description remains source text for DM review.
    """

    markdown = str(record.get("content_markdown") or "")
    markers: list[tuple[int, int, int, str]] = []
    for match in _SUBCLASS_HEADING.finditer(markdown):
        level = int(match.group("level"))
        name = _strip_feature_title(match.group("name"))
        if 1 <= level <= 20 and name:
            markers.append((match.start(), match.end(), level, name))
    for match in _SUBCLASS_ITALIC_LEVEL.finditer(markdown):
        level = int(match.group("level"))
        name = _strip_feature_title(match.group("name"))
        if 1 <= level <= 20 and name:
            markers.append((match.start(), match.end(), level, name))
    markers = sorted(set(markers), key=lambda item: (item[0], item[2], item[3]))
    result: list[dict[str, Any]] = []
    source_id = str(record.get("stable_id") or "")
    for index, (_, body_start, level, name) in enumerate(markers):
        body_end = markers[index + 1][0] if index + 1 < len(markers) else len(markdown)
        description = markdown[body_start:body_end].strip()
        if not description or len(name) > 120:
            continue
        feature_id = f"{source_id}:{level}:{len(result) + 1}"
        definition: dict[str, Any] = {
            "id": feature_id,
            "name": name,
            "class_level": level,
            "description": description[:5000],
            "source_record_id": source_id,
            "source_path": str(record.get("source_relative_path") or ""),
            "rule_year": str(
                record.get("normalized_edition") or record.get("edition") or "2014"
            ),
            "content_pack_key": (
                str(record.get("content_pack_key"))
                if record.get("content_pack_key")
                else None
            ),
        }
        choice = _subclass_choice_schema(description)
        if choice is not None:
            definition["choice_requirement"] = choice
        result.append(definition)
    return tuple(result)


def _subclass_choice_schema(description: str) -> dict[str, Any] | None:
    if not re.search(r"(?:选择|选取|二选一|三选一|择一)", description):
        return None
    count_match = re.search(r"(?:选择|选取)\s*(?:其中)?\s*(\d+)\s*(?:项|个|种)?", description)
    chinese_count = re.search(r"([一二三])\s*选\s*一", description)
    count = int(count_match.group(1)) if count_match else {
        "一": 1,
        "二": 1,
        "三": 1,
    }.get(chinese_count.group(1) if chinese_count else "", 1)
    return {
        "key": "subclass_feature_choice",
        "minimum": count,
        "maximum": count,
        "strict": True,
        "options_source": "subclass.feature.description",
        "requires_dm_selection": True,
        "reason": "来源文本要求选择，但选项全集或前置条件未可靠结构化；请由 DM 选择并记录。",
    }


def _subclass_resource_update(
    definition: dict[str, Any],
    *,
    ability_scores: dict[str, int] | None,
) -> tuple[str, dict[str, Any]] | None:
    description = str(definition.get("description") or "")
    if "使用" not in description or "次" not in description:
        return None
    source_id = str(definition.get("source_record_id") or definition.get("id") or "")
    fingerprint = re.sub(r"[^a-z0-9]+", "", source_id.casefold())[-18:]
    if not fingerprint:
        fingerprint = hashlib.sha256(
            str(definition.get("id") or "").encode()
        ).hexdigest()[:18]
    key = f"subclass_{fingerprint}_{int(definition['class_level'])}"
    explicit = re.search(
        r"(?:可|能)?使用(?:此|该)?(?:特性|能力)?[^。；;]{0,32}?(\d+)\s*次",
        description,
    )
    ability_match = re.search(
        r"使用次数(?:等于|为)你的?(力量|敏捷|体质|智力|感知|魅力)(?:调整值|调整)",
        description,
    )
    proficiency = bool(
        re.search(r"使用次数(?:等于|为)你的?熟练加值", description)
    )
    update: dict[str, Any] = {
        "label": str(definition["name"]),
        "recovery": (
            "short_rest"
            if re.search(r"(?:短休|短休息)", description)
            else "long_rest"
            if re.search(r"(?:长休|长休息)", description)
            else "dm_adjudicated"
        ),
        "source": (
            f"{definition.get('source_path') or definition.get('source_record_id')}"
            f" · {definition['class_level']}级{definition['name']}"
        ),
        "requires_dm_adjudication": True,
    }
    if explicit:
        update["max"] = int(explicit.group(1))
    elif ability_match:
        ability = _SUBCLASS_ABILITY_NAMES[ability_match.group(1)]
        update["max_formula"] = f"max(1, {ability}_modifier)"
        if ability_scores is not None and ability in ability_scores:
            update["max"] = max(1, _ability_modifier(ability_scores, ability) or 0)
    elif proficiency:
        level = int(definition["class_level"])
        update["max_formula"] = "proficiency_bonus"
        update["max"] = 2 + (level - 1) // 4
    else:
        return None
    return key, update


def _subclass_action(definition: dict[str, Any], resource_key: str | None) -> dict[str, Any] | None:
    description = str(definition.get("description") or "")
    feature_id = str(definition.get("id") or definition.get("name") or "").strip()
    action_cost = (
        "bonus_action"
        if "附赠动作" in description
        else "reaction"
        if "反应" in description
        else "action"
        if re.search(r"(?:作为|花费|使用).{0,16}?动作", description)
        else None
    )
    if action_cost is None:
        return None
    return {
        "id": f"subclass_feature_action:{feature_id}",
        "feature_id": feature_id,
        "name": str(definition["name"]),
        "kind": "subclass_feature_action",
        "class_name": str(definition.get("class_name") or ""),
        "class_level": int(definition["class_level"]),
        "source_record_id": definition.get("source_record_id"),
        "source_path": definition.get("source_path"),
        "action_cost": action_cost,
        "resource_key": resource_key,
        "resource_cost": 1 if resource_key else 0,
        "runtime": {
            "automation_status": "partial",
            "requires_dm_adjudication": True,
            "note": "已记录动作经济和可验证资源；目标、检定、伤害及文本例外由 DM 裁定。",
        },
    }


def subclass_runtime_grants(
    subclass: dict[str, Any],
    *,
    class_name: str,
    target_class_level: int,
    ability_scores: dict[str, int] | None = None,
    selected_choices: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Compile a selected subclass's grants, sheet actions and resources.

    The returned ``choice_requirements`` is intentionally structured for the
    API rather than silently selecting one branch from prose.  A caller can
    validate a DM selection and persist it alongside the feature grant.
    """

    definitions = [
        dict(item)
        for item in subclass.get("feature_definitions", [])
        if isinstance(item, dict)
        and int(item.get("class_level") or 0) == target_class_level
    ]
    grants: list[dict[str, Any]] = []
    resources: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    choices = selected_choices or {}
    for definition in definitions:
        definition["class_name"] = class_name
        feature_id = str(definition.get("id") or definition.get("name") or "")
        requirement = definition.get("choice_requirement")
        selected = [str(item).strip() for item in choices.get(feature_id, []) if str(item).strip()]
        if isinstance(requirement, dict):
            requirements.append({"feature_id": feature_id, **requirement})
        resource = _subclass_resource_update(definition, ability_scores=ability_scores)
        resource_key = resource[0] if resource else None
        if resource is not None:
            resources[resource[0]] = resource[1]
        action = _subclass_action(definition, resource_key)
        if action is not None:
            actions.append(action)
        grants.append(
            {
                "feature_id": feature_id,
                "name": str(definition["name"]),
                "kind": "subclass_feature",
                "class_name": class_name,
                "subclass_name": str(subclass.get("name") or ""),
                "class_level": target_class_level,
                "source_record_id": definition.get("source_record_id"),
                "source_path": definition.get("source_path"),
                "rule_year": definition.get("rule_year") or "2014",
                "content_pack_key": definition.get("content_pack_key"),
                "description": definition.get("description"),
                "selected_choices": selected,
                "runtime": {
                    "automation_status": "partial" if (resource or action) else "dm_only",
                    "tracked_resource_keys": [resource_key] if resource_key else [],
                    "action_name": action.get("name") if action else None,
                    "requires_dm_adjudication": True,
                    "note": (
                        "已同步可验证的资源或动作经济；其余文本效果由 DM 裁定。"
                        if (resource or action)
                        else "该子职特性已自动授予；具体效果由 DM 根据来源文本裁定。"
                    ),
                },
            }
        )
    return {
        "grants": grants,
        "resources": resources,
        "actions": actions,
        "choice_requirements": requirements,
    }


def core_runtime_actions(
    rule: ClassProgression,
    target_class_level: int,
) -> tuple[dict[str, Any], ...]:
    """Return only action cards that the existing combat endpoint can execute.

    The older list was a second, shallow name-to-action mapping.  It could put
    a choice-bound feature on a player's action menu even though the feature
    endpoint would necessarily reject it.  The compiled registry now owns the
    decision and exposes such entries only through its audit contracts.
    """

    resources = progression_resource_updates(rule, target_class_level)
    scalings = progression_scaling_updates(rule, target_class_level)
    registry = compile_feature_runtime_registry(
        core_feature_grants(rule, target_class_level),
        resources=resources,
        scalings=scalings,
        class_levels={rule.name: target_class_level},
        total_level=target_class_level,
    )
    return tuple(feature_runtime_action_projections(registry))


def core_feature_grants(
    rule: ClassProgression,
    target_class_level: int,
    *,
    ability_scores: dict[str, int] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Compile one persisted grant for every named core-class feature.

    A grant is intentionally explicit about what the program can track.  A
    resource or table scalar is ``partial`` automation; a prose-only feature is
    retained as a durable, DM-adjudicated reference rather than a misleading
    pseudo-action.
    """

    level_rule = rule.levels[target_class_level - 1]
    resources = progression_resource_updates(
        rule,
        target_class_level,
        ability_scores=ability_scores,
    )
    scalings = progression_scaling_updates(rule, target_class_level)
    grants: list[dict[str, Any]] = []
    for feature in level_rule.features:
        resource_keys = sorted(
            {
                key
                for marker, key in FEATURE_RESOURCE_MARKERS.items()
                if _feature_marker_matches(feature, marker) and key in resources
            }
        )
        scaling_keys = sorted(
            {
                key
                for marker, key in FEATURE_SCALING_MARKERS.items()
                if _feature_marker_matches(feature, marker) and key in scalings
            }
        )
        modifier_profiles: list[dict[str, Any]] = []
        for marker, profiles in CORE_FEATURE_MODIFIER_PROFILES.items():
            if not _feature_marker_matches(feature, marker):
                continue
            for profile in profiles:
                normalized = dict(profile)
                scaling_key = normalized.get("scaling_key")
                if isinstance(scaling_key, str) and scaling_key in scalings:
                    raw_value = scalings[scaling_key].get("value")
                    if isinstance(raw_value, int):
                        normalized["value"] = raw_value
                    else:
                        normalized["value_source"] = raw_value
                normalized["source_feature"] = feature
                modifier_profiles.append(normalized)
        registry = feature_runtime_definition(
            feature_name=feature,
            class_name=rule.name,
            class_level=target_class_level,
            source_record_id=rule.source_record_id,
            resources=resources,
            tracked_resource_keys=resource_keys,
            tracked_scaling_keys=scaling_keys,
            modifiers=modifier_profiles,
        )
        progression_profile = progression_automation_profile(feature)
        contract = feature_runtime_contract(
            feature_name=feature,
            class_name=rule.name,
            class_level=target_class_level,
            kind="class_feature",
            source_record_id=rule.source_record_id,
            source_path=rule.source_path,
            definition=registry,
            declared_status=(
                progression_profile.overall_status
                if progression_profile is not None
                else None
            ),
            note=(
                progression_profile.dm_boundary
                if progression_profile is not None
                else None
            ),
        )
        tracked = contract["automation_status"] != "dm_only"
        grants.append(
            {
                "name": feature,
                "kind": "class_feature",
                "class_name": rule.name,
                "class_level": target_class_level,
                "source_record_id": rule.source_record_id,
                "source_path": rule.source_path,
                "rule_year": rule.rule_year,
                "runtime": {
                    "automation_status": contract["automation_status"],
                    "execution": {
                        "kind": "combat_grant",
                        "phase": "combat_start",
                        "feature_name": feature,
                        "requires_explicit_trigger": not bool(modifier_profiles),
                    },
                    "contract": contract,
                    "tracked_resource_keys": resource_keys,
                    "tracked_scaling_keys": scaling_keys,
                    "modifiers": modifier_profiles,
                    "registry": registry,
                    "advancement_automation": (
                        progression_profile.as_dict()
                        if progression_profile is not None
                        else None
                    ),
                    "requires_dm_adjudication": contract["requires_dm_adjudication"],
                    "note": (
                        "该特性有可验证的运行时 contract；未覆盖的触发、目标或分支"
                        "会在 contract 的 reasons 中明确列为 DM 裁定。"
                        if tracked
                        else "本地资料只结构化了授予时点；具体规则效果保留给 DM 裁定。"
                    ),
                },
            }
        )
    return tuple(grants)


def core_class_level_runtime_contract(
    rule: ClassProgression,
    target_class_level: int,
    *,
    ability_scores: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build the auditable contract for one core-class level from 1 through 20.

    This is deliberately a level-grant view rather than a prose parser. Every
    name in the class table gets a contract entry, while table facts that do
    not belong to one named feature (proficiency bonus and shared spell slots)
    are reported beside it.  Consumers can therefore distinguish an actually
    executable result from a durable DM-only reference.
    """

    if not 1 <= target_class_level <= 20:
        raise ValueError("target class level must be between 1 and 20")
    level_rule = rule.levels[target_class_level - 1]
    resources = progression_resource_updates(
        rule,
        target_class_level,
        ability_scores=ability_scores,
    )
    scalings = progression_scaling_updates(rule, target_class_level)
    shared_spell_slots = merge_spell_slot_resources(
        {},
        {rule.name: target_class_level},
    )
    grants = core_feature_grants(
        rule,
        target_class_level,
        ability_scores=ability_scores,
    )
    registry = compile_feature_runtime_registry(
        grants,
        resources={**shared_spell_slots, **resources},
        scalings=scalings,
        class_levels={rule.name: target_class_level},
        total_level=target_class_level,
    )
    summary = {status: 0 for status in ("full", "partial", "dm_only")}
    for contract in registry["feature_contracts"]:
        status = str(contract.get("automation_status") or "dm_only")
        if status in summary:
            summary[status] += 1
    return {
        "schema_version": registry["schema_version"],
        "class_name": rule.name,
        "class_level": target_class_level,
        "proficiency_bonus": level_rule.proficiency_bonus,
        "maximum_class_spell_level": maximum_class_spell_level(
            rule.name,
            target_class_level,
        ),
        "choice_requirements": [
            requirement.as_dict()
            for requirement in advancement_choice_requirements(rule, target_class_level)
        ],
        "feature_contracts": registry["feature_contracts"],
        "resources": registry["resources"],
        "scalings": scalings,
        "spell_slots": registry["progression"]["spell_slots"],
        "combat_start": registry["combat_start"],
        "automation_summary": summary,
    }
