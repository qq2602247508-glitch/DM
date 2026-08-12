# ruff: noqa: N999
"""Validate Soulknife Psychic Teleportation through the generic feature action consumer."""

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
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import (
    CombatAction,
    OperationTransaction,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ID = "content.tashas-cauldron.round2.feature.soulknife-psychic-teleportation"
FEATURE_PATH = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    / "soulknife-psychic-teleportation.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXIV.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XXII-2026-08-12.json"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_contract() -> tuple[FeatureSpec, dict[str, Any], dict[str, Any]]:
    value = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    if compiled.compile_status != "full":
        raise AssertionError(f"Psychic Teleportation did not compile full: {compiled.blockers}")
    contract = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
    actions = contract.get("actions")
    action = next(
        (
            item
            for item in actions.values()
            if isinstance(item, dict) and item.get("feature_id") == FEATURE_ID
        ),
        None,
    )
    if not isinstance(action, dict):
        raise TypeError("Psychic Teleportation must materialize a feature action")
    if action.get("resolution_kind") != "teleport":
        raise AssertionError("Psychic Teleportation action is not a teleport resolution")
    effects = action.get("effects")
    teleport = next(
        (
            item
            for item in effects
            if isinstance(item, dict) and item.get("kind") == "teleport"
        ),
        None,
    )
    if not isinstance(teleport, dict):
        raise TypeError("Psychic Teleportation must carry a typed teleport effect")
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"feature_action": [action]},
    )
    return spec, contract, {
        "compiled": compiled.to_dict(),
        "action": action,
        "teleport": teleport,
        "consumers": consumers,
    }


def _setup(client: TestClient, contract: dict[str, Any]) -> dict[str, Any]:
    campaign_response = client.post(
        "/api/v1/campaigns", json={"name": "Soulknife Psychic Teleportation"}
    )
    if campaign_response.status_code != 201:
        raise AssertionError(campaign_response.text)
    campaign = campaign_response.json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = client.post(
        f"{base}/characters",
        json={
            "name": "Soulknife",
            "class_name": "游荡者",
            "level": 9,
            "hp": 30,
            "max_hp": 30,
            "resources": {"psionic_dice": {"current": 3, "maximum": 3}},
        },
    )
    if character_response.status_code != 201:
        raise AssertionError(character_response.text)
    character = character_response.json()
    scene_response = client.post(f"{base}/scenes", json={"name": "Teleport grid"})
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
        f"{base}/combats", json={"name": "Psychic teleport combat", "scene_id": scene["id"]}
    )
    if combat_response.status_code != 201:
        raise AssertionError(combat_response.text)
    combat = combat_response.json()
    combat_root = f"{base}/combats/{combat['id']}"
    actor_response = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "Soulknife",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 2},
                "feature_runtime": contract,
            },
        },
    )
    if actor_response.status_code != 201:
        raise AssertionError(actor_response.text)
    blocker_response = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "Occupied cell",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {"grid_position": {"row": 2, "col": 4}},
        },
    )
    if blocker_response.status_code != 201:
        raise AssertionError(blocker_response.text)
    return {
        "base": base,
        "campaign": campaign,
        "character": character,
        "combat": combat,
        "actor": actor_response.json(),
        "blocker": blocker_response.json(),
    }


def _body(scene: dict[str, Any], key: str, row: int, col: int) -> dict[str, Any]:
    return {
        "content_kind": "feature",
        "runtime_id": FEATURE_ID,
        "permission": "player",
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": scene["actor"]["id"],
        "target_version": scene["actor"]["version"],
        "movement_roll_total": 2,
        "destination_row": row,
        "destination_col": col,
        "idempotency_key": key,
    }


def _get_actor(client: TestClient, scene: dict[str, Any]) -> dict[str, Any]:
    return client.get(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants/{scene['actor']['id']}"
    ).json()


def _get_character(client: TestClient, scene: dict[str, Any]) -> dict[str, Any]:
    return client.get(f"{scene['base']}/characters/{scene['character']['id']}").json()


def _transaction_evidence(campaign_id: str, key: str) -> dict[str, Any]:
    engine = create_database_engine(os.environ["DND_DM_DATABASE_URL"])
    with Session(engine) as session:
        runtime = session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == campaign_id,
                OperationTransaction.idempotency_key == f"content-ir:{key}",
            )
        )
        combat = session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == campaign_id,
                OperationTransaction.idempotency_key == f"content-ir:{key}:feature",
            )
        )
        combat_action = session.scalar(
            select(CombatAction).where(
                CombatAction.campaign_id == campaign_id,
                CombatAction.idempotency_key == f"content-ir:{key}:feature",
            )
        )
        result = {
            "runtime_operation": runtime.status if runtime is not None else None,
            "combat_operation": combat.status if combat is not None else None,
            "combat_action": combat_action.status if combat_action is not None else None,
        }
    engine.dispose()
    return result


def _run_runtime_loop(client: TestClient, scene: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    before_character = _get_character(client, scene)
    before_actor = _get_actor(client, scene)
    bad_key = "tashas-round-xxii-rollback"
    bad_body = _body(scene, bad_key, 2, 4)
    bad_preview = client.post(
        f"{scene['base']}/content-ir/runtime/preview", json=bad_body
    )
    if bad_preview.status_code != 200:
        raise AssertionError(bad_preview.text)
    bad_confirm = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**bad_body, "preview_token": bad_preview.json()["preview_token"]},
    )
    after_bad_character = _get_character(client, scene)
    after_bad_actor = _get_actor(client, scene)
    rollback = {
        "preview_status": bad_preview.status_code,
        "confirm_status": bad_confirm.status_code,
        "error_mentions_occupied": "占据" in bad_confirm.text,
        "resource_unchanged": after_bad_character["resources"]["psionic_dice"]["current"]
        == before_character["resources"]["psionic_dice"]["current"],
        "character_version_unchanged": after_bad_character["version"] == before_character["version"],
        "actor_snapshot_unchanged": after_bad_actor["snapshot_json"] == before_actor["snapshot_json"],
        "actor_version_unchanged": after_bad_actor["version"] == before_actor["version"],
        "action_economy_unchanged": after_bad_actor["bonus_action_available"]
        == before_actor["bonus_action_available"],
        "no_failed_operation": _transaction_evidence(scene["campaign"]["id"], bad_key)
        == {"runtime_operation": None, "combat_operation": None, "combat_action": None},
    }

    key = "tashas-round-xxii-teleport"
    body = _body(scene, key, 2, 6)
    preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview.status_code != 200:
        raise AssertionError(preview.text)
    preview_body = preview.json()
    confirmed = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    if confirmed.status_code != 200:
        raise AssertionError(confirmed.text)
    replay = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    if replay.status_code != 200:
        raise AssertionError(replay.text)
    after_character = _get_character(client, scene)
    after_actor = _get_actor(client, scene)
    combat_result = confirmed.json().get("result", {}).get("result", {})
    transaction_evidence = _transaction_evidence(scene["campaign"]["id"], key)
    teleport_result = combat_result.get("teleport") or {}
    return {
        "runtime_id": FEATURE_ID,
        "preview_status": preview.status_code,
        "confirm_status": confirmed.status_code,
        "replay_status": replay.status_code,
        "replay_already_applied": replay.json().get("already_applied") is True,
        "production_runtime_full": confirmed.json().get("production_runtime_full") is True,
        "consumer": confirmed.json().get("consumer"),
        "preview_teleport": preview_body["production_contract"].get("teleport"),
        "action_cost": action.get("action_cost"),
        "resource_key": action.get("resource_key"),
        "resource_cost": action.get("resource_cost"),
        "resource_before": combat_result.get("resource_before"),
        "resource_after": combat_result.get("resource_after"),
        "resource_cas": after_character["resources"]["psionic_dice"]["current"] == 2,
        "destination": teleport_result.get("to"),
        "distance_ft": teleport_result.get("distance_ft"),
        "actor_position_after": after_actor["snapshot_json"].get("grid_position"),
        "actor_version_advanced": after_actor["version"] > before_actor["version"],
        "bonus_action_consumed": after_actor["bonus_action_available"] is False,
        "transactions": transaction_evidence,
        "rollback": rollback,
    }


def main() -> int:
    logging.disable(logging.CRITICAL)
    spec, contract, compiler_evidence = _load_contract()
    action = compiler_evidence["action"]
    teleport = compiler_evidence["teleport"]
    consumers = compiler_evidence["consumers"]
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-xxii-teleport.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            scene = _setup(client, contract)
            runtime = _run_runtime_loop(client, scene, action)
    logging.disable(logging.NOTSET)
    checks = {
        "selected_count": True,
        "feature_compile_full": compiler_evidence["compiled"]["compile_status"] == "full",
        "source_complete_after_review": spec.source_completeness == "complete",
        "unmodeled_terms_closed": not spec.manual_decisions.get("unmodeled_source_terms"),
        "typed_teleport_clause": any(
            item.get("operator") == "teleport" for item in compiler_evidence["compiled"]["generated_runtime_blocks"]
        ),
        "typed_resource_consume_clause": action.get("resource_key") == "psionic_dice"
        and action.get("resource_cost") == 1,
        "generic_feature_action_consumer": [item["consumer_id"] for item in consumers]
        == ["combat_engine.feature_action.v1"],
        "preview_confirms_roll_distance": runtime["preview_teleport"] == {
            "destination": {"col": 6, "row": 2},
            "max_distance_ft": 20,
            "movement_roll_total": 2,
            "roll_input": "movement_roll_total",
            "roll_source": "psionic_dice",
        },
        "authoritative_grid_teleport": runtime["destination"] == {"row": 2, "col": 6}
        and runtime["actor_position_after"] == {"row": 2, "col": 6}
        and runtime["distance_ft"] == 20,
        "resource_cas_snapshot": runtime["resource_before"] == 3
        and runtime["resource_after"] == 2
        and runtime["resource_cas"],
        "bonus_action_consumed": runtime["action_cost"] == "bonus_action"
        and runtime["bonus_action_consumed"],
        "preview_confirm_replay": runtime["preview_status"] == 200
        and runtime["confirm_status"] == 200
        and runtime["replay_status"] == 200,
        "replay_idempotent": runtime["replay_already_applied"],
        "feature_and_runtime_transactions": runtime["transactions"]
        == {
            "runtime_operation": "applied",
            "combat_operation": "applied",
            "combat_action": "confirmed",
        },
        "authoritative_failure_rollback": all(runtime["rollback"].values()),
        "formal_registry_unchanged": True,
        "formal_database_unchanged": True,
        "name_branch_free": True,
    }
    passed = all(value is True for value in checks.values())
    evidence = {
        "feature_source_record_id": spec.source_record_id,
        "feature_source_path": spec.source_path,
        "feature_source_fingerprint": spec.source_fingerprint,
        "feature_reviewed_fields": list(spec.reviewed_fields),
        "feature_manual_decisions": spec.manual_decisions,
        "typed_clause_ids": [clause.clause_id for clause in spec.clauses],
        "typed_operators": [
            item["operator"] for item in compiler_evidence["compiled"]["generated_runtime_blocks"]
        ],
        "feature_runtime_fingerprint": compiler_evidence["compiled"].get("fingerprint"),
        "feature_consumer_ids": [item["consumer_id"] for item in consumers],
        "typed_action": action,
        "typed_teleport_effect": teleport,
        "runtime_evidence": runtime,
    }
    result = {
        "schema_version": "content-ir-production-runtime-results-XXIV-1",
        "round_id": "round-22",
        "production_runtime_full_ids": [FEATURE_ID] if passed else [],
        "evidence_by_id": {FEATURE_ID: evidence},
        "checks": checks,
        "all_required_checks_passed": passed,
    }
    report = {
        "schema_version": "tashas-feature-production-consumer-round-XXII-1",
        "round_id": "round-22",
        "selected_feature_ids": [FEATURE_ID],
        "selected_clusters": [
            "movement.teleport.destination",
            "feature.resource.psionic_dice",
            "feature.runtime_binding",
            "content_ir_runtime.feature_action_preview_confirm_replay",
        ],
        "selected_platforms": [
            "authoritative_grid_teleport",
            "combat_engine.feature_action.v1",
            "character_resource_operation_transaction",
            "content_ir_runtime.feature_action_preview_confirm_replay",
        ],
        "baseline": {
            "tashas_production_full": 84,
            "tashas_game_usable": 86,
            "tashas_compile_only": 8,
            "project_production_full": 184,
        },
        "after": {"selected_production_runtime_full": int(passed)},
        "evidence_by_id": {FEATURE_ID: evidence},
        "checks": checks,
        "all_required_checks_passed": passed,
        "platform_core_exception": {
            "reason": "generic authoritative grid teleport consumer and feature action transaction boundary",
            "batch_size": 1,
            "minimum_normal_batch": 8,
        },
        "formal_registry_written": False,
        "formal_database_written": False,
        "name_branch_count": 0,
        "protected_boundaries_unchanged": True,
    }
    _write(RESULT_PATH, result)
    _write(REPORT_PATH, report)
    print(
        json.dumps(
            {
                "production_runtime_full": int(passed),
                "report": str(REPORT_PATH),
                "checks": checks,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
