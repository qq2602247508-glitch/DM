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
def rest_client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'rests.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as client:
        yield client


def _campaign(client: TestClient, *, current_time: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "休息测试"}
    if current_time is not None:
        payload["current_time"] = current_time
    response = client.post("/api/v1/campaigns", json=payload)
    assert response.status_code == 201
    return response.json()


def _character(client: TestClient, campaign_id: str, name: str = "阿莱") -> dict[str, Any]:
    response = client.post(
        f"/api/v1/campaigns/{campaign_id}/characters",
        json={
            "name": name,
            "class_name": "战士",
            "level": 2,
            "hp": 4,
            "max_hp": 18,
            "ability_scores": {"constitution": 14},
            "resources": {
                "second_wind": {
                    "label": "回气",
                    "current": 0,
                    "max": 1,
                    "recovery": "short_rest",
                },
                "luck": {
                    "label": "幸运",
                    "current": 0,
                    "max": 1,
                    "recovery": "long_rest",
                },
                "dawn_charge": {
                    "label": "黎明充能",
                    "current": 0,
                    "max": 1,
                    "recovery": "dawn",
                },
            },
        },
    )
    assert response.status_code == 201
    return response.json()


def _preview_body(character: dict[str, Any], hit_die_id: str) -> dict[str, Any]:
    return {
        "rest_type": "short",
        "duration_minutes": 60,
        "participants": [
            {
                "character_id": character["id"],
                "character_version": character["version"],
                "hit_dice": [{"resource_pool_id": hit_die_id, "roll": 6}],
            }
        ],
    }


def test_short_rest_preview_and_confirm_are_atomic_and_idempotent(
    rest_client: TestClient,
) -> None:
    campaign = _campaign(rest_client, current_time="2026-07-26T10:00:00Z")
    character = _character(rest_client, campaign["id"])
    pools_response = rest_client.get(
        f"/api/v1/campaigns/{campaign['id']}/resources",
        params={"character_id": character["id"]},
    )
    assert pools_response.status_code == 200
    pools = pools_response.json()["items"]
    hit_die = next(pool for pool in pools if pool["category"] == "hit_die")
    body = _preview_body(character, hit_die["id"])

    preview_response = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/preview",
        json=body,
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    participant = preview["participants"][0]
    assert participant["after"]["hp"] == 12
    assert {change["key"] for change in participant["changes"] if "key" in change} == {
        "second_wind",
        hit_die["key"],
    }
    assert preview["world_time_after"].startswith("2026-07-26T11:00:00")

    confirm_body = {
        **body,
        "preview_token": preview["preview_token"],
        "idempotency_key": "rest-short-0001",
    }
    confirmed_response = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/confirm",
        json=confirm_body,
    )
    assert confirmed_response.status_code == 200
    confirmed = confirmed_response.json()
    assert confirmed["rest_record_id"]

    updated = rest_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert updated["hp"] == 12
    assert updated["resources"]["second_wind"]["current"] == 1
    assert updated["resources"]["luck"]["current"] == 0
    assert updated["resources"]["dawn_charge"]["current"] == 0

    replay_response = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/confirm",
        json=confirm_body,
    )
    assert replay_response.status_code == 200
    assert replay_response.json()["rest_record_id"] == confirmed["rest_record_id"]
    replayed_character = rest_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert replayed_character["version"] == updated["version"]


def test_team_rest_rejects_stale_participant_without_partial_changes(
    rest_client: TestClient,
) -> None:
    campaign = _campaign(rest_client)
    first = _character(rest_client, campaign["id"], "甲")
    second = _character(rest_client, campaign["id"], "乙")
    body = {
        "rest_type": "long",
        "duration_minutes": 480,
        "participants": [
            {"character_id": first["id"], "character_version": first["version"]},
            {"character_id": second["id"], "character_version": second["version"] + 1},
        ],
    }
    response = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/preview",
        json=body,
    )
    assert response.status_code == 409
    assert rest_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{first['id']}"
    ).json()["hp"] == 4


def test_rest_resets_relentless_rage_dc_in_active_combat_snapshot(
    rest_client: TestClient,
) -> None:
    campaign = _campaign(rest_client)
    character = _character(rest_client, campaign["id"], "狂暴 DC 重置者")
    combat_response = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "休息中的战斗快照"},
    )
    assert combat_response.status_code == 201, combat_response.text
    combat = combat_response.json()
    combatant_response = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "hp": 18,
            "max_hp": 18,
            "snapshot_json": {
                "relentless_rage_state": {
                    "current_dc": 25,
                    "last_result": "success",
                },
                "feature_runtime": {
                    "combat_start": {
                        "defenses": [
                            {
                                "id": "relentless_rage:zero_hit_points_save",
                                "kind": "zero_hp_intervention",
                                "trigger": "would_drop_to_zero_hit_points",
                                "saving_throw": {
                                    "ability": "constitution",
                                    "initial_dc": 10,
                                    "increase_after_success": 5,
                                },
                                "state": {
                                    "key": "relentless_rage_state",
                                    "current_dc_field": "current_dc",
                                    "reset_reason": "short_or_long_rest",
                                },
                                "resets": ["short_rest", "long_rest"],
                            }
                        ]
                    }
                },
            },
        },
    )
    assert combatant_response.status_code == 201, combatant_response.text
    combatant = combatant_response.json()
    body = {
        "rest_type": "short",
        "duration_minutes": 60,
        "participants": [
            {
                "character_id": character["id"],
                "character_version": character["version"],
            }
        ],
    }
    preview = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/preview",
        json=body,
    )
    assert preview.status_code == 200, preview.text
    confirm = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/confirm",
        json={
            **body,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": "relentless-rage-rest-reset",
        },
    )
    assert confirm.status_code == 200, confirm.text
    assert combatant["id"] in confirm.json()["participants"][0]["feature_runtime_resets"]
    refreshed = rest_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants/{combatant['id']}"
    )
    assert refreshed.status_code == 200, refreshed.text
    state = refreshed.json()["snapshot_json"]["relentless_rage_state"]
    assert state["current_dc"] == 10
    assert state["reset_reason"] == "short_or_long_rest"


def test_interrupted_short_rest_has_no_benefit_and_null_time_is_preserved(
    rest_client: TestClient,
) -> None:
    campaign = _campaign(rest_client)
    character = _character(rest_client, campaign["id"])
    body = {
        "rest_type": "short",
        "duration_minutes": 60,
        "interrupted": True,
        "interruption_reason": "遭遇巡逻队并进入先攻",
        "participants": [
            {"character_id": character["id"], "character_version": character["version"]}
        ],
    }
    preview = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/preview",
        json=body,
    ).json()
    assert preview["participants"][0]["after"]["hp"] == 4
    assert preview["world_time_after"] is None
    assert preview["warnings"]


def test_long_rest_recovers_long_term_reductions_and_enforces_cooldown(
    rest_client: TestClient,
) -> None:
    campaign = _campaign(rest_client, current_time="2026-07-26T20:00:00Z")
    created = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "受创法师",
            "class_name": "法师",
            "hp": 2,
            "max_hp": 10,
            "max_hp_reduction": 3,
            "ability_score_reductions": {"strength": 2},
            "death_saves": {"successes": 1, "failures": 2},
            "resources": {
                "spell_slots_1": {
                    "label": "1环法术位",
                    "current": 0,
                    "max": 2,
                    "recovery": "long_rest",
                }
            },
        },
    ).json()
    body = {
        "rest_type": "long",
        "duration_minutes": 480,
        "participants": [
            {"character_id": created["id"], "character_version": created["version"]}
        ],
    }
    preview = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/preview", json=body
    ).json()
    assert preview["participants"][0]["after"] == {
        "hp": 10,
        "fatigue": 0,
        "max_hp_reduction": 0,
        "ability_score_reductions": {},
        "death_saves": {"successes": 0, "failures": 0},
    }
    confirm = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/confirm",
        json={
            **body,
            "preview_token": preview["preview_token"],
            "idempotency_key": "rest-long-0001",
        },
    )
    assert confirm.status_code == 200, confirm.text
    updated = rest_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
    ).json()
    assert updated["max_hp_reduction"] == 0
    assert updated["ability_score_reductions"] == {}
    assert updated["death_saves"] == {"successes": 0, "failures": 0}
    assert updated["resources"]["spell_slots_1"]["current"] == 2

    too_soon = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/preview",
        json={
            **body,
            "participants": [
                {
                    "character_id": updated["id"],
                    "character_version": updated["version"],
                }
            ],
        },
    )
    assert too_soon.status_code == 400
    assert "16 hours" in too_soon.text


def test_tireless_ranger_short_rest_reduces_exhaustion_without_consuming_resource(
    rest_client: TestClient,
) -> None:
    campaign = _campaign(rest_client)
    created = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "不知疲倦游侠",
            "class_name": "游侠",
            "level": 10,
            "hp": 8,
            "max_hp": 20,
            "ability_scores": {"constitution": 12, "wisdom": 16},
            "class_levels": {"游侠": 10},
            "features": [
                {
                    "name": "不知疲倦",
                    "class_name": "游侠",
                    "class_level": 10,
                    "kind": "feature",
                    "runtime": {"tracked_resource_keys": ["tireless"]},
                }
            ],
            "resources": {
                "tireless": {
                    "label": "不知疲倦",
                    "current": 1,
                    "max": 3,
                    "recovery": "long_rest",
                }
            },
        },
    ).json()
    condition = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}/conditions",
        json={"condition_name": "力竭", "details": {"level": 3}},
    )
    assert condition.status_code == 201, condition.text

    body = {
        "rest_type": "short",
        "duration_minutes": 60,
        "participants": [
            {"character_id": created["id"], "character_version": created["version"]}
        ],
    }
    preview = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/preview", json=body
    )
    assert preview.status_code == 200, preview.text
    participant = preview.json()["participants"][0]
    assert participant["after"]["fatigue"] == 2
    assert any(
        change["type"] == "condition" and change["before"] == 3 and change["after"] == 2
        for change in participant["changes"]
    )

    confirm = rest_client.post(
        f"/api/v1/campaigns/{campaign['id']}/rests/confirm",
        json={
            **body,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": "tireless-short-rest-1",
        },
    )
    assert confirm.status_code == 200, confirm.text
    updated = rest_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}"
    ).json()
    assert updated["resources"]["tireless"]["current"] == 1
    fatigue = rest_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{created['id']}/conditions"
    ).json()["items"]
    assert fatigue[0]["details"]["level"] == 2
