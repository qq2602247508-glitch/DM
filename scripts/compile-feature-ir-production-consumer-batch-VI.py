#!/usr/bin/env python3
"""Emit the clause-graph production decision report for batch VI."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "reports/class-feature-audit-2026-08-07.json"
CORPUS = ROOT / "reports/feature-clause-corpus-2026-08-10.json"
UNLOCKS = ROOT / "reports/feature-capability-unlock-ranking-2026-08-10.json"
OUTPUT = ROOT / "reports/feature-ir-production-consumer-batch-VI-2026-08-10.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    unlocks = json.loads(UNLOCKS.read_text(encoding="utf-8"))
    result = {
        "schema_version": "feature-ir-production-consumer-batch-VI-1",
        "batch_id": "feature_clause_unlock_graph",
        "audit_total": audit["scope"]["total_features"],
        "before_status_counts": audit["status_counts"],
        "after_status_counts": audit["status_counts"],
        "actual_new_full": 0,
        "direct_ir_authority_count": 0,
        "verified_mapping_count": 0,
        "legacy_authority_count": 0,
        "clause_corpus": {
            "feature_count": corpus["feature_count"],
            "clause_count": corpus["clause_count"],
            "source_complete_feature_count": corpus["source_complete_feature_count"],
            "source_incomplete_feature_count": corpus["source_incomplete_feature_count"],
        },
        "unlock_graph": {
            "typed_missing_contract_count": unlocks["typed_missing_contract_count"],
            "untyped_clause_count": unlocks["untyped_clause_count"],
            "qualified_cluster_found": unlocks["qualified_cluster_found"],
            "eligible_capability_ids": unlocks["eligible_capability_ids"],
        },
        "production_decision": "no_platform_selected",
        "stop_reasons": [
            "全部 118 条 partial 均有 located source；旧 planner 的 missing_source=35 不是 source_parse 缺失。",
            "166 个 clause review 单元仍缺 trigger、target、effect、producer、consumer、persistence、CAS、idempotency 等显式合同。",
            "没有一个字段完整的 missing capability contract，因此 completion_unlock_count >= 8 的候选为 0。",
            "按 fail-closed 规则，禁止把文本锚点频次或 missing_semantic_contract 当成可实现平台。",
        ],
        "next_required_gate": "author reviewed typed clauses before platform selection",
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
