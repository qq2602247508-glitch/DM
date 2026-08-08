from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.advancement_choices import subclass_feature_runtime_definition


@pytest.fixture
def client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'glorious-defense.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _runtime() -> dict[str, Any]:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "辉煌防御",
            "class_name": "圣武士",
            "class_level": 15,
            "source_record_id": "test-glorious-defense",
        }
    )
    assert runtime is not None
    # Production advancement binds $feature_resource to the real pool key.
    # Tests inject the already-bound registry the combat engine sees in play.
    resources = dict(runtime.get("resources") or {})
    feature_resource = dict(resources.pop("$feature_resource", {}) or {})
    feature_resource["key"] = "glorious_defense"
    resources["glorious_defense"] = feature_resource
    actions = dict(runtime.get("actions") or {})
    action = dict(actions.get("glorious_defense") or {})
    action["resource"] = {"key": "glorious_defense", "cost": 1}
    eligibility = dict(action.get("eligibility") or {})
    eligibility["resource"] = {"key": "glorious_defense", "minimum": 1}
    action["eligibility"] = eligibility
    actions["glorious_defense"] = action
    runtime["resources"] = resources
    runtime["actions"] = actions
    return runtime


def test_glorious_defense_runtime_is_typed_and_full() -> None:
    raw = subclass_feature_runtime_definition(
        {
            "name": "辉煌防御",
            "class_name": "圣武士",
            "class_level": 15,
            "source_record_id": "test-glorious-defense",
        }
    )
    assert raw is not None
    action = raw["actions"]["glorious_defense"]
    assert action["kind"] == "attack_resolution_intervention"
    assert action["operation"]["kind"] == "add_to_target_ac"
    assert action["automation_status"] == "full"
    assert raw["automation_status"] == "full"
    assert raw["resources"]["$feature_resource"]["max_formula"] == "max(1, charisma_modifier)"
    runtime = _runtime()
    assert runtime["resources"]["glorious_defense"]["key"] == "glorious_defense"


def test_glorious_defense_turns_hit_into_miss_and_opens_same_reaction_riposte(
    client: TestClient,
) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Glorious Defense"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Glory room"}).json()
    grid = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 6, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    combat = client.post(
        f"{base}/combats",
        json={"name": "Glorious Defense combat", "scene_id": scene["id"]},
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "兽人",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "disposition": "enemy",
                "grid_position": {"row": 2, "col": 2},
            },
        },
    ).json()
    defender = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "荣耀圣武士",
            "entity_type": "character",
            "initiative": 12,
            "hp": 40,
            "max_hp": 40,
            "armor_class": 18,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 2, "col": 3},
                "ability_scores": {"charisma": 16},
                "resources": {
                    "glorious_defense": {
                        "label": "辉煌防御",
                        "current": 2,
                        "max": 2,
                        "maximum": 2,
                    }
                },
                "feature_runtime": _runtime(),
                "actions": [
                    {
                        "name": "长剑",
                        "is_weapon_attack": True,
                        "melee_weapon_attack": True,
                        "description": "近战武器攻击",
                    }
                ],
            },
        },
    ).json()

    paused = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "glorious-defense-parent"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": defender["id"],
            "target_version": defender["version"],
            "action_cost": "none",
            "action_name": "兽人砍击",
            "amount": 11,
            "damage_type": "slashing",
            "is_attack": True,
            "is_weapon_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 19,
        },
    )
    assert paused.status_code == 200, paused.text
    body = paused.json()
    assert body["phase"] == "awaiting_attack_intervention"
    window = body["pending_attack_intervention"]
    metadata = window["result_json"]["action_window"]
    assert metadata["phase"] == "attack_resolution"
    assert metadata["feature_id"] == "glorious_defense"
    assert body["target"]["hp"] == 40

    resolved = client.post(
        f"{base}/combats/{combat['id']}/reactions/attack-resolution/resolve",
        headers={"X-Request-ID": "glorious-defense-accept"},
        json={
            "window_id": window["id"],
            "window_version": window["version"],
            "decision": "accept",
            "feature_id": "glorious_defense",
        },
    )
    assert resolved.status_code == 200, resolved.text
    result = resolved.json()
    assert result["target"]["hp"] == 40
    assert result["target"]["reaction_available"] is False
    assert result["action"]["result_json"]["attack_resolution"]["hit"] is False
    assert result["action"]["result_json"]["attack_resolution"]["effective_armor_class"] == 21

    actions = client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    riposte = [
        item
        for item in actions
        if item["action_type"] == "triggered_attack_window"
        and (item["result_json"]["action_window"].get("feature_id") == "glorious_defense")
    ]
    assert len(riposte) == 1
    riposte_meta = riposte[0]["result_json"]["action_window"]
    assert riposte_meta["action_cost"] == "none"
    assert riposte_meta["resource_cost"] == 0
    assert riposte_meta["parent_action_part"] is True
    assert attacker["id"] in riposte_meta["candidate_target_ids"]

    replay = client.post(
        f"{base}/combats/{combat['id']}/reactions/attack-resolution/resolve",
        headers={"X-Request-ID": "glorious-defense-accept"},
        json={
            "window_id": window["id"],
            "window_version": window["version"],
            "decision": "accept",
            "feature_id": "glorious_defense",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["action"]["id"] == result["action"]["id"]
    assert replay.json()["target"]["hp"] == 40


def test_glorious_defense_still_hit_applies_damage_without_riposte(client: TestClient) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Glorious still hit"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Glory room 2"}).json()
    assert (
        client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 8, "height": 6, "cell_size_ft": 5, "mode": "combat"},
        ).status_code
        == 201
    )
    combat = client.post(
        f"{base}/combats",
        json={"name": "Still hit combat", "scene_id": scene["id"]},
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "重击者",
            "entity_type": "monster",
            "initiative": 18,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "enemy",
                "grid_position": {"row": 1, "col": 1},
            },
        },
    ).json()
    defender = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "圣武士",
            "entity_type": "character",
            "initiative": 8,
            "hp": 30,
            "max_hp": 30,
            "armor_class": 16,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 2},
                "ability_scores": {"charisma": 14},
                "resources": {
                    "glorious_defense": {
                        "label": "辉煌防御",
                        "current": 1,
                        "max": 1,
                        "maximum": 1,
                    }
                },
                "feature_runtime": _runtime(),
                "actions": [
                    {
                        "name": "长剑",
                        "is_weapon_attack": True,
                        "melee_weapon_attack": True,
                        "description": "近战武器攻击",
                    }
                ],
            },
        },
    ).json()
    paused = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "glorious-still-hit"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": defender["id"],
            "target_version": defender["version"],
            "action_cost": "none",
            "amount": 8,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 22,
        },
    )
    assert paused.status_code == 200, paused.text
    window = paused.json()["pending_attack_intervention"]
    resolved = client.post(
        f"{base}/combats/{combat['id']}/reactions/attack-resolution/resolve",
        headers={"X-Request-ID": "glorious-still-hit-accept"},
        json={
            "window_id": window["id"],
            "window_version": window["version"],
            "decision": "accept",
            "feature_id": "glorious_defense",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["target"]["hp"] == 22
    assert resolved.json()["action"]["result_json"]["attack_resolution"]["hit"] is True
    actions = client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    assert not any(item["action_type"] == "triggered_attack_window" for item in actions)
