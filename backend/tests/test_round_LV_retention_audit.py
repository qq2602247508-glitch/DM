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
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    compile_only = project_compile_only_ids(authoritative, loaded)
    migration = build_migration(ROOT)
    assert AUDIT_ID in compile_only
    assert set(migration["current_project_compile_only_ids"]) == compile_only
    assert set(loaded).issubset(existing_project_production_ids(ROOT))
    assert AUDIT_ID not in existing_project_production_ids(ROOT)
    assert set(compile_only) - {AUDIT_ID} == set(compile_only) - {AUDIT_ID}


def test_round_lv_invalid_duplicate_evidence_cannot_promote() -> None:
    artifact = json.loads(
        (
            ROOT / "data/content-ir/compiled/production-runtime-results-LV.json"
        ).read_text(encoding="utf-8")
    )
    assert artifact["production_runtime_full_ids"] == []
    assert artifact["evidence_by_id"][AUDIT_ID]["production_runtime_full"] is False
    assert artifact["checks"]["source_complete_consumer"] is False
    assert AUDIT_ID not in load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
