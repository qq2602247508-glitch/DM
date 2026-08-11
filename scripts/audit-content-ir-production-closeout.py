# ruff: noqa: N999
"""Emit the per-asset production blocker audit and generic unlock ranking."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_production_registry import (
    production_consumer_descriptors,
)

ROOT = Path(__file__).resolve().parents[1]
COMPILE_II = ROOT / "data/content-ir/compiled/batch-II/compile-result.json"
COMPILE_III = ROOT / "data/content-ir/compiled/batch-III/compile-result.json"
PRODUCTION_II = ROOT / "data/content-ir/compiled/batch-II/production-runtime-results.json"
PRODUCTION_III = ROOT / "data/content-ir/compiled/production-runtime-results-III.json"
REPORT_ROOT = ROOT / "reports"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rows(path: Path) -> list[dict[str, Any]]:
    return [dict(item) for item in json.loads(path.read_text(encoding="utf-8"))["results"]]


def _parameters(block: dict[str, Any]) -> dict[str, Any]:
    raw = block.get("parameters")
    return dict(raw) if isinstance(raw, dict) else dict(block)


def _runtime_blocks(runtime: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    resolution = runtime.get("resolution") if isinstance(runtime, dict) else None
    if not isinstance(resolution, dict):
        return {}
    return {
        str(key): [dict(item) for item in value if isinstance(item, dict)]
        for key, value in resolution.items()
        if isinstance(value, list)
    }


def _clause_types(row: dict[str, Any]) -> list[str]:
    typed = row.get("typed_ir")
    clauses = typed.get("clauses") if isinstance(typed, dict) else None
    if isinstance(clauses, list):
        return sorted({str(item.get("type")) for item in clauses if isinstance(item, dict) and item.get("type")})
    return sorted(
        {
            str(item.get("type"))
            for values in _runtime_blocks(row.get("runtime_spell_definition") or row.get("runtime_definition") or {}).values()
            for item in values
            if item.get("type")
        }
    )


def _content_id(row: dict[str, Any]) -> str:
    return str(row.get("spell_id") or row.get("feature_id") or "")


def _source(row: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    typed = row.get("typed_ir") if isinstance(row.get("typed_ir"), dict) else {}
    source = runtime.get("source") if isinstance(runtime.get("source"), dict) else {}
    return {
        "source_book": typed.get("source_book") or source.get("source_book"),
        "source_path": typed.get("source_path") or source.get("source_path"),
        "source_record_id": typed.get("source_record_id") or source.get("source_record_id"),
        "source_fingerprint": typed.get("source_fingerprint") or source.get("source_fingerprint"),
    }


def _contracts(row: dict[str, Any], runtime: dict[str, Any], clause_types: list[str]) -> dict[str, Any]:
    blocks = _runtime_blocks(runtime)
    effect_blocks = [_parameters(item) for item in blocks.get("effects", [])]
    return {
        "action_economy": sorted(
            {
                str(parameters.get("action_economy"))
                for values in blocks.values()
                for parameters in (_parameters(item) for item in values)
                if parameters.get("action_economy")
            }
        ),
        "resource": runtime.get("resources") or runtime.get("resource_key") or {},
        "target": blocks.get("target_selection") or runtime.get("target") or {},
        "roll": {
            "attack": blocks.get("attack_roll") or [],
            "save": blocks.get("saving_throw") or [],
            "expressions": sorted(
                {
                    str(parameters.get("expression") or parameters.get("damage") or parameters.get("healing"))
                    for parameters in effect_blocks
                    if parameters.get("expression") or parameters.get("damage") or parameters.get("healing")
                }
            ),
        },
        "settlement": effect_blocks,
        "condition": [
            parameters
            for parameters in effect_blocks
            if parameters.get("condition") or parameters.get("type") in {"condition", "apply_condition"}
        ],
        "persistence": {
            "duration": runtime.get("duration"),
            "concentration": bool(runtime.get("concentration")),
            "feature_registry": row.get("kind") == "feature",
        },
        "cas": {"character": row.get("kind") == "spell", "actor_combatant": True, "target_combatant": True},
        "idempotency": {"scope": "campaign:content-ir:request", "replay": "same operation returns already_applied"},
        "snapshot": {"hp": True, "temporary_hp": True, "conditions": bool("apply_condition" in clause_types), "resource_or_slot": row.get("kind") == "spell"},
    }


def _candidate_consumers(row: dict[str, Any], runtime: dict[str, Any], clause_types: list[str]) -> list[str]:
    blocks = _runtime_blocks(runtime)
    result: set[str] = set()
    if row.get("kind") == "spell":
        if any(parameters.get("type") in {"damage", "healing", "temporary_hp"} for parameters in (_parameters(item) for item in blocks.get("effects", []))):
            result.add("combat_engine.damage_heal.v1")
        if blocks.get("area") or any(_parameters(item).get("type") == "area" for item in blocks.get("effects", [])):
            result.add("combat_engine.area_damage.v1")
        if blocks.get("concentration"):
            result.add("spell_economy.concentration.v1")
        if "apply_condition" in clause_types:
            result.add("combat_engine.condition_lifecycle.v1")
    else:
        runtime_definition = row.get("runtime_definition") or {}
        if runtime_definition.get("attack_riders"):
            result.add("combat_engine.damage_heal.v1")
        if runtime_definition.get("actions"):
            result.add("combat_engine.feature_action.v1")
        if runtime_definition.get("triggers"):
            result.add("combat_engine.condition_lifecycle.v1")
        if (runtime_definition.get("combat_start") or {}).get("defenses") or (runtime_definition.get("combat_start") or {}).get("modifiers"):
            result.add("combat_engine.feature_action.v1")
    return sorted(result)


def _blockers(row: dict[str, Any], runtime: dict[str, Any], clause_types: list[str], production: bool) -> list[dict[str, str]]:
    if production:
        return []
    blocks = _runtime_blocks(runtime)
    result: list[dict[str, str]] = []
    if not runtime or runtime.get("execution_status") not in {None, "ready"}:
        result.append({"category": "runtime_schema", "detail": "runtime definition is not ready"})
    if not _candidate_consumers(row, runtime, clause_types):
        result.append({"category": "missing_consumer", "detail": "no closed production consumer matches the executable clauses"})
    if "target_selection" in clause_types and not blocks.get("target_selection") and row.get("kind") == "spell":
        result.append({"category": "target_contract", "detail": "target selection is not materialized as an authoritative block"})
    if any(item in clause_types for item in ("choice", "summon_or_creation", "movement", "teleport", "transformation")):
        result.append({"category": "manual_branch", "detail": "choice, summon, movement or transformation requires an explicit runtime consumer"})
    if any(item in clause_types for item in ("duration", "concentration")) and row.get("kind") == "spell":
        result.append({"category": "lifecycle_proof", "detail": "duration/concentration needs a production lifecycle loop before promotion"})
    if not result:
        result.append({"category": "production_not_proven", "detail": "compile and preview are full, but no production confirm evidence is recorded"})
    return result


def _entry(row: dict[str, Any], production_ids: set[str], *, baseline: bool) -> dict[str, Any]:
    runtime = dict(row.get("runtime_spell_definition") or row.get("runtime_definition") or {})
    clause_types = _clause_types(row)
    candidates = _candidate_consumers(row, runtime, clause_types)
    content_id = _content_id(row)
    production = content_id in production_ids
    source = _source(row, runtime)
    return {
        "content_id": content_id,
        "kind": row.get("kind"),
        "source": source,
        "template_id": f"{row.get('kind')}:runtime:{runtime.get('runtime_schema_version') or 'feature-runtime-1'}",
        "clause_types": clause_types,
        "compile_status": row.get("compile_status"),
        "runtime_preview_status": "full" if row.get("materialized") else "not_materialized",
        "production_status": "full" if production else "compile_only",
        "consumer_ids": candidates if production else [],
        "missing_consumers": [] if production else candidates,
        "contracts": _contracts(row, runtime, clause_types),
        "blockers": _blockers(row, runtime, clause_types, production),
        "completion_unlock_candidates": candidates,
        "baseline_scope": "existing_100" if baseline else "new_authored",
    }


def main() -> int:
    old_rows = _rows(COMPILE_II)
    new_rows = _rows(COMPILE_III)
    old_production = set(json.loads(PRODUCTION_II.read_text(encoding="utf-8"))["production_runtime_full_ids"])
    new_production = set(json.loads(PRODUCTION_III.read_text(encoding="utf-8"))["production_runtime_full_ids"])
    production_ids = old_production | new_production
    new_authored_ids = {_content_id(row) for row in new_rows}
    existing_production_after = production_ids - new_authored_ids
    entries = [
        *[_entry(row, production_ids, baseline=True) for row in old_rows],
        *[_entry(row, production_ids, baseline=False) for row in new_rows],
    ]
    entries.sort(key=lambda item: item["content_id"])
    candidate_counts: Counter[str] = Counter()
    unlocked_counts: Counter[str] = Counter()
    blocked_counts: Counter[str] = Counter()
    for entry in entries:
        for consumer in entry["completion_unlock_candidates"]:
            candidate_counts[consumer] += 1
            if entry["production_status"] == "full":
                unlocked_counts[consumer] += 1
            else:
                blocked_counts[consumer] += 1
    major_consumers = [consumer for consumer, count in candidate_counts.items() if count >= 8]
    ranking = []
    descriptors = production_consumer_descriptors()
    for consumer in sorted(major_consumers, key=lambda item: (-unlocked_counts[item], -candidate_counts[item], item))[:4]:
        descriptor = dict(descriptors[consumer])
        ranking.append(
            {
                "consumer_id": consumer,
                "candidate_content_count": candidate_counts[consumer],
                "blocked_content_count": blocked_counts[consumer],
                "unlocked_full_content_count": unlocked_counts[consumer],
                "implementation_risk": "medium" if consumer == "combat_engine.area_damage.v1" else "low",
                "required_modules": list(descriptor.get("required_services", [])),
                "registry_contract": descriptor,
            }
        )
    audit = {
        "schema_version": "content-ir-production-blocker-audit-1",
        "generated_for": "2026-08-11 compile-full-to-production-runtime-full closeout",
        "layers": {
            "existing_100": {"compile_full": 100, "runtime_preview_full": 100, "production_runtime_full_before": 20, "production_runtime_full_after": len(existing_production_after)},
            "new_authored": {"authored_typed_ir": len(new_rows), "compile_full": sum(row.get("compile_status") == "full" for row in new_rows), "runtime_preview_full": sum(bool(row.get("materialized")) for row in new_rows), "production_runtime_full": sum(_content_id(row) in new_production for row in new_rows)},
            "formal_feature_audit_unchanged": {"total": 499, "full": 328, "partial": 110, "dm_only": 61},
        },
        "entry_count": len(entries),
        "entries": entries,
        "blocker_category_counts": dict(sorted(Counter(blocker["category"] for entry in entries for blocker in entry["blockers"]).items())),
        "registry_version": "content-ir-production-registry-1",
        "policy": "compile_full and runtime_preview_full never imply production_runtime_full",
    }
    _write(REPORT_ROOT / "content-ir-production-blocker-audit-2026-08-11.json", audit)
    _write(
        REPORT_ROOT / "content-ir-production-unlock-ranking-2026-08-11.json",
        {
            "schema_version": "content-ir-production-unlock-ranking-1",
            "ranking": ranking,
            "major_consumer_rule": "only candidate consumers unlocking at least 8 content assets are ranked; max 4",
            "counts_are_content_assets": True,
        },
    )
    _write(
        REPORT_ROOT / "content-ir-runtime-level-audit-II-2026-08-11.json",
        {
            "schema_version": "content-ir-runtime-level-audit-II-1",
            "layers": {
                "compile_full": 113,
                "runtime_preview_full": 113,
                "production_runtime_full": len(production_ids),
                "existing_100_production_runtime_full": len(existing_production_after),
                "new_authored_production_runtime_full": len(new_authored_ids & production_ids),
            },
            "formal_feature_audit_unchanged": {"total": 499, "full": 328, "partial": 110, "dm_only": 61},
            "generic_production_blocks": ranking,
            "compile_preview_production_rule": "compile_full and runtime_preview_full do not imply production_runtime_full",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
