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


@pytest.fixture
def client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'triggered-attack.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_damage_event_opens_durable_retaliation_window_and_reject_is_idempotent(
    client: TestClient,
) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Triggered attack"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Triggered attack room"}).json()
    grid = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 6, "height": 4, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    combat = client.post(
        f"{base}/combats", json={"name": "Triggered attack combat", "scene_id": scene["id"]}
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "敌方兽人",
            "entity_type": "monster",
            "initiative": 20,
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
            "display_name": "狂战士",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 2},
                "feature_runtime": {
                    "triggers": [
                        {
                            "id": "retaliation:triggered_attack",
                            "feature_name": "报偿",
                            "kind": "triggered_attack",
                            "event": "after_taking_damage",
                            "action_cost": "reaction",
                            "reaction_trigger": "受到 5 尺内生物造成的实际伤害",
                            "target_policy": {
                                "mode": "event_actor",
                                "range_ft": 5,
                                "requires_visible_or_audible": True,
                            },
                            "attack_profile": {"mode": "melee_weapon_or_unarmed"},
                            "runtime_execution": {
                                "status": "ready",
                                "consumer": "generic_triggered_attack_window_and_player_attack",
                            },
                            "automation_status": "full",
                        }
                    ]
                },
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
    attack = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "retaliation-parent"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": defender["id"],
            "target_version": defender["version"],
            "action_cost": "none",
            "action_name": "兽人砍击",
            "amount": 4,
            "damage_type": "slashing",
            "is_attack": True,
            "is_weapon_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 20,
        },
    )
    assert attack.status_code == 200, attack.text
    actions = client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    windows = [item for item in actions if item["action_type"] == "triggered_attack_window"]
    assert len(windows) == 1
    window = windows[0]
    metadata = window["result_json"]["action_window"]
    assert metadata["trigger_event"] == "after_taking_damage"
    assert metadata["candidate_target_ids"] == [attacker["id"]]
    assert metadata["eligible_attack_profiles"][0]["action_name"] == "长剑"
    rejected = client.post(
        f"{base}/combats/{combat['id']}/triggered-attacks/{window['id']}/resolve",
        headers={"X-Request-ID": "retaliation-reject"},
        json={
            "window_id": window["id"],
            "window_version": window["version"],
            "decision": "reject",
        },
    )
    assert rejected.status_code == 200, rejected.text
    replay = client.post(
        f"{base}/combats/{combat['id']}/triggered-attacks/{window['id']}/resolve",
        headers={"X-Request-ID": "retaliation-reject"},
        json={
            "window_id": window["id"],
            "window_version": window["version"],
            "decision": "reject",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


def test_triggered_attack_accept_binds_real_reaction_and_attack_d20(client: TestClient) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Triggered accept"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Accept room"}).json()
    assert (
        client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 4, "height": 3, "cell_size_ft": 5, "mode": "combat"},
        ).status_code
        == 201
    )
    combat = client.post(
        f"{base}/combats", json={"name": "Accept combat", "scene_id": scene["id"]}
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "攻击者",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"disposition": "enemy", "grid_position": {"row": 1, "col": 1}},
        },
    ).json()
    defender = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "报偿者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": 1, "col": 2},
                "feature_runtime": {
                    "triggers": [
                        {
                            "id": "retaliation:triggered_attack",
                            "kind": "triggered_attack",
                            "event": "after_taking_damage",
                            "action_cost": "reaction",
                            "reaction_trigger": "受到 5 尺内生物造成的实际伤害",
                            "target_policy": {"mode": "event_actor", "range_ft": 5},
                            "attack_profile": {"mode": "melee_weapon_or_unarmed"},
                            "runtime_execution": {"consumer": "test"},
                            "automation_status": "full",
                        }
                    ]
                },
                "actions": [
                    {
                        "name": "短剑",
                        "is_weapon_attack": True,
                        "melee_weapon_attack": True,
                        "description": "近战武器攻击",
                    }
                ],
            },
        },
    ).json()
    parent = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "accept-parent"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": defender["id"],
            "target_version": defender["version"],
            "amount": 2,
            "damage_type": "slashing",
            "is_attack": True,
            "is_weapon_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 20,
            "idempotency_key": "accept-parent-command",
        },
    )
    assert parent.status_code == 200, parent.text
    actions = client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    window = next(item for item in actions if item["action_type"] == "triggered_attack_window")
    follow_up = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "accept-follow-up"},
        json={
            "action_type": "damage",
            "actor_combatant_id": defender["id"],
            "actor_version": parent.json()["target"]["version"],
            "target_combatant_id": attacker["id"],
            "target_version": attacker["version"],
            "action_cost": "reaction",
            "action_name": "短剑",
            "amount": 3,
            "damage_type": "piercing",
            "is_attack": True,
            "is_weapon_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 20,
            "attack_d20": 20,
            "reaction_trigger": "受到 5 尺内生物造成的实际伤害",
            "triggered_attack_window_id": window["id"],
            "triggered_attack_window_version": window["version"],
            "idempotency_key": "accept-follow-up-command",
        },
    )
    assert follow_up.status_code == 200, follow_up.text
    resolved = next(
        item
        for item in client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
        if item["id"] == window["id"]
    )
    assert resolved["result_json"]["action_window"]["status"] == "resolved"
    assert resolved["result_json"]["action_window"]["decision"] == "accept"
