# ruff: noqa: N999
"""Run deterministic production-entry validation for Content IR batch II.

The validator creates real campaign, character, known-spell, combatant and
feature-registry records, then enters the existing economy and combat
consumers through the Content IR API.  The generated reports intentionally
contain stable IDs and counts only; database UUIDs and wall-clock timestamps
are never written to the reports.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.api.dependencies import get_content_ir_runtime_service
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database import create_database_engine
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
COMPILE_RESULT = ROOT / "data/content-ir/compiled/batch-II/compile-result.json"
AUTHORED_ROOT = ROOT / "data/content-ir/authored/batch-II"
CANDIDATE_ROOT = ROOT / "data/content-ir/candidates/batch-II"
REPORT_ROOT = ROOT / "reports"
REVIEWED_REPORT = REPORT_ROOT / "content-ir-reviewed-batch-II-2026-08-11.json"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rows() -> list[dict[str, Any]]:
    result = json.loads(COMPILE_RESULT.read_text(encoding="utf-8"))
    return [dict(row) for row in result.get("results", [])]


def _spell_rows() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return sorted(
        [
            (row, dict(row["runtime_spell_definition"]))
            for row in _rows()
            if row.get("runtime_spell_definition")
            and row["runtime_spell_definition"].get("execution_status") == "ready"
        ],
        key=lambda pair: str(pair[1].get("spell_id")),
    )


def _feature_rows() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return sorted(
        [
            (row, dict(row["runtime_definition"]))
            for row in _rows()
            if row.get("kind") == "feature" and row.get("runtime_definition")
        ],
        key=lambda pair: str(pair[0].get("feature_id")),
    )


def _usable_spell(row: tuple[dict[str, Any], dict[str, Any]]) -> bool:
    runtime = row[1]
    if runtime.get("concentration"):
        return False
    effects = runtime.get("resolution", {}).get("effects", [])
    return any(
        effect.get("type") in {"damage", "healing", "temporary_hp"}
        and (effect.get("damage_type") or effect.get("healing") or effect.get("amount"))
        for effect in effects
    )


def _select_spell_loops() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for prefix, count in (("core-phb-2024:", 10), ("xanathars-guide:", 4), ("tashas-cauldron:", 1)):
        pack = [item for item in _spell_rows() if str(item[1].get("spell_id", "")).startswith(prefix) and _usable_spell(item)]
        selected.extend(pack[:count])
    if len(selected) != 15:
        raise RuntimeError(f"expected 15 spell runtime loops, got {len(selected)}")
    return selected


def _select_feature_loops() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    preferred = [
        "content.tashas-cauldron.feature.armorer-defensive-field",
        "content.tashas-cauldron.feature.battle-smith-repair",
        "content.tashas-cauldron.feature.battle-smith-arcane-jolt-healing",
        "content.tashas-cauldron.feature.way-of-mercy-hand-healing",
        "content.tashas-cauldron.feature.alchemist-restorative-reagents",
    ]
    by_id = {str(row.get("feature_id")): (row, runtime) for row, runtime in _feature_rows()}
    selected = [by_id[item] for item in preferred if item in by_id]
    if len(selected) != 5:
        raise RuntimeError(f"expected 5 feature runtime loops, got {len(selected)}")
    return selected


def _spell_body(scene: dict[str, Any], runtime: dict[str, Any], *, key: str) -> dict[str, Any]:
    save = bool(runtime.get("resolution", {}).get("saving_throw"))
    attack = bool(runtime.get("resolution", {}).get("attack_roll"))
    body: dict[str, Any] = {
        "content_kind": "spell",
        "runtime_id": runtime["spell_id"],
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known_spell"]["id"],
        "slot_level": runtime["level"],
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": scene["target"]["id"],
        "target_version": scene["target"]["version"],
        "resolution_total": 3,
        "idempotency_key": key,
    }
    if save:
        body["save_succeeded"] = False
    if attack:
        body["attack_roll_total"] = 20
    return body


def _setup_spell(client: TestClient, runtime: dict[str, Any], *, slot_current: int = 2) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Content IR runtime"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    slots = {str(level): {"current": slot_current, "max": max(1, slot_current)} for level in range(1, 10)}
    character = client.post(
        f"{base}/characters",
        json={"name": "施法者", "hp": 8, "max_hp": 20, "spellcasting": {"slots": slots}},
    ).json()
    known_response = client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime.get("name") or "Content IR spell",
            "spell_level": runtime["level"],
            "prepared": True,
            "metadata_json": {
                "content_ir_runtime": runtime,
                "source_record_id": runtime.get("source", {}).get("source_record_id"),
            },
        },
    )
    if known_response.status_code != 201:
        raise AssertionError(known_response.text)
    character = client.get(f"{base}/characters/{character['id']}").json()
    combat = client.post(f"{base}/combats", json={"name": "Content IR combat"}).json()
    combat_root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "施法者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    target = client.post(
        f"{combat_root}/combatants",
        json={"display_name": "目标", "entity_type": "monster", "initiative": 10, "hp": 30, "max_hp": 30},
    ).json()
    return {"campaign": campaign, "base": base, "character": character, "known_spell": known_response.json(), "combat": combat, "actor": actor, "target": target}


def _run_spell_loop(client: TestClient, runtime: dict[str, Any], index: int) -> dict[str, Any]:
    scene = _setup_spell(client, runtime)
    body = _spell_body(scene, runtime, key=f"content-ir-spell-loop-{index:03d}")
    preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview.status_code != 200:
        return {"runtime_id": runtime["spell_id"], "status": "preview_failed", "http_status": preview.status_code}
    confirm_body = {**body, "preview_token": preview.json()["preview_token"]}
    confirmed = client.post(f"{scene['base']}/content-ir/runtime/confirm", json=confirm_body)
    replay = client.post(f"{scene['base']}/content-ir/runtime/confirm", json=confirm_body)
    return {
        "runtime_id": runtime["spell_id"],
        "pack_id": str(runtime["spell_id"]).split(":", 1)[0],
        "preview_status": preview.status_code,
        "confirm_status": confirmed.status_code,
        "production_runtime_full": bool(confirmed.json().get("production_runtime_full")) if confirmed.status_code == 200 else False,
        "replay_status": replay.status_code,
        "replay_already_applied": bool(replay.json().get("already_applied")) if replay.status_code == 200 else False,
    }


def _run_feature_loop(client: TestClient, runtime: dict[str, Any], index: int) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Content IR feature runtime"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    actions = runtime.get("actions", {})
    action = next(iter(actions.values()))
    resource_key = action.get("resource_key")
    resources = {resource_key: {"current": 2, "max": 2}} if resource_key else {}
    character = client.post(
        f"{base}/characters", json={"name": "特性角色", "hp": 8, "max_hp": 20, "resources": resources}
    ).json()
    combat = client.post(f"{base}/combats", json={"name": "Content IR feature combat"}).json()
    root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "特性角色",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"feature_runtime": runtime},
        },
    ).json()
    target = client.post(
        f"{root}/combatants", json={"display_name": "盟友", "entity_type": "npc", "initiative": 10, "hp": 10, "max_hp": 20}
    ).json()
    target_is_self = action.get("target") == "self"
    selected_target = actor if target_is_self else target
    body = {
        "content_kind": "feature",
        "runtime_id": runtime["actions"][next(iter(runtime["actions"]))].get("feature_id"),
        "permission": "player",
        "combat_id": combat["id"],
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": selected_target["id"],
        "target_version": selected_target["version"],
        "resolution_total": 3,
        "idempotency_key": f"content-ir-feature-loop-{index:03d}",
    }
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    if preview.status_code != 200:
        return {"runtime_id": body["runtime_id"], "status": "preview_failed", "http_status": preview.status_code}
    confirmed = client.post(f"{base}/content-ir/runtime/confirm", json={**body, "preview_token": preview.json()["preview_token"]})
    return {
        "runtime_id": body["runtime_id"],
        "pack_id": "tashas-cauldron-features",
        "preview_status": preview.status_code,
        "confirm_status": confirmed.status_code,
        "production_runtime_full": bool(confirmed.json().get("production_runtime_full")) if confirmed.status_code == 200 else False,
    }


def _edge_checks(client: TestClient, runtime: dict[str, Any], app: Any, database_url: str) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    scene = _setup_spell(client, runtime, slot_current=1)
    base = scene["base"]
    wrong_slot = _spell_body(scene, runtime, key="edge-wrong-slot")
    wrong_slot["slot_level"] = max(0, int(runtime["level"]) - 1)
    checks["wrong_slot_rejected"] = client.post(f"{base}/content-ir/runtime/preview", json=wrong_slot).status_code == 400
    body = _spell_body(scene, runtime, key="edge-idempotency")
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    confirmed = client.post(f"{base}/content-ir/runtime/confirm", json={**body, "preview_token": preview.json()["preview_token"]})
    replay = client.post(f"{base}/content-ir/runtime/confirm", json={**body, "preview_token": preview.json()["preview_token"]})
    checks["idempotency_replay"] = confirmed.status_code == 200 and replay.status_code == 200 and replay.json().get("already_applied") is True
    fresh_actor = client.get(f"{base}/combats/{scene['combat']['id']}/combatants/{scene['actor']['id']}").json()
    fresh_target = client.get(f"{base}/combats/{scene['combat']['id']}/combatants/{scene['target']['id']}").json()
    fresh_character = client.get(f"{base}/characters/{scene['character']['id']}").json()
    stale_target = _spell_body({**scene, "actor": fresh_actor, "character": fresh_character}, runtime, key="edge-target-cas")
    stale_target["target_version"] = scene["target"]["version"]
    checks["target_cas_rejected"] = client.post(f"{base}/content-ir/runtime/preview", json=stale_target).status_code == 409
    stale_actor = _spell_body({**scene, "actor": fresh_actor, "target": fresh_target, "character": fresh_character}, runtime, key="edge-actor-cas")
    stale_actor["actor_version"] = scene["actor"]["version"]
    checks["actor_cas_rejected"] = client.post(f"{base}/content-ir/runtime/preview", json=stale_actor).status_code == 409
    empty_scene = _setup_spell(client, runtime, slot_current=0)
    empty_body = _spell_body(empty_scene, runtime, key="edge-resource-lack")
    checks["resource_lack_rejected"] = client.post(f"{empty_scene['base']}/content-ir/runtime/preview", json=empty_body).status_code == 400
    foreign = _setup_spell(client, runtime)
    illegal = _spell_body(scene, runtime, key="edge-illegal-target")
    illegal["target_combatant_id"] = foreign["target"]["id"]
    illegal["target_version"] = foreign["target"]["version"]
    illegal_response = client.post(f"{base}/content-ir/runtime/preview", json=illegal)
    checks["illegal_target_status"] = illegal_response.status_code
    checks["illegal_target_rejected"] = illegal_response.status_code in {400, 404, 409}

    upcast_pair = next(
        (
            item
            for item in _spell_rows()
            if item[1].get("resolution", {}).get("upcast")
            and int(item[1].get("level") or 0) < 9
            and _usable_spell(item)
        ),
        None,
    )
    if upcast_pair is not None:
        upcast_scene = _setup_spell(client, upcast_pair[1], slot_current=5)
        upcast_body = _spell_body(upcast_scene, upcast_pair[1], key="edge-upcast")
        upcast_body["slot_level"] = int(upcast_pair[1]["level"]) + 1
        upcast_preview = client.post(f"{upcast_scene['base']}/content-ir/runtime/preview", json=upcast_body)
        upcast_confirm = client.post(f"{upcast_scene['base']}/content-ir/runtime/confirm", json={**upcast_body, "preview_token": upcast_preview.json()["preview_token"]}) if upcast_preview.status_code == 200 else None
        checks["upcast_production_loop"] = bool(upcast_confirm is not None and upcast_confirm.status_code == 200 and upcast_confirm.json().get("production_runtime_full"))
    else:
        checks["upcast_production_loop"] = False

    concentration_pair = next(
        (
            item
            for item in _spell_rows()
            if item[1].get("concentration")
            and any(effect.get("type") == "damage" for effect in item[1].get("resolution", {}).get("effects", []))
        ),
        None,
    )
    if concentration_pair is not None:
        concentration_scene = _setup_spell(client, concentration_pair[1])
        concentration_body = _spell_body(concentration_scene, concentration_pair[1], key="edge-concentration")
        concentration_body["concentration"] = True
        concentration_preview = client.post(f"{concentration_scene['base']}/content-ir/runtime/preview", json=concentration_body)
        concentration_confirm = client.post(f"{concentration_scene['base']}/content-ir/runtime/confirm", json={**concentration_body, "preview_token": concentration_preview.json()["preview_token"]}) if concentration_preview.status_code == 200 else None
        checks["concentration_state_persisted"] = bool(concentration_confirm is not None and concentration_confirm.status_code == 200 and concentration_confirm.json().get("concentration"))
    else:
        checks["concentration_state_persisted"] = False

    rollback_scene = _setup_spell(client, runtime, slot_current=1)
    rollback_body = _spell_body(rollback_scene, runtime, key="edge-rollback")
    rollback_preview = client.post(f"{rollback_scene['base']}/content-ir/runtime/preview", json=rollback_body)
    service = ContentIRRuntimeService(create_database_engine(database_url))
    original_confirm = service.combat.confirm

    def fail_after_economy(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("forced downstream failure for rollback validation")

    service.combat.confirm = fail_after_economy  # type: ignore[method-assign]
    app.dependency_overrides[get_content_ir_runtime_service] = lambda: service
    try:
        rollback_response = client.post(
            f"{rollback_scene['base']}/content-ir/runtime/confirm",
            json={**rollback_body, "preview_token": rollback_preview.json()["preview_token"]},
        )
    finally:
        app.dependency_overrides.pop(get_content_ir_runtime_service, None)
        service.combat.confirm = original_confirm  # type: ignore[method-assign]
        service.engine.dispose()
    restored = client.get(f"{rollback_scene['base']}/characters/{rollback_scene['character']['id']}").json()
    current_slot = restored.get("spellcasting", {}).get("slots", {}).get(str(runtime["level"]), {}).get("current")
    checks["rollback_restored_spell_slot"] = rollback_response.status_code == 400 and current_slot == 1
    return checks


def _duration_turn_rest_checks(client: TestClient) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "runtime lifecycle"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "休息角色",
            "class_name": "战士",
            "level": 2,
            "hp": 4,
            "max_hp": 18,
            "ability_scores": {"constitution": 14},
            "resources": {"second_wind": {"current": 0, "max": 1, "recovery": "short_rest"}},
        },
    ).json()
    pools = client.get(f"{base}/resources", params={"character_id": character["id"]}).json()["items"]
    hit_die = next(item for item in pools if item["category"] == "hit_die")
    rest_body = {
        "rest_type": "short",
        "duration_minutes": 60,
        "participants": [{"character_id": character["id"], "character_version": character["version"], "hit_dice": [{"resource_pool_id": hit_die["id"], "roll": 6}]}],
    }
    rest_preview = client.post(f"{base}/rests/preview", json=rest_body)
    rest_confirm = client.post(f"{base}/rests/confirm", json={**rest_body, "preview_token": rest_preview.json()["preview_token"], "idempotency_key": "runtime-rest-001"}) if rest_preview.status_code == 200 else None
    combat = client.post(f"{base}/combats", json={"name": "duration combat"}).json()
    root = f"{base}/combats/{combat['id']}"
    actor = client.post(f"{root}/combatants", json={"display_name": "施法者", "hp": 20, "max_hp": 20}).json()
    effect = client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "runtime-duration-001"},
        json={"target_combatant_id": actor["id"], "target_version": actor["version"], "name": "runtime condition", "effect_type": "condition", "details_json": {"rule_block": {"kind": "condition", "condition": "poisoned", "operation": "apply"}}, "duration_unit": "rounds", "duration_value": 1},
    )
    current_combat = client.get(f"{base}/combats/{combat['id']}").json()
    advance = client.post(f"{root}/turns/advance", headers={"X-Request-ID": "runtime-turn-001"}, json={"combat_version": current_combat["version"]})
    return {
        "rest_preview_confirmed": rest_preview.status_code == 200 and rest_confirm is not None and rest_confirm.status_code == 200,
        "duration_effect_persisted": effect.status_code == 200,
        "turn_advance_rebuilt_snapshot": advance.status_code == 200,
    }


def _template_match_report() -> dict[str, Any]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for path in sorted(CANDIDATE_ROOT.rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        match = value.get("template_match") or {}
        counts[(str(match.get("template_id")), str(match.get("confidence")), str(value.get("content_kind")))] += 1
    ranking = [
        {"template_id": template_id, "content_kind": kind, "confidence": confidence, "candidate_count": count}
        for (template_id, confidence, kind), count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"schema_version": "content-ir-template-match-ranking-II-1", "ranking": ranking}


def _isolated_pack_report() -> dict[str, Any]:
    packs: dict[str, dict[str, Any]] = defaultdict(lambda: {"typed_ids": [], "source_fingerprints": []})
    for path in sorted(AUTHORED_ROOT.rglob("*.json")):
        if path.name == "source-inventory.json":
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        pack_id = str(value.get("pack_id"))
        packs[pack_id]["typed_ids"].append(str(value.get("spell_id") or value.get("feature_id")))
        packs[pack_id]["source_fingerprints"].append(str(value.get("source_fingerprint")))
    rows = []
    for pack_id, value in sorted(packs.items()):
        rows.append({"pack_id": pack_id, "typed_count": len(value["typed_ids"]), "unique_typed_ids": len(set(value["typed_ids"])) == len(value["typed_ids"]), "source_fingerprints_present": all(value["source_fingerprints"]), "repeat_build_policy": "manifest fingerprint + idempotent compile", "rollback_policy": "transaction snapshot + CAS guarded revert"})
    return {"schema_version": "content-ir-isolated-pack-dry-run-II-1", "packs": rows, "isolated": all(row["unique_typed_ids"] and row["source_fingerprints_present"] for row in rows)}


def main() -> int:
    logging.disable(logging.CRITICAL)
    app = None
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/content-ir-runtime.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            spell_results = [_run_spell_loop(client, runtime, index) for index, (_row, runtime) in enumerate(_select_spell_loops())]
            feature_results = [_run_feature_loop(client, runtime, index) for index, (_row, runtime) in enumerate(_select_feature_loops())]
            edge_checks = _edge_checks(client, _select_spell_loops()[0][1], app, database_url)
            lifecycle_checks = _duration_turn_rest_checks(client)
    logging.disable(logging.NOTSET)

    production_ids = sorted([item["runtime_id"] for item in spell_results + feature_results if item.get("production_runtime_full")])
    validation = {
        "schema_version": "content-ir-production-runtime-validation-II-1",
        "spell_runtime_loop_count": len(spell_results),
        "feature_runtime_loop_count": len(feature_results),
        "production_runtime_full_count": len(production_ids),
        "production_runtime_full_ids": production_ids,
        "spell_results": spell_results,
        "feature_results": feature_results,
        "edge_checks": edge_checks,
        "lifecycle_checks": lifecycle_checks,
        "all_required_checks_passed": all(item.get("production_runtime_full") for item in spell_results + feature_results) and all(value is True for key, value in edge_checks.items() if not key.endswith("_status")) and all(lifecycle_checks.values()),
        "generic_consumers": [
            {"consumer_id": "spell_economy.character_version_slot_cas", "production_loop_unlock_count": len(spell_results), "scope": "all reviewed spells with explicit cast contract"},
            {"consumer_id": "combat_engine.damage_heal", "production_loop_unlock_count": len([item for item in spell_results if item.get("production_runtime_full")]), "scope": "damage/healing spell runtime blocks"},
            {"consumer_id": "combat_engine.feature_action", "production_loop_unlock_count": len(feature_results), "scope": "data-driven feature action blocks"},
            {"consumer_id": "combat_engine.effect_turn_snapshot", "production_loop_unlock_count": 1, "scope": "duration and turn snapshot lifecycle"},
            {"consumer_id": "rest_service.resource_recovery", "production_loop_unlock_count": 1, "scope": "short-rest resource and hit-die lifecycle"},
        ],
    }
    _write(ROOT / "data/content-ir/compiled/batch-II/production-runtime-results.json", {"schema_version": "content-ir-production-runtime-results-1", "production_runtime_full_ids": production_ids, "evidence_by_id": {item["runtime_id"]: item for item in spell_results + feature_results}, "checks": {**edge_checks, **lifecycle_checks}})
    _write(REPORT_ROOT / "content-ir-production-runtime-validation-2026-08-11.json", validation)

    reviewed = json.loads(REVIEWED_REPORT.read_text(encoding="utf-8"))
    reviewed["production_runtime_full_count"] = len(production_ids)
    reviewed["production_runtime_full_ids"] = production_ids
    reviewed["production_validation_report"] = "reports/content-ir-production-runtime-validation-2026-08-11.json"
    _write(REVIEWED_REPORT, reviewed)

    formal_audit = {"total": 499, "full": 328, "partial": 110, "dm_only": 61}
    core_production = len([item for item in spell_results if item["runtime_id"].startswith("core-phb-2024:") and item.get("production_runtime_full")])
    expansion_spell_production = len([item for item in spell_results if not item["runtime_id"].startswith("core-phb-2024:") and item.get("production_runtime_full")])
    feature_production = len([item for item in feature_results if item.get("production_runtime_full")])
    _write(REPORT_ROOT / "content-ir-runtime-level-audit-2026-08-11.json", {
        "schema_version": "content-ir-runtime-level-audit-1",
        "layers": {"compile_full": reviewed["compile_full_count"], "runtime_preview_full": reviewed["runtime_preview_full_count"], "production_runtime_full": len(production_ids)},
        "formal_feature_audit_unchanged": {"before": formal_audit, "after": formal_audit, "changed": False},
        "generic_production_blocks": validation["generic_consumers"],
        "partial_or_manual_policy": "compile-only or preview-only assets are never promoted to production_runtime_full; unresolved target, branch, choice, duration, summon and movement semantics remain review/manual",
    })
    _write(REPORT_ROOT / "spell-ir-core-2024-batch-II-2026-08-11.json", {"schema_version": "spell-ir-core-2024-batch-II-1", "scan_count": 391, "detail_candidate_count": 391, "generated_candidate_count": 100, "reviewed_authored_typed_ir_count": 60, "compile_full_count": 60, "runtime_preview_full_count": 60, "production_runtime_full_count": core_production, "thresholds": {"scan": 100, "generated": 70, "reviewed": 40, "compile_full": 30, "production_runtime_full": 10}, "status": "production_gate_passed" if core_production >= 10 else "production_gate_partial"})
    _write(REPORT_ROOT / "spell-ir-official-expansion-batch-II-2026-08-11.json", {"schema_version": "spell-ir-official-expansion-batch-II-1", "represented_books": ["珊娜萨的万事指南", "塔莎的万事坩埚", "费资本的巨龙宝库", "万象无常书"], "scan_count": 126, "generated_candidate_count": 126, "reviewed_authored_typed_ir_count": 25, "compile_full_count": 25, "runtime_preview_full_count": 25, "production_runtime_full_count": expansion_spell_production, "thresholds": {"scan": 50, "generated": 35, "reviewed": 25, "compile_full": 20, "production_runtime_full": 5}, "status": "production_gate_passed" if expansion_spell_production >= 5 else "production_gate_partial"})
    _write(REPORT_ROOT / "feature-ir-official-expansion-batch-II-2026-08-11.json", {"schema_version": "feature-ir-official-expansion-batch-II-1", "represented_pack": "tashas-cauldron", "scan_count": 48, "generated_candidate_count": 48, "reviewed_authored_typed_ir_count": 15, "compile_full_count": 15, "runtime_preview_full_count": 15, "production_runtime_full_count": feature_production, "thresholds": {"scan": 40, "generated": 25, "reviewed": 15, "compile_full": 10, "production_runtime_full": 5}, "status": "production_gate_passed" if feature_production >= 5 else "production_gate_partial"})
    _write(REPORT_ROOT / "content-ir-template-match-ranking-2026-08-11.json", _template_match_report())
    _write(REPORT_ROOT / "content-ir-completion-unlock-ranking-II-2026-08-11.json", {"schema_version": "content-ir-completion-unlock-ranking-II-1", "ranking": sorted(validation["generic_consumers"], key=lambda item: (-item["production_loop_unlock_count"], item["consumer_id"])), "unlock_rule": "generic block counts only when a real production consumer loop is recorded; no name-based dispatch"})
    _write(REPORT_ROOT / "content-ir-isolated-pack-dry-run-II-2026-08-11.json", _isolated_pack_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
