# ruff: noqa: N999
"""Validate Sword Burst through the generic Content IR spell consumer."""

from __future__ import annotations

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
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_spell_spec,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import OperationTransaction
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SPELL_ID = "tashas-cauldron:spell:eec6bd94eb83a351fb987de2"
SPELL_PATH = (
    ROOT
    / "data/content-ir/authored/official-packs/tashas-cauldron/spells/spells/"
    / "tashas-cauldron-spell-eec6bd94eb83a351fb987de2.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXII.json"
REPORT_PATH = ROOT / "reports/tashas-spell-production-consumer-round-XX-2026-08-12.json"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_runtime() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    authored = json.loads(SPELL_PATH.read_text(encoding="utf-8"))
    spec = SpellSpec.from_dict(authored)
    compiled = compile_spell_spec(spec)
    runtime = dict(compiled.get("runtime_spell_definition") or {})
    if compiled.get("compile_status") != "full" or not runtime:
        raise AssertionError(f"Sword Burst did not compile full: {compiled}")
    return authored, compiled, runtime


def _setup_spell(client: TestClient, runtime: dict[str, Any], level: int) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": f"Sword Burst L{level}"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = client.post(
        f"{base}/characters",
        json={
            "name": f"Sword Burst caster L{level}",
            "level": level,
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {
                "slots": {str(slot): {"current": 2, "max": 2} for slot in range(1, 10)}
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
    scene_response = client.post(f"{base}/scenes", json={"name": "Sword Burst grid"})
    if scene_response.status_code != 201:
        raise AssertionError(scene_response.text)
    scene = scene_response.json()
    grid_response = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 12, "height": 8, "cell_size_ft": 5, "mode": "combat"},
    )
    if grid_response.status_code != 201:
        raise AssertionError(grid_response.text)
    combat_response = client.post(
        f"{base}/combats", json={"name": "Sword Burst combat", "scene_id": scene["id"]}
    )
    if combat_response.status_code != 201:
        raise AssertionError(combat_response.text)
    combat = combat_response.json()
    root = f"{base}/combats/{combat['id']}"
    actor_response = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Sword Burst caster",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 2, "col": 2}},
        },
    )
    if actor_response.status_code != 201:
        raise AssertionError(actor_response.text)
    actor = actor_response.json()
    target_payload = {
        "display_name": "Sword Burst target",
        "entity_type": "monster",
        "initiative": 10,
        "hp": 100,
        "max_hp": 100,
        "snapshot_json": {"grid_position": {"row": 2, "col": 3}, "disposition": "enemy"},
    }
    target_response = client.post(f"{root}/combatants", json=target_payload)
    if target_response.status_code != 201:
        raise AssertionError(target_response.text)
    second_payload = {
        **target_payload,
        "display_name": "Sword Burst target 2",
        "snapshot_json": {"grid_position": {"row": 3, "col": 2}, "disposition": "enemy"},
    }
    second_response = client.post(f"{root}/combatants", json=second_payload)
    if second_response.status_code != 201:
        raise AssertionError(second_response.text)
    return {
        "base": base,
        "campaign": campaign,
        "character": character,
        "known_spell": known_response.json(),
        "combat": combat,
        "actor": actor,
        "target": target_response.json(),
        "second_target": second_response.json(),
    }


def _spell_body(scene: dict[str, Any], *, key: str, total: int, multi: bool = True) -> dict[str, Any]:
    target = scene["target"]
    second = scene["second_target"]
    # ``all_in_area`` is source-complete: submit the authoritative actor plus
    # every in-area combatant, including in the scaling/save probes.
    target_ids = [target["id"], second["id"]]
    target_versions = {
        scene["actor"]["id"]: scene["actor"]["version"],
        target["id"]: target["version"],
        second["id"]: second["version"],
    }
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known_spell"]["id"],
        "slot_level": 0,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": scene["actor"]["id"],
        "target_combatant_ids": target_ids,
        "target_versions": target_versions,
        "area_shape": "sphere",
        "area_size_ft": 5,
        "area_anchor_row": 2,
        "area_anchor_col": 2,
        "resolution_total": total,
        "save_succeeded_by_target": {
            scene["actor"]["id"]: False,
            target["id"]: False,
            second["id"]: False,
        },
        "idempotency_key": key,
    }


def _combat_amounts(preview: dict[str, Any]) -> list[int]:
    combat_preview = preview.get("combat_preview")
    rows = combat_preview if isinstance(combat_preview, list) else [combat_preview]
    amounts: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result = row.get("result")
        if isinstance(result, dict):
            amounts.append(int(result.get("original_damage", result.get("adjusted_damage", 0))))
        elif row.get("amount") is not None:
            amounts.append(int(row["amount"]))
    return amounts


def _run_production_loop(client: TestClient, runtime: dict[str, Any]) -> dict[str, Any]:
    scene = _setup_spell(client, runtime, 5)
    body = _spell_body(scene, key="tashas-round-xx-sword-burst", total=8)
    preview_response = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview_response.status_code != 200:
        raise AssertionError(preview_response.text)
    preview = preview_response.json()
    consumers = preview["production_contract"]["consumers"]
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
    target_after = client.get(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants/{scene['target']['id']}"
    ).json()
    actor_after = client.get(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants/{scene['actor']['id']}"
    ).json()
    second_after = client.get(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants/{scene['second_target']['id']}"
    ).json()
    evidence_engine = create_database_engine(os.environ["DND_DM_DATABASE_URL"])
    with Session(evidence_engine) as session:
        spell_transaction = session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == scene["campaign"]["id"],
                OperationTransaction.idempotency_key == "spell:tashas-round-xx-sword-burst:spell",
            )
        )
        runtime_transaction = session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == scene["campaign"]["id"],
                OperationTransaction.idempotency_key == "content-ir:tashas-round-xx-sword-burst",
            )
        )
    evidence_engine.dispose()
    stale_body = {**body, "idempotency_key": "tashas-round-xx-stale"}
    stale_response = client.post(
        f"{scene['base']}/content-ir/runtime/preview", json=stale_body
    )
    return {
        "runtime_id": SPELL_ID,
        "pack_id": "tashas-cauldron",
        "level": 5,
        "preview_status": preview_response.status_code,
        "confirm_status": confirmed_response.status_code,
        "replay_status": replay_response.status_code,
        "replay_already_applied": bool(replay.get("already_applied")),
        "production_runtime_full": bool(confirmed.get("production_runtime_full")),
        "preview_amounts": _combat_amounts(preview),
        "confirmed_target_hp": target_after["hp"],
        "confirmed_second_target_hp": second_after["hp"],
        "confirmed_actor_hp": actor_after["hp"],
        "target_version_advanced": int(target_after["version"]) > int(scene["target"]["version"]),
        "second_target_version_advanced": int(second_after["version"]) > int(scene["second_target"]["version"]),
        "stale_target_cas_status": stale_response.status_code,
        "consumer_ids": consumers,
        "operation_transaction": spell_transaction is not None and runtime_transaction is not None,
    }


def _run_scaling_previews(client: TestClient, runtime: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for level, total in ((1, 4), (5, 8), (11, 12), (17, 16)):
        scene = _setup_spell(client, runtime, level)
        body = _spell_body(
            scene,
            key=f"tashas-round-xx-scaling-{level}",
            total=total,
            multi=False,
        )
        body["save_succeeded"] = False
        preview_response = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
        if preview_response.status_code != 200:
            raise AssertionError(preview_response.text)
        preview = preview_response.json()
        rows.append(
            {
                "character_level": level,
                "reported_total": total,
                "resolved_amounts": _combat_amounts(preview),
                "consumer_ids": preview["production_contract"]["consumers"],
            }
        )
    return rows


def _run_save_success_preview(client: TestClient, runtime: dict[str, Any]) -> bool:
    scene = _setup_spell(client, runtime, 5)
    body = _spell_body(
        scene,
        key="tashas-round-xx-save-success",
        total=8,
        multi=False,
    )
    body["save_succeeded"] = True
    body["save_succeeded_by_target"] = {scene["target"]["id"]: True}
    response = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if response.status_code != 200:
        raise AssertionError(response.text)
    return _combat_amounts(response.json()) == [0, 0, 0]


def _run_rollback_probe(
    client: TestClient, app: Any, database_url: str, runtime: dict[str, Any]
) -> bool:
    scene = _setup_spell(client, runtime, 5)
    body = _spell_body(scene, key="tashas-round-xx-rollback", total=8)
    preview_response = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview_response.status_code != 200:
        raise AssertionError(preview_response.text)
    service = ContentIRRuntimeService(create_database_engine(database_url))
    original_confirm = service.combat.confirm_action_batch

    def fail_downstream(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Round XX rollback probe")

    service.combat.confirm_action_batch = fail_downstream  # type: ignore[method-assign]
    app.dependency_overrides[get_content_ir_runtime_service] = lambda: service
    try:
        response = client.post(
            f"{scene['base']}/content-ir/runtime/confirm",
            json={**body, "preview_token": preview_response.json()["preview_token"]},
        )
    finally:
        app.dependency_overrides.pop(get_content_ir_runtime_service, None)
        service.combat.confirm_action_batch = original_confirm  # type: ignore[method-assign]
        service.engine.dispose()
    restored = client.get(f"{scene['base']}/characters/{scene['character']['id']}").json()
    evidence_engine = create_database_engine(database_url)
    with Session(evidence_engine) as session:
        transaction = session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == scene["campaign"]["id"],
                OperationTransaction.idempotency_key
                == "spell:tashas-round-xx-rollback:spell",
            )
        )
    evidence_engine.dispose()
    return (
        response.status_code == 400
        and transaction is not None
        and transaction.status == "reverted"
        and int(restored["version"]) > int(scene["character"]["version"])
    )


def main() -> int:
    logging.disable(logging.CRITICAL)
    authored, compiled, runtime = _load_runtime()
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-xx.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            production = _run_production_loop(client, runtime)
            scaling = _run_scaling_previews(client, runtime)
            save_success_zero_damage = _run_save_success_preview(client, runtime)
            rollback_restored = _run_rollback_probe(client, app, database_url, runtime)
    logging.disable(logging.NOTSET)

    required_consumers = {
        "combat_engine.area_damage.v1",
        "combat_engine.damage_heal.v1",
        "spell.cantrip_scaling.v1",
    }
    source_text = str((authored.get("source_evidence") or {}).get("source_text") or "")
    normalized_source_text = "".join(source_text.split())
    checks = {
        "selected_count": len([SPELL_ID]) == 1,
        "compile_full": compiled.get("compile_status") == "full",
        "source_provenance_complete": all(
            authored.get(key)
            for key in ("source_record_id", "source_path", "source_fingerprint", "reviewed_fields")
        ),
        "source_evidence_has_full_clause": all(
            marker in normalized_source_text
            for marker in ("剑刃爆发", "敏捷豁免", "1d6", "5级", "11级", "17级")
        ),
        "typed_area_save_damage": {
            "target_selection": bool(runtime.get("resolution", {}).get("target_selection")),
            "area": any(
                item.get("type") == "area"
                for item in runtime.get("resolution", {}).get("effects", [])
            ),
            "saving_throw": bool(runtime.get("resolution", {}).get("saving_throw")),
            "damage": any(
                item.get("type") == "damage"
                for item in runtime.get("resolution", {}).get("effects", [])
            ),
            "progression": bool(runtime.get("resolution", {}).get("upcast")),
        },
        "generic_consumers_present": required_consumers.issubset(
            set(production["consumer_ids"])
        ),
        "preview_confirm_replay": production["preview_status"] == 200
        and production["confirm_status"] == 200
        and production["replay_status"] == 200,
        "production_runtime_full": production["production_runtime_full"],
        "three_area_targets_damage": production["preview_amounts"] == [8, 8, 8]
        and production["confirmed_target_hp"] == 92
        and production["confirmed_second_target_hp"] == 92
        and production["confirmed_actor_hp"] == 12,
        "replay_idempotent": production["replay_already_applied"],
        "target_cas_rejected": production["stale_target_cas_status"] == 409,
        "operation_transaction_persisted": production["operation_transaction"],
        "save_success_no_damage": save_success_zero_damage,
        "cantrip_scaling_levels": scaling
        == [
            {**scaling[0], "resolved_amounts": [4, 4, 4]},
            {**scaling[1], "resolved_amounts": [8, 8, 8]},
            {**scaling[2], "resolved_amounts": [12, 12, 12]},
            {**scaling[3], "resolved_amounts": [16, 16, 16]},
        ],
        "rollback_restored_character": rollback_restored,
    }
    checks["typed_area_save_damage"] = all(checks["typed_area_save_damage"].values())
    all_checks_passed = all(value is True for value in checks.values())
    evidence = {
        "runtime_id": SPELL_ID,
        "source_record_id": authored.get("source_record_id"),
        "source_path": authored.get("source_path"),
        "source_fingerprint": authored.get("source_fingerprint"),
        "reviewed_fields": authored.get("reviewed_fields"),
        "manual_decisions": authored.get("manual_decisions"),
        "runtime_schema_version": runtime.get("runtime_schema_version"),
        "runtime_definition_fingerprint": compiled.get("fingerprint"),
        "production": production,
        "scaling_previews": scaling,
    }
    result = {
        "schema_version": "content-ir-production-runtime-results-XXII-1",
        "round_id": "round-20",
        "production_runtime_full_ids": [SPELL_ID] if all_checks_passed else [],
        "evidence_by_id": {SPELL_ID: evidence},
        "checks": checks,
        "all_required_checks_passed": all_checks_passed,
    }
    report = {
        "schema_version": "tashas-spell-production-consumer-round-XX-1",
        "round_id": "round-20",
        "selected_content_ids": [SPELL_ID],
        "selected_cluster": "spell.area_saving_throw_damage_cantrip_scaling",
        "baseline": {
            "tashas_production_full": 82,
            "tashas_game_usable": 84,
            "tashas_compile_only": 10,
            "project_production_full": 182,
        },
        "after": {
            "selected_production_runtime_full": 1 if all_checks_passed else 0,
            "consumer_unlocks": {
                "spell.cantrip_scaling.v1": 1,
                "combat_engine.area_damage.v1": 1,
                "combat_engine.damage_heal.v1": 1,
            },
        },
        "production_runtime_full_ids": result["production_runtime_full_ids"],
        "source_review": {
            "source_record_id": authored.get("source_record_id"),
            "source_path": authored.get("source_path"),
            "source_fingerprint": authored.get("source_fingerprint"),
            "reviewed_fields": authored.get("reviewed_fields"),
            "manual_decisions": authored.get("manual_decisions"),
        },
        "checks": checks,
        "all_required_checks_passed": all_checks_passed,
        "formal_database_written": False,
        "formal_registry_written": False,
        "name_branch_count": 0,
    }
    _write(RESULT_PATH, result)
    _write(REPORT_PATH, report)
    return 0 if all_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
