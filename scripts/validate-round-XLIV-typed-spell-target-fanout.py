# ruff: noqa: N999
"""Validate the Round XLIV reusable typed spell target fan-out seam."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports/round-XLIV-typed-spell-target-fanout-2026-08-13.json"
BASELINE_PATH = ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"

CANDIDATES = {
    "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb": {
        "name": "Longstrider",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/6f5b6f21ffa22e705a9bd6cb.md",
        "source_required_blockers": [
            "speed +10 ft modifier",
            "1-hour persistence and expiry",
            "replacement/stacking behavior",
        ],
        "seam_covered": ["one_creature target", "upcast target fan-out"],
    },
    "core-phb-2024:spell:83b7d94b77f332dd71310bbe": {
        "name": "Disguise Self",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/83b7d94b77f332dd71310bbe.md",
        "source_required_blockers": [
            "illusion appearance envelope",
            "physical inspection behavior",
            "research action and Investigation vs spell DC",
            "1-hour expiry",
        ],
        "seam_covered": ["one_creature self target shape"],
    },
    "core-phb-2024:spell:b9db026fa1853bca5b6f1c13": {
        "name": "Prestidigitation",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/b9db026fa1853bca5b6f1c13.md",
        "source_required_blockers": [
            "six effect modes",
            "instant vs timed mode lifecycle",
            "three concurrent non-instant effects",
        ],
        "seam_covered": ["typed object target shape"],
    },
    "core-phb-2024:spell:d82624a42cf6c33ccec927b8": {
        "name": "Speak with Animals",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/d82624a42cf6c33ccec927b8.md",
        "source_required_blockers": [
            "10-minute communication capability",
            "beast-scope Influence skills",
            "recent-observation information boundary",
        ],
        "seam_covered": ["self target shape"],
    },
    "core-phb-2024:spell:dd9cb25c63b7e13194c7d01c": {
        "name": "Message",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/dd9cb25c63b7e13194c7d01c.md",
        "source_required_blockers": [
            "visibility/familiarity/material barrier path",
            "private reply channel",
            "magical silence interaction",
        ],
        "seam_covered": ["one creature target shape"],
    },
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
        "backend/tests/test_typed_spell_targets.py",
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
    focused = _focused_tests()
    source_matrix = {}
    for content_id, candidate in CANDIDATES.items():
        source_path = ROOT / candidate["source_file"]
        source_matrix[content_id] = {
            "content_id": content_id,
            "name": candidate["name"],
            "source_path": candidate["source_file"],
            "source_sha256": _sha256(source_path),
            "source_required_blockers": candidate["source_required_blockers"],
            "seam_covered": candidate["seam_covered"],
            "decision": "retained_compile_only",
        }
    before = baseline["after"]["canonical_projection_counts"]
    after = dict(before)
    report = {
        "schema_version": "round-XLIV-typed-spell-target-fanout-1",
        "round_id": "round-XLIV",
        "artifact_date": "2026-08-13",
        "candidate_selection": {
            "chosen_cluster": "typed spell target fan-out",
            "rationale": (
                "Longstrider exposes a reusable upcast target-cardinality seam; "
                "the other four candidates confirm the seam is generic but retain distinct blockers."
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
            "schema": "spell.target.fanout.v1",
            "producer": "resolve_typed_spell_targets",
            "consumer": "TypedSpellTargetReceipt",
            "source_provenance": True,
            "upcast_cardinality": True,
            "idempotent_replay": True,
            "payload_drift_rejection": True,
            "fail_closed_invalid_targets": True,
            "effect_duration_persistence": False,
        },
        "focused_tests": focused,
        "protected_fingerprints": _protected(),
        "promotion_rule": (
            "promote only when every source-required semantic dimension has a persisted tested consumer"
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
