from __future__ import annotations

from fastapi.testclient import TestClient


def test_player_movement_enforces_remaining_distance_obstacles_and_sync(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "联机移动验收"}
    ).json()
    campaign_id = campaign["id"]
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/characters",
        json={
            "name": "移动玩家",
            "race": "人类",
            "class_name": "战士",
            "background": "士兵",
            "speed": 30,
            "hp": 10,
            "max_hp": 10,
            "ability_scores": {"strength": 14, "dexterity": 14, "constitution": 12},
        },
    ).json()
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes",
        json={"name": "有墙的战术场景"},
    ).json()
    grid = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes/{scene['id']}/grid",
        json={
            "width": 20,
            "height": 12,
            "cell_size_ft": 5,
            "mode": "combat",
            "public_description": "训练场",
            "layers_json": {"cells": []},
        },
    )
    assert grid.status_code == 201
    wall = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes/{scene['id']}/objects",
        json={
            "object_type": "wall",
            "label": "中央墙壁",
            "row": 5,
            "col": 3,
            "width_cells": 1,
            "height_cells": 2,
            "state": "active",
            "visibility": "public",
        },
    )
    assert wall.status_code == 201
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats",
        json={"name": "移动规则战斗", "scene_id": scene["id"]},
    ).json()
    fighter_response = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 30,
            "hp": 10,
            "max_hp": 10,
            "speed_ft": 30,
            "movement_remaining_ft": 10,
            "snapshot_json": {"grid_position": {"row": 5, "col": 2}},
        },
    )
    assert fighter_response.status_code == 201, fighter_response.text
    enemy = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": "训练假人",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 10,
            "max_hp": 10,
                "snapshot_json": {"grid_position": {"row": 1, "col": 20}},
        },
    )
    assert enemy.status_code == 201
    opened = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/player-room/open", json={"hours": 4}
    ).json()
    player_a = TestClient(campaign_client.app)
    player_b = TestClient(campaign_client.app)
    try:
        for client, name in ((player_a, "移动玩家浏览器"), (player_b, "旁观浏览器")):
            joined = client.post(
                "/api/v1/player-room/join",
                json={"join_code": opened["join_code"], "display_name": name},
            )
            assert joined.status_code == 201, joined.text
        assert player_a.post(
            "/api/v1/player-room/me/bind-character",
            json={"character_id": character["id"]},
        ).status_code == 200
        assert player_b.get("/api/v1/player-room/me").json()["character"] is None
        assert campaign_client.post(
            f"/api/v1/campaigns/{campaign_id}/player-room/live-state",
            json={"scene_id": scene["id"], "combat_id": combat["id"]},
        ).status_code == 200

        initial = player_a.get("/api/v1/player-room/me").json()["combat"]
        assert initial["is_my_turn"] is True
        assert all(item["name"] != "训练假人" for item in initial["combatants"])
        current = next(
            item for item in initial["combatants"] if item["id"] == initial["own_combatant_id"]
        )
        blocked = player_a.post(
            "/api/v1/player-room/me/combat/move",
            json={
                "row": 5,
                "col": 4,
                "combatant_version": current["version"],
            },
        )
        assert blocked.status_code == 400
        assert "阻挡" in str(blocked.json())

        legal = player_a.post(
            "/api/v1/player-room/me/combat/move",
            json={
                "row": 4,
                "col": 2,
                "combatant_version": current["version"],
            },
        )
        assert legal.status_code == 200, legal.text
        assert legal.json()["movement_remaining_ft"] == 5
        after_legal = player_a.get("/api/v1/player-room/me").json()["combat"]
        moved = next(
            item
            for item in after_legal["combatants"]
            if item["id"] == after_legal["own_combatant_id"]
        )
        assert moved["position"] == {"row": 4, "col": 2}
        assert moved["movement_remaining_ft"] == 5
        shared = player_b.get("/api/v1/player-room/me").json()["combat"]
        assert shared is not None
        assert next(item for item in shared["combatants"] if item["entity_type"] == "character")[
            "position"
        ] == {"row": 4, "col": 2}

        dodged = player_a.post(
            "/api/v1/player-room/me/combat/maneuver",
            json={
                "action_type": "dodge",
                "actor_version": moved["version"],
                "idempotency_key": "player-dodge-001",
            },
        )
        assert dodged.status_code == 200, dodged.text
        assert dodged.json()["action"]["action_type"] == "dodge"
        after_dodge = player_a.get("/api/v1/player-room/me").json()["combat"]
        dodging = next(
            item
            for item in after_dodge["combatants"]
            if item["id"] == after_dodge["own_combatant_id"]
        )
        assert dodging["action_available"] is False
        assert "闪避" in dodging["conditions"]
        assert any("闪避" in effect["name"] for effect in dodging["active_effects"])

        too_far = player_a.post(
            "/api/v1/player-room/me/combat/move",
            json={
                "row": 1,
                "col": 2,
                "combatant_version": dodging["version"],
            },
        )
        assert too_far.status_code == 400
        assert "超出本回合剩余移动范围" in str(too_far.json())
    finally:
        player_a.close()
        player_b.close()


def test_leaving_melee_range_creates_dm_opportunity_request_and_resolves_attack(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "借机攻击触发链路"}
    ).json()
    campaign_id = campaign["id"]
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/characters",
        json={"name": "撤离者", "class_name": "战士", "hp": 10, "max_hp": 10},
    ).json()
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats", json={"name": "借机战斗"}
    ).json()
    actor = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": "撤离者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {"grid_position": {"row": 2, "col": 2}},
        },
    ).json()
    enemy = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": "近战守卫",
            "entity_type": "monster",
            "initiative": 10,
            "armor_class": 12,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 3},
                "actions": [{"name": "长剑", "damage": "1d8+3", "damage_type": "slashing"}],
            },
        },
    ).json()
    opened = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/player-room/open", json={"hours": 4}
    ).json()
    player = TestClient(campaign_client.app)
    try:
        joined = player.post(
            "/api/v1/player-room/join",
            json={"join_code": opened["join_code"], "display_name": "撤离者客户端"},
        )
        assert joined.status_code == 201, joined.text
        assert player.post(
            "/api/v1/player-room/me/bind-character",
            json={"character_id": character["id"]},
        ).status_code == 200
        assert campaign_client.post(
            f"/api/v1/campaigns/{campaign_id}/player-room/live-state",
            json={"combat_id": combat["id"]},
        ).status_code == 200

        moved = player.post(
            "/api/v1/player-room/me/combat/move",
            json={
                "row": 2,
                "col": 5,
                "combatant_version": actor["version"],
            },
        )
        assert moved.status_code == 200, moved.text

        requests = campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/player-action-requests?status=pending"
        ).json()["items"]
        opportunity = next(
            item for item in requests if item["action_type"] == "opportunity_attack"
        )
        assert opportunity["payload_json"]["source_combatant_id"] == enemy["id"]
        assert opportunity["payload_json"]["target_combatant_id"] == actor["id"]

        resolved = campaign_client.post(
            f"/api/v1/campaigns/{campaign_id}/player-action-requests/{opportunity['id']}/accept",
            json={
                "version": opportunity["version"],
                "attack_total": 15,
                "damage_total": 6,
                "dm_note": "守卫确认使用长剑借机攻击",
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "accepted"
        assert resolved.json()["payload_json"]["hit"] is True
        current_enemy = campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants/{enemy['id']}"
        ).json()
        current_actor = campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants/{actor['id']}"
        ).json()
        assert current_enemy["reaction_available"] is False
        assert current_actor["hp"] == 4
    finally:
        player.close()
