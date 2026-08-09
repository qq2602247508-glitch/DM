from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
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
    "元素之怒": ("elemental_fury", 1),
    "元素狂怒": ("elemental_fury_improvement", 1),
    "受祝击": ("blessed_strikes", 1),
    "专精": ("expertise", 2),
    # Scholar is a one-skill expertise grant.  It intentionally reuses the
    # same generic expertise executor as Rogue/Bard expertise.
    "学者": ("expertise", 1),
    "法术精通": ("spell_mastery", 2),
    "招牌法术": ("signature_spells", 2),
    "玄奥秘法（六环）": ("mystic_arcanum_6", 1),
    "玄奥秘法（七环）": ("mystic_arcanum_7", 1),
    "玄奥秘法（八环）": ("mystic_arcanum_8", 1),
    "玄奥秘法（九环）": ("mystic_arcanum_9", 1),
}

CORE_SELECTED_SPELL_GRANTS: dict[str, dict[str, Any]] = {
    f"mystic_arcanum_{spell_level}": {
        "count": 1,
        "allowed_classes": ["魔契师"],
        "exact_level": spell_level,
        "grant_class": "owner_class",
        "always_prepared": True,
        "free_cast_resource_key": f"mystic_arcanum_{spell_level}",
    }
    for spell_level in (6, 7, 8, 9)
}
CORE_SELECTED_SPELL_GRANTS.update(
    {
        "primal_order_cantrip": {
            "count": 1,
            "allowed_classes": ["德鲁伊"],
            "exact_level": 0,
            "grant_class": "owner_class",
            "always_prepared": True,
            "conditional_choice": ("primal_order", "magician"),
        },
        "divine_order_cantrip": {
            "count": 1,
            "allowed_classes": ["牧师"],
            "exact_level": 0,
            "grant_class": "owner_class",
            "always_prepared": True,
            "conditional_choice": ("divine_order", "thaumaturge"),
        },
        "blessed_warrior_cantrips": {
            "count": 2,
            "allowed_classes": ["牧师"],
            "exact_level": 0,
            "grant_class": "owner_class",
            "always_prepared": True,
            "spellcasting_ability": "charisma",
            "conditional_choice": ("fighting_style", "blessed_warrior"),
        },
        "druidic_warrior_cantrips": {
            "count": 2,
            "allowed_classes": ["德鲁伊"],
            "exact_level": 0,
            "grant_class": "owner_class",
            "always_prepared": True,
            "spellcasting_ability": "wisdom",
            "conditional_choice": ("fighting_style", "druidic_warrior"),
        },
    }
)

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
    "复原之触": "lay_on_hands",
    "宿敌": "favored_enemy",
    "持久狂暴": "rage",
    "先发激励": "bardic_inspiration",
    "明镜止水": "focus",
    "大德鲁伊": "wild_shape",
    "信实坐骑": "faithful_steed",
    "神圣干预": "divine_intervention",
    "进阶神圣干预": "divine_intervention",
    "术法复苏": "sorcery_restoration",
    "秘法回流": "magical_cunning",
    "归复平衡": "clockwork_balance",
    "龙翼": "dragon_wings",
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
    options: tuple[str, ...] = ()
    selected_asset_kind: str | None = None
    expected_category: str | None = None
    duplicate_policy: str | None = None
    replacement_policy: str | None = None

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
        if str(record.get("source_relative_path") or "").startswith("玩家手册2024/专长/")
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
                source_path=detail[2] or str(overview.get("source_relative_path") or ""),
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
        category = category_match.group(1).strip(" ：:。") if category_match else "通用"
        result.append(
            FeatRule(
                name=name,
                category=category,
                prerequisite=(
                    prerequisite_match.group(1).strip(" ：:。") if prerequisite_match else ""
                ),
                repeatable=bool(re.search(r"(?:可重复|Repeatable)", markdown, re.I)),
                source_record_id=str(record.get("stable_id") or ""),
                source_path=source_path,
                rule_year=str(record.get("normalized_edition") or record.get("edition") or "2014"),
                content_pack_key=(
                    str(record.get("content_pack_key")) if record.get("content_pack_key") else None
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
        if (
            max(
                (int(ability_scores.get(ABILITY_LABELS[label], 0)) for label in abilities),
                default=0,
            )
            < minimum
        ):
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
        re.sub(r"[\s（）()]", "", str(key)): value for key, value in progression.items()
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

    if any("战斗风格" in feature for feature in level_rule.features):
        alternatives = (
            ("blessed_warrior",) if rule.name == "圣武士" else
            ("druidic_warrior",) if rule.name == "游侠" else ()
        )
        requirements.append(
            ChoiceRequirement(
                key="fighting_style",
                kind="selected_asset",
                minimum=1,
                maximum=1,
                strict=True,
                options_source="feats:战斗风格",
                options=alternatives,
                selected_asset_kind="feat_or_typed_option",
                expected_category="战斗风格",
                duplicate_policy="forbid",
                replacement_policy=(
                    "replace_on_owner_class_level" if rule.name == "战士" else None
                ),
                reason="从权威战斗风格专长目录选择；职业专属戏法分支使用封闭选项。",
            )
        )

        if rule.name == "圣武士":
            requirements.append(
                ChoiceRequirement(
                    key="blessed_warrior_cantrips",
                    kind="feature_option",
                    minimum=0,
                    maximum=2,
                    strict=True,
                    options_source="spells:牧师:0",
                    reason="仅选择受祝福的勇士时，必须选择两道不重复牧师戏法。",
                    maximum_spell_level=0,
                )
            )
        elif rule.name == "游侠":
            requirements.append(
                ChoiceRequirement(
                    key="druidic_warrior_cantrips",
                    kind="feature_option",
                    minimum=0,
                    maximum=2,
                    strict=True,
                    options_source="spells:德鲁伊:0",
                    reason="仅选择德鲁伊教战士时，必须选择两道不重复德鲁伊戏法。",
                    maximum_spell_level=0,
                )
            )

    if rule.name == "战士" and target_class_level > 1:
        requirements.append(
            ChoiceRequirement(
                key="fighting_style_replacement",
                kind="selected_asset_replacement",
                minimum=0,
                maximum=1,
                strict=True,
                options_source="feats:战斗风格",
                selected_asset_kind="feat",
                expected_category="战斗风格",
                duplicate_policy="forbid",
                replacement_policy="old->new",
                reason="每次获得战士等级时，可将一个已选战斗风格替换为另一个。",
            )
        )

    if any("熟练探险家" in feature for feature in level_rule.features):
        requirements.extend(
            (
                ChoiceRequirement(
                    key="deft_explorer_expertise",
                    kind="selected_expertise",
                    minimum=1,
                    maximum=1,
                    strict=True,
                    options_source="character.proficient_skills",
                    reason="选择一项已熟练且尚未专精的技能。",
                    duplicate_policy="forbid",
                ),
                ChoiceRequirement(
                    key="deft_explorer_languages",
                    kind="selected_language",
                    minimum=2,
                    maximum=2,
                    strict=True,
                    options_source="catalog.languages",
                    reason="从2024核心语言表选择两门尚未掌握的非通用语。",
                    duplicate_policy="forbid",
                ),
            )
        )

    for feature_name, key, options, cantrip_key, spell_class in (
        ("原初职能", "primal_order", ("magician", "warden"), "primal_order_cantrip", "德鲁伊"),
        ("圣职", "divine_order", ("protector", "thaumaturge"), "divine_order_cantrip", "牧师"),
    ):
        if not any(feature_name in feature for feature in level_rule.features):
            continue
        requirements.extend(
            (
                ChoiceRequirement(
                    key=key,
                    kind="selected_option_bundle",
                    minimum=1,
                    maximum=1,
                    strict=True,
                    options_source=f"feature:{feature_name}",
                    options=options,
                    duplicate_policy="forbid",
                    reason=f"{feature_name}使用封闭分支，并在升级事务中写入全部效果。",
                ),
                ChoiceRequirement(
                    key=cantrip_key,
                    kind="feature_option",
                    minimum=0,
                    maximum=1,
                    strict=True,
                    options_source=f"spells:{spell_class}:0",
                    reason="仅施法分支必须选择一道权威职业戏法。",
                    maximum_spell_level=0,
                ),
            )
        )

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
                maximum_spell_level=maximum_class_spell_level(rule.name, target_class_level),
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
                maximum_spell_level=maximum_class_spell_level(rule.name, target_class_level),
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
        if target_class_level >= 5:
            updates["faithful_steed"] = {
                "label": "信实坐骑免费施法",
                "max": 1,
                "recovery": "long_rest",
                "source": source,
                "resource_kind": "free_spell_cast",
                "automation_status": "full",
                "requires_dm_adjudication": False,
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
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "note": "短休恢复数量由休息输入限定为不超过术士等级一半。",
        }
    if rule.name == "魔契师" and target_class_level >= 2:
        updates["magical_cunning"] = {
            "label": "秘法回流",
            "max": 1,
            "recovery": "long_rest",
            "source": source,
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "note": "一分钟仪式恢复数量按已消耗契约魔法法术位的一半向上取整。",
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


# Battle Master maneuvers are persisted as canonical IDs.  The display labels
# are kept at the choice boundary; the roll/attack consumers only receive the
# resulting typed action contracts.
BATTLE_MASTER_MANEUVER_OPTIONS: dict[str, str] = {
    "ambush": "伏击",
    "bait_and_switch": "换位诈术",
    "commander_strike": "指挥官奇袭",
    "commanding_presence": "领导风范",
    "disarming_attack": "缴械攻击",
    "distracting_strike": "扰乱打击",
    "evasive_footwork": "灵巧步法",
    "feinting_attack": "诡诈攻击",
    "goading_attack": "挑衅攻击",
    "lunging_attack": "突刺攻击",
    "maneuvering_attack": "灵动攻击",
    "menacing_attack": "恐吓攻击",
    "parry": "格挡",
    "precision_attack": "精准攻击",
    "pushing_attack": "推撞攻击",
    "rally": "重整旗鼓",
    "riposte": "反击",
    "sweeping_attack": "横扫攻击",
    "tactical_assessment": "战术预估",
    "trip_attack": "摔绊攻击",
}
_BATTLE_MASTER_MANEUVER_ALIASES = {
    **{key: key for key in BATTLE_MASTER_MANEUVER_OPTIONS},
    **{label: key for key, label in BATTLE_MASTER_MANEUVER_OPTIONS.items()},
}


def _canonical_battle_master_maneuver(value: object) -> str | None:
    normalized = str(value or "").strip().casefold()
    if normalized.startswith("replace:") and "->" in normalized:
        old, new = normalized[8:].split("->", 1)
        old_key = _BATTLE_MASTER_MANEUVER_ALIASES.get(old.strip())
        new_key = _BATTLE_MASTER_MANEUVER_ALIASES.get(new.strip())
        if old_key and new_key:
            return f"replace:{old_key}->{new_key}"
        return None
    return _BATTLE_MASTER_MANEUVER_ALIASES.get(normalized)


# A small, explicit set of subclass configurations whose effect is already
# represented by the shared combat defense consumer.  This table is an
# adapter/configuration layer; the consumer only reads typed defense fields and
# never dispatches on a subclass or feature identifier.
SUBCLASS_FEATURE_RUNTIME_CONFIGS: dict[str, dict[str, Any]] = {
    # Trickster's Blessing is a single, rest-scoped skill advantage.  The
    # action writes a typed modifier into the target snapshot; the player-roll
    # resolver consumes that modifier and the rest service removes it on a
    # long rest.  Reusing the feature replaces the previous blessing instead
    # of leaving duplicate sources behind.
    "诡术祝福": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "trickster_blessing": {
                "id": "trickster_blessing",
                "name": "诡术祝福",
                "kind": "feature_action",
                "action_cost": "action",
                "target": "ally_or_self",
                "target_policy": {
                    "mode": "ally_or_self",
                    "same_faction": True,
                    "range_ft": 30,
                },
                "resolution_kind": "timed_modifier",
                "effects": [
                    {
                        "kind": "grant_timed_modifier",
                        "modifier": {
                            "stat": "skill_check",
                            "skill": "stealth",
                            "operation": "advantage",
                            "scope": "self",
                        },
                        "expires_on": "long_rest",
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action_and_player_roll_resolution",
                    "effect_kinds": ["grant_timed_modifier"],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Fanatical Focus is a once-per-rage failed-save recovery.  The rage
    # action produces ``feature_states.fanatical_focus`` and the generic roll
    # consumer clears it in the same confirmation transaction that records the
    # replacement roll.  The bonus is bound to the persisted rage-damage
    # scaling entry, never guessed from a class name.
    "专心炽志": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "fanatical_focus": {
                "id": "fanatical_focus",
                "name": "专心炽志",
                "kind": "roll_intervention",
                "trigger": "after_failed_d20_test",
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": ["saving_throw"],
                    "required_conditions": ["raging"],
                    "state": {"key": "fanatical_focus"},
                    "resource": {
                        "key": "rage_damage",
                        "minimum": 0,
                        "value_bind_as": "rage_damage",
                    },
                },
                "operation": {
                    "kind": "failure_recovery",
                    "recovery": {
                        "kind": "reroll_with_add",
                        "selection": "replacement",
                        "amount": "rage_damage",
                    },
                    "consume_when": "on_confirm",
                },
                "idempotency": {"prefix": "roll-intervention"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                    "producer": "rage_activation",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Bend Luck is a post-d20 reaction that can target any visible creature.
    # The generic resolver asks for the reported d4 and sign, then the combat
    # transaction consumes one sorcery point and the reactor's reaction.
    "扭曲幸运": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "bend_luck": {
                "id": "bend_luck",
                "name": "扭曲幸运",
                "kind": "roll_intervention",
                "trigger": "after_d20_test",
                "action_cost": "reaction",
                "target_policy": {
                    "mode": "any",
                    "range_ft": 60,
                    "requires_visible_or_audible": True,
                },
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": [
                        "ability_check",
                        "skill_check",
                        "saving_throw",
                        "armor_class",
                    ],
                    "resource": {"key": "sorcery_points", "minimum": 1},
                },
                "input_requirements": [
                    {"key": "luck_die", "kind": "die_roll", "die_sides": 4},
                    {"key": "luck_direction", "kind": "signed_unit"},
                ],
                "operation": {
                    "kind": "add",
                    "amount": "luck_die*luck_direction",
                },
                "resource": {"key": "sorcery_points", "cost": 1},
                "idempotency": {"prefix": "roll-intervention"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                    "target_validation": "line_of_sight_or_audibility",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    "归复平衡": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {
            "clockwork_balance": {
                "key": "clockwork_balance",
                "label": "归复平衡",
                "max_formula": "max(1, charisma_modifier)",
                "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "actions": {
            "restore_balance": {
                "id": "restore_balance",
                "name": "归复平衡",
                "kind": "roll_intervention",
                "trigger": "after_d20_test",
                "action_cost": "reaction",
                "target_policy": {
                    "mode": "any",
                    "range_ft": 60,
                    "requires_visible_or_audible": True,
                },
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": ["ability_check", "skill_check", "saving_throw", "armor_class"],
                    "roll_modes": ["advantage", "disadvantage"],
                    "resource": {"key": "clockwork_balance", "minimum": 1},
                },
                "operation": {
                    "kind": "cancel_advantage_disadvantage",
                    "selection": "first",
                },
                "resource": {"key": "clockwork_balance", "cost": 1},
                "idempotency": {"prefix": "roll-intervention"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                    "target_validation": "line_of_sight_or_audibility",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Warding Flare is the same external-reactor, post-roll window with a
    # disadvantage transform.  The separate feature pool is restored on a
    # long rest; the second reported d20 is mandatory, so the server never
    # invents the reaction roll.
    "守御之光": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {
            "warding_flare": {
                "key": "warding_flare",
                "label": "守御之光",
                "max_formula": "max(1, wisdom_modifier)",
                "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "actions": {
            "warding_flare": {
                "id": "warding_flare",
                "name": "守御之光",
                "kind": "roll_intervention",
                "trigger": "after_d20_test",
                "action_cost": "reaction",
                "target_policy": {
                    "mode": "any",
                    "range_ft": 30,
                    "requires_visible_or_audible": True,
                },
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": ["armor_class"],
                    "resource": {"key": "warding_flare", "minimum": 1},
                },
                "operation": {"kind": "disadvantage", "selection": "lowest"},
                "resource": {"key": "warding_flare", "cost": 1},
                "idempotency": {"prefix": "roll-intervention"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                    "target_validation": "line_of_sight_or_audibility",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Improved Warding Flare keeps the existing external reaction, resource
    # CAS and disadvantage operation, then applies its additional 2d6 + WIS
    # temporary-hit-point grant to the attack's target in the same transaction.
    "精通守御之光": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "warding_flare": {
                "id": "warding_flare",
                "name": "守御之光（精通）",
                "kind": "roll_intervention",
                "trigger": "after_d20_test",
                "action_cost": "reaction",
                "target_policy": {
                    "mode": "any",
                    "range_ft": 30,
                    "requires_visible_or_audible": True,
                },
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": ["armor_class"],
                    "resource": {"key": "warding_flare", "minimum": 1},
                },
                "operation": {"kind": "disadvantage", "selection": "lowest"},
                "input_requirements": [{"key": "temporary_hp_total", "kind": "roll_total"}],
                "post_effect": {
                    "kind": "grant_temporary_hp",
                    "input_key": "temporary_hp_total",
                    "dice_count": 2,
                    "die_sides": 6,
                    "ability_modifier": "wisdom",
                },
                "resource": {"key": "warding_flare", "cost": 1},
                "idempotency": {"prefix": "roll-intervention"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution_and_temporary_hp",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Guided Strike is a fixed +10 recovery after a missed attack.  The
    # reaction is conditional: the cleric spends it only when correcting an
    # ally's roll, while correcting its own attack is reaction-free.
    "导引打击": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "guided_strike": {
                "id": "guided_strike",
                "name": "导引打击",
                "kind": "roll_intervention",
                "trigger": "after_failed_d20_test",
                "action_cost": "reaction_if_external",
                "target_policy": {
                    "mode": "any",
                    "range_ft": 30,
                    "requires_visible_or_audible": True,
                },
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": ["armor_class"],
                    "resource": {"key": "channel_divinity", "minimum": 1},
                },
                "operation": {"kind": "add", "amount": 10},
                "resource": {"key": "channel_divinity", "cost": 1},
                "idempotency": {"prefix": "roll-intervention"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                    "target_validation": "line_of_sight_or_audibility",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Leading Evasion reuses the existing Evasion save consumer and extends
    # it through a position-aware five-foot ally passive.  The source must be
    # visible and not incapacitated; leaving the radius immediately removes
    # the shared benefit without mutating the ally's sheet.
    "引导闪避": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "leading_evasion:ranged_evasion",
                    "kind": "evasion",
                    "ranged_passive": {
                        "effect_kind": "evasion",
                        "target_relation": "self_and_allies",
                        "range_ft": 5,
                        "requires_grid_position_for_others": True,
                        "source_forbidden_conditions": ["incapacitated"],
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "ranged_passive_evasion_and_saving_throw_resolution",
                    },
                }
            ],
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    # Starry Form remains partial because its constellation branches still
    # require their dedicated attack/healing/concentration consumers.  Its
    # activation lifecycle is nevertheless authoritative and reusable by
    # later features such as Full of Stars.
    "星耀形态": {
        "automation_status": "partial",
        "requires_dm_adjudication": True,
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "starry_form": {
                "id": "starry_form",
                "name": "星耀形态",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "wild_shape",
                "resource_cost": 1,
                "target": "self",
                "resolution_kind": "condition",
                "duration": "10_minutes",
                "effects": [
                    {
                        "kind": "activate_duration_condition",
                        "condition": "starry_form",
                        "duration_unit": "minutes",
                        "duration_value": 10,
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action",
                    "effect_kinds": ["activate_duration_condition"],
                },
                "automation_status": "partial",
                "requires_dm_adjudication": True,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Full of Stars is a complete conditional defense.  Activation is written
    # by the typed Starry Form action above; the damage resolver consumes only
    # this structured condition list and never dispatches on a feature name.
    "灿若繁星": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "subclass:full_of_stars:physical_resistance",
                    "kind": "damage_resistance",
                    "damage_types": ["bludgeoning", "piercing", "slashing"],
                    "applies_when": "always",
                    "required_conditions": ["starry_form"],
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    # Fixed spell access uses the same authoritative character-spell list as
    # class spellcasting, while retaining the source-specific casting ability.
    "掌控元素": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "advancement": {
            "kind": "fixed_spell_grant",
            "spells": ["四象法门"],
            "grant_class": "owner_class",
            "casting_ability": "wisdom",
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service_and_player_action_resolution",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    # Faithful Steed has two linked effects: the spell is always prepared and
    # one casting per long rest bypasses ordinary spell slots.  Spell economy
    # consumes the typed resource metadata, not this feature name.
    "信实坐骑": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {
            "faithful_steed": {
                "key": "faithful_steed",
                "label": "信实坐骑免费施法",
                "max": 1,
                "recovery": "long_rest",
                "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "advancement": {
            "kind": "fixed_spell_grant",
            "spells": ["寻获坐骑"],
            "grant_class": "owner_class",
            "casting_ability": "charisma",
            "free_cast_resource_key": "faithful_steed",
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service_and_spell_economy_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    # Portent and Greater Portent share one pre-roll replacement pool.  The
    # pool values are supplied by the player/DM when a long rest is confirmed;
    # combat only consumes one persisted value after the player arms it before
    # the d20 is rolled.  The runtime never invents a die result.
    "预兆": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "portent_pool": {
                "id": "portent_pool",
                "name": "预兆",
                "kind": "roll_intervention",
                "trigger": "before_d20_test",
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": ["ability_check", "skill_check", "saving_throw", "armor_class"],
                    "resource": {"key": "$feature_resource", "minimum": 1},
                },
                "operation": {
                    "kind": "replace_d20_from_pool",
                    "input_key": "pool_value",
                },
                "target_policy": {
                    "mode": "any",
                    "requires_visible_or_audible": True,
                },
                "input_requirements": [{"key": "pool_value", "kind": "d20_roll"}],
                "resource": {"key": "$feature_resource", "cost": 1},
                "pool_resource": True,
                "idempotency": {"prefix": "roll-intervention"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_prompt_and_resolution",
                    "rest_producer": "long_rest_submitted_d20_values",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Psionic Power is itself a resource-producing feature.  Its consumers
    # (Guarded Mind, Psychic Teleportation, and the other subclass actions)
    # are separate contracts; this block owns only the authoritative die pool
    # size and its short/long-rest lifecycle.  The subclass compiler binds
    # ``$feature_resource`` to the class-specific pool emitted by
    # ``_subclass_resource_update``.
    "灵能力量": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {
            "$feature_resource": {
                "key": "$feature_resource",
                "label": "灵能骰",
                "resource_kind": "psionic_dice",
                "recovery_events": [
                    {"rest": "short_rest", "operation": "restore", "amount": 1},
                    {"rest": "long_rest", "operation": "set_to_max"},
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "rest_service_and_resource_registry",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    # War God's Blessing is a reaction after an attack roll is reported.  The
    # target/range and reaction are validated by the shared roll-intervention
    # resolver; the Wisdom-scaled pool is produced by the typed resource
    # parser below and restored on a long rest.
    "战神祝福": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {
            "$feature_resource": {
                "key": "$feature_resource",
                "label": "战神祝福",
                "resource_kind": "feature_uses",
                "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "actions": {
            "war_gods_blessing": {
                "id": "war_gods_blessing",
                "name": "战神祝福",
                "kind": "roll_intervention",
                "trigger": "after_d20_test",
                "action_cost": "reaction",
                "target_policy": {
                    "mode": "any",
                    "range_ft": 30,
                    "requires_visible_or_audible": True,
                },
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": ["armor_class"],
                    "resource": {"key": "$feature_resource", "minimum": 1},
                },
                "operation": {"kind": "add", "amount": 10},
                "resource": {"key": "$feature_resource", "cost": 1},
                "idempotency": {"prefix": "roll-intervention"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                    "target_validation": "line_of_sight_or_audibility",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    "高等预兆": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "portent_pool": {
                "id": "portent_pool",
                "name": "高等预兆",
                "kind": "roll_intervention",
                "trigger": "before_d20_test",
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": ["ability_check", "skill_check", "saving_throw", "armor_class"],
                    "resource": {"key": "$feature_resource", "minimum": 1},
                },
                "operation": {
                    "kind": "replace_d20_from_pool",
                    "input_key": "pool_value",
                },
                "target_policy": {
                    "mode": "any",
                    "requires_visible_or_audible": True,
                },
                "input_requirements": [{"key": "pool_value", "kind": "d20_roll"}],
                "resource": {"key": "$feature_resource", "cost": 1},
                "pool_resource": True,
                "idempotency": {"prefix": "roll-intervention"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_prompt_and_resolution",
                    "rest_producer": "long_rest_submitted_d20_values",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # A selected spell grant is an advancement effect, not an informal note.
    # The advancement service validates the selected catalog entries against
    # this typed source/class/school/level contract and persists them on the
    # authoritative spell sheet.  Consumers never identify the subclass.
    "魔法探秘": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "advancement": {
            "kind": "selected_spell_grant",
            "selection": {
                "count": 2,
                "allowed_classes": ["牧师", "德鲁伊", "法师"],
                "maximum_level": "owner_class",
                "grant_class": "owner_class",
                "always_prepared": True,
            },
            "choice_requirement": {
                "key": "subclass_selected_spells",
                "minimum": 2,
                "maximum": 2,
                "strict": True,
                "options_source": "spell_catalog:牧师|德鲁伊|法师",
                "requires_dm_selection": False,
                "reason": "魔法探秘要求从牧师、德鲁伊或法师法术表选择两道法术。",
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    # The four specialist schools share one source-validated spellbook grant.
    # Adding future schools is configuration-only; the executor consumes the
    # same `selected_spell_grant` grammar above.
    "塑能学者": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "advancement": {
            "kind": "selected_spell_grant",
            "selection": {
                "count": 2,
                "add_one_per_new_spell_level": True,
                "allowed_classes": ["法师"],
                "school": "塑能",
                "maximum_level": "owner_class",
                "grant_class": "owner_class",
                "spellbook": True,
            },
            "choice_requirement": {
                "key": "subclass_selected_spells",
                "minimum": 2,
                "maximum": 2,
                "strict": True,
                "options_source": "spell_catalog:法师:塑能:1-2",
                "requires_dm_selection": False,
                "reason": "塑能学者要求从法师塑能法术中选择两道不高于二环的法术加入法术书。",
            },
            "runtime_execution": {"status": "ready", "consumer": "advancement_service"},
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    "幻术学者": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "advancement": {
            "kind": "selected_spell_grant",
            "selection": {
                "count": 2,
                "add_one_per_new_spell_level": True,
                "allowed_classes": ["法师"],
                "school": "幻术",
                "maximum_level": "owner_class",
                "grant_class": "owner_class",
                "spellbook": True,
            },
            "choice_requirement": {
                "key": "subclass_selected_spells",
                "minimum": 2,
                "maximum": 2,
                "strict": True,
                "options_source": "spell_catalog:法师:幻术:1-2",
                "requires_dm_selection": False,
                "reason": "幻术学者要求从法师幻术法术中选择两道不高于二环的法术加入法术书。",
            },
            "runtime_execution": {"status": "ready", "consumer": "advancement_service"},
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    "防护学者": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "advancement": {
            "kind": "selected_spell_grant",
            "selection": {
                "count": 2,
                "add_one_per_new_spell_level": True,
                "allowed_classes": ["法师"],
                "school": "防护",
                "maximum_level": "owner_class",
                "grant_class": "owner_class",
                "spellbook": True,
            },
            "choice_requirement": {
                "key": "subclass_selected_spells",
                "minimum": 2,
                "maximum": 2,
                "strict": True,
                "options_source": "spell_catalog:法师:防护:1-2",
                "requires_dm_selection": False,
                "reason": "防护学者要求从法师防护法术中选择两道不高于二环的法术加入法术书。",
            },
            "runtime_execution": {"status": "ready", "consumer": "advancement_service"},
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    "预言学者": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "advancement": {
            "kind": "selected_spell_grant",
            "selection": {
                "count": 2,
                "add_one_per_new_spell_level": True,
                "allowed_classes": ["法师"],
                "school": "预言",
                "maximum_level": "owner_class",
                "grant_class": "owner_class",
                "spellbook": True,
            },
            "choice_requirement": {
                "key": "subclass_selected_spells",
                "minimum": 2,
                "maximum": 2,
                "strict": True,
                "options_source": "spell_catalog:法师:预言:1-2",
                "requires_dm_selection": False,
                "reason": "预言学者要求从法师预言法术中选择两道不高于二环的法术加入法术书。",
            },
            "runtime_execution": {"status": "ready", "consumer": "advancement_service"},
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    # Eldritch Knight and Arcane Trickster obtain their spellcasting from this
    # subclass grant rather than their base class.  Their third-caster slot
    # progression, spell preparation validation, and spell-economy spending
    # are already calculated from the selected subclass by the advancement
    # and spell-economy services.  This contract makes that existing runtime
    # capability explicit in the feature registry; it does not manufacture a
    # spell list or let a non-selected subclass cast spells.
    "施法": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "spellcasting": {
            "kind": "spellcasting_capability",
            "consumer": "spell_economy_service",
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    # Lore's Bonus Proficiencies is a typed, player-selected skill grant.  The
    # generic advancement consumer validates selections against the supported
    # skill registry and writes them into Character.skills, which is the state
    # used by actual skill checks.  This deliberately does not match other
    # vaguely named proficiency features with different option sets.
    "附赠熟练": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "advancement": {
            "kind": "proficiency_choice",
            "option_kind": "skill",
            "operation": "grant_proficiency",
            "allowed_options": "supported_skills",
            "choice_requirement": {
                "key": "subclass_skill_proficiency",
                "minimum": 3,
                "maximum": 3,
                "strict": True,
                "options_source": "supported_skill_registry",
                "requires_dm_selection": False,
                "reason": "逸闻学院附赠熟练要求选择三项技能熟练。",
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    # Student of War grants two independently typed choices.  The request
    # format keeps the existing flat subclass-choice API while making each
    # selection unambiguous (``skill:<name>`` and ``tool:<name>``); the
    # advancement service validates each group's local option set and writes
    # skill proficiency or tool proficiency to the authoritative sheet.
    "战争学者": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "advancement": {
            "kind": "typed_proficiency_choice",
            "choice_groups": [
                {
                    "prefix": "skill",
                    "kind": "skill",
                    "minimum": 1,
                    "maximum": 1,
                    "allowed_options": [
                        "杂技",
                        "驯兽",
                        "运动",
                        "历史",
                        "洞悉",
                        "威吓",
                        "察觉",
                        "生存",
                    ],
                },
                {
                    "prefix": "tool",
                    "kind": "tool",
                    "minimum": 1,
                    "maximum": 1,
                    "allowed_options": [
                        "木匠工具",
                        "铁匠工具",
                        "皮匠工具",
                        "石匠工具",
                        "陶匠工具",
                        "织工工具",
                        "玻璃工工具",
                        "珠宝匠工具",
                        "制图工具",
                        "书法工具",
                        "画家工具",
                    ],
                },
            ],
            "choice_requirement": {
                "key": "subclass_typed_proficiency",
                "minimum": 2,
                "maximum": 2,
                "strict": True,
                "options_source": "typed_subclass_choice_groups",
                "requires_dm_selection": False,
                "reason": (
                    "战争学者要求选择一项工匠工具和一项战士技能；"
                    "使用 skill:<名称>、tool:<名称> 提交。"
                ),
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    # Psychic Defenses is a pair of passive consumers already present in the
    # authoritative damage and saving-throw paths.  The saving-throw
    # predicate is evaluated against the condition being avoided/ended, so it
    # does not grant unconditional advantage on every save.
    "心灵防御": {
        "combat_start": {
            "modifiers": [
                {
                    "id": "psychic_defenses:condition_save_advantage",
                    "stat": "saving_throw",
                    "operation": "advantage",
                    "scope": "self",
                    "applies_when": "saving_throw_against_charmed_or_frightened",
                    "source": "对抗或终止魅惑/恐慌的豁免具有优势",
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
            "defenses": [
                {
                    "id": "psychic_defenses:psychic_resistance",
                    "kind": "damage_resistance",
                    "damage_types": ["psychic"],
                    "applies_when": "always",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    # Iron Mind is a typed saving-throw proficiency choice.  The advancement
    # service persists the selected save and enforces the source replacement
    # rule; the combat snapshot narrows this modifier to that one ability.
    "钢铁意志": {
        "combat_start": {
            "modifiers": [
                {
                    "id": "iron_mind:saving_throw_proficiency",
                    "stat": "saving_throw",
                    "operation": "grant_proficiency",
                    "abilities": ["wisdom"],
                    "scope": "self",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "saving_throw_resolution",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
            "defenses": [],
        },
        "advancement": {
            "kind": "typed_proficiency_choice",
            "choice_groups": [
                {
                    "prefix": "save",
                    "kind": "saving_throw",
                    "minimum": 1,
                    "maximum": 1,
                    "allowed_options": ["wisdom", "intelligence", "charisma"],
                }
            ],
            "choice_requirement": {
                "key": "subclass_typed_proficiency",
                "minimum": 1,
                "maximum": 1,
                "strict": True,
                "options_source": "iron_mind_saving_throw_choices",
                "requires_dm_selection": False,
                "reason": (
                    "钢铁意志使用 save:wisdom；已有感知豁免熟练时改用 "
                    "save:intelligence 或 save:charisma。"
                ),
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service_and_saving_throw_resolution",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    "专业预言": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "expert_divination_slot_recovery": {
                "id": "expert_divination_slot_recovery",
                "name": "专业预言",
                "kind": "spell_slot_recovery",
                "activation_window": "after_spell_cast",
                "requirements": [
                    "divination_spell_level_at_least_2",
                    "recovery_slot_lower_than_cast_slot",
                    "recovery_slot_level_at_most_5",
                ],
                "input_requirements": [
                    {
                        "key": "recovery_slot_level",
                        "kind": "player_or_dm_choice",
                        "minimum": 1,
                        "maximum": 5,
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "spell_economy_service",
                    "persistent_state": "spellcasting.slots",
                    "idempotency": "spell_cast_operation",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    # Extra Attack is a subclass grant in several source tables, but the
    # execution contract is the same typed attack-action-count consumer used
    # by core class grants.  The executor does not branch on a subclass ID.
    "额外攻击": {
        "combat_start": {
            "attack_action_count": 2,
            "modifiers": [],
            "defenses": [],
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    # Assassin's Tools is a fixed proficiency grant.  It uses the same
    # persisted proficiency list as class/background grants; the compiler and
    # advancement transaction consume only typed entries, never this feature
    # name.
    "刺客工具": {
        "combat_start": {"modifiers": [], "defenses": []},
        "proficiencies": [
            {
                "kind": "tool",
                "name": "易容工具",
                "operation": "grant",
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
            {
                "kind": "tool",
                "name": "毒药工具",
                "operation": "grant",
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        ],
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    # Mercy's Implements is another fixed proficiency-only grant.  It reuses
    # the exact same typed sheet consumer as Assassin's Tools; the executor
    # has no monk/subclass-specific branch.
    "操命本事": {
        "combat_start": {"modifiers": [], "defenses": []},
        "proficiencies": [
            {
                "kind": "skill",
                "name": "洞悉",
                "operation": "grant",
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
            {
                "kind": "skill",
                "name": "医药",
                "operation": "grant",
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
            {
                "kind": "tool",
                "name": "草药工具",
                "operation": "grant",
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        ],
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    # Superior Critical is a pure threshold modifier.  It reuses the same
    # attack-resolution consumer as the existing generic critical block; the
    # executor reads only the typed stat/value pair.
    "高效重击": {
        "combat_start": {
            "modifiers": [
                {
                    "id": "critical_threshold:18",
                    "stat": "attack_critical_threshold",
                    "operation": "set",
                    "scope": "outgoing",
                    "value": 18,
                    "applies_when": "always",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "attack_resolution",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
            "defenses": [],
        },
        "proficiencies": [],
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    # Remarkable Athlete combines two passive roll modifiers with a critical
    # hit follow-up.  The trigger is generic and keyed only by the declared
    # event/conditions, so another feature can reuse the same after-attack
    # movement contract.
    "运动健将": {
        "combat_start": {
            "modifiers": [
                {
                    "id": "remarkable_athlete:initiative_advantage",
                    "stat": "initiative",
                    "operation": "advantage",
                    "scope": "self",
                    "applies_when": "always",
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                },
                {
                    "id": "remarkable_athlete:athletics_advantage",
                    "stat": "skill_check",
                    "skill": "运动",
                    "operation": "advantage",
                    "scope": "self",
                    "applies_when": "always",
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                },
            ],
            "defenses": [],
        },
        "proficiencies": [],
        "resources": {},
        "actions": {},
        "triggers": [
            {
                "id": "remarkable_athlete:critical_movement",
                "event": "after_attack",
                "when": {"hit": True, "critical_hit": True},
                "effects": [
                    {"kind": "grant_movement_budget", "amount_source": "half_current_speed"},
                    {"kind": "grant_disengage", "expires": "turn_end"},
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_trigger_resolver",
                    "effect_kinds": ["grant_movement_budget", "grant_disengage"],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
        "attack_riders": [],
    },
    # These two entries use the same roll-intervention and resource-lifecycle
    # consumers as core features.  The feature name is only the source-side
    # configuration selector; the executor consumes typed trigger, eligibility,
    # die and resource fields and never dispatches on either feature ID.
    "黑暗强运": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "dark_ones_own_luck": {
                "id": "dark_ones_own_luck",
                "name": "黑暗强运",
                "kind": "roll_intervention",
                "trigger": "after_failed_d20_test",
                "eligibility": {
                    "test_kinds": ["ability_check", "skill_check", "saving_throw"],
                    "resource": {
                        "key": "$feature_resource",
                        "minimum": 1,
                    },
                },
                "operation": {
                    "kind": "add_die",
                    "input_key": "die_roll",
                    "die_sides": 10,
                },
                "input_requirements": [{"key": "die_roll", "kind": "die_roll", "die_sides": 10}],
                "resource": {"key": "$feature_resource", "cost": 1},
                "resource_lifecycle": {
                    "events": [
                        {
                            "trigger": "long_rest",
                            "operation": "set_to_max",
                        }
                    ]
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Dark One's Blessing is a complete zero-HP trigger: the warlock gains
    # temporary hit points when they reduce a hostile creature to 0 HP, or
    # when an ally does so within 10 feet.  Both branches share the same
    # persisted temporary-HP consumer and are kept as separate typed triggers
    # so the killer/range distinction cannot be silently skipped.
    "黑暗赐福": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [
            {
                "id": "dark_ones_blessing:self_kill",
                "event": "after_zero_hp",
                "when": {"source_is_killer": True},
                "target_policy": {"mode": "enemy"},
                "effects": [
                    {
                        "kind": "grant_temporary_hp",
                        "ability_modifier": "charisma",
                        "class_level_source": "魔契师",
                        "minimum": 1,
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "damage_zero_hp_trigger_temporary_hp",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
            {
                "id": "dark_ones_blessing:ally_kill",
                "event": "after_zero_hp",
                "when": {"source_is_killer": False},
                "target_policy": {
                    "mode": "enemy",
                    "range_ft": 10,
                },
                "effects": [
                    {
                        "kind": "grant_temporary_hp",
                        "ability_modifier": "charisma",
                        "class_level_source": "魔契师",
                        "minimum": 1,
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "damage_zero_hp_trigger_temporary_hp",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        ],
        "attack_riders": [],
    },
    "超凡技艺": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "peerless_skill": {
                "id": "peerless_skill",
                "name": "超凡技艺",
                "kind": "roll_intervention",
                "trigger": "after_failed_d20_test",
                "eligibility": {
                    "test_kinds": ["ability_check", "skill_check"],
                    "resource": {
                        "key": "bardic_inspiration",
                        "minimum": 1,
                        "value_bind_as": "die_sides",
                    },
                },
                "operation": {
                    "kind": "add_die",
                    "input_key": "die_roll",
                    "die_sides_expression": "die_sides",
                },
                "input_requirements": [{"key": "die_roll", "kind": "integer"}],
                "resource": {"key": "bardic_inspiration", "cost": 1},
                "resource_lifecycle": {
                    "events": [
                        {
                            "trigger": "short_rest",
                            "operation": "set_to_max",
                        },
                        {
                            "trigger": "long_rest",
                            "operation": "set_to_max",
                        },
                    ]
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    "战争化身": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "subclass:avatar_of_battle:physical_resistance",
                    "kind": "damage_resistance",
                    "damage_types": ["bludgeoning", "piercing", "slashing"],
                    "applies_when": "always",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {},
        "actions": {},
        "attack_riders": [],
    },
    "奉献灵光": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "subclass:aura_of_devotion:charmed_immunity",
                    "kind": "condition_immunity",
                    "condition": "charmed",
                    "scope": "self_and_allies_within_10ft",
                    "applies_when": "within_aura_of_devotion",
                    "ranged_passive": {
                        "range_group": "paladin_aura_radius",
                        "source_scope": "self",
                        "target_relation": "self_and_allies",
                        "range_ft": 10,
                        "requires_grid_position_for_others": True,
                        "source_forbidden_conditions": ["incapacitated"],
                        "stacking": "unique_source",
                        "effect_kind": "condition_immunity",
                    },
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "condition_immunity_resolution",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {},
        "actions": {},
        "attack_riders": [],
    },
    "守御灵光": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "subclass:aura_of_warding:outer_planar_resistance",
                    "kind": "damage_resistance",
                    "damage_types": ["necrotic", "psychic", "radiant"],
                    "scope": "self_and_allies_within_10ft",
                    "applies_when": "within_aura_of_warding",
                    "ranged_passive": {
                        "range_group": "paladin_aura_radius",
                        "source_scope": "self",
                        "target_relation": "self_and_allies",
                        "range_ft": 10,
                        "requires_grid_position_for_others": True,
                        "source_forbidden_conditions": ["incapacitated"],
                        "stacking": "unique_source",
                        "effect_kind": "damage_resistance",
                    },
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {},
        "actions": {},
        "attack_riders": [],
    },
    "法术抗性": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "subclass:spell_resistance:magical_saves",
                    "kind": "saving_throw_advantage",
                    "applies_when": "magical",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "saving_throw_resolution",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                },
                {
                    "id": "subclass:spell_resistance:magical_damage",
                    "kind": "damage_resistance",
                    "damage_types": [
                        "acid",
                        "bludgeoning",
                        "cold",
                        "fire",
                        "force",
                        "lightning",
                        "necrotic",
                        "piercing",
                        "poison",
                        "psychic",
                        "radiant",
                        "slashing",
                        "thunder",
                    ],
                    "applies_when": "magical",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                },
            ],
        },
        "resources": {},
        "actions": {},
        "attack_riders": [],
    },
    "无我狂暴": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "subclass:mindless_rage:condition_immunity",
                    "kind": "condition_immunity",
                    "condition": "charmed",
                    "applies_when": "always",
                    "required_conditions": ["raging"],
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "condition_immunity_resolution",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                },
                {
                    "id": "subclass:mindless_rage:frightened_immunity",
                    "kind": "condition_immunity",
                    "condition": "frightened",
                    "applies_when": "always",
                    "required_conditions": ["raging"],
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "condition_immunity_resolution",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                },
            ],
        },
        "resources": {},
        "actions": {},
        "triggers": [
            {
                "id": "mindless_rage:clear_control_conditions",
                "event": "after_feature_action",
                "action_id": "rage",
                "effects": [
                    {
                        "kind": "remove_conditions",
                        "conditions": ["charmed", "frightened"],
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "feature_action_trigger_resolver",
                    "effect_kinds": ["remove_conditions"],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
        "attack_riders": [],
    },
    # Open Hand's healing feature is a plain bonus-action self-heal.  The
    # generated subclass resource key is bound below at compilation time;
    # this configuration intentionally contains no Open Hand/feature-ID
    # branch in the executor itself.
    "混元体": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "wholeness_of_body": {
                "id": "wholeness_of_body",
                "name": "混元体",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "$feature_resource",
                "resource_cost": 1,
                "target": "self",
                "resolution_kind": "healing",
                "healing_formula": "martial_arts_die+wisdom_modifier",
                "dice_key": "martial_arts_die",
                "minimum_healing": 1,
                "resource_lifecycle": {
                    "events": [{"trigger": "long_rest", "operation": "set_to_max"}]
                },
                "effects": [{"kind": "healing"}],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action",
                    "effect_kinds": ["healing"],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Healing-dice pools are a reusable action contract.  The pool key is
    # bound from the subclass resource compiler; the combat executor only
    # consumes the declared die size, per-use cap, target policy and lifecycle.
    "神之勇者": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "warrior_of_the_gods": {
                "id": "warrior_of_the_gods",
                "name": "神之勇者",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "$feature_resource",
                "resource_cost": 0,
                "resource_cost_mode": "dice_count",
                "target": "self",
                "target_policy": {"mode": "self"},
                "resolution_kind": "healing",
                "healing_formula": "healing_dice_pool",
                "healing_dice": {
                    "die_size": 12,
                    "max_dice": 4,
                },
                "resource_lifecycle": {
                    "events": [{"trigger": "long_rest", "operation": "set_to_max"}]
                },
                "effects": [{"kind": "healing"}],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action",
                    "effect_kinds": ["healing"],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    "治疗之光": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "healing_light": {
                "id": "healing_light",
                "name": "治疗之光",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "$feature_resource",
                "resource_cost": 0,
                "resource_cost_mode": "dice_count",
                "target": "ally_or_self",
                "target_policy": {
                    "mode": "ally_or_self",
                    "same_faction": True,
                    "range_ft": 60,
                },
                "resolution_kind": "healing",
                "healing_formula": "healing_dice_pool",
                "healing_dice": {
                    "die_size": 6,
                    "max_dice_formula": "max(1, charisma_modifier)",
                },
                "resource_lifecycle": {
                    "events": [{"trigger": "long_rest", "operation": "set_to_max"}]
                },
                "effects": [{"kind": "healing"}],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action",
                    "effect_kinds": ["healing"],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Hand of Harm is a generic opt-in post-hit damage rider.  The resolver
    # binds the current martial-arts die and Wisdom modifier from the
    # authoritative combat snapshot; the player/DM still supplies the actual
    # reported damage total.
    "夺命之手": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [
            {
                "id": "hand_of_harm:bonus_damage",
                "kind": "post_hit_rider",
                "trigger": "after_hit",
                "frequency": "once_per_turn",
                "activation": {
                    "input_key": "activate_hand_of_harm",
                    "label": "消耗1点功力发动夺命之手",
                },
                "eligibility": {
                    "actor_entity_types": ["character"],
                    "target_relations": ["enemy"],
                    "action_tags_any": ["unarmed", "monk_weapon"],
                },
                "resource": {"key": "focus", "amount": 1},
                "damage": {
                    "id": "hand_of_harm:necrotic",
                    "expression": "@martial_arts_die+@wisdom_modifier",
                    "damage_type": "necrotic",
                    "input_key": "hand_of_harm_total",
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "post_hit_rider_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
    },
    # Hand of Healing is exposed as the same typed healing action used by
    # other feature resources.  Its free Flurry replacement is intentionally
    # left as a separate partial boundary until Flurry has a structured action
    # window; the ordinary magic-action use is nevertheless executable.
    "予命之手": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "hand_of_healing": {
                "id": "hand_of_healing",
                "name": "予命之手",
                "kind": "feature_action",
                "action_cost": "action",
                "resource_key": "$feature_resource",
                "resource_cost": 1,
                "target": "ally_or_self",
                "target_policy": {
                    "mode": "ally_or_self",
                    "same_faction": True,
                    "range_ft": 5,
                },
                "resolution_kind": "healing",
                "healing_formula": "martial_arts_die+wisdom_modifier",
                "dice_key": "martial_arts_die",
                "condition_cure_options": [],
                "effects": [{"kind": "healing"}],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action",
                    "effect_kinds": ["healing"],
                },
                "automation_status": "partial",
                "requires_dm_adjudication": False,
                "note": "普通魔法动作治疗已闭环；疾风连击替换时免费使用仍需动作窗口积木。",
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Physician's Touch is an overlay on the already executable Hand of Harm
    # rider.  Overlays are applied by the compiler using declared typed IDs;
    # the combat executor remains unaware of subclass names.
    "生死之触": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "attack_rider_overlays": [
            {
                "target_id": "hand_of_harm:bonus_damage",
                "on_hit": [
                    {
                        "id": "hand_of_harm:poisoned",
                        "kind": "condition",
                        "operation": "apply",
                        "condition": "poisoned",
                        "duration": {"unit": "until_source_turn_end"},
                    }
                ],
            }
        ],
        "action_overlays": [
            {
                "target_id": "hand_of_healing",
                "condition_cure_options": [
                    "blinded",
                    "deafened",
                    "paralyzed",
                    "poisoned",
                    "stunned",
                ],
            }
        ],
        "runtime_execution": {
            "status": "ready",
            "consumer": "attack_rider_resolver",
        },
        "automation_status": "partial",
        "requires_dm_adjudication": True,
        "note": "已接入命中后中毒覆盖；予命之手的状态解除/疾风连击替换仍需独立动作积木。",
    },
    # Divine Fury and Dreadful Strikes share the persisted post-hit rider
    # consumer.  Their only dynamic values are authoritative class-level
    # bindings; the executor does not branch on either subclass identity.
    "神性之怒": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [
            {
                "id": "divine_fury:bonus_damage",
                "kind": "post_hit_rider",
                "trigger": "after_hit",
                "frequency": "once_per_turn",
                "eligibility": {
                    "actor_entity_types": ["character"],
                    "actor_conditions_all": ["raging"],
                    "target_relations": ["enemy"],
                    "action_tags_any": ["weapon", "unarmed"],
                },
                "choice": {
                    "input_key": "divine_fury_damage_type",
                    "options": [
                        {"key": "radiant", "label": "光耀"},
                        {"key": "necrotic", "label": "暗蚀"},
                    ],
                },
                "damage": {
                    "id": "divine_fury:damage",
                    "expression": "1d6+@barbarian_level_half",
                    "damage_type": "radiant",
                    "damage_type_source": "divine_fury_damage_type",
                    "damage_type_options": ["radiant", "necrotic"],
                    "input_key": "divine_fury_total",
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "post_hit_rider_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
    },
    "哀惧灵袭": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [
            {
                "id": "dreadful_strikes:bonus_damage",
                "kind": "post_hit_rider",
                "trigger": "after_hit",
                "frequency": "once_per_target_per_turn",
                "eligibility": {
                    "actor_entity_types": ["character"],
                    "target_relations": ["enemy"],
                    "action_tags_all": ["weapon"],
                },
                "damage": {
                    "id": "dreadful_strikes:psychic",
                    "expression": "@dreadful_strikes_die",
                    "damage_type": "psychic",
                    "input_key": "dreadful_strikes_total",
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "post_hit_rider_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
    },
    "精通重击": {
        "combat_start": {
            "modifiers": [
                {
                    "id": "subclass:improved_critical:threshold",
                    "stat": "attack_critical_threshold",
                    "operation": "set",
                    "scope": "outgoing",
                    "value": 19,
                    "applies_when": "always",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "attack_resolution",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
            "defenses": [],
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    "奥法打击": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [
            {
                "id": "eldritch_strike:next_spell_save",
                "kind": "post_hit_rider",
                "trigger": "after_hit",
                "frequency": "each_eligible_hit",
                "eligibility": {
                    "actor_entity_types": ["character"],
                    "target_relations": ["enemy"],
                    "action_tags_all": ["attack", "weapon"],
                },
                "on_hit": [
                    {
                        "id": "eldritch_strike:next_save_disadvantage",
                        "kind": "modifier",
                        "stat": "saving_throw",
                        "scope": "incoming",
                        "operation": "disadvantage",
                        "duration": {"unit": "until_next_save"},
                        "source": "奥法打击：对抗施法者法术的下一次豁免具有劣势",
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "post_hit_rider_and_source_bound_spell_save_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
    },
    "龙族体魄": {
        "combat_start": {
            "modifiers": [
                {
                    "id": "draconic_resilience:unarmored_ac",
                    "stat": "armor_class",
                    "operation": "set_base_formula",
                    "formula": "10+dexterity_modifier+charisma_modifier",
                    "scope": "self",
                    "requirements": ["not_wearing_armor"],
                    "shield_allowed": False,
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "unarmored_defense_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
            "defenses": [],
        },
        "advancement": {
            "kind": "hit_points_by_class_level",
            "minimum_class_level": 3,
            "initial_bonus": 3,
            "per_level_bonus": 1,
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    "龙翼": {
        "combat_start": {
            "modifiers": [],
            "defenses": [],
            "movement_modes": [
                {
                    "id": "dragon_wings:flight",
                    "mode": "fly",
                    "speed_ft": 60,
                    "applies_when": "dragon_wings",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "turn_budget_movement_mode_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {
            "dragon_wings": {
                "key": "dragon_wings",
                "label": "龙翼",
                "max": 1,
                "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "actions": {
            "dragon_wings": {
                "id": "dragon_wings",
                "name": "龙翼",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "target": "self",
                "resource_key": "dragon_wings",
                "resource_cost": 1,
                "effects": [
                    {
                        "kind": "activate_duration_condition",
                        "condition": "dragon_wings",
                        "duration_unit": "minutes",
                        "duration_value": 60,
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action_and_turn_budget_movement_mode_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
            "reset_dragon_wings": {
                "id": "reset_dragon_wings",
                "name": "龙翼（术法点重置）",
                "kind": "feature_action",
                "action_cost": "none",
                "target": "self",
                "resource_key": "sorcery_points",
                "resource_cost": 3,
                "effects": [
                    {
                        "kind": "restore_resource",
                        "resource_key": "dragon_wings",
                        "operation": "set_to_max",
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action_resource_restore",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        },
        "triggers": [],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    "勇战英豪": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "heroic_inspiration": {
                "id": "heroic_inspiration",
                "name": "勇战英豪",
                "kind": "roll_intervention",
                "trigger": "after_d20_test",
                "eligibility": {
                    "entity_types": ["character"],
                    "test_kinds": ["ability_check", "skill_check", "saving_throw", "armor_class"],
                    "state": {"key": "heroic_inspiration"},
                },
                "operation": {"kind": "reroll", "selection": "replacement"},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                    "producer": "turn_start_feature_state",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [
            {
                "id": "heroic_warrior:turn_start",
                "event": "turn_start",
                "effects": [
                    {
                        "kind": "grant_feature_state_if_missing",
                        "state_key": "heroic_inspiration",
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "turn_start_feature_state_producer",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    "幻影化形": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {
            "illusory_self": {
                "key": "illusory_self",
                "label": "幻影化形",
                "max": 1,
                "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
                "reset_options": {
                    "kind": "spell_slot",
                    "minimum_level": 2,
                    "cost": 1,
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "actions": {
            "illusory_self": {
                "id": "illusory_self",
                "name": "幻影化形",
                "kind": "feature_action",
                "action_cost": "reaction",
                "target": "self",
                "trigger": {
                    "event": "attacker_hits_self",
                    "timing": "before_damage",
                    "requirements": ["attacker_visible"],
                },
                "resource": {"key": "illusory_self", "cost": 1},
                "pre_damage_intervention": {
                    "kind": "pre_damage_intervention",
                    "eligibility": {
                        "entity_types": ["character"],
                        "damage_types": "all",
                        "forbidden_conditions": ["incapacitated"],
                    },
                    "input_requirements": [],
                    "damage_transform": {"operation": "set_zero"},
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "pre_damage_reaction_window",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
    # Superior Hunter's Defense is a reaction after taking damage.  The
    # selected concrete damage type is bound by the combat event itself; the
    # generic pre-damage consumer persists a reversible resistance effect
    # through the target's turn end, then the normal damage-defense resolver
    # applies it to every matching component.
    "高阶防守战术": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "superior_hunters_defense": {
                "id": "superior_hunters_defense",
                "name": "高阶防守战术",
                "kind": "feature_action",
                "action_cost": "reaction",
                "target": "self",
                "trigger": {"event": "takes_damage", "timing": "before_damage"},
                "pre_damage_intervention": {
                    "kind": "pre_damage_intervention",
                    "eligibility": {
                        "entity_types": ["character"],
                        "damage_types": "all",
                        "forbidden_conditions": ["incapacitated"],
                    },
                    "input_requirements": [],
                    "damage_transform": {"operation": "resistance"},
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "pre_damage_reaction_window_and_damage_defense_resolver",
                    "persistence": "combat_effect_until_target_turn_end",
                    "idempotency": "source_damage_operation_key",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    # War Priest is a direct bonus-action weapon or unarmed attack.  The
    # player attack endpoint receives the selected base attack profile (for
    # example a configured mace or unarmed strike), while this typed action
    # owns the bonus-action economy, Wisdom-scaled pool, target range and
    # short/long-rest recovery parsed from the source feature.
    "战争祭司": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "war_priest_attack": {
                "id": "war_priest_attack",
                "name": "战争祭司",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "$feature_resource",
                "resource_cost": 1,
                "target_disposition": "enemy",
                "range": "5尺",
                "resolution_kind": "weapon_attack",
                "feature_attack_profile_input_key": "weapon_action_name",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_attack_resolution",
                    "input": "player_selected_weapon_or_unarmed_action",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    # Fiendish Resilience stores the player's short/long-rest damage-type
    # choice in the character resource JSON; the combat resolver reads that
    # persisted selection rather than guessing from the feature name.
    "邪魔体魄": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "fiendish_resilience:selected_resistance",
                    "kind": "damage_resistance",
                    "damage_types": [],
                    "selection_resource_key": "fiendish_resilience_choice",
                    "selection_options": [
                        "acid",
                        "bludgeoning",
                        "cold",
                        "fire",
                        "lightning",
                        "necrotic",
                        "piercing",
                        "poison",
                        "psychic",
                        "radiant",
                        "slashing",
                        "thunder",
                    ],
                    "applies_when": "selected_damage_type",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                        "selection_source": "character_resource",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {},
        "actions": {
            "fiendish_resilience_choice": {
                "id": "fiendish_resilience_choice",
                "name": "邪魔体魄（休息选择抗性）",
                "kind": "rest_choice",
                "trigger": "short_or_long_rest",
                "choice_key": "fiendish_resilience_choice",
                "choice_options": [
                    "acid",
                    "bludgeoning",
                    "cold",
                    "fire",
                    "lightning",
                    "necrotic",
                    "piercing",
                    "poison",
                    "psychic",
                    "radiant",
                    "slashing",
                    "thunder",
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "rest_feature_choice_persistence",
                    "input": "player_selected_damage_type",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    "光耀之魂": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "radiant_soul:radiant_resistance",
                    "kind": "damage_resistance",
                    "damage_types": ["radiant"],
                    "applies_when": "always",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [
            {
                "id": "radiant_soul:bonus_damage",
                "kind": "bonus_damage",
                "value": "0",
                "modifier_source": "charisma_modifier",
                "damage_type": "spell_damage_type",
                "applies_when": "radiant_soul_spell_damage",
                "frequency": "once_per_turn",
                "eligibility_input": "radiant_soul",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_rider_resolver",
                    "input": "attack_rider_eligibility.radiant_soul + radiant_soul_target_id",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    "元素亲和": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "elemental_affinity:selected_resistance",
                    "kind": "damage_resistance",
                    "damage_types": [],
                    "applies_when": "always",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                        "selection_source": "advancement_choice",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [
            {
                "id": "elemental_affinity:bonus_damage",
                "kind": "bonus_damage",
                "value": "0",
                "modifier_source": "charisma_modifier",
                "damage_type": "spell_damage_type",
                "applies_when": "elemental_affinity_spell_damage",
                "frequency": "once_per_turn",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_rider_resolver",
                    "selection_source": "advancement_choice",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    # Guarded Mind combines a permanent psychic resistance with an optional
    # turn-start cleanup. The action consumes the same subclass psionic-die
    # pool produced by Psionic Power and takes the selected condition from
    # the player's structured feature-action input.
    "意念守护": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "guarded_mind:psychic_resistance",
                    "kind": "damage_resistance",
                    "damage_types": ["psychic"],
                    "applies_when": "always",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            ],
        },
        "resources": {},
        "actions": {
            "guarded_mind_clear": {
                "id": "guarded_mind_clear",
                "name": "意念守护（清除控制）",
                "kind": "feature_action",
                "action_cost": "none",
                "activation_window": "turn_start",
                "resource_key": "$feature_resource",
                "resource_cost": 1,
                "target": "self",
                "resolution_kind": "condition_removal",
                "condition_removal_options": ["charmed", "frightened"],
                "effects": [{"kind": "condition_removal"}],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action",
                    "effect_kinds": ["condition_removal"],
                    "input": "player_selected_condition",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        },
        "triggers": [],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    "思维之盾": {
        "combat_start": {
            "modifiers": [],
            "defenses": [
                {
                    "id": "thought_shield:psychic_resistance",
                    "kind": "damage_resistance",
                    "damage_types": ["psychic"],
                    "applies_when": "always",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_defense_resolver",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                },
                {
                    "id": "thought_shield:psychic_reflection",
                    "kind": "damage_reflection",
                    "damage_types": ["psychic"],
                    "reflection": "equal_adjusted_damage_to_source",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "damage_resolution",
                    },
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                },
            ],
        },
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
    },
    "奥能冲锋": {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "triggers": [
            {
                "id": "arcane_charge:after_action_surge",
                "event": "after_feature_action",
                "action_id": "action_surge",
                "effects": [{"kind": "teleport", "max_distance_ft": 30}],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "feature_action_trigger_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
        "attack_riders": [],
    },
    "灵魂之刃": {
        "automation_status": "partial",
        "requires_dm_adjudication": True,
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {
            "psychic_teleportation": {
                "id": "psychic_teleportation",
                "name": "心灵传送",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "$feature_resource",
                "resource_cost": 1,
                "target": "self",
                "effects": [{"kind": "teleport", "roll_multiplier_ft": 10}],
                "runtime_execution": {"status": "ready", "consumer": "combat_feature_action"},
                "automation_status": "partial",
                "requires_dm_adjudication": True,
                "partial_reason": "心灵传送已可执行；寻的斩击尚未接入未命中攻击重算窗口。",
            }
        },
        "triggers": [],
        "attack_riders": [],
    },
}
# The source pack uses both translated labels for Healing Light.  Keep the
# same configuration contract for the alias; the executor remains completely
# unaware of either feature name.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["治愈之光"] = SUBCLASS_FEATURE_RUNTIME_CONFIGS["治疗之光"]

# Circle of the Land's Natural Recovery is a deterministic short-rest
# recovery.  The player still chooses the individual spell-slot levels; the
# rest service receives that choice explicitly and validates the combined
# level budget instead of inventing a slot distribution.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["自然恢复"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {},
    "actions": {
        "natural_recovery": {
            "id": "natural_recovery",
            "name": "自然恢复",
            "kind": "rest_recovery",
            "trigger": "short_rest",
            "resource_key": "$feature_resource",
            "resource_cost": 1,
            "restore_resource_prefix": "spell_slots_",
            "maximum_total_levels_formula": "half_class_level_round_up",
            "maximum_slot_level": 5,
            "reset_trigger": "long_rest",
            "runtime_execution": {
                "status": "ready",
                "consumer": "rest_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": (
                "短休结束时选择恢复总环阶不超过德鲁伊等级一半（向上取整）的1至5环法术位；"
                "使用权长休恢复。"
            ),
        }
    },
    "triggers": [],
    "attack_riders": [],
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["百折不挠"] = {
    "combat_start": {
        "modifiers": [],
        "defenses": [
            {
                "id": "survivor:death_save_advantage",
                "kind": "death_save_advantage",
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
            {
                "id": "survivor:death_save_18_is_20",
                "kind": "death_save_success_threshold",
                "minimum_roll": 18,
                "treat_as": 20,
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        ],
    },
    "resources": {},
    "actions": {},
    "triggers": [
        {
            "id": "survivor:turn_start_bloodied_healing",
            "event": "turn_start",
            "effects": [
                {
                    "kind": "restore_hit_points_if_bloodied",
                    "amount": 5,
                    "ability_modifier": "constitution",
                    "minimum": 1,
                }
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "turn_start_feature_healing",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    ],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

# Otherworldly Glamour has two coupled effects: a wisdom-scaled bonus on every
# Charisma ability check and one explicitly chosen skill proficiency.  The
# modifier is consumed by the player-roll resolver; the typed choice is
# persisted by the existing subclass advancement consumer.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["妖冶娴都"] = {
    "combat_start": {
        "modifiers": [
            {
                "id": "otherworldly_glamour:charisma_check_bonus",
                "stat": "ability_check",
                "ability": "charisma",
                "operation": "add",
                "value_source": "wisdom_modifier",
                "scope": "self",
                "applies_when": "every_charisma_ability_check",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
        "defenses": [],
    },
    "resources": {},
    "actions": {},
    "triggers": [],
    "attack_riders": [],
    "advancement": {
        "kind": "proficiency_choice",
        "option_kind": "skill",
        "operation": "grant_proficiency",
        "allowed_options": "supported_skills",
        "choice_requirement": {
            "key": "subclass_skill_proficiency",
            "minimum": 1,
            "maximum": 1,
            "strict": True,
            "options_source": "supported_skill_registry",
            "requires_dm_selection": False,
        },
        "runtime_execution": {
            "status": "ready",
            "consumer": "advancement_service",
        },
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

# Frenzy is a first-hit rider, not a second rage implementation.  The
# existing attack-rider path supplies the reported d6 total; this contract
# only binds the rage-damage scaling and the authoritative reckless/raging
# conditions.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["狂怒"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {},
    "actions": {},
    "triggers": [],
    "attack_riders": [
        {
            "id": "frenzy:bonus_damage",
            "kind": "bonus_damage",
            "value": "1d6",
            "dice_count_source": "rage_damage",
            "damage_type": "weapon_damage_type",
            "applies_when": "raging_reckless_strength_weapon_attack",
            "frequency": "once_per_turn",
            "runtime_execution": {
                "status": "ready",
                "consumer": "attack_rider_resolver",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    ],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

# Nature's Ward consumes the terrain selected by Circle of the Land Spells.
# The selection is a long-rest input, persisted under one stable resource key;
# the defense resolver then reads that key for the matching resistance while
# the condition-immunity consumer applies poison immunity independently.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["自然守御"] = {
    "combat_start": {
        "modifiers": [],
        "defenses": [
            {
                "id": "nature_ward:poison_immunity",
                "kind": "condition_immunity",
                "condition": "poisoned",
                "applies_when": "always",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "condition_immunity_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
            {
                "id": "nature_ward:terrain_resistance",
                "kind": "damage_resistance",
                "selection_resource_key": "circle_land_terrain",
                "selection_options": ["arid", "polar", "temperate", "tropical"],
                "selection_damage_types": {
                    "arid": ["fire"],
                    "polar": ["cold"],
                    "temperate": ["lightning"],
                    "tropical": ["poison"],
                },
                "damage_types": [],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "damage_defense_resolver",
                    "selection_source": "long_rest",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        ],
    },
    "resources": {},
    "actions": {
        "terrain_choice": {
            "id": "circle_land_terrain_choice",
            "name": "结社地形选择",
            "kind": "rest_choice",
            "trigger": "long_rest",
            "choice_key": "circle_land_terrain",
            "choice_options": ["arid", "polar", "temperate", "tropical"],
            "runtime_execution": {
                "status": "ready",
                "consumer": "rest_service_and_damage_defense_resolver",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

# Combat Inspiration changes how a granted Bardic Inspiration die can be spent:
# the recipient chooses AC protection after being hit or extra damage after a
# hit.  The attack resolver consumes the same persisted die and idempotency
# record as ordinary Bardic Inspiration; this contract only declares the two
# legal post-roll modes.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["战斗激励"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {},
    "actions": {
        "combat_inspiration": {
            "id": "combat_inspiration",
            "name": "战斗激励",
            "kind": "attack_roll_intervention",
            "source_die_key": "bardic_inspiration_die",
            "modes": ["defense", "offense"],
            "input_requirements": [
                {
                    "key": "bardic_inspiration_mode",
                    "kind": "enum",
                    "options": ["defense", "offense"],
                },
                {"key": "bardic_inspiration_total", "kind": "die_roll"},
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "player_attack_resolver",
                "persisted_die_consumer": "bardic_inspiration_die",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

# Superiority dice are one shared resource across every Battle Master
# feature.  The resource producer is bound to the exact class-level table by
# ``_subclass_resource_update``; these three maneuvers then reuse the existing
# player-roll intervention window instead of creating a second dice resolver.
# The parent feature remains partial until every selected maneuver has its
# complete consumer, but the connected roll maneuvers are fail-closed and
# cannot expose an unlearned option.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["卓越战技"] = {
    "combat_start": {
        "modifiers": [],
        "defenses": [],
        "attack_slot_replacements": [
            {
                "id": "battle_master:commander_strike",
                "kind": "replace_attack_with_ally_attack",
                "maneuver_id": "commander_strike",
                "slot_cost": 1,
                "uses_per_sequence": 1,
                "ally_action_cost": "reaction",
                "attack_profile": "weapon_or_unarmed",
                "payment": {
                    "resource_kind": "superiority_dice",
                    "resource_cost": 1,
                    "actual_die_value": True,
                    "resource_die_size": True,
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_sequence_ally_triggered_attack_window",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
    },
    "resources": {
        "$feature_resource": {
            "key": "$feature_resource",
            "label": "卓越骰",
            "max": 4,
            "max_mode": "exact",
            "value": "d8",
            "die_size": 8,
            "resource_kind": "superiority_dice",
            "recovery": "both",
            "recovery_events": [
                {"rest": "short_rest", "operation": "set_to_max"},
                {"rest": "long_rest", "operation": "set_to_max"},
            ],
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "actions": {
        "ambush": {
            "id": "battle_master:ambush",
            "kind": "roll_intervention",
            "maneuver_id": "ambush",
            "trigger": "after_d20_test",
            "operation": {
                "kind": "add_die",
                "input_key": "superiority_die_roll",
                "die_sides_expression": "superiority_die_sides",
            },
            "eligibility": {
                "entity_types": ["character"],
                "test_kinds": ["skill_check"],
                "skills": ["隐匿", "stealth"],
                "forbidden_conditions": ["incapacitated"],
                "resource": {
                    "key": "$feature_resource",
                    "minimum": 1,
                    "value_bind_as": "superiority_die_sides",
                },
            },
            "input_requirements": [{"key": "superiority_die_roll", "kind": "integer"}],
            "window": {"phase": "after_d20_test", "expires": "operation"},
            "action_cost": "none",
            "resource": {"key": "$feature_resource", "cost": 1},
            "runtime_execution": {
                "status": "ready",
                "consumer": "player_roll_resolution",
                "persistence": "character_resource_and_operation_transaction",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
        "commanding_presence": {
            "id": "battle_master:commanding_presence",
            "kind": "roll_intervention",
            "maneuver_id": "commanding_presence",
            "trigger": "after_d20_test",
            "operation": {
                "kind": "add_die",
                "input_key": "superiority_die_roll",
                "die_sides_expression": "superiority_die_sides",
            },
            "eligibility": {
                "entity_types": ["character"],
                "test_kinds": ["ability_check"],
                "abilities": ["charisma"],
                "skills": ["威吓", "表演", "游说", "intimidation", "performance", "persuasion"],
                "resource": {
                    "key": "$feature_resource",
                    "minimum": 1,
                    "value_bind_as": "superiority_die_sides",
                },
            },
            "input_requirements": [{"key": "superiority_die_roll", "kind": "integer"}],
            "window": {"phase": "after_d20_test", "expires": "operation"},
            "action_cost": "none",
            "resource": {"key": "$feature_resource", "cost": 1},
            "runtime_execution": {
                "status": "ready",
                "consumer": "player_roll_resolution",
                "persistence": "character_resource_and_operation_transaction",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
        "tactical_assessment": {
            "id": "battle_master:tactical_assessment",
            "kind": "roll_intervention",
            "maneuver_id": "tactical_assessment",
            "trigger": "after_d20_test",
            "operation": {
                "kind": "add_die",
                "input_key": "superiority_die_roll",
                "die_sides_expression": "superiority_die_sides",
            },
            "eligibility": {
                "entity_types": ["character"],
                "test_kinds": ["ability_check"],
                "abilities": ["intelligence", "wisdom"],
                "skills": ["调查", "历史", "洞悉", "investigation", "history", "insight"],
                "resource": {
                    "key": "$feature_resource",
                    "minimum": 1,
                    "value_bind_as": "superiority_die_sides",
                },
            },
            "input_requirements": [{"key": "superiority_die_roll", "kind": "integer"}],
            "window": {"phase": "after_d20_test", "expires": "operation"},
            "action_cost": "none",
            "resource": {"key": "$feature_resource", "cost": 1},
            "runtime_execution": {
                "status": "ready",
                "consumer": "player_roll_resolution",
                "persistence": "character_resource_and_operation_transaction",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    "triggers": [
        {
            "id": "battle_master:riposte",
            "feature_name": "反击",
            "kind": "triggered_attack",
            "maneuver_id": "riposte",
            "event": "after_enemy_attack_miss",
            "action_cost": "reaction",
            "reaction_trigger": "敌方近战攻击未命中",
            "target_policy": {
                "mode": "event_actor",
                "range_ft": 5,
                "requires_visible_or_audible": True,
            },
            "attack_profile": {"mode": "melee_weapon_or_unarmed"},
            "resource": {"key": "$feature_resource", "cost": 1},
            "runtime_execution": {
                "status": "ready",
                "consumer": "generic_triggered_attack_window_and_player_attack",
                "persistence": "combat_action_window_and_cas",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    ],
    "attack_riders": [],
    "advancement": {
        "kind": "battle_master_maneuver_selection",
        "choice_requirement": {
            "key": "battle_master_maneuvers",
            "minimum": 3,
            "maximum": 3,
            "strict": True,
            "options": [
                *sorted(BATTLE_MASTER_MANEUVER_OPTIONS),
                *sorted(BATTLE_MASTER_MANEUVER_OPTIONS.values()),
            ],
            "options_labels": BATTLE_MASTER_MANEUVER_OPTIONS,
            "requires_dm_selection": False,
            "unique_group": "battle_master_maneuvers",
        },
        "runtime_execution": {
            "status": "ready",
            "consumer": "advancement_service_and_roll_intervention_resolver",
        },
        "automation_status": "partial",
        "requires_dm_adjudication": True,
        "partial_reason": (
            "仅三项检定战技接入；命中后、反应、位移、目标物品和状态分支仍需完整消费者。"
        ),
    },
    "automation_status": "partial",
    "requires_dm_adjudication": True,
}

# These entries describe only the generic event contract.  The combat engine
# consumes event/target/profile/resource fields and never branches on these
# feature names.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["防守战术"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {},
    "actions": {
        "defensive_tactics_choice": {
            "id": "defensive_tactics_choice",
            "name": "防守战术（休息选择）",
            "kind": "rest_choice",
            "trigger": "short_or_long_rest",
            "choice_key": "defensive_tactics",
            "choice_options": ["escape_the_horde", "multiattack_defense"],
            "runtime_execution": {
                "status": "ready",
                "consumer": "rest_service_and_incoming_attack_context",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["斗转星移"] = {
    "combat_start": {
        "modifiers": [],
        "defenses": [
            {
                "id": "subclass:beguiling_defenses:charmed_immunity",
                "kind": "condition_immunity",
                "condition": "charmed",
                "applies_when": "always",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "condition_immunity_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
    },
    "resources": {
        "$feature_resource": {
            "key": "$feature_resource",
            "label": "斗转星移",
            "resource_kind": "feature_uses",
            "max_formula": "fixed_one",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "actions": {
        "beguiling_defenses": {
            "id": "beguiling_defenses",
            "name": "斗转星移",
            "kind": "feature_action",
            "action_cost": "reaction",
            "trigger": {
                "event": "hit_by_attack",
                "timing": "before_damage",
                "requirements": ["attacker_visible"],
            },
            "pre_damage_intervention": {
                "kind": "pre_damage_intervention",
                "eligibility": {
                    "entity_types": ["character"],
                    "damage_types": "all",
                    "forbidden_conditions": ["incapacitated"],
                },
                "input_requirements": [],
                "damage_transform": {
                    "operation": "multiply_each_component",
                    "multiplier": 0.5,
                    "rounding": "floor",
                },
            },
            "resource": {"key": "$feature_resource", "cost": 1},
            "reflection": {
                "kind": "beguiling_reflection",
                "save_ability": "wisdom",
                "save_dc_source": "spellcasting",
                "damage_type": "psychic",
                "damage_basis": "actual_damage_taken",
                "attacker_target": True,
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "pre_damage_reaction_window_and_beguiling_reflection",
                "persistence": "combat_action_window_and_cas",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["如影随行"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {},
    "actions": {
        "shadowy_dodge": {
            "id": "shadowy_dodge",
            "name": "如影随行",
            "kind": "attack_resolution_intervention",
            "action_cost": "reaction",
            "phase": "before_attack_roll_resolution",
            "operation": {"kind": "impose_disadvantage"},
            "eligibility": {
                "entity_types": ["character"],
                "subject": "self",
                "trigger": "attacked_by_visible_creature",
            },
            "input_requirements": [],
            "follow_up": {
                "kind": "teleport_after_attack",
                "parent_action_part": True,
                "action_cost": "none",
                "range_ft": 30,
                "requires_visible_destination": True,
                "requires_unoccupied_destination": True,
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "attack_resolution_intervention_window",
                "persistence": "combat_action_window_and_cas",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["语出惊人"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {},
    "actions": {
        "cutting_words_attack": {
            "id": "cutting_words_attack",
            "name": "语出惊人·攻击检定",
            "kind": "attack_resolution_intervention",
            "action_cost": "reaction",
            "phase": "after_provisional_hit",
            "operation": {
                "kind": "subtract_from_attack_total",
                "amount": "bardic_die",
            },
            "eligibility": {
                "entity_types": ["character"],
                "subject": "visible_creature",
                "range_ft": 60,
                "requires_visible": True,
                "resource": {"key": "bardic_inspiration", "minimum": 1},
            },
            "input_requirements": [
                {
                    "key": "bardic_die",
                    "kind": "die_roll",
                    "die_sides_source": "bardic_inspiration_die",
                }
            ],
            "resource": {"key": "bardic_inspiration", "cost": 1},
            "runtime_execution": {
                "status": "ready",
                "consumer": "attack_resolution_intervention_window",
                "persistence": "combat_action_window_and_cas",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
        "cutting_words_check": {
            "id": "cutting_words_check",
            "name": "语出惊人·属性检定",
            "kind": "roll_intervention",
            "trigger": "after_d20_test",
            "action_cost": "reaction",
            "operation": {
                "kind": "add",
                "amount": "0-bardic_die",
            },
            "eligibility": {
                "entity_types": ["character"],
                "test_kinds": ["ability_check", "skill_check"],
                "success_only": True,
                "resource": {"key": "bardic_inspiration", "minimum": 1},
            },
            "target_policy": {
                "mode": "any",
                "range_ft": 60,
                "requires_visible_or_audible": True,
            },
            "input_requirements": [
                {
                    "key": "bardic_die",
                    "kind": "die_roll",
                    "die_sides_source": "bardic_inspiration_die",
                }
            ],
            "resource": {"key": "bardic_inspiration", "cost": 1},
            "window": {"phase": "after_d20_test", "expires": "operation"},
            "runtime_execution": {
                "status": "ready",
                "consumer": "player_roll_resolution",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
        "cutting_words_damage": {
            "id": "cutting_words_damage",
            "name": "语出惊人·伤害掷骰",
            "kind": "feature_action",
            "action_cost": "reaction",
            "trigger": {
                "event": "takes_damage",
                "timing": "before_damage",
                "requirements": ["attacker_visible"],
            },
            "pre_damage_intervention": {
                "kind": "pre_damage_intervention",
                "eligibility": {
                    "entity_types": ["character"],
                    "damage_types": "all",
                    "range_ft": 60,
                    "requires_visible": True,
                },
                "input_requirements": [
                    {"key": "bardic_die", "kind": "die_roll", "die_sides": 12}
                ],
                "damage_transform": {
                    "operation": "subtract_total",
                    "amount": "bardic_die",
                    "distribution": "components_in_order",
                    "minimum": 0,
                },
            },
            "resource": {"key": "bardic_inspiration", "cost": 1},
            "runtime_execution": {
                "status": "ready",
                "consumer": "pre_damage_reaction_window",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    },
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["辉煌防御"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {
        "$feature_resource": {
            "key": "$feature_resource",
            "label": "辉煌防御",
            "resource_kind": "feature_uses",
            "max_formula": "max(1, charisma_modifier)",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "actions": {
        "glorious_defense": {
            "id": "glorious_defense",
            "name": "辉煌防御",
            "kind": "attack_resolution_intervention",
            "action_cost": "reaction",
            "phase": "after_provisional_hit",
            "operation": {
                "kind": "add_to_target_ac",
                "amount": "max(1, charisma_modifier)",
                "minimum": 1,
            },
            "eligibility": {
                "entity_types": ["character"],
                "subject": "self_or_ally",
                "range_ft": 10,
                "requires_visible": True,
                "resource": {"key": "$feature_resource", "minimum": 1},
            },
            "input_requirements": [],
            "resource": {"key": "$feature_resource", "cost": 1},
            "follow_up": {
                "kind": "triggered_attack_on_miss",
                "parent_action_part": True,
                "action_cost": "none",
                "attack_profile": {"mode": "weapon_only"},
                "target_policy": {
                    "mode": "event_actor",
                    "range_ft": "weapon_reach",
                    "requires_visible_or_audible": True,
                },
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "attack_resolution_intervention_window",
                "persistence": "combat_action_window_and_cas",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["报偿"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {},
    "actions": {},
    "triggers": [
        {
            "id": "retaliation:triggered_attack",
            "feature_name": "报偿",
            "kind": "triggered_attack",
            "event": "after_taking_damage",
            "action_cost": "reaction",
            "reaction_trigger": "受到 5 尺内生物造成的实际伤害",
            "target_policy": {
                "mode": "event_actor",
                "range_ft": 5,
                "requires_visible_or_audible": True,
            },
            "attack_profile": {"mode": "melee_weapon_or_unarmed"},
            "runtime_execution": {
                "status": "ready",
                "consumer": "generic_triggered_attack_window_and_player_attack",
                "persistence": "combat_action_window_and_cas",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    ],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["战斗魔法"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {},
    "actions": {},
    "triggers": [
        {
            "id": "battle_magic:triggered_attack",
            "feature_name": "战斗魔法",
            "kind": "triggered_attack",
            "event": "after_casting_spell",
            "action_cost": "bonus_action",
            "reaction_trigger": "施展施法时间为一动作的法术成功后",
            "target_policy": {
                "mode": "enemy",
                "requires_visible_or_audible": True,
            },
            "attack_profile": {"mode": "weapon_only"},
            "runtime_execution": {
                "status": "ready",
                "consumer": "generic_triggered_attack_window_and_player_attack",
                "persistence": "combat_action_window_and_cas",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    ],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

# Improved Combat changes only the die size of the already-persisted
# superiority-dice resource.  It is therefore a complete typed progression
# contract even while the parent maneuver catalogue remains partial.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["精通战技"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {
        "$feature_resource": {
            "key": "$feature_resource",
            "label": "卓越骰",
            "max": 5,
            "max_mode": "exact",
            "value": "d10",
            "die_size": 10,
            "resource_kind": "superiority_dice",
            "recovery": "both",
            "recovery_events": [
                {"rest": "short_rest", "operation": "set_to_max"},
                {"rest": "long_rest", "operation": "set_to_max"},
            ],
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "actions": {},
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

# Attack-slot replacement contracts are frozen into each Attack action sequence.
# The combat consumer dispatches only on these typed policies; class and feature
# names never enter the transactional resolver.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["战争魔法"] = {
    "combat_start": {
        "modifiers": [],
        "defenses": [],
        "attack_slot_replacements": [
            {
                "id": "replace_attack_with_wizard_cantrip",
                "kind": "replace_attack_with_spell",
                "slot_cost": 1,
                "spell_levels": [0],
                "spellcasting_classes": ["法师", "wizard"],
                "casting_time": "action",
                "uses_per_sequence": 1,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_action_sequence_and_player_spell_action",
                    "persistence": "combat_action_operation_transaction_and_character_resource",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
    },
    "resources": {},
    "actions": {},
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["精通战争魔法"] = {
    "combat_start": {
        "modifiers": [],
        "defenses": [],
        "attack_slot_replacements": [
            {
                "id": "replace_two_attacks_with_wizard_spell",
                "kind": "replace_attack_with_spell",
                "slot_cost": 2,
                "spell_levels": [1, 2],
                "spellcasting_classes": ["法师", "wizard"],
                "casting_time": "action",
                "uses_per_sequence": 1,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_action_sequence_and_player_spell_action",
                    "persistence": "combat_action_operation_transaction_and_character_resource",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        ],
    },
    "resources": {},
    "actions": {},
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

# Moonlight Step is a single bonus-action teleport contract. Its resource is
# parsed from the source's Wisdom-modifier uses and bound to the generated
# subclass resource key; a qualifying spell slot can reset one spent use.
# The second effect is a real turn-end lifecycle state consumed by the attack
# context resolver, so the advantage is granted exactly once after movement.
SUBCLASS_FEATURE_RUNTIME_CONFIGS["月光飞步"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "resources": {},
    "actions": {
        "moonlight_step": {
            "id": "moonlight_step",
            "name": "月光飞步",
            "kind": "feature_action",
            "action_cost": "bonus_action",
            "resource_key": "$feature_resource",
            "resource_cost": 1,
            "target": "self",
            "reset_options": {
                "minimum_spell_slot_level": 2,
                "maximum_spell_slot_level": 9,
                "amount": 1,
            },
            "effects": [
                {"kind": "teleport", "max_distance_ft": 30},
                {
                    "kind": "activate_timed_condition",
                    "condition": "moonlight_step",
                    "expires": "turn_end",
                },
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action_and_attack_context_resolver",
                "effect_kinds": ["teleport", "activate_timed_condition"],
                "input": "explicit_visible_unoccupied_destination",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    },
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["战争训练"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "proficiencies": [
        {
            "kind": "weapon_group",
            "name": "军用武器",
            "operation": "grant",
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
        {
            "kind": "armor",
            "name": "中甲",
            "operation": "grant",
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
        {
            "kind": "armor",
            "name": "盾牌",
            "operation": "grant",
            "automation_status": "full",
            "requires_dm_adjudication": False,
        },
    ],
    "spellcasting": {
        "kind": "spellcasting_focus_permission",
        "spell_class": "吟游诗人",
        "allowed_equipment_kinds": ["weapon"],
        "requires_weapon_proficiency": True,
        "runtime_execution": {
            "status": "ready",
            "consumer": "spell_economy_service",
        },
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    "resources": {},
    "actions": {},
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}

SUBCLASS_FEATURE_RUNTIME_CONFIGS["额外战斗风格"] = {
    "combat_start": {"modifiers": [], "defenses": []},
    "advancement": {
        "kind": "selected_asset_grant",
        "asset_kind": "feat",
        "expected_category": "战斗风格",
        "catalog_source": "feats:战斗风格",
        "duplicate_policy": "forbid",
        "choice_requirement": {
            "key": "additional_fighting_style",
            "minimum": 1,
            "maximum": 1,
            "strict": True,
            "options_source": "feats:战斗风格",
            "selected_asset_kind": "feat",
            "expected_category": "战斗风格",
            "duplicate_policy": "forbid",
            "requires_dm_selection": False,
        },
        "runtime_execution": {
            "status": "ready",
            "consumer": "advancement_service_and_feat_prerequisite_validator",
            "grant_status": "full",
            "effect_status": "separate_contract",
        },
        "automation_status": "full",
        "requires_dm_adjudication": False,
    },
    "resources": {},
    "actions": {},
    "triggers": [],
    "attack_riders": [],
    "automation_status": "full",
    "requires_dm_adjudication": False,
}


def subclass_feature_runtime_definition(
    definition: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return a typed runtime registry for an explicitly supported subclass effect."""

    name = str(definition.get("name") or "").strip()
    config = SUBCLASS_FEATURE_RUNTIME_CONFIGS.get(name)
    if config is None:
        for prefix, candidate in SUBCLASS_FEATURE_RUNTIME_CONFIGS.items():
            if name.startswith(prefix):
                config = candidate
                break
    spell_contract = _subclass_prepared_spell_contract(str(definition.get("description") or ""))
    if config is None and spell_contract is not None:
        return {
            "combat_start": {"modifiers": [], "defenses": []},
            "resources": {},
            "actions": {},
            "triggers": [],
            "attack_riders": [],
            "prepared_spell_list": spell_contract,
        }
    if config is None and (name == "动物语者" or name.startswith("自然语者")):
        spells = ["野兽感官", "动物交谈"] if name == "动物语者" else ["问道自然"]
        return {
            "combat_start": {"modifiers": [], "defenses": []},
            "resources": {},
            "actions": {},
            "triggers": [],
            "attack_riders": [],
            "advancement": {
                "kind": "fixed_spell_grant",
                "spells": spells,
                "grant_class": "owner_class",
                "casting_ability": "wisdom",
                "ritual_only": True,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "advancement_service_and_noncombat_spell_economy",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        }
    if config is None:
        return None
    runtime = deepcopy(config)
    source = {
        "feature_name": name,
        "class_name": str(definition.get("class_name") or ""),
        "class_level": int(definition.get("class_level") or 0),
        "source_record_id": definition.get("source_record_id"),
    }
    for section in ("combat_start",):
        block = runtime.get(section)
        if not isinstance(block, dict):
            continue
        for group in ("modifiers", "defenses"):
            entries = block.get(group)
            if not isinstance(entries, list):
                continue
            block[group] = [{**dict(entry), **source} for entry in entries]
    entries = runtime.get("proficiencies")
    if isinstance(entries, list):
        runtime["proficiencies"] = [{**dict(entry), **source} for entry in entries]
    spellcasting = runtime.get("spellcasting")
    if isinstance(spellcasting, Mapping):
        # A shared source-side config intentionally has no class name of its
        # own.  Bind the selected subclass's owning class here, at compilation
        # time, so downstream consumers receive the same typed source identity
        # as core spellcasting grants without feature-ID branching.
        runtime["spellcasting"] = {
            **dict(spellcasting),
            "class_name": source["class_name"],
            "class_level": source["class_level"],
            "source_record_id": source["source_record_id"],
        }
    advancement = runtime.get("advancement")
    if isinstance(advancement, Mapping):
        runtime["advancement"] = {**dict(advancement), **source}
    return runtime


def subclass_feature_automation_status(definition: Mapping[str, Any]) -> str | None:
    runtime = subclass_feature_runtime_definition(definition)
    if runtime is None:
        return None
    contract = feature_runtime_contract(
        feature_name=str(definition.get("name") or ""),
        class_name=str(definition.get("class_name") or ""),
        class_level=int(definition.get("class_level") or 0),
        definition=runtime,
        kind="subclass_feature",
        source_record_id=(
            str(definition.get("source_record_id"))
            if definition.get("source_record_id") is not None
            else None
        ),
        source_path=(
            str(definition.get("source_path"))
            if definition.get("source_path") is not None
            else None
        ),
        declared_status=(
            str(runtime.get("automation_status"))
            if runtime.get("automation_status") is not None
            else None
        ),
    )
    return str(contract["automation_status"])


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
            "rule_year": str(record.get("normalized_edition") or record.get("edition") or "2014"),
            "content_pack_key": (
                str(record.get("content_pack_key")) if record.get("content_pack_key") else None
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
    count = (
        int(count_match.group(1))
        if count_match
        else {
            "一": 1,
            "二": 1,
            "三": 1,
        }.get(chinese_count.group(1) if chinese_count else "", 1)
    )
    return {
        "key": "subclass_feature_choice",
        "minimum": count,
        "maximum": count,
        "strict": True,
        "options_source": "subclass.feature.description",
        "requires_dm_selection": True,
        "reason": "来源文本要求选择，但选项全集或前置条件未可靠结构化；请由 DM 选择并记录。",
    }


def _subclass_prepared_spell_contract(description: str) -> dict[str, Any] | None:
    """Recognise only fixed, always-prepared spell lists.

    This is deliberately narrower than the generic word ``法术``.  A list is
    eligible only when the source explicitly says the spells are always
    prepared; choice-bound lists (for example, ``你选择的这些法术``) remain
    DM/partial until their selection is persisted by a separate choice block.
    The executor later resolves names against the authoritative spell catalog.
    """

    text = str(description or "")
    if "你选择的这些法术" in text or "自选法术" in text:
        return None
    if not re.search(r"(?:始终|总是)准备着(?:特定的法术|表中对应的法术)", text):
        return None
    if not re.search(r"(?:法术表|Spells|准备法术)", text, re.IGNORECASE):
        return None
    return {
        "kind": "always_prepared_spell_list",
        "source": "subclass_feature_description",
        "runtime_execution": {
            "status": "ready",
            "consumer": "spell_selection_and_preparation",
        },
        "automation_status": "full",
        "requires_dm_adjudication": False,
    }


def _subclass_resource_update(
    definition: dict[str, Any],
    *,
    ability_scores: dict[str, int] | None,
    current_class_level: int | None = None,
) -> tuple[str, dict[str, Any]] | None:
    description = str(definition.get("description") or "")
    feature_name = str(definition.get("name") or "").strip()
    subclass_name = str(definition.get("subclass_name") or "").strip()
    if subclass_name == "战斗大师" and str(definition.get("class_name") or "") == "战士":
        if feature_name.startswith(("卓越战技", "精通战技", "坚韧", "究极战技")):
            level = int(current_class_level or definition.get("class_level") or 0)
            if level >= 18:
                die_size, maximum = 12, 6
            elif level >= 15:
                die_size, maximum = 10, 6
            elif level >= 10:
                die_size, maximum = 10, 5
            elif level >= 7:
                die_size, maximum = 8, 5
            else:
                die_size, maximum = 8, 4
            return "superiority_dice", {
                "label": "卓越骰",
                "max": maximum,
                "max_mode": "exact",
                "max_formula": "battle_master_superiority_dice_table",
                "value": f"d{die_size}",
                "die_size": die_size,
                "resource_kind": "superiority_dice",
                "recovery": "both",
                "recovery_events": [
                    {"rest": "short_rest", "operation": "set_to_max"},
                    {"rest": "long_rest", "operation": "set_to_max"},
                ],
                "source": (
                    f"{definition.get('source_path') or definition.get('source_record_id')}"
                    f" · {definition.get('class_level')}级{feature_name}"
                ),
                "requires_dm_adjudication": False,
                "automation_status": "full",
            }
    if feature_name == "信实坐骑":
        return "faithful_steed", {
            "label": "信实坐骑免费施法",
            "max": 1,
            "max_formula": "fixed_one",
            "resource_kind": "free_spell_cast",
            "recovery": "long_rest",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "source": (
                f"{definition.get('source_path') or definition.get('source_record_id')}"
                f" · {definition.get('class_level')}级{feature_name}"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        }
    if feature_name.startswith("预兆"):
        return "portent_dice", {
            "label": "预兆骰",
            "max": 2,
            "max_formula": "submitted_long_rest_pool",
            "resource_kind": "d20_pool",
            "recovery": "long_rest",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "source": (
                f"{definition.get('source_path') or definition.get('source_record_id')}"
                f" · {definition.get('class_level')}级{feature_name}"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        }
    if feature_name.startswith("高等预兆"):
        return "portent_dice", {
            "label": "高等预兆骰",
            "max": 3,
            "max_formula": "submitted_long_rest_pool",
            "resource_kind": "d20_pool",
            "recovery": "long_rest",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "source": (
                f"{definition.get('source_path') or definition.get('source_record_id')}"
                f" · {definition.get('class_level')}级{feature_name}"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        }
    if feature_name.startswith("辉煌防御"):
        ability = "charisma"
        maximum = (
            max(1, _ability_modifier(ability_scores, ability) or 0)
            if ability_scores is not None
            else None
        )
        resource = {
            "label": feature_name,
            "max_formula": "max(1, charisma_modifier)",
            "resource_kind": "feature_uses",
            "recovery": "long_rest",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "source": (
                f"{definition.get('source_path') or definition.get('source_record_id')}"
                f" · {definition.get('class_level')}级{feature_name}"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        }
        if maximum is not None:
            resource["max"] = maximum
        return "glorious_defense", resource
    if feature_name.startswith("战神祝福"):
        ability = "wisdom"
        maximum = (
            max(1, _ability_modifier(ability_scores, ability) or 0)
            if ability_scores is not None
            else None
        )
        resource: dict[str, Any] = {
            "label": feature_name,
            "max_formula": "max(1, wisdom_modifier)",
            "resource_kind": "feature_uses",
            "recovery": "long_rest",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "source": (
                f"{definition.get('source_path') or definition.get('source_record_id')}"
                f" · {definition.get('class_level')}级{feature_name}"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        }
        if maximum is not None:
            resource["max"] = maximum
        return "war_gods_blessing", resource
    if feature_name.startswith("斗转星移"):
        return "beguiling_defenses", {
            "label": "斗转星移",
            "max": 1,
            "max_formula": "fixed_one",
            "resource_kind": "feature_uses",
            "recovery": "long_rest",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "source": (
                f"{definition.get('source_path') or definition.get('source_record_id')}"
                f" · {definition.get('class_level')}级{feature_name}"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        }
    if feature_name.startswith("自然恢复"):
        return "natural_recovery", {
            "label": feature_name,
            "max": 1,
            "max_formula": "fixed_one",
            "recovery": "long_rest",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "source": (
                f"{definition.get('source_path') or definition.get('source_record_id')}"
                f" · {definition.get('class_level')}级{feature_name}"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        }
    healing_pool = re.search(
        r"(?:有着|拥有)\s*(\d+)\s*枚\s*d(\d+)\s*(?:骰子|骰)?的治疗池",
        description,
        re.IGNORECASE,
    )
    scaling_healing_pool = re.search(
        r"(?:有着|拥有)\s*1\s*\+\s*你的[^。；;]{0,24}?等级\s*枚\s*d(\d+)\s*骰子?的骰池",
        description,
        re.IGNORECASE,
    )
    # Psi Warrior and Soulknife share the official six-step psionic-die
    # table. Bind all features in one owning class to one stable pool so a
    # later feature consumes the resource produced by the level-3 feature.
    if "灵能骰" in description and str(definition.get("class_name") or "") in {
        "战士",
        "游荡者",
    }:
        level = int(current_class_level or definition.get("class_level") or 0)
        if level >= 17:
            die_size, maximum = 12, 12
        elif level >= 13:
            die_size, maximum = 10, 10
        elif level >= 11:
            die_size, maximum = 10, 8
        elif level >= 9:
            die_size, maximum = 8, 8
        elif level >= 5:
            die_size, maximum = 8, 6
        else:
            die_size, maximum = 6, 4
        class_name = str(definition["class_name"])
        key = f"psionic_dice:{class_name}"
        return key, {
            "label": f"{class_name}灵能骰",
            "max": maximum,
            "max_formula": "psionic_energy_dice_table",
            "die_size": die_size,
            "resource_kind": "psionic_dice",
            "recovery": "both",
            "recovery_events": [
                {"rest": "short_rest", "operation": "restore", "amount": 1},
                {"rest": "long_rest", "operation": "set_to_max"},
            ],
            "source": (
                f"{definition.get('source_path') or definition.get('source_record_id')}"
                f" · {definition.get('class_level')}级灵能力量"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        }
    if healing_pool or scaling_healing_pool:
        source_id = str(definition.get("source_record_id") or definition.get("id") or "")
        fingerprint = re.sub(r"[^a-z0-9]+", "", source_id.casefold())[-18:]
        if not fingerprint:
            fingerprint = hashlib.sha256(str(definition.get("id") or "").encode()).hexdigest()[:18]
        die_size = int((healing_pool or scaling_healing_pool).group(2 if healing_pool else 1))
        level = int(current_class_level or definition.get("class_level") or 0)
        maximum = int(healing_pool.group(1)) if healing_pool else 1 + max(0, level)
        return f"subclass_{fingerprint}_{int(definition['class_level'])}", {
            "label": str(definition["name"]),
            "max": maximum,
            "max_formula": "fixed_pool" if healing_pool else "1+class_level",
            "die_size": die_size,
            "resource_kind": "healing_dice_pool",
            "recovery": "long_rest",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "source": (
                f"{definition.get('source_path') or definition.get('source_record_id')}"
                f" · {definition['class_level']}级{definition['name']}"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        }
    if "使用" not in description or "次" not in description:
        return None
    source_id = str(definition.get("source_record_id") or definition.get("id") or "")
    fingerprint = re.sub(r"[^a-z0-9]+", "", source_id.casefold())[-18:]
    if not fingerprint:
        fingerprint = hashlib.sha256(str(definition.get("id") or "").encode()).hexdigest()[:18]
    key = f"subclass_{fingerprint}_{int(definition['class_level'])}"
    explicit = re.search(
        r"(?:可|能)?使用(?:此|该)?(?:特性|能力)?[^。；;]{0,32}?(\d+)\s*次",
        description,
    )
    ability_match = re.search(
        r"(?:使用次数|使用(?:这|此|该)?(?:个)?(?:特性|附赠动作)的次数)"
        r"(?:等于|为|相当于)你的?"
        r"(力量|敏捷|体质|智力|感知|魅力)(?:调整值|调整)",
        description,
    )
    proficiency = bool(
        re.search(
            r"(?:使用次数|使用(?:此|该)特性的次数)(?:等于|为)你的?熟练加值",
            description,
        )
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
    current_class_level: int | None = None,
) -> dict[str, Any]:
    """Compile a selected subclass's grants, sheet actions and resources.

    The returned ``choice_requirements`` is intentionally structured for the
    API rather than silently selecting one branch from prose.  A caller can
    validate a DM selection and persist it alongside the feature grant.
    """

    definitions = [
        dict(item)
        for item in subclass.get("feature_definitions", [])
        if isinstance(item, dict) and int(item.get("class_level") or 0) == target_class_level
    ]
    grants: list[dict[str, Any]] = []
    resources: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    prepared_spell_features: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    choices = selected_choices or {}
    for definition in definitions:
        definition["class_name"] = class_name
        definition["subclass_name"] = str(subclass.get("name") or "")
        feature_id = str(definition.get("id") or definition.get("name") or "")
        feature_name = str(definition.get("name") or "").strip()
        declared_requirement = definition.get("choice_requirement")
        selected = [str(item).strip() for item in choices.get(feature_id, []) if str(item).strip()]
        is_battle_master = class_name == "战士" and definition["subclass_name"] == "战斗大师"
        if is_battle_master:
            canonical_selected = [_canonical_battle_master_maneuver(item) for item in selected]
            if all(item is not None for item in canonical_selected):
                selected = [str(item) for item in canonical_selected if item is not None]
            definition_level = int(definition.get("class_level") or target_class_level)
            maneuver_count = (
                {3: 3, 7: 2, 10: 2, 15: 2}.get(definition_level)
                if definition_level != 3 or feature_name.startswith("卓越战技")
                else None
            )
            if maneuver_count is not None:
                declared_requirement = {
                    "key": "battle_master_maneuvers",
                    "minimum": maneuver_count,
                    "maximum": maneuver_count,
                    "strict": True,
                    "options": [
                        *sorted(BATTLE_MASTER_MANEUVER_OPTIONS),
                        *sorted(BATTLE_MASTER_MANEUVER_OPTIONS.values()),
                    ],
                    "options_labels": dict(BATTLE_MASTER_MANEUVER_OPTIONS),
                    "requires_dm_selection": False,
                    "unique_group": "battle_master_maneuvers",
                    "replacement_format": "replace:<known_maneuver>-><new_maneuver>",
                }
        dc_feature_id = f"{feature_id}:dc_ability"
        dc_selected = [
            str(item).strip().casefold()
            for item in choices.get(dc_feature_id, [])
            if str(item).strip()
        ]
        resource = _subclass_resource_update(
            definition,
            ability_scores=ability_scores,
            current_class_level=current_class_level,
        )
        resource_key = resource[0] if resource else None
        if resource is not None:
            resources[resource[0]] = resource[1]
        action = _subclass_action(definition, resource_key)
        if action is not None:
            actions.append(action)
        runtime_registry = subclass_feature_runtime_definition(definition)
        if runtime_registry is not None and str(definition.get("name") or "").startswith(
            "元素亲和"
        ):
            elemental_options = {
                "damage_type:acid": "acid",
                "damage_type:cold": "cold",
                "damage_type:fire": "fire",
                "damage_type:lightning": "lightning",
                "damage_type:poison": "poison",
            }
            choice_requirement = {
                "key": "elemental_affinity_damage_type",
                "minimum": 1,
                "maximum": 1,
                "strict": True,
                "options": sorted(elemental_options),
                "requires_dm_selection": True,
            }
            runtime_registry = deepcopy(runtime_registry)
            runtime_registry["advancement"] = {
                "kind": "selected_damage_type",
                "choice_requirement": choice_requirement,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "advancement_service_and_damage_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
            selected_damage_type = next(
                (elemental_options[value] for value in selected if value in elemental_options),
                None,
            )
            if selected_damage_type is not None:
                defense_entries = runtime_registry["combat_start"]["defenses"]
                for defense in defense_entries:
                    if isinstance(defense, dict) and defense.get("id") == (
                        "elemental_affinity:selected_resistance"
                    ):
                        defense["damage_types"] = [selected_damage_type]
                for rider in runtime_registry.get("attack_riders") or ():
                    if isinstance(rider, dict) and rider.get("id") == (
                        "elemental_affinity:bonus_damage"
                    ):
                        rider["selected_damage_type"] = selected_damage_type
        if runtime_registry is not None and str(definition.get("name") or "").startswith(
            "钢铁意志"
        ):
            selected_save = next(
                (
                    value.split(":", 1)[1].strip()
                    for value in selected
                    if value.startswith("save:") and value.split(":", 1)[1].strip()
                ),
                None,
            )
            if selected_save:
                combat_start = runtime_registry.get("combat_start")
                modifiers = (
                    combat_start.get("modifiers") if isinstance(combat_start, dict) else None
                )
                if isinstance(modifiers, list):
                    for modifier in modifiers:
                        if (
                            isinstance(modifier, dict)
                            and modifier.get("id") == "iron_mind:saving_throw_proficiency"
                        ):
                            modifier["abilities"] = [selected_save]
        if runtime_registry is not None and resource_key:
            # Bind a generic resource-lifecycle action to the resource parsed
            # from this feature's source description.  The shared executor sees
            # only the resulting key; this adapter is kept at configuration
            # compilation and is not a feature-ID branch in the executor.
            runtime_registry = deepcopy(runtime_registry)
            raw_resources = runtime_registry.get("resources")
            if isinstance(raw_resources, Mapping):
                bound_resources: dict[str, dict[str, Any]] = {}
                for raw_key, raw_value in raw_resources.items():
                    if not isinstance(raw_value, Mapping):
                        continue
                    bound_key = (
                        resource_key if str(raw_key) == "$feature_resource" else str(raw_key)
                    )
                    value = deepcopy(dict(raw_value))
                    if str(raw_key) == "$feature_resource":
                        # The resource parser is the single source of truth
                        # for the class-level die table and recovery metadata.
                        # Keep the typed config's runtime consumer while
                        # binding the actual persisted key and numeric values.
                        value = {**value, **deepcopy(resource[1])}
                    value["key"] = bound_key
                    bound_resources[bound_key] = value
                runtime_registry["resources"] = bound_resources
            raw_actions = runtime_registry.get("actions")
            if isinstance(raw_actions, dict):
                for raw_action in raw_actions.values():
                    if not isinstance(raw_action, dict):
                        continue
                    if raw_action.get("resource_key") == "$feature_resource":
                        raw_action["resource_key"] = resource_key
                    lifecycle = raw_action.get("resource_lifecycle")
                    if isinstance(lifecycle, dict):
                        lifecycle["key"] = resource_key
                    for field in ("resource", "eligibility"):
                        value = raw_action.get(field)
                        if isinstance(value, dict) and value.get("key") == "$feature_resource":
                            value["key"] = resource_key
                        if field == "eligibility" and isinstance(value, dict):
                            nested = value.get("resource")
                            if (
                                isinstance(nested, dict)
                                and nested.get("key") == "$feature_resource"
                            ):
                                nested["key"] = resource_key
            raw_runtime_triggers = runtime_registry.get("triggers")
            if isinstance(raw_runtime_triggers, list):
                for raw_trigger in raw_runtime_triggers:
                    if not isinstance(raw_trigger, dict):
                        continue
                    trigger_resource = raw_trigger.get("resource")
                    if (
                        isinstance(trigger_resource, dict)
                        and trigger_resource.get("key") == "$feature_resource"
                    ):
                        trigger_resource["key"] = resource_key
        if runtime_registry is not None and is_battle_master:
            # Reconstruct the learned set in level order.  The registry is
            # persisted on every grant, so a rebuilt character exposes only
            # maneuvers actually learned/replaced by that point in the sheet.
            learned: list[str] = []
            ordered_definitions = sorted(
                (
                    item
                    for item in subclass.get("feature_definitions", [])
                    if isinstance(item, Mapping)
                    and int(item.get("class_level") or 0) <= target_class_level
                ),
                key=lambda item: (int(item.get("class_level") or 0), str(item.get("id") or "")),
            )
            for prior in ordered_definitions:
                prior_id = str(prior.get("id") or prior.get("name") or "")
                prior_level = int(prior.get("class_level") or 0)
                if prior_level not in {3, 7, 10, 15}:
                    continue
                for raw_choice in choices.get(prior_id, []):
                    choice = _canonical_battle_master_maneuver(raw_choice)
                    if choice is None:
                        continue
                    if choice.startswith("replace:"):
                        old_key, new_key = choice[8:].split("->", 1)
                        if old_key in learned:
                            learned.remove(old_key)
                        if new_key not in learned:
                            learned.append(new_key)
                    elif choice not in learned:
                        learned.append(choice)
            runtime_registry = deepcopy(runtime_registry)
            runtime_registry["selected_maneuvers"] = list(learned)
            if is_battle_master and feature_name.startswith("卓越战技"):
                if dc_selected:
                    runtime_registry["superiority_dc_ability"] = dc_selected[0]
                runtime_registry["advancement"] = {
                    **dict(runtime_registry.get("advancement") or {}),
                    "dc_ability_choice_requirement": {
                        "key": "battle_master_superiority_dc_ability",
                        "minimum": 1,
                        "maximum": 1,
                        "strict": True,
                        "options": ["strength", "dexterity"],
                        "requires_dm_selection": False,
                    },
                }
            raw_runtime_actions = runtime_registry.get("actions")
            if isinstance(raw_runtime_actions, Mapping):
                runtime_registry["actions"] = {
                    str(key): value
                    for key, value in raw_runtime_actions.items()
                    if not isinstance(value, Mapping)
                    or not value.get("maneuver_id")
                    or str(value.get("maneuver_id")) in learned
                }
            raw_runtime_riders = runtime_registry.get("attack_riders")
            if isinstance(raw_runtime_riders, list):
                runtime_registry["attack_riders"] = [
                    value
                    for value in raw_runtime_riders
                    if not isinstance(value, Mapping)
                    or not value.get("maneuver_id")
                    or str(value.get("maneuver_id")) in learned
                ]
            raw_runtime_triggers = runtime_registry.get("triggers")
            if isinstance(raw_runtime_triggers, list):
                runtime_registry["triggers"] = [
                    value
                    for value in raw_runtime_triggers
                    if not isinstance(value, Mapping)
                    or not value.get("maneuver_id")
                    or str(value.get("maneuver_id")) in learned
                ]
            combat_start = runtime_registry.get("combat_start")
            if isinstance(combat_start, dict):
                raw_replacements = combat_start.get("attack_slot_replacements")
                if isinstance(raw_replacements, list):
                    combat_start["attack_slot_replacements"] = [
                        value
                        for value in raw_replacements
                        if not isinstance(value, Mapping)
                        or not value.get("maneuver_id")
                        or str(value.get("maneuver_id")) in learned
                    ]
        spell_contract = _subclass_prepared_spell_contract(str(definition.get("description") or ""))
        if spell_contract is not None:
            runtime_registry = {
                **(runtime_registry or {"combat_start": {"modifiers": [], "defenses": []}}),
                "prepared_spell_list": spell_contract,
            }
            prepared_spell_features.append(
                {
                    "feature_id": feature_id,
                    "feature_name": str(definition.get("name") or ""),
                    "class_name": class_name,
                    "class_level": target_class_level,
                    "source_record_id": definition.get("source_record_id"),
                    "description": str(definition.get("description") or ""),
                }
            )
        if isinstance(runtime_registry, dict):
            advancement = runtime_registry.get("advancement")
            configured_requirement = (
                advancement.get("choice_requirement") if isinstance(advancement, Mapping) else None
            )
            if (
                isinstance(advancement, Mapping)
                and advancement.get("kind") == "selected_spell_grant"
                and isinstance(advancement.get("selection"), Mapping)
                and isinstance(configured_requirement, Mapping)
            ):
                selection = advancement["selection"]
                required_count = int(selection.get("count") or 0)
                if selection.get("add_one_per_new_spell_level") is True:
                    required_count += max(
                        0,
                        maximum_class_spell_level(
                            class_name, int(current_class_level or target_class_level)
                        )
                        - 2,
                    )
                configured_requirement = {
                    **dict(configured_requirement),
                    "minimum": required_count,
                    "maximum": required_count,
                }
            requirement = (
                configured_requirement
                if isinstance(configured_requirement, Mapping)
                else declared_requirement
            )
            if isinstance(requirement, Mapping):
                requirements.append({"feature_id": feature_id, **dict(requirement)})
            if is_battle_master and feature_name.startswith("卓越战技"):
                requirements.append(
                    {
                        "feature_id": dc_feature_id,
                        "key": "battle_master_superiority_dc_ability",
                        "minimum": 1,
                        "maximum": 1,
                        "strict": True,
                        "options": ["strength", "dexterity"],
                        "requires_dm_selection": False,
                    }
                )
            runtime_contract = feature_runtime_contract(
                feature_name=str(definition.get("name") or ""),
                class_name=class_name,
                class_level=target_class_level,
                definition=runtime_registry,
                kind="subclass_feature",
                source_record_id=(
                    str(definition.get("source_record_id"))
                    if definition.get("source_record_id") is not None
                    else None
                ),
                source_path=(
                    str(definition.get("source_path"))
                    if definition.get("source_path") is not None
                    else None
                ),
                declared_status=(
                    str(runtime_registry.get("automation_status"))
                    if runtime_registry.get("automation_status") is not None
                    else None
                ),
            )
            runtime_status = str(runtime_contract["automation_status"])
        else:
            if isinstance(declared_requirement, Mapping):
                requirements.append({"feature_id": feature_id, **dict(declared_requirement)})
            runtime_status = "partial" if (resource or action) else "dm_only"
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
                "selected_choice_inputs": (
                    {"superiority_dc_ability": dc_selected[0]}
                    if dc_selected and is_battle_master and feature_name.startswith("卓越战技")
                    else {}
                ),
                "runtime": {
                    "automation_status": runtime_status,
                    "tracked_resource_keys": [resource_key] if resource_key else [],
                    "action_name": action.get("name") if action else None,
                    "requires_dm_adjudication": runtime_status != "full",
                    "registry": runtime_registry,
                    "note": (
                        "该子职特性已接入通用运行时积木并写入战斗快照。"
                        if runtime_status == "full"
                        else "已同步可验证的资源或动作经济；其余文本效果由 DM 裁定。"
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
        "prepared_spell_features": prepared_spell_features,
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
        if (
            ("子职" in feature or "子职业" in feature)
            and "子职特性" not in feature
            and "子职业特性" not in feature
        ):
            # The class-table row is the subclass-selection grant itself.
            # Concrete subclass features are separate persisted grants and
            # remain independently audited.
            registry["advancement"] = {
                "kind": "subclass_selection",
                "choice_key": "subclass",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "advancement_service",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        progression_profile = progression_automation_profile(feature)
        compact_feature = re.sub(r"\s+", "", feature)
        if "战斗风格" in compact_feature and rule.name == "战士":
            registry["advancement"] = {
                "kind": "selected_asset_grant",
                "choice_requirement_key": "fighting_style",
                "request_field": "feature_choices_by_key.fighting_style",
                "asset_kind": "feat",
                "authoritative_catalog": "core_feat_rules",
                "expected_category": "战斗风格",
                "count": 1,
                "duplicate_policy": "forbid",
                "replacement_policy": "replace_on_owner_class_level",
                "prerequisites": "authoritative_feat_catalog",
                "persisted_state": "character.features",
                "selected_asset_runtime": "separate_contract",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "advancement_service_and_feat_prerequisite_validator",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        elif "熟练探险家" in compact_feature:
            registry["advancement"] = {
                "kind": "selected_option_bundle",
                "choice_requirement_keys": [
                    "deft_explorer_expertise",
                    "deft_explorer_languages",
                ],
                "operations": ["grant_expertise", "grant_languages"],
                "authoritative_catalogs": ["character.skills", "core_languages"],
                "persisted_state": ["character.skills", "character.proficiencies"],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "advancement_service_and_skill_modifier",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        elif "原初职能" in compact_feature or compact_feature == "圣职":
            primal = "原初职能" in compact_feature
            registry["advancement"] = {
                "kind": "selected_option_bundle",
                "choice_requirement_keys": [
                    "primal_order" if primal else "divine_order",
                    "primal_order_cantrip" if primal else "divine_order_cantrip",
                ],
                "options": ["magician", "warden"] if primal else ["protector", "thaumaturge"],
                "operations": [
                    "grant_proficiencies",
                    "grant_selected_cantrip",
                    "grant_skill_ability_modifier_bonus",
                ],
                "authoritative_catalogs": ["class_spell_list", "supported_skills"],
                "persisted_state": [
                    "character.features",
                    "character.proficiencies",
                    "character.skills",
                    "character.spells",
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "advancement_service_spell_grant_and_skill_modifier",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        elif "魔法奥秘" in compact_feature:
            registry["advancement"] = {
                "kind": "spell_list_expansion",
                "allowed_classes": ["吟游诗人", "牧师", "德鲁伊", "法师"],
                "applies_to": ["prepared_spell_increase", "prepared_spell_replacement"],
                "persisted_state": "character.spells",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "advancement_service_spell_catalog_validator",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        elif "仪式学家" in compact_feature:
            registry["advancement"] = {
                "kind": "ritual_spellbook_casting",
                "spell_source": "wizard_spellbook",
                "requires_ritual_tag": True,
                "requires_prepared": False,
                "consumes_spell_slot": False,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "spell_economy_service",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        if progression_profile is not None and progression_profile.choice_key == "epic_boon":
            # The class-table feature is a typed asset grant.  The chosen feat
            # remains a separate persisted runtime contract, whose concrete
            # effects retain their own automation status.  This mirrors the
            # existing subclass-selection boundary and prevents a class grant
            # from claiming that every possible selected asset is executable.
            registry["advancement"] = {
                "kind": "selected_asset_grant",
                "choice_requirement_key": "epic_boon",
                "request_field": "feat_choice",
                "asset_kind": "feat",
                "expected_category": "传奇恩惠",
                "prerequisites": "authoritative_feat_catalog",
                "persisted_state": "character.features",
                "selected_asset_runtime": "separate_contract",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "advancement_service_and_feat_prerequisite_validator",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
            }
        contract = feature_runtime_contract(
            feature_name=feature,
            class_name=rule.name,
            class_level=target_class_level,
            kind="class_feature",
            source_record_id=rule.source_record_id,
            source_path=rule.source_path,
            definition=registry,
            declared_status=(
                progression_profile.overall_status if progression_profile is not None else None
            ),
            note=(progression_profile.dm_boundary if progression_profile is not None else None),
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
                        progression_profile.as_dict() if progression_profile is not None else None
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
