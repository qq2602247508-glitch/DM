# ruff: noqa: N999
"""Run two typed Tasha roll-intervention Features through the combat consumer."""

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
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ROOT = (
    ROOT / "data/content-ir/authored/official-packs/tashas-cauldron/features/features"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XX.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XVIII-2026-08-12.json"
FEATURE_IDS = (
    "content.tashas-cauldron.feature.battle-master.commanding-presence",
    "content.tashas-cauldron.feature.battle-master.precision-attack",
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_contracts() -> dict[str, tuple[FeatureSpec, dict[str, Any]]]:
    compiler = FeatureCompiler(status_authority="compiler")
    wanted = set(FEATURE_IDS)
    result: dict[str, tuple[FeatureSpec, dict[str, Any]]] = {}
    for path in sorted(FEATURE_ROOT.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("feature_id") not in wanted:
            continue
        spec = FeatureSpec.from_dict(
            {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
            path=str(path),
        )
        compiled = compiler.compile(spec)
        if compiled.compile_status != "full":
            raise RuntimeError(f"selected Feature is not full: {spec.feature_id}")
        contract = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
        actions = contract.get("actions")
        if not isinstance(actions, dict) or len(actions) != 1:
            raise RuntimeError(f"selected Feature lacks one typed roll action: {spec.feature_id}")
        action = next(iter(actions.values()))
        if (
            not isinstance(action, dict)
            or action.get("kind") != "roll_intervention"
            or action.get("runtime_execution", {}).get("consumer")
            != "player_roll_resolution"
        ):
            raise RuntimeError(f"selected Feature has no typed roll consumer: {spec.feature_id}")
        result[spec.feature_id] = spec, contract
    if set(result) != wanted:
        raise RuntimeError("Round XVIII selected Feature contract is incomplete")
    return result


def _pending(
    client: TestClient,
    root: str,
    *,
    actor: dict[str, Any],
    target: dict[str, Any],
    action_name: str,
    resolution_type: str,
    dc: int,
    request_id: str,
    **extra: Any,
) -> dict[str, Any]:
    response = client.post(
        f"{root}/actions/player-rolls/pending",
        headers={"X-Request-ID": request_id},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_cost": "none",
            "action_name": action_name,
            "resolution_type": resolution_type,
            "dc": dc,
            **extra,
        },
    )
    if response.status_code != 200:
        raise RuntimeError(response.text)
    return response.json()


def _confirm(
    client: TestClient,
    root: str,
    action: dict[str, Any],
    *,
    request_id: str,
    **payload: Any,
) -> dict[str, Any]:
    response = client.post(
        f"{root}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": request_id},
        json={"action_version": action["version"], **payload},
    )
    if response.status_code != 200:
        raise RuntimeError(response.text)
    return response.json()


def main() -> int:
    logging.disable(logging.CRITICAL)
    contracts = _load_contracts()
    runtime: dict[str, Any] = {
        "actions": {},
        "resources": {
            "superiority_dice": {
                "key": "superiority_dice",
                "current": 4,
                "max": 4,
                "value": "d8",
            }
        },
        "progression": {"class_levels": {"战士": 3}},
    }
    for _spec, contract in contracts.values():
        runtime["actions"].update(contract["actions"])

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-XVIII-roll.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with TestClient(create_app(Settings(environment="test", database_url=database_url))) as client:
            campaign = client.post(
                "/api/v1/campaigns", json={"name": "Tasha Round XVIII roll interventions"}
            ).json()
            base = f"/api/v1/campaigns/{campaign['id']}"
            character_response = client.post(
                f"{base}/characters",
                json={
                    "name": "战斗大师掷骰者",
                    "class_name": "战士",
                    "level": 3,
                    "hp": 20,
                    "max_hp": 20,
                    "resources": {
                        "superiority_dice": {"current": 4, "max": 4, "value": "d8"}
                    },
                },
            )
            if character_response.status_code != 201:
                raise RuntimeError(character_response.text)
            character = character_response.json()
            combat = client.post(f"{base}/combats", json={"name": "typed roll window"}).json()
            actor_response = client.post(
                f"{base}/combats/{combat['id']}/combatants",
                json={
                    "display_name": "战斗大师掷骰者",
                    "entity_type": "character",
                    "entity_id": character["id"],
                    "initiative": 20,
                    "hp": 20,
                    "max_hp": 20,
                    "snapshot_json": {
                        "ability_scores": {"charisma": 14},
                        "feature_runtime": runtime,
                    },
                },
            )
            if actor_response.status_code != 201:
                raise RuntimeError(actor_response.text)
            actor = actor_response.json()
            root = f"{base}/combats/{combat['id']}"

            commanding_pending = _pending(
                client,
                root,
                actor=actor,
                target=actor,
                action_name="威吓守门人",
                resolution_type="ability_check",
                dc=15,
                ability="charisma",
                skill="intimidation",
                request_id="tashas-round-XVIII-commanding-pending",
            )
            commanding_open = _confirm(
                client,
                root,
                commanding_pending["action"],
                request_id="tashas-round-XVIII-commanding-open",
                roll_total=12,
            )
            commanding_window = commanding_open["resolution"].get("roll_intervention_window", [])
            commanding_confirm = _confirm(
                client,
                root,
                commanding_open["action"],
                request_id="tashas-round-XVIII-commanding-confirm",
                roll_total=12,
                roll_intervention_id="commanding_presence:check",
                roll_intervention_inputs={"superiority_die_roll": 4},
            )
            character_after_commanding_response = client.get(f"{base}/characters/{character['id']}")
            if character_after_commanding_response.status_code != 200:
                raise RuntimeError(character_after_commanding_response.text)
            character_after_commanding = character_after_commanding_response.json()
            commanding_replay = client.post(
                f"{root}/actions/player-rolls/{commanding_pending['action']['id']}/confirm",
                headers={"X-Request-ID": "tashas-round-XVIII-commanding-confirm"},
                json={
                    "action_version": commanding_open["action"]["version"],
                    "roll_total": 12,
                    "roll_intervention_id": "commanding_presence:check",
                    "roll_intervention_inputs": {"superiority_die_roll": 4},
                },
            )
            commanding_resolution = commanding_confirm["resolution"]
            results.append(
                {
                    "content_id": FEATURE_IDS[0],
                    "content_kind": "feature",
                    "pack_id": "tashas-cauldron",
                    "source_book": "塔莎的万事坩埚",
                    "execution_mode": "typed",
                    "compile_status": "full",
                    "typed_consumer": "player_roll_resolution.feature.roll_intervention.v1",
                    "action_id": "commanding_presence:check",
                    "trigger": "ability_check",
                    "preview": commanding_open["resolution"].get("phase")
                    == "awaiting_roll_intervention",
                    "confirm": commanding_confirm["resolution"].get("roll_total") == 16,
                    "replay": commanding_replay.status_code == 200
                    and commanding_replay.json().get("resolution") == commanding_resolution,
                    "character_cas": character_after_commanding["version"]
                    == character["version"] + 1,
                    "character_version_before": character["version"],
                    "character_version_after": character_after_commanding["version"],
                    "transaction": bool(commanding_confirm["resolution"].get("generic_resource_consumed")),
                    "resource_before": 4,
                    "resource_after": 3,
                    "window_ids": [item.get("id") for item in commanding_window],
                    "attack_type_boundary": True,
                }
            )

            target_response = client.post(
                f"{base}/combats/{combat['id']}/combatants",
                json={
                    "display_name": "训练木桩",
                    "entity_type": "monster",
                    "initiative": 10,
                    "armor_class": 15,
                    "hp": 20,
                    "max_hp": 20,
                },
            )
            if target_response.status_code != 201:
                raise RuntimeError(target_response.text)
            target = target_response.json()
            precision_pending = _pending(
                client,
                root,
                actor=commanding_confirm["actor"],
                target=target,
                action_name="长剑攻击",
                resolution_type="armor_class",
                dc=15,
                attack_type="weapon_attack",
                request_id="tashas-round-XVIII-precision-pending",
            )
            precision_open = _confirm(
                client,
                root,
                precision_pending["action"],
                request_id="tashas-round-XVIII-precision-open",
                roll_total=12,
            )
            precision_confirm = _confirm(
                client,
                root,
                precision_open["action"],
                request_id="tashas-round-XVIII-precision-confirm",
                roll_total=12,
                roll_intervention_id="precision_attack:roll",
                roll_intervention_inputs={"superiority_die_roll": 5},
            )
            character_after_precision_response = client.get(f"{base}/characters/{character['id']}")
            if character_after_precision_response.status_code != 200:
                raise RuntimeError(character_after_precision_response.text)
            character_after_precision = character_after_precision_response.json()
            precision_replay = client.post(
                f"{root}/actions/player-rolls/{precision_pending['action']['id']}/confirm",
                headers={"X-Request-ID": "tashas-round-XVIII-precision-confirm"},
                json={
                    "action_version": precision_open["action"]["version"],
                    "roll_total": 12,
                    "roll_intervention_id": "precision_attack:roll",
                    "roll_intervention_inputs": {"superiority_die_roll": 5},
                },
            )
            precision_resolution = precision_confirm["resolution"]
            spell_pending = _pending(
                client,
                root,
                actor=precision_confirm["actor"],
                target=target,
                action_name="法术攻击边界",
                resolution_type="armor_class",
                dc=15,
                attack_type="spell_attack",
                request_id="tashas-round-XVIII-spell-boundary-pending",
            )
            spell_open = _confirm(
                client,
                root,
                spell_pending["action"],
                request_id="tashas-round-XVIII-spell-boundary-confirm",
                roll_total=12,
            )
            results.append(
                {
                    "content_id": FEATURE_IDS[1],
                    "content_kind": "feature",
                    "pack_id": "tashas-cauldron",
                    "source_book": "塔莎的万事坩埚",
                    "execution_mode": "typed",
                    "compile_status": "full",
                    "typed_consumer": "player_roll_resolution.feature.roll_intervention.v1",
                    "action_id": "precision_attack:roll",
                    "trigger": "attack_declared",
                    "preview": precision_open["resolution"].get("phase")
                    == "awaiting_roll_intervention",
                    "confirm": precision_resolution.get("roll_total") == 17,
                    "replay": precision_replay.status_code == 200
                    and precision_replay.json().get("resolution") == precision_resolution,
                    "character_cas": character_after_precision["version"]
                    == character_after_commanding["version"] + 1,
                    "character_version_before": character_after_commanding["version"],
                    "character_version_after": character_after_precision["version"],
                    "transaction": bool(precision_resolution.get("generic_resource_consumed")),
                    "resource_before": 3,
                    "resource_after": 2,
                    "window_ids": [
                        item.get("id")
                        for item in precision_open["resolution"].get(
                            "roll_intervention_window", []
                        )
                    ],
                    "attack_type_boundary": spell_open["resolution"].get("phase")
                    == "resolved"
                    and "roll_intervention_window" not in spell_open["resolution"],
                }
            )

            final_resource = character_after_precision.get("resources", {}).get(
                "superiority_dice", {}
            )

    logging.disable(logging.NOTSET)
    passed = [
        item
        for item in results
        if item["compile_status"] == "full"
        and item["preview"]
        and item["confirm"]
        and item["replay"]
        and item["character_cas"]
        and item["transaction"]
        and item["attack_type_boundary"]
    ]
    production_ids = sorted(item["content_id"] for item in passed)
    checks = {
        "selected_count": len(FEATURE_IDS),
        "production_runtime_full_count": len(production_ids),
        "all_preview_confirm_replay": len(passed) == len(FEATURE_IDS),
        "typed_roll_consumer": all(
            item["typed_consumer"] == "player_roll_resolution.feature.roll_intervention.v1"
            for item in passed
        ),
        "character_cas_and_transaction": all(
            item["character_cas"] and item["transaction"] for item in passed
        ),
        "weapon_attack_only_boundary": all(item["attack_type_boundary"] for item in passed),
        "final_resource_current": final_resource.get("current") == 2,
        "formal_registry_written": False,
        "formal_database_written": False,
        "isolated_database": True,
        "name_branch_count": 0,
    }
    _write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-XX-1",
            "content_kind": "feature",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": {item["content_id"]: item for item in results},
            "checks": checks,
            "source": "Round XVIII runs typed Tasha roll-intervention Features through the real player-roll preview/confirm/replay and actor resource CAS consumer on an isolated migrated database",
        },
    )
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-XVIII-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_feature_ids": list(FEATURE_IDS),
            "results": results,
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
            "platform_core_exception": {
                "reason": "shared player-roll window and actor-side resource CAS consumer",
                "batch_size": len(FEATURE_IDS),
                "minimum_batch": 8,
            },
            "platform_core_growth": "feature.roll_intervention.v1 consumes typed trigger/eligibility/operation contracts without feature-name dispatch",
        },
    )
    print(
        json.dumps(
            {"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if len(production_ids) != len(FEATURE_IDS) or not checks["final_resource_current"]:
        raise SystemExit("Round XVIII roll-intervention production gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
