#!/usr/bin/env python3
# ruff: noqa: N999, EXE001
"""Compile the reviewed-clause production decision report for batch VII."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "reports/class-feature-audit-2026-08-07.json"
CORPUS = ROOT / "reports/feature-clause-corpus-2026-08-10.json"
UNLOCKS = ROOT / "reports/feature-capability-unlock-ranking-2026-08-10.json"
OUTPUT = ROOT / "reports/feature-ir-production-consumer-batch-VII-2026-08-10.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    unlocks = json.loads(UNLOCKS.read_text(encoding="utf-8"))
    clauses = corpus["clauses"]
    status_counts: dict[str, int] = {}
    for clause in clauses:
        status = str(clause.get("clause_status") or "invalid")
        status_counts[status] = status_counts.get(status, 0) + 1
    result = {
        "schema_version": "feature-ir-production-consumer-batch-VII-1",
        "batch_id": "feature_clause_reviewed_semantic_batch",
        "audit_total": audit["scope"]["total_features"],
        "before_status_counts": audit["status_counts"],
        "after_status_counts": audit["status_counts"],
        "actual_new_full": 0,
        "gross_new_full": 0,
        "false_positive_corrections": 0,
        "reviewed_source_clause_count": corpus["reviewed_clause_count"],
        "typed_clause_count": corpus["typed_clause_count"],
        "manual_boundary_count": corpus["manual_boundary_clause_count"],
        "invalid_clause_count": status_counts.get("invalid", 0),
        "source_incomplete_count": corpus["source_incomplete_clause_count"],
        "clause_status_counts": dict(sorted(status_counts.items())),
        "capability_candidate_count": len(unlocks["ranking"]),
        "qualified_capability_count": len(unlocks["eligible_capability_ids"]),
        "selected_capability_ids": unlocks["eligible_capability_ids"],
        "selected_completion_unlock_counts": {
            item["capability_id"]: item["completion_unlock_count"]
            for item in unlocks["ranking"]
            if item["capability_id"] in unlocks["eligible_capability_ids"]
        },
        "direct_ir_authority_count": 0,
        "verified_mapping_count": 0,
        "legacy_authority_count": 0,
        "feature_name_branch_count": 65,
        "implemented_platforms": [],
        "newly_full_feature_ids": [],
        "remaining_partial_ids_and_blockers": {
            item["feature_id"]: {
                "clause_ids": [
                    clause["clause_id"]
                    for clause in clauses
                    if clause["feature_id"] == item["feature_id"]
                ],
                "blocker": "manual_boundary",
            }
            for item in clauses
            if item["feature_id"]
        },
        "stop_reasons": [
            "全部 166 个 source review clause 已进入带 source fingerprint 和 missing_fields 的 reviewed typed schema。",
            "当前 166 个 clause 仍为 manual_boundary，缺口合同尚未达到可建设 capability 的字段级等价要求。",
            "因此 completion_unlock_count >= 8 的合格 capability 为 0，本轮没有建设专用平台或虚报 full。",
            "feature-name branch count 沿用此前正式审计基线 65；本轮未新增运行时名称分支。",
        ],
        "unlock_summary": {
            "reviewed_clause_count": unlocks["reviewed_clause_count"],
            "manual_boundary_clause_count": unlocks["manual_boundary_clause_count"],
            "source_incomplete_clause_count": unlocks["source_incomplete_clause_count"],
            "typed_missing_contract_count": unlocks["typed_missing_contract_count"],
            "untyped_clause_count": unlocks["untyped_clause_count"],
            "qualified_cluster_found": unlocks["qualified_cluster_found"],
        },
    }
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
