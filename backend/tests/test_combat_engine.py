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
def combat_client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'combat.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as client:
        yield client


def _campaign(client: TestClient, name: str = "Combat") -> dict[str, Any]:
    response = client.post("/api/v1/campaigns", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _combatant(
    client: TestClient,
    campaign_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    combat_response = client.post(
        f"/api/v1/campaigns/{campaign_id}/combats",
        json={"name": "Rule Test"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    fighter_response = client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Fire Guard",
            "hp": 20,
            "max_hp": 20,
            "temporary_hp": 3,
            "damage_resistances": ["fire"],
        },
    )
    assert fighter_response.status_code == 201, fighter_response.json()
    return combat, fighter_response.json()


def _fighter_path(campaign_id: str, combat_id: str, fighter_id: str) -> str:
    return (
        f"/api/v1/campaigns/{campaign_id}/combats/{combat_id}/combatants/{fighter_id}"
    )


def test_damage_preview_is_read_only(combat_client: TestClient) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    preview_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/preview"
    )

    preview = combat_client.post(
        preview_path,
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 9,
            "damage_type": "fire",
        },
    )

    assert preview.status_code == 200
    assert preview.json()["result"]["adjusted_damage"] == 4
    assert preview.json()["after"]["temporary_hp"] == 0
    assert preview.json()["after"]["hp"] == 19
    unchanged = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], fighter["id"])
    ).json()
    assert unchanged["temporary_hp"] == 3
    assert unchanged["hp"] == 20
    assert unchanged["version"] == 1


def test_confirm_damage_is_atomic_logged_and_idempotent(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    confirm_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm"
    )
    payload = {
        "action_type": "damage",
        "target_combatant_id": fighter["id"],
        "target_version": fighter["version"],
        "amount": 9,
        "damage_type": "fire",
    }

    confirmed = combat_client.post(
        confirm_path,
        json=payload,
        headers={"X-Request-ID": "damage-once"},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["action"]["action_type"] == "damage"
    assert body["action"]["round_number"] == 1
    assert body["target"]["temporary_hp"] == 0
    assert body["target"]["hp"] == 19
    assert body["target"]["version"] == 2

    repeated = combat_client.post(
        confirm_path,
        json=payload,
        headers={"X-Request-ID": "damage-once"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["action"]["id"] == body["action"]["id"]
    assert repeated.json()["target"]["hp"] == 19
    actions = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions"
    )
    assert actions.status_code == 200
    assert len(actions.json()["items"]) == 1


def test_healing_respects_max_hp_reduction(combat_client: TestClient) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    patch = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], fighter["id"]),
        headers={"If-Match": '"1"'},
        json={
            "hp": 10,
            "max_hp_reduction": 5,
        },
    )
    assert patch.status_code == 200
    healed = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "heal-once"},
        json={
            "action_type": "heal",
            "target_combatant_id": fighter["id"],
            "target_version": patch.json()["version"],
            "amount": 20,
        },
    )

    assert healed.status_code == 200
    assert healed.json()["target"]["hp"] == 15
    assert healed.json()["action"]["result_json"]["hp_gained"] == 5
    assert healed.json()["action"]["result_json"]["unapplied_healing"] == 15


def test_zero_hp_creates_death_track_and_natural_twenty_recovers(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    dropped = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "drop-to-zero"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 100,
            "damage_type": "force",
        },
    )
    assert dropped.status_code == 200
    assert dropped.json()["target"]["hp"] == 0

    death_track_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        f"/combatants/{fighter['id']}/death-save"
    )
    track = combat_client.get(death_track_path)
    assert track.status_code == 200
    assert track.json()["successes"] == 0
    assert track.json()["failures"] == 0

    recovered = combat_client.post(
        f"{death_track_path}/confirm",
        headers={"X-Request-ID": "natural-twenty"},
        json={
            "target_version": dropped.json()["target"]["version"],
            "roll": 20,
        },
    )
    assert recovered.status_code == 200
    assert recovered.json()["target"]["hp"] == 1
    assert recovered.json()["death_save"]["successes"] == 0
    assert recovered.json()["death_save"]["failures"] == 0
    assert recovered.json()["action"]["result_json"]["hp_restored"] == 1


def test_third_death_failure_stays_pending_until_dm_confirms(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    fighter_path = _fighter_path(campaign["id"], combat["id"], fighter["id"])
    dropped = combat_client.patch(
        fighter_path,
        headers={"If-Match": '"1"'},
        json={"hp": 0},
    )
    assert dropped.status_code == 200
    target = dropped.json()
    death_track_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        f"/combatants/{fighter['id']}/death-save"
    )
    for index, roll in enumerate((2, 3, 4), start=1):
        saved = combat_client.post(
            f"{death_track_path}/confirm",
            headers={"X-Request-ID": f"failed-save-{index}"},
            json={
                "target_version": target["version"],
                "roll": roll,
            },
        )
        assert saved.status_code == 200
        target = saved.json()["target"]

    assert saved.json()["death_save"]["pending_death_confirmation"] is True
    assert saved.json()["death_save"]["dead"] is False
    confirmed = combat_client.post(
        f"{death_track_path}/confirm-death",
        headers={"X-Request-ID": "confirm-death"},
        json={
            "target_version": target["version"],
            "reason": "三次死亡豁免失败，DM确认",
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["death_save"]["dead"] is True


def test_advance_turn_restores_next_combatant_action_economy(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    second = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Scout",
            "initiative": -1,
            "hp": 8,
            "max_hp": 8,
            "speed_ft": 35,
            "movement_remaining_ft": 0,
            "action_available": False,
            "bonus_action_available": False,
            "reaction_available": False,
        },
    )
    assert second.status_code == 201

    advanced = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "next-turn"},
        json={"combat_version": combat["version"]},
    )

    assert advanced.status_code == 200
    assert advanced.json()["combat"]["current_turn_index"] == 1
    assert advanced.json()["combat"]["round_number"] == 1
    assert advanced.json()["active_combatant"]["id"] == second.json()["id"]
    assert advanced.json()["active_combatant"]["movement_remaining_ft"] == 35
    assert advanced.json()["active_combatant"]["action_available"] is True
    assert advanced.json()["active_combatant"]["bonus_action_available"] is True
    assert advanced.json()["active_combatant"]["reaction_available"] is True

    repeated = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "next-turn"},
        json={"combat_version": combat["version"]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["combat"]["current_turn_index"] == 1
    assert repeated.json()["action"]["id"] == advanced.json()["action"]["id"]
