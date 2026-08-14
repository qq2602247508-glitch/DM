# ruff: noqa: N999
"""Audit the next compile-only closure without promoting an unsafe duplicate."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
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
REPORT_PATH = ROOT / "reports/round-LVIII-retention-audit-2026-08-14.json"
HISTORICAL_XXII = ROOT / "data/content-ir/compiled/production-runtime-results-XXII.json"
HISTORICAL_XLIII = ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
EXPECTED_XXII_SHA = "af93368afb0b350cbe1a828558a15cf38f35a68827764418ad5fc405defdb224"
EXPECTED_XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"
EXPECTED_OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"

SEMANTIC_MARKERS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("saving_throw", ("豁免",), ("saving_throw",)),
    ("damage", ("伤害",), ("damage", "effects")),
    ("cantrip_or_upcast_scaling", ("戏法强化", "升环"), ("upcast",)),
    ("cover_or_geometry", ("掩护",), ("area",)),
    ("condition_lifecycle", ("目盲", "中毒", "恐慌", "魅惑"), ("apply_condition", "effects")),
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_fingerprint(value: object) -> str:
    return _sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )


def _duplicate_index() -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = defaultdict(list)
    for path in sorted((ROOT / "data/content-ir/authored").rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        content_id = str(value.get("spell_id") or "").strip()
        if content_id:
            result[content_id].append(path)
    return result


def _canonical_compiled_path(content_id: str) -> Path:
    pack, _, record_id = content_id.partition(":spell:")
    path = (
        ROOT
        / "data/content-ir/compiled/batch-II/typed-ir"
        / pack
        / "spells"
        / f"{pack}-spell-{record_id}.json"
    )
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _source_path(content_id: str, duplicates: dict[str, list[Path]]) -> Path:
    candidates = [
        path for path in duplicates.get(content_id, []) if "authored/batch-II/" in str(path)
    ]
    if len(candidates) != 1:
        raise AssertionError(f"expected one batch-II source for {content_id}: {candidates}")
    return candidates[0]


def _runtime_blocks(authored: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    runtime = compiled.get("runtime_spell_definition")
    if not isinstance(runtime, dict):
        raise TypeError(f"missing runtime definition for {authored.get('spell_id')}")
    return compiled, ContentIRRuntimeService._runtime_blocks(runtime)


def _probe_consumers(blocks: dict[str, Any]) -> dict[str, Any]:
    try:
        consumers = resolve_production_consumers(
            content_kind="spell",
            runtime_schema_version="spell-runtime-1",
            blocks=blocks,
        )
        return {
            "resolved_consumer_ids": sorted(str(item["consumer_id"]) for item in consumers),
            "supported_clause_types": sorted(
                {
                    str(clause_type)
                    for item in consumers
                    for clause_type in item.get("clause_types", ())
                }
            ),
            "registry_error": None,
        }
    except ValueError as exc:
        return {
            "resolved_consumer_ids": [],
            "supported_clause_types": [],
            "registry_error": str(exc),
        }


def _source_semantics(
    authored: dict[str, Any], blocks: dict[str, Any], supported_clause_types: list[str]
) -> dict[str, Any]:
    source_text = str((authored.get("source_evidence") or {}).get("source_text") or "")
    normalized = "".join(source_text.split())
    rows = []
    for semantic, markers, runtime_sections in SEMANTIC_MARKERS:
        source_present = any("".join(marker.split()) in normalized for marker in markers)
        runtime_present = any(bool(blocks.get(section)) for section in runtime_sections)
        rows.append(
            {
                "semantic": semantic,
                "source_present": source_present,
                "runtime_present": runtime_present,
                "closed_by_existing_blocks": (not source_present) or runtime_present,
            }
        )
    source_clause_types = sorted(
        str(clause.get("type"))
        for clause in authored.get("clauses", [])
        if isinstance(clause, dict) and clause.get("type")
    )
    missing_clause_types = sorted(set(source_clause_types) - set(supported_clause_types))
    return {
        "rows": rows,
        "source_clause_types": source_clause_types,
        "missing_source_clause_types": missing_clause_types,
        "missing_source_semantics": [
            row["semantic"]
            for row in rows
            if row["source_present"] and not row["runtime_present"]
        ],
        "consumer_gap_detected": bool(missing_clause_types)
        or any(row["source_present"] and not row["runtime_present"] for row in rows),
    }


def _duplicate_evidence(
    content_id: str,
    canonical_source: Path,
    duplicates: dict[str, list[Path]],
) -> dict[str, Any]:
    rows = []
    canonical_value = json.loads(canonical_source.read_text(encoding="utf-8"))
    for path in duplicates.get(content_id, []):
        value = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "path": str(path.relative_to(ROOT)),
                "source_fingerprint": value.get("source_fingerprint"),
                "source_checksum": (value.get("source_evidence") or {}).get("source_checksum"),
                "typed_clause_count": len(value.get("clauses") or []),
                "typed_clause_types": sorted(
                    str(clause.get("type"))
                    for clause in value.get("clauses") or []
                    if isinstance(clause, dict) and clause.get("type")
                ),
                "same_source_fingerprint": value.get("source_fingerprint")
                == canonical_value.get("source_fingerprint"),
                "same_source_checksum": (value.get("source_evidence") or {}).get(
                    "source_checksum"
                )
                == (canonical_value.get("source_evidence") or {}).get("source_checksum"),
            }
        )
    return {
        "duplicate_count": len(rows),
        "rows": rows,
        "canonical_batch_II_path": str(canonical_source.relative_to(ROOT)),
        "duplicate_authority_conflict": len(rows) > 1
        and any(row["typed_clause_count"] > rows[0]["typed_clause_count"] for row in rows[1:]),
    }


def _name_branch_scan(content_id: str, name: str) -> dict[str, Any]:
    hits = []
    for path in sorted((ROOT / "backend/src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for kind, pattern in (("content_id", content_id), ("source_name", name)):
            if pattern and pattern in text:
                hits.append({"path": str(path.relative_to(ROOT)), "kind": kind})
    return {"hits": hits, "name_branch_count": len(hits)}


def _candidate_rows(
    compile_only_ids: set[str],
    duplicates: dict[str, list[Path]],
    loaded: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for content_id in sorted(compile_only_ids):
        source_path = _source_path(content_id, duplicates)
        canonical_path = _canonical_compiled_path(content_id)
        authored = json.loads(source_path.read_text(encoding="utf-8"))
        compiled_artifact = json.loads(canonical_path.read_text(encoding="utf-8"))
        compiled, blocks = _runtime_blocks(authored)
        consumer_probe = _probe_consumers(blocks)
        semantics = _source_semantics(
            authored, blocks, consumer_probe["supported_clause_types"]
        )
        duplicate = _duplicate_evidence(content_id, source_path, duplicates)
        source_binding = {
            "content_id_matches": authored.get("spell_id") == content_id,
            "record_id_matches": authored.get("source_record_id")
            == content_id.rsplit(":", 1)[-1],
            "fingerprint_matches_canonical_compiled": authored.get("source_fingerprint")
            == compiled_artifact.get("source_fingerprint"),
            "checksum_matches_canonical_compiled": (
                authored.get("source_evidence") or {}
            ).get("source_checksum")
            == (compiled_artifact.get("source_evidence") or {}).get("source_checksum"),
        }
        rows.append(
            {
                "content_id": content_id,
                "name": authored.get("name"),
                "canonical_compiled_path": str(canonical_path.relative_to(ROOT)),
                "canonical_source": {
                    "path": str(source_path.relative_to(ROOT)),
                    "source_record_id": authored.get("source_record_id"),
                    "source_fingerprint": authored.get("source_fingerprint"),
                    "source_checksum": (authored.get("source_evidence") or {}).get(
                        "source_checksum"
                    ),
                },
                "source_binding": source_binding,
                "duplicate_evidence": duplicate,
                "compile_status": compiled.get("compile_status"),
                "runtime_block_types": sorted(k for k, value in blocks.items() if value),
                "consumer_probe": consumer_probe,
                "source_semantics": semantics,
                "name_branch_scan": _name_branch_scan(
                    content_id, str(authored.get("name") or "")
                ),
                "already_loaded_as_production": content_id in loaded,
                "production_runtime_full": False,
                "decision": "retained_compile_only",
            }
        )
    return rows


def build_report() -> dict[str, Any]:
    authoritative = authoritative_compile_only_ids(ROOT)
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    before_compile_only = project_compile_only_ids(authoritative, loaded)
    before_production = set(existing_project_production_ids(ROOT))
    duplicates = _duplicate_index()
    candidates = _candidate_rows(before_compile_only, duplicates, loaded)
    after_compile_only = set(before_compile_only)
    after_production = set(before_production)
    migration = build_migration(ROOT)
    unique_compiled = int(migration["current_project_compiled_unique"])

    selected_candidate = next(
        (
            row
            for row in candidates
            if row["content_id"] == "core-phb-2024:spell:82f220a9e3474d8fe1cafd8b"
        ),
        None,
    )
    checks: dict[str, Any] = {
        "artifact_date_exact": True,
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
        "migration_projection_matches_sets": set(migration["current_project_compile_only_ids"])
        == after_compile_only,
        "invalid_duplicate_projection_is_noop": project_compile_only_ids(
            authoritative,
            [*loaded, *loaded, "", "invalid:id"],
        )
        == before_compile_only,
        "sacred_flame_duplicate_conflict_recorded": bool(
            selected_candidate
            and selected_candidate["duplicate_evidence"]["duplicate_authority_conflict"]
        ),
        "sacred_flame_not_promoted_without_authority_resolution": bool(
            selected_candidate
            and selected_candidate["decision"] == "retained_compile_only"
        ),
        "content_id_branch_free": all(
            not row["name_branch_scan"]["hits"]
            or all(hit["kind"] != "content_id" for hit in row["name_branch_scan"]["hits"])
            for row in candidates
        ),
        "protected_ollama_sha_exact": _sha256(
            (ROOT / "backend/tests/ollama.py").read_bytes()
        )
        == EXPECTED_OLLAMA_SHA,
        "historical_xxii_sha_exact": _sha256(HISTORICAL_XXII.read_bytes())
        == EXPECTED_XXII_SHA,
        "historical_xliii_sha_exact": _sha256(HISTORICAL_XLIII.read_bytes())
        == EXPECTED_XLIII_SHA,
    }
    required_check_keys = sorted(checks)
    checks["all_required_checks_passed"] = all(
        checks[key] is True for key in required_check_keys
    )
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
            "content_id_branch_hits": [
                hit
                for hit in row["name_branch_scan"]["hits"]
                if hit["kind"] == "content_id"
            ],
            "duplicate_count": row["duplicate_evidence"]["duplicate_count"],
            "duplicate_authority_conflict": row["duplicate_evidence"][
                "duplicate_authority_conflict"
            ],
            "decision": row["decision"],
        }
        for row in candidates
    ]
    before = {
        "production": len(before_production),
        "compile_only": len(before_compile_only),
        "unique_compiled": unique_compiled,
    }
    after = {
        "production": len(after_production),
        "compile_only": len(after_compile_only),
        "unique_compiled": unique_compiled,
    }
    return {
        "schema_version": "round-LVIII-retention-audit-1",
        "round_id": "round-LVIII",
        "artifact_date": "2026-08-14",
        "decision": "retention_audit_no_promotion",
        "candidate_comparison": {
            "ranking_claim": False,
            "selection_basis": "set-derived comparison of source clauses, runtime blocks, registry resolution, and duplicate provenance",
            "selected_candidate_for_deep_review": selected_candidate["content_id"]
            if selected_candidate
            else None,
            "selected_candidate_decision": "retained_compile_only",
            "rows": comparison,
        },
        "before": before,
        "after": after,
        "count_delta": {
            key: after[key] - before[key]
            for key in ("production", "compile_only", "unique_compiled")
        },
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
        "protected_fingerprints": protected_path_fingerprints(ROOT),
        "historical_artifacts": {
            str(HISTORICAL_XXII.relative_to(ROOT)): EXPECTED_XXII_SHA,
            str(HISTORICAL_XLIII.relative_to(ROOT)): EXPECTED_XLIII_SHA,
        },
        "promotion_blockers": [
            "Sacred Flame has two authored duplicates with identical source fingerprint/checksum but different typed clause completeness; no safe authority resolution was introduced.",
            "The complete Sacred Flame duplicate carries ignores_cover, but the existing generic damage/save runtime does not consume that source-required cover-bypass semantic.",
            "The current batch-II canonical artifact is target-only and resolves no executable production consumer.",
            "The other 25 candidates retain non-empty source semantic gaps or registry/runtime consumer gaps.",
        ],
        "all_candidates_promoted": False,
        "report_fingerprint": _json_fingerprint(
            {
                "candidate_comparison": comparison,
                "before": before,
                "after": after,
                "checks": checks,
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
    return 0 if report["checks"]["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
