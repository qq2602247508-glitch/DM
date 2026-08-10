"""Regression tests for the real-corpus Feature IR batch compiler."""

from __future__ import annotations

from dnd_dm_assistant.application.feature_ir_batch_compiler import (
    compile_audit_batch,
    normalize_audit_row,
    stable_feature_id,
)
from dnd_dm_assistant.application.formal_feature_specs import formal_feature_specs


def test_real_audit_row_normalization_has_stable_identity_and_fingerprint() -> None:
    row = {
        "scope": "subclass",
        "class_name": "游侠",
        "subclass_name": "猎人",
        "level": 3,
        "feature_name": "猎人学识 Hunter's Lore",
        "source_record_id": "verified:hunters-lore",
        "runtime_status": "partial",
    }
    first = normalize_audit_row(row)
    second = normalize_audit_row(dict(reversed(row.items())))
    assert stable_feature_id(row) == first["feature_id"]
    assert first["source_fingerprint"] == second["source_fingerprint"]
    changed_status = normalize_audit_row({**row, "runtime_status": "full"})
    assert first["source_fingerprint"] == changed_status["source_fingerprint"]


def test_real_rows_without_explicit_typed_spec_are_partial() -> None:
    rows = [
        {
            "feature_id": "class-feature:one",
            "feature_name": "候选一",
            "runtime_status": "partial",
        },
        {
            "feature_id": "class-feature:two",
            "feature_name": "候选二",
            "runtime_status": "partial",
        },
    ]
    result = compile_audit_batch(rows, mode="preview")
    assert result["audit_total"] == 2
    assert result["compiler_status_counts"]["partial"] == 2
    assert result["direct_ir_authority_count"] == 0
    assert all("missing_typed_spec" in item["blockers"] for item in result["features"])


def test_explicit_untrusted_spec_cannot_be_promoted() -> None:
    spec = next(
        item
        for item in formal_feature_specs()
        if item.feature_id == "dnd2024.core.druid.druidic"
    )
    row = {
        "feature_id": spec.feature_id,
        "feature_name": spec.source_name,
        "runtime_status": "partial",
    }
    draft = spec.__class__.from_dict(
        {**spec.to_dict(), "source_trust": "generated_draft"},
        "test.generated_draft",
    )
    result = compile_audit_batch([row], specs=[draft], mode="dry-run")
    assert result["compiler_status_counts"]["partial"] == 1
    assert result["direct_ir_authority_count"] == 0
    assert result["features"][0]["blockers"] == ["untrusted_source"]


def test_batch_fingerprints_are_order_independent_and_conflicts_fail_closed() -> None:
    rows = [
        {"feature_id": "class-feature:a", "feature_name": "A", "runtime_status": "partial"},
        {"feature_id": "class-feature:b", "feature_name": "B", "runtime_status": "partial"},
    ]
    first = compile_audit_batch(rows, mode="preview")
    second = compile_audit_batch(list(reversed(rows)), mode="replay", existing=first)
    assert [item["feature_id"] for item in first["features"]] == [
        "class-feature:a",
        "class-feature:b",
    ]
    assert second["conflicts"] == []
    changed = compile_audit_batch(
        [
            {
                "feature_id": "class-feature:a",
                "feature_name": "changed",
                "runtime_status": "partial",
            }
        ],
        mode="replay",
        existing=first,
    )
    assert changed["conflicts"] == ["class-feature:a: source fingerprint conflict"]
