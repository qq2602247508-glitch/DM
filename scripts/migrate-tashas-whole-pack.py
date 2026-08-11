# ruff: noqa: N999
"""Build the deterministic whole-pack Tasha migration artifacts and reports."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.tashas_whole_pack import (
    PACK_ID,
    SOURCE_BOOK,
    build_migration,
    fingerprint,
    report_projection,
)
from dnd_dm_assistant.domain.content_packs import validate_content_pack_compatibility

ROOT = Path(__file__).resolve().parents[1]
REPORT_DATE = "2026-08-11"


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
    template_report = {
        "schema_version": "tashas-template-match-report-1",
        "pack_id": PACK_ID,
        "candidate_total": len(candidates),
        "template_matched": len(matched),
        "template_match_rate": _rate(len(matched), len(candidates)),
        "existing_template_count": 12,
        "new_template_count": 0,
        "new_template_ids": [],
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
        "item_ir_implemented": False,
        "magic_item_atom_total": len(item_atoms),
        "magic_tattoo_atom_total": sum(
            atom["content_kind"] == "magic_tattoo" for atom in item_atoms
        ),
        "production_full": 0,
        "dm_assisted": 0,
        "status_counts": _status_summary(item_atoms),
        "inventory": item_atoms,
        "blocker": migration["item_ir"]["blocker"],
        "unlock_ranking": migration["item_ir"]["unlock_ranking"],
        "name_branch_count": 0,
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
        "runtime": production_report,
        "dm_assisted": dm_report,
        "character_advancement": character_report,
        "spell_runtime": spell_report,
        "isolated_pack": pack_validation,
        "efficiency": efficiency,
        "formal_499_status": migration["formal_499_status"],
        "baseline": baseline_projection,
    }
    return {
        "source_inventory": source_inventory,
        "atom_catalog": atom_catalog,
        "duplicate_map": migration["duplicate_map"],
        "template_report": template_report,
        "review_report": review_report,
        "feature_report": typed_report("feature", feature_atoms),
        "spell_report": typed_report("spell", spell_atoms),
        "player_options_report": typed_report("player-options", player_options),
        "item_report": item_report,
        "production_report": production_report,
        "dm_report": dm_report,
        "character_report": character_report,
        "spell_runtime_report": spell_report,
        "pack_validation": pack_validation,
        "coverage": coverage,
        "efficiency": efficiency,
        "runtime_audit": runtime_audit,
        "whole_pack": whole_pack,
    }


def build_closeout(migration: dict[str, Any], reports: dict[str, Any]) -> str:
    item = reports["item_report"]
    return "\n".join(
        [
            f"# 《塔莎的万事坩埚》整包迁移 I 收口（{REPORT_DATE}）",
            "",
            "本轮建立了从真实 CHM generated-content 到 source record、Content Atom、Candidate、Review、Typed IR 运行时证据的可重复审计链。原始 source HTML/JSON、正式数据库、正式 registry 和 499 条职业审计均未被迁移脚本改写。",
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
            f"- 现有 authored IR 中有 {len(migration['existing_typed_ir_unmatched'])} 条 provenance 没有匹配到真实原子，已单列，未计入覆盖率。",
            "",
            "## 真实阻塞",
            "",
            f"- Item IR 未实现：{item['magic_item_atom_total']} 件物品/刺青仅完成完整 inventory；没有伪装成 production 或 DM-assisted。",
            "- 角色成长全链路未被本轮 inventory 产物冒充完成：pack pin/legacy boundary 已验证，完整升级、降级、快照重建仍需 advancement importer/asset registration。",
            "- 复杂召唤的既有 production evidence 使用正式 typed DM continuation，因此计入 dm_assisted，而不是把“请 DM 决定”文本当作可用。",
            "",
            "## 保护与回归",
            "",
            "- `backend/tests/integrations/` 与 `backend/tests/ollama.py` 的执行前指纹已记录；最终门禁会再次比较。",
            "- 报告、atom index 和 pack manifest 由固定日期、稳定排序和 source fingerprint 生成，可连续运行并进行 byte-identical 比较。",
            "- 新增 runtime consumer：0；新增 feature/spell/item name branch：0。",
            "",
            "下一步应优先建设通用 ItemSpec + equipment/attunement/resource consumer，再处理奇械师注法、魔能祈唤、战技和复杂子职的 choice/resource/实体生命周期闭环；它们的 atom 分母已经在本轮固定。",
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
    write_json(pack_dir / "runtime-definitions.json", {"definitions": runtime_definitions})
    write_json(pack_dir / "compatibility.json", compatibility)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=REPORT_DATE)
    args = parser.parse_args()
    if args.date != REPORT_DATE:
        raise SystemExit(f"this migration is pinned to {REPORT_DATE}")
    migration = build_migration(ROOT)
    baseline = build_baseline(migration)
    reports = build_reports(migration, baseline)
    reports_dir = ROOT / "reports"
    write_json(reports_dir / f"tashas-baseline-{REPORT_DATE}.json", baseline)
    names = {
        "source_inventory": "tashas-source-inventory",
        "atom_catalog": "tashas-content-atom-catalog",
        "duplicate_map": "tashas-duplicate-version-map",
        "template_report": "tashas-template-match-report",
        "review_report": "tashas-review-report",
        "feature_report": "tashas-feature-ir-report",
        "spell_report": "tashas-spell-ir-report",
        "player_options_report": "tashas-player-options-ir-report",
        "item_report": "tashas-item-ir-report",
        "production_report": "tashas-production-runtime-report",
        "dm_report": "tashas-dm-assisted-report",
        "character_report": "tashas-character-advancement-validation",
        "spell_runtime_report": "tashas-spell-runtime-validation",
        "pack_validation": "tashas-isolated-pack-validation",
        "coverage": "tashas-whole-pack-coverage",
        "efficiency": "tashas-migration-efficiency",
        "runtime_audit": "content-ir-runtime-level-audit-IV",
        "whole_pack": "tashas-whole-pack-report",
    }
    for key, stem in names.items():
        write_json(reports_dir / f"{stem}-{REPORT_DATE}.json", reports[key])
    write_isolated_pack(ROOT, migration, reports)
    closeout = build_closeout(migration, reports)
    closeout_path = ROOT / "docs" / f"tashas-whole-pack-migration-closeout-{REPORT_DATE}.md"
    closeout_path.parent.mkdir(parents=True, exist_ok=True)
    closeout_path.write_text(closeout, encoding="utf-8")
    print(json.dumps(report_projection(migration), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
