# ruff: noqa: N999
"""Validate the Round XLVI reusable typed spell communication-route seam."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports/round-XLVI-typed-spell-communication-route-2026-08-13.json"
BASELINE_PATH = ROOT / "reports/round-XLV-typed-spell-timed-modifier-2026-08-13.json"

CANDIDATES = {
    "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb": (
        "Longstrider",
        "data/generated-content/dnd5e_chm/markdown/spells/6f5b6f21ffa22e705a9bd6cb.md",
        ["real known-spell producer/runtime fixture", "source-complete replacement semantics"],
    ),
    "core-phb-2024:spell:83b7d94b77f332dd71310bbe": (
        "Disguise Self",
        "data/generated-content/dnd5e_chm/markdown/spells/83b7d94b77f332dd71310bbe.md",
        ["illusion appearance envelope", "physical inspection and Investigation consumer"],
    ),
    "core-phb-2024:spell:b9db026fa1853bca5b6f1c13": (
        "Prestidigitation",
        "data/generated-content/dnd5e_chm/markdown/spells/b9db026fa1853bca5b6f1c13.md",
        ["six effect modes", "three-slot concurrent lifecycle"],
    ),
    "core-phb-2024:spell:d82624a42cf6c33ccec927b8": (
        "Speak with Animals",
        "data/generated-content/dnd5e_chm/markdown/spells/d82624a42cf6c33ccec927b8.md",
        ["beast communication capability", "recent-observation boundary"],
    ),
    "core-phb-2024:spell:dd9cb25c63b7e13194c7d01c": (
        "Message",
        "data/generated-content/dnd5e_chm/markdown/spells/dd9cb25c63b7e13194c7d01c.md",
        ["source-complete Message producer/runtime fixture", "full barrier/familiarity/silence semantics"],
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected() -> dict[str, str]:
    manifest = [
        {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}
        for path in sorted((ROOT / "backend/tests/integrations").rglob("*"))
        if path.is_file()
    ]
    return {
        "ollama": _sha256(ROOT / "backend/tests/ollama.py"),
        "integrations_manifest": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest(),
    }


def _focused_tests() -> dict[str, Any]:
    command = [
        str(ROOT / "backend/.venv/bin/python"),
        "-m",
        "pytest",
        "-q",
        "backend/tests/test_typed_spell_communication_routes.py",
        "backend/tests/test_content_ir_production_closure.py",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def build_report() -> dict[str, Any]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    before = baseline["after"]["canonical_projection_counts"]
    source_matrix = {}
    for content_id, (name, source_file, blockers) in CANDIDATES.items():
        source_path = ROOT / source_file
        source_matrix[content_id] = {
            "content_id": content_id,
            "name": name,
            "source_path": source_file,
            "source_sha256": _sha256(source_path),
            "source_required_blockers": blockers,
            "decision": "retained_compile_only",
        }
    after = dict(before)
    report = {
        "schema_version": "round-XLVI-typed-spell-communication-route-1",
        "round_id": "round-XLVI",
        "artifact_date": "2026-08-13",
        "candidate_selection": {
            "chosen_cluster": "private communication route",
            "chosen_candidate": "core-phb-2024:spell:dd9cb25c63b7e13194c7d01c",
            "rationale": (
                "Message is the strongest exact cluster: its visibility/familiarity, "
                "material-barrier, target-only, private-reply, and magical-silence "
                "dimensions form a reusable typed route policy. The seam is generic "
                "and tested, but Message lacks a source-complete producer/runtime fixture."
            ),
            "excluded_already_production_candidate": (
                "content.tashas-cauldron.round2.feature.scribe-manifest-mind"
            ),
        },
        "baseline": {
            "path": str(BASELINE_PATH.relative_to(ROOT)),
            "sha256": _sha256(BASELINE_PATH),
            "counts": before,
        },
        "after": {
            "canonical_projection_counts": after,
            "promoted_ids": [],
            "retained_compile_only_ids": sorted(CANDIDATES),
        },
        "count_delta": {key: after[key] - before[key] for key in before},
        "source_boundary_matrix": source_matrix,
        "generic_seam": {
            "schema": "spell.communication.route.v1",
            "producer": "TypedSpellCommunicationRouteSpec",
            "consumer": "apply_typed_spell_communication_route",
            "source_provenance": True,
            "visibility_or_familiarity_gate": True,
            "material_barrier_gate": True,
            "target_only_delivery": True,
            "private_reply": True,
            "magical_silence_block": True,
            "cas_version_check": True,
            "idempotent_replay": True,
            "payload_drift_rejection": True,
            "fail_closed_invalid_contract": True,
        },
        "focused_tests": _focused_tests(),
        "protected_fingerprints": _protected(),
        "promotion_rule": (
            "promote only when every source-required semantic dimension has a "
            "persisted tested producer and real runtime consumer"
        ),
        "promotion_decision": "no_promotion",
    }
    report["report_fingerprint"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return report


def main() -> int:
    report = build_report()
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["focused_tests"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
