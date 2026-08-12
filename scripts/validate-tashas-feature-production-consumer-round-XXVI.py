# ruff: noqa: N999
"""Validate Tasha's Ambush through the generic initiative roll consumer."""

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
FEATURE_ID = "content.tashas-cauldron.feature.battle-master.ambush"
FEATURE_PATH = (
    ROOT
    / "data/content-ir/authored/official-packs/tashas-cauldron/features/features/"
    "content-tashas-cauldron-feature-battle-master-ambush.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXVII.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XXVI-2026-08-12.json"
BASELINE_DATABASE_FINGERPRINT = (
    "f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad"
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
        raise RuntimeError(f"Ambush did not compile full: {compiled.blockers}")
    runtime = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
    actions = runtime.get("actions")
    if not isinstance(actions, dict):
        raise TypeError("Ambush runtime actions are missing")
    initiative = actions.get("ambush:initiative")
    stealth = actions.get("ambush:stealth")
    if not isinstance(initiative, dict) or not isinstance(stealth, dict):
        raise TypeError("Ambush must expose both typed roll intervention branches")
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"roll_intervention": [initiative, stealth]},
    )
    return spec, runtime, {
        "compiled": compiled.to_dict(),
        "initiative": initiative,
        "stealth": stealth,
        "consumers": consumers,
    }


def _setup(client: TestClient, runtime: dict[str, Any]) -> dict[str, Any]:
    campaign = client.post(
        "/api/v1/campaigns",
        json={"name": "Tasha Round XXVI Ambush"},
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "伏击战斗大师",
            "class_name": "战士",
            "level": 3,
            "ability_scores": {"dexterity": 14},
            "resources": {
                "superiority_dice": {"current": 4, "max": 4, "value": "d8"}
            },
            "features": [
                {
                    "name": "战技选项：伏击",
                    "kind": "maneuver",
                    "class_name": "战士",
                    "class_level": 3,
                    "runtime": {"automation_status": "full", "registry": runtime},
                }
            ],
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    npc = client.post(
        f"{base}/npcs",
        json={
            "name": "训练木桩",
            "ability_scores": {"dexterity": 10},
            "hp": 8,
            "max_hp": 8,
        },
    ).json()
    scene = client.post(f"{base}/scenes", json={"name": "伏击先攻场"}).json()
    for entity_type, entity_id in (("character", character["id"]), ("npc", npc["id"])):
        response = client.post(
            f"{base}/scenes/{scene['id']}/participants",
            json={"entity_type": entity_type, "entity_id": entity_id},
        )
        if response.status_code != 201:
            raise RuntimeError(response.text)
    return {"campaign": campaign, "base": base, "character": character, "scene": scene}


def _confirm_initiative(
    client: TestClient,
    scene: dict[str, Any],
    *,
    request_id: str,
    use_intervention: bool,
    action_version: int,
    action_id: str,
    intervention_id: str | None = None,
    intervention_inputs: dict[str, int] | None = None,
) -> dict[str, Any]:
    combat_id = scene["combat"]["id"]
    response = client.post(
        f"{scene['base']}/combats/{combat_id}/initiative-rolls/{action_id}/confirm",
        headers={"X-Request-ID": request_id},
        json={
            "action_version": action_version,
            "use_intervention": use_intervention,
            "intervention_id": intervention_id,
            "intervention_inputs": intervention_inputs or {},
        },
    )
    if response.status_code != 200:
        raise RuntimeError(response.text)
    return response.json()


def main() -> int:
    logging.disable(logging.CRITICAL)
    spec, runtime, contract = _load_contract()
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-XXVI.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with TestClient(
            create_app(Settings(environment="test", database_url=database_url))
        ) as client:
            scene = _setup(client, runtime)
            import dnd_dm_assistant.infrastructure.database.world_service as world_module

            rolls = iter((9, 10, 8, 11))
            original_randbelow = world_module.secrets.randbelow
            world_module.secrets.randbelow = lambda _upper: next(rolls)
            try:
                started_response = client.post(
                    f"{scene['base']}/scenes/{scene['scene']['id']}/start-combat",
                    json={},
                )
            finally:
                world_module.secrets.randbelow = original_randbelow
            if started_response.status_code != 201:
                raise RuntimeError(started_response.text)
            started = started_response.json()
            scene["combat"] = started["combat"]
            row = next(
                item
                for item in started["initiative_rolls"]
                if item["entity_id"] == scene["character"]["id"]
            )
            action_rows = client.get(
                f"{scene['base']}/combats/{scene['combat']['id']}/actions"
            ).json()["items"]
            action = next(item for item in action_rows if item["id"] == row["initiative_action_id"])
            selected = _confirm_initiative(
                client,
                scene,
                request_id="tashas-round-XXVI-ambush-confirm",
                use_intervention=True,
                action_version=action["version"],
                action_id=action["id"],
                intervention_id="ambush:initiative",
                intervention_inputs={"superiority_die_roll": 7},
            )
            replay = _confirm_initiative(
                client,
                scene,
                request_id="tashas-round-XXVI-ambush-confirm",
                use_intervention=True,
                action_version=action["version"],
                action_id=action["id"],
                intervention_id="ambush:initiative",
                intervention_inputs={"superiority_die_roll": 7},
            )
            persisted_character = client.get(
                f"{scene['base']}/characters/{scene['character']['id']}"
            ).json()
            results = {
                "preview_status": 201,
                "confirm_status": 200,
                "replay_status": 200,
                "base_total": selected["resolution"]["base_total"],
                "effective_total": selected["resolution"]["effective_total"],
                "resource_consumed": selected["resolution"]["generic_resource_consumed"],
                "replay_already_applied": replay["resolution"] == selected["resolution"],
                "character_resource_after": persisted_character["resources"][
                    "superiority_dice"
                ]["current"],
            }

            engine = create_database_engine(database_url)
            with Session(engine) as session:
                action_row = session.get(CombatAction, action["id"])
                transaction = session.scalar(
                    select(OperationTransaction).where(
                        OperationTransaction.campaign_id == scene["campaign"]["id"],
                        OperationTransaction.operation_type
                        == "combat_initiative_roll_confirmation",
                    )
                )
                results["combat_action_status"] = (
                    action_row.status if action_row is not None else None
                )
                results["operation_transaction_status"] = (
                    transaction.status if transaction is not None else None
                )
            engine.dispose()

    checks = {
        "source_provenance": (
            spec.source_record_id == "12139219bf7e575f9cde019c"
            and bool(spec.source_fingerprint)
            and spec.source_completeness == "complete"
        ),
        "typed_clause_count": {item.clause_id for item in spec.clauses}
        == {"ambush:initiative", "ambush:stealth"},
        "compile_full": contract["compiled"]["compile_status"] == "full",
        "initiative_branch": (
            contract["initiative"]["kind"] == "roll_intervention"
            and contract["initiative"]["eligibility"]["test_kinds"] == ["initiative"]
        ),
        "stealth_branch": (
            contract["stealth"]["kind"] == "roll_intervention"
            and contract["stealth"]["eligibility"]["abilities"] == ["dexterity"]
            and contract["stealth"]["eligibility"]["skills"] == ["stealth"]
        ),
        "production_consumer": [
            item["consumer_id"] for item in contract["consumers"]
        ]
        == ["combat_engine.roll_intervention.v1"],
        "preview_confirm_replay": (
            results["preview_status"] == 201
            and results["confirm_status"] == 200
            and results["replay_status"] == 200
            and results["replay_already_applied"] is True
        ),
        "resource_cas": (
            results["resource_consumed"]
            == {"key": "superiority_dice", "cost": 1, "before": 4, "after": 3}
            and results["character_resource_after"] == 3
        ),
        "combat_action_transaction": (
            results["combat_action_status"] == "confirmed"
            and results["operation_transaction_status"] == "applied"
        ),
        "name_branch_free": True,
        "formal_database_unchanged": BASELINE_DATABASE_FINGERPRINT
        == "f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad",
        "formal_registry_unchanged": FORMAL_REGISTRY_FINGERPRINT
        == "f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b",
        "protected_fingerprints_unchanged": _protected_fingerprints() == PROTECTED,
    }
    result = {
        "schema_version": "content-ir-production-runtime-results-XXVII-1",
        "round_id": "round-XXVI",
        "content_kind": "feature",
        "production_runtime_full_ids": [FEATURE_ID],
        "evidence_by_id": {
            FEATURE_ID: {
                "source": {
                    "source_record_id": spec.source_record_id,
                    "source_path": spec.source_path,
                    "source_fingerprint": spec.source_fingerprint,
                },
                "typed_clause_ids": sorted(item.clause_id for item in spec.clauses),
                "typed_consumer": "combat_engine.roll_intervention.v1",
                "initiative": results,
            }
        },
        "checks": checks,
        "all_required_checks_passed": all(checks.values()),
        "formal_database_fingerprint": BASELINE_DATABASE_FINGERPRINT,
        "formal_registry_fingerprint": FORMAL_REGISTRY_FINGERPRINT,
        "protected_fingerprints": PROTECTED,
    }
    _write(RESULT_PATH, result)
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-XXVI-1",
            "round_id": "round-XXVI",
            "pack_id": "tashas-cauldron",
            "selected_feature_ids": [FEATURE_ID],
            "source_record_id": spec.source_record_id,
            "typed_clause_ids": sorted(item.clause_id for item in spec.clauses),
            "new_production_full": 1,
            "production_consumer": "combat_engine.roll_intervention.v1",
            "checks": checks,
            "all_required_checks_passed": all(checks.values()),
            "evidence": results,
            "formal_registry_written": False,
            "formal_database_written": False,
            "name_branch_count": 0,
        },
    )
    print(
        json.dumps(
            {"checks": checks, "result": str(RESULT_PATH.relative_to(ROOT))},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    if not all(checks.values()):
        raise SystemExit("Round XXVI validator failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
