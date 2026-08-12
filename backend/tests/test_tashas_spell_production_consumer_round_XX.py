"""Round XX receipt tests for Sword Burst's generic spell runtime consumer."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_registry import resolve_production_consumers

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-spell-production-consumer-round-XX-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXII.json"


def _report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_round_xx_sword_burst_receipt_is_complete() -> None:
    report = _report()
    assert report["all_required_checks_passed"] is True
    assert report["selected_content_ids"] == [
        "tashas-cauldron:spell:eec6bd94eb83a351fb987de2"
    ]
    assert report["production_runtime_full_ids"] == report["selected_content_ids"]
    assert report["name_branch_count"] == 0
    assert report["formal_database_written"] is False
    assert report["formal_registry_written"] is False
    assert all(value is True for value in report["checks"].values())


def test_round_xx_result_records_real_runtime_evidence() -> None:
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert result["all_required_checks_passed"] is True
    assert result["production_runtime_full_ids"] == [
        "tashas-cauldron:spell:eec6bd94eb83a351fb987de2"
    ]
    evidence = result["evidence_by_id"][result["production_runtime_full_ids"][0]]
    assert evidence["runtime_schema_version"] == "spell-runtime-1"
    assert evidence["production"]["consumer_ids"] == [
        "combat_engine.area_damage.v1",
        "combat_engine.damage_heal.v1",
        "spell.cantrip_scaling.v1",
    ]
    assert evidence["production"]["replay_already_applied"] is True
    assert evidence["production"]["stale_target_cas_status"] == 409
    assert evidence["scaling_previews"][-1]["resolved_amounts"] == [16]


def test_round_xx_generic_registry_resolves_area_save_damage_and_scaling() -> None:
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks={
            "target_selection": [{"kind": "area", "shape": "sphere", "size_ft": 5}],
            "area": [{"type": "area", "shape": "sphere", "size_ft": 5}],
            "saving_throw": [{"type": "saving_throw", "save_ability": "dexterity"}],
            "effects": [
                {"type": "damage", "expression": "2d6", "damage_type": "force"}
            ],
            "upcast": [
                {
                    "type": "upcast",
                    "progression": [{"character_level": 5, "expression": "2d6"}],
                }
            ],
        },
    )
    assert [item["consumer_id"] for item in consumers] == [
        "combat_engine.area_damage.v1",
        "combat_engine.damage_heal.v1",
        "spell.cantrip_scaling.v1",
    ]
