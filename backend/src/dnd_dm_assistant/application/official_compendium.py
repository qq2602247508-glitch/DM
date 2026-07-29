from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

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


def _monster_actions(text: str) -> list[dict[str, Any]]:
    section = re.search(
        r"(?:^|\n)动作(?:Actions)?\s*\n([\s\S]*?)(?=\n(?:附赠动作|反应|传奇动作|巢穴动作|施法)\b|$)",
        text,
    )
    raw = section.group(1) if section else text
    actions: list[dict[str, Any]] = []
    for line in (part.strip(" *#") for part in raw.splitlines()):
        if not line or not re.search(r"命中|伤害|豁免|多重攻击|充能", line):
            continue
        name_match = re.match(r"([^。.：:]{2,40})[。.：:]", line)
        damage = re.search(r"[（(]\s*(\d+d\d+(?:\s*[+-]\s*\d+)?)\s*[）)]", line)
        bonus = re.search(r"(?:命中|攻击检定[：:]?)\s*\+\s*(\d+)", line)
        reach = re.search(r"(?:触及|射程)\s*(\d+)\s*尺", line)
        save = re.search(r"DC\s*(\d+)\s*的?\s*(力量|敏捷|体质|智力|感知|魅力)\s*豁免", line)
        actions.append(
            {
                "name": (name_match.group(1) if name_match else line[:30]).strip(),
                "description": line[:900],
                "damage": damage.group(1).replace(" ", "") if damage else None,
                "attack_bonus": int(bonus.group(1)) if bonus else None,
                "range_ft": int(reach.group(1)) if reach else 5,
                "save_dc": int(save.group(1)) if save else None,
                "save_ability": ABILITY_KEYS.get(save.group(2)) if save else None,
                "action_type": "action",
            }
        )
        if len(actions) >= 12:
            break
    return actions


def _monster_fields(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    scores = {
        key: _number(text, rf"{label}\s*(\d{{1,2}})(?:\s|（|\()", 10)
        for label, key in ABILITY_KEYS.items()
    }
    cr_match = re.search(r"(?:\bCR|挑战等级)[：:]?\s*([0-9]+(?:/[0-9]+)?)", text)
    type_match = re.search(
        r"(?:微型|小型|中型|大型|巨型|超巨型)(?:\s*[\u3400-\u9fff]+)?"
        r"\s*(异怪|野兽|构装生物|龙|元素|妖精|邪魔|巨人|类人生物|怪兽|泥怪|植物|亡灵)",
        text,
    )
    filters = {
        "challenge_rating": cr_match.group(1) if cr_match else "未知",
        "monster_type": type_match.group(1) if type_match else "未分类",
    }
    rules = {
        "armor_class": _number(text, r"(?:\bAC|护甲等级)[：:]?\s*(\d+)", 10),
        "hp": _number(text, r"(?:\bHP|生命值)[：:]?\s*(\d+)", 1),
        "speed": _number(text, r"速度[：:]?\s*(\d+)\s*尺", 30),
        "ability_scores": scores,
        "actions": _monster_actions(text),
    }
    return filters, rules


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


def _record_entry(data: dict[str, Any]) -> dict[str, Any] | None:
    content_type = str(data.get("content_type") or "")
    entry_type = CONTENT_ENTRY_TYPES.get(content_type)
    if entry_type is None or data.get("officiality") != "official":
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
        classes = _normalize_spell_classes(spell.get("classes"))
        if not classes or not spell.get("casting_time") or not spell.get("range"):
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
    if entry_type == "monster":
        monster_filters, monster_rules = _monster_fields(str(data.get("content_plain_text") or ""))
        filters.update(monster_filters)
        rules.update(monster_rules)
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
                "entry_type": "equipment" if category in {"weapon", "armor", "shield"} else "item",
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
            suffix = hashlib.sha256(f"{stable_id}|{variant_name}|{position}".encode()).hexdigest()[
                :12
            ]
            result.append(
                {
                    "id": f"official:{stable_id}:{suffix}",
                    "version": 1,
                    "campaign_id": "official",
                    "entry_type": "item",
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
                        "rarity": variant_rarity,
                        "attunement": "需同调" if "同调" in metadata else "无需同调",
                        "attunement_classes": (
                            attunement_match.group(1).strip() if attunement_match else ""
                        ),
                        "atomic_item": True,
                    },
                    "rules_json": {
                        "canonical_url": data.get("canonical_url"),
                        "source_relative_path": data.get("source_relative_path"),
                        "charges": int(charge_match.group(1)) if charge_match else None,
                        "attunement": "同调" in metadata,
                        "magic_bonus": magic_bonus,
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
    for content_type in CONTENT_ENTRY_TYPES:
        directory = root / content_type
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            if content_type == "monsters" and data.get("officiality") == "official":
                atomic_monsters = _atomic_monster_entries(data)
                if atomic_monsters:
                    entries.extend(atomic_monsters)
                    continue
            if content_type == "equipment" and data.get("officiality") == "official":
                atomic_equipment = (
                    _atomic_equipment_entries(data) if data.get("edition") == "2024" else []
                )
                entries.extend(atomic_equipment)
                continue
            if content_type == "items" and data.get("officiality") == "official":
                atomic_items = _atomic_item_entries(data)
                if atomic_items:
                    entries.extend(atomic_items)
                continue
            entry = _record_entry(data)
            if entry is not None:
                entries.append(entry)
    return tuple(entries)


class OfficialCompendiumCatalog:
    """Read-only atom view over the already-ingested local D&D rule corpus."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def entries(self) -> tuple[dict[str, Any], ...]:
        return _load_catalog(str(self.root.resolve()))

    def get(self, entry_id: str) -> dict[str, Any] | None:
        return next((entry for entry in self.entries if entry["id"] == entry_id), None)

    def search(
        self,
        *,
        entry_type: str | None = None,
        text: str = "",
        filters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        query = text.strip().lower()
        return [
            entry
            for entry in self.entries
            if (not entry_type or entry["entry_type"] == entry_type)
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
