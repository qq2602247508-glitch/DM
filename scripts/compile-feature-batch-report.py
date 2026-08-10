#!/usr/bin/env python3
# ruff: noqa: N999
"""Deterministic batch-assembly report for the current migration batch."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from dnd_dm_assistant.domain.feature_batch_declarations import BATCH_BUFF_FEATURES

ROOT = Path(__file__).resolve().parents[1]
CENSUS_SCRIPT = ROOT / "scripts" / "feature-ir-semantic-cluster-census.py"


def _census() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("feature_audit_census", CENSUS_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.census()


def build() -> dict[str, Any]:
    census = _census()
    status_counts = census["status_counts"]
    return {
        "schema_version": "feature-ir-production-consumer-batch-III-1",
        "batch_id": "production_consumer_batch_III",
        "audit_total": census["audit_total"],
        "before_status_counts": {"full": 315, "partial": 123, "dm_only": 61},
        "after_status_counts": status_counts,
        "actual_new_full": 2,
        "gross_new_full": 2,
        "false_positive_corrections": 0,
        "candidate_cluster_count": len(
            [
                cluster
                for cluster in census["largest_partial_clusters"]
                if cluster["member_count"] >= 8
            ]
        ),
        "candidate_feature_count": 0,
        "direct_ir_authority_count": 0,
        "verified_mapping_count": 0,
        "legacy_authority_count": 2,
        "batch_features": [
            {
                "feature_name": feature.name,
                "class_name": feature.class_name,
                "subclass_name": feature.subclass_name,
                "level": feature.level,
                "resource_key": feature.resource_key or None,
                "condition": feature.condition,
                "modifier_count": len(feature.modifiers),
                "defense_count": len(feature.defenses),
                "movement_mode_count": len(feature.movement_modes),
            }
            for feature in BATCH_BUFF_FEATURES
        ],
        "production_tests": [
            "backend/tests/test_combat_action_lifecycle.py::"
            "test_batch_buff_condition_gates_flight_and_resistance_end_to_end",
            "backend/tests/test_feature_batch_assembly.py",
        ],
        "census_evidence": {
            "partial_total": census["partial_total"],
            "partial_exact_cluster_count": census["partial_exact_cluster_count"],
            "largest_partial_cluster_member_count": census["largest_partial_clusters"][0][
                "member_count"
            ]
            if census["largest_partial_clusters"]
            else 0,
        },
        "stop_reason": (
            "真实语料 census 显示 121 条 partial 中 121 条是唯一语义签名、最大簇仅 2 条，"
            "不存在可收割的 ≥8 条同构簇；剩余 partial 依赖攻击骑手、多目标/光环、强制移动、"
            "召唤、目标信息读取、法术上下文等未接线机制。本轮新增批量装配层与 2 条真实闭环，"
            "未达到 20 条门槛，Goal 保持 active。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        type=Path,
        default=ROOT / "reports/feature-ir-production-consumer-batch-III-2026-08-10.json",
    )
    args = parser.parse_args()
    result = build()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
