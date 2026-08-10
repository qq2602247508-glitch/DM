#!/usr/bin/env python3
"""Produce deterministic capability completion-unlock ranking."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.feature_capability_unlocks import plan_capability_unlocks

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "reports/feature-clause-corpus-2026-08-10.json"
OUTPUT = ROOT / "reports/feature-capability-unlock-ranking-2026-08-10.json"


def main() -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    report = plan_capability_unlocks(corpus)
    report["audit_total"] = corpus["audit_total"]
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("feature_count", "clause_count", "typed_missing_contract_count", "untyped_clause_count", "qualified_cluster_found")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
