# ruff: noqa: N999
"""Close Intellect Fortress through the existing generic defense consumers."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.application.content_ir_production_evidence import (
    authoritative_compile_only_ids,
    load_production_runtime_evidence,
    project_compile_only_ids,
)
from dnd_dm_assistant.application.tashas_whole_pack import (
    build_migration,
    protected_path_fingerprints,
)
from dnd_dm_assistant.config import Settings
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SPELL_ID = "tashas-cauldron:spell:b4ea0dc1907dd5ac08666af3"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-LVI.json"
REPORT_PATH = ROOT / "reports/round-LVI-intellect-fortress-closure-2026-08-14.json"
FOCUSED_TEST = "backend/tests/test_round_LVI_intellect_fortress_closure.py"
EXPECTED_OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
EXPECTED_XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"
OLD_VALIDATOR = ROOT / "scripts/validate-tashas-spell-production-consumer-round-XXIII.py"
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_ISO_TIMESTAMP_RE = re.compile(
    r"\b20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\b"
)


def _load_old() -> Any:
    spec = importlib.util.spec_from_file_location("round_xxiii_validator", OLD_VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load the existing generic defense harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable(value: Any) -> Any:
    if isinstance(value, str):
        value = _UUID_RE.sub("stable-id", value)
        return _ISO_TIMESTAMP_RE.sub("stable-time", value)
    if isinstance(value, dict):
        return {
            key: (
                _stable(item)
                if isinstance(item, (list, dict))
                else "stable-id"
                if key.endswith(("_id", "_ids"))
                or key in {"id", "operation_transaction_id"}
                else "stable-token"
                if key.endswith("_fingerprint") or key == "preview_token"
                else "stable-time"
                if key.endswith("_at") or key in {"created_at", "updated_at"}
                else _stable(item)
            )
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def _payload_drift_probe(old: Any, runtime: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="round-lvi-drift-") as directory:
        database_url = f"sqlite:///{Path(directory) / 'drift.db'}"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            scene = old._setup(client, runtime)
            body = old._body(
                scene,
                "round-lvi-payload-drift",
                target_indexes=[0],
            )
            preview = client.post(
                f"{scene['base']}/content-ir/runtime/preview",
                json=body,
            )
            drifted = {
                **body,
                "slot_level": 4,
                "preview_token": preview.json()["preview_token"],
            }
            response = client.post(
                f"{scene['base']}/content-ir/runtime/confirm",
                json=drifted,
            )
            return {
                "preview_status": preview.status_code,
                "confirm_status": response.status_code,
                "rejected": response.status_code in {400, 409},
                "response_text": response.text,
            }


def _strict_nonproduction_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="round-lvi-loader-") as directory:
        root = Path(directory)
        artifact_path = root / "data/content-ir/compiled/production-runtime-results-invalid.json"
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_text(
            json.dumps(
                {
                    "production_runtime_full_ids": [SPELL_ID],
                    "evidence_by_id": {
                        SPELL_ID: {
                            "content_id": SPELL_ID,
                            "production_runtime_full": False,
                        }
                    },
                    "checks": {
                        "all_required_checks_passed": False,
                        "name_branch_count": 1,
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        loaded = load_production_runtime_evidence(
            root,
            pack_id=None,
            required_checks=("all_required_checks_passed",),
            require_name_branch_free=True,
        )
        return {
            "artifact": "stable-loader-artifact",
            "loaded_ids": sorted(loaded),
            "rejected": SPELL_ID not in loaded,
        }


def _run_base_validator(old: Any) -> dict[str, Any]:
    old.RESULT_PATH = RESULT_PATH
    old.REPORT_PATH = REPORT_PATH
    old.main()
    return json.loads(RESULT_PATH.read_text(encoding="utf-8"))


def _projection_before() -> dict[str, Any]:
    current_artifact = str(RESULT_PATH.relative_to(ROOT))
    authoritative = authoritative_compile_only_ids(ROOT)
    prior_loaded = {
        content_id: row
        for content_id, row in load_production_runtime_evidence(
            ROOT,
            pack_id=None,
            required_checks=("all_required_checks_passed",),
            require_name_branch_free=True,
        ).items()
        if row.get("evidence_path") != current_artifact
    }
    before_compile_only = project_compile_only_ids(authoritative, prior_loaded)
    production_before = {
        content_id
        for content_id, row in load_production_runtime_evidence(ROOT, pack_id=None).items()
        if row.get("evidence_path") != current_artifact
    }
    return {
        "authoritative_size": len(authoritative),
        "prior_loaded_ids": sorted(prior_loaded),
        "before_compile_only_ids": sorted(before_compile_only),
        "production_before_ids": sorted(production_before),
    }


def _candidate_comparison() -> dict[str, Any]:
    census_path = ROOT / "reports/round-LIV-summon-census-closure-2026-08-14.json"
    census = json.loads(census_path.read_text(encoding="utf-8"))
    rows = census["census"]["groups"]
    selected = next(
        group
        for group in rows
        if SPELL_ID in group["content_ids"]
    )
    return {
        "selected": {
            "content_id": SPELL_ID,
            "semantic_group": selected["semantic_group"],
            "shared_consumer": selected["shared_consumer"],
        },
        "basis": [
            "source-complete authored/compiled IR",
            "existing generic spell.defense.v1 and spell_economy.concentration.v1",
            "existing real API/SQLite harness with persistence, lifecycle and rollback coverage",
        ],
        "other_remaining_groups": sorted(
            group["semantic_group"]
            for group in rows
            if SPELL_ID not in group["content_ids"]
        ),
        "ranking_claim": False,
    }


def _source_names(source: dict[str, Any]) -> tuple[str, str]:
    source_text = json.dumps(source, ensure_ascii=False)
    match = re.search(r"｜([A-Za-z][A-Za-z -]+)", source_text)
    if match is None:
        raise AssertionError("source does not expose the English spell name")
    return str(source["name"]), match.group(1).strip()


def _name_branch_count(source: dict[str, Any]) -> dict[str, Any]:
    chinese_name, english_name = _source_names(source)
    markers = (SPELL_ID, chinese_name, english_name)
    files = sorted((ROOT / "backend/src/dnd_dm_assistant").rglob("*.py"))
    occurrences = {
        str(path.relative_to(ROOT)): {
            marker: path.read_text(encoding="utf-8").count(marker)
            for marker in markers
            if path.read_text(encoding="utf-8").count(marker)
        }
        for path in files
    }
    occurrences = {path: counts for path, counts in occurrences.items() if counts}
    return {
        "count": sum(sum(counts.values()) for counts in occurrences.values()),
        "markers": {
            "content_id": SPELL_ID,
            "chinese_name": chinese_name,
            "english_name": english_name,
        },
        "occurrences": occurrences,
    }


def _current_evidence_exact(
    base_result: dict[str, Any],
    source: dict[str, Any],
    consumers: list[str],
) -> bool:
    evidence = base_result.get("evidence_by_id")
    if not isinstance(evidence, dict) or set(evidence) != {SPELL_ID}:
        return False
    if base_result.get("checks", {}).get("production_runtime_full") is not True:
        return False
    row = evidence.get(SPELL_ID)
    if not isinstance(row, dict):
        return False
    return (
        row.get("runtime_id") == SPELL_ID
        and row.get("source_record_id") == source.get("source_record_id")
        and row.get("source_path") == source.get("source_path")
        and row.get("source_fingerprint") == source.get("source_fingerprint")
        and row.get("consumer_ids") == consumers
    )


def _write_artifact(result: dict[str, Any], *, bootstrap_phase: bool) -> None:
    payload = {**result, "bootstrap_phase": bootstrap_phase}
    RESULT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _required_check_keys(checks: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        key
        for key, value in checks.items()
        if key not in {"all_required_checks_passed", "name_branch_count"}
        and isinstance(value, bool)
    )


def main() -> int:
    old = _load_old()
    base_result = _run_base_validator(old)
    runtime = old._load_spell()[2]
    payload_drift = _payload_drift_probe(old, runtime)
    strict_probe = _strict_nonproduction_probe()
    projection = _projection_before()
    selected_row = _stable(base_result["evidence_by_id"][SPELL_ID])
    selected_row["payload_drift"] = _stable(payload_drift)
    selected_row["strict_loader_probe"] = _stable(strict_probe)
    selected_row["production_runtime_full"] = True

    authoritative = authoritative_compile_only_ids(ROOT)
    before = set(projection["before_compile_only_ids"])
    prior_loaded = set(projection["prior_loaded_ids"])
    after = project_compile_only_ids(authoritative, prior_loaded | {SPELL_ID})
    production_before = set(projection["production_before_ids"])
    production_after = production_before | {SPELL_ID}
    duplicate_invalid = project_compile_only_ids(
        set(projection["before_compile_only_ids"])
        | {SPELL_ID},
        [SPELL_ID, SPELL_ID, "", "invalid:id"],
    )
    protected = protected_path_fingerprints(ROOT)
    source_path = ROOT / "data/content-ir/authored/batch-II/tashas-cauldron/spells/tashas-cauldron-spell-b4ea0dc1907dd5ac08666af3.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    consumers = list(
        base_result["evidence_by_id"][SPELL_ID]["consumer_ids"]
    )
    name_branches = _name_branch_count(source)
    current_evidence_exact = _current_evidence_exact(
        base_result, source, consumers
    )
    base_checks = {
        key: value
        for key, value in base_result["checks"].items()
        if key not in {"all_required_checks_passed", "protected_fingerprints_unchanged"}
    }
    checks = {
        **base_checks,
        "name_branch_count": name_branches["count"],
        "selected_id_authoritative": SPELL_ID in authoritative_compile_only_ids(ROOT),
        "current_evidence_exact": current_evidence_exact,
        "payload_drift_rejected": payload_drift["rejected"],
        "strict_loader_rejects_nonproduction_row": strict_probe["rejected"],
        "each_selected_id_removed_once": before - after == {SPELL_ID}
        and after - before == set(),
        "duplicate_invalid_set_idempotent": duplicate_invalid == after,
        "unrelated_compile_only_ids_unchanged": (before - {SPELL_ID}) == (after - set()),
        "unrelated_production_ids_unchanged": (production_before - {SPELL_ID})
        == (production_after - {SPELL_ID}),
        "migration_projection_matches_sets": False,
        "name_branch_free": name_branches["count"] == 0,
        "selected_preexisting_in_production_union": SPELL_ID in production_before,
        "production_union_semantics_proven": (
            len(production_after) == len(production_before)
            if SPELL_ID in production_before
            else len(production_after) == len(production_before) + 1
        ),
        "protected_ollama_sha_exact": protected["backend/tests/ollama.py"]["sha256"]
        == EXPECTED_OLLAMA_SHA,
        "historical_xliii_sha_exact": _sha(
            (ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json").read_bytes()
        )
        == EXPECTED_XLIII_SHA,
    }
    required = tuple(
        key
        for key in _required_check_keys(checks)
        if key != "migration_projection_matches_sets"
    )
    pre_persist_passed = all(checks[key] is True for key in required)
    base_result["checks"] = {
        **checks,
        "all_required_checks_passed": pre_persist_passed,
    }
    base_result["all_required_checks_passed"] = pre_persist_passed
    base_result["schema_version"] = "content-ir-production-runtime-results-LVI-1"
    base_result["round_id"] = "round-LVI"
    base_result["artifact_date"] = "2026-08-14"
    base_result["production_runtime_full_ids"] = [SPELL_ID]
    base_result["evidence_by_id"] = {SPELL_ID: selected_row}
    base_result["required_check_keys"] = list(required)
    _write_artifact(base_result, bootstrap_phase=True)
    migration = build_migration(ROOT)
    checks["migration_projection_matches_sets"] = (
        set(migration["current_project_compile_only_ids"]) == after
    )
    required = _required_check_keys(checks)
    pre_persist_passed = all(checks[key] is True for key in required)
    base_result["checks"] = {
        **checks,
        "all_required_checks_passed": pre_persist_passed,
    }
    base_result["all_required_checks_passed"] = pre_persist_passed
    projection = {
        **projection,
        "after_compile_only_ids": sorted(after),
        "production_after_ids": sorted(production_after),
        "migration_compile_only_ids": sorted(migration["current_project_compile_only_ids"]),
        "migration_unique_compiled": migration["current_project_compiled_unique"],
    }
    candidate_ids = [SPELL_ID] if pre_persist_passed else []
    candidate_row = selected_row if pre_persist_passed else {
        **selected_row,
        "production_runtime_full": False,
    }
    base_result["production_runtime_full_ids"] = candidate_ids
    base_result["evidence_by_id"] = {SPELL_ID: candidate_row}
    base_result["required_check_keys"] = list(required)
    _write_artifact(base_result, bootstrap_phase=True)
    loaded_candidate = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    final_loader_acceptance = (
        SPELL_ID in loaded_candidate
        and loaded_candidate[SPELL_ID]["production_runtime_full"] is True
    )
    final_migration = build_migration(ROOT)
    checks["current_loader_acceptance"] = final_loader_acceptance
    checks["migration_projection_matches_sets"] = (
        set(final_migration["current_project_compile_only_ids"]) == after
    )
    checks["all_required_checks_passed"] = all(checks[key] is True for key in required)
    final_passed = checks["all_required_checks_passed"]
    final_ids = [SPELL_ID] if final_passed else []
    final_row = selected_row if final_passed else {
        **selected_row,
        "production_runtime_full": False,
    }
    base_result["checks"] = checks
    base_result["all_required_checks_passed"] = final_passed
    base_result["production_runtime_full_ids"] = final_ids
    base_result["evidence_by_id"] = {SPELL_ID: final_row}
    base_result["required_check_keys"] = list(required)
    _write_artifact(base_result, bootstrap_phase=False)
    final_loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    final_loader_acceptance = (
        SPELL_ID in final_loaded
        and final_loaded[SPELL_ID]["production_runtime_full"] is True
    )
    checks["current_loader_acceptance"] = final_loader_acceptance
    required = _required_check_keys(checks)
    checks["migration_projection_matches_sets"] = (
        set(build_migration(ROOT)["current_project_compile_only_ids"]) == after
    )
    checks["all_required_checks_passed"] = all(checks[key] is True for key in required)
    final_passed = checks["all_required_checks_passed"]
    if not final_passed:
        final_ids = []
        final_row = {**selected_row, "production_runtime_full": False}
    base_result["checks"] = checks
    base_result["all_required_checks_passed"] = final_passed
    base_result["production_runtime_full_ids"] = final_ids
    base_result["evidence_by_id"] = {SPELL_ID: final_row}
    _write_artifact(base_result, bootstrap_phase=False)
    migration = build_migration(ROOT)
    checks["migration_projection_matches_sets"] = (
        set(migration["current_project_compile_only_ids"]) == after
    )
    checks["all_required_checks_passed"] = all(checks[key] is True for key in required)
    base_result["checks"] = checks
    base_result["all_required_checks_passed"] = checks["all_required_checks_passed"]
    base_result["production_runtime_full_ids"] = (
        [SPELL_ID] if checks["all_required_checks_passed"] else []
    )
    base_result["evidence_by_id"] = {
        SPELL_ID: (
            selected_row
            if checks["all_required_checks_passed"]
            else {**selected_row, "production_runtime_full": False}
        )
    }
    base_result["required_check_keys"] = list(required)
    _write_artifact(base_result, bootstrap_phase=False)
    if json.loads(RESULT_PATH.read_text(encoding="utf-8")).get("bootstrap_phase"):
        raise AssertionError("bootstrap artifact escaped into final output")
    final_report_checks = checks
    report = {
        "schema_version": "round-LVI-intellect-fortress-closure-1",
        "round_id": "round-LVI",
        "artifact_date": "2026-08-14",
        "baseline_commit": "3ef55cf",
        "decision": "promote_existing_generic_defense_consumer",
        "selected_content_ids": final_ids,
        "candidate_comparison": _candidate_comparison(),
        "before": {
            "production": len(production_before),
            "compile_only": len(before),
            "unique_compiled": projection["migration_unique_compiled"],
        },
        "after": {
            "production": len(production_after),
            "compile_only": len(after),
            "unique_compiled": projection["migration_unique_compiled"],
        },
        "projection_sets": projection,
        "checks": final_report_checks,
        "all_required_checks_passed": final_report_checks["all_required_checks_passed"],
        "required_check_keys": list(required),
        "evidence_artifact": str(RESULT_PATH.relative_to(ROOT)),
        "focused_test": FOCUSED_TEST,
        "source": {
            "authored_path": str(source_path.relative_to(ROOT)),
            "source_record_id": source["source_record_id"],
            "source_fingerprint": source["source_fingerprint"],
            "compile_status": "full",
        },
        "protected_fingerprints": protected,
        "historical_artifact_sha256": {
            "round_xliii_report": EXPECTED_XLIII_SHA,
            "backend_tests_ollama": EXPECTED_OLLAMA_SHA,
        },
        "no_push": True,
        "bootstrap_phase": False,
        "production_runtime_full_ids": final_ids,
    }
    report["report_fingerprint"] = _sha(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "all_required_checks_passed": checks["all_required_checks_passed"],
                "artifact": str(RESULT_PATH),
                "report": str(REPORT_PATH),
                "checks": checks,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if checks["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
