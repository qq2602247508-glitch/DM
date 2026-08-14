from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_evidence import (
    authoritative_compile_only_ids,
    load_production_runtime_evidence,
    project_compile_only_ids,
)
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import SpellSpec, compile_spell_spec
from dnd_dm_assistant.application.tashas_whole_pack import (
    build_migration,
    existing_project_production_ids,
)

ROOT = Path(__file__).resolve().parents[2]
AUDIT_ID = "core-phb-2024:spell:63fb2360b8c30fb0419d9225"


def _compiled() -> tuple[dict, dict, dict]:
    path = (
        ROOT
        / "data/content-ir/authored/batch-II/core-phb-2024/spells/"
        "core-phb-2024-spell-63fb2360b8c30fb0419d9225.json"
    )
    authored = json.loads(path.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    blocks = ContentIRRuntimeService._runtime_blocks(compiled["runtime_spell_definition"])
    return authored, compiled, blocks


def test_round_lv_source_bound_compile_and_consumer_gap() -> None:
    authored, compiled, blocks = _compiled()
    assert authored["spell_id"] == AUDIT_ID
    assert compiled["compile_status"] == "full"
    assert {clause["type"] for clause in authored["clauses"]} == {
        "target_selection",
        "concentration",
    }
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=blocks,
    )
    assert [item["consumer_id"] for item in consumers] == [
        "spell_economy.concentration.v1"
    ]
    assert "attack" not in blocks
    assert "transfer" not in blocks


def test_round_lv_projection_retains_selected_id_and_unrelated_ids() -> None:
    authoritative = authoritative_compile_only_ids(ROOT)
    artifact_path = "data/content-ir/compiled/production-runtime-results-LV.json"
    loaded_before = {
        content_id: row
        for content_id, row in load_production_runtime_evidence(
            ROOT,
            pack_id=None,
            required_checks=("all_required_checks_passed",),
            require_name_branch_free=True,
        ).items()
        if row["evidence_path"] != artifact_path
    }
    loaded_after = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    before_compile_only = project_compile_only_ids(authoritative, loaded_before)
    after_compile_only = project_compile_only_ids(authoritative, loaded_after)
    report = json.loads(
        (ROOT / "reports/round-LV-retention-audit-2026-08-14.json").read_text(
            encoding="utf-8"
        )
    )
    migration = build_migration(ROOT)
    assert before_compile_only == after_compile_only
    assert before_compile_only == set(report["projection_sets"]["before_compile_only_ids"])
    assert after_compile_only == set(report["projection_sets"]["after_compile_only_ids"])
    assert AUDIT_ID in before_compile_only and AUDIT_ID in after_compile_only
    assert (before_compile_only - {AUDIT_ID}) == (after_compile_only - {AUDIT_ID})
    assert set(migration["current_project_compile_only_ids"]) == after_compile_only
    assert set(loaded_after).issubset(existing_project_production_ids(ROOT))
    assert AUDIT_ID not in existing_project_production_ids(ROOT)
    assert report["projection_sets"]["production_before_ids"] == report[
        "projection_sets"
    ]["production_after_ids"]


def test_round_lv_invalid_duplicate_evidence_cannot_promote() -> None:
    authoritative = authoritative_compile_only_ids(ROOT)
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    baseline = project_compile_only_ids(authoritative, loaded)
    once = project_compile_only_ids(authoritative, [*loaded, AUDIT_ID])
    repeated = project_compile_only_ids(
        authoritative,
        [*loaded, AUDIT_ID, AUDIT_ID, "", "invalid:id", AUDIT_ID],
    )
    invalid_only = project_compile_only_ids(authoritative, [*loaded, "", "invalid:id"])
    artifact = json.loads(
        (
            ROOT / "data/content-ir/compiled/production-runtime-results-LV.json"
        ).read_text(encoding="utf-8")
    )
    assert artifact["production_runtime_full_ids"] == []
    assert artifact["evidence_by_id"][AUDIT_ID]["production_runtime_full"] is False
    assert artifact["gate_facts"]["source_complete_consumer"] is False
    assert artifact["gate_facts"]["promotion_gate_closed"] is False
    assert once == repeated
    assert invalid_only == baseline
    assert AUDIT_ID in baseline and AUDIT_ID not in once
    assert AUDIT_ID not in load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )


def test_round_lv_required_checks_are_positive_and_gate_facts_are_separate() -> None:
    report = json.loads(
        (ROOT / "reports/round-LV-retention-audit-2026-08-14.json").read_text(
            encoding="utf-8"
        )
    )
    required = report["required_check_keys"]
    checks = report["checks"]
    assert report["checks"]["all_required_checks_passed"] is True
    assert all(checks[key] is True for key in required)
    assert "source_complete_consumer" not in checks
    assert "promotion_gate_closed" not in checks
    assert report["gate_facts"]["source_complete_consumer"] is False
    assert report["gate_facts"]["promotion_gate_closed"] is False
