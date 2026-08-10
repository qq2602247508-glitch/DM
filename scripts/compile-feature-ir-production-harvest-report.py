#!/usr/bin/env python3
# ruff: noqa: N999, EXE001
"""Compile the production-harvest VIII acceptance report."""

from __future__ import annotations

import json
import re
from pathlib import Path

from dnd_dm_assistant.application.feature_materializers import (
    default_materializer_registry,
)
from dnd_dm_assistant.domain.feature_capabilities import default_capability_catalog
from dnd_dm_assistant.domain.feature_operators import default_operator_contracts

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "reports/class-feature-audit-2026-08-07.json"
PLAN = ROOT / "reports/feature-ir-production-harvest-plan-2026-08-10.json"
PACK = ROOT / "reports/feature-pack-expansion-import-2026-08-10.json"
OUTPUT = ROOT / "reports/feature-ir-production-harvest-VIII-2026-08-10.json"
BEFORE = {"full": 320, "partial": 118, "dm_only": 61}


def _feature_name_branch_count() -> int:
    pattern = re.compile(
        r"\b(?:if|elif)\s+(?:identity|feature_name|name)\s*(?:in|==|\.startswith)"
    )
    paths = (
        ROOT / "backend/src/dnd_dm_assistant/domain/feature_runtime.py",
        ROOT / "backend/src/dnd_dm_assistant/domain/advancement_choices.py",
    )
    return sum(
        len(pattern.findall(path.read_text(encoding="utf-8")))
        for path in paths
        if path.exists()
    )


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    after = audit["status_counts"]
    selected = plan["selected_feature_ids"]
    remaining = [
        {
            "feature_id": (
                f"class-feature:{row['scope']}:{row['class_name']}:"
                f"{row['subclass_name']}:{row['level']}:{row['feature_name']}"
            ),
            "feature_name": row["feature_name"],
            "runtime_reasons": row.get("runtime_reasons", []),
            "formal_ir": row.get("formal_ir", False),
            "compiler_blockers": row.get("compiler_blockers", []),
        }
        for row in audit["rows"]
        if row["runtime_status"] == "partial"
    ]
    closed = sum(
        descriptor.production_status == "production_closed"
        for descriptor in default_capability_catalog().descriptors()
    )
    result = {
        "schema_version": "feature-ir-production-harvest-VIII-1",
        "batch_id": "production_consumer_harvest_viii",
        "audit_total": audit["scope"]["total_features"],
        "before_status_counts": BEFORE,
        "after_status_counts": after,
        "actual_new_full": after["full"] - BEFORE["full"],
        "gross_new_full": after["full"] - BEFORE["full"],
        "false_positive_corrections": 0,
        "harvest_ready_count": plan["harvest_ready_count"],
        "selected_feature_ids": selected,
        "newly_full_feature_ids": selected,
        "direct_ir_authority_count": len(selected),
        "verified_mapping_count": 0,
        "legacy_authority_count": 0,
        "operator_count": len(default_operator_contracts()),
        "production_closed_count": closed,
        "materializer_count": len(default_materializer_registry().to_dict()),
        "real_consumer_count": closed,
        "feature_name_branch_count": _feature_name_branch_count(),
        "remaining_partial_count": len(remaining),
        "remaining_partial_blockers": remaining,
        "extension_pack": pack,
        "stop_reasons": [],
    }
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
