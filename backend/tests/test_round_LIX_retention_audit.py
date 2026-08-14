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
SCRIPT = ROOT / "scripts/validate-round-LIX-retention-audit.py"
REPORT = ROOT / "reports/round-LIX-retention-audit-2026-08-14.json"
SELECTED_ID = "xanathars-guide:spell:aadf89719f073bfca1fefb3a"


def _run_validator() -> dict:
    namespace = runpy.run_path(str(SCRIPT))
    assert namespace["main"]() == 0
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_round_lix_retention_is_set_derived_and_no_promotion() -> None:
    report = _run_validator()
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    compile_only = project_compile_only_ids(authoritative_compile_only_ids(ROOT), loaded)
    production = existing_project_production_ids(ROOT)
    migration = build_migration(ROOT)
    assert report["decision"] == "retention_audit_no_promotion"
    assert report["before"] == {
        "production": len(production),
        "compile_only": len(compile_only),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    assert report["after"] == report["before"]
    assert report["count_delta"] == {"production": 0, "compile_only": 0, "unique_compiled": 0}
    assert report["projection_sets"]["promoted_ids"] == []
    assert {row["content_id"] for row in report["candidate_evidence"]} == compile_only
    assert report["checks"]["all_required_checks_passed"] is True
    assert report["candidate_comparison"]["selected_candidate_for_deep_review"] == SELECTED_ID


def test_round_lix_selected_candidate_has_positive_source_and_runtime_blocker() -> None:
    report = _run_validator()
    assert report["candidate_comparison"]["ranking_claim"] is True
    blocker = report["selected_candidate_blocker"]
    assert all(blocker["source_markers"].values())
    assert blocker["runtime_block_types"] == ["concentration"]
    assert blocker["missing_runtime_capabilities"] == {
        "cloud_text_creation": True,
        "cloud_text_persistence": True,
        "wind_early_termination": True,
        "termination": True,
    }
    assert blocker["source_complete"] is False
    row = next(item for item in report["candidate_evidence"] if item["content_id"] == SELECTED_ID)
    assert row["source_semantics"]["missing_source_clause_types"] == []
    assert row["source_semantics"]["missing_source_semantics"] == []
    assert row["consumer_probe"]["resolved_consumer_ids"] == ["spell_economy.concentration.v1"]
    assert row["duplicate_evidence"]["duplicate_authority_conflict"] is False
    assert row["decision"] == "retained_compile_only"


def test_round_lix_historical_and_protected_hashes_are_exact() -> None:
    report = _run_validator()
    assert report["checks"]["accepted_head_is_ancestor"] is True
    assert report["checks"]["historical_xxii_sha_exact"] is True
    assert report["checks"]["historical_xliii_sha_exact"] is True
    assert report["checks"]["protected_ollama_sha_exact"] is True
    assert report["after"]["production"] == len(
        set(report["projection_sets"]["production_after_ids"])
    )
