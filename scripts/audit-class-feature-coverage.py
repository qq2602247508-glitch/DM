#!/usr/bin/env python3
# ruff: noqa: N999
"""Audit class and subclass feature source coverage separately from runtime coverage.

This report is deliberately conservative.  It never turns a keyword match into
an executable rule.  ``source_parse`` answers whether a source description was
located and retained; ``runtime_status`` comes from the existing typed runtime
contract.  The two fields are kept separate because a complete source sentence
can still have no executor, while a partial executor can exist for a feature
whose remaining prose is not implemented.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.character_catalog import CharacterCatalog
from dnd_dm_assistant.domain.advancement_choices import (
    CORE_CLASSES_2024,
    core_class_level_runtime_contract,
    subclass_feature_automation_status,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/generated-content/dnd5e_chm/json"

CORE_HEADING = re.compile(r"\*\*(?P<level>\d{1,2})级：(?P<name>.*?)\*\*", re.DOTALL)
CORE_HEADING_LINE = re.compile(
    r"(?m)^\s*\*{0,2}(?P<level>\d{1,2})级：(?P<name>[^\n*]+?)\*{0,2}\s*$"
)

# These are audit labels, not executor implementations.  A feature can match
# multiple labels; report counts therefore intentionally overlap.
BLOCK_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "advancement_choice",
        "成长授予/升级选择",
        (
            "属性值提升",
            "传奇恩惠",
            "战斗风格",
            "武器精通",
            "专精",
            "选择以下",
            "选择其中",
            "选择一项",
            "选择之一",
        ),
    ),
    (
        "spellcasting",
        "施法框架/法术修改",
        ("施法", "法术位", "准备法术", "戏法", "法术列表", "始终准备", "施展法术", "施放法术"),
    ),
    (
        "spell_modification",
        "法术框架详细修改",
        ("额外目标", "第二个生物", "法术距离", "法术范围", "将其视作", "法术效果"),
    ),
    (
        "spell_selection",
        "法术选择/准备",
        ("始终准备着", "选择一道", "选择一项法术", "替换为另一道法术", "法术列表"),
    ),
    (
        "action_economy",
        "动作经济",
        (
            "以一个动作",
            "以一个附赠动作",
            "作为一个动作",
            "作为一个附赠动作",
            "以一个魔法动作",
            "以一个反应",
            "作为反应",
        ),
    ),
    (
        "action_trigger",
        "动作经济与触发条件",
        ("每当", "当你", "当一个生物", "在你进行", "在受到伤害时", "在回合开始"),
    ),
    (
        "resource_recovery",
        "资源/恢复/频率",
        ("使用次数", "消耗", "重获", "恢复", "短休", "长休", "法术位"),
    ),
    (
        "resource_binding",
        "资源/恢复绑定",
        ("消耗一次", "消耗一个法术位", "消耗圣疗", "消耗引导神力", "重获所有"),
    ),
    ("damage_healing", "伤害/治疗", ("伤害", "治疗", "生命值", "临时生命值", "恢复生命")),
    (
        "pre_damage_defense",
        "伤害前/防御干预",
        ("受到伤害", "伤害减半", "伤害抗性", "伤害免疫", "伤害前", "减少伤害"),
    ),
    ("aura_range", "光环/范围被动", ("光环", "范围内", "尺内", "距离你", "半径")),
    (
        "roll_intervention",
        "掷骰干预",
        ("重骰", "具有优势", "具有劣势", "优势进行", "劣势进行", "D20检定", "D20掷骰", "骰具有"),
    ),
    (
        "hit_rider",
        "命中后骑手",
        ("攻击检定并命中", "攻击命中", "命中目标时", "命中时额外", "额外受到"),
    ),
    ("save_dc", "豁免/DC", ("豁免", "DC", "难度等级", "豁免检定")),
    (
        "target_range_save",
        "目标/范围/豁免组合",
        ("选择目标", "选择位于", "目标必须", "范围内", "尺内"),
    ),
    (
        "movement",
        "移动/位移",
        ("移动速度", "传送", "位移", "飞行速度", "强制移动", "推离", "拉向", "撤离"),
    ),
    (
        "zero_hp",
        "0 HP/死亡生命周期",
        ("生命值降至0", "生命值降到0", "生命值为0", "0点生命值", "昏迷", "濒死"),
    ),
    (
        "status_lifecycle",
        "状态生命周期",
        ("目盲", "魅惑", "恐慌", "麻痹", "震慑", "隐形", "失能", "持续"),
    ),
    ("summon_companion", "召唤/伙伴", ("召唤", "精魂", "伙伴", "魔宠", "召唤物")),
    ("world_state", "创造物/世界状态", ("创造出", "生成", "物件", "环境", "植物生长", "世界")),
    (
        "narrative_language",
        "语言/开放叙事",
        ("秘密语言", "隐藏信息", "语言交流", "传递隐藏信息", "社交"),
    ),
    (
        "choice_branch",
        "多分支选择",
        ("选择以下", "选择其中", "以下一项", "二选一", "任选", "从以下"),
    ),
)


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("**", "")).strip()


def _core_source_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    markdown = str(record.get("content_markdown") or "")
    matches = list(CORE_HEADING.finditer(markdown))
    matches.extend(CORE_HEADING_LINE.finditer(markdown))
    # Keep the first marker for a position; bold headings are otherwise found
    # twice by the permissive line parser.
    unique: dict[int, re.Match[str]] = {}
    for match in matches:
        previous = unique.get(match.start())
        if previous is None or match.end() - match.start() > previous.end() - previous.start():
            unique[match.start()] = match
    matches = sorted(unique.values(), key=lambda item: item.start())
    entries: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        level = int(match.group("level"))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        name = _compact(match.group("name"))
        description = markdown[start:end].strip()
        entries.append({"level": level, "name": name, "description": description})
    return entries


def _feature_name_matches(table_name: str, source_name: str) -> bool:
    table = re.sub(r"[（(].*?[）)]", "", _compact(table_name)).split(" ")[0]
    source = re.sub(r"[（(].*?[）)]", "", _compact(source_name))
    aliases = {
        "子职特性": ("子职", "子职特性", "Subclass"),
        "施法": ("施法", "Spellcasting"),
    }
    if table in source or source.startswith(table):
        return True
    if "子职" in table and "子职" in source:
        return True
    return any(alias in source for alias in aliases.get(table, ()))


def _source_for_core(record: dict[str, Any], level: int, table_name: str) -> dict[str, Any] | None:
    if _compact(table_name) == "子职特性":
        # Later subclass grant rows point to the selected subclass document;
        # the class page intentionally has no second prose section to copy.
        return None
    candidates = [
        item
        for item in _core_source_entries(record)
        if int(item["level"]) == level and _feature_name_matches(table_name, item["name"])
    ]
    if candidates:
        return max(candidates, key=lambda item: len(item["description"]))
    # Repeated table grants (ASI, Epic Boon, subclass slots, etc.) normally
    # have one canonical prose section at the first granting level.  Reuse the
    # source section explicitly instead of calling later table rows "missing".
    repeated = [
        item
        for item in _core_source_entries(record)
        if _feature_name_matches(table_name, item["name"])
    ]
    if repeated:
        return max(repeated, key=lambda item: len(item["description"]))
    return None


def _blocks(description: str, title: str) -> list[str]:
    text = f"{title}\n{description}"
    return [
        key for key, _label, markers in BLOCK_PATTERNS if any(marker in text for marker in markers)
    ]


def _block_labels(keys: list[str]) -> list[str]:
    return [label for key, label, _markers in BLOCK_PATTERNS if key in keys]


def _source_parse(
    description: str | None, *, placeholder: bool = False, reused: bool = False
) -> str:
    if placeholder:
        return "structural_placeholder"
    if description is None:
        return "missing"
    if reused:
        return "description_reused"
    return "description_located"


def _runtime_map(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_status": contract.get("automation_status", "dm_only"),
        "runtime_sections": list(contract.get("runtime_sections") or []),
        "runtime_reasons": list(contract.get("reasons") or []),
    }


def audit() -> dict[str, Any]:
    catalog = CharacterCatalog(CORPUS)
    classes = catalog.classes()
    by_name = {item.name: item for item in classes}
    records_by_path: dict[str, dict[str, Any]] = {}
    for path in (CORPUS / "classes").glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records_by_path[str(value.get("source_relative_path") or "")] = value

    rows: list[dict[str, Any]] = []
    for class_name in sorted(CORE_CLASSES_2024):
        rule = by_name[class_name]
        record = records_by_path[rule.source_path]
        for level_rule in rule.levels:
            contract = core_class_level_runtime_contract(rule, level_rule.level)
            contracts = {item["name"]: item for item in contract["feature_contracts"]}
            for feature_name in level_rule.features:
                source = _source_for_core(record, level_rule.level, feature_name)
                description = source["description"] if source else None
                keys = _blocks(description or "", feature_name)
                runtime = _runtime_map(contracts[feature_name])
                placeholder = _compact(feature_name) == "子职特性"
                reused = bool(source and int(source["level"]) != level_rule.level)
                rows.append(
                    {
                        "scope": "core",
                        "class_name": class_name,
                        "subclass_name": None,
                        "level": level_rule.level,
                        "feature_name": feature_name,
                        "source_record_id": rule.source_record_id,
                        "source_path": rule.source_path,
                        "source_parse": _source_parse(
                            description, placeholder=placeholder, reused=reused
                        ),
                        "source_description_chars": len(description or ""),
                        "source_description": description or "",
                        "detected_blocks": keys,
                        "detected_block_labels": _block_labels(keys),
                        **runtime,
                    }
                )

        for subclass in rule.subclasses:
            subclass_name = str(subclass.get("name") or "")
            for definition in subclass.get("feature_definitions") or ():
                description = str(definition.get("description") or "")
                keys = _blocks(description, str(definition.get("name") or ""))
                configured_status = subclass_feature_automation_status(definition)
                runtime_status = configured_status or (
                    "partial" if subclass.get("automation_status") == "partial" else "dm_only"
                )
                rows.append(
                    {
                        "scope": "subclass",
                        "class_name": class_name,
                        "subclass_name": subclass_name,
                        "level": int(definition.get("class_level") or 0),
                        "feature_name": str(definition.get("name") or ""),
                        "source_record_id": definition.get("source_record_id"),
                        "source_path": definition.get("source_path"),
                        "source_parse": _source_parse(description),
                        "source_description_chars": len(description),
                        "source_description": description,
                        "detected_blocks": keys,
                        "detected_block_labels": _block_labels(keys),
                        "runtime_status": runtime_status,
                        "runtime_sections": [],
                        "runtime_reasons": [
                            "子职业当前仅同步授予、部分资源或动作字段；具体效果未统一接入执行器。"
                            if configured_status is None
                            else "已接入通用伤害防御积木并写入战斗快照。"
                        ],
                    }
                )

    status_counts = Counter(row["runtime_status"] for row in rows)
    source_counts = Counter(row["source_parse"] for row in rows)
    block_rows = {}
    for key, label, _markers in BLOCK_PATTERNS:
        matching = [row for row in rows if key in row["detected_blocks"]]
        block_rows[key] = {
            "label": label,
            "coverage": len(matching),
            "full": sum(row["runtime_status"] == "full" for row in matching),
            "partial": sum(row["runtime_status"] == "partial" for row in matching),
            "dm_only": sum(row["runtime_status"] == "dm_only" for row in matching),
        }
    return {
        "schema_version": "class-feature-audit-1",
        "scope": {
            "core_classes": len(CORE_CLASSES_2024),
            "core_features": sum(1 for row in rows if row["scope"] == "core"),
            "subclasses": sum(1 for item in classes for _ in item.subclasses),
            "subclass_features": sum(1 for row in rows if row["scope"] == "subclass"),
            "total_features": len(rows),
        },
        "status_counts": dict(status_counts),
        "source_parse_counts": dict(source_counts),
        "block_counts_overlap": block_rows,
        "rows": rows,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# 职业/子职业特性源码级审计",
        "",
        "这份报告把源码描述解析状态与运行时执行状态分开统计。积木覆盖数允许重叠，一条特性可以使用多个积木；检测到积木不等于已有执行器。",
        "",
        f"- 总条目：{report['scope']['total_features']}",
        (
            f"- 核心职业：{report['scope']['core_classes']} 个，"
            f"特性 {report['scope']['core_features']} 条"
        ),
        (
            f"- 子职业：{report['scope']['subclasses']} 个，"
            f"显式等级特性 {report['scope']['subclass_features']} 条"
        ),
        f"- 运行时状态：`{report['status_counts']}`",
        f"- 源码读取状态：`{report['source_parse_counts']}`",
        "",
        "## 积木覆盖（允许重叠）",
        "",
        "| 积木 | 源码候选 | full | partial | dm_only |",
        "|---|---:|---:|---:|---:|",
    ]
    for value in report["block_counts_overlap"].values():
        lines.append(
            "| {label} | {coverage} | {full} | {partial} | {dm_only} |".format(
                **value
            )
        )
    lines.extend(
        [
            "",
            "## 需要优先复核的条目",
            "",
            "| 范围 | 职业 | 子职业 | 等级 | 特性 | 源码状态 | 运行时 | 检测积木 |",
            "|---|---|---|---:|---|---|---|---|",
        ]
    )
    for row in report["rows"]:
        if row["runtime_status"] == "dm_only" or row["source_parse"] != "description_located":
            labels = "、".join(row["detected_block_labels"]) or "未检测到"
            lines.append(
                "| {scope} | {class_name} | {subclass} | {level} | {feature} | "
                "{source} | {runtime} | {labels} |".format(
                    scope=row["scope"],
                    class_name=row["class_name"],
                    subclass=row["subclass_name"] or "—",
                    level=row["level"],
                    feature=row["feature_name"],
                    source=row["source_parse"],
                    runtime=row["runtime_status"],
                    labels=labels,
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json", type=Path, default=ROOT / "reports/class-feature-audit-2026-08-07.json"
    )
    parser.add_argument(
        "--markdown", type=Path, default=ROOT / "docs/class-feature-audit-2026-08-07.md"
    )
    args = parser.parse_args()
    report = audit()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, args.markdown)
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("scope", "status_counts", "source_parse_counts", "block_counts_overlap")
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
