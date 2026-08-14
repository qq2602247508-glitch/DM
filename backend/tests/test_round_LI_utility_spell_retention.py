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
CANDIDATE_IDS = (
    "core-phb-2024:spell:83b7d94b77f332dd71310bbe",
    "core-phb-2024:spell:b9db026fa1853bca5b6f1c13",
)
DISGUISE_SELF_ID = CANDIDATE_IDS[0]


def _compiled(content_id: str) -> tuple[dict, dict]:
    record_id = content_id.rsplit(":", 1)[1]
    path = ROOT / (
        "data/content-ir/authored/batch-II/core-phb-2024/spells/"
        f"core-phb-2024-spell-{record_id}.json"
    )
    authored = json.loads(path.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    return authored, compiled


def test_round_li_candidates_compile_from_source_bound_ir() -> None:
    for content_id in CANDIDATE_IDS:
        authored, compiled = _compiled(content_id)
        assert authored["spell_id"] == content_id
        assert compiled["compile_status"] == "full"
        assert compiled["runtime_spell_definition"]["source"]["source_record_id"] == authored[
            "source_record_id"
        ]


def test_round_li_generic_registry_resolves_current_generic_consumers() -> None:
    for content_id in CANDIDATE_IDS:
        _authored, compiled = _compiled(content_id)
        blocks = ContentIRRuntimeService._runtime_blocks(
            compiled["runtime_spell_definition"]
        )
        if content_id == DISGUISE_SELF_ID:
            consumers = resolve_production_consumers(
                content_kind="spell",
                runtime_schema_version="spell-runtime-1",
                blocks=blocks,
            )
            assert [item["consumer_id"] for item in consumers] == [
                "spell.illusion.lifecycle.v1"
            ]
            continue
        consumers = resolve_production_consumers(
            content_kind="spell",
            runtime_schema_version="spell-runtime-1",
            blocks=blocks,
        )
        assert [item["consumer_id"] for item in consumers] == [
            "spell.object_effect.lifecycle.v1"
        ]


def test_round_li_projection_retains_both_candidates() -> None:
    migration = build_migration(ROOT)
    loaded = existing_project_production_ids(ROOT)
    validated = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    compile_only = project_compile_only_ids(authoritative_compile_only_ids(ROOT), validated)
    assert loaded == existing_project_production_ids(ROOT)
    assert compile_only == project_compile_only_ids(
        authoritative_compile_only_ids(ROOT), validated
    )
    assert int(migration["current_project_production_full"]) == len(loaded)
    assert int(migration["current_project_compile_only"]) == len(compile_only)
    assert int(migration["current_project_compiled_unique"]) > len(compile_only)
    assert DISGUISE_SELF_ID in validated
    assert CANDIDATE_IDS[1] in validated
