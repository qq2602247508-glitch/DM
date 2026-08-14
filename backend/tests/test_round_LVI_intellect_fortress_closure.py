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
SPELL_ID = "tashas-cauldron:spell:b4ea0dc1907dd5ac08666af3"
ARTIFACT = ROOT / "data/content-ir/compiled/production-runtime-results-LVI.json"
REPORT = ROOT / "reports/round-LVI-intellect-fortress-closure-2026-08-14.json"


def _report() -> dict[str, object]:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_round_lvi_selected_artifact_is_source_bound_and_full() -> None:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    row = artifact["evidence_by_id"][SPELL_ID]
    assert artifact["artifact_date"] == "2026-08-14"
    assert artifact["production_runtime_full_ids"] == [SPELL_ID]
    assert row["production_runtime_full"] is True
    assert row["consumer_ids"] == [
        "spell.defense.v1",
        "spell_economy.concentration.v1",
    ]
    assert row["payload_drift"]["rejected"] is True
    assert row["strict_loader_probe"]["rejected"] is True
    assert artifact["checks"]["all_required_checks_passed"] is True


def test_round_lvi_projection_is_set_derived_and_unrelated_ids_unchanged() -> None:
    report = _report()
    authoritative = authoritative_compile_only_ids(ROOT)
    current = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    before = project_compile_only_ids(
        authoritative,
        [
            content_id
            for content_id, row in current.items()
            if row.get("evidence_path") != str(ARTIFACT.relative_to(ROOT))
        ],
    )
    after = project_compile_only_ids(authoritative, current)
    assert before - after == {SPELL_ID}
    assert after - before == set()
    assert (before - {SPELL_ID}) == (after - set())
    assert set(report["projection_sets"]["after_compile_only_ids"]) == after
    migration = build_migration(ROOT)
    assert set(migration["current_project_compile_only_ids"]) == after
    assert report["checks"]["duplicate_invalid_set_idempotent"] is True


def test_round_lvi_selected_artifact_is_not_a_name_branch() -> None:
    report = _report()
    assert report["checks"]["name_branch_free"] is True
    assert report["candidate_comparison"]["ranking_claim"] is False
