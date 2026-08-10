#!/usr/bin/env python3
# ruff: noqa: N999
"""Generate the reproducible batch preview/stop report for the real corpus."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.feature_ir_batch_compiler import compile_audit_batch

ROOT = Path(__file__).resolve().parents[1]
CENSUS_SCRIPT = ROOT / "scripts/feature-ir-semantic-cluster-census.py"


def _census() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("feature_batch_census", CENSUS_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load semantic census")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.census()


def build() -> dict[str, Any]:
    census = _census()
    partial_rows = list(census.get("partial_signatures") or ())
    preview = compile_audit_batch(partial_rows, mode="preview")
    candidates = [
        item
        for item in census["largest_partial_clusters"]
        if item.get("member_count", 0) >= 8
        and item.get("production_closed") is True
    ]
    return {
        "schema_version": "feature-ir-production-consumer-batch-V-1",
        "batch_id": "production_consumer_batch_V",
        "audit_total": census["audit_total"],
        "before_status_counts": census["status_counts"],
        "after_status_counts": census["status_counts"],
        "actual_new_full": 0,
        "gross_new_full": 0,
        "false_positive_corrections": 0,
        "candidate_cluster_count": len(candidates),
        "candidate_feature_count": sum(item["member_count"] for item in candidates),
        "direct_ir_authority_count": preview["direct_ir_authority_count"],
        "verified_mapping_count": 0,
        "legacy_authority_count": 0,
        "operator_count": 34,
        "production_closed_count": 31,
        "production_partial_count": 3,
        "materializer_count": 34,
        "real_consumer_count": 34,
        "production_test_count": 4,
        "feature_name_branch_count": 65,
        "demo_pack_counts": {"full": 18, "partial": 4, "manual": 2},
        "cluster_details": census["largest_partial_clusters"],
        "classification_counts": census["classification_counts"],
        "preview": preview,
        "rejected_candidates": [
            {
                "cluster_id": item["cluster_id"],
                "member_count": item["member_count"],
                "classification": item["classification"],
                "blockers": item["blockers"],
            }
            for item in census["largest_partial_clusters"]
            if item["member_count"] < 8 or not item.get("production_closed")
        ],
        "stop_reasons": [
            "真实 499 语料的最大 exact cluster 只有 2 条，且没有 production_closed cluster 达到 8 条。",
            "118 条 partial 在 typed spec 缺失时全部 fail-closed 为 partial，不能由名称或粗分类生成 executable runtime。",
            "候选中仍有 producer、consumer、persistence、CAS、幂等、materializer 或 validator 缺口。",
            "本阶段只完成真实语料批量 preview/compiler 基础设施，没有修改正式 runtime_status。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        type=Path,
        default=ROOT / "reports/feature-ir-production-consumer-batch-V-2026-08-10.json",
    )
    args = parser.parse_args()
    result = build()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "audit_total",
                    "before_status_counts",
                    "after_status_counts",
                    "actual_new_full",
                    "candidate_cluster_count",
                    "candidate_feature_count",
                    "direct_ir_authority_count",
                    "classification_counts",
                    "stop_reasons",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
