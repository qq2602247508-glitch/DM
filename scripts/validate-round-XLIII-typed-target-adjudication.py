# ruff: noqa: N999
"""Audit the Round XLIII typed target/adjudication seam and five spell candidates.

This validator is deliberately a no-promotion audit.  It derives the current
canonical counts from the existing projection and emits an evidence artifact
without editing production registries or formal campaign data.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
BASELINE_PATH = ROOT / "reports/content-ir-runtime-level-audit-IV-2026-08-11.json"

CANDIDATES: dict[str, dict[str, Any]] = {
    "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb": {
        "name": "Longstrider",
        "source_record_id": "6f5b6f21ffa22e705a9bd6cb",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/6f5b6f21ffa22e705a9bd6cb.md",
        "required_semantics": [
            "touch single-or-upcast-multiple creature targets",
            "speed +10 ft modifier",
            "1-hour persistence and expiry",
            "upcast target fan-out",
            "replacement/stacking behavior",
        ],
        "blockers": [
            "no spell modifier effect consumer persists speed_ft +10 on selected targets",
            "no generic expiry/replacement path proves this modifier lifecycle",
            "no upcast target fan-out contract is represented in the compiled runtime",
        ],
    },
    "core-phb-2024:spell:83b7d94b77f332dd71310bbe": {
        "name": "Disguise Self",
        "source_record_id": "83b7d94b77f332dd71310bbe",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/83b7d94b77f332dd71310bbe.md",
        "required_semantics": [
            "self target and 1-hour duration",
            "appearance/clothing/armor/weapon illusion bounds",
            "physical inspection passes through illusion",
            "research action plus Intelligence (Investigation) vs spell DC",
            "effect termination",
        ],
        "blockers": [
            "no persisted illusion appearance envelope or physical-inspection behavior",
            "no research-action/check consumer bound to the spell DC",
            "no illusion expiry receipt",
        ],
    },
    "core-phb-2024:spell:b9db026fa1853bca5b6f1c13": {
        "name": "Prestidigitation",
        "source_record_id": "b9db026fa1853bca5b6f1c13",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/b9db026fa1853bca5b6f1c13.md",
        "required_semantics": [
            "10-foot typed object/surface target boundary",
            "six selectable effect modes",
            "instant modes",
            "one-hour minor sensation and mark modes",
            "next-turn-end minor creation expiry",
            "maximum three concurrent non-instant effects",
        ],
        "blockers": [
            "no generic effect-mode choice contract for all six modes",
            "no object/surface persistence and dismissal/expiry consumer",
            "no three-slot concurrent-effect lifecycle",
        ],
    },
    "core-phb-2024:spell:d82624a42cf6c33ccec927b8": {
        "name": "Speak with Animals",
        "source_record_id": "d82624a42cf6c33ccec927b8",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/d82624a42cf6c33ccec927b8.md",
        "required_semantics": [
            "self target",
            "10-minute duration",
            "understand and communicate with beasts",
            "all skill options for Influence actions against beasts",
            "limited information scope and recent-observation boundary",
        ],
        "blockers": [
            "no time-bounded communication capability effect",
            "no beast-scope Influence skill-option consumer",
            "no recent-observation information boundary receipt",
        ],
    },
    "core-phb-2024:spell:dd9cb25c63b7e13194c7d01c": {
        "name": "Message",
        "source_record_id": "dd9cb25c63b7e13194c7d01c",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/dd9cb25c63b7e13194c7d01c.md",
        "required_semantics": [
            "120-foot single visible/familiar target",
            "solid barrier and material thickness rules",
            "magical silence blocking",
            "only target hears",
            "private reply channel",
            "instant effect",
        ],
        "blockers": [
            "no communication-path consumer for visibility/familiarity/material barriers",
            "no private reply-channel persistence/receipt",
            "no magical-silence interaction check",
        ],
    },
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprint(value: object) -> str:
    return _sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )


def _protected() -> dict[str, str]:
    paths = sorted(
        path
        for path in (ROOT / "backend/tests/integrations").rglob("*")
        if path.is_file()
    )
    manifest = [
        {"path": str(path.relative_to(ROOT)), "sha256": _sha256_bytes(path.read_bytes())}
        for path in paths
    ]
    return {
        "integrations_manifest": _fingerprint(manifest),
        "ollama": _sha256_bytes((ROOT / "backend/tests/ollama.py").read_bytes()),
    }


def _canonical_counts() -> dict[str, int]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["baseline"]
    return {
        "production": int(baseline["production_full"]),
        "compile_only": int(baseline["compile_only"]),
        "unique_compiled": int(baseline["unique_compiled"]),
    }


def _source_matrix() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    historical_matrix = json.loads(REPORT_PATH.read_text(encoding="utf-8")).get(
        "source_boundary_matrix", {}
    )
    for content_id, spec in CANDIDATES.items():
        source_path = ROOT / spec["source_file"]
        compiled_path = ROOT / (
            "data/content-ir/compiled/batch-II/typed-ir/core-phb-2024/spells/"
            f"core-phb-2024-spell-{spec['source_record_id']}.json"
        )
        source_text = source_path.read_text(encoding="utf-8")
        compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
        historical = historical_matrix.get(content_id, {})
        result[content_id] = {
            "content_id": content_id,
            "name": spec["name"],
            "source_record_id": spec["source_record_id"],
            "source_path": spec["source_file"],
            "source_fingerprint": compiled["source_fingerprint"],
            "source_sha256": _sha256_bytes(source_text.encode()),
            "compiled_clause_ids": historical.get(
                "compiled_clause_ids",
                [str(clause["clause_id"]) for clause in compiled.get("clauses", [])],
            ),
            "compiled_target_kind": historical.get(
                "compiled_target_kind", compiled.get("clauses", [{}])[0].get("kind")
            ),
            "required_semantics": spec["required_semantics"],
            "blockers": spec["blockers"],
            "decision": "retained_compile_only",
        }
    return result


def _focused_tests() -> dict[str, Any]:
    command = [
        str(ROOT / "backend/.venv/bin/python"),
        "-m",
        "pytest",
        "-q",
        "backend/tests/test_rules_kernel.py",
        "backend/tests/test_migrations.py",
        (
            "backend/tests/test_round_XLIII_typed_target_adjudication.py::"
            "test_round_xliii_legacy_adjudication_is_fail_closed"
        ),
        (
            "backend/tests/test_round_XLIII_typed_target_adjudication.py::"
            "test_round_xliii_typed_resolution_rejects_target_and_contract_drift"
        ),
        (
            "backend/tests/test_round_XLIII_typed_target_adjudication.py::"
            "test_round_xliii_typed_resolution_rejects_payload_drift_on_replay"
        ),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = f"{completed.stdout}\n{completed.stderr}"
    passed_count = re.search(r"(\d+)\s+passed", output)
    summary = (
        passed_count.group(0)
        if passed_count is not None
        else "selected XLIII-focused nodes passed"
        if completed.returncode == 0
        else "focused pytest failed"
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "summary": summary,
        "passed": completed.returncode == 0,
    }


def _behavioral_gates() -> dict[str, dict[str, Any]]:
    nodes = {
        "source_binding": (
            "backend/tests/test_rules_kernel.py::"
            "test_typed_adjudication_is_source_bound_and_emits_receipt"
        ),
        "campaign_actor_scene_target_mismatch": (
            "backend/tests/test_rules_kernel.py::"
            "test_typed_adjudication_rejects_wrong_source_and_target_bindings"
        ),
        "stale_cas_expiry": (
            "backend/tests/test_round_XLIII_typed_target_adjudication.py::"
            "test_round_xliii_adjudication_stale_cas_and_expiry_fail_closed"
        ),
        "resolve_replay_payload_drift": (
            "backend/tests/test_round_XLIII_typed_target_adjudication.py::"
            "test_round_xliii_typed_resolution_rejects_payload_drift_on_replay"
        ),
        "immutable_contract": (
            "backend/tests/test_round_XLIII_typed_target_adjudication.py::"
            "test_round_xliii_typed_resolution_rejects_target_and_contract_drift"
        ),
        "legacy_fail_closed": (
            "backend/tests/test_round_XLIII_typed_target_adjudication.py::"
            "test_round_xliii_legacy_adjudication_is_fail_closed"
        ),
        "operation_transaction_receipt": (
            "backend/tests/test_rules_kernel.py::"
            "test_typed_adjudication_is_source_bound_and_emits_receipt"
        ),
    }
    result: dict[str, dict[str, Any]] = {}
    for name, node in nodes.items():
        command = [str(ROOT / "backend/.venv/bin/python"), "-m", "pytest", "-q", node]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        result[name] = {
            "node": node,
            "command": command,
            "returncode": completed.returncode,
            "passed": completed.returncode == 0,
        }
    return result


def build_report() -> dict[str, Any]:
    before = _canonical_counts()
    after = dict(before)
    matrix = _source_matrix()
    focused = _focused_tests()
    gates = _behavioral_gates()
    gate_status = {name: details["passed"] for name, details in gates.items()}
    return {
        "schema_version": "round-XLIII-typed-target-adjudication-1",
        "round_id": "round-XLIII",
        "artifact_date": "2026-08-13",
        "baseline": {
            "path": str(BASELINE_PATH.relative_to(ROOT)),
            "sha256": _sha256_bytes(BASELINE_PATH.read_bytes()),
            "counts": before,
        },
        "after": {
            "canonical_projection_counts": after,
            "promoted_ids": [],
            "retained_compile_only_ids": sorted(matrix),
        },
        "count_delta": {
            key: after[key] - before[key]
            for key in before
        },
        "source_boundary_matrix": matrix,
        "generic_seam": {
            "typed_contract": "typed-adjudication-1",
            "producer": "rules-kernel",
            "consumer": "RulesKernelService.confirm",
            "preview_confirm_replay": gate_status["source_binding"],
            "source_record_fingerprint_clause_binding": gate_status["source_binding"],
            "campaign_actor_scene_target_binding": gate_status[
                "campaign_actor_scene_target_mismatch"
            ],
            "idempotency_payload_drift_rejection": gate_status[
                "resolve_replay_payload_drift"
            ],
            "actor_target_scene_cas": gate_status["stale_cas_expiry"],
            "operation_transaction_receipt": gate_status[
                "operation_transaction_receipt"
            ],
            "immutable_producer_provenance": gate_status["immutable_contract"],
            "fail_closed_missing_or_wrong_binding": gate_status["legacy_fail_closed"],
        },
        "focused_tests": focused,
        "behavioral_gates": gates,
        "protected_fingerprints": _protected(),
        "promotion_rule": "promote only when every source-required semantic dimension has a persisted tested consumer",
        "all_candidates_promoted": False,
        "report_fingerprint": _fingerprint(
            {
                "matrix": matrix,
                "before": before,
                "after": after,
                "focused": focused,
                "gates": gates,
            }
        ),
    }


def main() -> int:
    report = build_report()
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["focused_tests"]["passed"] and all(
        value is True
        for key, value in report["generic_seam"].items()
        if isinstance(value, bool)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
