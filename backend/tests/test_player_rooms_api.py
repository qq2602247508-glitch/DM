from __future__ import annotations

import hashlib
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.routes.player_rooms import _clear_join_failures
from dnd_dm_assistant.infrastructure.database.models import PlayerRoom, PlayerSession
from dnd_dm_assistant.infrastructure.database.player_room_service import _code_digest


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
    assert len(code) == 6
    assert code.startswith("D")
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


def test_legacy_unprefixed_six_character_room_code_still_joins(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client)
    _open(campaign_client, campaign["id"])
    legacy_code = "7HJK29"

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        room = session.scalar(select(PlayerRoom).where(PlayerRoom.campaign_id == campaign["id"]))
        assert room is not None
        room.join_code_hash = _code_digest(legacy_code, room.join_code_salt)
        room.join_code_hint = legacy_code[-2:]

    joined = _join(campaign_client, legacy_code.lower())
    assert joined["campaign"]["id"] == campaign["id"]


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
        "cells": [
            {"row": 1, "col": 1, "kind": "wall", "label": "酒馆外墙"},
            {"row": 2, "col": 2, "kind": "cover", "label": "木制吧台"},
        ],
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


def test_noncombat_lockpick_uses_raw_roll_and_dm_confirmation(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "非战斗规则团")
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "洛克",
            "class_name": "游荡者",
            "level": 3,
            "hp": 20,
            "max_hp": 20,
            "ability_scores": {
                "strength": 8,
                "dexterity": 16,
                "constitution": 12,
                "intelligence": 14,
                "wisdom": 10,
                "charisma": 13,
            },
            "skills": {"巧手": {"proficient": True}},
        },
    ).json()
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "锁住的酒馆后门"},
    ).json()
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid",
        json={
            "width": 8,
            "height": 6,
            "cell_size_ft": 5,
            "mode": "exploration",
            "layers_json": {"cells": [{"row": 2, "col": 3, "kind": "door"}]},
        },
    ).status_code == 201
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/tokens",
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "label": character["name"],
            "row": 2,
            "col": 2,
        },
    ).status_code == 201
    door = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/objects",
        json={
            "object_type": "door",
            "label": "后门铁锁",
            "row": 2,
            "col": 3,
            "state": "closed",
            "visibility": "public",
            "interaction_json": {"action": "lockpick", "locked": True, "dc": 15},
        },
    ).json()
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    ).status_code == 200
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-room/live-state",
        json={"scene_id": scene["id"]},
    ).status_code == 200

    dm_snapshot = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/player-room/dm/noncombat-actions/"
        f"{character['id']}"
    )
    assert dm_snapshot.status_code == 200
    assert any(
        action["id"] == "tool:thieves_tools"
        for action in dm_snapshot.json()["available_actions"]
    )
    dm_planned = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-room/dm/noncombat-actions/plan",
        json={
            "character_id": character["id"],
            "action_id": "tool:thieves_tools",
            "target_type": "object",
            "target_id": door["id"],
            "message": "DM 代玩家尝试后门铁锁。",
            "idempotency_key": "dm-lockpick-plan-1",
        },
    )
    assert dm_planned.status_code == 200
    dm_request = dm_planned.json()
    assert dm_request["payload_json"]["actor"]["id"] == character["id"]
    dm_rolled = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-room/dm/noncombat-actions/"
        f"{dm_request['id']}/roll",
        json={
            "character_id": character["id"],
            "version": dm_request["version"],
            "raw_roll": 1,
        },
    )
    assert dm_rolled.status_code == 200
    assert dm_rolled.json()["payload_json"]["resolution"]["raw_roll"] == 1
    rejected = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-action-requests/"
        f"{dm_request['id']}/reject",
        json={"version": dm_rolled.json()["version"], "dm_note": "仅用于回归测试。"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    snapshot = campaign_client.get("/api/v1/player-room/me").json()
    token = snapshot["table"]["scene"]["tokens"][0]
    assert token["entity_type"] == "character"
    assert token["entity_id"] == character["id"]
    assert any(
        action["id"] == "tool:thieves_tools"
        for action in snapshot["table"]["noncombat"]["available_actions"]
    )
    planned = campaign_client.post(
        "/api/v1/player-room/me/noncombat-actions/plan",
        json={
            "action_id": "tool:thieves_tools",
            "target_type": "object",
            "target_id": door["id"],
            "message": "我用盗贼工具撬开后门。",
            "idempotency_key": "lockpick-plan-1",
        },
    )
    assert planned.status_code == 201
    request = planned.json()
    resolution = request["payload_json"]["resolution"]
    assert resolution["modifier"] == 5
    assert resolution["dc"] == 15
    rolled = campaign_client.post(
        f"/api/v1/player-room/me/noncombat-actions/{request['id']}/roll",
        json={"version": request["version"], "raw_roll": 10},
    )
    assert rolled.status_code == 200
    resolved = rolled.json()
    assert resolved["payload_json"]["resolution"]["total"] == 15
    assert resolved["payload_json"]["resolution"]["success"] is True
    accepted = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-action-requests/{request['id']}/accept",
        json={"version": resolved["version"], "dm_note": "锁舌弹开。"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["payload_json"]["phase"] == "dm_confirmed"
    grid = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid"
    ).json()
    updated_door = next(item for item in grid["objects"] if item["id"] == door["id"])
    assert updated_door["state"] == "open"
    shared = campaign_client.get("/api/v1/player-room/me").json()["table"]["shared_log"]
    assert shared[0]["event_type"] == "player_noncombat_action"


def test_player_area_spell_uses_one_damage_roll_and_spends_one_slot(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "联机区域法术团")
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "区域法术验收员",
            "class_name": "法师",
            "level": 12,
            "hp": 70,
            "max_hp": 70,
            "actions": [
                {
                    "name": "火球术",
                    "cost": "动作",
                    "range": "150尺，20尺半径球形",
                    "damage": "8d6火焰",
                    "save_ability": "dexterity",
                    "save_dc": 17,
                    "half_damage_on_save": True,
                    "resource_key": "spell_slots_3",
                    "resource_cost": 1,
                },
                {
                    "name": "闪电束",
                    "cost": "动作",
                    "range": "100尺直线，5尺宽",
                    "damage": "8d6闪电",
                    "save_ability": "dexterity",
                    "save_dc": 17,
                    "half_damage_on_save": True,
                    "resource_key": "spell_slots_3",
                    "resource_cost": 1,
                },
            ],
            "resources": {
                "spell_slots_3": {"label": "3环法术位", "current": 3, "maximum": 3}
            },
        },
    ).json()
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "法术范围试验场"},
    ).json()
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid",
        json={
            "width": 30,
            "height": 10,
            "cell_size_ft": 5,
            "mode": "combat",
            "layers_json": {"cells": []},
        },
    ).status_code == 201
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "区域法术战斗", "scene_id": scene["id"]},
    ).json()
    actor = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "armor_class": 15,
            "hp": 70,
            "max_hp": 70,
            "snapshot_json": {"grid_position": {"row": 2, "col": 2}},
        },
    ).json()
    enemies: list[dict[str, Any]] = []
    for index, (row, col) in enumerate(((2, 20), (2, 21), (3, 25)), start=1):
        response = campaign_client.post(
            f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
            json={
                "display_name": f"夺心魔{index}",
                "entity_type": "monster",
                "initiative": 10 - index,
                "armor_class": 15,
                "hp": 71,
                "max_hp": 71,
                "snapshot_json": {
                    "grid_position": {"row": row, "col": col},
                    "ability_scores": {"dexterity": 12},
                },
            },
        )
        assert response.status_code == 201
        enemies.append(response.json())
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    ).status_code == 200
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-room/live-state",
        json={"scene_id": scene["id"], "combat_id": combat["id"]},
    ).status_code == 200

    too_far = campaign_client.post(
        "/api/v1/player-room/me/combat/attack",
        json={
            "target_combatant_id": enemies[0]["id"],
            "target_combatant_ids": [enemies[0]["id"], enemies[1]["id"], enemies[2]["id"]],
            "action_name": "闪电束",
            "attack_total": 0,
            "damage_total": 28,
            "idempotency_key": "line-range-regression-1",
        },
    )
    assert too_far.status_code == 400
    assert "技能范围" in too_far.json()["message"]
    moved_third = campaign_client.patch(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants/"
        f"{enemies[2]['id']}",
        headers={"If-Match": f'"{enemies[2]["version"]}"'},
        json={
            "snapshot_json": {
                **enemies[2]["snapshot_json"],
                "grid_position": {"row": 3, "col": 20},
            }
        },
    )
    assert moved_third.status_code == 200
    enemies[2] = moved_third.json()

    resolved = campaign_client.post(
        "/api/v1/player-room/me/combat/attack",
        json={
            "target_combatant_id": enemies[0]["id"],
            "target_combatant_ids": [item["id"] for item in enemies],
            "action_name": "火球术",
            "attack_total": 0,
            "damage_total": 28,
            "idempotency_key": "fireball-area-regression-1",
        },
    )
    assert resolved.status_code == 200, resolved.json()
    assert resolved.json()["target_count"] == 3
    assert len(resolved.json()["results"]) == 3
    updated = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants"
    ).json()["items"]
    updated_actor = next(item for item in updated if item["id"] == actor["id"])
    updated_enemies = [item for item in updated if item["entity_type"] == "monster"]
    assert updated_actor["action_available"] is False
    assert all(item["hp"] in {43, 57} for item in updated_enemies)
    refreshed_character = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert refreshed_character["resources"]["spell_slots_3"]["current"] == 2
