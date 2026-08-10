from __future__ import annotations

from dnd_dm_assistant.application.feature_capability_unlocks import plan_capability_unlocks
from dnd_dm_assistant.application.feature_clause_corpus import compile_clause_corpus


def _partial_row(**overrides: object) -> dict[str, object]:
    return {
        "scope": "subclass",
        "class_name": "测试职业",
        "subclass_name": "测试子职",
        "level": 3,
        "feature_name": "测试特性",
        "source_record_id": "source:test",
        "source_parse": "description_located",
        "source_description": "第一段规则。\n\n- 第二段规则。",
        "runtime_status": "partial",
        "detected_blocks": ["save_dc"],
        **overrides,
    }


def test_clause_corpus_retains_source_without_inferring_executable_contract() -> None:
    report = compile_clause_corpus([_partial_row()])

    assert report["feature_count"] == 1
    assert report["clause_count"] == 2
    assert report["source_complete_feature_count"] == 1
    assert report["reviewed_clause_count"] == 2
    assert report["typed_clause_count"] == 2
    assert report["manual_boundary_clause_count"] == 2
    assert {item["clause_status"] for item in report["clauses"]} == {"manual_boundary"}
    assert {item["effect_operator"] for item in report["clauses"]} == {None}
    assert report["clauses"][0]["analysis_anchors"] == ["save_dc"]
    assert report["clauses"][0]["review_status"] == "reviewed_typed"
    assert report["clauses"][0]["missing_fields"]
    assert report["clauses"][0]["source_fingerprint"]


def test_unlock_planner_never_converts_untyped_source_frequency_into_unlocks() -> None:
    corpus = compile_clause_corpus(
        [
            _partial_row(feature_name=f"特性{index}", source_record_id=f"source:{index}")
            for index in range(8)
        ]
    )

    report = plan_capability_unlocks(corpus)

    assert report["typed_missing_contract_count"] == 0
    assert report["qualified_cluster_found"] is False
    assert report["reviewed_clause_count"] == 16
    assert report["manual_boundary_clause_count"] == 16
    review = next(
        item
        for item in report["ranking"]
        if item["capability_id"] == "review:manual_boundary"
    )
    assert review["occurrence_count"] == 16
    assert review["completion_unlock_count"] == 0
