from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.rule_block_compiler import (
    compile_rule_blocks_dict,
)
from dnd_dm_assistant.application.rule_metadata import spell_rule_fields
from dnd_dm_assistant.domain.advancement import (
    ClassProgression,
    class_progression_from_record,
)
from dnd_dm_assistant.domain.advancement_choices import (
    advancement_choice_requirements,
    canonical_class_name,
    core_class_level_runtime_contract,
    core_feat_rules_from_records,
    core_feature_grants,
    core_runtime_actions,
    extension_feat_rules_from_records,
    progression_resource_updates,
    progression_scaling_updates,
    subclass_feature_definitions_from_record,
)
from dnd_dm_assistant.domain.content_packs import (
    content_pack_for_record,
    is_spell_detail_record,
    list_content_packs,
    normalized_record_edition,
    record_is_enabled_for_content_packs,
    validate_content_pack_compatibility,
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

    def _records(
        self,
        *,
        enabled_content_packs: object = (),
        allow_legacy: bool = False,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        enabled_pack_keys = frozenset(
            validate_content_pack_compatibility(
                enabled_content_packs,
                allow_legacy=allow_legacy,
            )
            if enabled_content_packs
            else ()
        )
        if not self.corpus_root.exists():
            return records
        for path in self.corpus_root.glob("*/*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            is_core = value.get("edition") == "2024" and value.get("officiality") == "official"
            is_enabled_pack = record_is_enabled_for_content_packs(
                value,
                enabled_pack_keys,
                allow_source_path=True,
                allow_legacy=allow_legacy,
            )
            if is_core:
                records.append(value)
            elif is_enabled_pack:
                pack = content_pack_for_record(value, allow_source_path=True)
                records.append(
                    {
                        **value,
                        "content_pack_key": pack.key if pack is not None else None,
                        "normalized_edition": normalized_record_edition(value),
                        "source_origin": "official_supplement",
                    }
                )
        return records

    @staticmethod
    def _subclass_parent_class(
        record: dict[str, Any],
        class_names: set[str],
    ) -> str | None:
        source_path = str(record.get("source_relative_path") or "")
        parts = [
            canonical_class_name(re.sub(r"[（(].*?[）)]", "", part).strip())
            for part in source_path.split("/")
        ]
        for part in reversed(parts):
            if part in class_names:
                return part
        raw = source_path.casefold()
        return next(
            (
                class_name
                for class_name in sorted(class_names, key=len, reverse=True)
                if class_name.casefold() in raw
            ),
            None,
        )

    def classes(
        self,
        *,
        enabled_content_packs: object = (),
        allow_legacy: bool = False,
    ) -> tuple[ClassProgression, ...]:
        records = self._records(
            enabled_content_packs=enabled_content_packs,
            allow_legacy=allow_legacy,
        )
        by_path = {str(record.get("source_relative_path") or ""): record for record in records}
        result: list[ClassProgression] = []
        for record in records:
            raw_name = str(record.get("name") or "")
            name = canonical_class_name(raw_name)
            source_path = str(record.get("source_relative_path") or "")
            is_core = name in CORE_CLASSES_2024 and record.get("edition") == "2024"
            is_extension = bool(record.get("content_pack_key"))
            source_basename = re.sub(r"\s*[（(].*?[）)]", "", raw_name).strip()
            expected_suffixes = tuple(
                f"/{candidate}.{extension}"
                for candidate in dict.fromkeys((raw_name, source_basename, name))
                if candidate
                for extension in ("htm", "html")
            )
            if is_core:
                expected_suffixes = (f"/{name}.htm", f"/{name}.html")
            if not (is_core or is_extension) or not source_path.endswith(expected_suffixes):
                continue
            if "职业" not in source_path or "子职" in raw_name or "选项" in raw_name:
                continue
            try:
                # Parsing is the completeness gate for automatic advancement.
                result.append(class_progression_from_record({**record, "name": name}))
            except ValueError:
                continue
        class_names = {item.name for item in result}
        with_subclasses: list[ClassProgression] = []
        for rule in result:
            subclasses: list[dict[str, Any]] = []
            for candidate_path, candidate in sorted(by_path.items()):
                candidate_name = str(candidate.get("name") or "").strip()
                if (
                    candidate_path == rule.source_path
                    or not candidate_name
                    or "选项" in candidate_name
                    or "职业" not in candidate_path
                ):
                    continue
                parent = self._subclass_parent_class(candidate, class_names)
                # A source path must name the parent class explicitly.  Using a
                # common book-level ``职业`` directory would otherwise attach all
                # supplement subclasses to the first extension class found.
                if parent != rule.name:
                    continue
                definitions = subclass_feature_definitions_from_record(candidate)
                is_extension = bool(candidate.get("content_pack_key"))
                if is_extension and not definitions:
                    # Supplementary directories, spell lists and option pages
                    # share the class folder.  Without an explicit grant-level
                    # marker they remain reference material, not subclasses.
                    continue
                subclasses.append(
                    {
                        "name": candidate_name,
                        "source_record_id": str(candidate.get("stable_id") or ""),
                        "source_path": candidate_path,
                        "rule_year": str(
                            candidate.get("normalized_edition")
                            or candidate.get("edition")
                            or rule.rule_year
                        ),
                        "content_pack_key": candidate.get("content_pack_key"),
                        "feature_definitions": list(definitions),
                        "automation_status": "partial" if definitions else "dm_only",
                        "selectable_for_automatic_advancement": (
                            bool(definitions) or not is_extension
                        ),
                        "requires_dm_adjudication": True,
                    }
                )
            with_subclasses.append(
                ClassProgression(
                    name=rule.name,
                    source_record_id=rule.source_record_id,
                    source_path=rule.source_path,
                    hit_die=rule.hit_die,
                    levels=rule.levels,
                    subclasses=tuple(subclasses),
                    rule_year=rule.rule_year,
                    content_pack_key=rule.content_pack_key,
                )
            )
        return tuple(sorted(with_subclasses, key=lambda item: item.name))

    def options(
        self,
        *,
        enabled_content_packs: object = (),
        allow_legacy: bool = False,
    ) -> dict[str, Any]:
        enabled_pack_keys = frozenset(
            validate_content_pack_compatibility(
                enabled_content_packs,
                allow_legacy=allow_legacy,
            )
            if enabled_content_packs
            else ()
        )
        records = self._records(
            enabled_content_packs=enabled_pack_keys,
            allow_legacy=allow_legacy,
        )

        def spell_summary(record: dict[str, Any]) -> dict[str, Any]:
            mechanics = {
                **dict(record.get("spell") or {}),
                **spell_rule_fields(record),
            }
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
                "healing": mechanics.get("healing"),
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
                "resolution_kind": str(
                    mechanics.get("resolution_kind")
                    or (
                        "damage"
                        if damage_expression
                        else "heal"
                        if mechanics.get("healing")
                        else "narrative"
                    )
                ),
            }
            content_pack = content_pack_for_record(record, allow_source_path=True)
            if content_pack is not None:
                summary.update(
                    {
                        "content_pack_key": content_pack.key,
                        "content_pack_label": content_pack.label,
                        "content_pack_status": "imported",
                    }
                )
            for key in (
                "area_shape", "area_size_ft", "max_targets", "conditions", "movement", "reaction",
                "upcast_damage_dice", "upcast_healing_dice", "half_damage_on_save", "summon",
            ):
                if mechanics.get(key) not in (None, "", [], {}):
                    summary[key] = mechanics[key]
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

        class_rules = self.classes(
            enabled_content_packs=enabled_pack_keys,
            allow_legacy=allow_legacy,
        )
        core_feats = core_feat_rules_from_records(records)
        extension_feats = extension_feat_rules_from_records(
            record for record in records if record.get("content_pack_key")
        )
        feat_rules = (*core_feats, *extension_feats)
        feat_options = [
            {
                "name": item.name,
                "category": item.category,
                "prerequisite": item.prerequisite,
                "source_record_id": item.source_record_id,
                "source_path": item.source_path,
                "rule_year": item.rule_year,
                "content_pack_key": item.content_pack_key,
                "automation_status": "dm_only",
                "selectable_for_automatic_advancement": True,
                "requires_dm_adjudication": True,
            }
            for item in feat_rules
        ]

        def extension_character_options() -> list[dict[str, Any]]:
            """Expose selected supplements with a truthful automation contract."""

            classes_by_source = {
                item.source_record_id: item for item in class_rules if item.content_pack_key
            }
            subclasses_by_source = {
                str(subclass.get("source_record_id") or ""): (rule, subclass)
                for rule in class_rules
                for subclass in rule.subclasses
                if subclass.get("content_pack_key")
            }
            feats_by_source = {item.source_record_id: item for item in extension_feats}
            entries: list[dict[str, Any]] = []
            for record in records:
                pack = content_pack_for_record(record, allow_source_path=True)
                source_id = str(record.get("stable_id") or "")
                source_path = str(record.get("source_relative_path") or "")
                name = str(record.get("name") or "").strip()
                if (
                    pack is None
                    or not name
                    or not record_is_enabled_for_content_packs(
                        record,
                        enabled_pack_keys,
                        allow_source_path=True,
                        allow_legacy=allow_legacy,
                    )
                ):
                    continue
                if source_id in classes_by_source:
                    kind, selectable, automation = "class", True, "partial"
                    parent_class = None
                    reason = "完整 1–20 成长表已标准化；特性按等级自动授予。"
                elif source_id in subclasses_by_source:
                    rule, subclass = subclasses_by_source[source_id]
                    kind = "subclass"
                    selectable = bool(subclass.get("selectable_for_automatic_advancement"))
                    automation = str(subclass.get("automation_status") or "dm_only")
                    parent_class = rule.name
                    reason = (
                        "显式等级标题已标准化；特性会在对应职业等级自动授予。"
                        if selectable
                        else "该子职没有可靠的等级标题；只能通过 DM 覆盖记录。"
                    )
                elif source_id in feats_by_source:
                    kind, selectable, automation = "feat", True, "dm_only"
                    parent_class = None
                    reason = "前置条件已进入共享专长校验；具体效果保留 DM 裁定。"
                else:
                    content_type = str(record.get("content_type") or "")
                    if "专长" in source_path or content_type == "feats":
                        kind = "feat"
                    elif "职业" in source_path or content_type in {"classes", "subclasses"}:
                        kind = "subclass"
                    else:
                        continue
                    selectable, automation = False, "dm_only"
                    parent_class = self._subclass_parent_class(
                        record, {item.name for item in class_rules}
                    )
                    reason = "来源已隔离并可查阅；缺少可验证的结构，需 DM 明确选择。"
                entries.append(
                    {
                        "name": name,
                        "source_record_id": source_id,
                        "source_path": source_path,
                        "content_pack_key": pack.key,
                        "content_pack_label": pack.label,
                        "source_edition": normalized_record_edition(record),
                        "source_origin": "official_supplement",
                        "kind": kind,
                        "parent_class": parent_class,
                        "normalization_status": "structured" if selectable else "dm_choice",
                        "automation_status": automation,
                        "selectable_for_automatic_advancement": selectable,
                        "requires_dm_adjudication": True,
                        "reason": reason,
                    }
                )
            return sorted(
                entries,
                key=lambda item: (
                    str(item["content_pack_key"]),
                    str(item["kind"]),
                    str(item["name"]),
                    str(item["source_record_id"]),
                ),
            )

        return {
            "edition": 2024,
            "officiality": "official",
            "allow_legacy": allow_legacy,
            "classes": [
                {
                    "name": item.name,
                    "source_record_id": item.source_record_id,
                    "source_path": item.source_path,
                    "rule_year": item.rule_year,
                    "content_pack_key": item.content_pack_key,
                    "source_origin": (
                        "official_supplement" if item.content_pack_key else "official_core"
                    ),
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
                            "scaling_updates": progression_scaling_updates(
                                item,
                                level.level,
                            ),
                            "feature_grants": list(
                                core_feature_grants(item, level.level)
                            ),
                            "runtime_actions": list(
                                core_runtime_actions(item, level.level)
                            ),
                            "runtime_contract": core_class_level_runtime_contract(
                                item,
                                level.level,
                            ),
                        }
                        for level in item.levels
                    ],
                    "subclasses": list(item.subclasses),
                }
                for item in class_rules
            ],
            "species": summaries("玩家手册2024/角色起源/种族/"),
            "backgrounds": summaries("玩家手册2024/角色起源/背景/"),
            "feats": feat_options or summaries("玩家手册2024/专长/"),
            "spells": sorted(
                (
                    spell_summary(record)
                    for record in records
                    if record.get("spell")
                    and (
                        "玩家手册2024/法术详述/"
                        in str(record.get("source_relative_path") or "")
                        or (
                            record_is_enabled_for_content_packs(
                                record,
                                enabled_pack_keys,
                                allow_source_path=True,
                                allow_legacy=allow_legacy,
                            )
                            and is_spell_detail_record(record)
                        )
                    )
                ),
                key=lambda item: (item["level"], item["name"]),
            ),
            "enabled_content_packs": sorted(enabled_pack_keys),
            "content_packs": [
                pack for pack in list_content_packs() if pack["key"] in enabled_pack_keys
            ],
            "extension_character_options": extension_character_options(),
            "extension_character_option_policy": {
                "automatic_advancement": "structured_core_or_enabled_supplement",
                "unstructured_extension_behavior": "structured_dm_choice",
                "reason": (
                    "扩展职业需要完整 1–20 表；子职需显式等级标题；复杂分支始终要求 DM 选择。"
                ),
            },
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
