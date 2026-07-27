from __future__ import annotations

import hashlib
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.routes.player_rooms import _clear_join_failures
from dnd_dm_assistant.infrastructure.database.models import PlayerRoom, PlayerSession


def _campaign(client: TestClient, name: str = "LAN团") -> dict[str, Any]:
    return client.post("/api/v1/campaigns", json={"name": name}).json()


def _open(client: TestClient, campaign_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/campaigns/{campaign_id}/player-room/open",
        json={"hours": 4},
    )
    assert response.status_code == 200
    return response.json()


def _join(client: TestClient, code: str, name: str = "玩家甲") -> dict[str, Any]:
    response = client.post(
        "/api/v1/player-room/join",
        json={"join_code": code, "display_name": name},
    )
    assert response.status_code == 201
    assert "token" not in response.json()
    assert "dnd_player_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    return response.json()


def test_room_code_is_salted_and_cookie_session_is_revocable(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client)
    opened = _open(campaign_client, campaign["id"])
    code = opened["join_code"]
    assert opened["join_code_hint"] == code[-2:]
    assert opened["active"] is True

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        room = session.scalar(select(PlayerRoom).where(PlayerRoom.campaign_id == campaign["id"]))
        assert room is not None
        assert len(room.join_code_salt) == 32
        assert room.join_code_hash != hashlib.sha256(code.encode()).hexdigest()
        assert code not in room.join_code_hash

    _join(campaign_client, code)
    assert campaign_client.get("/api/v1/player-room/me").status_code == 200
    logged_out = campaign_client.post("/api/v1/player-room/logout")
    assert logged_out.status_code == 204
    assert campaign_client.get("/api/v1/player-room/me").status_code == 401


def test_player_character_creation_binding_and_campaign_scope(
    campaign_client: TestClient,
) -> None:
    campaign_a = _campaign(campaign_client, "A团")
    campaign_b = _campaign(campaign_client, "B团")
    opened = _open(campaign_client, campaign_a["id"])
    _join(campaign_client, opened["join_code"])
    wizard_spells = [
        {
            "name": name,
            "source_record_id": f"spell-{index}",
            "source_path": f"玩家手册2024/法术详述/{level}环.htm",
            "spell_level": level,
            "classes": ["法师"],
        }
        for index, (name, level) in enumerate(
            [
                ("火焰箭", 0),
                ("法师之手", 0),
                ("次级幻象", 0),
                ("魔法飞弹", 1),
                ("护盾术", 1),
                ("睡眠术", 1),
                ("油腻术", 1),
                ("云雾术", 1),
                ("寻获魔宠", 1),
            ]
        )
    ]
    for spell in wizard_spells:
        spell["prepared"] = spell["spell_level"] == 0 or spell["name"] in {
            "魔法飞弹",
            "护盾术",
            "睡眠术",
            "油腻术",
        }
    rejected_unlimited = campaign_client.post(
        "/api/v1/player-room/me/characters",
        json={
            "name": "未按规则选择",
            "race": "精灵",
            "class_name": "法师",
            "background": "学者",
            "ability_scores": {
                "strength": 8,
                "dexterity": 14,
                "constitution": 13,
                "intelligence": 15,
                "wisdom": 12,
                "charisma": 10,
            },
            "skill_proficiencies": [],
            "spells": wizard_spells[:1],
        },
    )
    assert rejected_unlimited.status_code == 400
    invalid_preparation = [
        {**spell, "prepared": spell["spell_level"] == 0} for spell in wizard_spells
    ]
    rejected_unprepared = campaign_client.post(
        "/api/v1/player-room/me/characters",
        json={
            "name": "未准备足够法术",
            "race": "精灵",
            "class_name": "法师",
            "background": "学者",
            "ability_scores": {
                "strength": 8,
                "dexterity": 14,
                "constitution": 13,
                "intelligence": 15,
                "wisdom": 12,
                "charisma": 10,
            },
            "skill_proficiencies": ["洞悉", "调查"],
            "spells": invalid_preparation,
        },
    )
    assert rejected_unprepared.status_code == 400

    created = campaign_client.post(
        "/api/v1/player-room/me/characters",
        json={
            "name": "伊莱娜",
            "race": "精灵",
            "class_name": "法师",
            "background": "学者",
            "ability_scores": {
                "strength": 8,
                "dexterity": 14,
                "constitution": 13,
                "intelligence": 15,
                "wisdom": 12,
                "charisma": 10,
            },
            "skill_proficiencies": ["洞悉", "调查"],
            "spells": wizard_spells,
        },
    )
    assert created.status_code == 201
    character = created.json()
    assert character["level"] == 1
    assert character["class_levels"] == {"法师": 1}
    assert character["speed"] == 30
    assert {"黑暗视觉", "敏锐感官", "出神"} <= set(character["features"])
    assert "背景专长：魔法学徒（法师）" in character["features"]
    assert {"奥秘", "历史", "调查"} <= set(character["skills"])
    assert {"法杖", "法术书", "书法工具"} <= set(character["equipment"])
    assert character["resources"]["spell_slots_1"]["current"] == 2
    assert character["resources"]["arcane_recovery"]["current"] == 1
    assert character["spellcasting"]["ability"] == "智力"
    assert character["actions"][0]["name"] == "火焰箭"
    assert {spell["name"] for spell in character["spells"]} >= {"魔法飞弹", "火焰箭"}
    assert sum(
        spell["spell_level"] == 1 and spell["prepared"] for spell in character["spells"]
    ) == 4
    assert "notes" not in character
    assert (
        campaign_client.get("/api/v1/player-room/me").json()["character"]["id"] == character["id"]
    )

    foreign = campaign_client.post(
        f"/api/v1/campaigns/{campaign_b['id']}/characters",
        json={"name": "外团角色", "hp": 1, "max_hp": 1},
    ).json()
    rejected = campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": foreign["id"]},
    )
    assert rejected.status_code == 404


def test_player_snapshot_exposes_selected_scene_grid_and_public_objects(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "公开地图团")
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "博德之门酒馆"},
    ).json()
    created_grid = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid",
        json={
            "width": 18,
            "height": 12,
            "cell_size_ft": 5,
            "mode": "combat",
            "public_description": "酒馆大厅、吧台与后厨",
            "layers_json": {
                "cells": [
                    {"row": 1, "col": 1, "kind": "wall", "label": "酒馆外墙"},
                    {"row": 2, "col": 2, "kind": "cover", "label": "木制吧台"},
                ]
            },
        },
    )
    assert created_grid.status_code == 201
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    live = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-room/live-state",
        json={"scene_id": scene["id"]},
    )
    assert live.status_code == 200

    public_scene = campaign_client.get("/api/v1/player-room/me").json()["table"]["scene"]
    assert public_scene["grid"] == {
        "width": 18,
        "height": 12,
        "cell_size_ft": 5,
        "mode": "combat",
        "public_description": "酒馆大厅、吧台与后厨",
    }
    assert {(item["object_type"], item["label"]) for item in public_scene["objects"]} == {
        ("wall", "酒馆外墙"),
        ("cover", "木制吧台"),
    }


def test_room_live_state_rejects_cross_campaign_ids(campaign_client: TestClient) -> None:
    campaign_a = _campaign(campaign_client, "A团")
    campaign_b = _campaign(campaign_client, "B团")
    _open(campaign_client, campaign_a["id"])
    scene_b = campaign_client.post(
        f"/api/v1/campaigns/{campaign_b['id']}/scenes",
        json={"name": "B团秘密场景"},
    ).json()
    response = campaign_client.post(
        f"/api/v1/campaigns/{campaign_a['id']}/player-room/live-state",
        json={"scene_id": scene_b["id"]},
    )
    assert response.status_code == 404


def test_active_character_can_only_be_claimed_once(campaign_client: TestClient) -> None:
    campaign = _campaign(campaign_client)
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "唯一角色", "hp": 8, "max_hp": 8},
    ).json()
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"], "玩家甲")
    first_cookie = campaign_client.cookies.get("dnd_player_session")
    first = campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    )
    assert first.status_code == 200

    _join(campaign_client, opened["join_code"], "玩家乙")
    second = campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    )
    assert second.status_code == 400

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        claims = session.scalars(
            select(PlayerSession).where(
                PlayerSession.character_id == character["id"],
                PlayerSession.status == "active",
            )
        ).all()
        assert len(claims) == 1
    assert first_cookie


def test_failed_join_is_rate_limited_and_success_clears_failures(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client)
    opened = _open(campaign_client, campaign["id"])
    for _ in range(5):
        response = campaign_client.post(
            "/api/v1/player-room/join",
            json={"join_code": "XXXXXX", "display_name": "猜码者"},
        )
        assert response.status_code == 400
    limited = campaign_client.post(
        "/api/v1/player-room/join",
        json={"join_code": opened["join_code"], "display_name": "猜码者"},
    )
    assert limited.status_code == 429
    _clear_join_failures("testclient")
    assert (
        campaign_client.post(
            "/api/v1/player-room/join",
            json={"join_code": opened["join_code"], "display_name": "正常玩家"},
        ).status_code
        == 201
    )


def test_closing_room_revokes_every_player_cookie(campaign_client: TestClient) -> None:
    campaign = _campaign(campaign_client)
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    assert campaign_client.get("/api/v1/player-room/me").status_code == 200
    closed = campaign_client.post(f"/api/v1/campaigns/{campaign['id']}/player-room/close")
    assert closed.status_code == 200
    assert closed.json()["active"] is False
    assert campaign_client.get("/api/v1/player-room/me").status_code == 401


def test_ended_combat_is_read_only_in_player_snapshot(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client)
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "联机法师", "hp": 7, "max_hp": 7},
    ).json()
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    bound = campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    )
    assert bound.status_code == 200

    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "已结束的联机战斗"},
    ).json()
    fighter = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 7,
            "max_hp": 7,
        },
    )
    assert fighter.status_code == 201
    enemy = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "地精",
            "entity_type": "monster",
            "initiative": 10,
            "armor_class": 15,
            "hp": 7,
            "max_hp": 7,
        },
    )
    assert enemy.status_code == 201
    ended = campaign_client.patch(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}",
        headers={"If-Match": '"1"'},
        json={"status": "ended"},
    )
    assert ended.status_code == 200
    live = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-room/live-state",
        json={"combat_id": combat["id"]},
    )
    assert live.status_code == 200

    snapshot = campaign_client.get("/api/v1/player-room/me").json()["combat"]
    assert snapshot["status"] == "ended"
    assert snapshot["active_combatant_id"] is None
    assert snapshot["is_my_turn"] is False
    assert snapshot["pending_rolls"] == []
    enemy_snapshot = next(item for item in snapshot["combatants"] if item["name"] == "地精")
    assert enemy_snapshot["armor_class"] == 15
    assert "hp" not in enemy_snapshot
