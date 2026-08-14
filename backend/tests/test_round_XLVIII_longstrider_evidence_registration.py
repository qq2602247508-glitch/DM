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
SPELL_ID = "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XLVIII.json"
REPORT = ROOT / "reports/round-XLVIII-longstrider-evidence-registration-2026-08-14.json"


def test_round_xlviii_artifact_is_included_by_generic_loader() -> None:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    loaded = load_production_runtime_evidence(ROOT, pack_id=None)
    assert results["production_runtime_full_ids"] == [SPELL_ID]
    assert SPELL_ID in loaded
    assert loaded[SPELL_ID]["evidence_path"] == str(RESULTS.relative_to(ROOT))
    assert existing_project_production_ids(ROOT) >= {SPELL_ID}


def test_round_xlviii_projection_reconciles_naturally() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    migration = build_migration(ROOT)
    assert report["canonical_projection"]["counts"] == {
        "production": 204,
        "compile_only": 34,
        "unique_compiled": 111,
    }
    assert migration["current_project_production_full"] == 204
    assert report["canonical_projection"]["migration_projection_matches_project_union"] is True
    assert report["promotion_decision"] == "promote"


def test_round_xlviii_runtime_receipt_is_complete() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    receipt = report["runtime_receipt"]
    assert receipt["consumer"] == "spell.timed_modifier.v1"
    assert receipt["preview_confirm_replay"] == {
        "preview": True,
        "confirm": True,
        "replay": True,
    }
    assert receipt["persistence"]["receipts_have_source_provenance"] is True
    assert receipt["persistence"]["receipts_have_expiry"] is True
    assert receipt["transaction"]["operation_transaction_present"] is True


def test_compile_only_projection_is_set_based_and_validated(tmp_path: Path) -> None:
    compiled = tmp_path / "data/content-ir/compiled"
    compiled.mkdir(parents=True)
    valid = {
        "round_id": "round-XLVIII",
        "production_runtime_full_ids": [SPELL_ID, "unrelated:id"],
        "compile_only_delta": -99,
        "checks": {"all_required_checks_passed": True},
        "evidence_by_id": {
            SPELL_ID: {"production_runtime_full": True},
            "unrelated:id": {"production_runtime_full": True},
        },
    }
    (compiled / "production-runtime-results-a.json").write_text(
        json.dumps(valid), encoding="utf-8"
    )
    (compiled / "production-runtime-results-b.json").write_text(
        json.dumps(valid), encoding="utf-8"
    )
    (compiled / "production-runtime-results-invalid.json").write_text(
        json.dumps(
            {
                "round_id": "round-XLVIII",
                "production_runtime_full_ids": [SPELL_ID, "invalid:id"],
                "compile_only_delta": -1000,
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
        tmp_path, pack_id=None, round_id="round-XLVIII"
    )
    assert set(loaded) == {SPELL_ID, "unrelated:id"}
    census = authoritative_compile_only_ids(ROOT)
    assert len(census) == 35
    assert len(project_compile_only_ids(census, loaded)) == 34
    assert SPELL_ID not in project_compile_only_ids(census, loaded)
    assert "unrelated:id" not in census
