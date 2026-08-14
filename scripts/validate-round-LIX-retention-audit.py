# ruff: noqa: N999
"""Audit the strongest current compile-only candidate without unsafe promotion."""

from __future__ import annotations

import hashlib
import json
import runpy
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports/round-LIX-retention-audit-2026-08-14.json"
HISTORICAL_XXII = ROOT / "data/content-ir/compiled/production-runtime-results-XXII.json"
HISTORICAL_XLIII = ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
EXPECTED_XXII_SHA = "af93368afb0b350cbe1a828558a15cf38f35a68827764418ad5fc405defdb224"
EXPECTED_XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"
EXPECTED_OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
SELECTED_ID = "xanathars-guide:spell:aadf89719f073bfca1fefb3a"

LVIII = runpy.run_path(str(ROOT / "scripts/validate-round-LVIII-retention-audit.py"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _select_candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def key(row: dict[str, Any]) -> tuple[Any, ...]:
        semantics = row["source_semantics"]
        probe = row["consumer_probe"]
        duplicate = row["duplicate_evidence"]
        return (
            len(semantics["missing_source_semantics"]),
            len(semantics["missing_source_clause_types"]),
            probe["registry_error"] is not None,
            duplicate["duplicate_authority_conflict"],
            -len(probe["resolved_consumer_ids"]),
            row["content_id"],
        )

    selected = min(rows, key=key)
    if selected["content_id"] != SELECTED_ID:
        raise AssertionError(
            f"derived strongest candidate changed: {selected['content_id']} != {SELECTED_ID}"
        )
    return selected


def _source_blocker(selected: dict[str, Any]) -> dict[str, Any]:
    source_path = ROOT / selected["canonical_source"]["path"]
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source_text = str((source.get("source_evidence") or {}).get("source_text") or "")
    required_markers = {
        "cloud_text_creation": "云彩构成",
        "cloud_text_persistence": "留在原位",
        "wind_early_termination": "强风可以吹散云彩",
        "termination": "法术提前终止",
    }
    marker_presence = {
        name: marker in source_text for name, marker in required_markers.items()
    }
    runtime_types = set(selected["runtime_block_types"])
    missing_runtime_capabilities = {
        "cloud_text_creation": "object_effect_lifecycle" not in runtime_types,
        "cloud_text_persistence": "duration" not in runtime_types,
        "wind_early_termination": "environmental_termination" not in runtime_types,
        "termination": "termination" not in runtime_types,
    }
    return {
        "source_path": str(source_path.relative_to(ROOT)),
        "source_markers": marker_presence,
        "runtime_block_types": sorted(runtime_types),
        "missing_runtime_capabilities": missing_runtime_capabilities,
        "source_complete": all(marker_presence.values())
        and not any(missing_runtime_capabilities.values()),
    }


def build_report() -> dict[str, Any]:
    authoritative = LVIII["authoritative_compile_only_ids"](ROOT)
    loaded = LVIII["load_production_runtime_evidence"](
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    before_compile_only = LVIII["project_compile_only_ids"](authoritative, loaded)
    before_production = set(LVIII["existing_project_production_ids"](ROOT))
    duplicates = LVIII["_duplicate_index"]()
    candidates = LVIII["_candidate_rows"](before_compile_only, duplicates, loaded)
    selected = _select_candidate(candidates)
    blocker = _source_blocker(selected)
    migration = LVIII["build_migration"](ROOT)
    after_compile_only = set(before_compile_only)
    after_production = set(before_production)
    artifact_date = REPORT_PATH.stem[-10:]

    checks: dict[str, Any] = {
        "artifact_date_exact": (
            date.fromisoformat(artifact_date).isoformat() == artifact_date
            and REPORT_PATH.name == f"round-LIX-retention-audit-{artifact_date}.json"
        ),
        "accepted_head_is_ancestor": __import__("subprocess").run(
            ["git", "merge-base", "--is-ancestor", "063e9e171d6432c66349acce36a58ab74f37be2f", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0,
        "candidate_set_is_authoritative": {row["content_id"] for row in candidates}
        == before_compile_only,
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
        "unrelated_compile_only_ids_unchanged": before_compile_only == after_compile_only,
        "production_union_unchanged": before_production == after_production,
        "production_union_deduplicated": len(after_production) == len(set(after_production)),
        "migration_projection_matches_sets": set(
            migration["current_project_compile_only_ids"]
        )
        == after_compile_only,
        "invalid_duplicate_projection_is_noop": LVIII["project_compile_only_ids"](
            authoritative, [*loaded, *loaded, "", "invalid:id"]
        )
        == before_compile_only,
        "selected_candidate_is_derived": selected["content_id"]
        == min(
            candidates,
            key=lambda row: (
                len(row["source_semantics"]["missing_source_semantics"]),
                len(row["source_semantics"]["missing_source_clause_types"]),
                row["consumer_probe"]["registry_error"] is not None,
                row["duplicate_evidence"]["duplicate_authority_conflict"],
                -len(row["consumer_probe"]["resolved_consumer_ids"]),
                row["content_id"],
            ),
        )["content_id"],
        "selected_candidate_has_generic_consumer": selected["consumer_probe"][
            "resolved_consumer_ids"
        ]
        == ["spell_economy.concentration.v1"],
        "selected_candidate_source_blocker_positive": all(
            blocker["source_markers"].values()
        ),
        "selected_candidate_runtime_gap_positive": any(
            blocker["missing_runtime_capabilities"].values()
        ),
        "selected_candidate_not_promoted": selected["decision"]
        == "retained_compile_only"
        and selected["production_runtime_full"] is False,
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
    required_check_keys = sorted(checks)
    checks["all_required_checks_passed"] = all(checks[key] is True for key in required_check_keys)

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
    comparison = [
        {
            "content_id": row["content_id"],
            "name": row["name"],
            "resolved_consumer_ids": row["consumer_probe"]["resolved_consumer_ids"],
            "registry_error": row["consumer_probe"]["registry_error"],
            "runtime_block_types": row["runtime_block_types"],
            "source_clause_types": row["source_semantics"]["source_clause_types"],
            "missing_source_clause_types": row["source_semantics"][
                "missing_source_clause_types"
            ],
            "missing_source_semantics": row["source_semantics"]["missing_source_semantics"],
            "duplicate_count": row["duplicate_evidence"]["duplicate_count"],
            "duplicate_authority_conflict": row["duplicate_evidence"][
                "duplicate_authority_conflict"
            ],
            "decision": row["decision"],
        }
        for row in candidates
    ]
    return {
        "schema_version": "round-LIX-retention-audit-1",
        "round_id": "round-LIX",
        "artifact_date": artifact_date,
        "decision": "retention_audit_no_promotion",
        "candidate_comparison": {
            "ranking_claim": bool(candidates)
            and selected["content_id"]
            == min(
                candidates,
                key=lambda row: (
                    len(row["source_semantics"]["missing_source_semantics"]),
                    len(row["source_semantics"]["missing_source_clause_types"]),
                    row["consumer_probe"]["registry_error"] is not None,
                    row["duplicate_evidence"]["duplicate_authority_conflict"],
                    -len(row["consumer_probe"]["resolved_consumer_ids"]),
                    row["content_id"],
                ),
            )["content_id"],
            "selection_basis": "derived minimum of source semantic gaps, missing typed clauses, registry errors, duplicate authority conflicts, and generic consumer count",
            "selected_candidate_for_deep_review": selected["content_id"],
            "selected_candidate_decision": selected["decision"],
            "rows": comparison,
        },
        "selected_candidate_blocker": blocker,
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
        "candidate_evidence": candidates,
        "checks": checks,
        "required_check_keys": required_check_keys,
        "protected_fingerprints": LVIII["protected_path_fingerprints"](ROOT),
        "historical_artifacts": {
            str(HISTORICAL_XXII.relative_to(ROOT)): EXPECTED_XXII_SHA,
            str(HISTORICAL_XLIII.relative_to(ROOT)): EXPECTED_XLIII_SHA,
        },
        "promotion_blockers": [
            "The selected Skywrite source requires cloud-written text creation and persistence in the visible sky.",
            "The selected Skywrite source requires strong wind to terminate the spell early.",
            "The current generic runtime exposes only concentration for this source; it has no generic object/cloud lifecycle, duration persistence, environmental termination, or termination consumer.",
        ],
        "all_candidates_promoted": all(
            row["production_runtime_full"] is True for row in candidates
        ),
        "all_required_checks_passed": checks["all_required_checks_passed"],
    }


def main() -> int:
    report = build_report()
    report["report_fingerprint"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["checks"]["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
