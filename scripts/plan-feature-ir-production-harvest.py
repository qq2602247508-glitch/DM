#!/usr/bin/env python3
# ruff: noqa: N999, EXE001
"""Generate the production-harvest candidate plan."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.feature_ir_production_harvest import (
    build_production_harvest_plan,
)

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "reports/class-feature-audit-2026-08-07.json"
OUTPUT = ROOT / "reports/feature-ir-production-harvest-plan-2026-08-10.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    report = build_production_harvest_plan(audit["rows"])
    report["audit_total"] = audit["scope"]["total_features"]
    report["audit_status_counts"] = audit["status_counts"]
    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidate_count": report["candidate_count"],
                "harvest_ready_count": report["harvest_ready_count"],
                "selected_feature_ids": report["selected_feature_ids"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
