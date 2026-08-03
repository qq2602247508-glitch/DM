from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dnd_dm_assistant.domain.feature_runtime import resource_recovery_events

TABLE_ROW = re.compile(r"^\|\s*(.*?)\s*\|\s*$")
# The core tables use plain digits, while already-ingested supplement tables
# commonly use ``1st``/``2nd``.  Both are table rows; arbitrary prose numbers
# remain excluded.
LEVEL = re.compile(r"^(\d{1,2})(?:st|nd|rd|th|级)?$", re.I)

MULTICLASS_SPELL_SLOTS: tuple[tuple[int, ...], ...] = (
    (),
    (2,),
    (3,),
    (4, 2),
    (4, 3),
    (4, 3, 2),
    (4, 3, 3),
    (4, 3, 3, 1),
    (4, 3, 3, 2),
    (4, 3, 3, 3, 1),
    (4, 3, 3, 3, 2),
    (4, 3, 3, 3, 2, 1),
    (4, 3, 3, 3, 2, 1),
    (4, 3, 3, 3, 2, 1, 1),
    (4, 3, 3, 3, 2, 1, 1),
    (4, 3, 3, 3, 2, 1, 1, 1),
    (4, 3, 3, 3, 2, 1, 1, 1),
    (4, 3, 3, 3, 2, 1, 1, 1, 1),
    (4, 3, 3, 3, 3, 1, 1, 1, 1),
    (4, 3, 3, 3, 3, 2, 1, 1, 1),
    (4, 3, 3, 3, 3, 2, 2, 1, 1),
)

# ``class_levels`` predates the normalized character-sheet contract in a few
# saved campaigns.  Keep the spell-slot helper tolerant of those historical
# labels instead of accidentally treating one class as two separate casters.
# The broader catalog aliases live in ``advancement_choices``; this small copy
# deliberately stays here to avoid a domain-layer import cycle.
MULTICLASS_CLASS_ALIASES: dict[str, str] = {
    "邪术师": "魔契师",
    "奇械师（旧版）": "奇械师",
    "奇械师(旧版)": "奇械师",
    "Artificer": "奇械师",
}


@dataclass(frozen=True, slots=True)
class ClassLevel:
    level: int
    proficiency_bonus: int
    features: tuple[str, ...]
    progression: dict[str, str]


@dataclass(frozen=True, slots=True)
class ClassProgression:
    name: str
    source_record_id: str
    source_path: str
    hit_die: int
    levels: tuple[ClassLevel, ...]
    subclasses: tuple[dict[str, Any], ...] = ()
    rule_year: str = "2024"
    content_pack_key: str | None = None


def proficiency_bonus_for_level(total_level: int) -> int:
    """Return the deterministic 2024 proficiency bonus for total character level."""

    if not 1 <= total_level <= 20:
        raise ValueError("total character level must be between 1 and 20")
    return 2 + (total_level - 1) // 4


def _cells(line: str) -> list[str]:
    match = TABLE_ROW.match(line.strip())
    if not match:
        return []
    return [cell.strip().replace("\\|", "|") for cell in match.group(1).split("|")]


def _feature_names(raw: str) -> tuple[str, ...]:
    if raw.strip() in {"", "—", "-", "无"}:
        return ()
    return tuple(
        item.strip()
        for item in re.split(r"[,，、；;]", raw)
        if item.strip()
    )


def parse_progression_table(markdown: str) -> tuple[ClassLevel, ...]:
    """Extract the 1–20 class table without copying feature prose."""

    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        header = _cells(line)
        if not header or "等级" not in header[0]:
            continue
        if not any("职业特性" in cell or cell.strip() == "特性" for cell in header):
            continue
        feature_index = next(
            position
            for position, cell in enumerate(header)
            if "职业特性" in cell or cell.strip() == "特性"
        )
        pb_index = next(
            (
                position
                for position, cell in enumerate(header)
                if "熟练" in cell or "PB" in cell.upper()
            ),
            1,
        )
        rows: list[ClassLevel] = []
        for row_line in lines[index + 2 :]:
            row = _cells(row_line)
            if not row:
                break
            level_match = LEVEL.match(row[0]) if row else None
            if not row or level_match is None:
                continue
            level = int(level_match.group(1))
            if not 1 <= level <= 20:
                continue
            pb_raw = row[pb_index] if pb_index < len(row) else ""
            pb_match = re.search(r"\d+", pb_raw)
            pb = int(pb_match.group()) if pb_match else proficiency_bonus_for_level(level)
            features = _feature_names(row[feature_index] if feature_index < len(row) else "")
            progression = {
                header[position]: value
                for position, value in enumerate(row)
                if position < len(header)
                and position not in {0, pb_index, feature_index}
                and header[position]
            }
            rows.append(
                ClassLevel(
                    level=level,
                    proficiency_bonus=pb,
                    features=features,
                    progression=progression,
                )
            )
        if len(rows) == 20 and [row.level for row in rows] == list(range(1, 21)):
            return tuple(rows)
    raise ValueError("complete 1-20 class progression table not found")


def parse_hit_die(markdown: str) -> int:
    match = re.search(
        r"(?:生命值骰|生命骰|Hit Point Die).*?[Dd](6|8|10|12)",
        markdown,
        re.I | re.S,
    )
    return int(match.group(1)) if match else 8


def class_progression_from_record(
    record: dict[str, Any],
    *,
    subclasses: tuple[dict[str, str], ...] = (),
) -> ClassProgression:
    markdown = str(record.get("content_markdown") or "")
    return ClassProgression(
        name=str(record["name"]),
        source_record_id=str(record["stable_id"]),
        source_path=str(record.get("source_relative_path") or ""),
        hit_die=parse_hit_die(markdown),
        levels=parse_progression_table(markdown),
        subclasses=subclasses,
        rule_year=str(record.get("normalized_edition") or record.get("edition") or "2024"),
        content_pack_key=(
            str(record.get("content_pack_key"))
            if record.get("content_pack_key")
            else None
        ),
    )


def average_hp_gain(hit_die: int, constitution_modifier: int) -> int:
    if hit_die not in {6, 8, 10, 12}:
        raise ValueError("unsupported hit die")
    return max(1, hit_die // 2 + 1 + constitution_modifier)


def validate_multiclass_prerequisites(
    class_name: str,
    ability_scores: dict[str, int],
) -> tuple[str, ...]:
    requirements: dict[str, tuple[tuple[str, int], ...]] = {
        "野蛮人": (("strength", 13),),
        "吟游诗人": (("charisma", 13),),
        "牧师": (("wisdom", 13),),
        "德鲁伊": (("wisdom", 13),),
        "战士": (("strength_or_dexterity", 13),),
        "武僧": (("dexterity", 13), ("wisdom", 13)),
        "圣武士": (("strength", 13), ("charisma", 13)),
        "游侠": (("dexterity", 13), ("wisdom", 13)),
        "游荡者": (("dexterity", 13),),
        "术士": (("charisma", 13),),
        "魔契师": (("charisma", 13),),
        "邪术师": (("charisma", 13),),
        "法师": (("intelligence", 13),),
        "奇械师": (("intelligence", 13),),
    }
    failures: list[str] = []
    for ability, minimum in requirements.get(class_name, ()):
        if ability == "strength_or_dexterity":
            if max(
                int(ability_scores.get("strength", 0)),
                int(ability_scores.get("dexterity", 0)),
            ) < minimum:
                failures.append("力量或敏捷 13")
        elif int(ability_scores.get(ability, 0)) < minimum:
            failures.append(f"{ability} {minimum}")
    return tuple(failures)


def normalize_multiclass_class_levels(
    class_levels: Mapping[str, object],
) -> dict[str, int]:
    """Return canonical positive class levels for multiclass math.

    Character creation already rejects duplicate canonical class names.  This
    helper protects advancement/resource recalculation as well, including
    sheets saved before aliases such as ``邪术师`` were normalized.  Combining
    duplicate alias entries would silently invent class levels, so it is an
    explicit validation error instead.
    """

    normalized: dict[str, int] = {}
    for raw_name, raw_level in class_levels.items():
        name = MULTICLASS_CLASS_ALIASES.get(str(raw_name).strip(), str(raw_name).strip())
        if not name:
            raise ValueError("class_levels contains an empty class name")
        level = int(raw_level)
        if level < 0:
            raise ValueError(f"{name} class level cannot be negative")
        if level == 0:
            continue
        if name in normalized:
            raise ValueError(
                f"class_levels contains duplicate class after alias normalization: {name}"
            )
        normalized[name] = level
    return normalized


def multiclass_caster_level(
    class_levels: dict[str, int],
    subclass_choices: dict[str, str] | None = None,
) -> int:
    """Return the 2024 multiclass spell-slot level; Pact Magic stays separate."""

    normalized_levels = normalize_multiclass_class_levels(class_levels)
    subclasses = subclass_choices or {}
    full = {"吟游诗人", "牧师", "德鲁伊", "术士", "法师"}
    total = sum(int(normalized_levels.get(name, 0)) for name in full)
    total += sum(
        (int(normalized_levels.get(name, 0)) + 1) // 2
        for name in ("圣武士", "游侠")
    )
    # The legacy artificer is a half caster whose multiclass contribution
    # rounds up. Pact Magic deliberately remains outside this shared table.
    total += (int(normalized_levels.get("奇械师", 0)) + 1) // 2
    fighter_subclass = str(subclasses.get("战士") or "")
    rogue_subclass = str(subclasses.get("游荡者") or "")
    if any(name in fighter_subclass for name in ("奥法骑士", "奥术骑士")):
        total += int(normalized_levels.get("战士", 0)) // 3
    if any(name in rogue_subclass for name in ("诡术师", "奥法诡术师")):
        total += int(normalized_levels.get("游荡者", 0)) // 3
    return min(20, total)


def multiclass_spell_slots(
    class_levels: dict[str, int],
    subclass_choices: dict[str, str] | None = None,
) -> tuple[int, ...]:
    return MULTICLASS_SPELL_SLOTS[
        multiclass_caster_level(class_levels, subclass_choices)
    ]


def merge_spell_slot_resources(
    resources: dict[str, Any],
    class_levels: dict[str, int],
    subclass_choices: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Update shared slots without restoring slots already spent before leveling."""

    merged = dict(resources)
    slots = multiclass_spell_slots(class_levels, subclass_choices)
    for level in range(1, 10):
        key = f"spell_slots_{level}"
        old = merged.get(key)
        new_max = slots[level - 1] if level <= len(slots) else 0
        if new_max <= 0:
            merged.pop(key, None)
            continue
        old_max = int(old.get("max", 0)) if isinstance(old, dict) else 0
        old_current = int(old.get("current", old_max)) if isinstance(old, dict) else 0
        merged[key] = {
            **(old if isinstance(old, dict) else {}),
            "label": f"{level}环法术位",
            "current": min(new_max, old_current + max(0, new_max - old_max)),
            "max": new_max,
            "recovery": "long_rest",
            "recovery_events": resource_recovery_events(
                key,
                {"recovery": "long_rest"},
            ),
        }
    return merged
