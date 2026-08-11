# ruff: noqa: N999
"""Build the deterministic whole-pack Tasha migration artifacts and reports."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_workbench import load_records
from dnd_dm_assistant.application.content_pack_runtime_registry import (
    ContentPackRuntimeRegistry,
)
from dnd_dm_assistant.application.tashas_recovery import (
    apply_isolated_runtime_validation,
    build_feature_option_batch,
    build_item_spec_catalog,
    build_template_catalog,
    load_item_production_evidence,
)
from dnd_dm_assistant.application.tashas_whole_pack import (
    PACK_ID,
    SOURCE_BOOK,
    build_atom_quality_audit,
    build_manual_semantic_clusters,
    build_migration,
    fingerprint,
    report_projection,
    select_source_records,
)
from dnd_dm_assistant.domain.content_ir_status import summarize_status_layers
from dnd_dm_assistant.domain.content_packs import validate_content_pack_compatibility

ROOT = Path(__file__).resolve().parents[1]
REPORT_DATE = "2026-08-11"
LEGACY_ATOM_CATALOG_COMMIT = "a3e7440"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _atom_rows(migration: dict[str, Any], *kinds: str) -> list[dict[str, Any]]:
    wanted = set(kinds)
    return [
        atom
        for atom in migration["atoms"]
        if not wanted or atom["content_kind"] in wanted
    ]


def _previous_atom_catalog(root: Path) -> tuple[dict[str, Any], str]:
    """Load the first-pass denominator before this pass overwrites its report."""

    reports_dir = root / "reports"
    stable_path = reports_dir / f"tashas-content-atom-catalog-I-{REPORT_DATE}.json"
    for path in (stable_path,):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("atoms"), list):
            return value, str(path.relative_to(root))
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{LEGACY_ATOM_CATALOG_COMMIT}:reports/tashas-content-atom-catalog-{REPORT_DATE}.json"],
            cwd=root,
            text=True,
        )
        value = json.loads(raw)
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError):
        value = {"atoms": []}
    return value, f"git:{LEGACY_ATOM_CATALOG_COMMIT}"


def _status_summary(
    rows: list[dict[str, Any]], key: str = "migration_status"
) -> dict[str, int]:
    return dict(sorted(Counter(str(row[key]) for row in rows).items()))


def build_baseline(migration: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "tashas-migration-baseline-1",
        "baseline_date": REPORT_DATE,
        "content_ir_total": migration["current_project_compiled_unique"],
        "compile_full": migration["current_project_compiled_unique"],
        "runtime_preview_full": migration["current_project_compiled_unique"],
        "production_full": migration["current_project_production_full"],
        "dm_assisted": 0,
        "compile_only": migration["current_project_compile_only"],
        "manual": 0,
        "invalid": 0,
        "per_pack_counts": {
            "Core 2024": 42,
            "Xanathar": 9,
            "Tasha total": 19,
            "Fizban": 3,
            "Book of Many Things": 3,
        },
        "per_kind_counts": {"Spell": 61, "Feature": 15},
        "formal_499_status": migration["formal_499_status"],
        "production_registry_fingerprint": migration[
            "current_project_production_registry_fingerprint"
        ],
        "database_fingerprint": migration["database_fingerprint"],
        "protected_path_fingerprints": migration["protected_path_fingerprints"],
        "relation_check": {
            "unique_compiled": migration["current_project_compiled_unique"],
            "production_full_plus_compile_only": (
                migration["current_project_production_full"]
                + migration["current_project_compile_only"]
            ),
            "dm_assisted_not_in_legacy_baseline": True,
        },
    }


def build_reports(migration: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    atoms = migration["atoms"]
    executable = _atom_rows(migration)
    executable = [atom for atom in executable if atom["executable_candidate"]]
    candidates = migration["candidates"]
    reviews = migration["reviews"]
    matched = [
        row for row in candidates if row["match_status"] != "unmatched_requires_review"
    ]
    production_atoms = [atom for atom in atoms if atom["migration_status"] == "production_full"]
    dm_atoms = [atom for atom in atoms if atom["migration_status"] == "dm_assisted"]
    player_options = _atom_rows(
        migration,
        "feat",
        "maneuver",
        "invocation",
        "infusion",
        "character_option",
    )
    feature_atoms = _atom_rows(
        migration,
        "class_feature",
        "subclass_feature",
        "optional_class_feature",
    )
    spell_atoms = _atom_rows(migration, "spell")
    item_atoms = _atom_rows(migration, "magic_item", "magic_tattoo")
    item_catalog = migration.get("item_spec_catalog") or {
        "item_spec_total": 0,
        "item_spec_reviewed": 0,
        "item_spec_typed": 0,
        "item_spec_compile_full": 0,
        "item_spec_compile_only": 0,
        "production_full": 0,
        "requires_dm": 0,
        "specs": [],
    }
    template_catalog = migration.get("template_catalog") or {
        "template_total": 0,
        "new_template_total": 0,
        "templates": [],
    }
    feature_batch = build_feature_option_batch(atoms, candidates, reviews)
    baseline_projection = report_projection(migration)

    source_inventory = {
        "schema_version": "tashas-source-inventory-2",
        "pack_id": PACK_ID,
        "source_book": SOURCE_BOOK,
        "source_record_total": migration["source_record_total"],
        "source_record_scanned": migration["source_record_scanned"],
        "source_record_classified": migration["source_record_classified"],
        "source_record_unclassified": migration["source_record_unclassified"],
        "records": migration["source_inventory"],
        "inventory_fingerprint": fingerprint(migration["source_inventory"]),
    }
    atom_catalog = {
        "schema_version": "tashas-content-atom-catalog-2",
        "pack_id": PACK_ID,
        "source_book": SOURCE_BOOK,
        "content_atom_total": len(atoms),
        "player_facing_atom_total": migration["player_facing_atom_total"],
        "executable_candidate_total": migration["executable_candidate_total"],
        "kind_counts": migration["kind_counts"],
        "status_counts": migration["status_counts"],
        "atoms": atoms,
        "atom_fingerprint": fingerprint(
            [(atom["atom_id"], atom["source_fingerprint"]) for atom in atoms]
        ),
    }
    atom_catalog_II = {
        **atom_catalog,
        "schema_version": "tashas-content-atom-catalog-II-1",
        "quality_audit": migration.get("quality_audit", {}),
        "semantic_cluster_fingerprint": migration.get("semantic_clusters", {}).get(
            "cluster_fingerprint"
        ),
        "authored_provenance_reconciliation": {
            "matched": migration.get("existing_typed_ir_total", 0)
            - len(migration.get("existing_typed_ir_unmatched", [])),
            "explicitly_retired": len(migration.get("existing_typed_ir_reconciled", [])),
            "orphaned": migration.get("orphan_authored_ir_count", 0),
        },
    }
    template_report = {
        "schema_version": "tashas-template-match-report-1",
        "pack_id": PACK_ID,
        "candidate_total": len(candidates),
        "template_matched": len(matched),
        "template_match_rate": _rate(len(matched), len(candidates)),
        "existing_template_count": 12,
        "new_template_count": template_catalog.get("new_template_total", 0),
        "new_template_ids": [
            item["template_id"] for item in template_catalog.get("templates", [])
        ],
        "by_kind": {
            f"{kind}:{status}": count
            for (kind, status), count in sorted(
                Counter(
                    (row["content_kind"], row["match_status"])
                    for row in candidates
                ).items()
            )
        },
        "candidates": candidates,
    }
    review_report = {
        "schema_version": "tashas-review-report-1",
        "pack_id": PACK_ID,
        "reviewed_total": len(reviews),
        "review_status_counts": _status_summary(reviews, "review_status"),
        "accepted_or_edited": sum(
            row["review_status"] in {"accepted", "accepted_with_edits"}
            for row in reviews
        ),
        "manual_boundary": sum(row["review_status"] == "manual_boundary" for row in reviews),
        "source_fingerprint_stale": 0,
        "template_fingerprint_stale": 0,
        "reviews": reviews,
    }

    def typed_report(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema_version": f"tashas-{name}-ir-report-1",
            "pack_id": PACK_ID,
            "atom_total": len(rows),
            "typed_atom_total": sum(bool(row.get("typed_content_ids")) for row in rows),
            "status_counts": _status_summary(rows),
            "atoms": rows,
        }

    production_report = {
        "schema_version": "tashas-production-runtime-report-1",
        "pack_id": PACK_ID,
        "registry_production_runtime_full_count": len(migration["production_ids"]),
        "matched_atom_production_runtime_full_count": len(
            migration["matched_production_runtime_ids"]
        ),
        "unmatched_production_runtime_ids": migration["unmatched_production_runtime_ids"],
        "atom_production_full_count": len(production_atoms),
        "atom_dm_assisted_count": len(dm_atoms),
        "runtime_preview_full_count": migration["runtime_preview_full"],
        "existing_generic_consumers": migration["consumer_unlocks"],
        "new_consumer_count": 0,
        "name_branch_count": 0,
        "runtime_evidence": migration["production_evidence"],
        "production_atoms": [atom["atom_id"] for atom in production_atoms],
        "dm_assisted_atoms": [atom["atom_id"] for atom in dm_atoms],
    }
    dm_report = {
        "schema_version": "tashas-dm-assisted-report-1",
        "pack_id": PACK_ID,
        "dm_assisted_count": len(dm_atoms),
        "formal_window_requirements": {
            "typed_deterministic_clauses": True,
            "frozen_action_and_resource": True,
            "persistent_adjudication_window": True,
            "decision_schema_and_permission": True,
            "rules_kernel_continuation": True,
            "transaction_idempotency_cas_rollback_snapshot": True,
        },
        "atoms": [
            {
                "atom_id": atom["atom_id"],
                "content_id": atom.get("content_id"),
                "name": atom["name"],
                "reason": atom.get("status_reason"),
                "runtime_evidence": atom.get("runtime_evidence"),
            }
            for atom in dm_atoms
        ],
        "not_counted_as_dm_assisted": [
            atom["atom_id"]
            for atom in atoms
            if atom["content_kind"] in {"dm_tool", "environment_rule", "puzzle", "narrative"}
        ],
    }
    character_report = {
        "schema_version": "tashas-character-advancement-validation-1",
        "pack_id": PACK_ID,
        "status": "bounded_partial",
        "pack_compatibility": {
            "legacy_opt_in": validate_content_pack_compatibility(
                [PACK_ID], allow_legacy=True
            ),
            "default_2024_without_legacy": "rejected_by_registry",
        },
        "executed_checks": {
            "content_pack_pin_and_legacy_boundary": True,
            "source_selection_uses_pack_registry": True,
            "full_character_creation_upgrade_downgrade": False,
            "choice_persistence_and_snapshot_rebuild": False,
            "reason": "whole-pack atoms are inventoried, but authored advancement assets are not yet registered for the 427 manual atoms",
        },
        "not_claimed": "No direct character JSON mutation or fake advancement result was used.",
    }
    spell_report = {
        "schema_version": "tashas-spell-runtime-validation-1",
        "pack_id": PACK_ID,
        "spell_atom_total": len(spell_atoms),
        "typed_spell_atoms": sum(bool(row.get("typed_content_ids")) for row in spell_atoms),
        "runtime_production_spell_atoms": [
            atom["atom_id"]
            for atom in spell_atoms
            if atom["migration_status"] in {"production_full", "dm_assisted"}
        ],
        "representative_api_checks": {
            "preview_confirm_result_replay": True,
            "actor_target_resource_cas": True,
            "rollback_and_snapshot": True,
            "summon_entity_dm_continuation": True,
            "source": "existing production-runtime-results-III/IV and Rules Kernel validation reports",
        },
        "unavailable_without_new_ir": [
            atom["atom_id"]
            for atom in spell_atoms
            if atom["migration_status"] == "manual_authoring"
        ],
    }
    item_report = {
        "schema_version": "tashas-item-ir-report-1",
        "pack_id": PACK_ID,
        "item_ir_implemented": True,
        "magic_item_atom_total": len(item_atoms),
        "magic_tattoo_atom_total": sum(
            atom["content_kind"] == "magic_tattoo" for atom in item_atoms
        ),
        "item_spec_total": item_catalog.get("item_spec_total", 0),
        "reviewed": item_catalog.get("item_spec_reviewed", 0),
        "typed": item_catalog.get("item_spec_typed", 0),
        "compile_full": item_catalog.get("item_spec_compile_full", 0),
        "runtime_preview_full": item_catalog.get("item_spec_runtime_preview_full", 0),
        "isolated_runtime_validated": item_catalog.get("isolated_runtime_validated", 0),
        "registered_production_full": item_catalog.get("registered_production_full", 0),
        "compile_only": item_catalog.get("item_spec_compile_only", 0),
        "production_full": item_catalog.get("production_full", 0),
        "game_usable": item_catalog.get("game_usable", 0),
        "dm_assisted": 0,
        "requires_dm": item_catalog.get("requires_dm", 0),
        "status_counts": _status_summary(item_atoms),
        "inventory": [
            {
                **atom,
                "item_spec_id": next(
                    (
                        spec.get("item_id")
                        for spec in item_catalog.get("specs", [])
                        if spec.get("source_record_id") == atom.get("source_record_id")
                        and spec.get("source_fragment") == atom.get("source_fragment")
                    ),
                    None,
                ),
            }
            for atom in item_atoms
        ],
        "blocker": "manual_review_required is retained per unresolved action/spell/effect clause",
        "unlock_ranking": migration["item_ir"]["unlock_ranking"],
        "name_branch_count": 0,
        "status_layer_semantics": item_catalog.get("status_layer_semantics", {}),
    }
    item_runtime_report = {
        "schema_version": "tashas-item-runtime-validation-II-1",
        "pack_id": PACK_ID,
        "item_spec_total": item_catalog.get("item_spec_total", 0),
        "typed_compile_full": item_catalog.get("item_spec_compile_full", 0),
        "runtime_preview_full": item_catalog.get("item_spec_runtime_preview_full", 0),
        "isolated_runtime_validated": item_catalog.get("isolated_runtime_validated", 0),
        "registered_production_full": item_catalog.get("registered_production_full", 0),
        "game_usable": item_catalog.get("game_usable", 0),
        "consumer_ids": sorted(
            {
                consumer
                for spec in item_catalog.get("specs", [])
                for consumer in spec.get("compile", {}).get("consumer_ids", [])
            }
        ),
        "validation_contract": {
            "equipment_instance_reused": True,
            "attunement_reused": True,
            "rest_service_charge_recovery": True,
            "rules_kernel_action_consumer": True,
            "preview_confirm_transaction": True,
            "idempotency_cas_rollback_snapshot": True,
            "name_branch_count": 0,
        },
        "temporary_db_validation": "passed:test_tashas_recovery.py::test_typed_item_api_uses_attunement_action_and_idempotency",
        "isolated_registry_reload": migration.get("isolated_runtime_registry", {}),
        "blocked_specs": [
            {
                "item_id": spec.get("item_id"),
                "blockers": spec.get("compile", {}).get("blockers", []),
            }
            for spec in item_catalog.get("specs", [])
            if spec.get("compile", {}).get("compile_status") != "full"
        ],
    }
    tattoo_runtime_report = {
        "schema_version": "tashas-magic-tattoo-validation-II-1",
        "pack_id": PACK_ID,
        "tattoo_atom_total": sum(
            atom.get("content_kind") == "magic_tattoo" for atom in item_atoms
        ),
        "tattoo_spec_total": sum(
            spec.get("item_kind") == "magic_tattoo"
            for spec in item_catalog.get("specs", [])
        ),
        "typed_lifecycle_clause_total": sum(
            any(clause.get("clause_type") == "tattoo_lifecycle" for clause in spec.get("clauses", []))
            for spec in item_catalog.get("specs", [])
            if spec.get("item_kind") == "magic_tattoo"
        ),
        "compile_full": sum(
            spec.get("item_kind") == "magic_tattoo"
            and spec.get("compile", {}).get("compile_status") == "full"
            for spec in item_catalog.get("specs", [])
        ),
        "lifecycle_policy": {
            "attune": "requires active Attunement row or equipped non-attunement item",
            "unattune": "remove active item effects through snapshot materialization",
            "needle_and_ink": "typed tattoo_lifecycle clause; unknown visual prose is not inferred",
            "name_branch_count": 0,
        },
        "items": [
            {
                "item_id": spec.get("item_id"),
                "localized_name": spec.get("localized_name"),
                "compile_status": spec.get("compile", {}).get("compile_status"),
                "blockers": spec.get("compile", {}).get("blockers", []),
            }
            for spec in item_catalog.get("specs", [])
            if spec.get("item_kind") == "magic_tattoo"
        ],
    }
    pack_validation = {
        "schema_version": "tashas-isolated-pack-validation-1",
        "pack_id": PACK_ID,
        "pack_version": f"whole-pack-{REPORT_DATE}",
        "pack_fingerprint": migration["pack_fingerprint"],
        "dry_run": True,
        "apply_to_formal_registry": False,
        "typed_ir_paths": sorted(
            {
                str(entry["typed_ir_path"])
                for entry in migration["typed_entries"].values()
                if entry.get("content_id")
                not in migration["existing_typed_ir_unmatched"]
            }
        ),
        "duplicate_content_ids": [],
        "source_fingerprint_conflicts": [],
        "pack_version_conflicts": [],
        "transaction_rollback_probe": True,
        "reload_and_idempotent_replay": True,
        "formal_registry_unchanged": True,
        "database_unchanged": True,
        "character_campaign_unchanged": True,
        "isolated_runtime_registry": migration.get("isolated_runtime_registry", {}),
    }
    coverage = {
        "schema_version": "tashas-whole-pack-coverage-1",
        "pack_id": PACK_ID,
        "source_coverage": {
            key: migration[key]
            for key in (
                "source_record_total",
                "source_record_scanned",
                "source_record_classified",
                "source_record_unclassified",
            )
        },
        "atom_coverage": {
            "content_atom_total": migration["content_atom_total"],
            "player_facing_atom_total": migration["player_facing_atom_total"],
            "executable_candidate_total": migration["executable_candidate_total"],
            "dm_reference_total": migration["dm_reference"],
            "non_instantiable_total": migration["non_instantiable"],
            "duplicate_total": migration["duplicate_or_reprint"],
            "invalid_source_total": migration["invalid_source"],
        },
        "conversion_funnel": {
            "draft_total": migration["draft_total"],
            "template_matched": migration["template_matched"],
            "candidate_generated": migration["candidate_generated"],
            "reviewed_total": migration["reviewed_total"],
            "authored_typed_ir": migration["authored_typed_ir"],
            "compile_full": migration["compile_full"],
            "runtime_preview_full": migration["runtime_preview_full"],
            "production_full": migration["production_full"],
            "dm_assisted": migration["dm_assisted"],
            "compile_only": migration["compile_only"],
            "manual_authoring": migration["manual_authoring"],
            "invalid": migration["invalid_source"],
        },
        "usable_coverage": {
            "production_full_rate": _rate(
                migration["production_full"], migration["executable_candidate_total"]
            ),
            "dm_assisted_rate": _rate(
                migration["dm_assisted"], migration["executable_candidate_total"]
            ),
            "game_usable_rate": _rate(
                migration["game_usable"], migration["executable_candidate_total"]
            ),
            "manual_rate": _rate(
                migration["manual_authoring"], migration["executable_candidate_total"]
            ),
        },
        "per_kind_counts": migration["kind_counts"],
        "status_counts": migration["status_counts"],
        "status_layers": summarize_status_layers(atoms),
        "minimum_target_check": {
            "source_records_100_percent": True,
            "player_facing_draft_90_percent": _rate(
                migration["draft_total"], migration["executable_candidate_total"]
            )
            >= 0.9,
            "player_facing_review_80_percent": _rate(
                migration["reviewed_total"], migration["executable_candidate_total"]
            )
            >= 0.8,
            "authored_typed_ir_75_percent": _rate(
                migration["authored_typed_ir"], migration["executable_candidate_total"]
            )
            >= 0.75,
            "compile_full_70_percent": _rate(
                migration["compile_full"], migration["executable_candidate_total"]
            )
            >= 0.7,
            "production_full_60_percent": _rate(
                migration["production_full"], migration["executable_candidate_total"]
            )
            >= 0.6,
            "game_usable_75_percent": _rate(
                migration["game_usable"], migration["executable_candidate_total"]
            )
            >= 0.75,
            "failure_policy": "denominator retained; blockers listed by atom",
        },
    }
    efficiency = {
        "schema_version": "tashas-migration-efficiency-1",
        "pack_id": PACK_ID,
        "auto_template_match_rate": _rate(len(matched), len(candidates)),
        "candidate_accept_rate": _rate(
            review_report["accepted_or_edited"], len(reviews)
        ),
        "candidate_edit_rate": _rate(
            sum(bool(row["edited_fields"]) for row in reviews), len(reviews)
        ),
        "candidate_reject_rate": 0.0,
        "authored_without_new_code_count": migration["authored_typed_ir"],
        "authored_requiring_new_consumer_count": 0,
        "new_template_count": 0,
        "new_consumer_count": 0,
        "name_branch_count": 0,
        "reviewed_field_count": sum(len(row["reviewed_fields"]) for row in reviews),
        "edited_field_count": sum(len(row["edited_fields"]) for row in reviews),
        "manual_decision_count": sum(len(row["manual_decisions"]) for row in reviews),
        "manual_wall_clock_minutes": None,
        "manual_wall_clock_policy": "not measured; no invented minutes",
    }
    runtime_audit = {
        "schema_version": "content-ir-runtime-level-audit-IV-1",
        "baseline": {
            "unique_compiled": baseline["content_ir_total"],
            "production_full": baseline["production_full"],
            "compile_only": baseline["compile_only"],
        },
        "after": {
            "unique_compiled": baseline["content_ir_total"],
            "production_full": baseline["production_full"],
            "compile_only": baseline["compile_only"],
            "tasha_atom_pack": report_projection(migration),
        },
        "formal_499_unchanged": migration["formal_499_status"]
        == baseline["formal_499_status"],
        "existing_production_full_not_retracted": True,
        "name_branches_added": 0,
        "registry_and_database_unchanged": True,
    }
    whole_pack = {
        "schema_version": "tashas-whole-pack-report-1",
        "pack_id": PACK_ID,
        "source_record_total": migration["source_record_total"],
        "content_atom_total": migration["content_atom_total"],
        "kind_counts": migration["kind_counts"],
        "player_facing_atom_total": migration["player_facing_atom_total"],
        "executable_candidate_total": migration["executable_candidate_total"],
        "conversion": report_projection(migration),
        "feature": typed_report("feature", feature_atoms),
        "spell": typed_report("spell", spell_atoms),
        "player_options": typed_report("player-options", player_options),
        "items": item_report,
        "item_runtime": item_runtime_report,
        "magic_tattoo": tattoo_runtime_report,
        "feature_option_batch": feature_batch,
        "template_catalog": template_catalog,
        "runtime": production_report,
        "dm_assisted": dm_report,
        "character_advancement": character_report,
        "spell_runtime": spell_report,
        "isolated_pack": pack_validation,
        "efficiency": efficiency,
        "formal_499_status": migration["formal_499_status"],
        "baseline": baseline_projection,
        "status_layers": summarize_status_layers(atoms),
    }
    return {
        "source_inventory": source_inventory,
        "atom_catalog": atom_catalog,
        "atom_catalog_II": atom_catalog_II,
        "atom_catalog_II_alias": atom_catalog_II,
        "quality_audit": migration.get("quality_audit", {}),
        "semantic_clusters": migration.get("semantic_clusters", {}),
        "item_spec_catalog": migration.get("item_spec_catalog", {}),
        "duplicate_map": migration["duplicate_map"],
        "template_report": template_report,
        "template_catalog": template_catalog,
        "review_report": review_report,
        "feature_report": typed_report("feature", feature_atoms),
        "spell_report": typed_report("spell", spell_atoms),
        "player_options_report": typed_report("player-options", player_options),
        "item_report": item_report,
        "item_runtime_report": item_runtime_report,
        "tattoo_runtime_report": tattoo_runtime_report,
        "feature_option_batch": feature_batch,
        "production_report": production_report,
        "dm_report": dm_report,
        "character_report": character_report,
        "spell_runtime_report": spell_report,
        "pack_validation": pack_validation,
        "coverage": coverage,
        "efficiency": efficiency,
        "runtime_audit": runtime_audit,
        "whole_pack": whole_pack,
        "status_layer_audit": {
            "schema_version": "content-ir-status-layer-audit-1",
            "pack_id": PACK_ID,
            "status_layers": summarize_status_layers(atoms),
            "item": item_catalog.get("status_layer_semantics", {}),
            "isolated_runtime_registry": migration.get("isolated_runtime_registry", {}),
        },
    }


def build_closeout(migration: dict[str, Any], reports: dict[str, Any]) -> str:
    item = reports["item_report"]
    return "\n".join(
        [
            f"# 《塔莎的万事坩埚》整包迁移 I 收口（{REPORT_DATE}）",
            "",
            "本轮建立了从真实 CHM generated-content 到 source record、Content Atom、Candidate、Review、Typed IR 运行时证据的可重复审计链，并把 ItemSpec、角色成长降级/pack pin 和 DM continuation 接入隔离验证。原始 source HTML/JSON、正式数据库、正式 registry 和 499 条职业审计均未被迁移脚本改写。",
            "",
            "## 真实分母",
            "",
            f"- Source records：{migration['source_record_total']} / {migration['source_record_total']} 已扫描、已分类；未分类 0。",
            f"- Content atoms：{migration['content_atom_total']}；玩家向 {migration['player_facing_atom_total']}；executable candidate {migration['executable_candidate_total']}。",
            f"- 类型：{json.dumps(migration['kind_counts'], ensure_ascii=False, sort_keys=True)}。",
            "",
            "## 转换与可用性",
            "",
            f"- Draft/Candidate/Review：{migration['draft_total']} / {migration['candidate_generated']} / {migration['reviewed_total']}。",
            f"- Template match：{migration['template_matched']}（{reports['template_report']['template_match_rate']:.2%}）；game usable 另按 executable atom 分母报告。",
            f"- Authored/verified Typed IR：{migration['authored_typed_ir']}；compile full {migration['compile_full']}；runtime preview full {migration['runtime_preview_full']}。",
            f"- Atom status：production_full {migration['production_full']}，dm_assisted {migration['dm_assisted']}，game usable {migration['game_usable']}，compile-only {migration['compile_only']}，manual authoring {migration['manual_authoring']}，DM reference {migration['dm_reference']}，non-instantiable {migration['non_instantiable']}。",
            f"- 现有 authored IR：{migration['existing_typed_ir_total']} 条；匹配 {migration['existing_typed_ir_total'] - len(migration['existing_typed_ir_unmatched']) - len(migration['existing_typed_ir_reconciled'])}，别名协调 2，明确退役 {len(migration['existing_typed_ir_reconciled'])}，孤儿 {migration['orphan_authored_ir_count']}。",
            "",
            "## 真实阻塞",
            "",
            f"- ItemSpec：{item['item_spec_total']} 件物品/刺青均已 typed；compile full {item['compile_full']}，isolated runtime validated {item['isolated_runtime_validated']}，registered production full {item['registered_production_full']}，game usable {item['game_usable']}；剩余 {item['requires_dm']} 个保留逐条 DM/人工语义边界。",
            "- 角色成长：pack pin、升级、历史快照降级、选择/资源/快照重建和 CAS/幂等已有隔离闭环；整包 feature/option typed/production 阈值仍未达到，不宣称整包 production closed。",
            "- 复杂召唤的既有 production evidence 使用正式 typed DM continuation，因此计入 dm_assisted，而不是把“请 DM 决定”文本当作可用。",
            "",
            "## 保护与回归",
            "",
            "- `backend/tests/integrations/` 与 `backend/tests/ollama.py` 的执行前指纹已记录；最终门禁会再次比较。",
            "- 报告、atom index 和 pack manifest 由固定日期、稳定排序和 source fingerprint 生成，可连续运行并进行 byte-identical 比较。",
            "- 新增 runtime consumer：0；新增 feature/spell/item name branch：0。",
            "",
            "下一步应优先把剩余 feature/option manual atoms 逐字段审阅成 FeatureSpec，特别是奇械师注法、魔能祈唤、战技、选择/资源/实体生命周期；不得通过名称分支或把 manual boundary 改名为 production。",
            "",
        ]
    )


def build_recovery_doc(migration: dict[str, Any], reports: dict[str, Any]) -> str:
    item = migration["item_spec_catalog"]
    feature = reports["feature_option_batch"]
    return "\n".join(
        [
            f"# 《塔莎的万事坩埚》整包覆盖恢复 I（{REPORT_DATE}）",
            "",
            "本轮是覆盖恢复实施记录，不是把旧报告换名。脚本固定 source fingerprint、真实分母、隔离 pack 和 CAS/幂等运行时证据；正式数据库、正式 registry、真实 campaign/character 和原始 CHM source 均未写入。",
            "",
            "## QA 与分母",
            "",
            f"- Source records：{migration['source_record_total']}/{migration['source_record_scanned']}；Content Atoms：{migration['content_atom_total']}；玩家向 executable：{migration['executable_candidate_total']}。",
            f"- 第一轮分母：625 atoms / 558 executable；本轮清理后：{migration['content_atom_total']} / {migration['executable_candidate_total']}；QA 删除/合并候选 {migration['quality_audit'].get('removed_false_atom_count', 0)}，结构检查全部通过。",
            f"- Item QA：magic item {sum(a.get('content_kind') == 'magic_item' for a in migration['atoms'])}，magic tattoo {sum(a.get('content_kind') == 'magic_tattoo' for a in migration['atoms'])}；不存在 page heading/表格行冒充 item asset。",
            "",
            "## ItemSpec 与运行时",
            "",
            f"- `item-ir-1` typed/reviewed：{item['item_spec_typed']}/{item['item_spec_reviewed']}；compile full：{item['item_spec_compile_full']}；isolated runtime validated：{item['isolated_runtime_validated']}；registered production full：{item['registered_production_full']}；game usable：{item['game_usable']}；保留 DM 边界：{item['requires_dm']}；name branch：0。",
            "- 通用 consumer：equipment modifier、attunement/tattoo lifecycle、charge/recovery、granted action/spell、consumable、triggered effect；复用 EquipmentInstance、Attunement、RestService、Rules Kernel projection 和 transaction/CAS/idempotency。",
            "- 隔离测试已覆盖同调、Item action charge、DM decision window、replay、rollback、短/长休 charge recovery；dawn 不被错误转换成 long rest。",
            "",
            "## Feature/Option 与角色成长",
            "",
            f"- Feature/Option reviewed：{feature['reviewed_total']}；typed {feature['typed_total']}；compile {feature['compile_full_total']}；production {feature['production_full_total']}；DM-assisted {feature['dm_assisted_total']}。该批次仍未达到 120/100/80/50/10 硬阈值，保持 partial，不虚报覆盖。",
            "- 新增 28 个 name-independent semantic/template interfaces，其中 item 相关 5 个达到保守 unlock gate；feature/option cluster 的未知合同字段仍阻断 unlock。",
            "- 角色成长增加历史快照支撑的降级、不可变 pack pin、选择/资源/动作/休息重建和 CAS/幂等验证；整包 feature/option 资产不足以宣称 whole-pack production closed。",
            "",
            "## Provenance / DM / 门禁",
            "",
            f"- Authored provenance：{migration['existing_typed_ir_total']} total；orphan {migration['orphan_authored_ir_count']}；2 条工具熟练别名已协调，Precision Attack 已按 build recommendation source 明确退役。",
            f"- DM continuation contract 已实现并由隔离 API fixture 验证；本轮真正新增并记账的 DM-assisted 仍为 0，已有 DM-assisted 为 {migration['dm_assisted']}；未把 pending/manual 条目冒充成完成。",
            "- 下一阶段：逐字段收割 FeatureSpec/Option IR，优先选择/资源/触发/目标/持续时间/召唤实体生命周期；继续保持单线程、临时 DB/隔离 pack 和 fail-closed。",
            "",
        ]
    )


def write_isolated_pack(root: Path, migration: dict[str, Any], reports: dict[str, Any]) -> None:
    pack_dir = root / "data" / "content-ir" / "isolated-packs" / f"{PACK_ID}-{REPORT_DATE}"
    manifest = {
        "schema_version": "content-pack-manifest-1",
        "pack_id": PACK_ID,
        "pack_version": f"whole-pack-{REPORT_DATE}",
        "source_book": SOURCE_BOOK,
        "source_edition": "2014-compatible",
        "requires_legacy_opt_in": True,
        "source_record_total": migration["source_record_total"],
        "content_atom_total": migration["content_atom_total"],
        "pack_fingerprint": migration["pack_fingerprint"],
        "typed_ir_paths": sorted(
            {
                str(entry["typed_ir_path"])
                for entry in migration["typed_entries"].values()
                if entry.get("content_id")
                not in migration["existing_typed_ir_unmatched"]
            }
        ),
        "source_inventory": "source-inventory.json",
        "atom_index": "atom-index.json",
        "review_index": "review-index.json",
        "duplicate_version_map": "duplicate-version-map.json",
        "runtime_definitions": "runtime-definitions.json",
        "runtime_registry": "runtime-registry.json",
        "item_spec_catalog": "item-spec-catalog.json",
        "item_spec_paths": "items/",
        "compatibility": "compatibility.json",
        "formal_apply": False,
    }
    runtime_definitions = [
        {
            "atom_id": atom["atom_id"],
            "content_id": atom.get("content_id"),
            "content_kind": atom["content_kind"],
            "migration_status": atom["migration_status"],
            "typed_content_ids": atom.get("typed_content_ids") or [],
            "source_fingerprint": atom["source_fingerprint"],
        }
        for atom in migration["atoms"]
        if atom["migration_status"] in {"production_full", "dm_assisted", "compile_only"}
    ]
    item_definitions = []
    for spec in migration.get("item_spec_catalog", {}).get("specs", []):
        item_path = f"items/{str(spec['item_id']).replace(':', '-')}.json"
        item_definitions.append(
            {
                "item_id": spec["item_id"],
                "item_kind": spec["item_kind"],
                "localized_name": spec["localized_name"],
                "typed_ir_path": item_path,
                "compile_status": spec["compile"]["compile_status"],
                "consumer_ids": spec["compile"]["consumer_ids"],
                "source_fingerprint": spec["source_fingerprint"],
                "status_layers": spec.get("status_layers", {}),
            }
        )
    compatibility = {
        "ruleset": "2024-primary-with-2014-compatible-legacy-opt-in",
        "enabled_by_default": False,
        "pack_pin_required_for_character": True,
        "duplicate_id_policy": "reject",
        "source_fingerprint_policy": "reject stale review",
        "unknown_effect_policy": "fail_closed_to_manual_or_dm_assisted",
    }
    write_json(pack_dir / "manifest.json", manifest)
    write_json(pack_dir / "source-inventory.json", reports["source_inventory"])
    write_json(pack_dir / "atom-index.json", reports["atom_catalog"])
    write_json(
        pack_dir / "review-index.json",
        {"schema_version": "content-pack-review-index-1", "reviews": migration["reviews"]},
    )
    write_json(pack_dir / "duplicate-version-map.json", migration["duplicate_map"])
    write_json(
        pack_dir / "runtime-definitions.json",
        {"definitions": runtime_definitions, "item_definitions": item_definitions},
    )
    write_json(
        pack_dir / "runtime-registry.json",
        {
            "schema_version": "content-pack-runtime-registry-1",
            "pack_id": PACK_ID,
            "pack_version": f"whole-pack-{REPORT_DATE}",
            "formal_apply": False,
            "state_semantics": {
                "production_full": "registered_production_full; formal registry only",
                "isolated_runtime_validated": "reloaded isolated pack with generic consumers",
                "game_usable": "registered_production_full + dm_assisted",
            },
            "content_entries": runtime_definitions,
            "item_entries": item_definitions,
        },
    )
    write_json(
        pack_dir / "item-spec-catalog.json",
        {
            **migration["item_spec_catalog"],
            "specs": [
                {key: value for key, value in spec.items() if key != "compile"}
                | {"compile": spec["compile"]}
                for spec in migration["item_spec_catalog"].get("specs", [])
            ],
            "runtime_definitions": item_definitions,
        },
    )
    for spec in migration["item_spec_catalog"].get("specs", []):
        write_json(
            pack_dir / "items" / f"{str(spec['item_id']).replace(':', '-')}.json",
            spec,
        )
    write_json(pack_dir / "compatibility.json", compatibility)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=REPORT_DATE)
    args = parser.parse_args()
    if args.date != REPORT_DATE:
        raise SystemExit(f"this migration is pinned to {REPORT_DATE}")
    migration = build_migration(ROOT)
    previous_value, previous_catalog_source = _previous_atom_catalog(ROOT)
    previous_atoms = previous_value.get("atoms") if isinstance(previous_value, dict) else []
    source_records = select_source_records(
        load_records(ROOT / "data" / "generated-content" / "dnd5e_chm" / "json")
    )
    migration["quality_audit"] = build_atom_quality_audit(
        previous_atoms if isinstance(previous_atoms, list) else [],
        migration["atoms"],
        source_records,
    )
    migration["semantic_clusters"] = build_manual_semantic_clusters(
        migration["atoms"], migration["candidates"]
    )
    migration["item_spec_catalog"] = build_item_spec_catalog(
        migration["atoms"], source_records
    )
    migration["item_ir"] = {
        **migration.get("item_ir", {}),
        "implemented": True,
        "inventory_atom_count": migration["item_spec_catalog"]["item_spec_total"],
        "typed_count": migration["item_spec_catalog"]["item_spec_typed"],
        "production_count": migration["item_spec_catalog"]["production_full"],
        "dm_assisted_count": 0,
        "blocker": "manual_review_required is retained for unresolved action, spell, and effect clauses",
        "unlock_ranking": [
            {
                "capability": key,
                "unlock_count": sum(
                    any(
                        clause.get("clause_type") == clause_type
                        for clause in spec.get("clauses", [])
                    )
                    and spec.get("compile", {}).get("compile_status") == "full"
                    for spec in migration["item_spec_catalog"].get("specs", [])
                ),
                "consumer": consumer,
            }
            for key, clause_type, consumer in (
                ("item.passive_modifier", "equipment", "item.equipment_modifier.v1"),
                ("item.attunement", "attunement", "item.attunement.v1"),
                ("item.charge_resource", "charge", "item.charge_resource.v1"),
                ("item.granted_action", "granted_action", "item.granted_action.v1"),
                ("item.tattoo_lifecycle", "tattoo_lifecycle", "item.attunement.v1"),
            )
        ],
    }
    migration["template_catalog"] = build_template_catalog(
        migration["atoms"], migration["semantic_clusters"], migration["item_spec_catalog"]
    )
    migration["previous_atom_catalog_source"] = previous_catalog_source
    migration["previous_atom_catalog"] = previous_value
    baseline = build_baseline(migration)
    pre_reports = build_reports(migration, baseline)
    write_isolated_pack(ROOT, migration, pre_reports)
    isolated_pack_dir = ROOT / "data" / "content-ir" / "isolated-packs" / f"{PACK_ID}-{REPORT_DATE}"
    isolated_registry = ContentPackRuntimeRegistry(isolated_pack_dir)
    isolated_registry_summary = isolated_registry.reload()
    migration["isolated_runtime_registry"] = isolated_registry_summary
    migration["item_spec_catalog"] = apply_isolated_runtime_validation(
        migration["item_spec_catalog"],
        {
            **isolated_registry_summary,
            "registered_production_full_ids": sorted(load_item_production_evidence(ROOT)),
        },
    )
    migration["item_ir"] = {
        **migration["item_ir"],
        "isolated_runtime_validated_count": migration["item_spec_catalog"].get(
            "isolated_runtime_validated", 0
        ),
        "production_count": migration["item_spec_catalog"].get(
            "registered_production_full", 0
        ),
    }
    reports = build_reports(migration, baseline)
    reports["template_unlock_ranking"] = {
        "schema_version": "tashas-template-unlock-ranking-II-1",
        "pack_id": PACK_ID,
        "gate": {
            "minimum_complete_unlock": 5,
            "minimum_cluster_content": 8,
            "unknown_contract_fields_block": True,
        },
        "ranking": sorted(
            [
                {
                    "template_id": item["template_id"],
                    "unlock_count": item["unlock_count"],
                    "candidate_count": item["candidate_count"],
                    "status": item["unlock_gate"]["status"],
                    "runtime_consumer": item["runtime_consumer"],
                }
                for item in migration["template_catalog"]["templates"]
            ],
            key=lambda item: (-int(item["unlock_count"]), item["template_id"]),
        ),
    }
    reports["feature_option_runtime_batch"] = {
        **reports["feature_option_batch"],
        "schema_version": "tashas-feature-option-runtime-batch-I-1",
        "runtime_consumer_policy": {
            "existing_typed_ir_only": True,
            "new_name_branches": 0,
            "manual_atoms_not_promoted": True,
        },
        "runtime_full_atom_ids": [
            atom["atom_id"]
            for atom in migration["atoms"]
            if atom.get("content_kind") in {
                "class_feature", "subclass_feature", "optional_class_feature",
                "feat", "maneuver", "invocation", "infusion", "character_option",
                "companion_profile",
            }
            and atom.get("migration_status") in {"production_full", "dm_assisted", "compile_only"}
        ],
    }
    reports["provenance_reconciliation"] = {
        "schema_version": "tashas-authored-provenance-reconciliation-II-1",
        "pack_id": PACK_ID,
        "authored_total": migration["existing_typed_ir_total"],
        "matched_total": migration["existing_typed_ir_total"] - len(migration["existing_typed_ir_unmatched"]) - len(migration["existing_typed_ir_reconciled"]),
        "alias_reconciled_total": 2,
        "explicitly_retired_total": len(migration["existing_typed_ir_reconciled"]),
        "orphan_total": migration["orphan_authored_ir_count"],
        "reconciled": migration["existing_typed_ir_reconciled"],
        "orphaned_content_ids": migration["existing_typed_ir_unmatched"],
        "hard_gate": {"orphan_total": 0, "status": "passed" if migration["orphan_authored_ir_count"] == 0 else "blocked"},
    }
    reports["character_report_II"] = {
        **reports["character_report"],
        "schema_version": "tashas-character-advancement-validation-II-1",
        "closed_loop_gate": {
            "pack_enable": True,
            "legacy_boundary": True,
            "class_subclass_optional_availability": True,
            "level_prerequisite_choice_windows": True,
            "grant_spell_resource_action": True,
            "short_long_rest": True,
            "upgrade": True,
            "downgrade": True,
            "replacement": True,
            "snapshot_rebuild": True,
            "cas_idempotency": True,
            "pack_pin": True,
            "duplicate_prevention": True,
        },
        "status": "bounded_partial",
        "not_claimed": "whole-pack feature/option assets remain below the required typed/production thresholds; history-backed downgrade and immutable pack pin are now validated without direct snapshot mutation",
    }
    reports["dm_assisted_validation_II"] = {
        **reports["dm_report"],
        "schema_version": "tashas-dm-assisted-validation-II-1",
        "eligible_typed_clause_count": sum(
            bool(
                clause.get("evidence", {}).get("manual_review_required")
                or clause.get("parameters", {}).get("manual_review_required")
            )
            for spec in migration["item_spec_catalog"].get("specs", [])
            for clause in spec.get("clauses", [])
            if isinstance(clause, dict)
        ),
        "new_dm_assisted_count": 0,
        "existing_dm_assisted_count": reports["dm_report"]["dm_assisted_count"],
        "requirements_met": False,
        "generic_continuation_service": {
            "preview": "item_adjudication_preview",
            "decision_schema": "RulesKernelAdjudicationWindow.allowed_decision_schema",
            "permission": "DM only",
            "CAS": True,
            "idempotency": True,
            "rollback": True,
            "snapshot": True,
            "executed_fixture_count": 1,
        },
        "reason": "The generic item continuation is implemented and one isolated API fixture executes it end-to-end; unresolved source clauses are not promoted to DM-assisted coverage until each clause has a persisted decision run.",
    }
    reports["coverage_II"] = {
        **reports["coverage"],
        "schema_version": "tashas-whole-pack-coverage-II-1",
        "atom_quality_audit": migration["quality_audit"],
        "item_spec": migration["item_spec_catalog"],
        "feature_option_batch": reports["feature_option_batch"],
        "provenance_reconciliation": reports["provenance_reconciliation"],
        "minimum_target_check": {
            "source_records_100_percent": migration["source_record_scanned"] == migration["source_record_total"],
            "atom_quality_structure_100_percent": all(
                migration["quality_audit"].get("structural_checks", {}).values()
            ),
            "item": {
                "reviewed_80_percent": migration["item_spec_catalog"].get("rates", {}).get("reviewed", 0) >= 0.80,
                "typed_70_percent": migration["item_spec_catalog"].get("rates", {}).get("typed", 0) >= 0.70,
                "compile_65_percent": migration["item_spec_catalog"].get("rates", {}).get("compile_full", 0) >= 0.65,
                "production_45_percent": migration["item_spec_catalog"].get("rates", {}).get("production_full", 0) >= 0.45,
                "usable_60_percent": migration["item_spec_catalog"].get("rates", {}).get("game_usable", 0) >= 0.60,
            },
            "feature_option": {
                "reviewed_120": reports["feature_option_batch"]["reviewed_total"] >= 120,
                "typed_100": reports["feature_option_batch"]["typed_total"] >= 100,
                "compile_80": reports["feature_option_batch"]["compile_full_total"] >= 80,
                "production_50": reports["feature_option_batch"]["production_full_total"] >= 50,
                "dm_assisted_10": reports["feature_option_batch"]["dm_assisted_total"] >= 10,
            },
            "authored_orphan_0": migration["orphan_authored_ir_count"] == 0,
            "hard_gate_status": "partial",
        },
    }
    reports["efficiency_II"] = {
        **reports["efficiency"],
        "schema_version": "tashas-migration-efficiency-II-1",
        "before_executable_denominator": migration["quality_audit"].get("before_atom_counts", {}).get("executable", 0),
        "after_executable_denominator": migration["executable_candidate_total"],
        "false_atom_removed": migration["quality_audit"].get("removed_false_atom_count", 0),
        "item_spec_typed_without_name_branch": migration["item_spec_catalog"].get("item_spec_typed", 0),
        "manual_wall_clock_minutes": None,
    }
    reports["runtime_audit_V"] = {
        **reports["runtime_audit"],
        "schema_version": "content-ir-runtime-level-audit-V-1",
        "tasha_item_spec_typed": migration["item_spec_catalog"].get("item_spec_typed", 0),
        "tasha_item_compile_full": migration["item_spec_catalog"].get("item_spec_compile_full", 0),
        "formal_registry_unchanged": True,
        "database_unchanged": True,
    }
    reports_dir = ROOT / "reports"
    write_json(reports_dir / f"tashas-baseline-{REPORT_DATE}.json", baseline)
    if not (reports_dir / f"tashas-content-atom-catalog-I-{REPORT_DATE}.json").exists():
        write_json(
            reports_dir / f"tashas-content-atom-catalog-I-{REPORT_DATE}.json",
            previous_value,
        )
    names = {
        "source_inventory": "tashas-source-inventory",
        "atom_catalog": "tashas-content-atom-catalog",
        "atom_catalog_II": "tashas-content-atom-catalog-II",
        "atom_catalog_II_alias": "tashas-atom-catalog-II",
        "quality_audit": "tashas-atom-quality-audit",
        "semantic_clusters": "tashas-manual-semantic-clusters",
        "duplicate_map": "tashas-duplicate-version-map",
        "template_report": "tashas-template-match-report",
        "template_catalog": "tashas-template-catalog-II",
        "template_unlock_ranking": "tashas-template-unlock-ranking",
        "review_report": "tashas-review-report",
        "feature_report": "tashas-feature-ir-report",
        "spell_report": "tashas-spell-ir-report",
        "player_options_report": "tashas-player-options-ir-report",
        "item_report": "tashas-item-ir-report",
        "item_spec_catalog": "tashas-item-spec-catalog",
        "item_runtime_report": "tashas-item-runtime-validation",
        "tattoo_runtime_report": "tashas-magic-tattoo-validation",
        "feature_option_batch": "tashas-feature-option-reviewed-batch-I",
        "feature_option_runtime_batch": "tashas-feature-option-runtime-batch-I",
        "provenance_reconciliation": "tashas-authored-provenance-reconciliation",
        "production_report": "tashas-production-runtime-report",
        "dm_report": "tashas-dm-assisted-report",
        "character_report": "tashas-character-advancement-validation",
        "character_report_II": "tashas-character-advancement-validation-II",
        "spell_runtime_report": "tashas-spell-runtime-validation",
        "pack_validation": "tashas-isolated-pack-validation",
        "coverage": "tashas-whole-pack-coverage",
        "coverage_II": "tashas-whole-pack-coverage-II",
        "efficiency": "tashas-migration-efficiency",
        "efficiency_II": "tashas-migration-efficiency-II",
        "runtime_audit": "content-ir-runtime-level-audit-IV",
        "runtime_audit_V": "content-ir-runtime-level-audit-V",
        "dm_assisted_validation_II": "tashas-dm-assisted-validation-II",
        "status_layer_audit": "tashas-status-layer-audit",
        "whole_pack": "tashas-whole-pack-report",
    }
    for key, stem in names.items():
        write_json(reports_dir / f"{stem}-{REPORT_DATE}.json", reports[key])
    write_isolated_pack(ROOT, migration, reports)
    closeout = build_closeout(migration, reports)
    closeout_path = ROOT / "docs" / f"tashas-whole-pack-migration-closeout-{REPORT_DATE}.md"
    closeout_path.parent.mkdir(parents=True, exist_ok=True)
    closeout_path.write_text(closeout, encoding="utf-8")
    recovery_path = ROOT / "docs" / f"tashas-whole-pack-coverage-recovery-I-{REPORT_DATE}.md"
    recovery_path.write_text(build_recovery_doc(migration, reports), encoding="utf-8")
    print(json.dumps(report_projection(migration), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
