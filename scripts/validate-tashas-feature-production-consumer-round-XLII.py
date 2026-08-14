# ruff: noqa: N999
"""Validate Genie Bottled Respite against the real vessel production seams."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

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
FEATURE_ID = "content.tashas-cauldron.round2.feature.genie-bottled-respite"
FEATURE_PATH = ROOT / (
    "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    "genie-bottled-respite.json"
)
RESULT_PATH = Path(
    os.environ.get(
        "ROUND_XLII_RESULT_PATH",
        str(ROOT / "data/content-ir/compiled/production-runtime-results-XLII.json"),
    )
)
REPORT_PATH = Path(
    os.environ.get(
        "ROUND_XLII_REPORT_PATH",
        str(ROOT / "reports/tashas-feature-production-consumer-round-XLII-2026-08-13.json"),
    )
)
BASELINE_PATH = ROOT / "reports/tashas-production-reconciliation-round-XXV-2026-08-12.json"
EXPECTED_BASELINE_SHA256 = (
    "1ca123067fedbcf6e8592afc8272f1e6f935280d475658c45613e4545094f8c7"
)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _protected_fingerprints() -> dict[str, str]:
    paths = sorted(
        path
        for path in (ROOT / "backend/tests/integrations").rglob("*")
        if path.is_file()
    )
    manifest = [
        {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in paths
    ]
    ollama = ROOT / "backend/tests/ollama.py"
    return {"integrations_manifest": _sha256(manifest), "ollama": hashlib.sha256(ollama.read_bytes()).hexdigest()}


def _load_authoritative_baseline() -> tuple[dict[str, Any], str]:
    """Load the last accepted reconciliation after-state, without mutation."""

    raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    counts = raw["counts"]
    baseline = {
        "tasha": {
            "authored": counts["after"]["tasha"]["authored_typed_ir"],
            "compile": counts["after"]["tasha"]["compile_full"],
            "preview": counts["after"]["tasha"]["runtime_preview_full"],
            "production": counts["after"]["tasha"]["production_full"],
            "compile_only": counts["after"]["tasha"]["compile_only"],
        },
        "project": {
            "production": counts["after"]["project"]["production"],
            "compile_only": counts["after"]["project"]["compile_only"],
            "unique_compiled": counts["after"]["project"]["unique_compiled"],
        },
        "selected_atom_status": {
            "production_full": int(
                FEATURE_ID in raw["evidence"]["tasha_receipt_ids"]
            ),
            "compile_only": int(
                FEATURE_ID not in raw["evidence"]["tasha_receipt_ids"]
            ),
        },
    }
    return baseline, hashlib.sha256(BASELINE_PATH.read_bytes()).hexdigest()


def _load_runtime() -> tuple[FeatureSpec, dict[str, Any], dict[str, Any], list[str]]:
    raw = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: value for key, value in raw.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    runtime = (
        materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
        if compiled.compile_status == "full"
        else {}
    )
    consumers = (
        [
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
        if runtime
        else []
    )
    return spec, compiled.to_dict(), runtime, consumers


def _run_real_e2e() -> dict[str, Any]:
    command = [
        str(ROOT / "backend/.venv/bin/python"),
        "-m",
        "pytest",
        "-q",
        "backend/tests/test_content_ir_vessel_runtime.py",
        "-k",
        (
            "real_content_ir_vessel_runtime_receipts_cover_lifecycle_and_long_rest"
            " or test_vessel_external_sound_real_event_e2e_resolves_and_replays"
            " or test_destroy_relocates_all_items_from_real_equipment_producer"
            " or test_owner_death_relocates_items_with_source_bound_receipts"
            " or test_destroy_requires_matching_real_producer_and_missing_producer_fails_closed"
            " or test_vessel_external_sound_direct_db_tampering_fails_closed"
        ),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "pytest_summary": completed.stdout.splitlines()[0] if completed.stdout else "",
        "warning_present": "DeprecationWarning" in completed.stdout,
        "passed": completed.returncode == 0,
    }


def _counts(migration: dict[str, Any]) -> dict[str, dict[str, int]]:
    tasha_atoms = [
        atom
        for atom in migration["atoms"]
        if atom.get("pack_id") == "tashas-cauldron"
        or str(atom.get("atom_id", "")).startswith("tashas-cauldron:")
    ]
    return {
        "tasha": {
            "authored": migration["authored_typed_ir"],
            "compile": migration["compile_full"],
            "preview": migration["runtime_preview_full"],
            "production": migration["production_full"],
            "compile_only": migration["compile_only"],
        },
        "project": {
            "production": migration["current_project_production_full"],
            "compile_only": migration["current_project_compile_only"],
            "unique_compiled": migration["current_project_compiled_unique"],
        },
        "selected_atom_status": {
            "production_full": sum(
                atom.get("content_id") == FEATURE_ID
                and atom.get("migration_status") == "production_full"
                for atom in tasha_atoms
            ),
            "compile_only": sum(
                atom.get("content_id") == FEATURE_ID
                and atom.get("migration_status") == "compile_only"
                for atom in tasha_atoms
            ),
        },
    }


def main() -> int:
    baseline, baseline_sha256 = _load_authoritative_baseline()
    spec, compile_result, runtime, consumers = _load_runtime()
    protected_before = _protected_fingerprints()
    e2e = _run_real_e2e()
    protected_after = _protected_fingerprints()
    migration = build_migration(ROOT)
    after = _counts(migration)
    selected_atom = next(
        (
            atom
            for atom in migration["atoms"]
            if atom.get("content_id") == FEATURE_ID
        ),
        None,
    )

    checks = {
        "source_complete_and_provenance": spec.source_completeness == "complete"
        and bool(spec.source_record_id and spec.source_fingerprint and spec.source_path),
        "compiler_full": compile_result["compile_status"] == "full",
        "materializer_full": bool(runtime)
        and runtime.get("automation_status") == "full"
        and len(runtime.get("vessel_spaces", [])) == 1,
        "typed_consumers_complete": consumers
        == ["vessel.external_sound.v1", "vessel.space.v1"],
        "external_sound_typed_and_producer_bound": bool(runtime.get("vessel_external_sound"))
        and runtime["vessel_external_sound"][0]["sound_contract"]
        == {
            "schema": "vessel.external_sound.v1",
            "channel": "hearing",
            "source_facts_authority": "asserted_input",
            "state_mutated": False,
            "producer_bound": True,
        },
        "isolated_real_api_e2e": e2e["passed"],
        "protected_paths_unchanged": protected_before == protected_after,
        "name_branch_count_zero": migration["item_spec_catalog"]["name_branch_count"] == 0,
        "baseline_artifact_present": BASELINE_PATH.is_file(),
        "baseline_artifact_hash_matches": baseline_sha256 == EXPECTED_BASELINE_SHA256,
        "baseline_after_state_is_accepted": (
            json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["checks"].get(
                "baseline_after_delta_relation"
            )
            is True
        ),
        "selected_atom_currently_production_full": (
            selected_atom is not None
            and selected_atom.get("migration_status") == "production_full"
        ),
    }
    all_required = all(
        value is True
        for key, value in checks.items()
        if key != "name_branch_count_zero"
    ) and checks["name_branch_count_zero"]
    delta = {
        group: {
            key: after[group][key] - baseline[group][key]
            for key in baseline[group]
            if isinstance(after[group].get(key), int)
        }
        for group in ("tasha", "project", "selected_atom_status")
    }

    # This file is intentionally generated before whole-pack reconciliation.
    # The second migration run supplies the post-promotion counts and hash.
    result = {
        "schema_version": "content-ir-production-runtime-results-XLII-1",
        "round_id": "round-XLII",
        "source": {
            "feature_id": spec.feature_id,
            "source_record_id": spec.source_record_id,
            "source_fingerprint": spec.source_fingerprint,
            "source_path": spec.source_path,
        },
        "compile": compile_result,
        "runtime_fingerprint": _sha256(runtime),
        "registry_consumers": consumers,
        "checks": checks,
        "e2e": e2e,
        "before_counts": baseline,
        "after_counts": after,
        "count_delta": delta,
        "production_runtime_full_ids": [FEATURE_ID] if all_required else [],
        "compile_only_ids": [] if all_required else [FEATURE_ID],
        "all_required_checks_passed": all_required,
    }
    # Keep the canonical compiled receipt self-describing.  The whole-pack
    # migration consumes this row to bind the persisted production ID back to
    # the typed atom; use a shallow copy to avoid a circular JSON structure.
    result["evidence_by_id"] = {FEATURE_ID: dict(result)}
    REPORT_PATH.write_text(json.dumps({
        "schema_version": "tashas-feature-production-consumer-round-XLII-1",
        "round_id": "round-XLII",
        "decision": "promoted" if all_required else "retained_compile_only",
        "baseline": baseline,
        "after": after,
        "delta": delta,
        "baseline_artifact": {
            "path": str(BASELINE_PATH.relative_to(ROOT)),
            "sha256": baseline_sha256,
        },
        "selected_feature_ids": [FEATURE_ID],
        "checks": checks,
        "blockers": [
            key for key, value in checks.items() if not value
        ],
        "production_runtime_full_ids": result["production_runtime_full_ids"],
        "compile_only_ids": result["compile_only_ids"],
        "evidence_by_id": {FEATURE_ID: result},
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if all_required else 1


if __name__ == "__main__":
    raise SystemExit(main())
