#!/usr/bin/env python3
"""Compile the partial-feature source corpus into non-executable Clause IR."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.feature_clause_corpus import compile_clause_corpus

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "reports/class-feature-audit-2026-08-07.json"
OUTPUT = ROOT / "reports/feature-clause-corpus-2026-08-10.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    report = compile_clause_corpus(audit["rows"])
    report["audit_total"] = int(audit["scope"]["total_features"])
    report["audit_partial"] = int(audit["status_counts"]["partial"])
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("feature_count", "clause_count", "source_complete_feature_count", "source_incomplete_feature_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
