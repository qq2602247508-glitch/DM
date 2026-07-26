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


def test_new_concentration_previews_and_ends_previous_effect(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    effect_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/effects"
    )
    first_payload = {
        "target_combatant_id": fighter["id"],
        "target_version": fighter["version"],
        "source_combatant_id": fighter["id"],
        "name": "祝福术",
        "effect_type": "buff",
        "requires_concentration": True,
        "duration_unit": "rounds",
        "duration_value": 10,
    }
    first = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "first-concentration"},
        json=first_payload,
    )
    assert first.status_code == 200
    assert first.json()["effect"]["status"] == "active"
    fighter = first.json()["target"]
    assert fighter["concentration"]["effect_id"] == first.json()["effect"]["id"]

    second_payload = {
        **first_payload,
        "target_version": fighter["version"],
        "name": "隐形术",
    }
    preview = combat_client.post(f"{effect_path}/preview", json=second_payload)
    assert preview.status_code == 200
    assert preview.json()["effects_to_end"][0]["id"] == first.json()["effect"]["id"]
    listed_before = combat_client.get(effect_path).json()["items"]
    assert listed_before[0]["status"] == "active"

    second = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "second-concentration"},
        json=second_payload,
    )
    assert second.status_code == 200
    assert second.json()["ended_effects"][0]["status"] == "ended"
    assert second.json()["effect"]["name"] == "隐形术"
    assert second.json()["target"]["concentration"]["effect_id"] == second.json()["effect"]["id"]

    repeated = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "second-concentration"},
        json=second_payload,
    )
    assert repeated.status_code == 200
    assert repeated.json()["effect"]["id"] == second.json()["effect"]["id"]


def test_failed_concentration_check_ends_effect_from_damage_action(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    effect_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/effects"
    )
    concentrated = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "concentrate"},
        json={
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "source_combatant_id": fighter["id"],
            "name": "隐形术",
            "effect_type": "buff",
            "requires_concentration": True,
            "duration_unit": "concentration",
        },
    )
    assert concentrated.status_code == 200
    fighter = concentrated.json()["target"]
    damaged = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "concentration-damage"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 12,
            "damage_type": "force",
        },
    )
    assert damaged.status_code == 200
    assert damaged.json()["action"]["result_json"]["concentration_check_dc"] == 10

    resolved = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/concentration/confirm",
        headers={"X-Request-ID": "failed-concentration"},
        json={
            "combatant_id": fighter["id"],
            "target_version": damaged.json()["target"]["version"],
            "damage_action_id": damaged.json()["action"]["id"],
            "roll_total": 9,
        },
    )

    assert resolved.status_code == 200
    assert resolved.json()["success"] is False
    assert resolved.json()["dc"] == 10
    assert resolved.json()["target"]["concentration"] == {}
    assert resolved.json()["ended_effects"][0]["status"] == "ended"


def test_turn_advance_prompts_expired_effect_until_dm_ends_it(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    second = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={"display_name": "Second", "hp": 5, "max_hp": 5, "initiative": -1},
    )
    assert second.status_code == 201
    effect_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/effects"
    )
    created = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "short-effect"},
        json={
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "name": "短暂目盲",
            "effect_type": "condition",
            "duration_unit": "rounds",
            "duration_value": 0,
            "trigger_timing": "turn_end",
        },
    )
    assert created.status_code == 200

    advanced = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "advance-with-expiry"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200
    assert advanced.json()["expiration_prompts"][0]["id"] == created.json()["effect"]["id"]
    listed = combat_client.get(effect_path).json()["items"]
    assert listed[0]["status"] == "active"

    ended = combat_client.post(
        f"{effect_path}/{created.json()['effect']['id']}/end",
        headers={"X-Request-ID": "end-short-effect"},
        json={
            "target_version": created.json()["target"]["version"],
            "reason": "持续时间结束，DM确认",
        },
    )
    assert ended.status_code == 200
    assert ended.json()["effect"]["status"] == "ended"


def test_combat_settlement_preview_and_confirm_are_atomic_and_once_only(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "Aria", "hp": 20, "max_hp": 20},
    )
    assert character_response.status_code == 201
    character = character_response.json()
    combat_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Settlement"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    fighter_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "hp": 5,
            "max_hp": 20,
            "conditions": ["poisoned"],
        },
    )
    assert fighter_response.status_code == 201
    fighter = fighter_response.json()
    ended_combat = combat_client.patch(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}",
        headers={"If-Match": '"1"'},
        json={"status": "ended"},
    )
    assert ended_combat.status_code == 200
    settlement_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/settlement"
    )
    payload = {
        "combat_version": ended_combat.json()["version"],
        "resolution_type": "victory",
        "xp_awards": [{"character_id": character["id"], "xp": 100}],
        "writebacks": [{
            "combatant_id": fighter["id"],
            "character_id": character["id"],
            "write_hp": True,
            "write_conditions": True,
        }],
    }
    preview = combat_client.post(f"{settlement_path}/preview", json=payload)
    assert preview.status_code == 200
    assert preview.json()["character_changes"][0]["before"]["hp"] == 20
    assert preview.json()["character_changes"][0]["after"]["hp"] == 5
    unchanged = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    )
    assert unchanged.json()["hp"] == 20
    assert unchanged.json()["experience"] == 0

    confirmed = combat_client.post(
        f"{settlement_path}/confirm",
        headers={"X-Request-ID": "settlement-once"},
        json=payload,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["settlement"]["status"] == "confirmed"
    assert confirmed.json()["characters"][0]["hp"] == 5
    assert confirmed.json()["characters"][0]["experience"] == 100
    conditions = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}/conditions"
    )
    assert conditions.status_code == 200
    assert conditions.json()["items"][0]["condition_name"] == "poisoned"

    repeated = combat_client.post(
        f"{settlement_path}/confirm",
        headers={"X-Request-ID": "settlement-once"},
        json=payload,
    )
    assert repeated.status_code == 200
    assert repeated.json()["settlement"]["id"] == confirmed.json()["settlement"]["id"]
    after = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert after["experience"] == 100
