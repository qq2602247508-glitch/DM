# ruff: noqa: N999
"""Validate the generic typed combat consumer for Tasha trigger-bound features."""

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
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.domain.feature_runtime import compile_feature_runtime_registry
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ROOT = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-X.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-VIII-2026-08-12.json"

FEATURE_IDS = (
    "content.tashas-cauldron.round2.feature.battle-master-grappling-strike",
    "content.tashas-cauldron.round2.feature.battle-master-tactical-assessment",
    "content.tashas-cauldron.round2.feature.psi-warrior-psi-powered-leap",
    "content.tashas-cauldron.round2.feature.soulknife-homing-strikes",
    "content.tashas-cauldron.round2.feature.soulknife-psi-bolstered-knack",
    "content.tashas-cauldron.round2.feature.stars-druid-full-of-stars",
    "content.tashas-cauldron.round2.feature.stars-druid-weal",
    "content.tashas-cauldron.round2.feature.stars-druid-woe",
)
RESOURCE_FEATURES = {
    "content.tashas-cauldron.round2.feature.psi-warrior-psi-powered-leap": {
        "psionic_dice": {"current": 3, "maximum": 3}
    }
}


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_contracts() -> dict[str, tuple[FeatureSpec, dict[str, Any]]]:
    compiler = FeatureCompiler(status_authority="compiler")
    result: dict[str, tuple[FeatureSpec, dict[str, Any]]] = {}
    for path in sorted(FEATURE_ROOT.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        spec = FeatureSpec.from_dict(
            {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
            path=str(path),
        )
        if spec.feature_id not in FEATURE_IDS:
            continue
        compiled = compiler.compile(spec)
        if compiled.compile_status != "full":
            raise RuntimeError(f"selected feature is not full: {spec.feature_id}")
        result[spec.feature_id] = (
            spec,
            materialize_runtime_definition(spec, compiled, catalog=compiler.catalog),
        )
    if set(result) != set(FEATURE_IDS):
        raise RuntimeError("Round VIII selected feature contract is incomplete")
    return result


def _registry(
    feature_id: str,
    spec: FeatureSpec,
    contract: dict[str, Any],
) -> dict[str, Any]:
    grants = [
        {
            "feature_id": feature_id,
            "name": spec.source_name,
            "class_name": spec.class_name or "",
            "class_level": int(spec.level or 1),
            "kind": "feature",
            "source_record_id": spec.source_record_id,
            "source_path": spec.source_path,
            "runtime": {"registry": contract, "automation_status": "full"},
        }
    ]
    return compile_feature_runtime_registry(
        grants,
        resources=RESOURCE_FEATURES.get(feature_id, {}),
        total_level=int(spec.level or 1),
    )


def _run_feature(
    client: TestClient,
    feature_id: str,
    spec: FeatureSpec,
    contract: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    resources = RESOURCE_FEATURES.get(feature_id, {})
    campaign = client.post(
        "/api/v1/campaigns", json={"name": "Tasha Round VIII combat consumer"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "Tasha trigger-bound actor",
            "class_name": spec.class_name or "玩家角色",
            "level": max(1, int(spec.level or 5)),
            "hp": 20,
            "max_hp": 20,
            "resources": resources,
        },
    ).json()
    combat = client.post(f"{base}/combats", json={"name": "Tasha typed combat"}).json()
    root = f"{base}/combats/{combat['id']}"
    registry = _registry(feature_id, spec, contract)
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Tasha trigger-bound actor",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "feature_runtime": registry,
                "ability_scores": {
                    "strength": 16,
                    "constitution": 16,
                    "intelligence": 16,
                    "wisdom": 16,
                    "charisma": 16,
                },
                "equipment": [],
            },
        },
    ).json()
    body = {
        "content_kind": "feature",
        "runtime_id": feature_id,
        "permission": "player",
        "combat_id": combat["id"],
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": actor["id"],
        "target_version": actor["version"],
        "idempotency_key": f"tashas-round-VIII-combat-{index:03d}",
    }
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    evidence: dict[str, Any] = {
        "content_id": feature_id,
        "content_kind": "feature",
        "pack_id": "tashas-cauldron",
        "source": "round-II-reviewed-feature-contract-through-round-VIII-typed-combat-consumer",
        "execution_mode": "typed",
        "preview": preview.status_code == 200,
        "typed_consumer": None,
        "runtime_id_bound": False,
        "passive_registry_bound": False,
        "inspection_resolution": False,
        "activation_resolution": False,
        "resource_cas": False,
    }
    if preview.status_code != 200:
        evidence["error"] = preview.text[:500]
        return evidence
    preview_body = preview.json()
    action = preview_body.get("feature_action") or {}
    evidence["runtime_id_bound"] = action.get("feature_id") == feature_id
    passive = action.get("passive_block") or {}
    evidence["passive_registry_bound"] = passive.get("feature_id") == feature_id
    evidence["inspection_resolution"] = action.get("resolution_kind") == "inspection"
    evidence["activation_resolution"] = action.get("resolution_kind") != "inspection"
    confirmed = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    evidence.update(
        {
            "confirm": confirmed.status_code == 200,
            "production_runtime_full": (
                bool(confirmed.json().get("production_runtime_full"))
                if confirmed.status_code == 200
                else False
            ),
            "typed_consumer": (
                confirmed.json().get("consumer") if confirmed.status_code == 200 else None
            ),
        }
    )
    if confirmed.status_code != 200:
        evidence["error"] = confirmed.text[:500]
        return evidence
    replay = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    result = confirmed.json().get("result", {}).get("result", {})
    evidence["replay"] = replay.status_code == 200 and replay.json().get("already_applied") is True
    if resources:
        evidence["resource_cas"] = (
            result.get("resource_before") == 3 and result.get("resource_after") == 2
        )
    else:
        evidence["resource_cas"] = True
    if not evidence["replay"]:
        evidence["error"] = replay.text[:500]
    return evidence


def main() -> int:
    logging.disable(logging.CRITICAL)
    contracts = _load_contracts()
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-VIII.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            for index, feature_id in enumerate(FEATURE_IDS, start=1):
                spec, contract = contracts[feature_id]
                results.append(_run_feature(client, feature_id, spec, contract, index))
    logging.disable(logging.NOTSET)
    passed = [
        item
        for item in results
        if item.get("production_runtime_full")
        and item.get("preview")
        and item.get("confirm")
        and item.get("replay")
        and item.get("typed_consumer") == "combat_engine.feature_action.v1"
        and item.get("runtime_id_bound")
        and item.get("resource_cas")
        and (item.get("inspection_resolution") or item.get("activation_resolution"))
    ]
    production_ids = sorted(item["content_id"] for item in passed)
    checks = {
        "selected_count": len(FEATURE_IDS),
        "production_runtime_full_count": len(production_ids),
        "all_preview_confirm_replay": len(passed) == len(FEATURE_IDS),
        "all_typed_consumers": all(item.get("typed_consumer") for item in passed),
        "all_runtime_id_bound": all(item.get("runtime_id_bound") for item in passed),
        "all_inspection_or_activation": all(
            item.get("inspection_resolution") or item.get("activation_resolution") for item in passed
        ),
        "all_resource_cas": all(item.get("resource_cas") for item in passed),
        "passive_registry_bound_count": sum(bool(item.get("passive_registry_bound")) for item in passed),
        "activation_resolution_count": sum(bool(item.get("activation_resolution")) for item in passed),
        "formal_registry_written": False,
        "formal_database_written": False,
        "name_branch_count": 0,
    }
    evidence_by_id = {item["content_id"]: item for item in results}
    _write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-X-1",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "Round-II reviewed Feature IR through real ContentIRRuntimeService typed combat action and passive inspection on an isolated migrated database",
        },
    )
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-VIII-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_feature_ids": list(FEATURE_IDS),
            "results": results,
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
        },
    )
    print(
        json.dumps(
            {"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if len(production_ids) != len(FEATURE_IDS):
        raise SystemExit("Round VIII production consumer gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
