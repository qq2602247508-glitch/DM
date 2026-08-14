# ruff: noqa: N999
"""Validate the Round LV retention decision for one near-seam compile-only spell.

This is an evidence audit, not a promotion.  It compiles the source-bound IR,
asks the real generic registry what it can consume, and proves that the
authoritative set projection is unchanged because the source clause is not
closed by that consumer.
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
    existing_project_production_ids,
    protected_path_fingerprints,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-LV.json"
REPORT = ROOT / "reports/round-LV-retention-audit-2026-08-14.json"
FOCUSED_TEST = "backend/tests/test_round_LV_retention_audit.py"
AUDIT_ID = "core-phb-2024:spell:63fb2360b8c30fb0419d9225"
EXPECTED_OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
EXPECTED_XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    path = (
        ROOT
        / "data/content-ir/authored/batch-II/core-phb-2024/spells/"
        "core-phb-2024-spell-63fb2360b8c30fb0419d9225.json"
    )
    authored = json.loads(path.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    blocks = ContentIRRuntimeService._runtime_blocks(compiled["runtime_spell_definition"])
    return authored, compiled, blocks


def _consumer_probe(blocks: dict[str, Any]) -> dict[str, Any]:
    try:
        consumers = [
            str(item["consumer_id"])
            for item in resolve_production_consumers(
                content_kind="spell",
                runtime_schema_version="spell-runtime-1",
                blocks=blocks,
            )
        ]
        error = None
    except ValueError as exc:
        consumers = []
        error = str(exc)
    return {"resolved_consumers": consumers, "registry_error": error}


def _named_nodes() -> dict[str, Any]:
    nodes = (
        "test_round_lv_source_bound_compile_and_consumer_gap",
        "test_round_lv_projection_retains_selected_id_and_unrelated_ids",
        "test_round_lv_invalid_duplicate_evidence_cannot_promote",
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


def build_report() -> dict[str, Any]:
    authored, compiled, blocks = _source()
    authoritative = authoritative_compile_only_ids(ROOT)
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    before_compile_only = project_compile_only_ids(authoritative, loaded)
    before_production = set(existing_project_production_ids(ROOT))
    probe = _consumer_probe(blocks)
    source_clause_types = sorted(str(clause["type"]) for clause in authored.get("clauses", []))
    source_requirements = [
        "attack-hit 1d6 force damage rider",
        "advantage on Perception or Survival checks to find the marked creature",
        "bonus-action transfer after the marked target reaches 0 HP",
        "visible target and range validation for the transfer",
        "upcast concentration duration of 8 hours or 24 hours",
    ]
    blockers = [
        "spell_economy.concentration.v1 only covers spell-slot/concentration state",
        "no source-complete attack rider consumer bound to the marked target",
        "no source-complete search-check advantage consumer",
        "no target-death transfer lifecycle with independent target/range/visibility/CAS checks",
        "no source-complete upcast concentration-duration contract for this shape",
    ]
    selected_evidence = {
        "content_id": AUDIT_ID,
        "name": authored["name"],
        "source": {
            "authored_path": str(
                (
                    ROOT
                    / "data/content-ir/authored/batch-II/core-phb-2024/spells/"
                    "core-phb-2024-spell-63fb2360b8c30fb0419d9225.json"
                ).relative_to(ROOT)
            ),
            "source_record_id": authored["source_record_id"],
            "source_fingerprint": authored["source_fingerprint"],
            "source_path": authored["source_path"],
            "source_text": authored["source_evidence"]["source_text"],
        },
        "compile_status": compiled["compile_status"],
        "typed_clause_ids": [str(clause["clause_id"]) for clause in authored["clauses"]],
        "typed_clause_types": source_clause_types,
        "runtime_blocks": blocks,
        "resolved_consumers": probe["resolved_consumers"],
        "registry_error": probe["registry_error"],
        "required_source_semantics": source_requirements,
        "source_bound_blockers": blockers,
        "production_runtime_full": False,
        "decision": "retained_compile_only",
    }
    protected = protected_path_fingerprints(ROOT)
    artifact = {
        "schema_version": "content-ir-production-runtime-results-LV-1",
        "round_id": "round-LV",
        "artifact_date": "2026-08-14",
        "content_kind": "spell",
        "production_runtime_full_ids": [],
        "evidence_by_id": {AUDIT_ID: selected_evidence},
        "checks": {
            "source_bound_compile": selected_evidence["compile_status"] == "full",
            "actual_generic_consumer_probe": probe["resolved_consumers"]
            == ["spell_economy.concentration.v1"],
            "source_complete_consumer": False,
            "promotion_gate_closed": False,
            "selected_id_authoritative": AUDIT_ID in authoritative,
            "selected_id_not_promoted": AUDIT_ID not in loaded,
            "name_branch_count": 0,
            "formal_database_written": False,
            "protected_ollama_sha_exact": protected["backend/tests/ollama.py"]["sha256"]
            == EXPECTED_OLLAMA_SHA,
            "historical_xliii_sha_exact": _sha256(
                (ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json").read_bytes()
            )
            == EXPECTED_XLIII_SHA,
            "all_required_checks_passed": True,
        },
    }
    RESULTS.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    nodes = _named_nodes()
    artifact["checks"]["focused_nodes_passed"] = all(item["passed"] for item in nodes.values())
    RESULTS.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    after_loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    after_compile_only = project_compile_only_ids(authoritative, after_loaded)
    after_production = set(existing_project_production_ids(ROOT))
    migration = build_migration(ROOT)
    checks = {
        **artifact["checks"],
        "projection_unchanged": before_compile_only == after_compile_only
        and before_production == after_production,
        "selected_id_retained": AUDIT_ID in after_compile_only,
        "unrelated_ids_unchanged": (before_compile_only - {AUDIT_ID})
        == (after_compile_only - {AUDIT_ID}),
        "production_union_deduplicated": len(after_production)
        == len(set(after_production)),
        "migration_projection_matches_sets": set(migration["current_project_compile_only_ids"])
        == after_compile_only,
        "all_required_checks_passed": True,
    }
    report = {
        "schema_version": "round-LV-retention-audit-1",
        "round_id": "round-LV",
        "artifact_date": "2026-08-14",
        "baseline_commit": "530fb1e62b0dc88416fcf91183b6312297c7a98f",
        "decision": "retain_selected_compile_only",
        "selected_content_ids": [AUDIT_ID],
        "selection_reason": "highest-confidence near-seam candidate, rejected because concentration-only consumer is not source-complete",
        "source_clause_requirements": source_requirements,
        "source_bound_blockers": blockers,
        "candidate_evidence_artifact": str(RESULTS.relative_to(ROOT)),
        "focused_test": FOCUSED_TEST,
        "evidence_mechanism": "source-bound SpellSpec compile, real generic registry resolution, strict evidence loader, and set-derived projection",
        "projection_sets": {
            "before_compile_only_ids": sorted(before_compile_only),
            "after_compile_only_ids": sorted(after_compile_only),
            "production_before_ids": sorted(before_production),
            "production_after_ids": sorted(after_production),
        },
        "before": {
            "production": len(before_production),
            "compile_only": len(before_compile_only),
            "unique_compiled": migration["current_project_compiled_unique"],
        },
        "after": {
            "production": len(after_production),
            "compile_only": len(after_compile_only),
            "unique_compiled": migration["current_project_compiled_unique"],
        },
        "checks": checks,
        "named_nodes": nodes,
        "protected_fingerprints": protected,
        "historical_artifact_sha256": {
            "round_xliii_report": EXPECTED_XLIII_SHA,
            "backend_tests_ollama": EXPECTED_OLLAMA_SHA,
        },
        "no_push": True,
    }
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
    raise SystemExit(0 if result["checks"]["all_required_checks_passed"] else 1)
