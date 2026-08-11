from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XVI-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XVIII.json"


def test_round_XVI_character_growth_consumes_typed_tool_proficiency_batch() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    checks = report["checks"]
    assert report["formal_apply"] is False
    assert report["isolated_database"] is True
    assert len(report["selected_feature_ids"]) == 4
    assert checks["production_runtime_full_count"] == 4
    assert checks["all_preview_confirm_replay"] is True
    assert checks["all_typed_consumers"] is True
    assert checks["character_cas_and_transaction"] is True
    assert checks["advancement_blocks_ready"] is True
    assert checks["proficiency_grant_count"] == 5
    assert checks["name_branch_count"] == 0
    assert results["content_kind"] == "advancement"
    assert results["production_runtime_full_ids"] == sorted(
        item["content_id"] for item in report["results"]
    )
