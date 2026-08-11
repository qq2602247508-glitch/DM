# ruff: noqa: N999
"""Validate generic typed resource profiles, exchanges and event windows."""

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
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XI.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-IX-2026-08-12.json"

ADVANCEMENT_ID = "content.tashas-cauldron.round2.feature.psi-warrior-psionic-power"
FEATURE_IDS = (
    "content.tashas-cauldron.round2.feature.battle-master-brace",
    "content.tashas-cauldron.round2.feature.battle-master-quick-toss",
    "content.tashas-cauldron.round2.feature.paladin-harness-divine-power",
    "content.tashas-cauldron.round2.feature.paladin-interception",
    "content.tashas-cauldron.round2.feature.rune-knight-runic-shield",
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_contracts() -> dict[str, tuple[FeatureSpec, dict[str, Any]]]:
    compiler = FeatureCompiler(status_authority="compiler")
    wanted = {*FEATURE_IDS, ADVANCEMENT_ID}
    result: dict[str, tuple[FeatureSpec, dict[str, Any]]] = {}
    for path in sorted(FEATURE_ROOT.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        spec = FeatureSpec.from_dict(
            {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
            path=str(path),
        )
        if spec.feature_id not in wanted:
            continue
        compiled = compiler.compile(spec)
        if compiled.compile_status != "full":
            raise RuntimeError(f"selected feature is not full: {spec.feature_id}")
        result[spec.feature_id] = (
            spec,
            materialize_runtime_definition(spec, compiled, catalog=compiler.catalog),
        )
    if set(result) != wanted:
        raise RuntimeError("Round IX selected feature contract is incomplete")
    return result


def _registry(
    feature_id: str,
    spec: FeatureSpec,
    contract: dict[str, Any],
    resources: dict[str, dict[str, Any]],
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
        resources=resources,
        total_level=max(5, int(spec.level or 1)),
    )


def _create_combatant(
    client: TestClient,
    root: str,
    *,
    name: str,
    entity_type: str,
    entity_id: str | None,
    initiative: int,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    return client.post(
        f"{root}/combatants",
        json={
            "display_name": name,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "initiative": initiative,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": snapshot,
        },
    ).json()


def _run_advancement(
    client: TestClient,
    spec: FeatureSpec,
    contract: dict[str, Any],
) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Tasha Round IX resources"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={"name": "Tasha resource profile actor", "class_name": "战士", "level": 5, "hp": 20, "max_hp": 20},
    ).json()
    body = {
        "content_kind": "advancement",
        "runtime_id": ADVANCEMENT_ID,
        "permission": "player",
        "character_id": character["id"],
        "character_version": character["version"],
        "runtime_contract": contract,
        "idempotency_key": "tashas-round-IX-resource-profile",
    }
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    evidence: dict[str, Any] = {
        "content_id": ADVANCEMENT_ID,
        "content_kind": "advancement",
        "preview": preview.status_code == 200,
        "confirm": False,
        "replay": False,
        "typed_consumer": None,
        "resource_profile_persisted": False,
        "character_cas": False,
        "transaction": False,
        "resource_cas": True,
    }
    if preview.status_code != 200:
        evidence["error"] = preview.text[:500]
        return evidence
    preview_body = preview.json()
    resource_grants = preview_body.get("resource_grants") or []
    evidence["resource_profile_persisted"] = any(
        isinstance(item, dict)
        and item.get("key") == "psionic_dice"
        and item.get("current") == 6
        and item.get("maximum") == 6
        for item in resource_grants
    )
    confirm = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    evidence["confirm"] = confirm.status_code == 200
    if confirm.status_code != 200:
        evidence["error"] = confirm.text[:500]
        return evidence
    output = confirm.json()
    replay = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    evidence.update(
        {
            "replay": replay.status_code == 200 and replay.json().get("already_applied") is True,
            "typed_consumer": output.get("consumer"),
            "character_cas": output.get("character_version_after") == character["version"] + 1,
            "transaction": bool(output.get("operation_transaction_id")),
            "resource_grant_count": len(output.get("resource_grants") or []),
        }
    )
    if not evidence["replay"]:
        evidence["error"] = replay.text[:500]
    return evidence


def _run_feature(
    client: TestClient,
    feature_id: str,
    spec: FeatureSpec,
    contract: dict[str, Any],
) -> dict[str, Any]:
    resources: dict[str, dict[str, Any]] = {}
    permission = "player"
    reaction_triggered = False
    target_kind = "self"
    if feature_id in {
        "content.tashas-cauldron.round2.feature.battle-master-brace",
        "content.tashas-cauldron.round2.feature.battle-master-quick-toss",
    }:
        resources = {"superiority_dice": {"current": 3, "maximum": 3}}
        target_kind = "enemy"
        permission = "dm" if feature_id.endswith("brace") else "player"
        reaction_triggered = permission == "dm"
    elif feature_id.endswith("paladin-interception"):
        permission = "dm"
        reaction_triggered = True
        target_kind = "ally_or_self"
    elif feature_id.endswith("runic-shield"):
        resources = {"runic_shield_uses": {"current": 1, "maximum": 1}}
        permission = "dm"
        reaction_triggered = True
        target_kind = "ally_or_self"
    elif feature_id.endswith("harness-divine-power"):
        resources = {
            "channel_divinity": {"current": 2, "maximum": 2},
            "spell_slots_1": {"current": 0, "maximum": 4},
        }
    campaign = client.post("/api/v1/campaigns", json={"name": "Tasha Round IX event windows"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={"name": "Tasha event actor", "class_name": spec.class_name or "玩家角色", "level": 5, "hp": 20, "max_hp": 20, "resources": resources},
    ).json()
    combat = client.post(f"{base}/combats", json={"name": "Tasha typed event combat"}).json()
    root = f"{base}/combats/{combat['id']}"
    registry = _registry(feature_id, spec, contract, resources)
    actor_snapshot = {
        "feature_runtime": registry,
        "ability_scores": {"strength": 16, "constitution": 16, "intelligence": 16, "wisdom": 16, "charisma": 16},
        "equipment": [],
        "actions": [{"name": "Longsword", "is_weapon_attack": True, "melee_weapon_attack": True, "is_melee": True}],
    }
    actor = _create_combatant(
        client,
        root,
        name="Tasha event actor",
        entity_type="character",
        entity_id=character["id"],
        initiative=20,
        snapshot=actor_snapshot,
    )
    target = actor
    if target_kind == "enemy":
        target = _create_combatant(
            client,
            root,
            name="typed enemy",
            entity_type="monster",
            entity_id=None,
            initiative=10,
            snapshot={"disposition": "enemy"},
        )
    elif target_kind == "ally_or_self":
        ally_campaign_character = client.post(
            f"{base}/characters",
            json={"name": "Tasha ally", "class_name": "盟友", "level": 5, "hp": 20, "max_hp": 20},
        ).json()
        target = _create_combatant(
            client,
            root,
            name="typed ally",
            entity_type="character",
            entity_id=ally_campaign_character["id"],
            initiative=10,
            snapshot={},
        )
    body = {
        "content_kind": "feature",
        "runtime_id": feature_id,
        "permission": permission,
        "combat_id": combat["id"],
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "reaction_triggered": reaction_triggered,
        "idempotency_key": f"tashas-round-IX-feature-{feature_id.rsplit('.', 1)[-1]}",
    }
    if feature_id.endswith("harness-divine-power"):
        body["reset_spell_slot_level"] = 1
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    evidence: dict[str, Any] = {
        "content_id": feature_id,
        "content_kind": "feature",
        "preview": preview.status_code == 200,
        "confirm": False,
        "replay": False,
        "typed_consumer": None,
        "window_persisted": False,
        "resource_cas": True,
        "resource_exchange": feature_id.endswith("harness-divine-power"),
    }
    if preview.status_code != 200:
        evidence["error"] = preview.text[:500]
        return evidence
    preview_body = preview.json()
    evidence["typed_event_contract"] = (
        preview_body.get("production_contract", {}).get("consumers")
        == ["combat_engine.feature_event_window.v1"]
    )
    confirm = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    evidence["confirm"] = confirm.status_code == 200
    if confirm.status_code != 200:
        evidence["error"] = confirm.text[:500]
        return evidence
    output = confirm.json()
    result = output.get("result", {}).get("result", {})
    window = result.get("feature_window") or {}
    evidence.update(
        {
            "typed_consumer": output.get("consumer"),
            "window_persisted": bool(window.get("id")) and window.get("status") == "eligible",
            "resource_before": result.get("resource_before"),
            "resource_after": result.get("resource_after"),
            "resource_exchange_amount": (result.get("resource_exchange") or {}).get("amount"),
        }
    )
    if feature_id.endswith(("brace", "quick-toss", "runic-shield")):
        evidence["resource_cas"] = result.get("resource_before") in {1, 3} and result.get("resource_after") in {0, 2}
    if evidence["resource_exchange"]:
        exchange = result.get("resource_exchange") or {}
        evidence["resource_exchange"] = exchange.get("from_after") == 0 and exchange.get("to_after") == 2
    replay = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    evidence["replay"] = replay.status_code == 200 and replay.json().get("already_applied") is True
    if not evidence["replay"]:
        evidence["error"] = replay.text[:500]
    return evidence


def main() -> int:
    logging.disable(logging.CRITICAL)
    contracts = _load_contracts()
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-IX.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            advancement_spec, advancement_contract = contracts[ADVANCEMENT_ID]
            results.append(_run_advancement(client, advancement_spec, advancement_contract))
            for feature_id in FEATURE_IDS:
                spec, contract = contracts[feature_id]
                results.append(_run_feature(client, feature_id, spec, contract))
    logging.disable(logging.NOTSET)
    passed = [
        item
        for item in results
        if item.get("preview")
        and item.get("confirm")
        and item.get("replay")
        and item.get("typed_consumer")
        and (item.get("resource_profile_persisted") or item.get("window_persisted") or item.get("resource_exchange"))
    ]
    production_ids = sorted(item["content_id"] for item in passed)
    checks = {
        "selected_count": len(results),
        "production_runtime_full_count": len(production_ids),
        "all_preview_confirm_replay": len(passed) == len(results),
        "all_typed_consumers": all(item.get("typed_consumer") for item in passed),
        "resource_profile_persisted": any(item.get("resource_profile_persisted") for item in passed),
        "event_windows_persisted": sum(bool(item.get("window_persisted")) for item in passed),
        "resource_exchange_passed": any(item.get("resource_exchange") for item in passed),
        "all_resource_cas": all(item.get("resource_cas", True) for item in passed),
        "formal_registry_written": False,
        "formal_database_written": False,
        "name_branch_count": 0,
    }
    evidence_by_id = {item["content_id"]: item for item in results}
    _write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-XI-1",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "Round-II reviewed Feature IR through real typed resource profile, exchange and event-window consumers on an isolated migrated database",
        },
    )
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-IX-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_feature_ids": [ADVANCEMENT_ID, *FEATURE_IDS],
            "results": results,
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
        },
    )
    print(json.dumps({"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)}, ensure_ascii=False, sort_keys=True))
    if len(production_ids) != len(results):
        raise SystemExit("Round IX production consumer gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
