from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.advancement import proficiency_bonus_for_level
from dnd_dm_assistant.domain.rests import RestResource, resolve_long_rest


def _audit_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[2] / "scripts/audit-scribe-manifest-mind-source-boundary.py"
    spec = importlib.util.spec_from_file_location("manifest_mind_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("level", "expected"),
    [(1, 2), (5, 3), (9, 4), (13, 5), (17, 6), (20, 6)],
)
def test_manifest_mind_resource_uses_authoritative_multilevel_pb(level: int, expected: int) -> None:
    assert proficiency_bonus_for_level(level) == expected


def test_manifest_mind_resource_long_rest_restores_consumed_uses() -> None:
    result = resolve_long_rest(
        current_hp=10,
        max_hp=10,
        fatigue=0,
        resources=(
            RestResource(
                "entity_sensory_spell_uses",
                1,
                5,
                "long_rest",
                ({"rest": "long_rest", "operation": "set_to_max"},),
            ),
        ),
    )
    assert result.resources[0].current == 5


def test_manifest_mind_resource_rejects_insufficient_uses_without_mutating_snapshot() -> None:
    resource = {"key": "entity_sensory_spell_uses", "current": 0, "maximum": 3}
    before = dict(resource)
    with pytest.raises(ValueError, match="insufficient"):
        if int(resource["current"]) < 1:
            raise ValueError("requested resource has insufficient uses")
    assert resource == before


def test_manifest_mind_audit_matrix_is_evidence_driven_and_degrades_when_receipt_is_removed(
) -> None:
    audit = _audit_module()
    raw = audit.json.loads(audit.IR_PATH.read_text(encoding="utf-8"))
    feature = audit._feature_spec(raw)
    compiled = audit.FeatureCompiler(status_authority="compiler").compile(feature)
    baseline = {
        row["clause_id"]: row
        for row in audit._matrix(feature, compiled)
    }
    assert baseline["proficiency-bonus-uses"]["status"] == "covered"
    degraded = {
        row["clause_id"]: row
        for row in audit._matrix(
            feature,
            compiled,
            evidence_overrides={("proficiency-bonus-uses", "focused_receipt"): False},
        )
    }
    assert degraded["proficiency-bonus-uses"]["status"] == "partial"
    assert degraded["proficiency-bonus-uses"]["evidence_checks"]["focused_receipt"] is False


def test_manifest_mind_audit_matrix_requires_all_runtime_dimensions() -> None:
    audit = _audit_module()
    raw = audit.json.loads(audit.IR_PATH.read_text(encoding="utf-8"))
    feature = audit._feature_spec(raw)
    compiled = audit.FeatureCompiler(status_authority="compiler").compile(feature)
    degraded = audit._matrix(
        feature,
        compiled,
        evidence_overrides={("proficiency-bonus-uses", "source_provenance"): False},
    )
    row = next(item for item in degraded if item["clause_id"] == "proficiency-bonus-uses")
    assert row["status"] == "partial"
    assert row["evidence_checks"]["source_provenance"] is False


def test_manifest_mind_termination_rows_degrade_when_focused_receipt_is_removed() -> None:
    audit = _audit_module()
    raw = audit.json.loads(audit.IR_PATH.read_text(encoding="utf-8"))
    feature = audit._feature_spec(raw)
    compiled = audit.FeatureCompiler(status_authority="compiler").compile(feature)
    baseline = {
        row["clause_id"]: row for row in audit._matrix(feature, compiled)
    }
    for clause_id in (
        "dispel-magic-expiry",
        "spellbook-destruction-expiry",
        "owner-death-expiry",
        "owner-dismissal-expiry",
    ):
        assert baseline[clause_id]["status"] == "covered"
        degraded = audit._matrix(
            feature,
            compiled,
            evidence_overrides={(clause_id, "focused_receipt"): False},
        )
        row = next(item for item in degraded if item["clause_id"] == clause_id)
        assert row["status"] == "partial"
        assert row["evidence_checks"]["focused_receipt"] is False
