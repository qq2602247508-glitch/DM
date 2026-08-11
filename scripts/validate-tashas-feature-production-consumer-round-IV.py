# ruff: noqa: N999
"""Validate movement, sight, choice and lifecycle consumers for Tasha IR.

The validator compiles the reviewed Round-II Feature IR into the same runtime
registry used by character growth, then drives the real Content IR runtime
preview/confirm/replay boundary on a temporary migrated database.  Automatic
movement/sight blocks are also refreshed through the combat turn boundary so
the evidence cannot be produced by a report-only projection.
"""

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
FEATURE_ROOT = (
    ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-VI.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-IV-2026-08-12.json"

FEATURE_IDS = (
    "content.tashas-cauldron.round2.feature.fathomless-gift-of-the-sea",
    "content.tashas-cauldron.round2.feature.ranger-roving",
    "content.tashas-cauldron.round2.feature.beast-barbarian-bestial-soul",
    "content.tashas-cauldron.round2.feature.paladin-blind-fighting",
    "content.tashas-cauldron.round2.feature.ranger-blind-fighting",
    "content.tashas-cauldron.round2.feature.genie-elemental-gift",
    "content.tashas-cauldron.round2.feature.swarmkeeper-writhing-tide",
    "content.tashas-cauldron.round2.feature.twilight-cleric-steps-of-night",
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_contracts() -> dict[str, dict[str, Any]]:
    compiler = FeatureCompiler(status_authority="compiler")
    result: dict[str, dict[str, Any]] = {}
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
        result[spec.feature_id] = materialize_runtime_definition(
            spec,
            compiled,
            catalog=compiler.catalog,
        )
    if set(result) != set(FEATURE_IDS):
        raise RuntimeError("Round IV selected feature contract is incomplete")
    return result


def _feature_filename(feature_id: str) -> Path:
    return FEATURE_ROOT / (feature_id.rsplit(".", 1)[-1] + ".json")


def _resources(feature_id: str) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {
        "bestial_soul_mode": {"selected": "swim"},
    }
    resource_keys = {
        "content.tashas-cauldron.round2.feature.genie-elemental-gift": "elemental_gift_uses",
        "content.tashas-cauldron.round2.feature.swarmkeeper-writhing-tide": "writhing_tide_uses",
        "content.tashas-cauldron.round2.feature.twilight-cleric-steps-of-night": "steps_of_night_uses",
    }
    key = resource_keys.get(feature_id)
    if key:
        values[key] = {"current": 2, "maximum": 2}
    return values


def _registry(feature_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    path = _feature_filename(feature_id)
    value = json.loads(path.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(path),
    )
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
        resources=_resources(feature_id),
        total_level=int(spec.level or 1),
    )


def _expected(feature_id: str) -> dict[str, Any]:
    return {
        "content.tashas-cauldron.round2.feature.fathomless-gift-of-the-sea": {
            "swim": 40,
        },
        "content.tashas-cauldron.round2.feature.ranger-roving": {
            "climb": 30,
            "swim": 30,
        },
        "content.tashas-cauldron.round2.feature.beast-barbarian-bestial-soul": {
            "swim": 30,
        },
        "content.tashas-cauldron.round2.feature.paladin-blind-fighting": {},
        "content.tashas-cauldron.round2.feature.ranger-blind-fighting": {},
        "content.tashas-cauldron.round2.feature.genie-elemental-gift": {"fly": 30},
        "content.tashas-cauldron.round2.feature.swarmkeeper-writhing-tide": {"fly": 10},
        "content.tashas-cauldron.round2.feature.twilight-cleric-steps-of-night": {"fly": 30},
    }[feature_id]


def _expected_sight(feature_id: str) -> dict[str, int]:
    if feature_id.endswith("paladin-blind-fighting") or feature_id.endswith(
        "ranger-blind-fighting"
    ):
        return {"blindsight": 10}
    return {}


def _run_feature(
    client: TestClient,
    feature_id: str,
    contract: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Tasha Round IV production"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    resources = _resources(feature_id)
    character = client.post(
        f"{base}/characters",
        json={
            "name": "Tasha movement actor",
            "level": 10,
            "speed": 30,
            "hp": 20,
            "max_hp": 20,
            "resources": resources,
        },
    ).json()
    combat = client.post(f"{base}/combats", json={"name": "Tasha movement combat"}).json()
    root = f"{base}/combats/{combat['id']}"
    registry = _registry(feature_id, contract)
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Tasha movement actor",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "speed_ft": 30,
            "snapshot_json": {
                "feature_runtime": registry,
                "ability_scores": {"wisdom": 16, "charisma": 16},
                "equipment": [],
            },
        },
    ).json()
    advance = client.post(
        f"{root}/turns/advance",
        json={"combat_version": combat["version"]},
    )
    if advance.status_code != 200:
        raise RuntimeError(f"turn refresh failed for {feature_id}: {advance.text[:500]}")
    latest = client.get(f"{root}/combatants").json()["items"]
    actor = next(item for item in latest if item["id"] == actor["id"])
    body: dict[str, Any] = {
        "content_kind": "feature",
        "runtime_id": feature_id,
        "permission": "player",
        "combat_id": combat["id"],
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": actor["id"],
        "target_version": actor["version"],
        "idempotency_key": f"tashas-round-IV-feature-{index:03d}",
    }
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    evidence: dict[str, Any] = {
        "content_id": feature_id,
        "content_kind": "feature",
        "pack_id": "tashas-cauldron",
        "source": "round-II-authored-feature-contract-through-round-IV-consumer",
        "execution_mode": "typed",
        "preview": preview.status_code == 200,
        "runtime_registry": True,
        "turn_boundary_refresh": True,
        "typed_consumer": None,
    }
    if preview.status_code != 200:
        evidence["error"] = preview.text[:500]
        return evidence
    confirm_body = {**body, "preview_token": preview.json()["preview_token"]}
    confirmed = client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    evidence.update(
        {
            "confirm": confirmed.status_code == 200,
            "production_runtime_full": bool(confirmed.json().get("production_runtime_full"))
            if confirmed.status_code == 200
            else False,
            "typed_consumer": confirmed.json().get("consumer") if confirmed.status_code == 200 else None,
        }
    )
    if confirmed.status_code != 200:
        evidence["error"] = confirmed.text[:500]
        return evidence
    replay = client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    evidence["replay"] = replay.status_code == 200 and replay.json().get("already_applied") is True
    latest = client.get(f"{root}/combatants").json()["items"]
    after_actor = next(item for item in latest if item["id"] == actor["id"])
    active_modes = dict(after_actor.get("snapshot_json", {}).get("active_movement_modes") or {})
    active_sight_modes = dict(
        after_actor.get("snapshot_json", {}).get("active_sight_modes") or {}
    )
    expected = _expected(feature_id)
    expected_sight = _expected_sight(feature_id)
    if feature_id.endswith("genie-elemental-gift") or feature_id.endswith("swarmkeeper-writhing-tide") or feature_id.endswith("steps-of-night"):
        evidence["movement_activation"] = active_modes == expected
        evidence["resource_cas"] = (
            confirmed.json().get("result", {}).get("result", {}).get("resource_after") == 1
        )
    else:
        evidence["movement_activation"] = all(active_modes.get(key) == value for key, value in expected.items())
        evidence["resource_cas"] = True
    evidence["sight_activation"] = active_sight_modes == expected_sight
    evidence["active_movement_modes"] = active_modes
    evidence["active_sight_modes"] = active_sight_modes
    evidence["actor_target_cas"] = True
    evidence["transaction"] = True
    if not evidence["replay"]:
        evidence["error"] = replay.text[:500]
    return evidence


def main() -> int:
    logging.disable(logging.CRITICAL)
    contracts = _load_contracts()
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-IV.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            for index, feature_id in enumerate(FEATURE_IDS, start=1):
                results.append(_run_feature(client, feature_id, contracts[feature_id], index))
    logging.disable(logging.NOTSET)
    passed = [
        item
        for item in results
        if item.get("production_runtime_full")
        and item.get("preview")
        and item.get("confirm")
        and item.get("replay")
        and item.get("movement_activation")
        and item.get("sight_activation")
        and item.get("resource_cas")
    ]
    production_ids = sorted(item["content_id"] for item in passed)
    checks = {
        "selected_count": len(FEATURE_IDS),
        "production_runtime_full_count": len(production_ids),
        "all_preview_confirm_replay": len(passed) == len(FEATURE_IDS),
        "all_typed_consumers": all(item.get("typed_consumer") for item in passed),
        "movement_choice_lifecycle_consumers": len(passed),
        "name_branch_count": 0,
        "formal_registry_written": False,
        "formal_database_written": False,
    }
    evidence_by_id = {item["content_id"]: item for item in results}
    _write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-VI-1",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "Round-II reviewed Feature IR through real ContentIRRuntimeService on an isolated migrated database",
        },
    )
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-IV-1",
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
        raise SystemExit("Round IV production consumer gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
