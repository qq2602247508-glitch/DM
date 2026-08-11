from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.tashas_recovery import load_item_production_evidence

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-item-production-consumer-round-X-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XII.json"
CATALOG = ROOT / "reports/tashas-item-spec-catalog-2026-08-11.json"
ROUND_XI_REPORT = ROOT / "reports/tashas-item-production-consumer-round-XI-2026-08-12.json"
ROUND_XII_REPORT = ROOT / "reports/tashas-item-production-consumer-round-XII-2026-08-12.json"


def test_round_X_item_specs_have_real_production_consumer_evidence() -> None:
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
    assert checks["charge_lifecycle_count"] == 2
    assert checks["operation_transaction_count"] == 14
    assert checks["name_branch_count"] == 0
    assert results["content_kind"] == "item"
    assert results["production_runtime_full_ids"] == sorted(report["selected_item_ids"])
    round_xi = json.loads(ROUND_XI_REPORT.read_text(encoding="utf-8"))
    round_xii = json.loads(ROUND_XII_REPORT.read_text(encoding="utf-8"))
    assert load_item_production_evidence(ROOT) >= (
        set(report["selected_item_ids"])
        | set(round_xi["selected_item_ids"])
        | set(round_xii["selected_item_ids"])
    )
    assert catalog["isolated_runtime_validated"] == 37
    assert catalog["registered_production_full"] >= 24
    assert catalog["game_usable"] >= 24
    assert sum(
        bool(item.get("status_layers", {}).get("registered_production_full"))
        for item in catalog["specs"]
    ) >= 24
