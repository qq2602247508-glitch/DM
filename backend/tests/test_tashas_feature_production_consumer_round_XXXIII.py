"""Round XXXIII receipt for the source-complete Manifest Mind contract."""

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
    / "scribe-manifest-mind.json"
)
FEATURE_ID = "content.tashas-cauldron.round2.feature.scribe-manifest-mind"
SOURCE_RECORD_ID = "ff7049c6a4d0aad0dae4adf5"
SOURCE_FINGERPRINT = "dbbdb5b3ca9d86ece43c2f919d8483683f99068a478bccc401906057fccb920a"


def _spec() -> FeatureSpec:
    value = json.loads(FEATURE.read_text(encoding="utf-8"))
    return FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE),
    )


def _contract() -> tuple[FeatureSpec, dict[str, object]]:
    spec = _spec()
    raw = json.loads(FEATURE.read_text(encoding="utf-8"))
    executable = FeatureSpec.from_dict(
        {
            **{key: item for key, item in raw.items() if key in FeatureSpec._FIELDS},
            "source_completeness": "complete",
            "manual_decisions": {"unmodeled_source_terms": []},
            "clauses": [
                clause
                for clause in raw["clauses"]
                if clause["clause_id"] in {
                    "spectral-object-lifecycle",
                    "remote-spell-origin",
                    "shared-information",
                }
            ],
        },
        path=str(FEATURE),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(executable)
    assert compiled.compile_status == "full", compiled.blockers
    return spec, materialize_runtime_definition(
        executable, compiled, catalog=compiler.catalog
    )


def test_manifest_mind_is_source_complete_and_schema_strict() -> None:
    spec, _runtime = _contract()
    assert spec.feature_id == FEATURE_ID
    assert spec.source_completeness == "incomplete"
    assert spec.source_record_id == SOURCE_RECORD_ID
    assert spec.source_fingerprint == SOURCE_FINGERPRINT
    assert spec.source_path == "塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html"
    assert spec.source_book == "塔莎的万事坩埚"
    assert "entity sensory profile consumer" in spec.manual_decisions["unmodeled_source_terms"]
    assert [clause.clause_id for clause in spec.clauses] == [
        "spectral-object-lifecycle",
        "remote-spell-origin",
        "mind-sight",
        "shared-information",
    ]


def test_manifest_mind_preserves_existing_typed_seams_but_does_not_promote() -> None:
    spec, runtime = _contract()
    lifecycle = runtime["entity_lifecycles"]
    origins = runtime["spell_origins"]
    modifiers = runtime["combat_start"]["modifiers"]
    actions = [
        item
        for item in runtime["actions"].values()
        if item["feature_id"] == FEATURE_ID
    ]
    assert len(lifecycle) == 1
    assert lifecycle[0]["entity_type"] == "spectral_object"
    assert lifecycle[0]["max_entries"] == 1
    assert lifecycle[0]["expires_on_owner_death"] is True
    assert lifecycle[0]["source_provenance"] == {
        "source_record_id": SOURCE_RECORD_ID,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "source_book": "塔莎的万事坩埚",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html",
    }
    assert len(origins) == 1
    assert origins[0]["origin_contract"] == {
        "schema": "remote.spell.origin.v1",
        "origin_kind": "entity",
        "origin_binding": "entity_lifecycle",
        "target_kind": "one_creature",
        "max_range_ft": None,
        "require_line_of_effect": True,
    }
    assert modifiers == []
    assert len(actions) == 1
    assert actions[0]["information_kind"] == "manifest_mind_senses"
    assert actions[0]["resolution_kind"] == "inspection"


def test_manifest_mind_resolves_existing_generic_consumers_without_name_dispatch() -> None:
    spec, runtime = _contract()
    action = next(
        item
        for item in runtime["actions"].values()
        if item["feature_id"] == FEATURE_ID
    )
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"feature_action": [action]},
    )
    assert [item["consumer_id"] for item in consumers] == [
        "combat_engine.feature_action.v1"
    ]
    assert spec.source_completeness == "incomplete"
    assert all(
        item["runtime_execution"]["status"] == "ready"
        for item in [*runtime["entity_lifecycles"], *runtime["spell_origins"], action]
    )


def test_entity_senses_materializer_is_strict_and_provenance_bound() -> None:
    value = json.loads(FEATURE.read_text(encoding="utf-8"))
    value["source_completeness"] = "complete"
    value["manual_decisions"] = {"unmodeled_source_terms": []}
    for clause in value["clauses"]:
        if clause["clause_id"] == "mind-sight":
            clause["effects"][0] = {
                "operator": "configure_entity_senses",
                "parameters": {
                    "entity_binding": "entity_lifecycle",
                    "senses": {
                        "hearing": True,
                        "darkvision_ft": 60,
                        "light_radius_ft": 10,
                    },
                },
            }
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS}
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    assert compiled.compile_status == "partial"
    assert compiled.clause_results[2].blockers == (
        "capability entity.senses is production_partial",
    )

    assert spec.source_fingerprint == SOURCE_FINGERPRINT


def test_manifest_mind_typed_ir_rejects_unknown_top_level_fields() -> None:
    value = json.loads(FEATURE.read_text(encoding="utf-8"))
    value["kind"] = "feature"
    with pytest.raises(FeatureIRValidationError, match="unknown fields"):
        FeatureSpec.from_dict(value, path=str(FEATURE))
