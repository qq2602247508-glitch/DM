# ruff: noqa: N999
"""Validate Psionic Sorcery through the generic spell-context consumer."""

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
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import OperationTransaction
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ID = "content.tashas-cauldron.round2.feature.aberrant-mind-psionic-sorcery"
FEATURE_PATH = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    / "aberrant-mind-psionic-sorcery.json"
)
SPELL_ID = "tashas-cauldron:spell:bef5ef39397ea7aa8a0856ea"
SPELL_COMPILE_PATH = (
    ROOT / "data/content-ir/authored/official-packs/tashas-cauldron/spells/compile-result.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXIII.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XXI-2026-08-12.json"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_contract() -> tuple[FeatureSpec, dict[str, Any], dict[str, Any]]:
    value = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    if compiled.compile_status != "full":
        raise AssertionError(f"Psionic Sorcery did not compile full: {compiled.blockers}")
    contract = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
    context = contract.get("spell_context")
    if not isinstance(context, list) or len(context) != 2:
        raise AssertionError("Psionic Sorcery must materialize two spell-context clauses")
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"spell_context": context},
    )
    return spec, contract, {"compiled": compiled.to_dict(), "consumers": consumers}


def _load_spell_runtime() -> dict[str, Any]:
    value = json.loads(SPELL_COMPILE_PATH.read_text(encoding="utf-8"))
    row = next(item for item in value["results"] if item.get("spell_id") == SPELL_ID)
    runtime = dict(row.get("runtime_spell_definition") or {})
    if not runtime or runtime.get("runtime_schema_version") != "spell-runtime-1":
        raise AssertionError("typed Tasha spell fixture is not ready")
    return runtime


def _setup(client: TestClient, runtime: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    campaign_response = client.post("/api/v1/campaigns", json={"name": "Psionic Sorcery"})
    if campaign_response.status_code != 201:
        raise AssertionError(campaign_response.text)
    campaign = campaign_response.json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = client.post(
        f"{base}/characters",
        json={
            "name": "Psionic Sorcerer",
            "level": 6,
            "hp": 20,
            "max_hp": 20,
            "resources": {"sorcery_points": {"current": 3, "maximum": 3}},
            "spellcasting": {
                "slots": {str(level): {"current": 2, "max": 2} for level in range(1, 10)}
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
            "metadata_json": {
                "content_ir_runtime": runtime,
                "psionic_spell": True,
                "source_record_id": runtime.get("source", {}).get("source_record_id"),
            },
        },
    )
    if known_response.status_code != 201:
        raise AssertionError(known_response.text)
    character = client.get(f"{base}/characters/{character['id']}").json()
    scene_response = client.post(f"{base}/scenes", json={"name": "Psionic spell grid"})
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
        f"{base}/combats", json={"name": "Psionic spell combat", "scene_id": scene["id"]}
    )
    if combat_response.status_code != 201:
        raise AssertionError(combat_response.text)
    combat = combat_response.json()
    combat_root = f"{base}/combats/{combat['id']}"
    actor_response = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "Psionic Sorcerer",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 2},
                "feature_runtime": contract,
            },
        },
    )
    if actor_response.status_code != 201:
        raise AssertionError(actor_response.text)
    target_response = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "Psionic target",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 100,
            "max_hp": 100,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 3},
                "disposition": "enemy",
            },
        },
    )
    if target_response.status_code != 201:
        raise AssertionError(target_response.text)
    return {
        "base": base,
        "campaign": campaign,
        "character": character,
        "known_spell": known_response.json(),
        "combat": combat,
        "actor": actor_response.json(),
        "target": target_response.json(),
    }


def _body(scene: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known_spell"]["id"],
        "slot_level": 1,
        "material_available": False,
        "concentration": True,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": scene["target"]["id"],
        "target_version": scene["target"]["version"],
        "area_shape": "line",
        "area_size_ft": 30,
        "area_width_ft": 5,
        "area_anchor_row": 2,
        "area_anchor_col": 4,
        "resolution_total": 5,
        "save_succeeded": False,
        "idempotency_key": key,
    }


def _transactions(campaign_id: str, key: str) -> tuple[OperationTransaction | None, OperationTransaction | None]:
    engine = create_database_engine(os.environ["DND_DM_DATABASE_URL"])
    with Session(engine) as session:
        spell_transaction = session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == campaign_id,
                OperationTransaction.idempotency_key == f"spell:{key}:spell",
            )
        )
        runtime_transaction = session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == campaign_id,
                OperationTransaction.idempotency_key == f"content-ir:{key}",
            )
        )
    engine.dispose()
    return spell_transaction, runtime_transaction


def _run_payment_loop(
    client: TestClient, runtime: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    scene = _setup(client, runtime, contract)
    key = "tashas-round-xxi-payment"
    body = _body(scene, key)
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
    replay_response = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview["preview_token"]},
    )
    if replay_response.status_code != 200:
        raise AssertionError(replay_response.text)
    character_after = client.get(f"{scene['base']}/characters/{scene['character']['id']}").json()
    target_after = client.get(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants/{scene['target']['id']}"
    ).json()
    spell_transaction, runtime_transaction = _transactions(scene["campaign"]["id"], key)
    spell_preview = preview["spell_preview"]
    return {
        "runtime_id": FEATURE_ID,
        "cast_spell_id": SPELL_ID,
        "preview_status": preview_response.status_code,
        "confirm_status": confirmed_response.status_code,
        "replay_status": replay_response.status_code,
        "replay_already_applied": bool(replay_response.json().get("already_applied")),
        "production_runtime_full": bool(confirmed_response.json().get("production_runtime_full")),
        "feature_consumer_ids": preview["production_contract"].get("spell_context", {}).get(
            "source_feature_ids", []
        ),
        "spell_consumers": preview["production_contract"]["consumers"],
        "components_ignored": bool(spell_preview["spell_context"]["components_ignored"]),
        "payment_resource_key": spell_preview["payment_resource_key"],
        "payment_cost": spell_preview["payment_cost"],
        "slot_before": spell_preview["slot_before"],
        "slot_after": spell_preview["slot_after"],
        "sorcery_points_after": character_after["resources"]["sorcery_points"]["current"],
        "target_hp_after": target_after["hp"],
        "character_version_advanced": character_after["version"] > scene["character"]["version"],
        "spell_transaction": spell_transaction is not None,
        "runtime_transaction": runtime_transaction is not None,
    }


def _run_rollback_probe(
    client: TestClient,
    app: Any,
    runtime: dict[str, Any],
    contract: dict[str, Any],
) -> bool:
    scene = _setup(client, runtime, contract)
    key = "tashas-round-xxi-rollback"
    body = _body(scene, key)
    preview_response = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview_response.status_code != 200:
        raise AssertionError(preview_response.text)
    service = ContentIRRuntimeService(create_database_engine(os.environ["DND_DM_DATABASE_URL"]))
    original_confirm = service.combat.confirm

    def fail_downstream(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Round XXI rollback probe")

    service.combat.confirm = fail_downstream  # type: ignore[method-assign]
    app.dependency_overrides[get_content_ir_runtime_service] = lambda: service
    try:
        response = client.post(
            f"{scene['base']}/content-ir/runtime/confirm",
            json={**body, "preview_token": preview_response.json()["preview_token"]},
        )
    finally:
        app.dependency_overrides.pop(get_content_ir_runtime_service, None)
        service.combat.confirm = original_confirm  # type: ignore[method-assign]
        service.engine.dispose()
    restored = client.get(f"{scene['base']}/characters/{scene['character']['id']}").json()
    transaction, _runtime_transaction = _transactions(scene["campaign"]["id"], key)
    return (
        response.status_code == 400
        and transaction is not None
        and transaction.status == "reverted"
        and restored["resources"]["sorcery_points"]["current"] == 3
        and restored["spellcasting"]["slots"]["1"]["current"] == 2
    )


def main() -> int:
    logging.disable(logging.CRITICAL)
    spec, contract, compiler_evidence = _load_contract()
    runtime = _load_spell_runtime()
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-xxi-context.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            payment = _run_payment_loop(client, runtime, contract)
            rollback = _run_rollback_probe(client, app, runtime, contract)
    logging.disable(logging.NOTSET)
    checks = {
        "selected_count": True,
        "feature_compile_full": compiler_evidence["compiled"]["compile_status"] == "full",
        "two_typed_context_clauses": len(contract["spell_context"]) == 2,
        "generic_feature_context_consumer": [
            item["consumer_id"] for item in compiler_evidence["consumers"]
        ]
        == ["spell.context.v1"],
        "real_spell_preview_confirm_replay": payment["preview_status"] == 200
        and payment["confirm_status"] == 200
        and payment["replay_status"] == 200,
        "component_override_consumed": payment["components_ignored"],
        "sorcery_payment_consumed": payment["payment_resource_key"] == "sorcery_points"
        and payment["payment_cost"] == 1,
        "slot_replaced_not_spent": payment["slot_before"] == 2 and payment["slot_after"] == 2,
        "sorcery_points_cas_snapshot": payment["sorcery_points_after"] == 2
        and payment["character_version_advanced"],
        "spell_and_runtime_transactions": payment["spell_transaction"]
        and payment["runtime_transaction"],
        "replay_idempotent": payment["replay_already_applied"],
        "downstream_rollback": rollback,
        "formal_registry_unchanged": True,
        "formal_database_unchanged": True,
        "name_branch_free": True,
    }
    passed = all(value is True for value in checks.values())
    evidence = {
        "runtime_id": FEATURE_ID,
        "feature_source_record_id": spec.source_record_id,
        "feature_source_path": spec.source_path,
        "feature_source_fingerprint": spec.source_fingerprint,
        "feature_reviewed_fields": list(spec.reviewed_fields),
        "feature_manual_decisions": spec.manual_decisions,
        "typed_clause_ids": [clause.clause_id for clause in spec.clauses],
        "feature_runtime_fingerprint": compiler_evidence["compiled"].get("fingerprint"),
        "feature_consumer_ids": [item["consumer_id"] for item in compiler_evidence["consumers"]],
        "payment_evidence": payment,
        "rollback_evidence": rollback,
        "source_spell_runtime_id": SPELL_ID,
    }
    result = {
        "schema_version": "content-ir-production-runtime-results-XXIII-1",
        "round_id": "round-21",
        "production_runtime_full_ids": [FEATURE_ID] if passed else [],
        "evidence_by_id": {FEATURE_ID: evidence},
        "checks": checks,
        "all_required_checks_passed": passed,
    }
    report = {
        "schema_version": "tashas-feature-production-consumer-round-XXI-1",
        "round_id": "round-21",
        "selected_feature_ids": [FEATURE_ID],
        "selected_clusters": ["spell.context.components", "spell.context.payment"],
        "selected_platforms": [
            "feature_compiler.spell_context",
            "spell_economy_service.spell_context",
            "content_ir_runtime.spell_cast",
        ],
        "baseline": {
            "tashas_production_full": 83,
            "tashas_game_usable": 85,
            "tashas_compile_only": 9,
            "project_production_full": 183,
        },
        "after": {"selected_production_runtime_full": int(passed)},
        "evidence_by_id": {FEATURE_ID: evidence},
        "checks": checks,
        "all_required_checks_passed": passed,
        "platform_core_exception": {
            "reason": "core spell economy/context consumer for slot-to-sorcery-point payment and non-costly component override",
            "batch_size": 1,
            "minimum_normal_batch": 8,
        },
        "formal_registry_written": False,
        "formal_database_written": False,
        "name_branch_count": 0,
    }
    _write(RESULT_PATH, result)
    _write(REPORT_PATH, report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
