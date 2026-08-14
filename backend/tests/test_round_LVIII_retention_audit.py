from __future__ import annotations

import json
import runpy
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_evidence import (
    authoritative_compile_only_ids,
    load_production_runtime_evidence,
    project_compile_only_ids,
)
from dnd_dm_assistant.application.tashas_whole_pack import (
    build_migration,
    existing_project_production_ids,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/validate-round-LVIII-retention-audit.py"
REPORT = ROOT / "reports/round-LVIII-retention-audit-2026-08-14.json"


def _run_validator() -> dict:
    namespace = runpy.run_path(str(SCRIPT))
    assert namespace["main"]() == 0
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_round_lviii_retention_is_set_derived_and_no_promotion() -> None:
    report = _run_validator()
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    compile_only = project_compile_only_ids(
        authoritative_compile_only_ids(ROOT), loaded
    )
    production = existing_project_production_ids(ROOT)
    migration = build_migration(ROOT)
    assert report["decision"] == "retention_audit_no_promotion"
    assert report["before"] == {
        "production": len(production),
        "compile_only": len(compile_only),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    assert report["after"] == report["before"]
    assert report["count_delta"] == {
        "production": 0,
        "compile_only": 0,
        "unique_compiled": 0,
    }
    assert report["projection_sets"]["promoted_ids"] == []
    assert {
        row["content_id"] for row in report["candidate_evidence"]
    } == compile_only
    assert report["checks"]["all_required_checks_passed"] is True
    assert report["candidate_comparison"]["ranking_claim"] is False
    assert (
        report["candidate_comparison"]["selected_candidate_for_deep_review"]
        == "core-phb-2024:spell:82f220a9e3474d8fe1cafd8b"
    )


def test_round_lviii_sacred_flame_duplicate_and_cover_gap_are_positive_evidence() -> None:
    report = _run_validator()
    row = next(
        item
        for item in report["candidate_evidence"]
        if item["content_id"] == "core-phb-2024:spell:82f220a9e3474d8fe1cafd8b"
    )
    assert row["decision"] == "retained_compile_only"
    assert row["duplicate_evidence"]["duplicate_count"] == 2
    assert row["duplicate_evidence"]["duplicate_authority_conflict"] is True
    assert "saving_throw" in row["duplicate_evidence"]["rows"][1]["typed_clause_types"]
    assert "cover_or_geometry" in row["source_semantics"]["missing_source_semantics"]
    complete_duplicate = max(
        row["duplicate_evidence"]["rows"],
        key=lambda item: item["typed_clause_count"],
    )
    assert complete_duplicate["ignores_cover_required"] is True
    assert complete_duplicate["ignores_cover_runtime_consumed"] is False
    assert report["checks"]["sacred_flame_not_promoted_without_authority_resolution"] is True
    assert report["checks"]["sacred_flame_cover_gap_recorded"] is True


def test_round_lviii_historical_and_protected_hashes_are_exact() -> None:
    report = _run_validator()
    assert report["checks"]["historical_xxii_sha_exact"] is True
    assert report["checks"]["historical_xliii_sha_exact"] is True
    assert report["checks"]["protected_ollama_sha_exact"] is True
    assert report["after"]["production"] == len(
        set(report["projection_sets"]["production_after_ids"])
    )
