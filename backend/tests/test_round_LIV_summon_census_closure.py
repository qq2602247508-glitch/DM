from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "round_liv_validator",
    ROOT / "scripts/validate-round-LIV-summon-census-closure.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_round_liv_census_has_30_remaining_ids_and_summon_cluster() -> None:
    census = MODULE._census()
    assert census["authoritative_census_size"] == 30
    assert set(MODULE.SUMMON_IDS).issubset(census["remaining_compile_only_ids"])
    summon_group = next(
        item
        for item in census["groups"]
        if item["semantic_group"] == "summon.stat_block.lifecycle"
    )
    assert summon_group["member_count"] == 2
    assert summon_group["shared_consumer"] == "spell.summon.v1"


def test_round_liv_summon_source_is_complete_and_compiles_full() -> None:
    census = MODULE._census()
    rows = {row["content_id"]: row for row in census["rows"]}
    for content_id in MODULE.SUMMON_IDS:
        assert rows[content_id]["source_complete"] is True
        assert rows[content_id]["compile_status"] == "full"
        assert rows[content_id]["source_bound_blockers"] == []
