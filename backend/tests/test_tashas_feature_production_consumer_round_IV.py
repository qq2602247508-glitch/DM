"""Regression checks for the Round-IV movement/sight consumer evidence."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.domain.feature_runtime import compile_feature_runtime_registry

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT.parent / "reports/tashas-feature-production-consumer-round-IV-2026-08-12.json"
RESULTS = ROOT.parent / "data/content-ir/compiled/production-runtime-results-VI.json"
FEATURE_ROOT = (
    ROOT.parent / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"
)


def test_round_iv_report_contains_eight_real_typed_consumers() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert report["checks"]["all_preview_confirm_replay"] is True
    assert report["checks"]["all_typed_consumers"] is True
    assert report["checks"]["movement_choice_lifecycle_consumers"] == 8
    assert report["checks"]["formal_database_written"] is False
    assert report["checks"]["formal_registry_written"] is False
    assert len(report["selected_feature_ids"]) == 8
    assert results["production_runtime_full_ids"] == sorted(report["selected_feature_ids"])
    assert all(item["sight_activation"] for item in report["results"])


def test_movement_materializer_preserves_choice_and_explicit_activation() -> None:
    compiler = FeatureCompiler(status_authority="compiler")

    def load(name: str) -> tuple[FeatureSpec, dict[str, object]]:
        path = FEATURE_ROOT / f"{name}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        spec = FeatureSpec.from_dict(
            {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
            path=str(path),
        )
        result = compiler.compile(spec)
        assert result.compile_status == "full"
        return spec, materialize_runtime_definition(spec, result, catalog=compiler.catalog)

    bestial_spec, bestial = load("beast-barbarian-bestial-soul")
    registry = compile_feature_runtime_registry(
        [
            {
                "feature_id": bestial_spec.feature_id,
                "name": bestial_spec.source_name,
                "class_name": bestial_spec.class_name,
                "class_level": bestial_spec.level,
                "kind": "feature",
                "source_record_id": bestial_spec.source_record_id,
                "runtime": {"registry": bestial, "automation_status": "full"},
            }
        ],
        resources={"bestial_soul_mode": {"selected": "climb"}},
        total_level=6,
    )
    assert [item["mode"] for item in registry["combat_start"]["movement_modes"]] == ["climb"]

    genie_spec, genie = load("genie-elemental-gift")
    action = genie["actions"][genie_spec.feature_id]
    assert action["kind"] == "feature_action"
    assert action["action_cost"] == "bonus_action"
    assert action["resource_key"] == "elemental_gift_uses"
    assert action["effects"][0]["kind"] == "activate_movement_mode"
