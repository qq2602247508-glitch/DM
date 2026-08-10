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
    assert rows["原初职能"]["runtime_status"] == "full"
    assert all(
        row["runtime_status"] == "dm_only"
        for name, row in rows.items()
        if name not in {"复原之触", "原初职能", "德鲁伊语"}
    )


def test_migration_planner_keeps_fixed_scope_and_status_counts() -> None:
    report = _planner_module().plan()
    assert report["audit_scope"]["total_features"] == 499
    assert report["audit_status_counts"] == {
        "full": 320,
        "partial": 118,
        "dm_only": 61,
    }
    assert report["readiness_counts"] == {
            "consumer_partial": 25,
            "already_full": 320,
            "missing_runtime_contract": 110,
        "missing_source": 35,
        "manual_boundary": 3,
        "needs_contract_review": 6,
    }


def test_growth_asset_batch_has_stable_ids_and_explicit_grant_effect_boundaries() -> None:
    report = _planner_module().plan()
    markers = (
        "战斗风格",
        "魔法奥秘",
        "熟练探险家",
        "原初职能",
        "圣职",
        "仪式学家",
        "战争训练",
    )
    rows = [
        row
        for row in report["rows"]
        if any(marker in row["feature_name"] for marker in markers)
        and row["class_name"] in {"战士", "圣武士", "游侠", "吟游诗人", "德鲁伊", "牧师", "法师"}
    ]
    assert len(rows) == 10
    assert len({row["feature_id"] for row in rows}) == 10
    assert sum(row["runtime_status"] == "full" for row in rows) == 10
    assert {
        (row["class_name"], row["feature_name"], row["runtime_status"])
        for row in rows
        if row["runtime_status"] != "full"
    } == set()
    for row in rows:
        assert row["authoritative_catalog"]
        assert row["selected_asset_kind"]
        assert row["grant_consumer"] == "advancement_service"
        assert row["selected_asset_consumer"]
        assert row["selected_asset_status"]
        assert row["persisted_state"]
        assert row["grant_status"] in {"full", "partial"}


def test_migration_matrix_exposes_stable_execution_evidence() -> None:
    report = _planner_module().plan()
    assert report["schema_version"] == "feature-automation-migration-plan-2"
    assert len({row["feature_id"] for row in report["rows"]}) == 499
    assert list(report["rows"]) == sorted(
        report["rows"],
        key=lambda item: (
            item["reusable_cluster"],
            item["readiness"],
            item["class_name"],
            item.get("subclass_name") or "",
            item["level"],
            item["feature_name"],
        ),
    )
    required = {
        "feature_id",
        "runtime_reason",
        "trigger_time",
        "required_producers",
        "required_consumers",
        "producer_available",
        "consumer_available",
        "requires_resource",
        "requires_action_economy",
        "requires_player_input",
        "requires_dm_input",
        "requires_authoritative_targeting",
        "requires_status_context",
        "estimated_risk",
        "reusable_cluster",
        "eligible_this_run",
        "contract_evidence",
        "parameterized_contract_test",
        "representative_e2e_test",
        "blocking_reason",
        "gap_category",
    }
    assert all(required <= row.keys() for row in report["rows"])
    assert all(
        row["gap_category"]
        in {
            "missing_runtime_contract",
            "producer_missing",
            "consumer_missing",
            "consumer_partial",
            "resource_missing",
            "action_economy_missing",
            "authoritative_targeting_missing",
            "ui_input_missing",
            "prerequisite_feature_missing",
            "source_missing",
            "manual_boundary",
            "needs_contract_review",
        }
        for row in report["rows"]
        if row["runtime_status"] != "full"
    )
    assert all(
        row["gap_category"] is None
        for row in report["rows"]
        if row["runtime_status"] == "full"
    )
    epic_rows = [
        row
        for row in report["rows"]
        if row["reusable_cluster"] == "advancement_asset_grant:epic_boon"
    ]
    assert len(epic_rows) == 12
    assert all(row["contract_evidence"] == ["advancement"] for row in epic_rows)
    assert all(row["parameterized_contract_test"] for row in epic_rows)
    assert all(row["representative_e2e_test"] for row in epic_rows)
    epic = report["clusters"]["advancement_asset_grant:epic_boon"]
    assert epic == {
        "total_count": 12,
        "full_count": 12,
        "candidate_count": 0,
        "eligible_this_run": 0,
        "producer_available": True,
        "consumer_available": True,
        "requires_new_ui": False,
        "requires_new_persistence": False,
        "risk_counts": {"low": 12},
        "readiness_counts": {"already_full": 12},
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
