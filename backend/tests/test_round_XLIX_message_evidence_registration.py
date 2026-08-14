from __future__ import annotations

import json
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
SPELL_ID = "core-phb-2024:spell:dd9cb25c63b7e13194c7d01c"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XLIX.json"
REPORT = ROOT / "reports/round-XLIX-message-production-2026-08-14.json"


def test_round_xlix_message_is_loaded_by_generic_evidence_loader() -> None:
    artifact = json.loads(RESULTS.read_text(encoding="utf-8"))
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    assert artifact["production_runtime_full_ids"] == [SPELL_ID]
    assert loaded[SPELL_ID]["evidence_path"] == str(RESULTS.relative_to(ROOT))
    assert SPELL_ID in existing_project_production_ids(ROOT)


def test_round_xlix_projection_is_derived_and_reconciled() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    migration = build_migration(ROOT)
    assert report["promotion_decision"] == "promote"
    assert report["canonical_projection"]["counts"] == {
        "production": 205,
        "compile_only": 33,
        "unique_compiled": 111,
    }
    assert migration["current_project_production_full"] == 205
    assert report["canonical_projection"]["migration_projection_matches_project_union"]


def test_round_xlix_duplicate_invalid_evidence_cannot_change_projection(tmp_path: Path) -> None:
    compiled = tmp_path / "data/content-ir/compiled"
    compiled.mkdir(parents=True)
    valid = {
        "round_id": "round-XLIX",
        "production_runtime_full_ids": [SPELL_ID, SPELL_ID, "unrelated:id"],
        "checks": {"all_required_checks_passed": True, "name_branch_count": 0},
        "evidence_by_id": {
            SPELL_ID: {"production_runtime_full": True},
            "unrelated:id": {"production_runtime_full": True},
        },
    }
    (compiled / "production-runtime-results-a.json").write_text(
        json.dumps(valid), encoding="utf-8"
    )
    (compiled / "production-runtime-results-invalid.json").write_text(
        json.dumps(
            {
                "round_id": "round-XLIX",
                "production_runtime_full_ids": [SPELL_ID, "invalid:id"],
                "checks": {"all_required_checks_passed": False},
                "evidence_by_id": {
                    SPELL_ID: {"production_runtime_full": True},
                    "invalid:id": {"production_runtime_full": True},
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = load_production_runtime_evidence(
        tmp_path,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
        round_id="round-XLIX",
    )
    census = authoritative_compile_only_ids(ROOT)
    assert set(loaded) == {SPELL_ID, "unrelated:id"}
    assert SPELL_ID not in project_compile_only_ids(census, loaded)
    assert "invalid:id" not in project_compile_only_ids(census, loaded)
