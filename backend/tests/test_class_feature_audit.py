from __future__ import annotations

import importlib.util
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPOSITORY_ROOT / "scripts/audit-class-feature-coverage.py"


def _audit_module():
    spec = importlib.util.spec_from_file_location("class_feature_audit", AUDIT_PATH)
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
    assert all(row["runtime_status"] == "dm_only" for row in rows.values())
