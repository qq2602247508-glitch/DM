from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-VIII-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-X.json"


def test_round_VIII_typed_combat_consumer_has_real_evidence() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert report["checks"]["all_preview_confirm_replay"] is True
    assert report["checks"]["all_typed_consumers"] is True
    assert report["checks"]["all_runtime_id_bound"] is True
    assert report["checks"]["all_inspection_or_activation"] is True
    assert report["checks"]["all_resource_cas"] is True
    assert report["checks"]["activation_resolution_count"] == 1
    assert report["checks"]["passive_registry_bound_count"] == 7
    assert report["checks"]["name_branch_count"] == 0
    assert report["formal_apply"] is False
    assert report["isolated_database"] is True
    assert len(report["selected_feature_ids"]) == 8
    assert results["production_runtime_full_ids"] == sorted(report["selected_feature_ids"])
