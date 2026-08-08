from __future__ import annotations

import importlib.util
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPOSITORY_ROOT / "scripts/audit-class-feature-coverage.py"
PLANNER_PATH = REPOSITORY_ROOT / "scripts/plan-feature-automation-migrations.py"


def _audit_module():
    spec = importlib.util.spec_from_file_location("class_feature_audit", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _planner_module():
    spec = importlib.util.spec_from_file_location("feature_migration_planner", PLANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_audit_covers_fixed_core_and_subclass_scope() -> None:
    report = _audit_module().audit()
    assert report["scope"] == {
        "core_classes": 12,
        "core_features": 258,
        "subclasses": 56,
        "subclass_features": 241,
        "total_features": 499,
    }
    assert report["source_parse_counts"] == {
        "description_located": 415,
        "description_reused": 49,
        "structural_placeholder": 35,
    }


def test_source_audit_does_not_hide_complete_rules_in_dm_only_bucket() -> None:
    report = _audit_module().audit()
    rows = {
        row["feature_name"]: row
        for row in report["rows"]
        if row["scope"] == "core"
        and row["feature_name"] in {"创生圣言", "弃绝众敌", "复原之触", "德鲁伊语", "原初职能"}
    }
    assert set(rows) == {"创生圣言", "弃绝众敌", "复原之触", "德鲁伊语", "原初职能"}
    assert all(row["source_parse"] == "description_located" for row in rows.values())
    assert rows["复原之触"]["runtime_status"] == "full"
    assert all(
        row["runtime_status"] == "dm_only"
        for name, row in rows.items()
        if name != "复原之触"
    )


def test_migration_planner_keeps_fixed_scope_and_status_counts() -> None:
    report = _planner_module().plan()
    assert report["audit_scope"]["total_features"] == 499
    assert report["audit_status_counts"] == {
        "full": 207,
        "partial": 215,
        "dm_only": 77,
    }
    assert report["readiness_counts"] == {
        "consumer_partial": 41,
        "already_full": 207,
        "missing_runtime_contract": 196,
        "missing_source": 35,
        "manual_boundary": 10,
        "needs_contract_review": 10,
    }


def test_migration_planner_never_promotes_non_full_rows() -> None:
    report = _planner_module().plan()
    for row in report["rows"]:
        if row["runtime_status"] != "full":
            assert row["readiness"] != "already_full"
        if row["readiness"] == "already_full":
            assert row["runtime_status"] == "full"


def test_migration_planner_declares_a_consumer_for_every_template() -> None:
    report = _planner_module().plan()
    assert report["templates"]
    for template in report["templates"].values():
        assert template["consumer_status"] in {
            "production_closed",
            "production_partial",
            "manual_only",
        }
