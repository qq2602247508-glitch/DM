"""Build the evidence-driven source-boundary matrix for Bottled Respite."""

# ruff: noqa: N999

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.tashas_whole_pack import build_migration
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/genie-bottled-respite.json"
REPORT = ROOT / "reports/tashas-genie-vessel-source-boundary-2026-08-13.json"
RUNTIME_SOURCE = ROOT / "backend/src/dnd_dm_assistant/application/content_ir_runtime.py"
TEST_SOURCE = ROOT / "backend/tests/test_content_ir_vessel_runtime.py"
SCHEMA_SOURCE = ROOT / "backend/src/dnd_dm_assistant/api/schemas.py"
EVENT_ROUTE_SOURCE = ROOT / "backend/src/dnd_dm_assistant/api/routes/campaigns.py"
EVENT_PRODUCER_SOURCE = ROOT / "backend/src/dnd_dm_assistant/infrastructure/database/campaign_service.py"
MODEL_SOURCE = ROOT / "backend/src/dnd_dm_assistant/infrastructure/database/models.py"
MIGRATION_SOURCE = ROOT / "backend/migrations/versions/20260813_0003_formal_vessel_persistence.py"
ATOM_INDEX = ROOT / "data/content-ir/isolated-packs/tashas-cauldron-2026-08-11/atom-index.json"
EVENT_PRODUCER_SOURCES = (
    EVENT_ROUTE_SOURCE,
    EVENT_PRODUCER_SOURCE,
)
PRODUCTION_RESULT = ROOT / "data/content-ir/compiled/production-runtime-results-XLII.json"
PRODUCTION_REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XLII-2026-08-13.json"


def _sanctuary_boundary(raw: dict[str, object]) -> dict[str, object]:
    atoms = json.loads(ATOM_INDEX.read_text(encoding="utf-8"))["atoms"]
    selected_atoms = [
        atom
        for atom in atoms
        if atom.get("content_id") == raw["feature_id"]
        and atom.get("source_record_id") == raw["source_record_id"]
        and atom.get("source_fragment") == "blockquote:42"
    ]
    sanctuary_atoms = [
        atom
        for atom in atoms
        if atom.get("english_name") == "Sanctuary Vessel"
        and atom.get("source_record_id") == raw["source_record_id"]
        and atom.get("level") == 10
        and atom.get("source_fragment") == "66"
        and not atom.get("content_id")
    ]
    metadata = raw["manual_decisions"].get("excluded_from_selected_feature", [])
    metadata_match = [
        item
        for item in metadata
        if item.get("feature_name") == "Sanctuary Vessel"
        and item.get("level") == 10
        and item.get("source_fragment") == "66"
    ]
    checks = [
        {
            "id": "selected_bottled_respite_atom",
            "path": str(ATOM_INDEX.relative_to(ROOT)),
            "required": True,
            "passed": len(selected_atoms) == 1,
            "matched": [selected_atoms[0]["atom_id"]] if len(selected_atoms) == 1 else [],
            "missing": [] if len(selected_atoms) == 1 else ["one selected Bottled Respite atom"],
        },
        {
            "id": "distinct_sanctuary_vessel_atom",
            "path": str(ATOM_INDEX.relative_to(ROOT)),
            "required": True,
            "passed": len(sanctuary_atoms) == 1,
            "matched": [sanctuary_atoms[0]["atom_id"]] if len(sanctuary_atoms) == 1 else [],
            "missing": [] if len(sanctuary_atoms) == 1 else ["one unassigned level-10 Sanctuary Vessel atom"],
        },
        {
            "id": "authored_exclusion_metadata",
            "path": str(SOURCE.relative_to(ROOT)),
            "required": True,
            "passed": len(metadata_match) == 1
            and metadata_match[0].get("feature_atom_id")
            == (sanctuary_atoms[0]["atom_id"] if len(sanctuary_atoms) == 1 else None),
            "matched": ["feature_atom_id", "level", "source_fragment"]
            if len(metadata_match) == 1
            and len(sanctuary_atoms) == 1
            and metadata_match[0].get("feature_atom_id") == sanctuary_atoms[0]["atom_id"]
            else [],
            "missing": [] if len(metadata_match) == 1 and len(sanctuary_atoms) == 1 and metadata_match[0].get("feature_atom_id") == sanctuary_atoms[0]["atom_id"] else ["matching exclusion metadata"],
        },
    ]
    missing = [f"{check['id']}: {', '.join(check['missing'])}" for check in checks if not check["passed"]]
    excluded_terms = {
        "sanctuary-vessel companion selection and short-rest benefit consumer"
    }
    source_terms = raw["manual_decisions"]["unmodeled_source_terms"]
    excluded = all(term not in source_terms for term in excluded_terms) and not missing
    return {
        "status": "excluded_from_selected_feature" if excluded else "blocked",
        "selected_feature": {
            "feature_id": raw["feature_id"],
            "atom_id": selected_atoms[0]["atom_id"] if len(selected_atoms) == 1 else None,
            "source_fragment": "blockquote:42",
        },
        "future_feature": {
            "feature_name": "Sanctuary Vessel",
            "atom_id": sanctuary_atoms[0]["atom_id"] if len(sanctuary_atoms) == 1 else None,
            "level": 10,
            "source_fragment": "66",
        },
        "checks": checks,
        "blockers": missing,
    }


def _check(
    source: Path,
    source_text: str,
    check_id: str,
    *needles: str,
) -> dict[str, object]:
    missing = [needle for needle in needles if needle not in source_text]
    return {
        "id": check_id,
        "path": str(source.relative_to(ROOT)),
        "required": True,
        "passed": not missing,
        "matched": [needle for needle in needles if needle not in missing],
        "missing": missing,
    }


def _destroyed_items_evidence() -> dict[str, object]:
    runtime_bytes = RUNTIME_SOURCE.read_bytes()
    test_bytes = TEST_SOURCE.read_bytes()
    runtime = runtime_bytes.decode("utf-8")
    tests = test_bytes.decode("utf-8")
    checks = [
        _check(
            RUNTIME_SOURCE,
            runtime,
            "real_destroy_producer_validation",
            "def _validate_lifecycle_producer(",
            'operation_type != "equipment_destroy"',
            'after.get("state") != "destroyed"',
            '_text(after.get("entity_id")) != entity_id',
        ),
        _check(
            RUNTIME_SOURCE,
            runtime,
            "world_item_version_cas",
            "select(WorldItem).where(",
            "update(WorldItem)",
            "WorldItem.version == expected_item_version",
            'raise VersionConflict(\n                            "world_item"',
        ),
        _check(
            RUNTIME_SOURCE,
            runtime,
            "per_item_nearest_position_receipt",
            "spatial.find_nearest_unoccupied_space(source)",
            '"position_receipt": item_position_receipt',
            '"before": before_item',
            '"after": {',
            '"version": item.version + 1',
        ),
        _check(
            RUNTIME_SOURCE,
            runtime,
            "replay_is_idempotent",
            "previous_vessel = previous.get(\"vessel_space\")",
            'return {**previous, "already_applied": True}',
            "vessel operation replay producer receipt does not match",
        ),
        _check(
            TEST_SOURCE,
            tests,
            "real_producer_e2e_test",
            "def _create_real_destroy_producer(",
            'f"{base}/characters/assets/equipment"',
            'f"{base}/equipment/preview"',
            'f"{base}/equipment/confirm"',
            '"operation": "destroy"',
            'producer.operation_type == "equipment_destroy"',
            'producer.status == "applied"',
        ),
        _check(
            TEST_SOURCE,
            tests,
            "required_destroy_test_collection",
            "def test_destroy_relocates_all_items_from_real_equipment_producer(",
            "def test_destroy_requires_matching_real_producer_and_missing_producer_fails_closed(",
            "def test_destroy_item_cas_conflict_rolls_back_vessel_and_character(",
        ),
        _check(
            TEST_SOURCE,
            tests,
            "multiple_item_receipts",
            'assert len(receipts) == 2',
            '"position_receipt"',
            '"before"',
            '"after"',
        ),
        _check(
            TEST_SOURCE,
            tests,
            "producer_mismatch_and_missing",
            'metadata={"vessel_id": vessel_id}',
            '"producer receipt" in response.text',
            '"not bound" in response.text',
        ),
        _check(
            TEST_SOURCE,
            tests,
            "item_cas_rollback",
            "item.version += 1",
            "assert confirmed.status_code == 409",
            '"vessel_container_id"] == vessel_id',
            '"inside"',
        ),
        _check(
            TEST_SOURCE,
            tests,
            "replay_no_duplicate_relocation",
            "assert replay.status_code == 200",
            'assert replay.json()["already_applied"] is True',
            '"vessel_relocated_from"] == vessel_id',
        ),
    ]
    missing = [
        f"{check['id']}: {', '.join(str(item) for item in check['missing'])}"
        for check in checks
        if not check["passed"]
    ]
    return {
        "status": "verified" if not missing else "blocked",
        "required_checks_passed": not missing,
        "checks": checks,
        "missing": missing,
        "blockers": missing,
        "runtime_source": str(RUNTIME_SOURCE.relative_to(ROOT)),
        "test_source": str(TEST_SOURCE.relative_to(ROOT)),
        "verified_at_source_hashes": {
            str(RUNTIME_SOURCE.relative_to(ROOT)): hashlib.sha256(runtime_bytes).hexdigest(),
            str(TEST_SOURCE.relative_to(ROOT)): hashlib.sha256(test_bytes).hexdigest(),
        },
        "pytest_target": [
            "backend/tests/test_content_ir_vessel_runtime.py",
            "test_destroy_relocates_all_items_from_real_equipment_producer",
            "test_destroy_requires_matching_real_producer_and_missing_producer_fails_closed",
            "test_destroy_item_cas_conflict_rolls_back_vessel_and_character",
        ],
    }


def _external_sound_evidence() -> dict[str, object]:
    runtime_text = RUNTIME_SOURCE.read_text(encoding="utf-8")
    tests = TEST_SOURCE.read_text(encoding="utf-8")
    schema_text = SCHEMA_SOURCE.read_text(encoding="utf-8")
    route_text = EVENT_ROUTE_SOURCE.read_text(encoding="utf-8")
    producer_text = EVENT_PRODUCER_SOURCE.read_text(encoding="utf-8")
    behavioral_command = [
        str(ROOT / "backend/.venv/bin/python"),
        "-m",
        "pytest",
        "-q",
        str(TEST_SOURCE.relative_to(ROOT)),
        "-k",
        "real_event_e2e_resolves_and_replays or direct_db_tampering_fails_closed",
    ]
    behavioral_result = subprocess.run(
        behavioral_command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks = [
        _check(
            SCHEMA_SOURCE,
            schema_text,
            "event_create_audible_validator",
            "class EventCreate(BaseModel):",
            "audible_sound events must be created through the producer path",
            "class AudibleSoundEventCreate(BaseModel):",
        ),
        {
            "id": "real_events_api_create_test",
            "path": str(TEST_SOURCE.relative_to(ROOT)),
            "required": True,
            "passed": all(
                needle in tests
                for needle in (
                    'f"{base}/events/audible-sound"',
                    '"source_producer"',
                    '"producer_operation_id"]',
                )
            ),
            "matched": [
                needle
                for needle in (
                    'f"{base}/events/audible-sound"',
                    '"source_producer"',
                    '"producer_operation_id"]',
                )
                if needle in tests
            ],
            "missing": [
                needle
                for needle in (
                    'f"{base}/events/audible-sound"',
                    '"source_producer"',
                    '"producer_operation_id"]',
                )
                if needle not in tests
            ],
        },
        {
            "id": "runtime_event_query_validation",
            "path": str(RUNTIME_SOURCE.relative_to(ROOT)),
            "required": True,
            "passed": all(
                needle in runtime_text
                for needle in (
                    "session.get(Event, event_id)",
                    'event.event_type != "audible_sound"',
                    "event.campaign_id != campaign_id",
                    "event.location_id",
                    "event.visibility",
                    "source_producer",
                    "source_fingerprint",
                )
            ),
            "matched": [
                needle
                for needle in (
                    "session.get(Event, event_id)",
                    'event.event_type != "audible_sound"',
                    "event.campaign_id != campaign_id",
                    "event.location_id",
                    "event.visibility",
                    "source_producer",
                    "source_fingerprint",
                )
                if needle in runtime_text
            ],
            "missing": [
                needle
                for needle in (
                    "session.get(Event, event_id)",
                    'event.event_type != "audible_sound"',
                    "event.campaign_id != campaign_id",
                    "event.location_id",
                    "event.visibility",
                    "source_producer",
                    "source_fingerprint",
                )
                if needle not in runtime_text
            ],
        },
        {
            "id": "dedicated_event_producer",
            "path": str(EVENT_PRODUCER_SOURCE.relative_to(ROOT)),
            "required": True,
            "passed": all(
                needle in producer_text
                for needle in (
                    "def create_audible_sound_event(",
                    'operation_type="event_audible_sound"',
                    '"source_facts_authority": "asserted_input"',
                    '"producer_operation_id": operation.id',
                )
            ),
            "matched": [
                needle
                for needle in (
                    "def create_audible_sound_event(",
                    'operation_type="event_audible_sound"',
                    '"source_facts_authority": "asserted_input"',
                    '"producer_operation_id": operation.id',
                )
                if needle in producer_text
            ],
            "missing": [
                needle
                for needle in (
                    "def create_audible_sound_event(",
                    'operation_type="event_audible_sound"',
                    '"source_facts_authority": "asserted_input"',
                    '"producer_operation_id": operation.id',
                )
                if needle not in producer_text
            ],
        },
        {
            "id": "generic_event_crud_rejection",
            "path": str(EVENT_ROUTE_SOURCE.relative_to(ROOT)),
            "required": True,
            "passed": all(
                needle in route_text
                for needle in (
                    "audible_sound events must be created through the producer path",
                    'if singular == "event" and values.get("event_type") == "audible_sound":',
                )
            ),
            "matched": [
                needle
                for needle in (
                    "audible_sound events must be created through the producer path",
                    'if singular == "event" and values.get("event_type") == "audible_sound":',
                )
                if needle in route_text
            ],
            "missing": [
                needle
                for needle in (
                    "audible_sound events must be created through the producer path",
                    'if singular == "event" and values.get("event_type") == "audible_sound":',
                )
                if needle not in route_text
            ],
        },
        {
            "id": "external_sound_e2e_receipt_test",
            "path": str(TEST_SOURCE.relative_to(ROOT)),
            "required": True,
            "passed": all(
                needle in tests
                for needle in (
                    "def test_vessel_external_sound_real_event_e2e_resolves_and_replays(",
                    '"status"] == "resolved"',
                    '"event_id"] == event["id"]',
                    '"channel"] == "hearing"',
                    '"state_mutated"] is False',
                    'assert replay.json()["already_applied"] is True',
                )
            ),
            "matched": [
                needle
                for needle in (
                    "def test_vessel_external_sound_real_event_e2e_resolves_and_replays(",
                    '"status"] == "resolved"',
                    '"event_id"] == event["id"]',
                    '"channel"] == "hearing"',
                    '"state_mutated"] is False',
                    'assert replay.json()["already_applied"] is True',
                )
                if needle in tests
            ],
            "missing": [
                needle
                for needle in (
                    "def test_vessel_external_sound_real_event_e2e_resolves_and_replays(",
                    '"status"] == "resolved"',
                    '"event_id"] == event["id"]',
                    '"channel"] == "hearing"',
                    '"state_mutated"] is False',
                    'assert replay.json()["already_applied"] is True',
                )
                if needle not in tests
            ],
        },
        {
            "id": "external_sound_negative_tests",
            "path": str(TEST_SOURCE.relative_to(ROOT)),
            "required": True,
            "passed": all(
                needle in tests
                for needle in (
                    "test_vessel_external_sound_event_validation_fails_closed(",
                    "test_vessel_external_sound_rejects_non_audible_event_and_wrong_binding(",
                    "test_vessel_external_sound_patch_cannot_mutate_producer_provenance(",
                    "test_vessel_external_sound_rejects_terminated_state(",
                    "test_vessel_external_sound_rejects_outsider_and_non_hearing_channel(",
                )
            ),
            "matched": [
                needle
                for needle in (
                    "test_vessel_external_sound_event_validation_fails_closed(",
                    "test_vessel_external_sound_rejects_non_audible_event_and_wrong_binding(",
                    "test_vessel_external_sound_patch_cannot_mutate_producer_provenance(",
                    "test_vessel_external_sound_rejects_terminated_state(",
                    "test_vessel_external_sound_rejects_outsider_and_non_hearing_channel(",
                )
                if needle in tests
            ],
            "missing": [
                needle
                for needle in (
                    "test_vessel_external_sound_event_validation_fails_closed(",
                    "test_vessel_external_sound_rejects_non_audible_event_and_wrong_binding(",
                    "test_vessel_external_sound_patch_cannot_mutate_producer_provenance(",
                    "test_vessel_external_sound_rejects_terminated_state(",
                    "test_vessel_external_sound_rejects_outsider_and_non_hearing_channel(",
                )
                if needle not in tests
            ],
        },
        {
            "id": "external_sound_behavioral_tests",
            "path": str(TEST_SOURCE.relative_to(ROOT)),
            "required": True,
            "passed": behavioral_result.returncode == 0,
            "matched": [
                "identical producer replay and conflicting same-key rejection",
                "direct DB producer receipt tamper fail-closed cases",
            ]
            if behavioral_result.returncode == 0
            else [],
            "missing": []
            if behavioral_result.returncode == 0
            else ["behavioral pytest for replay conflict and receipt tampering"],
        },
    ]
    blockers = [
        item["id"]
        for item in checks
        if item["required"] and not item["passed"]
    ]
    return {
        "status": "verified" if not blockers else "blocked",
        "producer_exists": all(item["passed"] for item in checks),
        "checks": checks,
        "blockers": blockers,
        "allowed_request_shape": ["event_id"],
        "caller_supplied_sound_events": False,
        "behavioral_pytest": behavioral_command,
        "sources": [
            str(MODEL_SOURCE.relative_to(ROOT)),
            *[str(path.relative_to(ROOT)) for path in EVENT_PRODUCER_SOURCES],
        ],
    }


def _formal_persistence_evidence() -> dict[str, object]:
    model = MODEL_SOURCE.read_text(encoding="utf-8")
    migration = MIGRATION_SOURCE.read_text(encoding="utf-8")
    runtime = RUNTIME_SOURCE.read_text(encoding="utf-8")
    tests = TEST_SOURCE.read_text(encoding="utf-8")
    checks = [
        _check(
            MODEL_SOURCE,
            model,
            "formal_vessel_model",
            "class VesselSpace(Timestamped, Base):",
            '__tablename__ = "vessel_spaces"',
            "source_fingerprint",
            "occupants_json",
            "items_json",
            "termination_reason",
        ),
        _check(
            MIGRATION_SOURCE,
            migration,
            "formal_vessel_empty_db_migration",
            'op.create_table(\n        "vessel_spaces"',
            'sa.PrimaryKeyConstraint("vessel_id")',
            'sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]',
        ),
        _check(
            RUNTIME_SOURCE,
            runtime,
            "formal_vessel_runtime_recovery_and_cas",
            "select(VesselSpace).where(",
            "formal_expected_version",
            "update(VesselSpace)",
            "vessel_preview[\"source_provenance\"]",
        ),
        _check(
            TEST_SOURCE,
            tests,
            "formal_vessel_independent_recovery_test",
            "def test_new_service_instance_recovers_vessel_state_from_formal_row(",
            "ContentIRRuntimeService(engine).preview(",
            "stale-feature-only",
        ),
    ]
    missing = [
        f"{check['id']}: {', '.join(str(item) for item in check['missing'])}"
        for check in checks
        if not check["passed"]
    ]
    return {
        "status": "verified" if not missing else "blocked",
        "required_checks_passed": not missing,
        "checks": checks,
        "blockers": missing,
        "sources": [
            str(MODEL_SOURCE.relative_to(ROOT)),
            str(MIGRATION_SOURCE.relative_to(ROOT)),
            str(RUNTIME_SOURCE.relative_to(ROOT)),
            str(TEST_SOURCE.relative_to(ROOT)),
        ],
    }


def _source_bound_exit_relocation_evidence() -> dict[str, object]:
    runtime = RUNTIME_SOURCE.read_text(encoding="utf-8")
    tests = TEST_SOURCE.read_text(encoding="utf-8")
    checks = [
        _check(
            RUNTIME_SOURCE,
            runtime,
            "nearest_source_bound_position_receipt",
            "def _vessel_position_receipt(",
            "find_nearest_unoccupied_space(",
            '"position_receipts": position_receipts',
        ),
        _check(
            RUNTIME_SOURCE,
            runtime,
            "distinct_termination_destinations",
            "spatial.add_entity(",
            "position_subject_ids = (",
            "receipt_item_ids = (",
            'event in {"destroy", "owner_death"}',
        ),
        _check(
            TEST_SOURCE,
            tests,
            "normal_exit_keeps_items_contained",
            'assert item_after_exit["metadata_json"]["vessel_container_id"] == vessel_id',
            'assert "vessel_relocated_from" not in item_after_exit["metadata_json"]',
        ),
        _check(
            TEST_SOURCE,
            tests,
            "owner_death_relocation_receipts",
            "def test_owner_death_relocates_items_with_source_bound_receipts(",
            'assert confirmed.json()["vessel_space"]["state"]["status"] == "removed"',
            'assert replay.json()["already_applied"] is True',
        ),
    ]
    command = [
        str(ROOT / "backend/.venv/bin/python"),
        "-m",
        "pytest",
        "-q",
        "backend/tests/test_content_ir_vessel_runtime.py",
        "backend/tests/test_vessel_space.py",
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks.append(
        {
            "id": "focused_runtime_tests",
            "path": "backend/tests/test_content_ir_vessel_runtime.py",
            "required": True,
            "passed": result.returncode == 0,
            "matched": ["focused vessel runtime/domain suite"] if result.returncode == 0 else [],
            "missing": [] if result.returncode == 0 else ["focused pytest"],
        }
    )
    missing = [
        f"{check['id']}: {', '.join(str(item) for item in check['missing'])}"
        for check in checks
        if not check["passed"]
    ]
    return {
        "status": "verified" if not missing else "blocked",
        "required_checks_passed": not missing,
        "checks": checks,
        "blockers": missing,
        "pytest_target": command[4:],
    }


def _production_parity_evidence(raw: dict[str, object]) -> dict[str, object]:
    source_value = json.loads(SOURCE.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: value for key, value in source_value.items() if key in FeatureSpec._FIELDS},
        path=str(SOURCE),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    runtime: dict[str, object] = {}
    materializer_error = None
    if compiled.compile_status == "full":
        try:
            runtime = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
        except (TypeError, ValueError) as exc:
            materializer_error = str(exc)
    consumers: list[str] = []
    registry_error = None
    if runtime:
        try:
            consumers = [
                item["consumer_id"]
                for item in resolve_production_consumers(
                    content_kind="advancement",
                    runtime_schema_version="feature-runtime-1",
                    blocks={
                        key: runtime[key]
                        for key in ("vessel_spaces", "vessel_external_sound")
                        if runtime.get(key)
                    },
                )
            ]
        except ValueError as exc:
            registry_error = str(exc)
    try:
        result = json.loads(PRODUCTION_RESULT.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {}
        result_error = str(exc)
    else:
        result_error = None
    try:
        report = json.loads(PRODUCTION_REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {}
        report_error = str(exc)
    else:
        report_error = None

    checks = {
        "source_complete": spec.source_completeness == "complete",
        "compiler_full": compiled.compile_status == "full",
        "materializer_full": bool(runtime)
        and runtime.get("automation_status") == "full"
        and len(runtime.get("vessel_spaces", [])) == 1,
        "vessel_external_sound_materialized": len(runtime.get("vessel_external_sound", [])) == 1,
        "registry_resolves_both_consumers": consumers
        == ["vessel.external_sound.v1", "vessel.space.v1"],
        "isolated_result_passed": result.get("all_required_checks_passed") is True
        and raw["feature_id"] in result.get("production_runtime_full_ids", []),
        "round_report_promoted": report.get("decision") == "promoted"
        and raw["feature_id"] in report.get("production_runtime_full_ids", []),
        "name_branch_count_zero": (
            report.get("checks", {}).get("name_branch_count_zero") is True
            or report.get("checks", {}).get("name_branch_count") == 0
        ),
    }
    blockers = [
        key
        for key, passed in checks.items()
        if not passed
    ]
    if materializer_error:
        blockers.append(f"materializer:{materializer_error}")
    if registry_error:
        blockers.append(f"registry:{registry_error}")
    if result_error:
        blockers.append(f"result:{result_error}")
    if report_error:
        blockers.append(f"round_report:{report_error}")

    migration = build_migration(ROOT)
    production_ids = set(migration["matched_production_runtime_ids"])
    selected_promoted = raw["feature_id"] in production_ids
    counts = {
        "tasha": {
            "authored": migration["authored_typed_ir"],
            "compile": migration["compile_full"],
            "preview": migration["runtime_preview_full"],
            "production": migration["production_full"],
            "compile_only": migration["compile_only"],
        },
        "project": {
            "production": migration["current_project_production_full"],
            "compile_only": len(set(migration["typed_entries"]) - production_ids),
            "unique_compiled": migration["current_project_compiled_unique"],
        },
    }
    return {
        "status": "verified" if not blockers and selected_promoted else "blocked",
        "feature_id": raw["feature_id"],
        "checks": checks,
        "blockers": blockers,
        "compiler": compiled.to_dict(),
        "materialized_sections": {
            key: len(value)
            for key, value in runtime.items()
            if isinstance(value, list) and key in {"vessel_spaces", "vessel_external_sound"}
        },
        "registry_consumers": consumers,
        "production_result_path": str(PRODUCTION_RESULT.relative_to(ROOT)),
        "production_report_path": str(PRODUCTION_REPORT.relative_to(ROOT)),
        "counts_from_whole_pack": counts,
        "production_runtime_full_ids": sorted(production_ids),
        "selected_feature_promoted": selected_promoted,
    }


def main() -> int:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    excerpt = raw["source_evidence"]["source_excerpt"]
    sanctuary_boundary = _sanctuary_boundary(raw)
    destroyed_items_evidence = _destroyed_items_evidence()
    external_sound_evidence = _external_sound_evidence()
    formal_persistence_evidence = _formal_persistence_evidence()
    exit_relocation_evidence = _source_bound_exit_relocation_evidence()
    production_parity_evidence = _production_parity_evidence(raw)
    destroyed_items_status = (
        "verified"
        if destroyed_items_evidence["required_checks_passed"]
        else "blocked"
    )
    matrix = [
        {"id": "enter_action", "source": "以一个动作", "status": "contracted", "runtime": "vessel.space.v1"},
        {"id": "touch_vessel", "source": "在你触碰你器皿的情况下", "status": "contracted", "runtime": "authoritative_fact"},
        {"id": "companion_capacity", "source": "10级器皿庇护所：最多5个可见自愿生物", "status": sanctuary_boundary["status"], "runtime": "future Sanctuary Vessel capability", "evidence": sanctuary_boundary},
        {"id": "companion_distance", "source": "10级器皿庇护所：30尺内", "status": sanctuary_boundary["status"], "runtime": "future Sanctuary Vessel capability", "evidence": sanctuary_boundary},
        {"id": "interior_geometry", "source": "20尺半径，20尺高的圆柱形异次元空间", "status": "contracted", "runtime": "vessel.space.v1"},
        {"id": "interior_state", "source": "温度适宜、舒适的垫子和茶几", "status": "contracted", "runtime": "vessel.space.v1"},
        {
            "id": "external_sound",
            "source": "如同身在器皿所在之处一般听到外界的声音",
            "status": (
                "verified"
                if external_sound_evidence["status"] == "verified"
                else "blocked"
            ),
            "runtime": (
                "producer-bound vessel.external_sound.v1"
                if external_sound_evidence["status"] == "verified"
                else "vessel.external_sound.v1 fail-closed evidence"
            ),
            "evidence": external_sound_evidence,
        },
        {"id": "duration", "source": "熟练加值双倍数目的小时", "status": "contracted", "runtime": "proficiency_bonus_times_2"},
        {"id": "leave_conditions", "source": "死亡、器皿被摧毁、附赠动作离开", "status": "contracted", "runtime": "entity lifecycle"},
        {
            "id": "exit_placement",
            "source": "距离它最近的未占据空间",
            "status": (
                "contracted"
                if exit_relocation_evidence["status"] != "verified"
                else "verified"
            ),
            "runtime": "SpatialAuthority",
            "evidence": exit_relocation_evidence,
        },
        {
            "id": "carried_items",
            "source": "器皿内的一切物件将被留在其中直到被取出",
            "status": "contracted",
            "runtime": "WorldItem containment receipt",
            "evidence": {
                "api": "content_ir_runtime.vessel_space",
                "receipt_fields": ["item_receipts", "vessel_container_id"],
                "transactional": True,
            },
        },
        {
            "id": "formal_persistence",
            "source": "formal vessel persistence and entity containment consumer",
            "status": (
                "contracted"
                if formal_persistence_evidence["status"] == "verified"
                else "blocked"
            ),
            "runtime": "VesselSpace SQLAlchemy model + ContentIRRuntime CAS",
            "evidence": formal_persistence_evidence,
        },
        {
            "id": "whole_feature_production_parity",
            "source": "compiler/materializer/registry/isolated production result/whole-pack migration",
            "status": production_parity_evidence["status"],
            "runtime": "registered_production_full",
            "evidence": production_parity_evidence,
        },
        {
            "id": "destroyed_items",
            "source": "器皿被摧毁，物品完好无损出现在最近未占据空间",
            "status": destroyed_items_status,
            "runtime": "WorldItem destruction relocation",
            "evidence": destroyed_items_evidence,
        },
        {"id": "long_rest_limit", "source": "直到完成一次长休前不能再度进入", "status": "contracted", "runtime": "RestService reset"},
        {"id": "sanctuary_eject", "source": "10级器皿庇护所：附赠动作逐出任意数目的生物", "status": sanctuary_boundary["status"], "runtime": "future Sanctuary Vessel capability", "evidence": sanctuary_boundary},
        {"id": "sanctuary_short_rest", "source": "10级器皿庇护所：停留至少10分钟可视为完成短休", "status": sanctuary_boundary["status"], "runtime": "future Sanctuary Vessel capability", "evidence": sanctuary_boundary},
        {"id": "vessel_appearance", "source": "D6 器皿表：油灯、瓮、戒指、瓶子、小雕像、提灯", "status": "contracted", "runtime": "source-bound enum"},
        {"id": "vessel_size", "source": "微型物件", "status": "contracted", "runtime": "vessel.space.v1"},
        {"id": "nested_entry", "source": "source does not explicitly state nested entry", "status": "fail_closed_policy", "runtime": "vessel.space.v1"},
        {"id": "illegal_facts", "source": "user/DM cannot invent capacity, consent, position or occupancy", "status": "fail_closed_policy", "runtime": "authoritative facts"},
    ]
    report = {
        "schema_version": "tashas-genie-vessel-source-boundary-1",
        "feature_id": raw["feature_id"],
        "source": {
            "record_id": raw["source_record_id"],
            "fingerprint": raw["source_fingerprint"],
            "path": raw["source_path"],
            "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "excerpt": excerpt,
            "source_completeness": raw["source_completeness"],
        },
        "authored_ir": {
            "path": str(SOURCE.relative_to(ROOT)),
            "clause_ids": [item["clause_id"] for item in raw["clauses"]],
            "unmodeled_source_terms": raw["manual_decisions"]["unmodeled_source_terms"],
            "excluded_from_selected_feature": raw["manual_decisions"].get("excluded_from_selected_feature", []),
        },
        "matrix": matrix,
        "promotion": {
            "compile_only": production_parity_evidence["status"] != "verified",
            "reason": (
                "all selected level-1 Bottled Respite production gates passed"
                if production_parity_evidence["status"] == "verified"
                else "whole-feature production parity remains blocked; see exact gate blockers"
            ),
            "whole_feature_production_parity": production_parity_evidence,
            "external_sound": external_sound_evidence,
            "formal_persistence": formal_persistence_evidence,
            "source_bound_exit_relocation": exit_relocation_evidence,
            "sanctuary_boundary": sanctuary_boundary,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "entries": len(matrix)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
