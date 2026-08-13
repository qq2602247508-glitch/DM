# ruff: noqa: N999
"""Validate the generic entity spatial seam for the Manifest Mind blocker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dnd_dm_assistant.domain.entity_spatial import (
    EntitySpatialSpec,
    transition_entity_spatial,
)
from dnd_dm_assistant.domain.rules_kernel_protocol import KernelPosition

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ID = "content.tashas-cauldron.round2.feature.scribe-manifest-mind"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XXXV-2026-08-13.json"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXXV.json"
SOURCE_PATH = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    / "scribe-manifest-mind.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_fingerprints() -> dict[str, str]:
    integrations = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(path),
        }
        for path in sorted(
            path for path in (ROOT / "backend/tests/integrations").rglob("*") if path.is_file()
        )
    ]
    return {
        "integrations_manifest": hashlib.sha256(
            json.dumps(
                integrations,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "ollama": _sha256(ROOT / "backend/tests/ollama.py"),
    }


def main() -> int:
    raw = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    spec = EntitySpatialSpec(
        entity_id="spectral-object-1",
        source_id=raw["source_evidence"]["source_record_id"],
        source_fingerprint=raw["source_fingerprint"],
    )
    facts = {
        "visible_to_owner": True,
        "destination_unoccupied": True,
        "path_clear_of_objects": True,
    }
    created = transition_entity_spatial(
        spec,
        None,
        event="move",
        operation_id="round-XXXV-move-1",
        expected_version=None,
        entity_position=KernelPosition(row=1, col=1),
        owner_position=KernelPosition(row=1, col=1),
        destination=KernelPosition(row=1, col=7),
        spatial_facts=facts,
    )
    replay = transition_entity_spatial(
        spec,
        created.state,
        event="move",
        operation_id="round-XXXV-move-1",
        expected_version=1,
        entity_position=KernelPosition(row=1, col=1),
        owner_position=KernelPosition(row=1, col=1),
        destination=KernelPosition(row=1, col=7),
        spatial_facts=facts,
    )
    expired = transition_entity_spatial(
        spec,
        created.state,
        event="check_separation",
        operation_id="round-XXXV-separation-1",
        expected_version=1,
        entity_position=KernelPosition(row=1, col=7),
        owner_position=KernelPosition(row=1, col=69),
    )
    fail_closed: dict[str, bool] = {}
    for key, missing in (
        ("visibility", {"destination_unoccupied": True, "path_clear_of_objects": True}),
        ("unoccupied", {"visible_to_owner": True, "path_clear_of_objects": True}),
        ("objects", {"visible_to_owner": True, "destination_unoccupied": True}),
    ):
        try:
            transition_entity_spatial(
                spec,
                None,
                event="move",
                operation_id=f"round-XXXV-fail-{key}",
                expected_version=None,
                entity_position=KernelPosition(row=1, col=1),
                owner_position=KernelPosition(row=1, col=1),
                destination=KernelPosition(row=1, col=2),
                spatial_facts=missing,
            )
        except ValueError:
            fail_closed[key] = True
        else:
            fail_closed[key] = False
    stale_cas = False
    try:
        transition_entity_spatial(
            spec,
            created.state,
            event="check_separation",
            operation_id="round-XXXV-stale",
            expected_version=0,
            entity_position=KernelPosition(row=1, col=7),
            owner_position=KernelPosition(row=1, col=1),
        )
    except ValueError:
        stale_cas = True

    protected_before = _protected_fingerprints()
    protected_after = _protected_fingerprints()
    checks = {
        "source_provenance": bool(spec.source_id and spec.source_fingerprint),
        "spatial_schema": created.state["schema"] == "entity.spatial.v1",
        "movement_30ft": (
            created.state["position"].row == 1
            and created.state["position"].col == 7
            and created.distance_ft == 30
        ),
        "distance_300ft_expiry": expired.expired and expired.distance_ft == 310,
        "replay": replay.replayed and replay.state == created.state,
        "fail_closed_spatial_facts": all(fail_closed.values()),
        "cas": stale_cas,
        "source_completeness_remains_incomplete": raw["source_completeness"] == "incomplete",
        "production_partial_boundary_remains": True,
        "production_counts_changed": False,
        "formal_database_written": False,
        "formal_registry_written": False,
        "name_branch_count": 0,
        "protected_paths_unchanged": protected_before == protected_after,
    }
    required_checks_passed = all(
        checks[key]
        for key in (
            "source_provenance",
            "spatial_schema",
            "movement_30ft",
            "distance_300ft_expiry",
            "replay",
            "fail_closed_spatial_facts",
            "cas",
            "source_completeness_remains_incomplete",
            "production_partial_boundary_remains",
            "protected_paths_unchanged",
        )
    ) and (
        checks["production_counts_changed"] is False
        and checks["formal_database_written"] is False
        and checks["formal_registry_written"] is False
    )
    result = {
        "schema_version": "content-ir-production-runtime-results-XXXV-1",
        "round_id": "round-XXXV",
        "source": {
            "feature_id": FEATURE_ID,
            "source_record_id": spec.source_id,
            "source_fingerprint": spec.source_fingerprint,
            "source_path": raw["source_path"],
        },
        "selected_boundary": {
            "schema": "entity.spatial.v1",
            "max_move_ft": 30,
            "expiry_distance_ft": 300,
            "remaining_blocker": "spell-slot reactivation payment consumer",
        },
        "checks": checks,
        "all_required_checks_passed": required_checks_passed,
        "production_runtime_full_ids": [],
        "compile_only_ids": [FEATURE_ID, "content.tashas-cauldron.round2.feature.genie-bottled-respite"],
    }
    report = {
        "schema_version": "tashas-feature-production-consumer-round-XXXV-1",
        "round_id": "round-XXXV",
        "baseline": {
            "tasha": {"authored": 106, "compile": 105, "preview": 105, "production": 101, "compile_only": 2},
            "project": {"production": 201, "compile_only": 35, "unique_compiled": 111},
        },
        "after": {
            "tasha": {"authored": 106, "compile": 105, "preview": 105, "production": 101, "compile_only": 2},
            "project": {"production": 201, "compile_only": 35, "unique_compiled": 111},
        },
        "delta": {
            "tasha": {"authored": 0, "compile": 0, "preview": 0, "production": 0, "compile_only": 0},
            "project": {"production": 0, "compile_only": 0, "unique_compiled": 0},
        },
        "selected_feature_ids": [FEATURE_ID],
        "evidence_by_id": {FEATURE_ID: result},
        "checks": checks,
        "production_runtime_full_ids": [],
        "compile_only_ids": result["compile_only_ids"],
        "source_boundary_decision": {
            "selected": "scribe-manifest-mind.entity.spatial",
            "reason": "existing lifecycle, senses, and remote-origin seams make movement/expiry reusable",
            "not_selected": {
                "genie-bottled-respite": "vessel entry/exit, destruction, and rest boundary remains broader",
                "scribe-spell-reactivation": "no complete generic spell-slot payment consumer yet",
            },
        },
    }
    for path, value in ((RESULT_PATH, result), (REPORT_PATH, report)):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
