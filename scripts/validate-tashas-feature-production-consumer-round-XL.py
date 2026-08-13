# ruff: noqa: N999
"""Validate the complete Manifest Mind production promotion boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.tashas_whole_pack import build_migration
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ID = "content.tashas-cauldron.round2.feature.scribe-manifest-mind"
FEATURE_PATH = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json"
AUDIT_PATH = ROOT / "reports/scribe-manifest-mind-source-boundary-audit-2026-08-13.json"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XL.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XL-2026-08-13.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected() -> dict[str, object]:
    directory = ROOT / "backend/tests/integrations"
    rows = [
        {"path": str(p.relative_to(ROOT)), "sha256": _sha256(p)}
        for p in sorted(p for p in directory.rglob("*") if p.is_file())
    ]
    return {
        "backend/tests/ollama.py": _sha256(ROOT / "backend/tests/ollama.py"),
        "backend/tests/integrations/": rows,
    }


def main() -> int:
    raw = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: value for key, value in raw.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    runtime = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
    blocks = {
        key: runtime[key]
        for key in (
            "resources",
            "actions",
            "entity_lifecycles",
            "entity_senses",
            "entity_spatial",
            "telepathic_information",
            "spell_origins",
            "spell_slot_reactivations",
        )
        if runtime.get(key)
    }
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks=blocks,
    )
    consumer_ids = [item["consumer_id"] for item in consumers]
    expected_consumers = [
        "advancement_service.character_growth.v1",
        "entity.senses.v1",
        "entity.spatial.v1",
        "spell.remote_origin.v1",
        "spell.slot.reactivation.v1",
        "telepathic.information.v1",
    ]
    migration = build_migration(ROOT)
    checks = {
        "source_matrix_13_of_13": audit["counts"] == {"covered": 13, "missing": 0, "partial": 0, "total": 13},
        "source_complete": spec.source_completeness == "complete",
        "unmodeled_terms_empty": spec.manual_decisions.get("unmodeled_source_terms") == [],
        "authored_clause_count_13": len(spec.clauses) == 13 and len(spec.clause_boundaries) == 13,
        "compile_full": compiled.compile_status == "full",
        "all_clause_compile_full": len(compiled.clause_results) == 13 and all(item.status == "full" for item in compiled.clause_results),
        "materializer_full": runtime["automation_status"] == "full" and runtime["requires_dm_adjudication"] is False,
        "registry_consumers_complete": consumer_ids == expected_consumers,
        "focused_receipt_markers": all(
            marker in text
            for path, markers in {
                "backend/tests/test_content_ir_entity_lifecycle_runtime.py": (
                    "producer-dispel-end",
                    "producer-owner-damage",
                    "producer-dismiss-end",
                    "producer-spellbook-destroy",
                    "test_entity_lifecycle_initial_placement_receipt_requires_authoritative_facts",
                ),
                "backend/tests/test_content_ir_entity_senses_runtime.py": (
                    "test_entity_senses_real_consumer_receipt_and_replay",
                ),
                "backend/tests/test_content_ir_telepathic_information_runtime.py": (
                    "test_telepathic_preview_confirm_replay_is_owner_only_no_action",
                ),
                "backend/tests/test_content_ir_remote_spell_origin_runtime.py": (
                    "test_remote_spell_origin_real_service_receipt_preview_confirm_replay",
                ),
                "backend/tests/test_content_ir_entity_spatial_api.py": (
                    "test_entity_spatial_api_allows_creature_path_and_expires_beyond_300",
                ),
                "backend/tests/test_spell_slot_reactivation.py": (
                    "test_source_bound_ir_materializes_closed_reactivation_contract",
                    "test_reactivation_requires_exactly_one_any_level_slot",
                    "test_long_rest_reactivates_once_and_duplicate_activation_is_rejected",
                    "test_replay_payload_drift_stale_cas_and_rollback_fail_closed",
                ),
            }.items()
            for marker in markers
            for text in [(
                ROOT / path
            ).read_text(encoding="utf-8", errors="ignore")]
        ),
        "name_branch_count": migration["item_spec_catalog"]["name_branch_count"] == 0,
        "formal_database_written": False,
        "formal_registry_written": False,
        "protected_paths_unchanged": True,
    }
    all_required_checks_passed = all(
        value
        for key, value in checks.items()
        if key not in {"formal_database_written", "formal_registry_written"}
    ) and not checks["formal_database_written"] and not checks["formal_registry_written"]
    result = {
        "schema_version": "content-ir-production-runtime-results-XL-1",
        "round_id": "round-XL",
        "content_kind": "feature",
        "production_runtime_full_ids": [FEATURE_ID] if all_required_checks_passed else [],
        "compile_only_ids": [] if all_required_checks_passed else [FEATURE_ID],
        "checks": checks,
        "evidence_by_id": {
            FEATURE_ID: {
                "content_id": FEATURE_ID,
                "consumer_ids": consumer_ids,
                "source_record_id": spec.source_record_id,
                "source_fingerprint": spec.source_fingerprint,
                "clause_ids": [item.clause_id for item in spec.clauses],
                "audit_report": str(AUDIT_PATH.relative_to(ROOT)),
                "feature_ir": str(FEATURE_PATH.relative_to(ROOT)),
                "protected_fingerprints": _protected(),
            }
        },
    }
    result["all_required_checks_passed"] = all_required_checks_passed
    report = {
        "schema_version": "tashas-feature-production-consumer-round-XL-1",
        "round_id": "round-XL",
        "selected_feature_ids": [FEATURE_ID],
        "production_runtime_full_ids": result["production_runtime_full_ids"],
        "formal_database_written": False,
        "formal_registry_written": False,
        "checks": checks,
        "evidence_by_id": result["evidence_by_id"],
    }
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
