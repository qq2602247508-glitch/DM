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


def test_round_lx_retention_audit_is_dynamic_and_source_bound() -> None:
    module = runpy.run_path(str(ROOT / "scripts/validate-round-LX-retention-audit.py"))
    report = module["build_report"]()
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
    assert report["all_required_checks_passed"] is True
    assert report["before"] == {
        "production": len(production),
        "compile_only": len(compile_only),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    assert report["after"] == report["before"]
    assert report["count_delta"] == {"production": 0, "compile_only": 0, "unique_compiled": 0}
    assert report["candidate_comparison"]["selected_candidate_for_deep_review"] == (
        "core-phb-2024:spell:9b29fbb72177f058bf1448ef"
    )
    blocker = report["selected_candidate_blocker"]
    assert blocker["source_record_id"] == "9b29fbb72177f058bf1448ef"
    assert blocker["source_complete"] is False
    assert set(blocker["missing_source_semantics"]) == {
        "persistent_area",
        "strong_wind_termination",
        "upcast_radius_scaling",
    }
    assert report["projection_sets"]["promoted_ids"] == []


def test_round_lx_report_artifact_matches_dynamic_output() -> None:
    module = runpy.run_path(str(ROOT / "scripts/validate-round-LX-retention-audit.py"))
    expected = module["build_report"]()
    actual = json.loads(
        (ROOT / "reports/round-LX-retention-audit-2026-08-14.json").read_text(
            encoding="utf-8"
        )
    )
    assert actual == expected
