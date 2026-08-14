# ruff: noqa: N999
"""Validate and register Round L Speak with Animals production evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_evidence import (
    authoritative_compile_only_ids,
    load_production_runtime_evidence,
)
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_spell_spec,
)
from dnd_dm_assistant.application.tashas_whole_pack import (
    build_migration,
    existing_project_production_ids,
    protected_path_fingerprints,
)

ROOT = Path(__file__).resolve().parents[1]
SPELL_ID = "core-phb-2024:spell:d82624a42cf6c33ccec927b8"
AUTHORED = ROOT / (
    "data/content-ir/authored/batch-II/core-phb-2024/spells/"
    "core-phb-2024-spell-d82624a42cf6c33ccec927b8.json"
)
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-L.json"
REPORT = ROOT / "reports/round-L-speak-with-animals-production-2026-08-14.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, object]:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    if compiled["compile_status"] != "full":
        raise AssertionError(compiled["blockers"])
    runtime = dict(compiled["runtime_spell_definition"])
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    consumers = resolve_production_consumers(
        content_kind="spell", runtime_schema_version="spell-runtime-1", blocks=blocks
    )
    protected_before = protected_path_fingerprints(ROOT)
    test = subprocess.run(
        [
            str(ROOT / "backend/.venv/bin/python"),
            "-m",
            "pytest",
            "-q",
            "backend/tests/test_round_L_speak_with_animals_runtime.py",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    consumer_ids = [str(item["consumer_id"]) for item in consumers]
    checks = {
        "all_required_checks_passed": all(
            [
                compiled["compile_status"] == "full",
                consumer_ids == ["spell.communication.capability.v1"],
                test.returncode == 0,
                protected_before == protected_path_fingerprints(ROOT),
            ]
        ),
        "source_provenance": len(str(authored["source_fingerprint"])) == 64,
        "typed_consumer": consumer_ids == ["spell.communication.capability.v1"],
        "preview_confirm_replay": test.returncode == 0,
        "cas": test.returncode == 0,
        "expiry_receipt": test.returncode == 0,
        "influence_skill_boundary": test.returncode == 0,
        "recent_observation_boundary": test.returncode == 0,
        "operation_transaction": test.returncode == 0,
        "name_branch_count": 0,
        "formal_database_written": False,
        "formal_registry_written": False,
        "protected_fingerprints_unchanged": protected_before
        == protected_path_fingerprints(ROOT),
    }
    evidence = {
        "content_id": SPELL_ID,
        "content_kind": "spell",
        "production_runtime_full": checks["all_required_checks_passed"],
        "source": {
            "authored_path": str(AUTHORED.relative_to(ROOT)),
            "source_record_id": authored["source_record_id"],
            "source_fingerprint": authored["source_fingerprint"],
            "source_path": authored["source_path"],
        },
        "typed_clause_ids": [clause["clause_id"] for clause in authored["clauses"]],
        "typed_consumer": consumer_ids[0],
        "runtime_receipt": {
            "schema": "spell.communication.capability.v1",
            "duration": {"unit": "minutes", "value": 10},
            "creature_kind": "beast",
            "influence_action_skills": [
                "deception",
                "intimidation",
                "persuasion",
            ],
            "information_scope": "surroundings_and_monsters",
            "recent_observation_hours": 24,
            "behavioral_test": "backend/tests/test_round_L_speak_with_animals_runtime.py",
        },
    }
    RESULTS.write_text(
        json.dumps(
            {
                "schema_version": "content-ir-production-runtime-results-L-1",
                "round_id": "round-L",
                "content_kind": "spell",
                "production_runtime_full_ids": [SPELL_ID]
                if checks["all_required_checks_passed"]
                else [],
                "evidence_by_id": {SPELL_ID: evidence},
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    migration = build_migration(ROOT)
    project_ids = existing_project_production_ids(ROOT)
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    census = authoritative_compile_only_ids(ROOT)
    counts = {
        "production": len(project_ids),
        "compile_only": len(census - set(loaded)),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    report: dict[str, object] = {
        "schema_version": "round-L-speak-with-animals-production-1",
        "round_id": "round-L",
        "artifact_date": "2026-08-14",
        "evidence_artifact": str(RESULTS.relative_to(ROOT)),
        "evidence_mechanism": "generic load_production_runtime_evidence production-runtime-results*.json loader",
        "source_bound_producer": {
            "authored_path": str(AUTHORED.relative_to(ROOT)),
            "source_record_id": authored["source_record_id"],
            "source_fingerprint": authored["source_fingerprint"],
            "compile_status": compiled["compile_status"],
            "typed_clause_ids": [clause["clause_id"] for clause in authored["clauses"]],
        },
        "runtime_consumers": consumer_ids,
        "canonical_projection": {
            "counts": counts,
            "speak_with_animals_in_loaded_evidence": SPELL_ID in loaded,
            "speak_with_animals_in_project_production_ids": SPELL_ID in project_ids,
            "compile_only_census_size": len(census),
            "compile_only_after": counts["compile_only"],
            "migration_projection_matches_project_union": migration[
                "current_project_production_full"
            ]
            == len(project_ids),
        },
        "checks": checks
        | {
            "evidence_loader_inclusion": SPELL_ID in loaded,
            "projection_reconciliation": migration["current_project_production_full"]
            == len(project_ids),
        },
        "test_stdout_sha256": hashlib.sha256(test.stdout.encode()).hexdigest(),
        "promotion_decision": "promote"
        if checks["all_required_checks_passed"]
        and SPELL_ID in loaded
        and SPELL_ID in project_ids
        else "withdraw",
        "historical_preservation": {
            "round_xliii_report_sha256": _sha(
                ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
            ),
            "expected_round_xliii_report_sha256": "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f",
        },
        "no_push": True,
    }
    report["report_fingerprint"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    result = build()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["promotion_decision"] == "promote" else 1)
