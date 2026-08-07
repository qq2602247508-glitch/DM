# ruff: noqa: N999
"""Plan feature migrations without promoting keyword matches to ``full``.

The class-feature audit intentionally reports overlapping source candidates.
This planner adds the missing execution-readiness layer: it groups non-full
rows by the first reusable contract that could consume them, records missing
fields and consumer state, and only marks a row ``batch_ready`` when its source
is available, its contract has a production consumer, and no manual boundary
was detected.  It does not mutate feature snapshots or audit statuses.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts/audit-class-feature-coverage.py"

# Ordered from the most specific event-driven contracts to broad structural
# labels.  The labels are planning buckets, not executor implementations.
TEMPLATE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("zero_hp_intervention", "0 HP/死亡生命周期", ("zero_hp",)),
    ("attack_rider", "命中后骑手", ("hit_rider",)),
    ("roll_intervention", "掷骰干预", ("roll_intervention",)),
    ("pre_damage_intervention", "伤害前/防御干预", ("pre_damage_defense",)),
    ("aura_passive", "光环/范围被动", ("aura_range",)),
    ("summon_lifecycle", "召唤/伙伴", ("summon_companion",)),
    ("state_lifecycle", "状态生命周期", ("status_lifecycle",)),
    ("movement", "移动/位移", ("movement",)),
    ("damage_healing", "伤害/治疗", ("damage_healing",)),
    ("target_save_status", "目标/范围/豁免组合", ("target_range_save", "save_dc")),
    ("resource_lifecycle", "资源/恢复/频率", ("resource_recovery", "resource_binding")),
    ("action_trigger", "动作经济与触发条件", ("action_trigger", "action_economy")),
    ("spell_capability", "施法框架/法术修改", ("spellcasting", "spell_selection")),
    ("progression_grant", "成长授予/升级选择", ("advancement_choice",)),
    ("passive_modifier", "通用被动/数值修正", ()),
    ("manual_narrative", "DM/开放叙事", ("narrative_language",)),
)

PRODUCTION_CONSUMERS = {
    "zero_hp_intervention": "production_closed",
    "pre_damage_intervention": "production_closed",
    "aura_passive": "production_closed",
    "summon_lifecycle": "production_closed",
    "state_lifecycle": "production_closed",
    "movement": "production_closed",
    "damage_healing": "production_closed",
    "target_save_status": "production_closed",
    "resource_lifecycle": "production_closed",
    "action_trigger": "production_closed",
    "spell_capability": "production_partial",
    "progression_grant": "production_closed",
    "passive_modifier": "production_closed",
    "roll_intervention": "production_partial",
    "attack_rider": "production_partial",
    "manual_narrative": "manual_only",
}

FIELD_REQUIREMENTS = {
    "zero_hp_intervention": ("trigger", "eligibility", "save/result", "reset"),
    "attack_rider": ("after_hit trigger", "target/qualification", "resource/frequency", "effect"),
    "roll_intervention": ("trigger", "operation", "input", "resource consumption"),
    "pre_damage_intervention": ("before_damage trigger", "damage eligibility", "transformation", "resource"),
    "aura_passive": ("source/target relation", "range", "stacking", "effect"),
    "summon_lifecycle": ("template", "quantity", "control", "duration"),
    "state_lifecycle": ("condition", "duration/end", "immunity or removal"),
    "movement": ("destination/distance", "path rule", "action/resource"),
    "damage_healing": ("dice/expression", "type/effect", "target", "lifecycle"),
    "target_save_status": ("target/range", "save ability/DC", "success/failure", "effect"),
    "resource_lifecycle": ("resource key", "cost", "recovery", "fail-closed"),
    "action_trigger": ("event", "action economy", "qualification", "effect"),
    "spell_capability": ("spell identity/list", "slot/choice", "consumer", "effect"),
    "progression_grant": ("choice schema", "validation", "grant consumer"),
    "passive_modifier": ("stat", "operation", "qualification", "consumer"),
    "manual_narrative": ("DM adjudication",),
}

MANUAL_MARKERS = (
    "需要 DM",
    "需由 DM",
    "由 DM",
    "需要选择",
    "任选",
    "自选",
    "具体法术",
    "具体形态",
    "具体选项",
    "开放叙事",
)


def _audit_module() -> Any:
    spec = importlib.util.spec_from_file_location("class_feature_audit", AUDIT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load class feature audit")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _template(row: dict[str, Any]) -> tuple[str, str]:
    blocks = set(row.get("detected_blocks") or ())
    for key, label, required_blocks in TEMPLATE_RULES:
        if required_blocks and any(block in blocks for block in required_blocks):
            return key, label
    return "passive_modifier", "通用被动/数值修正"


def _missing_fields(row: dict[str, Any], template: str) -> list[str]:
    description = str(row.get("source_description") or "")
    missing = list(FIELD_REQUIREMENTS.get(template, ()))
    if row.get("source_parse") not in {"description_located", "description_reused"}:
        missing.insert(0, "source description")
    if template != "manual_narrative" and not description.strip():
        missing.insert(0, "source description")
    return list(dict.fromkeys(missing))


def plan() -> dict[str, Any]:
    report = _audit_module().audit()
    rows: list[dict[str, Any]] = []
    for row in report["rows"]:
        if row["runtime_status"] == "full":
            readiness = "already_full"
            template, label = _template(row)
            blocker: list[str] = []
        else:
            template, label = _template(row)
            description = str(row.get("source_description") or "")
            has_manual_marker = any(marker in description for marker in MANUAL_MARKERS)
            source_available = row.get("source_parse") in {
                "description_located",
                "description_reused",
            }
            consumer = PRODUCTION_CONSUMERS[template]
            blocker = _missing_fields(row, template)
            if has_manual_marker or template == "manual_narrative":
                readiness = "manual_boundary"
                blocker.append("manual choice/adjudication boundary")
            elif not source_available:
                readiness = "missing_source"
            elif consumer == "manual_only":
                readiness = "manual_boundary"
            elif consumer == "production_partial":
                readiness = "consumer_partial"
                blocker.append("consumer integration or security closure")
            elif not row.get("runtime_sections"):
                readiness = "missing_runtime_contract"
                blocker.append("no runtime section/production configuration")
            else:
                readiness = "needs_contract_review"
                blocker.append("field-by-field contract review")
        rows.append(
            {
                "scope": row["scope"],
                "class_name": row["class_name"],
                "subclass_name": row.get("subclass_name"),
                "level": row["level"],
                "feature_name": row["feature_name"],
                "runtime_status": row["runtime_status"],
                "source_parse": row["source_parse"],
                "template": template,
                "template_label": label,
                "consumer_status": PRODUCTION_CONSUMERS[template],
                "readiness": readiness,
                "missing_fields": list(dict.fromkeys(blocker)),
            }
        )

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = grouped.setdefault(
            row["template"],
            {
                "label": row["template_label"],
                "consumer_status": row["consumer_status"],
                "total": 0,
                "already_full": 0,
                "missing_runtime_contract": 0,
                "needs_contract_review": 0,
                "consumer_partial": 0,
                "manual_boundary": 0,
                "missing_source": 0,
            },
        )
        group["total"] += 1
        group[row["readiness"]] = group.get(row["readiness"], 0) + 1

    readiness_counts = Counter(row["readiness"] for row in rows)
    return {
        "schema_version": "feature-automation-migration-plan-1",
        "audit_scope": report["scope"],
        "audit_status_counts": report["status_counts"],
        "readiness_counts": dict(readiness_counts),
        "templates": grouped,
        "rows": rows,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# 特性自动化迁移预审报告",
        "",
        "这份报告只规划迁移，不修改运行时状态，也不把候选行直接升级为 `full`。",
        "",
        f"- 总条目：{report['audit_scope']['total_features']}",
        f"- 当前状态：`{report['audit_status_counts']}`",
        f"- 预审状态：`{report['readiness_counts']}`",
        "",
        "## 模板分组",
        "",
        "| 模板 | 条目 | 已 full | 缺运行时合同 | 待合同复核 | 消费者不完整 | 人工边界 | 缺源码 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, group in report["templates"].items():
        lines.append(
            "| {label} (`{key}`) | {total} | {already_full} | {missing_runtime_contract} | "
            "{needs_contract_review} | {consumer_partial} | {manual_boundary} | {missing_source} |".format(
                key=key, **group
            )
        )
    lines.extend(
        [
            "",
            "## 预审结论",
            "",
            "- `missing_runtime_contract`：源码命中积木，但还没有真实运行时合同；不能仅靠字段改成 `full`。",
            "- `needs_contract_review`：已有部分运行时结构，但仍需逐字段核对消费者、输入、资源和幂等。",
            "- `consumer_partial`：执行器存在，但生产接线或安全闭环未完成。",
            "- `manual_boundary`：包含选择、DM裁定或开放叙事，不能强行无人值守。",
            "- 只有完成真实配置、消费者、状态写入、输入链和测试后，才允许从本报告中产生 `full` 增量。",
            "",
            "## 下一批执行门槛",
            "",
            "下一批必须从一个模板中选择一组条目，先生成配置和定向测试，再跑499条审计。预审数字是候选分组，不是承诺的新增 `full` 数量。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        type=Path,
        default=ROOT / "reports/feature-automation-migration-plan-2026-08-07.json",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=ROOT / "docs/feature-automation-migration-plan-2026-08-07.md",
    )
    args = parser.parse_args()
    report = plan()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(report, args.markdown)
    print(json.dumps({key: report[key] for key in ("audit_scope", "audit_status_counts", "readiness_counts", "templates")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
