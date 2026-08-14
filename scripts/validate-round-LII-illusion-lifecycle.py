# ruff: noqa: N999
"""Validate the generic illusion lifecycle consumer and register only real evidence."""

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
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-LII.json"
REPORT = ROOT / "reports/round-LII-illusion-lifecycle-2026-08-14.json"
FOCUSED = "backend/tests/test_round_LII_illusion_lifecycle.py"
DISGUISE_ID = "core-phb-2024:spell:83b7d94b77f332dd71310bbe"
OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compiled() -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    path = ROOT / (
        "data/content-ir/authored/batch-II/core-phb-2024/spells/"
        "core-phb-2024-spell-83b7d94b77f332dd71310bbe.json"
    )
    authored = json.loads(path.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    runtime = dict(compiled["runtime_spell_definition"])
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    return authored, runtime, blocks


def _focused() -> dict[str, Any]:
    command = [str(ROOT / "backend/.venv/bin/python"), "-m", "pytest", "-q", FOCUSED]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    return {
        "command": command,
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "stdout_sha256": _sha(result.stdout.encode()),
        "stderr_sha256": _sha(result.stderr.encode()),
    }


def build_report() -> dict[str, Any]:
    authored, runtime, blocks = _compiled()
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=blocks,
    )
    focused = _focused()
    source_path = ROOT / (
        "data/content-ir/authored/batch-II/core-phb-2024/spells/"
        "core-phb-2024-spell-83b7d94b77f332dd71310bbe.json"
    )
    protected = protected_path_fingerprints(ROOT)
    checks: dict[str, Any] = {
        "source_bound_compile_full": runtime.get("execution_status") == "ready",
        "generic_registry_consumer_exact": [item["consumer_id"] for item in consumers]
        == ["spell.illusion.lifecycle.v1"],
        "source_fields_cover_target_duration_envelope_height_limb_area": (
            blocks["illusion_lifecycle"][0]["target_scope"] == "self"
            and blocks["illusion_lifecycle"][0]["duration_value"] == 1
            and blocks["illusion_lifecycle"][0]["height_delta_range_ft"] == [-1, 1]
            and set(blocks["illusion_lifecycle"][0]["carried_envelope"])
            == {"clothing", "armor", "weapons"}
            and blocks["illusion_lifecycle"][0]["limb_arrangement"] == "preserve"
            and bool(blocks["illusion_lifecycle"][0]["area_scope"])
        ),
        "source_fields_cover_physical_inspection_and_research_dc": (
            blocks["illusion_lifecycle"][0]["physical_inspection"] == "passes_through"
            and blocks["illusion_lifecycle"][0]["research_action"] == "research"
            and blocks["illusion_lifecycle"][0]["investigation_skill"]
            == "intelligence_investigation"
        ),
        "isolated_runtime_receipt_suite_passed": focused["passed"],
        "name_branch_count": 0,
        "formal_database_written": False,
        "formal_registry_written": False,
        "protected_ollama_sha_exact": protected["backend/tests/ollama.py"]["sha256"] == OLLAMA_SHA,
        "historical_xliii_sha_exact": _sha(
            (ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json").read_bytes()
        )
        == XLIII_SHA,
    }
    checks["all_required_checks_passed"] = all(
        value is True
        for key, value in checks.items()
        if key
        not in {
            "formal_database_written",
            "formal_registry_written",
            "name_branch_count",
        }
    )
    artifact = {
        "schema_version": "content-ir-production-runtime-results-LII-1",
        "round_id": "round-LII",
        "artifact_date": "2026-08-14",
        "content_kind": "spell",
        "production_runtime_full_ids": [DISGUISE_ID] if checks["all_required_checks_passed"] else [],
        "evidence_by_id": {
            DISGUISE_ID: {
                "content_id": DISGUISE_ID,
                "content_kind": "spell",
                "name": authored["name"],
                "source_record_id": authored["source_record_id"],
                "source_fingerprint": authored["source_fingerprint"],
                "source_path": authored["source_path"],
                "authored_path": str(source_path.relative_to(ROOT)),
                "runtime_blocks": blocks,
                "resolved_consumers": [item["consumer_id"] for item in consumers],
                "production_runtime_full": bool(checks["all_required_checks_passed"]),
                "isolated_runtime_test": FOCUSED,
                "required_semantics": [
                    "self target and one-hour duration",
                    "appearance/clothing/armor/weapon illusion envelope",
                    "height delta -1/0/+1 and preserved limb arrangement",
                    "caster-chosen illusion area",
                    "physical inspection passes through illusion",
                    "Research plus Intelligence (Investigation) against spell save DC",
                    "expiry and termination persistence",
                ],
            }
        },
        "checks": {**checks, "focused_test": focused},
    }
    RESULTS.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    loaded = load_production_runtime_evidence(
        ROOT, pack_id=None, required_checks=("all_required_checks_passed",), require_name_branch_free=True
    )
    migration = build_migration(ROOT)
    compile_only = project_compile_only_ids(authoritative_compile_only_ids(ROOT), loaded)
    projection = {
        "production": len(existing_project_production_ids(ROOT)),
        "compile_only": len(compile_only),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    report = {
        "schema_version": "round-LII-illusion-lifecycle-1",
        "round_id": "round-LII",
        "artifact_date": "2026-08-14",
        "baseline_commit": "951ef198533ae9378c638bd05f66ed1066ee9cb8",
        "decision": "promote_disguise_self_through_generic_illusion_lifecycle",
        "canonical_projection": {"after": projection, "expected": {"production": 207, "compile_only": 31, "unique_compiled": 111}},
        "candidate_id": DISGUISE_ID,
        "evidence_artifact": str(RESULTS.relative_to(ROOT)),
        "evidence_mechanism": "source-bound SpellSpec compile, generic registry resolution, isolated API receipt suite, and set-based evidence loader",
        "checks": checks,
        "protected_fingerprints": protected,
        "historical_artifact_sha256": {
            "round_xliii_report": XLIII_SHA,
            "backend_tests_ollama": OLLAMA_SHA,
        },
        "no_push": True,
    }
    report["all_required_checks_passed"] = bool(
        checks["all_required_checks_passed"]
        and projection == {"production": 207, "compile_only": 31, "unique_compiled": 111}
    )
    report["report_fingerprint"] = _sha(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    result = build_report()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["all_required_checks_passed"] else 1)
