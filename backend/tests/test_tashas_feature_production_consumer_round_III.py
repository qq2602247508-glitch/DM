from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-III-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-V.json"


def test_round_III_real_consumer_batch_has_typed_and_dm_evidence() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = report["results"]
    assert len(results) == 12
    assert sum(item.get("execution_mode") == "typed" for item in results) == 11
    assert sum(item.get("execution_mode") == "dm_approved_typed" for item in results) == 1
    assert all(item["preview"] and item["confirm"] and item["replay"] for item in results)
    assert report["checks"]["all_preview_confirm_replay"] is True
    assert report["checks"]["all_typed_consumers"] is True
    assert report["checks"]["name_branch_count"] == 0
    assert report["formal_apply"] is False
    assert report["isolated_database"] is True


def test_round_III_evidence_is_consumed_by_whole_pack_status_layers() -> None:
    migration = json.loads(
        (ROOT / "reports/tashas-whole-pack-report-2026-08-11.json").read_text(encoding="utf-8")
    )
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert len(results["production_runtime_full_ids"]) == 12
    assert migration["runtime"]["atom_production_full_count"] == 44
    assert migration["runtime"]["atom_dm_assisted_count"] == 2
    assert migration["status_layers"]["game_usable"] == 46
