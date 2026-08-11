from __future__ import annotations

import copy
import json
from pathlib import Path

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
FEATURE_PATH = (
    ROOT
    / (
        "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
        "ranger-tireless.json"
    )
)


def _spec_value() -> dict[str, object]:
    value = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    return {key: item for key, item in value.items() if key in FeatureSpec._FIELDS}


def test_round_XVII_tireless_materializes_typed_rest_condition_effect() -> None:
    spec = FeatureSpec.from_dict(_spec_value(), path=str(FEATURE_PATH))
    compiler = FeatureCompiler(status_authority="compiler")
    result = compiler.compile(spec)

    assert result.compile_status == "full", result.blockers
    runtime = materialize_runtime_definition(spec, result, catalog=compiler.catalog)
    effect = runtime["triggers"][0]
    assert effect["kind"] == "rest_condition_effect"
    assert effect["trigger"] == "short_rest_completed"
    assert effect["rest"] == "short_rest"
    assert effect["condition"] == "exhaustion"
    assert effect["effect_kind"] == "reduce_condition_level"
    assert effect["amount"] == 1
    assert effect["runtime_execution"]["status"] == "ready"


def test_round_XVII_rest_condition_consumer_is_fail_closed_for_other_conditions() -> None:
    value = copy.deepcopy(_spec_value())
    clauses = value["clauses"]
    assert isinstance(clauses, list)
    effect_clause = clauses[0]
    assert isinstance(effect_clause, dict)
    effects = effect_clause["effects"]
    assert isinstance(effects, list)
    effect = effects[0]
    assert isinstance(effect, dict)
    parameters = effect["parameters"]
    assert isinstance(parameters, dict)
    parameters["condition"] = "poisoned"

    spec = FeatureSpec.from_dict(value, path=str(FEATURE_PATH))
    result = FeatureCompiler(status_authority="compiler").compile(spec)

    assert result.compile_status == "partial"
    assert "rest remove_condition only supports exhaustion" in result.clause_results[0].blockers
