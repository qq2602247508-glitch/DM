from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.tashas_recovery import load_item_production_evidence

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-item-production-consumer-round-XIII-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XV.json"
CATALOG = ROOT / "reports/tashas-item-spec-catalog-2026-08-11.json"


def test_round_XIII_adds_complete_item_consumer_batch() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    checks = report["checks"]
    assert report["formal_apply"] is False
    assert report["isolated_database"] is True
    assert len(report["selected_item_ids"]) == 8
    assert checks["production_runtime_full_count"] == 8
    assert checks["all_create_preview_confirm_replay"] is True
    assert checks["all_typed_consumers"] is True
    assert checks["all_item_state_persisted"] is True
    assert checks["all_attunement_cas"] is True
    assert checks["charge_lifecycle_count"] == 4
    assert checks["operation_transaction_count"] == 17
    assert checks["name_branch_count"] == 0
    assert results["content_kind"] == "item"
    assert results["production_runtime_full_ids"] == sorted(report["selected_item_ids"])
    assert load_item_production_evidence(ROOT) >= set(report["selected_item_ids"])
    assert catalog["item_spec_compile_full"] >= 37
    assert catalog["registered_production_full"] >= 32
    assert catalog["game_usable"] >= 32
