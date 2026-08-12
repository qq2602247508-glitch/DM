"""Round XXVII receipt and typed communication contract tests."""

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
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XXVII-2026-08-13.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXVIII.json"
FEATURE = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    / "fathomless-oceanic-soul.json"
)
FEATURE_ID = "content.tashas-cauldron.round2.feature.fathomless-oceanic-soul"


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


def test_round_xxvii_receipt_is_complete() -> None:
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


def test_fathomless_oceanic_soul_materializes_communication_action() -> None:
    spec, runtime = _contract()
    assert spec.source_completeness == "complete"
    assert spec.manual_decisions["unmodeled_source_terms"] == []
    actions = runtime["actions"]
    action = next(item for item in actions.values() if item["feature_id"] == FEATURE_ID)
    assert action["kind"] == "communication"
    assert action["resolution_kind"] == "communication"
    assert action["channel"] == "speech"
    assert action["direction"] == "mutual"
    assert action["required_condition"] == "submerged"
    assert action["action_cost"] == "none"
    assert action["effects"] == [
        {
            "kind": "mutual_comprehension",
            "channel": "speech",
            "direction": "mutual",
            "required_condition": "submerged",
        }
    ]
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"communication": [action]},
    )
    assert [item["consumer_id"] for item in consumers] == [
        "communication.mutual_comprehension.v1"
    ]


def test_content_runtime_request_preserves_typed_communication_inputs() -> None:
    request = ContentIRRuntimeRequest(
        content_kind="feature",
        runtime_id=FEATURE_ID,
        combat_id="combat",
        actor_combatant_id="actor",
        actor_version=1,
        target_combatant_id="target",
        target_version=1,
        idempotency_key="round-xxvii-request",
    )
    payload = request.model_dump(mode="json")
    assert payload["content_kind"] == "feature"
    assert payload["runtime_id"] == FEATURE_ID
    assert payload["actor_combatant_id"] == "actor"
    assert payload["target_combatant_id"] == "target"
