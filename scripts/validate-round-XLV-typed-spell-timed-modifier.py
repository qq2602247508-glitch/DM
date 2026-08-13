# ruff: noqa: N999
"""Validate the Round XLV reusable typed spell timed-modifier seam."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports/round-XLV-typed-spell-timed-modifier-2026-08-13.json"
BASELINE_PATH = ROOT / "reports/round-XLIV-typed-spell-target-fanout-2026-08-13.json"

CANDIDATES = {
    "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb": {
        "name": "Longstrider",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/6f5b6f21ffa22e705a9bd6cb.md",
        "source_required_blockers": [
            "production known-spell producer and runtime fixture",
            "source-complete replacement/stacking behavior",
        ],
        "seam_covered": [
            "typed speed_ft add modifier",
            "one-hour expiry persistence",
            "same-source replacement",
            "CAS and idempotent replay",
        ],
    },
    "core-phb-2024:spell:83b7d94b77f332dd71310bbe": {
        "name": "Disguise Self",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/83b7d94b77f332dd71310bbe.md",
        "source_required_blockers": ["illusion appearance envelope", "physical inspection and Investigation check"],
        "seam_covered": [],
    },
    "core-phb-2024:spell:b9db026fa1853bca5b6f1c13": {
        "name": "Prestidigitation",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/b9db026fa1853bca5b6f1c13.md",
        "source_required_blockers": ["six effect modes", "three concurrent non-instant effects"],
        "seam_covered": [],
    },
    "core-phb-2024:spell:d82624a42cf6c33ccec927b8": {
        "name": "Speak with Animals",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/d82624a42cf6c33ccec927b8.md",
        "source_required_blockers": ["beast communication capability", "recent-observation information boundary"],
        "seam_covered": [],
    },
    "core-phb-2024:spell:dd9cb25c63b7e13194c7d01c": {
        "name": "Message",
        "source_file": "data/generated-content/dnd5e_chm/markdown/spells/dd9cb25c63b7e13194c7d01c.md",
        "source_required_blockers": ["barrier and familiarity path", "private reply and magical silence interaction"],
        "seam_covered": [],
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
        "integrations_manifest": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
    }


def _focused_tests() -> dict[str, Any]:
    command = [
        str(ROOT / "backend/.venv/bin/python"),
        "-m",
        "pytest",
        "-q",
        "backend/tests/test_typed_spell_timed_modifiers.py",
        "backend/tests/test_content_ir_production_closure.py",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {"command": command, "returncode": result.returncode, "passed": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


def build_report() -> dict[str, Any]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    before = baseline["after"]["canonical_projection_counts"]
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
    after = dict(before)
    report = {
        "schema_version": "round-XLV-typed-spell-timed-modifier-1",
        "round_id": "round-XLV",
        "artifact_date": "2026-08-13",
        "candidate_selection": {
            "chosen_cluster": "typed spell timed modifier persistence",
            "rationale": "Longstrider exposes a reusable speed modifier plus one-hour expiry contract; the existing combat snapshot already has a typed timed-modifier persistence seam.",
            "excluded_already_production_candidate": "content.tashas-cauldron.round2.feature.scribe-manifest-mind",
        },
        "baseline": {"path": str(BASELINE_PATH.relative_to(ROOT)), "sha256": _sha256(BASELINE_PATH), "counts": before},
        "after": {"canonical_projection_counts": after, "promoted_ids": [], "retained_compile_only_ids": sorted(CANDIDATES)},
        "count_delta": {key: after[key] - before[key] for key in before},
        "source_boundary_matrix": source_matrix,
        "generic_seam": {
            "schema": "spell.timed_modifier.v1",
            "producer": "TypedSpellTimedModifierSpec",
            "consumer": "apply_typed_spell_timed_modifier",
            "source_provenance": True,
            "typed_speed_modifier": True,
            "expiry_persistence": True,
            "same_source_replacement": True,
            "cas_version_check": True,
            "idempotent_replay": True,
            "payload_drift_rejection": True,
            "fail_closed_invalid_contract": True,
        },
        "focused_tests": _focused_tests(),
        "protected_fingerprints": _protected(),
        "promotion_rule": "promote only when every source-required semantic dimension has a persisted tested producer and real runtime consumer",
        "promotion_decision": "no_promotion",
    }
    report["report_fingerprint"] = hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return report


def main() -> int:
    report = build_report()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["focused_tests"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
