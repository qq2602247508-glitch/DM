from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_evidence import (
    load_production_runtime_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "round_liv_validator",
    ROOT / "scripts/validate-round-LIV-summon-census-closure.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_round_liv_census_has_30_remaining_ids_and_summon_cluster() -> None:
    report = json.loads(
        (
            ROOT
            / "reports/round-LIV-summon-census-closure-2026-08-14.json"
        ).read_text(encoding="utf-8")
    )
    census = report["census"]
    assert census["authoritative_census_size"] == 35
    assert len(report["projection_sets"]["before_compile_only_ids"]) == 30
    assert set(MODULE.SUMMON_IDS).issubset(
        report["projection_sets"]["before_compile_only_ids"]
    )
    summon_group = next(
        item
        for item in census["groups"]
        if item["semantic_group"] == "summon.stat_block.lifecycle"
    )
    assert summon_group["member_count"] == 2
    assert summon_group["shared_consumer"] == "spell.summon.v1"


def test_round_liv_summon_source_is_complete_and_compiles_full() -> None:
    census = json.loads(
        (
            ROOT
            / "reports/round-LIV-summon-census-closure-2026-08-14.json"
        ).read_text(encoding="utf-8")
    )["census"]
    rows = {row["content_id"]: row for row in census["rows"]}
    for content_id in MODULE.SUMMON_IDS:
        assert rows[content_id]["source_complete"] is True
        assert rows[content_id]["compile_status"] == "full"
        assert rows[content_id]["source_bound_blockers"] == []


def test_round_liv_projection_and_transaction_evidence_are_set_derived() -> None:
    report = json.loads(
        (
            ROOT
            / "reports/round-LIV-summon-census-closure-2026-08-14.json"
        ).read_text(encoding="utf-8")
    )
    before_ids = set(report["projection_sets"]["before_compile_only_ids"])
    after_ids = set(report["projection_sets"]["after_compile_only_ids"])
    assert report["before"]["compile_only"] == len(before_ids)
    assert report["after"]["compile_only"] == len(after_ids)
    assert before_ids - after_ids == set(MODULE.SUMMON_IDS)
    assert after_ids - before_ids == set()
    assert report["projection_sets"]["production_before_ids"] == report[
        "projection_sets"
    ]["production_after_ids"]
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    assert set(MODULE.SUMMON_IDS).issubset(loaded)
    for content_id in MODULE.SUMMON_IDS:
        assert content_id in report["chosen_content_ids"]
        assert report["checks"][f"{content_id}:operation_transaction_binding"] is True
