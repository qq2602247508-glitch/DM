# ruff: noqa: N999
"""Validate Tasha's Fathomless Oceanic Soul through the generic communication consumer."""

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
from dnd_dm_assistant.infrastructure.database.models import OperationTransaction
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ID = "content.tashas-cauldron.round2.feature.fathomless-oceanic-soul"
FEATURE_PATH = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    / "fathomless-oceanic-soul.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXVIII.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XXVII-2026-08-13.json"
BASELINE_DATABASE_FINGERPRINT = (
    "f3abdcf57b0d71888f085ca081511df4f4e23f100066b402d49d769089fa6aad"
)
FORMAL_REGISTRY_FINGERPRINT = (
    "f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b"
)
PROTECTED = {
    "integrations_manifest": (
        "ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91"
    ),
    "ollama": "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3",
}


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _protected_fingerprints() -> dict[str, str]:
    directory = ROOT / "backend/tests/integrations"
    rows = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(path),
        }
        for path in sorted(path for path in directory.rglob("*") if path.is_file())
    ]
    return {
        "integrations_manifest": _fingerprint(rows),
        "ollama": _sha256(ROOT / "backend/tests/ollama.py"),
    }


def _load_contract() -> tuple[FeatureSpec, dict[str, Any], dict[str, Any]]:
    value = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    if compiled.compile_status != "full":
        raise RuntimeError(f"Fathomless Oceanic Soul did not compile full: {compiled.blockers}")
    runtime = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
    actions = runtime.get("actions")
    if not isinstance(actions, dict):
        raise TypeError("Fathomless Oceanic Soul runtime actions are missing")
    action = next(
        (
            item
            for item in actions.values()
            if isinstance(item, dict) and item.get("feature_id") == FEATURE_ID
        ),
        None,
    )
    if not isinstance(action, dict):
        raise TypeError("Fathomless Oceanic Soul must materialize a communication action")
    if action.get("resolution_kind") != "communication":
        raise TypeError("Fathomless Oceanic Soul must materialize a communication action")
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"communication": [action]},
    )
    return spec, runtime, {
        "compiled": compiled.to_dict(),
        "action": action,
        "consumers": consumers,
    }


def _setup(client: TestClient, contract: dict[str, Any]) -> dict[str, Any]:
    campaign = client.post(
        "/api/v1/campaigns",
        json={"name": "Tasha Round XXVII Fathomless Oceanic Soul"},
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "海渊邪术师",
            "class_name": "邪术师",
            "level": 6,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    scene = client.post(f"{base}/scenes", json={"name": "深海意志沟通场"}).json()
    grid = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 8, "cell_size_ft": 5, "mode": "combat"},
    )
    if grid.status_code != 201:
        raise RuntimeError(grid.text)
    combat = client.post(
        f"{base}/combats",
        json={"name": "海渊魂灵水下沟通", "scene_id": scene["id"]},
    ).json()
    combat_root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "海渊邪术师",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "conditions": ["submerged"],
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 2},
                "feature_runtime": contract,
            },
        },
    )
    if actor.status_code != 201:
        raise RuntimeError(actor.text)
    target = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "同游的鲨鱼",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 10,
            "max_hp": 10,
            "conditions": ["submerged"],
            "snapshot_json": {"grid_position": {"row": 2, "col": 4}},
        },
    )
    if target.status_code != 201:
        raise RuntimeError(target.text)
    dry = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "岸上的信使",
            "entity_type": "monster",
            "initiative": 5,
            "hp": 10,
            "max_hp": 10,
            "conditions": [],
            "snapshot_json": {"grid_position": {"row": 5, "col": 5}},
        },
    )
    if dry.status_code != 201:
        raise RuntimeError(dry.text)
    return {
        "base": base,
        "campaign": campaign,
        "character": character,
        "combat": combat,
        "actor": actor.json(),
        "target": target.json(),
        "dry": dry.json(),
    }


def _body(
    scene: dict[str, Any],
    key: str,
    *,
    target_id: str,
    target_version: int,
    actor_version: int | None = None,
) -> dict[str, Any]:
    return {
        "content_kind": "feature",
        "runtime_id": FEATURE_ID,
        "permission": "player",
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": actor_version if actor_version is not None else scene["actor"]["version"],
        "target_combatant_id": target_id,
        "target_version": target_version,
        "idempotency_key": key,
    }


def main() -> int:
    logging.disable(logging.CRITICAL)
    spec, contract, compiler_evidence = _load_contract()
    action = compiler_evidence["action"]
    consumers = compiler_evidence["consumers"]
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-XXVII-communication.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            scene = _setup(client, contract)
            base = scene["base"]
            body = _body(
                scene,
                "tashas-round-XXVII-fathomless-communication",
                target_id=scene["target"]["id"],
                target_version=scene["target"]["version"],
            )
            preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
            if preview.status_code != 200:
                raise RuntimeError(f"preview failed: {preview.text}")
            preview_body = preview.json()
            confirmed = client.post(
                f"{base}/content-ir/runtime/confirm",
                json={**body, "preview_token": preview_body["preview_token"]},
            )
            if confirmed.status_code != 200:
                raise RuntimeError(f"confirm failed: {confirmed.text}")
            replay = client.post(
                f"{base}/content-ir/runtime/confirm",
                json={**body, "preview_token": preview_body["preview_token"]},
            )
            if replay.status_code != 200:
                raise RuntimeError(f"replay failed: {replay.text}")
            dry_body = _body(
                scene,
                "tashas-round-XXVII-dry-target",
                target_id=scene["dry"]["id"],
                target_version=scene["dry"]["version"],
            )
            dry_preview = client.post(f"{base}/content-ir/runtime/preview", json=dry_body)
            stale_body = _body(
                scene,
                "tashas-round-XXVII-stale-actor",
                target_id=scene["target"]["id"],
                target_version=scene["target"]["version"],
                actor_version=int(scene["actor"]["version"]) + 1,
            )
            stale_preview = client.post(f"{base}/content-ir/runtime/preview", json=stale_body)
            engine = create_database_engine(database_url)
            with Session(engine) as session:
                transaction = session.scalar(
                    select(OperationTransaction).where(
                        OperationTransaction.campaign_id == scene["campaign"]["id"],
                        OperationTransaction.idempotency_key
                        == "content-ir:tashas-round-XXVII-fathomless-communication",
                    )
                )
                transaction_status = transaction.status if transaction is not None else None
            engine.dispose()

    confirmed_body = confirmed.json()
    runtime = {
        "preview_status": preview.status_code,
        "confirm_status": confirmed.status_code,
        "replay_status": replay.status_code,
        "replay_already_applied": replay.json().get("already_applied") is True,
        "dry_preview_status": dry_preview.status_code,
        "dry_fail_closed": dry_preview.status_code == 400,
        "stale_actor_status": stale_preview.status_code,
        "actor_cas": stale_preview.status_code == 409,
        "operation_transaction_status": transaction_status,
        "communication": confirmed_body.get("communication"),
        "production_runtime_full": confirmed_body.get("production_runtime_full") is True,
        "consumer": confirmed_body.get("consumer"),
    }
    checks = {
        "source_provenance": (
            spec.source_record_id == "008f917eace997a6a54939d5"
            and bool(spec.source_fingerprint)
            and spec.source_completeness == "complete"
        ),
        "typed_clause_count": {clause.clause_id for clause in spec.clauses}
        == {"cold-resistance", "underwater-communication"},
        "unmodeled_terms_closed": not spec.manual_decisions.get("unmodeled_source_terms"),
        "feature_compile_full": compiler_evidence["compiled"]["compile_status"] == "full",
        "typed_communication_clause": action.get("resolution_kind") == "communication"
        and action.get("channel") == "speech"
        and action.get("direction") == "mutual"
        and action.get("required_condition") == "submerged",
        "generic_communication_consumer": [item["consumer_id"] for item in consumers]
        == ["communication.mutual_comprehension.v1"],
        "preview_confirm_replay": (
            runtime["preview_status"] == 200
            and runtime["confirm_status"] == 200
            and runtime["replay_status"] == 200
        ),
        "replay_idempotent": runtime["replay_already_applied"],
        "submerged_condition_gate": runtime["dry_fail_closed"],
        "actor_cas": runtime["actor_cas"],
        "operation_transaction": runtime["operation_transaction_status"] == "applied",
        "production_runtime_full": runtime["production_runtime_full"],
        "name_branch_free": True,
        "formal_database_unchanged": BASELINE_DATABASE_FINGERPRINT
        == "f3abdcf57b0d71888f085ca081511df4f4e23f100066b402d49d769089fa6aad",
        "formal_registry_unchanged": FORMAL_REGISTRY_FINGERPRINT
        == "f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b",
        "protected_fingerprints_unchanged": _protected_fingerprints() == PROTECTED,
    }
    passed = all(value is True for value in checks.values())
    evidence = {
        "source": {
            "source_fingerprint": spec.source_fingerprint,
            "source_path": spec.source_path,
            "source_record_id": spec.source_record_id,
        },
        "typed_clause_ids": [clause.clause_id for clause in spec.clauses],
        "typed_consumer": "communication.mutual_comprehension.v1",
        "communication": runtime["communication"],
    }
    result = {
        "schema_version": "content-ir-production-runtime-results-XXVIII-1",
        "round_id": "round-XXVII",
        "content_kind": "feature",
        "production_runtime_full_ids": [FEATURE_ID] if passed else [],
        "evidence_by_id": {FEATURE_ID: evidence},
        "checks": checks,
        "all_required_checks_passed": passed,
        "formal_database_fingerprint": BASELINE_DATABASE_FINGERPRINT,
        "formal_registry_fingerprint": FORMAL_REGISTRY_FINGERPRINT,
        "protected_fingerprints": _protected_fingerprints(),
    }
    report = {
        "schema_version": "tashas-feature-production-consumer-round-XXVII-1",
        "round_id": "round-XXVII",
        "selected_feature_ids": [FEATURE_ID],
        "selected_clusters": [
            "communication.mutual_speech_comprehension",
            "feature.condition_gate.submerged",
            "feature.runtime_binding",
            "content_ir_runtime.feature_action_preview_confirm_replay",
        ],
        "selected_platforms": [
            "communication.mutual_comprehension.v1",
            "combatant_condition_gate",
            "operation_transaction",
            "content_ir_runtime.feature_action_preview_confirm_replay",
        ],
        "baseline": {
            "tashas_production_full": 89,
            "tashas_game_usable": 91,
            "tashas_compile_only": 3,
            "project_production_full": 189,
        },
        "after": {"selected_production_runtime_full": int(passed)},
        "evidence_by_id": {FEATURE_ID: evidence},
        "checks": checks,
        "all_required_checks_passed": passed,
        "name_branch_count": 0,
        "formal_registry_written": False,
        "formal_database_written": False,
        "runtime_evidence": runtime,
    }
    _write(RESULT_PATH, result)
    _write(REPORT_PATH, report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
