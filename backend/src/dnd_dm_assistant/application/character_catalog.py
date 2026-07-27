from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.rule_block_compiler import (
    compile_rule_blocks_dict,
)
from dnd_dm_assistant.domain.advancement import (
    ClassProgression,
    class_progression_from_record,
)
from dnd_dm_assistant.domain.advancement_choices import (
    advancement_choice_requirements,
    progression_resource_updates,
)

CORE_CLASSES_2024 = {
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
}


class CharacterCatalog:
    def __init__(self, corpus_root: Path) -> None:
        self.corpus_root = corpus_root

    def _records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.corpus_root.exists():
            return records
        for path in self.corpus_root.glob("*/*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("edition") == "2024" and value.get("officiality") == "official":
                records.append(value)
        return records

    def classes(self) -> tuple[ClassProgression, ...]:
        records = self._records()
        by_path = {str(record.get("source_relative_path") or ""): record for record in records}
        result: list[ClassProgression] = []
        for record in records:
            name = str(record.get("name") or "")
            source_path = str(record.get("source_relative_path") or "")
            if name not in CORE_CLASSES_2024:
                continue
            expected_suffix = f"/{name}/{name}.htm"
            if not source_path.endswith(expected_suffix):
                continue
            directory = source_path.rsplit("/", 1)[0]
            subclasses = tuple(
                {
                    "name": str(candidate.get("name") or ""),
                    "source_record_id": str(candidate.get("stable_id") or ""),
                    "source_path": candidate_path,
                }
                for candidate_path, candidate in sorted(by_path.items())
                if candidate_path.startswith(f"{directory}/")
                and candidate_path != source_path
                and "选项" not in str(candidate.get("name") or "")
            )
            try:
                result.append(
                    class_progression_from_record(
                        record,
                        subclasses=subclasses,
                    )
                )
            except ValueError:
                continue
        return tuple(sorted(result, key=lambda item: item.name))

    def options(self) -> dict[str, Any]:
        records = self._records()

        def spell_summary(record: dict[str, Any]) -> dict[str, Any]:
            mechanics = dict(record.get("spell") or {})
            source_path = str(record.get("source_relative_path") or "")
            raw_level = mechanics.get("level")
            level = (
                int(raw_level) if isinstance(raw_level, int) else 0 if "/0环." in source_path else 1
            )
            markdown = str(record.get("content_markdown") or "").strip()
            if markdown:
                headings = list(re.finditer(r"(?m)^#{2,6}\s+", markdown))
                body = markdown[: headings[1].start()].strip() if len(headings) > 1 else markdown
            else:
                body = str(record.get("content_plain_text") or "").strip()
            raw_save = str(mechanics.get("save") or "")
            save = raw_save if raw_save and raw_save in body else ""
            casting_time = str(mechanics.get("casting_time") or "")
            raw_damage_expression = mechanics.get("damage_expression")
            damage_expression = (
                raw_damage_expression
                if isinstance(raw_damage_expression, str)
                and re.search(
                    re.escape(raw_damage_expression).replace(r"\ ", r"\s*"),
                    body,
                    re.IGNORECASE,
                )
                else None
            )
            summary = {
                "name": str(record.get("name") or ""),
                "source_record_id": str(record.get("stable_id") or ""),
                "source_path": source_path,
                "level": level,
                "classes": [str(item) for item in mechanics.get("classes") or []],
                "school": mechanics.get("school"),
                "casting_time": mechanics.get("casting_time"),
                "range": mechanics.get("range"),
                "components": mechanics.get("components"),
                "duration": mechanics.get("duration"),
                "concentration": bool(mechanics.get("concentration")),
                "ritual": bool(mechanics.get("ritual")),
                "damage_expression": damage_expression,
                "damage_type": mechanics.get("damage_type") if damage_expression else None,
                "save_ability": save.removesuffix("豁免") or None,
                "half_damage_on_save": bool(
                    damage_expression
                    and re.search(
                        r"豁免成功.{0,24}(?:一半|半伤|减半)|成功则只受一半",
                        body,
                    )
                ),
                "description": body[:2400],
                "cost": (
                    "附赠动作"
                    if "附赠" in casting_time
                    else "反应"
                    if "反应" in casting_time
                    else "动作"
                ),
                "resource_key": f"spell_slots_{level}" if level > 0 else None,
                "resource_cost": 1 if level > 0 else 0,
                "resolution_kind": "damage" if damage_expression else "narrative",
            }
            summary["rule_plan"] = compile_rule_blocks_dict(
                summary,
                source_kind="spell",
            )
            return summary

        def summaries(fragment: str) -> list[dict[str, str]]:
            return sorted(
                (
                    {
                        "name": str(record.get("name") or ""),
                        "source_record_id": str(record.get("stable_id") or ""),
                        "source_path": str(record.get("source_relative_path") or ""),
                    }
                    for record in records
                    if fragment in str(record.get("source_relative_path") or "")
                    and str(record.get("name") or "") not in {"PHB2024", "背景详述"}
                ),
                key=lambda item: item["name"],
            )

        feat_options: list[dict[str, str]] = []
        feat_overview = next(
            (
                record
                for record in records
                if record.get("source_relative_path") == "玩家手册2024/专长/专长概述.htm"
            ),
            None,
        )
        if feat_overview:
            markdown = str(feat_overview.get("content_markdown") or "")
            table = re.search(
                r"\|\s*专长\s*\|\s*分类\s*\|.*?\n"
                r"\|[- |]+\|\n(?P<rows>(?:\|.*\|\n?)+)",
                markdown,
            )
            if table:
                for row in table.group("rows").splitlines():
                    cells = [cell.strip() for cell in row.strip("|").split("|")]
                    if len(cells) < 2 or not cells[0]:
                        continue
                    feat_options.append(
                        {
                            "name": cells[0],
                            "category": cells[1],
                            "source_record_id": str(feat_overview.get("stable_id") or ""),
                            "source_path": str(feat_overview.get("source_relative_path") or ""),
                        }
                    )

        return {
            "edition": 2024,
            "officiality": "official",
            "classes": [
                {
                    "name": item.name,
                    "source_record_id": item.source_record_id,
                    "source_path": item.source_path,
                    "hit_die": item.hit_die,
                    "levels": [
                        {
                            "level": level.level,
                            "proficiency_bonus": level.proficiency_bonus,
                            "features": list(level.features),
                            "progression": level.progression,
                            "choice_requirements": [
                                requirement.as_dict()
                                for requirement in advancement_choice_requirements(
                                    item,
                                    level.level,
                                )
                            ],
                            "resource_updates": progression_resource_updates(
                                item,
                                level.level,
                            ),
                        }
                        for level in item.levels
                    ],
                    "subclasses": list(item.subclasses),
                }
                for item in self.classes()
            ],
            "species": summaries("玩家手册2024/角色起源/种族/"),
            "backgrounds": summaries("玩家手册2024/角色起源/背景/"),
            "feats": feat_options or summaries("玩家手册2024/专长/"),
            "spells": sorted(
                (
                    spell_summary(record)
                    for record in records
                    if "玩家手册2024/法术详述/" in str(record.get("source_relative_path") or "")
                    and record.get("spell")
                ),
                key=lambda item: (item["level"], item["name"]),
            ),
            "skills": [
                "杂技",
                "驯兽",
                "奥秘",
                "运动",
                "欺瞒",
                "历史",
                "洞悉",
                "威吓",
                "调查",
                "医药",
                "自然",
                "察觉",
                "表演",
                "游说",
                "宗教",
                "巧手",
                "隐匿",
                "生存",
            ],
            "languages": [
                "通用语",
                "矮人语",
                "精灵语",
                "巨人语",
                "侏儒语",
                "地精语",
                "半身人语",
                "兽人语",
                "龙语",
                "炼狱语",
            ],
            "tools": [
                "炼金工具",
                "酿酒工具",
                "书法工具",
                "木匠工具",
                "制图工具",
                "鞋匠工具",
                "厨师工具",
                "玻璃工具",
                "珠宝工具",
                "皮匠工具",
                "石匠工具",
                "绘画工具",
                "陶匠工具",
                "铁匠工具",
                "修补工具",
                "织布工具",
                "木雕工具",
                "盗贼工具",
                "草药工具",
                "导航工具",
                "乐器",
                "游戏套组",
            ],
        }
