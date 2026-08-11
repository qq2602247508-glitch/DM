from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ROOT = (
    ROOT.parent
    / "data/content-ir/authored/official-packs/tashas-cauldron/features/features"
)
COMMANDING_PRESENCE = "content.tashas-cauldron.feature.battle-master.commanding-presence"
PRECISION_ATTACK = "content.tashas-cauldron.feature.battle-master.precision-attack"


def _contracts() -> dict[str, tuple[FeatureSpec, dict[str, Any]]]:
    wanted = {COMMANDING_PRESENCE, PRECISION_ATTACK}
    compiler = FeatureCompiler(status_authority="compiler")
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
        assert compiled.compile_status == "full", compiled.blockers
        contract = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
        assert len(contract["actions"]) == 1
        action = next(iter(contract["actions"].values()))
        assert action["kind"] == "roll_intervention"
        assert action["runtime_execution"]["consumer"] == "player_roll_resolution"
        result[spec.feature_id] = spec, contract
    assert set(result) == wanted
    return result


def _combined_runtime() -> tuple[dict[str, Any], dict[str, Any]]:
    contracts = _contracts()
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
    for _feature_id, (_spec, contract) in contracts.items():
        runtime["actions"].update(contract["actions"])
    return runtime, contracts


def _pending(
    client: TestClient,
    root: str,
    *,
    actor: dict[str, Any],
    target: dict[str, Any],
    action_name: str,
    resolution_type: str,
    dc: int,
    **extra: Any,
) -> dict[str, Any]:
    response = client.post(
        f"{root}/actions/player-rolls/pending",
        headers={"X-Request-ID": extra.pop("request_id")},
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
    assert response.status_code == 200, response.text
    return response.json()


def test_tashas_roll_interventions_use_typed_actor_runtime_and_resource_cas(
    campaign_client: TestClient,
) -> None:
    runtime, contracts = _combined_runtime()
    combat_client = campaign_client
    campaign = combat_client.post(
        "/api/v1/campaigns", json={"name": "Tasha Round XVIII roll interventions"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = combat_client.post(
        f"{base}/characters",
        json={
            "name": "战斗大师掷骰者",
            "class_name": "战士",
            "level": 3,
            "hp": 20,
            "max_hp": 20,
            "resources": {"superiority_dice": {"current": 4, "max": 4, "value": "d8"}},
        },
    )
    assert character.status_code == 201, character.text
    character_body = character.json()
    combat = combat_client.post(f"{base}/combats", json={"name": "typed roll window"}).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "战斗大师掷骰者",
            "entity_type": "character",
            "entity_id": character_body["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "ability_scores": {"charisma": 14},
                "feature_runtime": runtime,
            },
        },
    )
    assert actor.status_code == 201, actor.text
    actor_body = actor.json()
    root = f"{base}/combats/{combat['id']}"

    commanding = _pending(
        combat_client,
        root,
        actor=actor_body,
        target=actor_body,
        action_name="威吓守门人",
        resolution_type="ability_check",
        dc=15,
        ability="charisma",
        skill="intimidation",
        request_id="tashas-round-XVIII-commanding-pending",
    )
    commanding_action = commanding["action"]
    opened = combat_client.post(
        f"{root}/actions/player-rolls/{commanding_action['id']}/confirm",
        headers={"X-Request-ID": "tashas-round-XVIII-commanding-open"},
        json={"action_version": commanding_action["version"], "roll_total": 12},
    )
    assert opened.status_code == 200, opened.text
    opened_body = opened.json()
    assert opened_body["resolution"]["phase"] == "awaiting_roll_intervention"
    commanding_window = opened_body["resolution"]["roll_intervention_window"]
    assert len(commanding_window) == 1
    assert commanding_window[0]["id"] == "commanding_presence:check"
    assert commanding_window[0]["name"] == "战技选项：领导风范"
    assert commanding_window[0]["input_requirements"] == [
        {"key": "superiority_die_roll", "kind": "integer"}
    ]
    resolved = combat_client.post(
        f"{root}/actions/player-rolls/{commanding_action['id']}/confirm",
        headers={"X-Request-ID": "tashas-round-XVIII-commanding-confirm"},
        json={
            "action_version": opened_body["action"]["version"],
            "roll_total": 12,
            "roll_intervention_id": "commanding_presence:check",
            "roll_intervention_inputs": {"superiority_die_roll": 4},
        },
    )
    assert resolved.status_code == 200, resolved.text
    resolved_body = resolved.json()
    commanding_resolution = resolved_body["resolution"]
    assert commanding_resolution["roll_total"] == 16
    assert commanding_resolution["success"] is True
    assert commanding_resolution["generic_resource_consumed"] == {
        "key": "superiority_dice",
        "cost": 1,
        "before": 4,
        "after": 3,
    }
    replay = combat_client.post(
        f"{root}/actions/player-rolls/{commanding_action['id']}/confirm",
        headers={"X-Request-ID": "tashas-round-XVIII-commanding-confirm"},
        json={
            "action_version": opened_body["action"]["version"],
            "roll_total": 12,
            "roll_intervention_id": "commanding_presence:check",
            "roll_intervention_inputs": {"superiority_die_roll": 4},
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["resolution"] == commanding_resolution
    character_after_commanding = combat_client.get(
        f"{base}/characters/{character_body['id']}"
    )
    assert character_after_commanding.status_code == 200, character_after_commanding.text
    assert character_after_commanding.json()["version"] == character_body["version"] + 1

    actor_after = resolved_body["actor"]
    target_response = combat_client.post(
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
    assert target_response.status_code == 201, target_response.text
    target_body = target_response.json()
    precision = _pending(
        combat_client,
        root,
        actor=actor_after,
        target=target_body,
        action_name="长剑攻击",
        resolution_type="armor_class",
        dc=15,
        attack_type="weapon_attack",
        request_id="tashas-round-XVIII-precision-pending",
    )
    precision_action = precision["action"]
    precision_opened = combat_client.post(
        f"{root}/actions/player-rolls/{precision_action['id']}/confirm",
        headers={"X-Request-ID": "tashas-round-XVIII-precision-open"},
        json={"action_version": precision_action["version"], "roll_total": 12},
    )
    assert precision_opened.status_code == 200, precision_opened.text
    precision_opened_body = precision_opened.json()
    assert precision_opened_body["resolution"]["phase"] == "awaiting_roll_intervention"
    assert precision_opened_body["resolution"]["roll_intervention_window"][0]["id"] == (
        "precision_attack:roll"
    )
    precision_confirm = combat_client.post(
        f"{root}/actions/player-rolls/{precision_action['id']}/confirm",
        headers={"X-Request-ID": "tashas-round-XVIII-precision-confirm"},
        json={
            "action_version": precision_opened_body["action"]["version"],
            "roll_total": 12,
            "roll_intervention_id": "precision_attack:roll",
            "roll_intervention_inputs": {"superiority_die_roll": 5},
        },
    )
    assert precision_confirm.status_code == 200, precision_confirm.text
    precision_body = precision_confirm.json()
    assert precision_body["resolution"]["roll_total"] == 17
    assert precision_body["resolution"]["success"] is True
    assert precision_body["resolution"]["generic_resource_consumed"] == {
        "key": "superiority_dice",
        "cost": 1,
        "before": 3,
        "after": 2,
    }
    character_after_precision = combat_client.get(
        f"{base}/characters/{character_body['id']}"
    )
    assert character_after_precision.status_code == 200, character_after_precision.text
    assert character_after_precision.json()["version"] == (
        character_after_commanding.json()["version"] + 1
    )

    actor_for_spell = precision_body["actor"]
    spell_attack = _pending(
        combat_client,
        root,
        actor=actor_for_spell,
        target=target_body,
        action_name="法术攻击边界",
        resolution_type="armor_class",
        dc=15,
        attack_type="spell_attack",
        request_id="tashas-round-XVIII-spell-boundary-pending",
    )
    spell_action = spell_attack["action"]
    spell_opened = combat_client.post(
        f"{root}/actions/player-rolls/{spell_action['id']}/confirm",
        headers={"X-Request-ID": "tashas-round-XVIII-spell-boundary-confirm"},
        json={"action_version": spell_action["version"], "roll_total": 12},
    )
    assert spell_opened.status_code == 200, spell_opened.text
    assert spell_opened.json()["resolution"]["phase"] == "resolved"
    assert "roll_intervention_window" not in spell_opened.json()["resolution"]

    persisted = combat_client.get(f"{base}/characters/{character_body['id']}")
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["resources"]["superiority_dice"]["current"] == 2
    assert set(contracts) == {COMMANDING_PRESENCE, PRECISION_ATTACK}
