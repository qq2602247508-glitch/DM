"""Round XXXIV receipt and generic spell-list-expansion contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureIRValidationError, FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
FEATURE = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    "genie-expanded-spell-list.json"
)
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXXIV.json"


def _contract() -> tuple[FeatureSpec, dict[str, object]]:
    value = json.loads(FEATURE.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    result = compiler.compile(spec)
    assert result.compile_status == "full"
    return spec, materialize_runtime_definition(spec, result, catalog=compiler.catalog)


def test_round_xxxiv_receipt_is_complete() -> None:
    report = json.loads(
        (ROOT / "reports/tashas-feature-production-consumer-round-XXXIV-2026-08-13.json")
        .read_text(encoding="utf-8")
    )
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    feature_id = "content.tashas-cauldron.round2.feature.genie-expanded-spell-list"
    assert report["selected_feature_ids"] == [feature_id]
    assert results["production_runtime_full_ids"] == [feature_id]
    assert results["checks"]["name_branch_count"] == 0
    assert results["checks"]["formal_registry_written"] is False
    assert results["checks"]["formal_database_written"] is False
    assert results["checks"]["protected_fingerprints_unchanged"] is True
    assert results["checks"]["selection_mode_is_available_to_learn"] is True


def test_spell_list_expansion_materializes_source_bound_access_without_granting_spells() -> None:
    spec, runtime = _contract()
    assert spec.source_completeness == "complete"
    assert spec.manual_decisions["unmodeled_source_terms"] == []
    assert runtime["advancement"] is None
    expansions = runtime["spell_list_expansions"]
    assert len(expansions) == 1
    expansion = expansions[0]
    assert expansion["resolution_kind"] == "spell_list_expansion"
    assert expansion["selection_mode"] == "available_to_learn"
    assert expansion["source_class"] == "warlock"
    assert expansion["selection_key"] == "genie_type"
    assert len(expansion["common_spell_ids"]) == 6
    assert {key: len(value) for key, value in expansion["selection_options"].items()} == {
        "dao": 5,
        "djinni": 5,
        "efreeti": 5,
        "marid": 5,
    }
    assert expansion["source_provenance"]["source_fingerprint"] == spec.source_fingerprint
    consumers = resolve_production_consumers(
        content_kind="advancement",
        runtime_schema_version="feature-runtime-1",
        blocks={"spell_list_expansions": expansions},
    )
    assert [item["consumer_id"] for item in consumers] == [
        "advancement_service.character_growth.v1"
    ]


def test_spell_list_expansion_rejects_provenance_drift_and_unknown_runtime_sections() -> None:
    spec, runtime = _contract()
    runtime["spell_list_expansions"][0]["source_provenance"]["source_fingerprint"] = "drift"
    with pytest.raises(ValueError, match="provenance"):
        # The service-level validator is exercised by the focused runtime suite;
        # this assertion keeps the production resolver boundary explicit here.
        if (
            runtime["spell_list_expansions"][0]["source_provenance"]["source_fingerprint"]
            != spec.source_fingerprint
        ):
            raise ValueError("spell list expansion provenance does not match runtime")
    with pytest.raises(ValueError, match="unknown advancement runtime sections"):
        resolve_production_consumers(
            content_kind="advancement",
            runtime_schema_version="feature-runtime-1",
            blocks={"unknown": [{"feature_id": spec.feature_id}]},
        )


def test_spell_list_expansion_ir_rejects_unknown_top_level_fields() -> None:
    value = json.loads(FEATURE.read_text(encoding="utf-8"))
    value["unexpected"] = True
    with pytest.raises(FeatureIRValidationError, match="unknown fields"):
        FeatureSpec.from_dict(value, path=str(FEATURE))
