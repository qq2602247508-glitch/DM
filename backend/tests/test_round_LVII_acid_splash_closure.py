from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_evidence import (
    authoritative_compile_only_ids,
    load_production_runtime_evidence,
    project_compile_only_ids,
)
from dnd_dm_assistant.application.tashas_whole_pack import build_migration

ROOT = Path(__file__).resolve().parents[2]
SPELL_ID = "core-phb-2024:spell:d84dec64befac8db7294e0f1"
ARTIFACT = ROOT / "data/content-ir/compiled/production-runtime-results-LVII.json"
REPORT = ROOT / "reports/round-LVII-acid-splash-closure-2026-08-14.json"


def _artifact() -> dict[str, object]:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _report() -> dict[str, object]:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_round_lvii_artifact_captures_generic_runtime_evidence() -> None:
    artifact = _artifact()
    report = _report()
    row = artifact["evidence_by_id"][SPELL_ID]
    assert artifact["artifact_date"] == "2026-08-14"
    assert artifact["bootstrap_phase"] is False
    assert artifact["production_runtime_full_ids"] == [SPELL_ID]
    assert report["production_runtime_full_ids"] == [SPELL_ID]
    assert row["production_runtime_full"] is True
    assert row["consumer_ids"] == [
        "combat_engine.area_damage.v1",
        "combat_engine.damage_heal.v1",
        "spell.cantrip_scaling.v1",
    ]
    assert row["production"]["operation_transactions"]
    assert row["production"]["operation_transactions"][0]["status"] == "applied"
    assert row["payload_drift"]["rejected"] is True
    assert row["strict_loader_probe"]["rejected"] is True
    assert artifact["checks"]["all_required_checks_passed"] is True
    assert artifact["checks"] == report["checks"]
    assert artifact["required_check_keys"] == report["required_check_keys"]
    assert all(artifact["checks"][key] is True for key in artifact["required_check_keys"])


def test_round_lvii_projection_is_set_derived_and_unrelated_ids_unchanged() -> None:
    report = _report()
    authoritative = authoritative_compile_only_ids(ROOT)
    current = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    artifact_path = str(ARTIFACT.relative_to(ROOT))
    prior = {
        content_id: row
        for content_id, row in current.items()
        if row.get("evidence_path") != artifact_path
    }
    before = project_compile_only_ids(authoritative, prior)
    after = project_compile_only_ids(authoritative, current)
    assert before - after == {SPELL_ID}
    assert after - before == set()
    assert (before - {SPELL_ID}) == (after - set())
    assert set(report["projection_sets"]["after_compile_only_ids"]) == after
    migration = build_migration(ROOT)
    assert set(migration["current_project_compile_only_ids"]) == after
    assert report["checks"]["duplicate_invalid_set_idempotent"] is True
    assert report["checks"]["production_union_semantics_proven"] is True


def test_round_lvii_selected_artifact_is_source_bound_and_name_branch_free() -> None:
    artifact = _artifact()
    report = _report()
    source = report["source"]
    row = artifact["evidence_by_id"][SPELL_ID]
    assert source["compile_status"] == "full"
    assert source["source_record_id"] == row["source_record_id"]
    assert source["source_fingerprint"] == row["source_fingerprint"]
    assert report["candidate_comparison"]["ranking_claim"] is False
    assert report["checks"]["name_branch_free"] is True
