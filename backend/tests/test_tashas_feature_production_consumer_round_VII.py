from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-VII-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-IX.json"


def test_round_VII_advancement_consumer_has_real_character_growth_evidence() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert report["checks"]["all_preview_confirm_replay"] is True
    assert report["checks"]["all_typed_consumers"] is True
    assert report["checks"]["character_cas_and_transaction"] is True
    assert report["checks"]["advancement_blocks_ready"] is True
    assert report["checks"]["grant_spell_consumer"] is True
    assert report["checks"]["choice_lifecycle_consumers"] == 4
    assert report["checks"]["name_branch_count"] == 0
    assert report["formal_apply"] is False
    assert report["isolated_database"] is True
    assert len(report["selected_feature_ids"]) == 8
    assert results["production_runtime_full_ids"] == sorted(report["selected_feature_ids"])
