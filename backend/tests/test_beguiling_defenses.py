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
    database_url = f"sqlite:///{tmp_path / 'beguiling-defenses.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _runtime() -> dict[str, Any]:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "斗转星移",
            "class_name": "魔契师",
            "class_level": 10,
            "source_record_id": "test-beguiling-defenses",
        }
    )
    assert runtime is not None
    # Production advancement binds $feature_resource to the real pool key.
    resources = dict(runtime.get("resources") or {})
    feature_resource = dict(resources.pop("$feature_resource", {}) or {})
    feature_resource["key"] = "beguiling_defenses"
    resources["beguiling_defenses"] = feature_resource
    actions = dict(runtime.get("actions") or {})
    action = dict(actions.get("beguiling_defenses") or {})
    action["resource"] = {"key": "beguiling_defenses", "cost": 1}
    actions["beguiling_defenses"] = action
    runtime["resources"] = resources
    runtime["actions"] = actions
    return runtime


def test_beguiling_defenses_runtime_is_full() -> None:
    runtime = _runtime()
    assert runtime["automation_status"] == "full"
    assert runtime["combat_start"]["defenses"][0]["condition"] == "charmed"
    action = runtime["actions"]["beguiling_defenses"]
    assert action["kind"] == "feature_action"
    assert action["reflection"]["save_ability"] == "wisdom"


def test_beguiling_defenses_halves_damage_and_reflects_psychic(client: TestClient) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Beguiling Defenses"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Fey room"}).json()
    assert (
        client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 10, "height": 8, "cell_size_ft": 5, "mode": "combat"},
        ).status_code
        == 201
    )
    combat = client.post(
        f"{base}/combats",
        json={"name": "Beguiling combat", "scene_id": scene["id"]},
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "敌方法师",
            "entity_type": "monster",
            "initiative": 16,
            "hp": 30,
            "max_hp": 30,
            "armor_class": 12,
            "snapshot_json": {
                "disposition": "enemy",
                "grid_position": {"row": 2, "col": 2},
                "ability_scores": {"wisdom": 10},
            },
        },
    ).json()
    warlock = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "至高妖精魔契师",
            "entity_type": "character",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
            "armor_class": 15,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 2, "col": 3},
                "ability_scores": {"charisma": 20},
                "resources": {
                    "beguiling_defenses": {
                        "label": "斗转星移",
                        "current": 1,
                        "max": 1,
                        "maximum": 1,
                    }
                },
                "feature_runtime": {
                    **_runtime(),
                    "resources": {
                        "beguiling_defenses": {"current": 1, "max": 1},
                    },
                    "progression": {"proficiency_bonus": 4},
                },
            },
        },
    ).json()
    paused = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "beguiling-parent"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": warlock["id"],
            "target_version": warlock["version"],
            "action_cost": "none",
            "amount": 12,
            "damage_type": "fire",
            "is_attack": True,
            "attack_range_ft": 30,
            "attack_roll_total": 18,
        },
    )
    assert paused.status_code == 200, paused.text
    body = paused.json()
    assert body["phase"] == "awaiting_reaction"
    window = body["pending_reaction"]
    metadata = window["result_json"]["action_window"]
    assert metadata["feature_id"] == "beguiling_defenses"
    assert metadata["reflection"]["kind"] == "beguiling_reflection"

    resolved = client.post(
        f"{base}/combats/{combat['id']}/reactions/pre-damage/resolve",
        headers={"X-Request-ID": "beguiling-accept"},
        json={
            "reaction_window_id": window["id"],
            "reaction_window_version": window["version"],
            "decision": "accept",
            "feature_id": "beguiling_defenses",
        },
    )
    assert resolved.status_code == 200, resolved.text
    result = resolved.json()
    # 12 fire halved floor -> 6 damage; warlock HP 30 -> 24.
    assert result["target"]["hp"] == 24
    assert result["target"]["reaction_available"] is False

    actions = client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    reflection = [
        item
        for item in actions
        if item["action_type"] == "eligible_action_window"
        and (item["result_json"]["action_window"].get("phase") == "beguiling_reflection")
        and (item["result_json"]["action_window"].get("status") == "pending")
    ]
    assert len(reflection) == 1
    reflection_window = reflection[0]
    reflection_meta = reflection_window["result_json"]["action_window"]
    assert reflection_meta["reactor_combatant_id"] == attacker["id"]
    assert reflection_meta["save_ability"] == "wisdom"
    assert reflection_meta["actual_damage_taken"] == 6

    # Attacker fails Wisdom save -> takes 6 psychic damage.
    failed_save = client.post(
        f"{base}/combats/{combat['id']}/reactions/beguiling-reflection/{reflection_window['id']}/resolve",
        headers={"X-Request-ID": "beguiling-reflection-fail"},
        json={
            "window_id": reflection_window["id"],
            "window_version": reflection_window["version"],
            "decision": "accept",
            "save_total": 3,
        },
    )
    assert failed_save.status_code == 200, failed_save.text
    reflection_result = failed_save.json()["reflection_result"]
    assert reflection_result["save_success"] is False
    assert reflection_result["reflected_damage"] == 6
    attacker_after = next(
        item
        for item in client.get(f"{base}/combats/{combat['id']}/combatants").json()["items"]
        if item["id"] == attacker["id"]
    )
    assert attacker_after["hp"] == 24


def test_beguiling_defenses_successful_save_avoids_reflection(client: TestClient) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Beguiling Save"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Fey room 2"}).json()
    assert (
        client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 10, "height": 8, "cell_size_ft": 5, "mode": "combat"},
        ).status_code
        == 201
    )
    combat = client.post(
        f"{base}/combats",
        json={"name": "Beguiling save combat", "scene_id": scene["id"]},
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "敌方法师",
            "entity_type": "monster",
            "initiative": 16,
            "hp": 30,
            "max_hp": 30,
            "armor_class": 12,
            "snapshot_json": {
                "disposition": "enemy",
                "grid_position": {"row": 2, "col": 2},
                "ability_scores": {"wisdom": 14},
            },
        },
    ).json()
    warlock = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "魔契师",
            "entity_type": "character",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
            "armor_class": 15,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 2, "col": 3},
                "ability_scores": {"charisma": 20},
                "resources": {
                    "beguiling_defenses": {
                        "label": "斗转星移",
                        "current": 1,
                        "max": 1,
                        "maximum": 1,
                    }
                },
                "feature_runtime": {
                    **_runtime(),
                    "resources": {
                        "beguiling_defenses": {"current": 1, "max": 1},
                    },
                    "progression": {"proficiency_bonus": 4},
                },
            },
        },
    ).json()
    paused = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "beguiling-save-parent"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": warlock["id"],
            "target_version": warlock["version"],
            "action_cost": "none",
            "amount": 10,
            "damage_type": "fire",
            "is_attack": True,
            "attack_range_ft": 30,
            "attack_roll_total": 18,
        },
    )
    assert paused.status_code == 200, paused.text
    window = paused.json()["pending_reaction"]
    resolved = client.post(
        f"{base}/combats/{combat['id']}/reactions/pre-damage/resolve",
        headers={"X-Request-ID": "beguiling-save-accept"},
        json={
            "reaction_window_id": window["id"],
            "reaction_window_version": window["version"],
            "decision": "accept",
            "feature_id": "beguiling_defenses",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["target"]["hp"] == 25
    actions = client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    reflection = next(
        item
        for item in actions
        if item["action_type"] == "eligible_action_window"
        and (item["result_json"]["action_window"].get("phase") == "beguiling_reflection")
        and (item["result_json"]["action_window"].get("status") == "pending")
    )
    success_save = client.post(
        f"{base}/combats/{combat['id']}/reactions/beguiling-reflection/{reflection['id']}/resolve",
        headers={"X-Request-ID": "beguiling-save-success"},
        json={
            "window_id": reflection["id"],
            "window_version": reflection["version"],
            "decision": "accept",
            "save_total": 22,
        },
    )
    assert success_save.status_code == 200, success_save.text
    reflection_result = success_save.json()["reflection_result"]
    assert reflection_result["save_success"] is True
    assert reflection_result["reflected_damage"] == 0
    attacker_after = next(
        item
        for item in client.get(f"{base}/combats/{combat['id']}/combatants").json()["items"]
        if item["id"] == attacker["id"]
    )
    assert attacker_after["hp"] == 30
