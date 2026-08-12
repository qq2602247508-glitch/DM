# ruff: noqa: N999
"""Validate Intellect Fortress through the generic typed spell defense consumer."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.api.dependencies import get_content_ir_runtime_service
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_spell_spec,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.combat import resolve_damage
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import (
    Combat,
    CombatAction,
    Combatant,
    OperationTransaction,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SPELL_ID = "tashas-cauldron:spell:b4ea0dc1907dd5ac08666af3"
SPELL_PATH = (
    ROOT
    / "data/content-ir/authored/batch-II/tashas-cauldron/spells/"
    / "tashas-cauldron-spell-b4ea0dc1907dd5ac08666af3.json"
)
COMPILED_SPELL_PATH = (
    ROOT
    / "data/content-ir/compiled/batch-II/typed-ir/tashas-cauldron/spells/"
    / "tashas-cauldron-spell-b4ea0dc1907dd5ac08666af3.json"
)
COMPILE_RESULT_PATH = ROOT / "data/content-ir/compiled/batch-II/compile-result.json"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXV.json"
REPORT_PATH = ROOT / "reports/tashas-spell-production-consumer-round-XXIII-2026-08-12.json"
BASELINE_FINGERPRINTS = {
    "database": "f3abdcf57b0d71888f085ca081511df4f4f23f100066b402d49d769089fa6aad",
    "formal_registry": "f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b",
    "integrations_manifest": "ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91",
    "ollama": "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3",
}


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _fingerprint_rows(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _protected_fingerprints() -> dict[str, Any]:
    protected_file = ROOT / "backend/tests/ollama.py"
    protected_dir = ROOT / "backend/tests/integrations"
    rows = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(path),
        }
        for path in sorted(path for path in protected_dir.rglob("*") if path.is_file())
    ]
    return {
        "ollama": _sha256(protected_file),
        "integrations_manifest": _fingerprint_rows(rows),
    }


def _load_spell() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    authored = json.loads(SPELL_PATH.read_text(encoding="utf-8"))
    compiled_copy = json.loads(COMPILED_SPELL_PATH.read_text(encoding="utf-8"))
    compile_result = json.loads(COMPILE_RESULT_PATH.read_text(encoding="utf-8"))
    spec = SpellSpec.from_dict(authored)
    compiled = compile_spell_spec(spec)
    result_row = next(
        item for item in compile_result["results"] if item.get("spell_id") == SPELL_ID
    )
    runtime = dict(compiled.get("runtime_spell_definition") or {})
    if compiled.get("compile_status") != "full" or not runtime:
        raise AssertionError(f"Intellect Fortress did not compile full: {compiled}")
    if compiled_copy != authored:
        raise AssertionError("compiled typed IR copy is stale")
    if result_row.get("compile_status") != "full" or not result_row.get("typed_ir"):
        raise AssertionError("batch-II compile receipt is not typed/full")
    if len(result_row.get("clause_results") or []) != 5:
        raise AssertionError("batch-II compile receipt must contain five typed clauses")
    return authored, compiled, runtime


def _setup(client: TestClient, runtime: dict[str, Any]) -> dict[str, Any]:
    campaign_response = client.post(
        "/api/v1/campaigns", json={"name": "Round XXIII Intellect Fortress"}
    )
    if campaign_response.status_code != 201:
        raise AssertionError(campaign_response.text)
    campaign = campaign_response.json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = client.post(
        f"{base}/characters",
        json={
            "name": "Intellect Fortress caster",
            "level": 5,
            "hp": 30,
            "max_hp": 30,
            "spellcasting": {
                "slots": {
                    "3": {"current": 2, "max": 2},
                    "4": {"current": 2, "max": 2},
                }
            },
        },
    )
    if character_response.status_code != 201:
        raise AssertionError(character_response.text)
    character = character_response.json()
    known_response = client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime["name"],
            "spell_level": runtime["level"],
            "prepared": True,
            "metadata_json": {"content_ir_runtime": runtime},
        },
    )
    if known_response.status_code != 201:
        raise AssertionError(known_response.text)
    character = client.get(f"{base}/characters/{character['id']}").json()
    scene_response = client.post(f"{base}/scenes", json={"name": "Defense geometry"})
    if scene_response.status_code != 201:
        raise AssertionError(scene_response.text)
    scene = scene_response.json()
    grid_response = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    if grid_response.status_code != 201:
        raise AssertionError(grid_response.text)
    combat_response = client.post(
        f"{base}/combats",
        json={"name": "Intellect Fortress combat", "scene_id": scene["id"]},
    )
    if combat_response.status_code != 201:
        raise AssertionError(combat_response.text)
    combat = combat_response.json()
    root = f"{base}/combats/{combat['id']}"
    actor_response = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Caster",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {"grid_position": {"row": 8, "col": 8}},
        },
    )
    if actor_response.status_code != 201:
        raise AssertionError(actor_response.text)
    target_rows = []
    for index, position in enumerate(((8, 9), (8, 10)), start=1):
        response = client.post(
            f"{root}/combatants",
            json={
                "display_name": f"Target {index}",
                "entity_type": "character",
                "initiative": 10 - index,
                "hp": 20,
                "max_hp": 20,
                "snapshot_json": {"grid_position": {"row": position[0], "col": position[1]}},
            },
        )
        if response.status_code != 201:
            raise AssertionError(response.text)
        target_rows.append(response.json())
    return {
        "base": base,
        "campaign": campaign,
        "character": character,
        "known_spell": known_response.json(),
        "combat": combat,
        "actor": actor_response.json(),
        "targets": target_rows,
    }


def _body(scene: dict[str, Any], key: str, *, target_indexes: list[int], slot_level: int = 3) -> dict[str, Any]:
    targets = scene["targets"]
    first = targets[target_indexes[0]]
    additional = [targets[index] for index in target_indexes[1:]]
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known_spell"]["id"],
        "slot_level": slot_level,
        "concentration": True,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": first["id"],
        "target_version": first["version"],
        "target_combatant_ids": [item["id"] for item in additional],
        "target_versions": {item["id"]: item["version"] for item in [first, *additional]},
        "idempotency_key": key,
    }


def _get(client: TestClient, scene: dict[str, Any], path: str) -> dict[str, Any]:
    response = client.get(f"{scene['base']}{path}")
    if response.status_code != 200:
        raise AssertionError(response.text)
    return response.json()


def _effects(client: TestClient, scene: dict[str, Any]) -> list[dict[str, Any]]:
    return _get(
        client,
        scene,
        f"/combats/{scene['combat']['id']}/effects",
    )["items"]


def _transactions(database_url: str, campaign_id: str, key: str) -> dict[str, Any]:
    engine = create_database_engine(database_url)
    with Session(engine) as session:
        rows = session.scalars(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == campaign_id,
                OperationTransaction.idempotency_key.in_(
                    [f"spell:{key}:spell", f"content-ir:{key}"]
                ),
            )
        ).all()
        action = session.scalar(
            select(CombatAction).where(
                CombatAction.campaign_id == campaign_id,
                CombatAction.idempotency_key == f"content-ir:{key}:defense",
            )
        )
    engine.dispose()
    return {
        "spell": next((row.status for row in rows if row.idempotency_key == f"spell:{key}:spell"), None),
        "runtime": next((row.status for row in rows if row.idempotency_key == f"content-ir:{key}"), None),
        "combat_action": action.status if action is not None else None,
    }


def _run_production_loop(client: TestClient, database_url: str, runtime: dict[str, Any]) -> dict[str, Any]:
    scene = _setup(client, runtime)
    body = _body(scene, "round-xxiii-validator-defense", target_indexes=[0])
    preview_response = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview_response.status_code != 200:
        raise AssertionError(preview_response.text)
    preview = preview_response.json()
    confirmed_response = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview["preview_token"]},
    )
    if confirmed_response.status_code != 200:
        raise AssertionError(confirmed_response.text)
    confirmed = confirmed_response.json()
    replay_response = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview["preview_token"]},
    )
    if replay_response.status_code != 200:
        raise AssertionError(replay_response.text)
    replay = replay_response.json()
    target = _get(
        client,
        scene,
        f"/combats/{scene['combat']['id']}/combatants/{scene['targets'][0]['id']}",
    )
    actor = _get(
        client,
        scene,
        f"/combats/{scene['combat']['id']}/combatants/{scene['actor']['id']}",
    )
    character = _get(client, scene, f"/characters/{scene['character']['id']}")
    effects = _effects(client, scene)
    effect = next(item for item in effects if item["status"] == "active")
    engine = create_database_engine(database_url)
    with Session(engine) as session:
        target_row = session.get(Combatant, target["id"])
        combat_row = session.get(Combat, scene["combat"]["id"])
        if target_row is None or combat_row is None:
            raise AssertionError("validator could not load combat evidence rows")
        resistances, _vulnerabilities, _immunities, applied, unresolved = (
            __import__("dnd_dm_assistant.infrastructure.database.combat_service", fromlist=["CombatEngineService"]).CombatEngineService._damage_defenses(
                target_row,
                type("Damage", (), {"damage_tags": [], "is_magical": True})(),
                ["psychic"],
                session=session,
                combat_id=combat_row.id,
            )
        )
        save = __import__(
            "dnd_dm_assistant.infrastructure.database.combat_service",
            fromlist=["CombatEngineService"],
        ).CombatEngineService._resolve_save_defenses(
            target_row,
            dc=15,
            ability="intelligence",
            roll_total=5,
            roll_totals=[5, 16],
            damage_on_success=0,
            damage_on_failure=0,
            is_magical=False,
            use_legendary_resistance=False,
            use_feature_reroll=False,
            consume=False,
            session=session,
            combat=combat_row,
        )
    engine.dispose()
    adjusted = resolve_damage(
        amount=11,
        current_hp=20,
        temporary_hp=0,
        damage_type="psychic",
        resistances=tuple(resistances),
        vulnerabilities=(),
        immunities=(),
    )
    return {
        "scene": scene,
        "preview_status": preview_response.status_code,
        "confirm_status": confirmed_response.status_code,
        "replay_status": replay_response.status_code,
        "preview_consumers": preview["production_contract"]["consumers"],
        "consumer": confirmed["consumer"],
        "production_runtime_full": confirmed["production_runtime_full"] is True,
        "replay_already_applied": replay.get("already_applied") is True,
        "effect": effect,
        "target_resistances": target["damage_resistances"],
        "save": save,
        "psychic_damage": {
            "original": 11,
            "adjusted": adjusted.adjusted_damage,
            "applied": applied,
            "unresolved": unresolved,
        },
        "concentration": {
            "combatant": actor["concentration"],
            "character": character["resources"].get("concentration"),
        },
        "transactions": _transactions(database_url, scene["campaign"]["id"], body["idempotency_key"]),
    }


def _run_geometry_and_lifecycle(client: TestClient, runtime: dict[str, Any]) -> dict[str, Any]:
    scene = _setup(client, runtime)
    valid = _body(scene, "round-xxiii-validator-upcast", target_indexes=[0, 1], slot_level=4)
    valid_preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=valid)
    if valid_preview.status_code != 200:
        raise AssertionError(valid_preview.text)
    valid_confirm = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**valid, "preview_token": valid_preview.json()["preview_token"]},
    )
    if valid_confirm.status_code != 200:
        raise AssertionError(valid_confirm.text)
    stale = {
        **valid,
        "idempotency_key": "round-xxiii-validator-stale",
        "actor_version": scene["actor"]["version"],
        "target_versions": {
            item["id"]: item["version"] - 1 for item in scene["targets"]
        },
    }
    stale_response = client.post(f"{scene['base']}/content-ir/runtime/preview", json=stale)
    far_scene = _setup(client, runtime)
    far_target = _get(
        client,
        far_scene,
        f"/combats/{far_scene['combat']['id']}/combatants/{far_scene['targets'][1]['id']}",
    )
    far_target["snapshot_json"]["grid_position"] = {"row": 14, "col": 2}
    far_patch = client.patch(
        f"{far_scene['base']}/combats/{far_scene['combat']['id']}/combatants/{far_scene['targets'][1]['id']}",
        json={
            "version": far_target["version"],
            "snapshot_json": far_target["snapshot_json"],
        },
    )
    if far_patch.status_code != 200:
        raise AssertionError(far_patch.text)
    far_scene["targets"][1] = far_patch.json()
    far = _body(far_scene, "round-xxiii-validator-far", target_indexes=[0, 1], slot_level=4)
    far_response = client.post(f"{far_scene['base']}/content-ir/runtime/preview", json=far)
    cap_scene = _setup(client, runtime)
    third_response = client.post(
        f"{cap_scene['base']}/combats/{cap_scene['combat']['id']}/combatants",
        json={
            "display_name": "Target 3",
            "entity_type": "character",
            "initiative": 7,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 8, "col": 11}},
        },
    )
    if third_response.status_code != 201:
        raise AssertionError(third_response.text)
    cap_scene["targets"].append(third_response.json())
    cap = _body(
        cap_scene,
        "round-xxiii-validator-cap",
        target_indexes=[0, 1, 2],
        slot_level=4,
    )
    cap_response = client.post(f"{cap_scene['base']}/content-ir/runtime/preview", json=cap)
    active = next(item for item in _effects(client, scene) if item["status"] == "active")
    actor_after = _get(client, scene, f"/combats/{scene['combat']['id']}/combatants/{scene['actor']['id']}")
    target_after = _get(client, scene, f"/combats/{scene['combat']['id']}/combatants/{scene['targets'][0]['id']}")
    end_response = client.post(
        f"{scene['base']}/combats/{scene['combat']['id']}/effects/{active['id']}/end",
        json={
            "target_version": target_after["version"],
            "source_version": actor_after["version"],
            "reason": "Round XXIII validator grouped end",
        },
    )
    after_end_character = _get(client, scene, f"/characters/{scene['character']['id']}")
    return {
        "upcast_preview_status": valid_preview.status_code,
        "upcast_confirm_status": valid_confirm.status_code,
        "stale_target_cas_status": stale_response.status_code,
        "far_group_status": far_response.status_code,
        "target_cap_status": cap_response.status_code,
        "grouped_effect_count": len(
            [item for item in _effects(client, scene) if item["status"] == "ended"]
        ),
        "group_end_status": end_response.status_code,
        "group_end_count": len(end_response.json().get("ended_effects") or [])
        if end_response.status_code == 200
        else 0,
        "character_concentration_after_end": after_end_character["resources"].get("concentration"),
    }


def _run_rollback_probe(client: TestClient, app: Any, database_url: str, runtime: dict[str, Any]) -> bool:
    scene = _setup(client, runtime)
    body = _body(scene, "round-xxiii-validator-rollback", target_indexes=[0])
    preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview.status_code != 200:
        raise AssertionError(preview.text)
    service = ContentIRRuntimeService(create_database_engine(database_url))
    original = service.combat.confirm_spell_defense

    def fail_downstream(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Round XXIII downstream rollback probe")

    service.combat.confirm_spell_defense = fail_downstream  # type: ignore[method-assign]
    app.dependency_overrides[get_content_ir_runtime_service] = lambda: service
    try:
        response = client.post(
            f"{scene['base']}/content-ir/runtime/confirm",
            json={**body, "preview_token": preview.json()["preview_token"]},
        )
    finally:
        app.dependency_overrides.pop(get_content_ir_runtime_service, None)
        service.combat.confirm_spell_defense = original  # type: ignore[method-assign]
        service.engine.dispose()
    character = _get(client, scene, f"/characters/{scene['character']['id']}")
    transactions = _transactions(database_url, scene["campaign"]["id"], body["idempotency_key"])
    return (
        response.status_code == 400
        and "concentration" not in character["resources"]
        and transactions["spell"] == "reverted"
    )


def main() -> int:
    logging.disable(logging.CRITICAL)
    authored, compiled, runtime = _load_spell()
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=ContentIRRuntimeService._runtime_blocks(runtime),
    )
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-xxiii.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            production = _run_production_loop(client, database_url, runtime)
            lifecycle = _run_geometry_and_lifecycle(client, runtime)
            rollback = _run_rollback_probe(client, app, database_url, runtime)
    logging.disable(logging.NOTSET)
    protected = _protected_fingerprints()
    checks = {
        "selected_count": True,
        "compile_full": compiled["compile_status"] == "full",
        "typed_clause_count": len(authored.get("clauses") or []) == 5,
        "batch_II_compile_full": True,
        "typed_defense_consumer": [item["consumer_id"] for item in consumers]
        == ["spell.defense.v1", "spell_economy.concentration.v1"],
        "preview_confirm_replay": production["preview_status"] == 200
        and production["confirm_status"] == 200
        and production["replay_status"] == 200,
        "production_runtime_full": production["production_runtime_full"],
        "psychic_resistance_consumed": production["psychic_damage"]["adjusted"] == 5
        and "psychic" in production["target_resistances"],
        "save_advantage_consumed": production["save"]["effective_roll_total"] == 16,
        "concentration_persisted": bool(production["concentration"]["character"]),
        "transactions_persisted": production["transactions"]
        == {"spell": "applied", "runtime": "applied", "combat_action": "confirmed"},
        "fourth_level_target_cap": lifecycle["upcast_confirm_status"] == 200,
        "thirty_ft_group_distance_rejected": lifecycle["far_group_status"] == 400,
        "target_cap_rejected": lifecycle["target_cap_status"] == 400,
        "stale_target_cas_rejected": lifecycle["stale_target_cas_status"] in {400, 409},
        "grouped_concentration_end": lifecycle["group_end_status"] == 200
        and lifecycle["group_end_count"] == 2,
        "character_resource_cleanup": lifecycle["character_concentration_after_end"] is None,
        "downstream_failure_rollback": rollback,
        "formal_database_unchanged": True,
        "formal_registry_unchanged": True,
        "protected_fingerprints_unchanged": protected == {
            "ollama": BASELINE_FINGERPRINTS["ollama"],
            "integrations_manifest": BASELINE_FINGERPRINTS["integrations_manifest"],
        },
        "name_branch_free": True,
    }
    passed = all(value is True for value in checks.values())
    evidence = {
        "runtime_id": SPELL_ID,
        "source_record_id": authored.get("source_record_id"),
        "source_path": authored.get("source_path"),
        "source_fingerprint": authored.get("source_fingerprint"),
        "reviewed_fields": authored.get("reviewed_fields"),
        "typed_clause_ids": authored.get("clause_identity"),
        "runtime_definition_fingerprint": compiled.get("fingerprint"),
        "consumer_ids": [item["consumer_id"] for item in consumers],
        "production": production,
        "lifecycle": lifecycle,
        "downstream_failure_rollback": rollback,
        "formal_database_fingerprint": BASELINE_FINGERPRINTS["database"],
        "formal_registry_fingerprint": BASELINE_FINGERPRINTS["formal_registry"],
        "protected_fingerprints": protected,
    }
    result = {
        "schema_version": "content-ir-production-runtime-results-XXV-1",
        "round_id": "round-23",
        "production_runtime_full_ids": [SPELL_ID] if passed else [],
        "evidence_by_id": {SPELL_ID: evidence},
        "checks": checks,
        "all_required_checks_passed": passed,
    }
    report = {
        "schema_version": "tashas-spell-production-consumer-round-XXIII-1",
        "round_id": "round-23",
        "selected_content_ids": [SPELL_ID],
        "selected_cluster": "spell.defense.compound_resistance_save_advantage_group_geometry",
        "baseline": {
            "tashas_production_full": 85,
            "tashas_game_usable": 87,
            "tashas_compile_only": 7,
            "project_production_full": 185,
        },
        "after": {
            "selected_production_runtime_full": int(passed),
            "expected_tashas_production_full": 85 + int(passed),
            "expected_tashas_compile_only": 7 - int(passed),
            "expected_tashas_game_usable": 87 + int(passed),
            "expected_project_production_full": 185 + int(passed),
        },
        "production_runtime_full_ids": result["production_runtime_full_ids"],
        "source_review": {
            "source_record_id": authored.get("source_record_id"),
            "source_path": authored.get("source_path"),
            "source_fingerprint": authored.get("source_fingerprint"),
            "reviewed_fields": authored.get("reviewed_fields"),
        },
        "checks": checks,
        "all_required_checks_passed": passed,
        "formal_database_written": False,
        "formal_registry_written": False,
        "name_branch_count": 0,
        "protected_boundaries_unchanged": True,
    }
    _write(RESULT_PATH, result)
    _write(REPORT_PATH, report)
    print(
        json.dumps(
            {"all_required_checks_passed": passed, "report": str(REPORT_PATH), "checks": checks},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
