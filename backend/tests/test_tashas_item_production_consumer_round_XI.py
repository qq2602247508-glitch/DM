from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.tashas_recovery import (
    _explicit_spell_identities,
    load_item_production_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-item-production-consumer-round-XI-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XIII.json"
CATALOG = ROOT / "reports/tashas-item-spec-catalog-2026-08-11.json"


def test_round_XI_corrects_spell_identity_quality_and_adds_item_evidence() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    checks = report["checks"]
    assert report["formal_apply"] is False
    assert report["quality_review"]["false_granted_spell_extraction_corrected"] is True
    assert len(report["selected_item_ids"]) == 8
    assert checks["production_runtime_full_count"] == 8
    assert checks["all_create_preview_confirm_replay"] is True
    assert checks["all_typed_consumers"] is True
    assert checks["all_item_state_persisted"] is True
    assert checks["all_attunement_cas"] is True
    assert checks["charge_lifecycle_count"] == 6
    assert checks["operation_transaction_count"] == 16
    assert checks["name_branch_count"] == 0
    assert results["content_kind"] == "item"
    assert results["production_runtime_full_ids"] == sorted(report["selected_item_ids"])
    assert load_item_production_evidence(ROOT) >= set(report["selected_item_ids"])
    assert catalog["item_spec_total"] == 47
    assert catalog["item_spec_compile_full"] == 37
    assert catalog["registered_production_full"] == 16
    assert catalog["game_usable"] == 16
    assert _explicit_spell_identities("施展*易容术**Disguise Self*法术")[0]["spell_id"] == "disguise-self"
    assert _explicit_spell_identities("作为你施展德鲁伊和游侠法术的法器") == []
    assert _explicit_spell_identities("你可以施展那道法术") == []
