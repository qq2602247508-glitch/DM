from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.models import (
    Character,
    MonsterInstance,
    ResourcePool,
    SceneParticipant,
)


def _build_session(client: TestClient) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "检查点测试团"}).json()
    root = f"/api/v1/campaigns/{campaign['id']}"
    hero = client.post(
        f"{root}/characters",
        json={
            "name": "艾琳",
            "class_name": "法师",
            "experience": 900,
            "hp": 24,
            "max_hp": 30,
            "resources": {"arcane_recovery": {"current": 1, "maximum": 1}},
        },
    ).json()
    npc = client.post(
        f"{root}/npcs",
        json={"name": "旅店老板", "hp": 9, "max_hp": 9, "status": "active"},
    ).json()
    monster = client.post(
        f"{root}/monsters",
        json={"name": "灰矮人斥候", "hp": 18, "max_hp": 18, "armor_class": 15},
    ).json()
    scene = client.post(f"{root}/scenes", json={"name": "黑石酒馆"}).json()
    participants = []
    for kind, entity in (("character", hero), ("npc", npc), ("monster", monster)):
        response = client.post(
            f"{root}/scenes/{scene['id']}/participants",
            json={"entity_type": kind, "entity_id": entity["id"]},
        )
        assert response.status_code == 201
        participants.append(response.json())
    combat = client.post(
        f"{root}/scenes/{scene['id']}/start-combat",
        json={"name": "突袭酒馆"},
    ).json()["combat"]
    return {
        "campaign": campaign,
        "root": root,
        "hero": hero,
        "npc": npc,
        "monster": monster,
        "scene": scene,
        "participants": participants,
        "combat": combat,
    }


def test_checkpoint_captures_previews_and_transactionally_restores_authoritative_state(
    campaign_client: TestClient,
) -> None:
    data = _build_session(campaign_client)
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        session.add(
            ResourcePool(
                campaign_id=data["campaign"]["id"],
                character_id=data["hero"]["id"],
                key="spell_slot_3",
                label="3环法术位",
                category="spell_slot",
                current=2,
                maximum=3,
                recovery_timing="long_rest",
            )
        )

    created = campaign_client.post(
        f"{data['root']}/session-checkpoints",
        json={
            "name": "酒馆战斗前",
            "scene_id": data["scene"]["id"],
            "active_combat_id": data["combat"]["id"],
            "entries": [
                {"id": "entry-1", "kind": "dm", "text": "灰矮人踢开了后门。"},
                {"id": "entry-2", "kind": "system", "text": "进入战斗。"},
            ],
            "expected_campaign_version": data["campaign"]["version"],
        },
    )
    assert created.status_code == 201
    checkpoint = created.json()
    assert checkpoint["schema_version"] == 1
    assert checkpoint["participant_count"] == 3
    assert checkpoint["entity_count"] == 3
    assert checkpoint["combatant_count"] == 3
    assert checkpoint["entry_count"] == 2

    with Session(engine) as session, session.begin():
        hero = session.get(Character, data["hero"]["id"])
        assert hero is not None
        hero.hp = 3
        hero.experience = 1_500
        hero.resources = {"arcane_recovery": {"current": 0, "maximum": 1}}
        hero.version += 1
        pool = session.scalar(
            select(ResourcePool).where(
                ResourcePool.character_id == data["hero"]["id"],
                ResourcePool.key == "spell_slot_3",
            )
        )
        assert pool is not None
        pool.current = 0
        pool.version += 1
        participant = session.get(SceneParticipant, data["participants"][1]["id"])
        assert participant is not None
        session.delete(participant)

    preview = campaign_client.post(
        f"{data['root']}/session-checkpoints/{checkpoint['id']}/restore-preview",
        json={},
    )
    assert preview.status_code == 200
    assert preview.json()["can_restore"] is False
    assert preview.json()["force_required"] is True
    assert {
        row["entity_type"]
        for row in preview.json()["conflicts"]
        if row["code"] == "dependency_version_mismatch"
    } >= {"character", "resource_pool"}

    rejected = campaign_client.post(
        f"{data['root']}/session-checkpoints/{checkpoint['id']}/restore",
        json={"idempotency_key": "restore-checkpoint-no-force"},
    )
    assert rejected.status_code == 409

    restored = campaign_client.post(
        f"{data['root']}/session-checkpoints/{checkpoint['id']}/restore",
        json={"force": True, "idempotency_key": "restore-checkpoint-force-001"},
    )
    assert restored.status_code == 200
    assert restored.json()["restored"] is True
    assert restored.json()["entries"][0]["id"] == "entry-1"

    with Session(engine) as session:
        hero = session.get(Character, data["hero"]["id"])
        assert hero is not None
        assert hero.hp == 24
        assert hero.experience == 900
        assert hero.resources["arcane_recovery"]["current"] == 1
        pool = session.scalar(
            select(ResourcePool).where(
                ResourcePool.character_id == data["hero"]["id"],
                ResourcePool.key == "spell_slot_3",
            )
        )
        assert pool is not None
        assert pool.current == 2
        participants = list(
            session.scalars(
                select(SceneParticipant).where(
                    SceneParticipant.scene_id == data["scene"]["id"]
                )
            )
        )
        assert len(participants) == 3

    state = campaign_client.get(f"{data['root']}/session-checkpoints/current-state")
    assert state.status_code == 200
    assert state.json()["current_scene_id"] == data["scene"]["id"]
    assert state.json()["active_combat_id"] == data["combat"]["id"]
    assert state.json()["entries"][1]["kind"] == "system"

    replay = campaign_client.post(
        f"{data['root']}/session-checkpoints/{checkpoint['id']}/restore",
        json={"force": True, "idempotency_key": "restore-checkpoint-force-001"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True


def test_missing_required_dependency_blocks_force_restore_before_any_write(
    campaign_client: TestClient,
) -> None:
    data = _build_session(campaign_client)
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    checkpoint = campaign_client.post(
        f"{data['root']}/session-checkpoints",
        json={
            "name": "不可恢复依赖",
            "scene_id": data["scene"]["id"],
            "active_combat_id": data["combat"]["id"],
        },
    ).json()
    with Session(engine) as session, session.begin():
        hero = session.get(Character, data["hero"]["id"])
        monster = session.get(MonsterInstance, data["monster"]["id"])
        assert hero is not None and monster is not None
        hero.hp = 2
        hero.version += 1
        session.delete(monster)

    preview = campaign_client.post(
        f"{data['root']}/session-checkpoints/{checkpoint['id']}/restore-preview",
        json={"force": True},
    )
    assert preview.status_code == 200
    assert preview.json()["can_restore"] is False
    assert any(
        row["code"] == "missing_dependency" and row["entity_type"] == "monster"
        for row in preview.json()["conflicts"]
    )

    rejected = campaign_client.post(
        f"{data['root']}/session-checkpoints/{checkpoint['id']}/restore",
        json={"force": True, "idempotency_key": "restore-missing-monster"},
    )
    assert rejected.status_code == 409
    with Session(engine) as session:
        hero = session.get(Character, data["hero"]["id"])
        assert hero is not None
        assert hero.hp == 2


def test_checkpoint_archive_is_version_guarded(campaign_client: TestClient) -> None:
    data = _build_session(campaign_client)
    checkpoint = campaign_client.post(
        f"{data['root']}/session-checkpoints",
        json={"name": "可归档", "scene_id": data["scene"]["id"]},
    ).json()
    stale = campaign_client.post(
        f"{data['root']}/session-checkpoints/{checkpoint['id']}/archive",
        json={"version": checkpoint["version"] + 1},
    )
    assert stale.status_code == 409
    archived = campaign_client.post(
        f"{data['root']}/session-checkpoints/{checkpoint['id']}/archive",
        json={"version": checkpoint["version"]},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert campaign_client.get(f"{data['root']}/session-checkpoints").json()[
        "checkpoints"
    ] == []
    listed = campaign_client.get(
        f"{data['root']}/session-checkpoints?include_archived=true"
    ).json()["checkpoints"]
    assert listed[0]["id"] == checkpoint["id"]
