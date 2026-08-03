from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.routes.player_rooms import _clear_join_failures
from dnd_dm_assistant.application.rule_block_compiler import compile_rule_blocks_dict
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    EquipmentInstance,
    Event,
    PlayerRoom,
    PlayerSession,
    RestRecord,
    Scene,
    SceneParticipant,
    SceneToken,
    ShopInventory,
    SiteConnector,
    SiteLevel,
)
from dnd_dm_assistant.infrastructure.database.player_room_service import (
    PlayerRoomService,
    _code_digest,
)
from dnd_dm_assistant.infrastructure.database.player_service import PlayerService


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


def test_player_can_safely_switch_to_another_campaign(
    campaign_client: TestClient,
) -> None:
    campaign_a = _campaign(campaign_client, "A团")
    campaign_b = _campaign(campaign_client, "B团")
    room_a = _open(campaign_client, campaign_a["id"])
    room_b = _open(campaign_client, campaign_b["id"])
    joined_a = _join(campaign_client, room_a["join_code"])
    old_session_id = joined_a["player"]["id"]
    assert (
        campaign_client.get("/api/v1/player-room/me").json()["campaign"]["id"]
        == campaign_a["id"]
    )

    rejected = campaign_client.post(
        "/api/v1/player-room/switch",
        json={"join_code": "DXXXXX", "display_name": "玩家甲"},
    )
    assert rejected.status_code == 400
    assert (
        campaign_client.get("/api/v1/player-room/me").json()["campaign"]["id"]
        == campaign_a["id"]
    )

    switched = campaign_client.post(
        "/api/v1/player-room/switch",
        json={"join_code": room_b["join_code"], "display_name": "玩家甲"},
    )
    assert switched.status_code == 201
    assert switched.json()["campaign"]["id"] == campaign_b["id"]
    assert (
        campaign_client.get("/api/v1/player-room/me").json()["campaign"]["id"]
        == campaign_b["id"]
    )

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        old_session = session.get(PlayerSession, old_session_id)
        assert old_session is not None
        assert old_session.status == "revoked"


def test_player_equipment_is_scoped_to_bound_character(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "装备权限团")
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    own = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "自己的角色", "hp": 10, "max_hp": 10},
    ).json()
    other = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "别人的角色", "hp": 10, "max_hp": 10},
    ).json()
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": own["id"]},
    ).status_code == 200
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        own_sword = EquipmentInstance(
            campaign_id=campaign["id"],
            character_id=own["id"],
            name="长剑",
            category="weapon",
        )
        other_sword = EquipmentInstance(
            campaign_id=campaign["id"],
            character_id=other["id"],
            name="别人的长剑",
            category="weapon",
        )
        session.add_all([own_sword, other_sword])
        session.flush()
        own_id, other_id = own_sword.id, other_sword.id

    forbidden = campaign_client.post(
        "/api/v1/player-room/me/equipment/preview",
        json={
            "equipment_id": other_id,
            "operation": "equip",
            "slot": "main_hand",
        },
    )
    assert forbidden.status_code == 404
    body = {
        "equipment_id": own_id,
        "operation": "equip",
        "slot": "main_hand",
    }
    preview = campaign_client.post(
        "/api/v1/player-room/me/equipment/preview", json=body
    )
    assert preview.status_code == 200
    confirmed = campaign_client.post(
        "/api/v1/player-room/me/equipment/confirm",
        json={
            **body,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": "player-equip-001",
        },
    )
    assert confirmed.status_code == 200
    character = campaign_client.get("/api/v1/player-room/me").json()["character"]
    assert character["equipment_assets"][0]["name"] == "长剑"
    assert character["equipment_assets"][0]["slot"] == "main_hand"


def test_player_consumable_uses_quantity_instead_of_equipment_slot(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "消耗品操作团")
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "药水使用者", "hp": 8, "max_hp": 8},
    ).json()
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    ).status_code == 200
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        potion = EquipmentInstance(
            campaign_id=campaign["id"],
            character_id=character["id"],
            name="治疗药水",
            category="consumable",
            quantity=2,
            metadata_json={"healing": "2d4+2"},
        )
        session.add(potion)
        session.flush()
        potion_id = potion.id

    body = {"equipment_id": potion_id, "operation": "consume", "amount": 1}
    preview = campaign_client.post(
        "/api/v1/player-room/me/equipment/preview", json=body
    )
    assert preview.status_code == 200
    assert preview.json()["profile"]["kind"] == "consumable"
    assert preview.json()["slot"] is None
    confirmed = campaign_client.post(
        "/api/v1/player-room/me/equipment/confirm",
        json={
            **body,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": "player-consume-potion-001",
        },
    )
    assert confirmed.status_code == 200
    snapshot = campaign_client.get("/api/v1/player-room/me").json()
    asset = next(
        item for item in snapshot["character"]["equipment_assets"] if item["id"] == potion_id
    )
    assert asset["quantity"] == 1
    assert asset["profile"]["kind"] == "consumable"
    assert asset["slot"] is None

    equip = campaign_client.post(
        "/api/v1/player-room/me/equipment/preview",
        json={"equipment_id": potion_id, "operation": "equip"},
    )
    assert equip.status_code == 400
    assert "消耗品" in equip.json()["message"]


def test_player_rest_request_executes_only_after_dm_approval(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "玩家休息申请团")
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "需要休息的角色", "hp": 5, "max_hp": 10},
    ).json()
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    ).status_code == 200

    resources = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/resources",
        params={"character_id": character["id"]},
    )
    assert resources.status_code == 200
    hit_die = next(item for item in resources.json()["items"] if item["category"] == "hit_die")

    submitted = campaign_client.post(
        "/api/v1/player-room/me/action-requests",
        json={
            "action_type": "rest_request",
            "message": "申请短休。",
            "payload_json": {
                "rest_type": "short",
                "hit_dice": [{"resource_pool_id": hit_die["id"], "roll": 4}],
            },
            "idempotency_key": "player-rest-request-short",
        },
    )
    assert submitted.status_code == 201
    request = submitted.json()
    assert request["payload_json"]["rest_type"] == "short"
    assert request["payload_json"]["participants"][0]["hit_dice"] == [
        {"resource_pool_id": hit_die["id"], "roll": 4}
    ]
    assert campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()["hp"] == 5

    accepted = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-action-requests/{request['id']}/accept",
        json={"version": request["version"], "dm_note": "允许短休。"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"

    updated = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert updated["hp"] == 9

    long_request = campaign_client.post(
        "/api/v1/player-room/me/action-requests",
        json={
            "action_type": "rest_request",
            "message": "申请长休。",
            "payload_json": {"rest_type": "long"},
            "idempotency_key": "player-rest-request-long",
        },
    ).json()
    long_accepted = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-action-requests/{long_request['id']}/accept",
        json={"version": long_request["version"], "dm_note": None},
    )
    assert long_accepted.status_code == 200, long_accepted.text
    assert campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()["hp"] == 10


def test_concurrent_player_rest_approval_claims_once(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "并发休息审批团")
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "并发休息角色", "hp": 5, "max_hp": 10},
    ).json()
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    ).status_code == 200
    request = campaign_client.post(
        "/api/v1/player-room/me/action-requests",
        json={
            "action_type": "rest_request",
            "message": "申请长休。",
            "payload_json": {"rest_type": "long"},
            "idempotency_key": "player-rest-concurrent-001",
        },
    ).json()

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]

    def approve() -> dict[str, Any]:
        return PlayerService(engine).resolve_action(
            campaign["id"],
            request["id"],
            request["version"],
            "accepted",
            None,
            "concurrent-dm",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: approve(), range(2)))

    assert [item["status"] for item in results] == ["accepted", "accepted"]
    with Session(engine) as session:
        assert len(
            session.scalars(
                select(RestRecord).where(RestRecord.campaign_id == campaign["id"])
            ).all()
        ) == 1
        assert len(
            session.scalars(
                select(Event).where(
                    Event.campaign_id == campaign["id"], Event.event_type == "rest"
                )
            ).all()
        ) == 1
    assert campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()["hp"] == 10


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
    creation_context = {
        "ability_generation_method": "standard_array",
        "origin_ability_increases": {"intelligence": 2, "wisdom": 1},
        "background_tool_proficiency": "书法工具",
        "languages": ["精灵语", "龙语"],
        "starter_equipment_option": "fixed_package",
    }
    standard_array_scores = {
        "strength": 8,
        "dexterity": 14,
        "constitution": 13,
        "intelligence": 17,
        "wisdom": 13,
        "charisma": 10,
    }
    rejected_unlimited = campaign_client.post(
        "/api/v1/player-room/me/characters",
        json={
            "name": "未按规则选择",
            "race": "精灵",
            "class_name": "法师",
            "background": "学者",
            "ability_scores": standard_array_scores,
            **creation_context,
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
            "ability_scores": standard_array_scores,
            **creation_context,
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
            "ability_scores": standard_array_scores,
            **creation_context,
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
    assert "属性生成：标准数组" in character["features"]
    assert "背景起源：智力 +2、感知 +1" in character["features"]
    assert "背景专长：魔法学徒（法师）" in character["features"]
    assert {"奥秘", "历史", "调查"} <= set(character["skills"])
    assert {"法杖", "法术书", "书法工具"} <= set(character["equipment"])
    assert {"工具：书法工具", "语言：通用语", "语言：精灵语", "语言：龙语"} <= set(
        character["proficiencies"]
    )
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


def test_player_character_creation_uses_point_buy_and_fixed_starter_package(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "点购车卡团")
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    draft = {
        "name": "诺拉",
        "race": "人类",
        "class_name": "战士",
        "background": "学者",
        "ability_generation_method": "point_buy",
        "ability_scores": {
            "strength": 15,
            "dexterity": 14,
            "constitution": 13,
            "intelligence": 14,
            "wisdom": 11,
            "charisma": 8,
        },
        "origin_ability_increases": {"intelligence": 2, "wisdom": 1},
        "background_tool_proficiency": "书法工具",
        "languages": ["矮人语", "精灵语"],
        "starter_equipment_option": "fixed_package",
        "equipment": [],
        "skill_proficiencies": ["运动", "察觉"],
        "spells": [],
    }

    forged_equipment = campaign_client.post(
        "/api/v1/player-room/me/characters",
        json={**draft, "equipment": ["板甲"]},
    )
    assert forged_equipment.status_code == 400
    assert "不能在起始装备包外追加" in forged_equipment.json()["message"]

    created = campaign_client.post("/api/v1/player-room/me/characters", json=draft)
    assert created.status_code == 201
    character = created.json()
    assert character["ability_scores"]["intelligence"] == 14
    assert "属性生成：27 点购点" in character["features"]
    assert "背景起源：智力 +2、感知 +1" in character["features"]
    assert {"工具：书法工具", "语言：通用语", "语言：矮人语", "语言：精灵语"} <= set(
        character["proficiencies"]
    )
    assert {"长剑", "链甲", "法杖", "书法工具"} <= set(character["equipment"])
    assert "板甲" not in character["equipment"]


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


def test_bound_player_receives_server_filtered_fog_of_war(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "战争迷雾团")
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "探索者", "hp": 12, "max_hp": 12},
    ).json()
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "未知地下城"},
    ).json()
    cells = [
        {"row": row, "col": col, "kind": "floor", "label": "石地"}
        for row, col in ((2, 2), (3, 3), (10, 18))
    ]
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid",
        json={
            "width": 20,
            "height": 12,
            "cell_size_ft": 5,
            "mode": "exploration",
            "layers_json": {"cells": cells},
        },
    ).status_code == 201
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        session.add(
            SceneToken(
                scene_id=scene["id"],
                entity_type="character",
                entity_id=character["id"],
                label=character["name"],
                row=2,
                col=2,
            )
        )
        session.add(
            SceneToken(
                scene_id=scene["id"],
                entity_type="monster",
                entity_id="hidden-monster",
                label="远处怪物",
                row=10,
                col=18,
            )
        )
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
    public_scene = campaign_client.get("/api/v1/player-room/me").json()["table"]["scene"]
    assert public_scene["grid"]["fog_of_war"] is True
    visible_positions = {
        (cell["row"], cell["col"]) for cell in public_scene["grid"]["cells"]
    }
    assert (2, 2) in visible_positions
    assert (10, 18) not in visible_positions
    assert all(token["label"] != "远处怪物" for token in public_scene["tokens"])


def test_discovered_stairs_can_request_dm_approved_level_transition(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "楼层申请团")
    root = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{root}/characters",
        json={"name": "探路者", "class_name": "游荡者", "level": 5, "hp": 35, "max_hp": 35},
    ).json()
    preview = campaign_client.post(
        f"{root}/sites/generate/preview",
        json={
            "site_type": "dungeon",
            "name": "潮鳞巢穴",
            "brief": "蓝色潮湿的渔人地下城，由鲨华鱼人占据",
            "region_path": "深水城/海区",
            "maximum_levels": 2,
            "rooms_min": 4,
            "rooms_max": 5,
            "party_level": 5,
            "party_size": 1,
            "seed": 9917,
        },
    ).json()
    site = campaign_client.post(
        f"{root}/sites/generate/confirm",
        headers={"X-Request-ID": "stairs-flow-1"},
        json={"preview": preview},
    ).json()
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        first = session.scalar(
            select(SiteLevel).where(
                SiteLevel.site_id == site["id"], SiteLevel.level_index == 1
            )
        )
        second = session.scalar(
            select(SiteLevel).where(
                SiteLevel.site_id == site["id"], SiteLevel.level_index == 2
            )
        )
        assert first is not None and second is not None
        first_scene = session.scalar(select(Scene).where(Scene.location_id == first.location_id))
        second_scene = session.scalar(select(Scene).where(Scene.location_id == second.location_id))
        stairs = session.scalar(
            select(SiteConnector).where(
                SiteConnector.site_id == site["id"],
                SiteConnector.from_level_index == 1,
                SiteConnector.connector_type == "stairs_down",
            )
        )
        assert first_scene is not None and second_scene is not None and stairs is not None
        position = stairs.position_json
        session.add(
            SceneToken(
                scene_id=first_scene.id,
                entity_type="character",
                entity_id=character["id"],
                label=character["name"],
                row=int(position["row"]) + 1,
                col=int(position["col"]) + 1,
            )
        )
        first_scene_id = first_scene.id
        second_scene_id = second_scene.id

    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    ).status_code == 200
    assert campaign_client.post(
        f"{root}/player-room/live-state",
        json={"scene_id": first_scene_id, "combat_id": None},
    ).status_code == 200
    snapshot = campaign_client.get("/api/v1/player-room/me").json()
    transitions = snapshot["table"]["scene"]["available_transitions"]
    assert len(transitions) == 1
    transition = transitions[0]
    assert transition["target_scene_id"] == second_scene_id
    requested = campaign_client.post(
        "/api/v1/player-room/me/action-requests",
        json={
            "action_type": "site_level_transition",
            "message": "申请沿楼梯前往下一层。",
            "payload_json": {"connector_id": transition["connector_id"]},
            "idempotency_key": "stairs-request-1",
        },
    )
    assert requested.status_code == 201, requested.text
    accepted = campaign_client.post(
        f"{root}/player-action-requests/{requested.json()['id']}/accept",
        json={"version": requested.json()["version"], "dm_note": "允许换层。"},
    )
    assert accepted.status_code == 200, accepted.text
    room = campaign_client.get(f"{root}/player-room").json()
    assert room["current_scene_id"] == second_scene_id
    player_scene = campaign_client.get("/api/v1/player-room/me").json()["table"]["scene"]
    assert player_scene["id"] == second_scene_id


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


def test_room_live_state_is_idempotent_when_state_is_unchanged(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "幂等实时状态团")
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "唯一场景"},
    ).json()
    _open(campaign_client, campaign["id"])
    first = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-room/live-state",
        json={"scene_id": scene["id"]},
    )
    assert first.status_code == 200
    version = first.json()["version"]
    repeated = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/player-room/live-state",
        json={"scene_id": scene["id"], "expected_version": version},
    )
    assert repeated.status_code == 200
    assert repeated.json()["current_scene_id"] == scene["id"]
    assert repeated.json()["version"] == version


def test_open_player_room_starts_at_first_active_scene(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "首次开房默认首节点团")
    first = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "Scene 1"},
    ).json()
    second = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "Scene 5"},
    ).json()

    opened = _open(campaign_client, campaign["id"])

    assert opened["current_scene_id"] == first["id"]
    assert opened["current_scene_id"] != second["id"]


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
    assert enemy_snapshot["hp"] == 7
    assert enemy_snapshot["max_hp"] == 7
    assert enemy_snapshot["speed_ft"] == 30
    assert enemy_snapshot["ability_scores"] == {}
    assert enemy_snapshot["actions"] == []


def test_player_submitted_save_advances_enemy_turn(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "联机豁免推进团")
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "豁免玩家", "hp": 20, "max_hp": 20},
    ).json()
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "自动推进战斗"},
    ).json()
    player = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    monster = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "相位蜘蛛",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 32,
            "max_hp": 32,
            "armor_class": 13,
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
        json={"combat_id": combat["id"]},
    ).status_code == 200
    pending = campaign_client.post(
        (
            f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
            "/actions/player-rolls/pending"
        ),
        headers={"X-Request-ID": "lan-spider-save"},
        json={
            "actor_combatant_id": monster["id"],
            "actor_version": monster["version"],
            "target_combatant_id": player["id"],
            "target_version": player["version"],
            "action_name": "毒牙",
            "resolution_type": "saving_throw",
            "dc": 11,
            "ability": "constitution",
            "damage_on_failure": 7,
            "damage_on_success": 3,
            "damage_type": "poison",
        },
    )
    assert pending.status_code == 200
    action = pending.json()["action"]
    pending_snapshot = campaign_client.get("/api/v1/player-room/me").json()["combat"]
    prompt = pending_snapshot["pending_rolls"][0]
    assert prompt["actor_combatant_id"] == monster["id"]
    assert prompt["actor_name"] == "相位蜘蛛"
    assert prompt["target_combatant_id"] == player["id"]
    assert prompt["target_name"] == "豁免玩家"
    assert prompt["damage_on_failure"] == 7
    assert prompt["damage_on_success"] == 3
    assert prompt["damage_type"] == "poison"
    submitted = campaign_client.post(
        f"/api/v1/player-room/me/combat/player-rolls/{action['id']}",
        json={
            "action_version": action["version"],
            "roll_total": 9,
            "idempotency_key": "lan-player-save-001",
        },
    )
    assert submitted.status_code == 200, submitted.json()
    assert submitted.json()["turn_advance"]["active_combatant"]["id"] == player["id"]
    snapshot = campaign_client.get("/api/v1/player-room/me").json()["combat"]
    assert snapshot["active_combatant_id"] == player["id"]
    assert snapshot["is_my_turn"] is True
    assert snapshot["pending_rolls"] == []


def test_active_monster_action_preview_uses_structured_damage_action() -> None:
    action = PlayerRoomService._active_monster_action(
        [
            {"name": "无法自动猜测", "description": "需要 DM 裁定"},
            {"name": "毒牙", "damage": "2d8", "damage_type": "poison"},
        ],
        round_number=0,
        snapshot={},
    )
    assert action is not None
    assert action["name"] == "毒牙"


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
            "layers_json": {
                "cells": [
                    {
                        "row": 5,
                        "col": 2,
                        "kind": "cover",
                        "label": "落地石屏风",
                        "blocks_sight": True,
                    }
                ]
            },
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
    hidden_enemy = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "石屏风后的假人",
            "entity_type": "monster",
            "initiative": 1,
            "armor_class": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": 8, "col": 2},
                "ability_scores": {"dexterity": 10},
            },
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
        json={"scene_id": scene["id"], "combat_id": combat["id"]},
    ).status_code == 200

    blocked_by_sight = campaign_client.post(
        "/api/v1/player-room/me/combat/attack",
        json={
            "target_combatant_id": hidden_enemy["id"],
            "target_combatant_ids": [hidden_enemy["id"]],
            "action_name": "火球术",
            "attack_total": 0,
            "damage_total": 28,
            "idempotency_key": "line-of-sight-regression-1",
        },
    )
    assert blocked_by_sight.status_code == 400
    assert any(
        phrase in blocked_by_sight.json()["message"]
        for phrase in ("目标处于战争迷雾中", "无法建立攻击视线")
    )

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
    assert any(
        phrase in too_far.json()["message"]
        for phrase in ("技能范围", "目标处于战争迷雾中")
    )
    for index, position in enumerate(((2, 8), (2, 9), (3, 10))):
        moved = campaign_client.patch(
            f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants/"
            f"{enemies[index]['id']}",
            headers={"If-Match": f'"{enemies[index]["version"]}"'},
            json={
                "snapshot_json": {
                    **enemies[index]["snapshot_json"],
                    "grid_position": {"row": position[0], "col": position[1]},
                }
            },
        )
        assert moved.status_code == 200
        enemies[index] = moved.json()

    resolved = campaign_client.post(
        "/api/v1/player-room/me/combat/attack",
        json={
            "target_combatant_id": enemies[0]["id"],
            "target_combatant_ids": [item["id"] for item in enemies],
            "action_name": "火球术",
            "attack_total": 0,
            "damage_total": 28,
            "end_turn_after": True,
            "idempotency_key": "fireball-area-regression-1",
        },
    )
    assert resolved.status_code == 200, resolved.json()
    assert resolved.json()["target_count"] == 3
    assert len(resolved.json()["results"]) == 3
    assert resolved.json()["turn_advance"]["active_combatant"]["entity_type"] == "monster"
    updated = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants"
    ).json()["items"]
    updated_actor = next(item for item in updated if item["id"] == actor["id"])
    affected_ids = {item["id"] for item in enemies}
    updated_enemies = [item for item in updated if item["id"] in affected_ids]
    assert updated_actor["action_available"] is False
    assert all(item["hp"] in {43, 57} for item in updated_enemies)
    refreshed_character = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert refreshed_character["resources"]["spell_slots_3"]["current"] == 2


def test_player_shop_is_visible_only_in_current_scene_and_purchase_is_bound_to_character(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "玩家商店入口团")
    root = f"/api/v1/campaigns/{campaign['id']}"
    location = campaign_client.post(
        f"{root}/locations", json={"name": "长桥市场", "depth": 1}
    ).json()
    current_scene = campaign_client.post(
        f"{root}/scenes", json={"name": "月灯杂货铺", "location_id": location["id"]}
    ).json()
    other_scene = campaign_client.post(
        f"{root}/scenes", json={"name": "市场后巷", "location_id": location["id"]}
    ).json()
    opened = _open(campaign_client, campaign["id"])
    _join(campaign_client, opened["join_code"])
    character = campaign_client.post(
        f"{root}/characters",
        json={
            "name": "商店测试角色",
            "class_name": "战士",
            "ability_scores": {"strength": 10},
            "hp": 10,
            "max_hp": 10,
        },
    ).json()
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    ).status_code == 200
    wallet = campaign_client.post(
        f"{root}/characters/assets/wallets",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "copper": 100,
        },
    ).json()
    other_character = campaign_client.post(
        f"{root}/characters",
        json={"name": "别人的钱包", "hp": 10, "max_hp": 10},
    ).json()
    other_wallet = campaign_client.post(
        f"{root}/characters/assets/wallets",
        json={
            "character_id": other_character["id"],
            "character_version": other_character["version"],
            "copper": 100,
        },
    ).json()

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        current_npc = NPC(
            campaign_id=campaign["id"],
            name="月灯老板",
            description="只向眼前的客人展示货架。",
        )
        other_npc = NPC(
            campaign_id=campaign["id"], name="后巷商人", description="另一处货架。"
        )
        session.add_all([current_npc, other_npc])
        session.flush()
        session.add_all(
            [
                SceneParticipant(
                    scene_id=current_scene["id"],
                    entity_type="npc",
                    entity_id=current_npc.id,
                    role="merchant",
                    visible=True,
                ),
                SceneParticipant(
                    scene_id=other_scene["id"],
                    entity_type="npc",
                    entity_id=other_npc.id,
                    role="merchant",
                    visible=True,
                ),
                ShopInventory(
                    campaign_id=campaign["id"],
                    name="治疗药水",
                    quantity=2,
                    price_copper=25,
                    metadata_json={
                        "merchant_id": "current-shop",
                        "merchant_name": current_npc.name,
                        "merchant_npc_id": current_npc.id,
                        "scene_id": current_scene["id"],
                        "category": "potion",
                    },
                ),
                ShopInventory(
                    campaign_id=campaign["id"],
                    name="后巷卷轴",
                    quantity=2,
                    price_copper=25,
                    metadata_json={
                        "merchant_id": "other-shop",
                        "merchant_name": other_npc.name,
                        "merchant_npc_id": other_npc.id,
                        "scene_id": other_scene["id"],
                        "category": "scroll",
                    },
                ),
            ]
        )

    snapshot = campaign_client.get("/api/v1/player-room/me").json()
    assert snapshot["table"]["shops"][0]["name"] == "月灯老板"
    assert [item["name"] for item in snapshot["table"]["shops"][0]["stock"]] == ["治疗药水"]
    assert snapshot["character"]["wallet"]["id"] == wallet["id"]
    stock = snapshot["table"]["shops"][0]["stock"][0]
    trade = {
        "wallet_id": wallet["id"],
        "wallet_version": snapshot["character"]["wallet"]["version"],
        "shop_inventory_id": stock["id"],
        "shop_version": stock["version"],
        "quantity": 1,
    }
    preview = campaign_client.post("/api/v1/player-room/me/commerce/preview", json=trade)
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_copper"] == 25
    confirmed = campaign_client.post(
        "/api/v1/player-room/me/commerce/confirm",
        json={
            **trade,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": "player-shop-001",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    after = campaign_client.get("/api/v1/player-room/me").json()
    assert after["character"]["wallet"]["copper"] == 75
    assert after["table"]["shops"][0]["stock"][0]["quantity"] == 1
    assert any(item["name"] == "治疗药水" for item in after["character"]["equipment_assets"])
    forged = campaign_client.post(
        "/api/v1/player-room/me/commerce/preview",
        json={
            **trade,
            "wallet_id": other_wallet["id"],
            "wallet_version": other_wallet["version"],
        },
    )
    assert forged.status_code == 400
    assert "绑定角色" in forged.json()["message"]


def test_player_attack_applies_half_cover_to_target_ac(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "联机掩体规则团")
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "掩体测试员",
            "hp": 20,
            "max_hp": 20,
            "actions": [
                {
                    "name": "短弓",
                    "cost": "动作",
                    "range": "30尺",
                    "damage": "1d6穿刺",
                    "damage_type": "穿刺",
                }
            ],
        },
    ).json()
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "有掩体的靶场"},
    ).json()
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid",
        json={
            "width": 10,
            "height": 6,
            "cell_size_ft": 5,
            "mode": "combat",
            "layers_json": {"cells": []},
        },
    ).status_code == 201
    cover = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/objects",
        json={
            "object_type": "cover",
            "label": "半身高木箱",
            "row": 2,
            "col": 4,
            "state": "active",
            "visibility": "public",
        },
    )
    assert cover.status_code == 201, cover.text
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "掩体规则战斗", "scene_id": scene["id"]},
    ).json()
    campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 2, "col": 2}},
        },
    ).json()
    target = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "木箱后的靶人",
            "entity_type": "monster",
            "initiative": 10,
            "armor_class": 12,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 2, "col": 5}},
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
        json={"scene_id": scene["id"], "combat_id": combat["id"]},
    ).status_code == 200

    attack = campaign_client.post(
        "/api/v1/player-room/me/combat/attack",
        json={
            "target_combatant_id": target["id"],
            "action_name": "短弓",
            "attack_total": 13,
            "damage_total": 6,
            "idempotency_key": "half-cover-attack-001",
        },
    )
    assert attack.status_code == 200, attack.text
    result = attack.json()["results"][0]
    assert "半掩体 +2" in result["action"]["summary"]
    current_target = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants"
    ).json()["items"]
    assert next(item for item in current_target if item["id"] == target["id"])["hp"] == 20


def test_player_compound_damage_is_one_lifecycle_event(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "复合伤害生命周期团")
    compound_plan = compile_rule_blocks_dict(
        {
            "name": "元素裂解",
            "range": "30尺",
            "damage_components": [
                {"expression": "1d1", "damage_type": "火焰", "damage_tags": ["nonmagical"]},
                {"expression": "1d1", "damage_type": "寒冷"},
            ],
            "resolution_kind": "damage",
        },
        source_kind="spell",
    )
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "复合伤害施法者",
            "hp": 20,
            "max_hp": 20,
            "actions": [
                {
                    "name": "元素裂解",
                    "cost": "动作",
                    "range": "30尺",
                    "damage_components": [
                        {"expression": "1d1", "damage_type": "火焰", "damage_tags": ["nonmagical"]},
                        {"expression": "1d1", "damage_type": "寒冷"},
                    ],
                    "rule_plan": compound_plan,
                }
            ],
        },
    ).json()
    damage_ids = [
        block["id"]
        for block in compound_plan["blocks"]
        if block["kind"] == "damage"
    ]
    assert len(damage_ids) == 2
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "复合伤害靶场"},
    ).json()
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 5, "cell_size_ft": 5, "mode": "combat"},
    ).status_code == 201
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "复合伤害战斗", "scene_id": scene["id"]},
    ).json()
    _actor = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 3, "col": 2}},
        },
    ).json()
    target = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "复合伤害目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 2,
            "max_hp": 2,
            "snapshot_json": {
                "grid_position": {"row": 3, "col": 3},
                "conditional_damage_defenses": [
                    {
                        "id": "nonmagical-fire-resistance",
                        "condition": "nonmagical",
                        "operation": "resistance",
                        "damage_types": ["fire"],
                    }
                ],
            },
            "damage_vulnerabilities": ["cold"],
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
        json={"scene_id": scene["id"], "combat_id": combat["id"]},
    ).status_code == 200

    attack = campaign_client.post(
        "/api/v1/player-room/me/combat/attack",
        json={
            "target_combatant_id": target["id"],
            "action_name": "元素裂解",
            "attack_total": 20,
            "damage_total": 2,
            "damage_component_totals": {damage_ids[0]: 1, damage_ids[1]: 1},
            "idempotency_key": "compound-lifecycle-001",
        },
    )
    assert attack.status_code == 200, attack.text
    body = attack.json()
    assert len(body["results"]) == 1
    result = body["results"][0]["action"]["result_json"]
    assert result["damage_type"] == "mixed"
    assert [item["adjusted_damage"] for item in result["damage_components"]] == [0, 2]
    assert result["damage_components"][0]["damage_tags"] == ["nonmagical"]
    assert result["condition_changes"] == ["added:unconscious"]
    assert body["results"][0]["death_save"]["failures"] == 0

    public_snapshot = campaign_client.get("/api/v1/player-room/me").json()["combat"]
    public_entry = next(
        item for item in public_snapshot["log"] if item["id"] == body["results"][0]["action"]["id"]
    )
    assert [
        (item["damage_type"], item["original_damage"], item["adjusted_damage"])
        for item in public_entry["damage_components"]
    ] == [("fire", 1, 0), ("cold", 1, 2)]


def test_player_compiled_forced_movement_is_applied_after_failed_save(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "雷鸣波规则执行团")
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "雷鸣波施法者",
            "class_name": "法师",
            "hp": 20,
            "max_hp": 20,
            "actions": [
                {
                    "name": "雷鸣波",
                    "cost": "动作",
                    "range": "自身（15尺立方）",
                    "damage": "2d8雷鸣",
                    "damage_type": "雷鸣",
                    "save_ability": "constitution",
                    "save_dc": 99,
                    "rule_plan": compile_rule_blocks_dict(
                        {
                            "name": "雷鸣波",
                            "spell_level": 1,
                            "range": "自身（15尺立方）",
                            "description": (
                                "以你为源点15尺立方区域内的每个生物进行体质豁免，"
                                "失败受到2d8雷鸣伤害并被推离10尺。"
                            ),
                            "damage_expression": "2d8",
                            "damage_type": "雷鸣",
                            "save_ability": "constitution",
                            "save_dc": 99,
                            "movement": {
                                "distance_ft": 10,
                                "type": "forced",
                                "direction": "away",
                            },
                            "resolution_kind": "damage",
                        },
                        source_kind="spell",
                    ),
                }
            ],
        },
    ).json()
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "雷鸣波测试场"},
    ).json()
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid",
        json={"width": 10, "height": 10, "cell_size_ft": 5, "mode": "combat"},
    ).status_code == 201
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "雷鸣波战斗", "scene_id": scene["id"]},
    ).json()
    campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 5, "col": 5}},
        },
    ).json()
    target = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "雷鸣波目标",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": 5, "col": 6},
                "ability_scores": {"constitution": 10},
            },
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
        json={"scene_id": scene["id"], "combat_id": combat["id"]},
    ).status_code == 200

    attack = campaign_client.post(
        "/api/v1/player-room/me/combat/attack",
        json={
            "target_combatant_id": target["id"],
            "target_combatant_ids": [target["id"]],
            "action_name": "雷鸣波",
            "attack_total": 0,
            "damage_total": 8,
            "idempotency_key": "thunderwave-forced-movement-001",
        },
    )
    assert attack.status_code == 200, attack.text
    compiled = attack.json()["compiled_effects"]
    movement = next(item for item in compiled if item["block_id"].endswith("move"))
    assert movement["result"]["moved_ft"] == 10
    fighters = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants"
    ).json()["items"]
    moved_target = next(item for item in fighters if item["id"] == target["id"])
    assert moved_target["snapshot_json"]["grid_position"] == {"row": 5, "col": 8}
    assert moved_target["hp"] == 12


def test_player_cast_applies_friendly_modifier_and_spends_slot(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "友方战斗法术团")
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "增益施法者",
            "class_name": "法师",
            "hp": 20,
            "max_hp": 20,
            "actions": [
                {
                    "name": "护盾术",
                    "spell_level": 1,
                    "cost": "反应",
                    "range": "自身",
                    "resource_key": "spell_slots_1",
                    "resource_cost": 1,
                    "rule_plan": compile_rule_blocks_dict(
                        {
                            "name": "护盾术",
                            "spell_level": 1,
                            "range": "自身",
                            "description": "你的AC提高5，持续到你的下个回合开始。",
                            "resolution_kind": "modifier",
                        },
                        source_kind="spell",
                    ),
                }
            ],
            "resources": {
                "spell_slots_1": {"label": "1环法术位", "current": 1, "maximum": 1}
            },
        },
    ).json()
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes",
        json={"name": "友方效果测试场"},
    ).json()
    assert campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 8, "cell_size_ft": 5, "mode": "combat"},
    ).status_code == 201
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "友方效果战斗", "scene_id": scene["id"]},
    ).json()
    actor = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 4, "col": 4}},
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
        json={"scene_id": scene["id"], "combat_id": combat["id"]},
    ).status_code == 200

    cast = campaign_client.post(
        "/api/v1/player-room/me/combat/cast",
        json={
            "target_combatant_id": actor["id"],
            "target_combatant_ids": [actor["id"]],
            "action_name": "护盾术",
            "slot_level": 1,
            "idempotency_key": "friendly-shield-cast-001",
        },
    )
    assert cast.status_code == 200, cast.text
    assert cast.json()["compiled_effects"]
    assert cast.json()["resource_spend"] == {
        "resource_key": "spell_slots_1",
        "amount": 1,
    }
    current = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants"
    ).json()["items"]
    updated_actor = next(item for item in current if item["id"] == actor["id"])
    assert updated_actor["action_available"] is True
    assert updated_actor["reaction_available"] is False
    assert updated_actor["armor_class"] == 15
    refreshed_character = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    # A level-1 wizard is normalized to the 2024 core two-slot progression;
    # this cast spends one of those two slots.
    assert refreshed_character["resources"]["spell_slots_1"]["current"] == 1
