"""Round XXII receipt and typed teleport contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.api.schemas import ContentIRRuntimeRequest
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XXII-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXIV.json"
FEATURE = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    / "soulknife-psychic-teleportation.json"
)
FEATURE_ID = "content.tashas-cauldron.round2.feature.soulknife-psychic-teleportation"


def _contract() -> tuple[FeatureSpec, dict[str, object]]:
    value = json.loads(FEATURE.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    assert compiled.compile_status == "full"
    return spec, materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)


def test_round_xxii_receipt_is_complete() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert report["all_required_checks_passed"] is True
    assert results["all_required_checks_passed"] is True
    assert report["selected_feature_ids"] == [FEATURE_ID]
    assert results["production_runtime_full_ids"] == [FEATURE_ID]
    assert all(value is True for value in report["checks"].values())
    assert report["formal_registry_written"] is False
    assert report["formal_database_written"] is False
    assert report["name_branch_count"] == 0


def test_psychic_teleport_materializes_typed_action_and_resource() -> None:
    spec, runtime = _contract()
    assert spec.source_completeness == "complete"
    assert spec.manual_decisions["unmodeled_source_terms"] == []
    actions = runtime["actions"]
    action = next(item for item in actions.values() if item["feature_id"] == FEATURE_ID)
    assert action["kind"] == "feature_action"
    assert action["resolution_kind"] == "teleport"
    assert action["action_cost"] == "bonus_action"
    assert action["resource_key"] == "psionic_dice"
    assert action["resource_cost"] == 1
    assert action["effects"] == [
        {
            "kind": "teleport",
            "destination_kind": "visible_unoccupied_space",
            "roll_input": "movement_roll_total",
            "roll_multiplier_ft": 10,
            "roll_source": "psionic_dice",
        }
    ]
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"feature_action": [action]},
    )
    assert [item["consumer_id"] for item in consumers] == ["combat_engine.feature_action.v1"]


def test_content_runtime_request_preserves_typed_teleport_inputs() -> None:
    request = ContentIRRuntimeRequest(
        content_kind="feature",
        runtime_id=FEATURE_ID,
        combat_id="combat",
        actor_combatant_id="actor",
        actor_version=1,
        target_combatant_id="actor",
        target_version=1,
        movement_roll_total=2,
        destination_row=2,
        destination_col=6,
        idempotency_key="round-xxii-request",
    )
    payload = request.model_dump(mode="json")
    assert payload["movement_roll_total"] == 2
    assert payload["destination_row"] == 2
    assert payload["destination_col"] == 6
