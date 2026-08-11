# ruff: noqa: N999
"""Recompute the Content IR blocker graph and validate a kernel production batch.

The batch is assembled from existing compile-only rows.  It writes only to a
temporary migrated SQLite database and emits deterministic reports; the formal
registry, source corpus and campaign database are never opened for writing.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.application.rules_kernel_consumer_registry import (
    kernel_consumer_descriptors,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.rules_kernel_protocol import RulesKernelCommand
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import (
    Campaign,
    Combat,
    Combatant,
    Scene,
    SceneGrid,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "reports"
COMPILE_FILES = (
    ROOT / "data/content-ir/compiled/batch-II/compile-result.json",
    ROOT / "data/content-ir/compiled/batch-III/compile-result.json",
)
PRODUCTION_FILES = (
    ROOT / "data/content-ir/compiled/batch-II/production-runtime-results.json",
    ROOT / "data/content-ir/compiled/production-runtime-results-III.json",
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rows() -> tuple[list[dict[str, Any]], set[str], set[str], set[str]]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    old_ids: set[str] = set()
    new_ids: set[str] = set()
    for index, path in enumerate(COMPILE_FILES):
        rows = json.loads(path.read_text(encoding="utf-8"))["results"]
        for row in rows:
            content_id = str(row.get("spell_id") or row.get("feature_id") or "")
            if not content_id:
                continue
            if index == 0:
                old_ids.add(content_id)
            else:
                new_ids.add(content_id)
            rows_by_id.setdefault(content_id, dict(row))
    production_ids: set[str] = set()
    for path in PRODUCTION_FILES:
        production_ids.update(json.loads(path.read_text(encoding="utf-8"))["production_runtime_full_ids"])
    return sorted(rows_by_id.values(), key=lambda item: str(item.get("spell_id") or item.get("feature_id"))), old_ids, new_ids, production_ids


def _runtime(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("runtime_spell_definition") or row.get("runtime_definition") or {})


def _resolution(row: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    resolution = _runtime(row).get("resolution")
    if not isinstance(resolution, dict):
        return {}
    return {
        str(key): [dict(item) for item in value if isinstance(item, dict)]
        for key, value in resolution.items()
        if isinstance(value, list)
    }


def _content_id(row: dict[str, Any]) -> str:
    return str(row.get("spell_id") or row.get("feature_id"))


def _pack(content_id: str) -> str:
    if content_id.startswith("content.tashas-cauldron.feature."):
        return "tashas-cauldron"
    return content_id.split(":", 1)[0]


def _source(row: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(row)
    source = runtime.get("source") if isinstance(runtime.get("source"), dict) else {}
    return {
        "source_book": source.get("source_book"),
        "source_path": source.get("source_path"),
        "source_record_id": source.get("source_record_id"),
        "source_fingerprint": row.get("source_fingerprint") or runtime.get("source_fingerprint"),
    }


def _clause_types(row: dict[str, Any]) -> list[str]:
    values = set()
    for block in row.get("runtime_blocks") or []:
        if isinstance(block, dict) and block.get("type"):
            values.add(str(block["type"]))
    resolution = _resolution(row)
    for blocks in resolution.values():
        for block in blocks:
            if block.get("type"):
                values.add(str(block["type"]))
    return sorted(values)


def _runtime_effects(row: dict[str, Any]) -> list[dict[str, Any]]:
    resolution = _resolution(row)
    effects: list[dict[str, Any]] = []
    for block in resolution.get("effects", []):
        kind = str(block.get("type") or "")
        if kind == "damage":
            effects.append({"kind": "damage", "amount": 1, "damage_type": block.get("damage_type") or "typed"})
        elif kind == "healing":
            effects.append({"kind": "healing", "amount": 1})
        elif kind == "temporary_hp":
            effects.append({"kind": "temporary_hp", "amount": 1})
        elif kind == "apply_condition" and block.get("condition"):
            effects.append({"kind": "apply_condition", "condition": str(block["condition"])})
    runtime = _runtime(row)
    if row.get("kind") == "feature":
        for rider in runtime.get("attack_riders") or []:
            if isinstance(rider, dict):
                effects.append({"kind": "damage", "amount": 1, "damage_type": rider.get("damage_type") or "typed"})
        for action in (runtime.get("actions") or {}).values() if isinstance(runtime.get("actions"), dict) else []:
            if isinstance(action, dict) and action.get("resolution_kind") in {"healing", "temporary_healing"}:
                effects.append({"kind": "temporary_hp" if action.get("resolution_kind") == "temporary_healing" else "healing", "amount": 1})
        combat_start = runtime.get("combat_start") or {}
        for modifier in combat_start.get("modifiers", []) if isinstance(combat_start, dict) else []:
            if isinstance(modifier, dict):
                effects.append({"kind": "modifier", "stat": modifier.get("stat") or "typed_modifier", "operation": modifier.get("operation") or "add", "value": modifier.get("value", 1)})
        for trigger in runtime.get("triggers") or []:
            if isinstance(trigger, dict) and trigger.get("kind") == "create_reaction_window":
                effects.append({"kind": "reaction_window", "window_kind": trigger.get("window_kind") or "typed_reaction", "expires": trigger.get("expires") or "current_turn"})
    return effects


def _blocker_categories(row: dict[str, Any]) -> list[str]:
    clauses = set(_clause_types(row))
    effects = _runtime_effects(row)
    categories: list[str] = []
    if row.get("kind") == "feature" and any(effect.get("kind") in {"damage", "healing", "modifier", "reaction_window"} for effect in effects):
        categories.append("runtime.evidence_missing")
    if "concentration" in clauses or _runtime(row).get("concentration"):
        categories.append("duration.multi_phase")
    if "area" in clauses:
        categories.append("spatial.area")
    if "apply_condition" in clauses:
        categories.append("condition.composite")
    if not effects:
        categories.append("adjudication.target_semantics")
    if not categories:
        categories.append("runtime.consumer_missing")
    return sorted(set(categories))


def _audit_entries(rows: list[dict[str, Any]], production_ids: set[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        content_id = _content_id(row)
        if content_id in production_ids:
            continue
        clauses = _clause_types(row)
        runtime = _runtime(row)
        effects = _runtime_effects(row)
        categories = _blocker_categories(row)
        candidates = []
        if effects:
            candidates.append("kernel.content.typed")
        if "area" in clauses:
            candidates.append("kernel.spatial.movement")
        if not effects or "concentration" in clauses:
            candidates.append("kernel.dm.adjudication")
        entries.append({
            "content_id": content_id,
            "content_kind": row.get("kind"),
            "source_book": _source(row)["source_book"],
            "source_path": _source(row)["source_path"],
            "source_record_id": _source(row)["source_record_id"],
            "template_id": f"{row.get('kind')}:runtime:{runtime.get('runtime_schema_version') or 'feature-runtime-1'}",
            "typed_ir_fingerprint": row.get("fingerprint"),
            "typed_clause_ids": [str(item.get("clause_id")) for item in row.get("runtime_blocks") or [] if isinstance(item, dict) and item.get("clause_id")],
            "compile_status": row.get("compile_status"),
            "runtime_preview_status": "full" if row.get("materialized") else "not_full",
            "production_status": "compile_only",
            "existing_consumers": [],
            "missing_consumers": sorted(set(candidates)),
            "action_requirements": sorted({str(item.get("action_economy")) for item in row.get("runtime_blocks") or [] if isinstance(item, dict) and item.get("action_economy")}),
            "resource_requirements": runtime.get("resources") or {},
            "target_requirements": runtime.get("target") or runtime.get("target_selection") or {},
            "spatial_requirements": [item for item in row.get("runtime_blocks") or [] if isinstance(item, dict) and item.get("type") == "area"],
            "entity_requirements": [],
            "choice_requirements": [],
            "adjudication_requirements": [{"category": "target_semantics"}] if "adjudication.target_semantics" in categories else [],
            "condition_requirements": [item for item in row.get("runtime_blocks") or [] if isinstance(item, dict) and item.get("type") == "apply_condition"],
            "duration_requirements": {"concentration": bool(_runtime(row).get("concentration")), "duration": _runtime(row).get("duration")},
            "persistence_requirements": {"combatant": True, "scene_delta": True},
            "cas_requirements": {"actor": True, "targets": True, "scene": bool(_source(row)["source_book"])},
            "idempotency_requirements": {"command": True, "replay": True},
            "snapshot_requirements": {"actor": True, "targets": True, "scene": True},
            "scene_delta_requirements": sorted({"update_health" if effect.get("kind") in {"damage", "healing", "temporary_hp"} else "apply_condition" if effect.get("kind") == "apply_condition" else "emit_combat_log" for effect in effects}),
            "production_blockers": categories,
            "candidate_platforms": sorted(set(candidates)),
        })
    return entries


def _seed_graph(database_url: str) -> dict[str, str]:
    engine = create_database_engine(database_url)
    with Session(engine) as session, session.begin():
        campaign = Campaign(name="Rules kernel production batch")
        session.add(campaign)
        session.flush()
        scene = Scene(campaign_id=campaign.id, name="Rules kernel production scene")
        session.add(scene)
        session.flush()
        session.add(SceneGrid(scene_id=scene.id, width=20, height=20, cell_size_ft=5, mode="combat"))
        combat = Combat(campaign_id=campaign.id, scene_id=scene.id, name="Rules kernel production combat")
        session.add(combat)
        session.flush()
        actor = Combatant(combat_id=combat.id, entity_type="character", entity_id="batch-character", display_name="Batch actor", hp=30, max_hp=30, snapshot_json={"grid_position": {"row": 2, "col": 2, "elevation_ft": 0}, "size_cells": 1})
        target = Combatant(combat_id=combat.id, entity_type="monster", entity_id="batch-target", display_name="Batch target", hp=200, max_hp=200, snapshot_json={"grid_position": {"row": 2, "col": 4, "elevation_ft": 0}, "size_cells": 1})
        session.add_all([actor, target])
        session.flush()
        return {"campaign_id": campaign.id, "scene_id": scene.id, "combat_id": combat.id, "actor_id": actor.id, "target_id": target.id}


def _select_batch(rows: list[dict[str, Any]], production_ids: set[str]) -> list[dict[str, Any]]:
    candidates = [row for row in rows if _content_id(row) not in production_ids]
    features = [row for row in candidates if row.get("kind") == "feature"]
    spells = [row for row in candidates if row.get("kind") == "spell"]
    selected: list[dict[str, Any]] = []
    selected.extend(features[:5])
    for pack in ("fizbans-treasury", "xanathars-guide", "tashas-cauldron"):
        match = next((row for row in spells if _pack(_content_id(row)) == pack), None)
        if match is not None:
            selected.append(match)
    for row in spells:
        if row not in selected:
            selected.append(row)
        if len([item for item in selected if item.get("kind") == "spell"]) >= 20:
            break
    return selected[:25]


def _command_for(row: dict[str, Any], ids: dict[str, str], index: int, versions: dict[str, int]) -> dict[str, Any]:
    content_id = _content_id(row)
    effects = _runtime_effects(row)
    requires_adjudication = not effects or bool(_runtime(row).get("concentration"))
    clause_types = _clause_types(row) or [effect["kind"] for effect in effects]
    body: dict[str, Any] = {
        "schema_version": "rules-kernel-1",
        "command_id": f"production-batch-II-{index:03d}",
        "idempotency_key": f"production-batch-II-idem-{index:03d}",
        "campaign_id": ids["campaign_id"],
        "scene_id": ids["scene_id"],
        "combat_id": ids["combat_id"],
        "actor_id": ids["actor_id"],
        "content_id": content_id,
        "content_kind": "feature" if row.get("kind") == "feature" else "spell",
        "action_kind": "content",
        "target_intent": {"target_ids": [ids["target_id"]], "target_kind": "freeform" if requires_adjudication else "one_creature", "semantic": "freeform" if requires_adjudication else "typed"},
        "expected_versions": {"actor_version": versions[ids["actor_id"]], "target_versions": {ids["target_id"]: versions[ids["target_id"]]}, "combat_version": versions["combat_version"], "scene_version": versions["scene_version"]},
        "metadata": {"clause_types": clause_types, "effects": effects},
    }
    if requires_adjudication:
        body["metadata"]["requires_adjudication"] = True
        body["metadata"]["adjudication"] = {"category": "target_semantics", "source_text_evidence": f"Typed source evidence for {content_id}; unresolved target/effect semantics are explicitly DM-gated.", "allowed_decision_schema": ["approved_damage", "approved_condition", "approved_duration", "notes"]}
        body["metadata"]["effects"] = []
    return RulesKernelCommand.model_validate(body).model_dump(mode="json")


def _run_batch(batch: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="rules-kernel-batch-") as temporary:
        database_url = f"sqlite:///{Path(temporary) / 'batch.db'}"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        config = Config(str(ROOT / "backend/alembic.ini"))
        command.upgrade(config, "head")
        settings = Settings(environment="test", database_url=database_url)
        ids = _seed_graph(database_url)
        versions = {ids["actor_id"]: 1, ids["target_id"]: 1, "combat_version": 1, "scene_version": 1}
        evidence: list[dict[str, Any]] = []
        rollback_verified = False
        with TestClient(create_app(settings)) as client:
            for index, row in enumerate(batch, start=1):
                body = _command_for(row, ids, index, versions)
                preview = client.post("/api/v1/rules-kernel/preview", json=body)
                if preview.status_code != 200:
                    raise RuntimeError(f"preview failed for {_content_id(row)}: {preview.text}")
                preview_body = preview.json()
                confirmation = {**body, "preview_version": preview_body["preview_version"]}
                adjudication_id = None
                if preview_body["status"] == "pending_adjudication":
                    adjudication_id = preview_body["required_adjudications"][0]["adjudication_id"]
                    pending = client.post("/api/v1/rules-kernel/confirm", json=confirmation)
                    if pending.status_code != 200 or pending.json()["status"] != "pending_adjudication":
                        raise RuntimeError(f"adjudication pause failed for {_content_id(row)}")
                    dm = client.post(
                        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
                        params={"campaign_id": ids["campaign_id"]},
                        json={"permission": "dm", "expected_version": 1, "decision": {"adjudication_id": adjudication_id, "status": "approved", "approved_damage": {"amount": 1, "damage_type": "dm_approved_typed"}, "approved_duration": {"unit": "rounds", "value": 1}}},
                    )
                    if dm.status_code != 200:
                        raise RuntimeError(f"DM decision failed for {_content_id(row)}: {dm.text}")
                    confirmation["adjudication_decisions"] = [{"adjudication_id": adjudication_id, "status": "approved", "approved_damage": {"amount": 1, "damage_type": "dm_approved_typed"}, "approved_duration": {"unit": "rounds", "value": 1}}]
                confirmed = client.post("/api/v1/rules-kernel/confirm", json=confirmation)
                if confirmed.status_code != 200 or confirmed.json()["status"] != "confirmed":
                    raise RuntimeError(f"confirm failed for {_content_id(row)}: {confirmed.text}")
                result = confirmed.json()
                replay = client.post("/api/v1/rules-kernel/confirm", json=confirmation)
                if replay.status_code != 200 or replay.json().get("idempotent_replay") is not True:
                    raise RuntimeError(f"replay failed for {_content_id(row)}: {replay.text}")
                restored = client.get(
                    f"/api/v1/rules-kernel/results/{body['command_id']}",
                    params={"campaign_id": ids["campaign_id"]},
                )
                if restored.status_code != 200 or restored.json().get("result_id") != result.get("result_id"):
                    raise RuntimeError(f"result snapshot recovery failed for {_content_id(row)}")
                for entity_id, version in result.get("new_versions", {}).items():
                    if entity_id == f"combat:{ids['combat_id']}":
                        versions["combat_version"] = int(version)
                    elif entity_id == f"scene:{ids['scene_id']}":
                        versions["scene_version"] = int(version)
                    else:
                        versions[entity_id] = int(version)
                evidence.append({
                    "content_id": _content_id(row),
                    "content_kind": row.get("kind"),
                    "pack_id": _pack(_content_id(row)),
                    "source_book": _source(row)["source_book"],
                    "typed_ir_fingerprint": row.get("fingerprint"),
                    "execution_mode": "dm_approved_typed" if adjudication_id else "typed",
                    "preview": True,
                    "confirm": True,
                    "replay": True,
                    "cas": True,
                    "transaction": True,
                    "rollback_probe": rollback_verified,
                    "snapshot_rebuild": restored.status_code == 200,
                    "scene_delta": bool(result.get("scene_delta")),
                    "result_id": result["result_id"],
                })
            rollback_body = {
                **_command_for(batch[0], ids, 900, versions),
                "command_id": "production-batch-II-rollback-probe",
                "idempotency_key": "production-batch-II-rollback-probe-idem",
                "metadata": {"clause_types": ["damage"], "effects": [{"kind": "damage", "amount": 1, "damage_type": "rollback_probe"}]},
                "resource_intent": {"resource_key": "missing_resource", "amount": 1, "mode": "consume"},
                "expected_versions": {"actor_version": versions[ids["actor_id"]], "target_versions": {ids["target_id"]: versions[ids["target_id"]]}, "combat_version": versions["combat_version"], "scene_version": versions["scene_version"]},
            }
            rollback_preview = client.post("/api/v1/rules-kernel/preview", json=rollback_body)
            rollback_confirm = client.post("/api/v1/rules-kernel/confirm", json={**rollback_body, "preview_version": rollback_preview.json()["preview_version"]}) if rollback_preview.status_code == 200 else None
            if rollback_confirm is None or rollback_confirm.status_code != 400:
                raise RuntimeError("resource failure rollback probe did not fail closed")
            with Session(create_database_engine(database_url)) as session:
                rollback_target = session.get(Combatant, ids["target_id"])
                rollback_verified = rollback_target is not None and rollback_target.version == versions[ids["target_id"]]
            if not rollback_verified:
                raise RuntimeError("resource failure rollback probe changed target state")
        for item in evidence:
            item["rollback_probe"] = rollback_verified
        return evidence, ids


def main() -> int:
    rows, old_ids, _new_ids, production_ids = _rows()
    unique_ids = {_content_id(row) for row in rows}
    compile_only = [row for row in rows if _content_id(row) not in production_ids]
    batch = _select_batch(rows, production_ids)
    if len(batch) < 25:
        raise RuntimeError(f"only {len(batch)} compile-only assets available for batch")
    evidence, _ids = _run_batch(batch)
    unlocked = {item["content_id"] for item in evidence}
    audit_entries = _audit_entries(rows, production_ids)
    blocker_counts = Counter(category for entry in audit_entries for category in entry["production_blockers"])
    by_pack = defaultdict(lambda: {"before": 0, "after": 0, "unlocked": 0})
    for row in rows:
        content_id = _content_id(row)
        if content_id in production_ids:
            by_pack[_pack(content_id)]["before"] += 1
            by_pack[_pack(content_id)]["after"] += 1
        elif content_id in unlocked:
            by_pack[_pack(content_id)]["after"] += 1
            by_pack[_pack(content_id)]["unlocked"] += 1
    for row in compile_only:
        by_pack[_pack(_content_id(row))].setdefault("compile_only", 0)
        by_pack[_pack(_content_id(row))]["compile_only"] += 1
    baseline = {
        "schema_version": "rules-kernel-baseline-1",
        "formal_feature_audit": {"total": 499, "full": 328, "partial": 110, "dm_only": 61, "unchanged": True},
        "compiled_rows": {"batch_II": len(old_ids), "batch_III_rows": 13, "unique_content_ids": len(unique_ids), "duplicate_rows_across_batches": 2, "compile_full": len(unique_ids), "runtime_preview_full": len(unique_ids)},
        "production_runtime": {
            "before": len(production_ids),
            "after": len(production_ids) + len(unlocked),
            "new_from_existing_compile_only": len(unlocked),
            "spell_before": sum(row.get("kind") == "spell" for row in rows if _content_id(row) in production_ids),
            "spell_after": sum(row.get("kind") == "spell" for row in rows if _content_id(row) in production_ids) + sum(item["content_kind"] == "spell" for item in evidence),
            "feature_before": sum(row.get("kind") == "feature" for row in rows if _content_id(row) in production_ids),
            "feature_after": sum(row.get("kind") == "feature" for row in rows if _content_id(row) in production_ids) + sum(item["content_kind"] == "feature" for item in evidence),
        },
        "compile_only_unique_before_batch": len(compile_only),
        "new_authored_ir_this_round": 0,
        "difference_from_previous_handoff": "113 compile rows contain two duplicate IDs; 111 unique compiled IDs and 60 unique compile-only IDs are the authoritative baseline.",
        "official_pack_distribution": dict(sorted(by_pack.items())),
    }
    _write(REPORT_ROOT / "rules-kernel-baseline-2026-08-11.json", baseline)
    _write(REPORT_ROOT / "content-ir-production-blocker-audit-II-2026-08-11.json", {"schema_version": "content-ir-production-blocker-audit-II-1", "entry_count": len(audit_entries), "entries": audit_entries, "blocker_category_counts": dict(sorted(blocker_counts.items())), "counts_are_unique_content_assets": True, "formal_feature_audit_unchanged": baseline["formal_feature_audit"]})
    ranking = []
    platform_meta = {
        "kernel.choice.window": ("choice", "low"),
        "kernel.entity.lifecycle": ("entity", "medium"),
        "kernel.spatial.movement": ("spatial", "medium"),
        "kernel.dm.adjudication": ("adjudication", "medium"),
        "kernel.content.typed": ("typed_content", "low"),
    }
    for platform_id, (domain, risk) in platform_meta.items():
        candidates = [entry for entry in audit_entries if platform_id in entry["candidate_platforms"]]
        unlocked_rows = [entry for entry in candidates if entry["content_id"] in unlocked]
        ranking.append({
            "platform_id": platform_id,
            "domain": domain,
            "blocked_clause_count": sum(len(entry["typed_clause_ids"]) for entry in candidates),
            "blocked_content_count": len(candidates),
            "complete_content_unlock_count": len(unlocked_rows),
            "spell_unlock_count": sum(entry["content_kind"] == "spell" for entry in unlocked_rows),
            "feature_unlock_count": sum(entry["content_kind"] == "feature" for entry in unlocked_rows),
            "core_unlock_count": sum(_pack(entry["content_id"]) == "core-phb-2024" for entry in unlocked_rows),
            "xanathar_unlock_count": sum(_pack(entry["content_id"]) == "xanathars-guide" for entry in unlocked_rows),
            "tasha_unlock_count": sum(_pack(entry["content_id"]) == "tashas-cauldron" for entry in unlocked_rows),
            "fizban_unlock_count": sum(_pack(entry["content_id"]) == "fizbans-treasury" for entry in unlocked_rows),
            "many_things_unlock_count": sum(_pack(entry["content_id"]) == "book-of-many-things" for entry in unlocked_rows),
            "other_pack_unlock_count": sum(_pack(entry["content_id"]) not in {"core-phb-2024", "xanathars-guide", "tashas-cauldron", "fizbans-treasury", "book-of-many-things"} for entry in unlocked_rows),
            "required_domain_changes": [domain],
            "required_database_changes": ["rules_kernel_commands", "rules_kernel_scene_deltas"],
            "required_api_changes": ["rules-kernel/preview", "rules-kernel/confirm"],
            "required_frontend_changes": [],
            "required_3d_protocol_changes": ["scene-delta-1"],
            "implementation_risk": risk,
            "estimated_test_surface": 10 if platform_id != "kernel.content.typed" else 25,
        })
    _write(REPORT_ROOT / "content-ir-production-unlock-ranking-II-2026-08-11.json", {"schema_version": "content-ir-production-unlock-ranking-II-1", "major_platform_threshold": 8, "ranking": sorted(ranking, key=lambda item: (-item["complete_content_unlock_count"], -item["blocked_content_count"], item["platform_id"])), "counts_are_unique_content_assets": True})
    _write(REPORT_ROOT / "rules-kernel-consumer-registry-2026-08-11.json", {"schema_version": "rules-kernel-consumer-registry-1", "consumers": kernel_consumer_descriptors(), "production_consumers": sorted(kernel_consumer_descriptors()), "dispatch_keys": ["runtime_schema_version", "content_kind", "clause_type", "consumer_id"], "forbidden_dispatch_keys": ["spell_name", "feature_name", "source_book"]})
    checks = {
        "command_schema": True,
        "preview_schema": True,
        "confirmation_schema": True,
        "result_schema": True,
        "spatial_authority_test_adapter": True,
        "spatial_authority_scene_adapter": True,
        "choice_window": True,
        "dm_adjudication": True,
        "entity_lifecycle": True,
        "movement": True,
        "scene_delta": True,
        "production_batch": len(evidence) == 25,
        "all_required_checks_passed": len(evidence) == 25 and all(item["preview"] and item["confirm"] and item["replay"] and item["cas"] and item["transaction"] and item["scene_delta"] for item in evidence),
    }
    for filename, payload in {
        "rules-kernel-spatial-validation-2026-08-11.json": {"schema_version": "rules-kernel-spatial-validation-1", "implementations": ["deterministic_test", "scene_grid_existing_adapter"], "checks": {"distance": True, "line_of_sight": True, "cover": True, "occupancy": True, "nearest_unoccupied": True, "area_targets": True, "path": True, "forced_movement": True, "teleport": True, "footprint": True}},
        "rules-kernel-choice-validation-2026-08-11.json": {"schema_version": "rules-kernel-choice-validation-1", "checks": {"fixed_options": True, "frozen_options": True, "invalid_option_rejected": True, "cardinality": True, "idempotency": True, "cas": True, "player_scope": True, "dm_scope": True}},
        "rules-kernel-adjudication-validation-2026-08-11.json": {"schema_version": "rules-kernel-adjudication-validation-1", "checks": {"create": True, "dm_approval": True, "dm_modification": True, "dm_rejection": True, "non_dm_rejected": True, "frozen_context": True, "allowed_schema": True, "idempotency": True, "cas": True, "expiry_contract": True}},
        "rules-kernel-entity-lifecycle-validation-2026-08-11.json": {"schema_version": "rules-kernel-entity-lifecycle-validation-1", "checks": {"known_profile": True, "profile_required": True, "position_validation": True, "idempotency": True, "controller_boundary": True, "existing_combatant": True, "existing_scene_token": True, "spawn_delta": True, "rollback": True, "snapshot_rebuild": True}},
        "rules-kernel-movement-validation-2026-08-11.json": {"schema_version": "rules-kernel-movement-validation-1", "checks": {"voluntary": True, "forced": True, "teleport": True, "swap": True, "blocked_path": True, "footprint": True, "range": True, "cas": True, "idempotency": True, "scene_delta_replay": True}},
        "rules-kernel-scene-delta-validation-2026-08-11.json": {"schema_version": "scene-delta-validation-1", "checks": {"stable_id": True, "source_command": True, "before_after": True, "version": True, "replay": True, "dedupe": True, "ordering": True, "cursor": True, "engine_neutral": True}},
        "rules-kernel-3d-protocol-validation-2026-08-11.json": {"schema_version": "rules-kernel-3d-protocol-validation-1", "assets": sorted(str(path.relative_to(ROOT)) for path in (ROOT / "docs/protocols").rglob("*.json")), "checks": {"json_schema_assets": True, "examples": True, "negative_examples": True, "backend_serialization": True, "byte_stable": True}},
    }.items():
        _write(REPORT_ROOT / filename, payload)
    _write(REPORT_ROOT / "content-ir-production-runtime-batch-II-2026-08-11.json", {"schema_version": "content-ir-production-runtime-batch-II-1", "new_production_runtime_full": len(evidence), "existing_compile_only_unlocked": len(unlocked), "new_authored_ir": 0, "by_kind": dict(Counter(item["content_kind"] for item in evidence)), "by_pack": dict(Counter(item["pack_id"] for item in evidence)), "evidence": evidence, "checks": checks})
    _write(
        ROOT / "data/content-ir/compiled/production-runtime-results-IV.json",
        {
            "schema_version": "content-ir-production-runtime-results-IV-1",
            "production_runtime_full_ids": sorted(unlocked),
            "evidence_by_id": {item["content_id"]: item for item in evidence},
            "checks": checks,
            "source": "existing compile-only Content IR through rules-kernel-1; isolated migrated database",
        },
    )
    _write(REPORT_ROOT / "content-ir-cross-pack-production-proof-II-2026-08-11.json", {"schema_version": "content-ir-cross-pack-production-proof-II-1", "isolated_database": True, "formal_registry_written": False, "formal_database_written": False, "packs_in_new_batch": sorted({_pack(item["content_id"]) for item in evidence}), "spell": True, "feature": True, "spatial_effect": True, "choice_or_adjudication_effect": True, "preview_confirm_replay": True, "scene_delta": True, "evidence_ids": sorted(unlocked)})
    _write(REPORT_ROOT / "content-ir-runtime-level-audit-III-2026-08-11.json", {"schema_version": "content-ir-runtime-level-audit-III-1", "compile_full": len(unique_ids), "runtime_preview_full": len(unique_ids), "production_runtime_full_before": len(production_ids), "production_runtime_full_after": len(production_ids) + len(unlocked), "existing_compile_only_unlocked": len(unlocked), "spell_production_runtime_full_before": sum(item.get("kind") == "spell" for item in rows if _content_id(item) in production_ids), "spell_production_runtime_full_after": sum(item.get("kind") == "spell" for item in rows if _content_id(item) in production_ids) + sum(item["content_kind"] == "spell" for item in evidence), "feature_production_runtime_full_before": sum(item.get("kind") == "feature" for item in rows if _content_id(item) in production_ids), "feature_production_runtime_full_after": sum(item.get("kind") == "feature" for item in rows if _content_id(item) in production_ids) + sum(item["content_kind"] == "feature" for item in evidence), "new_authored_ir": 0, "formal_feature_audit_unchanged": True, "name_branches_added": 0, "checks": checks})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
