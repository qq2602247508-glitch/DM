"""Round XXI receipt tests for typed Psionic Sorcery spell context."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_registry import resolve_production_consumers

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XXI-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXIII.json"
FEATURE_ID = "content.tashas-cauldron.round2.feature.aberrant-mind-psionic-sorcery"


def test_round_xxi_psionic_sorcery_receipt_is_complete() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["all_required_checks_passed"] is True
    assert report["selected_feature_ids"] == [FEATURE_ID]
    assert report["after"]["selected_production_runtime_full"] == 1
    assert all(value is True for value in report["checks"].values())
    assert report["formal_registry_written"] is False
    assert report["formal_database_written"] is False
    assert report["name_branch_count"] == 0


def test_round_xxi_result_records_slot_replacement_and_context_consumption() -> None:
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert result["all_required_checks_passed"] is True
    assert result["production_runtime_full_ids"] == [FEATURE_ID]
    evidence = result["evidence_by_id"][FEATURE_ID]
    assert evidence["feature_consumer_ids"] == ["spell.context.v1"]
    assert evidence["typed_clause_ids"] == ["component-override", "payment-override"]
    payment = evidence["payment_evidence"]
    assert payment["components_ignored"] is True
    assert payment["payment_resource_key"] == "sorcery_points"
    assert payment["slot_before"] == payment["slot_after"] == 2
    assert payment["sorcery_points_after"] == 2
    assert payment["replay_already_applied"] is True
    assert evidence["rollback_evidence"] is True


def test_round_xxi_feature_context_consumer_is_name_agnostic() -> None:
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={
            "spell_context": [
                {
                    "operator": "override_spell_components",
                    "applies_when": "psionic_spell",
                    "component": "verbal_somatic_material_without_cost",
                    "operation": "ignore",
                },
                {
                    "operator": "override_spell_payment",
                    "applies_when": "psionic_spell",
                    "payment_kind": "spell_slot",
                    "operation": "replace_with_sorcery_points",
                    "resource_key": "sorcery_points",
                },
            ]
        },
    )
    assert [item["consumer_id"] for item in consumers] == ["spell.context.v1"]
