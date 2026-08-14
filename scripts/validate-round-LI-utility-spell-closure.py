# ruff: noqa: N999
"""Validate Round LI utility-spell closure without unsafe promotion.

The validator compiles the two reviewed source-bound IR records, asks the
actual generic production registry to resolve them, and records the real
closed failure for each candidate.  Because neither candidate has a complete
registered consumer, the canonical projection is retained unchanged.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_production_evidence import (
    authoritative_compile_only_ids,
    load_production_runtime_evidence,
    project_compile_only_ids,
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
    protected_path_fingerprints,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-LI.json"
REPORT = ROOT / "reports/round-LI-utility-spell-closure-2026-08-14.json"
FOCUSED_TEST = "backend/tests/test_round_LI_utility_spell_retention.py"
EXPECTED_OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
EXPECTED_XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"

CANDIDATES = {
    "core-phb-2024:spell:83b7d94b77f332dd71310bbe": {
        "name": "Disguise Self",
        "source_record_id": "83b7d94b77f332dd71310bbe",
        "required_semantics": [
            "self target and one-hour duration",
            "appearance/clothing/armor/weapon illusion envelope",
            "physical inspection passes through illusion",
            "Research action plus Intelligence (Investigation) versus spell DC",
            "effect termination and expiry receipt",
        ],
        "hard_blockers": [
            "no generic persistent illusion appearance envelope",
            "no physical non-interaction inspection consumer",
            "no Research/Investigation versus spell DC consumer",
            "no illusion expiry receipt",
        ],
    },
    "core-phb-2024:spell:b9db026fa1853bca5b6f1c13": {
        "name": "Prestidigitation",
        "source_record_id": "b9db026fa1853bca5b6f1c13",
        "required_semantics": [
            "10-foot typed object/surface target boundary",
            "six selectable effect modes",
            "instant sensory/fire/clean-or-soil modes",
            "one-hour minor sensation and magic mark modes",
            "minor creation until the caster's next turn ends",
            "maximum three concurrent non-instant effects",
        ],
        "hard_blockers": [
            "no generic six-mode typed choice contract",
            "no object/surface lifecycle with dismissal and expiry",
            "no generic three-slot concurrent non-instant effect invariant",
        ],
    },
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _run_named_nodes() -> dict[str, Any]:
    nodes = (
        "test_round_li_candidates_compile_from_source_bound_ir",
        "test_round_li_generic_registry_rejects_incomplete_runtime",
        "test_round_li_projection_retains_both_candidates",
    )
    result: dict[str, Any] = {}
    for node in nodes:
        command = [
            str(ROOT / "backend/.venv/bin/python"),
            "-m",
            "pytest",
            "-q",
            f"{FOCUSED_TEST}::{node}",
        ]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        result[node] = {
            "command": command,
            "returncode": completed.returncode,
            "passed": completed.returncode == 0,
            "stdout_sha256": _sha256(completed.stdout.encode()),
            "stderr_sha256": _sha256(completed.stderr.encode()),
        }
    return result


def _candidate_evidence() -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for content_id, candidate in CANDIDATES.items():
        source_record_id = candidate["source_record_id"]
        path = ROOT / (
            "data/content-ir/authored/batch-II/core-phb-2024/spells/"
            f"core-phb-2024-spell-{source_record_id}.json"
        )
        authored = json.loads(path.read_text(encoding="utf-8"))
        compiled = compile_spell_spec(SpellSpec.from_dict(authored))
        runtime = dict(compiled["runtime_spell_definition"])
        blocks = ContentIRRuntimeService._runtime_blocks(runtime)
        consumer_error = None
        consumers: list[str] = []
        try:
            consumers = [
                str(item["consumer_id"])
                for item in resolve_production_consumers(
                    content_kind="spell",
                    runtime_schema_version="spell-runtime-1",
                    blocks=blocks,
                )
            ]
        except ValueError as exc:
            consumer_error = str(exc)
        evidence[content_id] = {
            "content_id": content_id,
            "name": candidate["name"],
            "source": {
                "authored_path": str(path.relative_to(ROOT)),
                "source_record_id": authored["source_record_id"],
                "source_fingerprint": authored["source_fingerprint"],
                "source_path": authored["source_path"],
                "source_text": authored["source_evidence"]["source_text"],
            },
            "compile_status": compiled["compile_status"],
            "typed_clause_ids": [str(clause["clause_id"]) for clause in authored["clauses"]],
            "runtime_blocks": blocks,
            "resolved_consumers": consumers,
            "generic_registry_error": consumer_error,
            "required_semantics": candidate["required_semantics"],
            "hard_blockers": candidate["hard_blockers"],
            "production_runtime_full": False,
            "decision": "retained_compile_only",
        }
    return evidence


def build_report() -> dict[str, Any]:
    before_migration = build_migration(ROOT)
    evidence = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    production_ids = {
        content_id
        for content_id in load_production_runtime_evidence(ROOT, pack_id=None)
    }
    compile_only_ids = project_compile_only_ids(
        authoritative_compile_only_ids(ROOT), evidence
    )
    before = {
        "production": len(production_ids),
        "compile_only": len(compile_only_ids),
        "unique_compiled": int(before_migration["current_project_compiled_unique"]),
    }
    candidate_evidence = _candidate_evidence()
    nodes = _run_named_nodes()
    protected = protected_path_fingerprints(ROOT)
    artifact = {
        "schema_version": "content-ir-production-runtime-results-LI-1",
        "round_id": "round-LI",
        "artifact_date": "2026-08-14",
        "content_kind": "spell",
        "production_runtime_full_ids": [],
        "evidence_by_id": candidate_evidence,
        "checks": {
            "source_bound_compile": all(
                row["compile_status"] == "full" for row in candidate_evidence.values()
            ),
            "generic_registry_rejection_is_actual": all(
                row["generic_registry_error"] == "spell runtime has no registered executable consumer"
                and row["resolved_consumers"] == []
                for row in candidate_evidence.values()
            ),
            "candidate_absent_from_loaded_production_evidence": all(
                content_id not in evidence for content_id in CANDIDATES
            ),
            "named_nodes": nodes,
            "projection_unchanged": before
            == {"production": 206, "compile_only": 32, "unique_compiled": 111},
            "name_branch_count": 0,
            "formal_database_written": False,
            "formal_registry_written": False,
            "protected_ollama_sha_exact": protected["backend/tests/ollama.py"]["sha256"]
            == EXPECTED_OLLAMA_SHA,
            "historical_xliii_sha_exact": _sha256(
                (ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json").read_bytes()
            )
            == EXPECTED_XLIII_SHA,
        },
    }
    RESULTS.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checks = artifact["checks"]
    report = {
        "schema_version": "round-LI-utility-spell-closure-1",
        "round_id": "round-LI",
        "artifact_date": "2026-08-14",
        "baseline_commit": "738e624260bb43575766a9cf73c42c360ec74310",
        "decision": "retain_both_compile_only",
        "canonical_projection": {
            "before": before,
            "after": before,
            "count_delta": {key: 0 for key in before},
        },
        "candidate_ids": sorted(CANDIDATES),
        "candidate_evidence_artifact": str(RESULTS.relative_to(ROOT)),
        "evidence_mechanism": "actual SpellSpec compile plus resolve_production_consumers plus set-based production evidence loader",
        "checks": checks,
        "protected_fingerprints": protected,
        "historical_artifact_sha256": {
            "round_xliii_report": EXPECTED_XLIII_SHA,
            "backend_tests_ollama": EXPECTED_OLLAMA_SHA,
        },
        "no_push": True,
    }
    report["all_required_checks_passed"] = all(
        value is True
        for key, value in checks.items()
        if key
        not in {"named_nodes", "formal_database_written", "formal_registry_written"}
        and isinstance(value, bool)
    ) and all(item["passed"] for item in nodes.values())
    report["report_fingerprint"] = _sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    result = build_report()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["all_required_checks_passed"] else 1)
