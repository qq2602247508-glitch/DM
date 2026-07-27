from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database.models import AuditLog


@pytest.fixture
def campaign_client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'campaign.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as client:
        client.database_url = database_url  # type: ignore[attr-defined]
        yield client


def _campaign(client: TestClient, name: str = "Ravenloft") -> dict[str, Any]:
    response = client.post("/api/v1/campaigns", json={"name": name})
    assert response.status_code == 201
    return response.json()


def test_campaign_character_update_conflict_and_audit(campaign_client: TestClient) -> None:
    campaign = _campaign(campaign_client)
    path = f"/api/v1/campaigns/{campaign['id']}/characters"
    character_response = campaign_client.post(
        path, json={"name": "Ireena", "level": 3, "hp": 18, "max_hp": 18}
    )
    assert character_response.status_code == 201
    character = character_response.json()

    updated = campaign_client.patch(
        f"{path}/{character['id']}",
        headers={"If-Match": '"1"', "X-Request-ID": "test-update"},
        json={"hp": 12},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["hp"] == 12

    conflict = campaign_client.patch(
        f"{path}/{character['id']}", headers={"If-Match": "1"}, json={"hp": 1}
    )
    assert conflict.status_code == 409
    assert campaign_client.get(f"{path}/{character['id']}").json()["hp"] == 12

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        actions = session.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity_id == character["id"])
            .order_by(AuditLog.created_at)
        ).all()
        assert actions == ["create", "update"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.request_id == "test-update")
            )
            == 1
        )


def test_cross_campaign_and_parent_scope_are_404(campaign_client: TestClient) -> None:
    first = _campaign(campaign_client, "First")
    second = _campaign(campaign_client, "Second")
    character = campaign_client.post(
        f"/api/v1/campaigns/{first['id']}/characters",
        json={"name": "Hero", "hp": 5, "max_hp": 5},
    ).json()
    condition = campaign_client.post(
        f"/api/v1/campaigns/{first['id']}/characters/{character['id']}/conditions",
        json={"condition_name": "Poisoned"},
    ).json()

    assert (
        campaign_client.get(
            f"/api/v1/campaigns/{second['id']}/characters/{character['id']}"
        ).status_code
        == 404
    )
    assert (
        campaign_client.get(
            f"/api/v1/campaigns/{second['id']}/characters/{character['id']}/"
            f"conditions/{condition['id']}"
        ).status_code
        == 404
    )


def test_aggregate_is_bounded_and_filters_open_state(campaign_client: TestClient) -> None:
    campaign = _campaign(campaign_client)
    for index in range(3):
        response = campaign_client.post(
            f"/api/v1/campaigns/{campaign['id']}/characters",
            json={"name": f"Hero {index}", "hp": 1, "max_hp": 1},
        )
        assert response.status_code == 201
    closed = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/clues",
        json={"name": "Known", "discovered": True},
    )
    assert closed.status_code == 201

    state = campaign_client.get(f"/api/v1/campaigns/{campaign['id']}/state?limit=2")
    assert state.status_code == 200
    assert len(state.json()["characters"]) == 2
    assert state.json()["open_clues"] == []


def test_campaign_delete_retains_tombstone_audit(campaign_client: TestClient) -> None:
    campaign = _campaign(campaign_client)
    response = campaign_client.delete(
        f"/api/v1/campaigns/{campaign['id']}", headers={"If-Match": "1"}
    )
    assert response.status_code == 204

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.entity_type == "campaign",
                AuditLog.entity_id == campaign["id"],
                AuditLog.action == "delete",
            )
        )
        assert audit is not None
        assert audit.campaign_id is None


def test_deleting_current_location_sets_campaign_reference_null(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client)
    location = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/locations", json={"name": "Castle"}
    ).json()
    updated = campaign_client.patch(
        f"/api/v1/campaigns/{campaign['id']}",
        headers={"If-Match": "1"},
        json={"current_location_id": location["id"]},
    )
    assert updated.status_code == 200
    deleted = campaign_client.delete(
        f"/api/v1/campaigns/{campaign['id']}/locations/{location['id']}",
        headers={"If-Match": "1"},
    )
    assert deleted.status_code == 204
    refreshed = campaign_client.get(f"/api/v1/campaigns/{campaign['id']}").json()
    assert refreshed["current_location_id"] is None


def test_validation_and_if_match_contract(campaign_client: TestClient) -> None:
    campaign = _campaign(campaign_client)
    path = f"/api/v1/campaigns/{campaign['id']}/characters"
    invalid = campaign_client.post(path, json={"name": "Broken", "hp": 2, "max_hp": 1})
    assert invalid.status_code == 422
    character = campaign_client.post(path, json={"name": "Valid", "hp": 1, "max_hp": 1}).json()
    target = f"{path}/{character['id']}"
    assert campaign_client.patch(target, json={"hp": 0}).status_code == 428
    assert (
        campaign_client.patch(
            target, headers={"If-Match": "1"}, json={"version": 2, "hp": 0}
        ).status_code
        == 400
    )
    assert campaign_client.patch(target, headers={"If-Match": "1"}, json={}).status_code == 400
    assert (
        campaign_client.patch(target, headers={"If-Match": "1"}, json={"max_hp": 0}).status_code
        == 422
    )
    unchanged = campaign_client.get(target).json()
    assert (unchanged["hp"], unchanged["max_hp"], unchanged["version"]) == (1, 1, 1)
    assert campaign_client.delete(target, headers={"If-Match": "2"}).status_code == 409
    assert campaign_client.get(target).status_code == 200


def test_openapi_exposes_typed_nested_request(campaign_client: TestClient) -> None:
    schema = campaign_client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/campaigns/{campaign_id}/characters"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/CharacterCreate")


def test_structured_dnd_fields_and_backup_round_trip(campaign_client: TestClient) -> None:
    campaign = _campaign(campaign_client, "Structured")
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "Aerin",
            "race": "Elf",
            "class_name": "Wizard",
            "level": 5,
            "armor_class": 15,
            "speed": 30,
            "ability_scores": {"intelligence": 18},
            "equipment": ["spellbook"],
            "hp": 22,
            "max_hp": 22,
        },
    )
    assert character.status_code == 201
    assert character.json()["armor_class"] == 15
    quest = campaign_client.post(
        f"{base}/quests",
        json={
            "name": "Find the bell",
            "quest_type": "main",
            "giver": "Harbormaster",
            "reward": "200 gp",
        },
    )
    assert quest.status_code == 201
    campaign_client.post(
        f"{base}/clues",
        json={
            "name": "Black feather",
            "player_text": "A wet black feather",
            "dm_truth": "Cult marker",
            "verified": True,
        },
    )

    exported = campaign_client.get(f"{base}/export")
    assert exported.status_code == 200
    assert exported.json()["characters"][0]["equipment"] == ["spellbook"]

    imported = campaign_client.post(
        "/api/v1/campaigns/import-backup",
        json={"backup": exported.json(), "name": "Structured Copy"},
    )
    assert imported.status_code == 201
    imported_id = imported.json()["id"]
    characters = campaign_client.get(
        f"/api/v1/campaigns/{imported_id}/characters"
    ).json()["items"]
    clues = campaign_client.get(f"/api/v1/campaigns/{imported_id}/clues").json()["items"]
    assert characters[0]["race"] == "Elf"
    assert characters[0]["ability_scores"] == {"intelligence": 18}
    assert clues[0]["dm_truth"] == "Cult marker"


def test_location_tree_item_pickup_and_dnd5e_encumbrance(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "World atoms")
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "Porter",
            "ability_scores": {"strength": 8, "dexterity": 12},
            "hp": 10,
            "max_hp": 10,
        },
    ).json()
    preview = {
        "ruleset": "dnd5e",
        "primary_rules_year": 2024,
        "maximum_depth": 2,
        "root": {
            "temp_id": "church",
            "name": "旧教堂",
            "description": "被异端占据的礼拜堂。",
            "interactive_objects": ["裂开的祭坛"],
            "secrets": "祭坛后有机关。",
            "discovered": True,
            "items": [
                {
                    "name": "黄铜圣徽",
                    "description": "表面已经发黑。",
                    "category": "treasure",
                    "quantity": 2,
                    "unit_weight_lb": 1.5,
                    "price_cp": 250,
                    "hidden": False,
                }
            ],
            "suggested_npcs": [],
            "suggested_monsters": [],
            "children": [
                {
                    "temp_id": "crypt",
                    "name": "地下墓室",
                    "description": "潮湿而寒冷。",
                    "interactive_objects": ["石棺"],
                    "discovered": False,
                    "items": [],
                    "suggested_npcs": [],
                    "suggested_monsters": ["骷髅"],
                    "children": [],
                }
            ],
        },
        "citations": [],
        "warnings": [],
    }
    confirmed = campaign_client.post(
        f"{base}/generate/location/confirm", json={"preview": preview}
    )
    assert confirmed.status_code == 201
    assert [row["depth"] for row in confirmed.json()["locations"]] == [1, 2]
    item = confirmed.json()["items"][0]

    picked_up = campaign_client.post(
        f"{base}/items/{item['id']}/pickup",
        json={"character_id": character["id"], "quantity": 1, "version": item["version"]},
    )
    assert picked_up.status_code == 200
    summary = picked_up.json()["inventory"]
    assert summary["total_weight_lb"] == 1.5
    assert summary["maximum_weight_lb"] == 120
    assert summary["state"] == "normal"
    remaining = campaign_client.get(
        f"{base}/items?location_id={confirmed.json()['locations'][0]['id']}"
    ).json()["items"]
    assert remaining[0]["quantity"] == 1
    backup = campaign_client.get(f"{base}/export").json()
    assert len(backup["world_items"]) == 2
    imported = campaign_client.post(
        "/api/v1/campaigns/import-backup",
        json={"backup": backup, "name": "World atoms copy"},
    )
    assert imported.status_code == 201
    imported_base = f"/api/v1/campaigns/{imported.json()['id']}"
    imported_locations = campaign_client.get(f"{imported_base}/locations").json()["items"]
    assert len(imported_locations) == 2
    assert next(row for row in imported_locations if row["depth"] == 2)[
        "parent_location_id"
    ] == next(row for row in imported_locations if row["depth"] == 1)["id"]
    assert len(campaign_client.get(f"{imported_base}/items").json()["items"]) == 2


def test_scene_reuses_atomic_participants_and_starts_visible_initiative(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "Scene combat")
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "Rogue",
            "armor_class": 15,
            "ability_scores": {"dexterity": 18},
            "hp": 12,
            "max_hp": 12,
        },
    ).json()
    npc = campaign_client.post(
        f"{base}/npcs",
        json={
            "name": "Guard",
            "armor_class": 13,
            "ability_scores": {"dexterity": 12},
            "hp": 9,
            "max_hp": 9,
        },
    ).json()
    scene = campaign_client.post(f"{base}/scenes", json={"name": "教堂冲突"}).json()
    grid = campaign_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 12, "height": 8, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201
    for entity_type, entity_id in (("character", character["id"]), ("npc", npc["id"])):
        response = campaign_client.post(
            f"{base}/scenes/{scene['id']}/participants",
            json={"entity_type": entity_type, "entity_id": entity_id},
        )
        assert response.status_code == 201
        assert response.json()["entity"]["id"] == entity_id

    duplicate = campaign_client.post(
        f"{base}/scenes/{scene['id']}/participants",
        json={"entity_type": "npc", "entity_id": npc["id"]},
    )
    assert duplicate.status_code == 422

    started = campaign_client.post(
        f"{base}/scenes/{scene['id']}/start-combat", json={}
    )
    assert started.status_code == 201
    rolls = started.json()["initiative_rolls"]
    assert len(rolls) == 2
    assert {roll["dexterity_modifier"] for roll in rolls} == {1, 4}
    assert all(1 <= roll["die"] <= 20 for roll in rolls)
    combat_id = started.json()["combat"]["id"]
    combatants = campaign_client.get(f"{base}/combats/{combat_id}/combatants").json()[
        "items"
    ]
    assert {row["entity_id"] for row in combatants} == {character["id"], npc["id"]}
    positions = [row["snapshot_json"]["grid_position"] for row in combatants]
    assert len({(position["row"], position["col"]) for position in positions}) == 2
    assert all(1 <= position["row"] <= 8 for position in positions)
    assert all(1 <= position["col"] <= 12 for position in positions)
    backup = campaign_client.get(f"{base}/export").json()
    imported = campaign_client.post(
        "/api/v1/campaigns/import-backup",
        json={"backup": backup, "name": "Scene combat copy"},
    )
    assert imported.status_code == 201
    imported_base = f"/api/v1/campaigns/{imported.json()['id']}"
    imported_scenes = campaign_client.get(f"{imported_base}/scenes").json()["items"]
    imported_participants = campaign_client.get(
        f"{imported_base}/scenes/{imported_scenes[0]['id']}/participants"
    ).json()["items"]
    assert len(imported_participants) == 2
