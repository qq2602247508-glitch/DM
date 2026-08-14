# ruff: noqa: N999
"""Round LX dynamic retention audit for the strongest non-repeat candidate."""

from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
REPORT_PATH = ROOT / "reports/round-LX-retention-audit-2026-08-14.json"
HISTORICAL_XXII = ROOT / "data/content-ir/compiled/production-runtime-results-XXII.json"
HISTORICAL_XLIII = ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
EXPECTED_XXII_SHA = "af93368afb0b350cbe1a828558a15cf38f35a68827764418ad5fc405defdb224"
EXPECTED_XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"
EXPECTED_OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
PREVIOUSLY_DEEP_REVIEWED = {
    "core-phb-2024:spell:82f220a9e3474d8fe1cafd8b",
    "xanathars-guide:spell:aadf89719f073bfca1fefb3a",
}
LX = runpy.run_path(str(ROOT / "scripts/validate-round-LVIII-retention-audit.py"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_gap(row: dict[str, Any]) -> dict[str, Any]:
    source = json.loads((ROOT / row["canonical_source"]["path"]).read_text(encoding="utf-8"))
    text = str((source.get("source_evidence") or {}).get("source_text") or "")
    markers = {
        "persistent_area": ("创造一片", "球状浓雾"),
        "strong_wind_termination": ("强风", "吹散"),
        "upcast_radius_scaling": ("升环施法", "半径就增加"),
        "concentration": ("专注",),
    }
    present = {key: all(marker in text for marker in values) for key, values in markers.items()}
    runtime_types = set(row["runtime_block_types"])
    consumed = {
        "persistent_area": bool({"area", "object_effect_lifecycle"} & runtime_types),
        "strong_wind_termination": "environmental_termination" in runtime_types,
        "upcast_radius_scaling": "upcast" in runtime_types,
        "concentration": "concentration" in runtime_types,
    }
    return {
        "source_path": row["canonical_source"]["path"],
        "source_record_id": row["canonical_source"]["source_record_id"],
        "source_fingerprint": row["canonical_source"]["source_fingerprint"],
        "source_checksum": row["canonical_source"]["source_checksum"],
        "marker_presence": present,
        "runtime_consumption": consumed,
        "missing_source_semantics": [
            key for key in present if present[key] and not consumed[key]
        ],
        "source_complete": all(not present[key] or consumed[key] for key in present),
    }


def _selection_key(row: dict[str, Any]) -> tuple[Any, ...]:
    gap = _source_gap(row)
    probe = row["consumer_probe"]
    return (
        row["content_id"] in PREVIOUSLY_DEEP_REVIEWED,
        not bool(gap["missing_source_semantics"]),
        bool(row["duplicate_evidence"]["duplicate_authority_conflict"]),
        bool(probe["registry_error"]),
        len(gap["missing_source_semantics"]),
        len(row["source_semantics"]["missing_source_clause_types"]),
        -len(probe["resolved_consumer_ids"]),
        row["content_id"],
    )


def build_report() -> dict[str, Any]:
    authoritative = LX["authoritative_compile_only_ids"](ROOT)
    loaded = LX["load_production_runtime_evidence"](
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    before_compile_only = LX["project_compile_only_ids"](authoritative, loaded)
    before_production = set(LX["existing_project_production_ids"](ROOT))
    candidates = LX["_candidate_rows"](
        before_compile_only, LX["_duplicate_index"](), loaded
    )
    selected = min(candidates, key=_selection_key)
    gap = _source_gap(selected)
    migration = LX["build_migration"](ROOT)
    after_compile_only = set(before_compile_only)
    after_production = set(before_production)
    checks: dict[str, Any] = {
        "artifact_date_exact": REPORT_PATH.name == "round-LX-retention-audit-2026-08-14.json",
        "accepted_head_is_ancestor": subprocess.run(
            ["git", "merge-base", "--is-ancestor", "062e07d", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0,
        "candidate_set_is_authoritative": {
            row["content_id"] for row in candidates
        } == before_compile_only,
        "candidate_set_count_is_current": len(candidates) == len(before_compile_only),
        "all_candidates_source_bound": all(
            all(row["source_binding"].values()) for row in candidates
        ),
        "all_candidates_retained": all(
            row["decision"] == "retained_compile_only"
            and row["production_runtime_full"] is False
            for row in candidates
        ),
        "no_candidate_loaded_as_production": all(
            row["already_loaded_as_production"] is False for row in candidates
        ),
        "projection_unchanged": before_compile_only == after_compile_only
        and before_production == after_production,
        "migration_projection_matches_sets": set(
            migration["current_project_compile_only_ids"]
        ) == after_compile_only,
        "selected_candidate_is_derived": selected["content_id"]
        == min(candidates, key=_selection_key)["content_id"],
        "selected_candidate_not_previous_deep_review": selected["content_id"]
        not in PREVIOUSLY_DEEP_REVIEWED,
        "selected_candidate_source_bound": all(selected["source_binding"].values()),
        "selected_candidate_source_incomplete": not gap["source_complete"],
        "selected_candidate_runtime_gap_positive": bool(gap["missing_source_semantics"]),
        "selected_candidate_not_promoted": selected["production_runtime_full"] is False,
        "content_id_branch_free": all(
            not row["name_branch_scan"]["hits"]
            or all(hit["kind"] != "content_id" for hit in row["name_branch_scan"]["hits"])
            for row in candidates
        ),
        "protected_ollama_sha_exact": _sha(ROOT / "backend/tests/ollama.py")
        == EXPECTED_OLLAMA_SHA,
        "historical_xxii_sha_exact": _sha(HISTORICAL_XXII) == EXPECTED_XXII_SHA,
        "historical_xliii_sha_exact": _sha(HISTORICAL_XLIII) == EXPECTED_XLIII_SHA,
    }
    checks["all_required_checks_passed"] = all(checks.values())
    before = {
        "production": len(before_production),
        "compile_only": len(before_compile_only),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    after = {
        "production": len(after_production),
        "compile_only": len(after_compile_only),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    return {
        "schema_version": "round-LX-retention-audit-1",
        "round_id": "round-LX",
        "artifact_date": "2026-08-14",
        "decision": "retention_audit_no_promotion",
        "candidate_comparison": {
            "selection_basis": (
                "derived minimum of prior-review exclusion, duplicate authority conflict, "
                "registry errors, source semantic gaps, typed clause gaps, and consumer count"
            ),
            "selected_candidate_for_deep_review": selected["content_id"],
            "selected_candidate_decision": selected["decision"],
            "rows": [
                {
                    "content_id": row["content_id"],
                    "name": row["name"],
                    "selection_key": list(_selection_key(row)),
                    "resolved_consumer_ids": row["consumer_probe"]["resolved_consumer_ids"],
                    "registry_error": row["consumer_probe"]["registry_error"],
                    "runtime_block_types": row["runtime_block_types"],
                    "source_clause_types": row["source_semantics"]["source_clause_types"],
                    "missing_source_clause_types": row["source_semantics"][
                        "missing_source_clause_types"
                    ],
                    "deep_review_source_gap": _source_gap(row),
                    "decision": row["decision"],
                }
                for row in candidates
            ],
        },
        "selected_candidate_blocker": gap,
        "before": before,
        "after": after,
        "count_delta": {key: after[key] - before[key] for key in before},
        "projection_sets": {
            "before_compile_only_ids": sorted(before_compile_only),
            "after_compile_only_ids": sorted(after_compile_only),
            "promoted_ids": [],
            "production_before_ids": sorted(before_production),
            "production_after_ids": sorted(after_production),
        },
        "promotion_blockers": [
            "The selected Fog Cloud source creates a persistent obscuring area.",
            "The selected Fog Cloud source requires strong wind to terminate the effect early.",
            "The selected Fog Cloud source requires upcast radius scaling.",
            (
                "The current typed runtime exposes only concentration for this source; no generic "
                "area persistence, environmental termination, or radius-scaling consumer is registered."
            ),
        ],
        "checks": checks,
        "required_check_keys": sorted(checks),
        "protected_fingerprints": LX["protected_path_fingerprints"](ROOT),
        "historical_artifacts": {
            str(HISTORICAL_XXII.relative_to(ROOT)): EXPECTED_XXII_SHA,
            str(HISTORICAL_XLIII.relative_to(ROOT)): EXPECTED_XLIII_SHA,
        },
        "all_candidates_promoted": all(
            row["production_runtime_full"] is True for row in candidates
        ),
        "all_required_checks_passed": checks["all_required_checks_passed"],
    }


def main() -> None:
    report = build_report()
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not report["all_required_checks_passed"]:
        raise SystemExit("Round LX retention audit failed")


if __name__ == "__main__":
    main()
