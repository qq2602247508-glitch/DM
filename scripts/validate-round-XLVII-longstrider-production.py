# ruff: noqa: N999
"""Validate Round XLVII without inventing a promotion or behavioral evidence."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

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
)

ROOT = Path(__file__).resolve().parents[1]
SPELL_ID = "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb"
AUTHORED = ROOT / "data/content-ir/authored/batch-II/core-phb-2024/spells/core-phb-2024-spell-6f5b6f21ffa22e705a9bd6cb.json"
BASELINE = ROOT / "reports/round-XLVI-typed-spell-communication-route-2026-08-13.json"
REPORT = ROOT / "reports/round-XLVII-longstrider-production-2026-08-13.json"

BEHAVIORAL_NODES = {
    "base_target": "backend/tests/test_round_XLVII_longstrider_runtime.py::test_longstrider_source_bound_runtime_preview_confirm_replay_and_receipt",
    "upcast_fanout": "backend/tests/test_round_XLVII_longstrider_runtime.py::test_longstrider_source_bound_runtime_preview_confirm_replay_and_receipt",
    "willing_target_rejection": "backend/tests/test_round_XLVII_longstrider_runtime.py::test_longstrider_rejects_unwilling_target_and_payload_drift",
    "payload_drift": "backend/tests/test_round_XLVII_longstrider_runtime.py::test_longstrider_rejects_unwilling_target_and_payload_drift",
    "stale_cas": "backend/tests/test_round_XLVII_longstrider_runtime.py::test_longstrider_rejects_stale_target_cas_and_wrong_slot",
    "typed_registry": "backend/tests/test_round_XLVII_longstrider_runtime.py::test_longstrider_registry_and_compiled_source_are_typed",
    "contract_rejections": "backend/tests/test_typed_spell_timed_modifiers.py::test_timed_spell_modifier_fails_closed",
    "expiry": "backend/tests/test_typed_spell_timed_modifiers.py::test_timed_spell_modifier_persists_source_bound_expiry_and_replaces_same_source",
    "same_source_replacement": "backend/tests/test_typed_spell_timed_modifiers.py::test_timed_spell_modifier_persists_source_bound_expiry_and_replaces_same_source",
    "api_contract_rejections": "backend/tests/test_round_XLVII_longstrider_runtime.py::test_longstrider_rejects_wrong_runtime_cardinality_range_and_actor_cas",
    "api_all_target_cas_expiry": "backend/tests/test_round_XLVII_longstrider_runtime.py::test_longstrider_rejects_all_target_stale_cas_and_expires_existing_modifier",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_node(node: str) -> dict[str, Any]:
    command = [str(ROOT / "backend/.venv/bin/python"), "-m", "pytest", "-q", node]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "node": node,
        "command": command,
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def focused() -> dict[str, Any]:
    command = [
        str(ROOT / "backend/.venv/bin/python"),
        "-m",
        "pytest",
        "-q",
        "backend/tests/test_round_XLVII_longstrider_runtime.py",
        "backend/tests/test_typed_spell_timed_modifiers.py",
        "backend/tests/test_typed_spell_targets.py",
        "backend/tests/test_content_ir_production_closure.py",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    match = re.search(r"(\d+)\s+passed", f"{result.stdout}\n{result.stderr}")
    if match is None and result.returncode == 0:
        match = re.search(r"(?m)^(\.+)\s+\[\s*100%\]\s*$", result.stdout)
    return {
        "command": command,
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "passed_count": (
            int(match.group(1))
            if match and match.group(1).isdigit()
            else len(match.group(1))
            if match
            else 0
        ),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def canonical_counts() -> dict[str, int]:
    migration = build_migration(ROOT)
    production_ids = existing_project_production_ids(ROOT)
    return {
        "production": len(production_ids),
        "compile_only": int(migration["current_project_compile_only"]),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }


def build() -> dict[str, Any]:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    runtime = compiled["runtime_spell_definition"]
    assert isinstance(runtime, dict)
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    consumers = resolve_production_consumers(
        content_kind="spell", runtime_schema_version="spell-runtime-1", blocks=blocks
    )
    counts = canonical_counts()
    nodes = {name: run_node(node) for name, node in BEHAVIORAL_NODES.items()}
    focused_result = focused()
    source_text = authored["source_evidence"]["source_text"]
    required = ["你触碰一个生物", "速度增加10尺", "持续时间", "1 小时", "额外指定一个目标"]
    promoted = SPELL_ID in existing_project_production_ids(ROOT)
    coverage = {
        "base_target": nodes["base_target"]["passed"],
        "upcast_fanout": nodes["upcast_fanout"]["passed"],
        "willing_target_rejection": nodes["willing_target_rejection"]["passed"],
        "wrong_source_target_slot_duration_modifier_rejection": nodes["api_contract_rejections"][
            "passed"
        ],
        "expiry": nodes["api_all_target_cas_expiry"]["passed"],
        "same_source_replacement": nodes.get("same_source_replacement", {}).get(
            "passed", False
        ),
        "stale_cas": nodes["stale_cas"]["passed"],
        "exact_replay": nodes["base_target"]["passed"],
        "payload_drift": nodes["payload_drift"]["passed"],
        "transaction_receipt": nodes["base_target"]["passed"],
    }
    report = {
        "schema_version": "round-XLVII-longstrider-production-2",
        "round_id": "round-XLVII",
        "artifact_date": "2026-08-13",
        "baseline": {"path": str(BASELINE.relative_to(ROOT)), "sha256": sha(BASELINE)},
        "authoritative_counts": counts,
        "after": {
            "canonical_projection_counts": counts,
            "promoted_ids": [SPELL_ID] if promoted else [],
            "retained_compile_only_ids": [] if promoted else [SPELL_ID],
        },
        "source_bound_producer": {
            "authored_path": str(AUTHORED.relative_to(ROOT)),
            "source_fingerprint": authored["source_fingerprint"],
            "source_text_terms_present": {term: term in source_text for term in required},
            "typed_clause_types": [item["type"] for item in authored["clauses"]],
            "compile_status": compiled["compile_status"],
            "runtime_schema": runtime["runtime_schema_version"],
        },
        "runtime_consumers": [item["consumer_id"] for item in consumers],
        "behavioral_coverage": coverage,
        "behavioral_nodes": nodes,
        "focused_tests": focused_result,
        "promotion_decision": "promote" if promoted and all(coverage.values()) else "withdraw",
        "promotion_blockers": [
            "Longstrider is absent from the authoritative production evidence union"
            if not promoted
            else "",
            "expiry and same-source replacement have no direct passing API/runtime node"
            if not (coverage["expiry"] and coverage["same_source_replacement"])
            else "",
            "wrong source/target/duration/modifier rejection lacks a direct passing node"
            if not coverage["wrong_source_target_slot_duration_modifier_rejection"]
            else "",
        ],
        "no_push": True,
    }
    report["report_fingerprint"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return report


if __name__ == "__main__":
    value = build()
    REPORT.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if value["focused_tests"]["passed"] else 1)
