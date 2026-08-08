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
    database_url = f"sqlite:///{tmp_path / 'shadowy-dodge.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _runtime() -> dict[str, Any]:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "如影随行",
            "class_name": "游侠",
            "class_level": 15,
            "source_record_id": "test-shadowy-dodge",
        }
    )
    assert runtime is not None
    return runtime


def test_shadowy_dodge_runtime_is_full() -> None:
    runtime = _runtime()
    assert runtime["automation_status"] == "full"
    action = runtime["actions"]["shadowy_dodge"]
    assert action["kind"] == "attack_resolution_intervention"
    assert action["phase"] == "before_attack_roll_resolution"
    assert action["operation"]["kind"] == "impose_disadvantage"
    assert action["follow_up"]["kind"] == "teleport_after_attack"


def _setup(
    client: TestClient, name: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    campaign = client.post("/api/v1/campaigns", json={"name": name}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Shadow room"}).json()
    assert (
        client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 12, "height": 10, "cell_size_ft": 5, "mode": "combat"},
        ).status_code
        == 201
    )
    combat = client.post(
        f"{base}/combats",
        json={"name": "Shadow combat", "scene_id": scene["id"]},
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "伏击者",
            "entity_type": "monster",
            "initiative": 18,
            "hp": 30,
            "max_hp": 30,
            "armor_class": 14,
            "snapshot_json": {
                "disposition": "enemy",
                "grid_position": {"row": 2, "col": 2},
            },
        },
    ).json()
    ranger = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "幽域追猎者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 36,
            "max_hp": 36,
            "armor_class": 16,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 2, "col": 3},
                "feature_runtime": _runtime(),
            },
        },
    ).json()
    return combat, attacker, ranger, base


def test_shadowy_dodge_imposes_disadvantage_and_opens_teleport(client: TestClient) -> None:
    combat, attacker, ranger, base = _setup(client, "Shadowy Dodge full chain")
    # Attack declared without a final roll total.
    paused = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "shadowy-parent"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": ranger["id"],
            "target_version": ranger["version"],
            "action_cost": "none",
            "amount": 10,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_range_ft": 5,
        },
    )
    assert paused.status_code == 200, paused.text
    body = paused.json()
    assert body["phase"] == "awaiting_attack_intervention"
    window = body["pending_attack_intervention"]
    metadata = window["result_json"]["action_window"]
    assert metadata["phase"] == "before_attack_roll_resolution"
    assert metadata["feature_id"] == "shadowy_dodge"
    assert body["target"]["hp"] == 36

    # Accept with two d20 naturals and totals; server picks the lower d20's total.
    resolved = client.post(
        f"{base}/combats/{combat['id']}/reactions/attack-resolution/resolve",
        headers={"X-Request-ID": "shadowy-accept"},
        json={
            "window_id": window["id"],
            "window_version": window["version"],
            "decision": "accept",
            "feature_id": "shadowy_dodge",
            "attack_rolls": [17, 4],
            "attack_roll_totals": [24, 11],
        },
    )
    assert resolved.status_code == 200, resolved.text
    result = resolved.json()
    # d20 17 total 24 would hit AC 16; d20 4 total 11 misses. Lower d20 chosen -> miss.
    assert result["target"]["hp"] == 36
    assert result["target"]["reaction_available"] is False
    resolution = result["action"]["result_json"]["attack_resolution"]
    assert resolution["imposed_disadvantage"] is True
    assert resolution["selected_d20"] == 4
    assert resolution["effective_attack_total"] == 11
    assert resolution["hit"] is False

    # Teleport window opened as the same reaction's follow-up.
    actions = client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    teleport = [
        item
        for item in actions
        if item["action_type"] == "eligible_action_window"
        and (item["result_json"]["action_window"].get("phase") == "attack_resolution_teleport")
        and (item["result_json"]["action_window"].get("status") == "pending")
    ]
    assert len(teleport) == 1
    teleport_window = teleport[0]
    teleport_meta = teleport_window["result_json"]["action_window"]
    assert teleport_meta["action_cost"] == "none"
    assert teleport_meta["reactor_combatant_id"] == ranger["id"]
    assert teleport_meta["range_ft"] == 30

    # Accept teleport to a visible unoccupied cell within 30 ft (ranger at 2,3 -> 5,3 is 15ft).
    teleported = client.post(
        f"{base}/combats/{combat['id']}/reactions/attack-resolution-teleport/{teleport_window['id']}/resolve",
        headers={"X-Request-ID": "shadowy-teleport"},
        json={
            "window_id": teleport_window["id"],
            "window_version": teleport_window["version"],
            "decision": "accept",
            "destination_row": 5,
            "destination_col": 3,
        },
    )
    assert teleported.status_code == 200, teleported.text
    assert teleported.json()["teleport_result"]["applied"] is True
    ranger_after = next(
        item
        for item in client.get(f"{base}/combats/{combat['id']}/combatants").json()["items"]
        if item["id"] == ranger["id"]
    )
    assert ranger_after["snapshot_json"]["grid_position"] == {"row": 5, "col": 3}


def test_shadowy_dodge_reject_keeps_single_d20_and_no_teleport_required(client: TestClient) -> None:
    combat, attacker, ranger, base = _setup(client, "Shadowy Dodge reject")
    paused = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "shadowy-reject-parent"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": ranger["id"],
            "target_version": ranger["version"],
            "action_cost": "none",
            "amount": 10,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_range_ft": 5,
        },
    )
    assert paused.status_code == 200, paused.text
    window = paused.json()["pending_attack_intervention"]
    rejected = client.post(
        f"{base}/combats/{combat['id']}/reactions/attack-resolution/resolve",
        headers={"X-Request-ID": "shadowy-reject"},
        json={
            "window_id": window["id"],
            "window_version": window["version"],
            "decision": "reject",
        },
    )
    assert rejected.status_code == 200, rejected.text
    # Reject should resume the attack; the attacker still must provide a roll.
    assert rejected.json()["target"]["reaction_available"] is True
    # No teleport window for a rejected reaction.
    actions = client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    assert not any(
        item["action_type"] == "eligible_action_window"
        and (item["result_json"]["action_window"].get("phase") == "attack_resolution_teleport")
        and (item["result_json"]["action_window"].get("status") == "pending")
        for item in actions
    )
