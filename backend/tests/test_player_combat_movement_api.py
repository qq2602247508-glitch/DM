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
                "actions": [
                    {
                        "name": "短弓",
                        "damage": "1d6",
                        "damage_type": "piercing",
                        "range_ft": 80,
                        "attack_type": "ranged",
                    },
                    {
                        "name": "长剑",
                        "damage": "1d8+3",
                        "damage_type": "slashing",
                        "range_ft": 5,
                        "attack_type": "melee",
                    },
                ],
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
        assert opportunity["payload_json"]["source_action_name"] == "长剑"
        assert opportunity["payload_json"]["reaction_trigger"] == (
            "撤离者 离开 近战守卫 的近战威胁范围"
        )

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


def test_structured_player_escape_auto_resolves_opportunity_attack(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "自动借机攻击"}).json()
    campaign_id = campaign["id"]
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/characters",
        json={"name": "自动撤离者", "class_name": "战士", "hp": 10, "max_hp": 10},
    ).json()
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats", json={"name": "自动借机战斗"}
    ).json()
    actor = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 2},
                "actions": [
                    {
                        "name": "短剑",
                        "damage": "1d1",
                        "damage_type": "piercing",
                        "range_ft": 5,
                        "attack_type": "melee",
                        "attack_bonus": 100,
                    }
                ],
            },
        },
    ).json()
    enemy = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": "结构化守卫",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 3},
                "actions": [
                    {
                        "name": "长剑",
                        "damage_expression": "1d1",
                        "damage_type": "slashing",
                        "range_ft": 5,
                        "attack_type": "melee",
                        "action_type": "reaction",
                        "attack_bonus": 100,
                    }
                ],
            },
        },
    ).json()
    opened = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/player-room/open", json={"hours": 4}
    ).json()
    player = TestClient(campaign_client.app)
    try:
        assert player.post(
            "/api/v1/player-room/join",
            json={"join_code": opened["join_code"], "display_name": "自动撤离客户端"},
        ).status_code == 201
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
            json={"row": 2, "col": 5, "combatant_version": actor["version"]},
        )
        assert moved.status_code == 200, moved.text
        body = moved.json()
        assert len(body["automatic_opportunity_attacks"]) == 1
        assert body["opportunity_attacks"][0]["automatic"] is True
        assert campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants/{enemy['id']}"
        ).json()["reaction_available"] is False
        assert campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/player-action-requests?status=pending"
        ).json()["items"] == []
    finally:
        player.close()


def test_monster_move_prompts_player_and_player_can_accept_structured_reaction(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "玩家借机选择"}).json()
    campaign_id = campaign["id"]
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/characters",
        json={"name": "反应玩家", "class_name": "战士", "hp": 10, "max_hp": 10},
    ).json()
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats", json={"name": "怪物离场反应"}
    ).json()
    campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 2},
                "actions": [
                    {
                        "name": "短剑",
                        "damage_expression": "1d1",
                        "damage_type": "piercing",
                        "range_ft": 5,
                        "attack_type": "melee",
                        "action_type": "reaction",
                        "attack_bonus": 100,
                    }
                ],
            },
        },
    )
    enemy = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": "离场怪物",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "movement_remaining_ft": 30,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 3},
                "actions": [
                    {
                        "name": "利爪",
                        "damage": "1d1",
                        "damage_type": "slashing",
                        "range_ft": 5,
                        "attack_type": "melee",
                        "attack_bonus": 100,
                    }
                ],
            },
        },
    ).json()
    reactor = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": "进入范围守卫",
            "entity_type": "monster",
            "initiative": 5,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 2, "col": 6},
                "actions": [
                    {
                        "name": "近身拦截",
                        "action_type": "reaction",
                        "reaction_event": "enters_reach",
                        "reaction_trigger": "当生物进入近战威胁范围时",
                        "range_ft": 5,
                    }
                ],
            },
        },
    ).json()
    opened = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/player-room/open", json={"hours": 4}
    ).json()
    player = TestClient(campaign_client.app)
    try:
        assert player.post(
            "/api/v1/player-room/join",
            json={"join_code": opened["join_code"], "display_name": "反应客户端"},
        ).status_code == 201
        assert player.post(
            "/api/v1/player-room/me/bind-character",
            json={"character_id": character["id"]},
        ).status_code == 200
        assert campaign_client.post(
            f"/api/v1/campaigns/{campaign_id}/player-room/live-state",
            json={"combat_id": combat["id"]},
        ).status_code == 200
        moved = campaign_client.post(
            f"/api/v1/campaigns/{campaign_id}/player-room/combat/{combat['id']}/monster-move/{enemy['id']}",
            json={
                "row": 2,
                "col": 5,
                "combatant_version": enemy["version"],
                "movement_remaining_ft": 20,
            },
        )
        assert moved.status_code == 200, moved.text
        request = moved.json()["reaction_requests"][0]
        actions = campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/actions"
        ).json()["items"]
        enters_window_items = [
            item
            for item in actions
            if item["action_type"] == "eligible_action_window"
            and item["result_json"].get("action_window", {}).get("reaction_event")
            == "enters_reach"
        ]
        assert len(enters_window_items) == 1
        assert enters_window_items[0]["actor_combatant_id"] == reactor["id"]
        assert enters_window_items[0]["result_json"]["action_window"][
            "trigger_combatant_id"
        ] == enemy["id"]
        pending = player.get("/api/v1/player-room/me").json()["combat"]["pending_reactions"]
        assert pending[0]["id"] == request["id"]
        accepted = player.post(
            f"/api/v1/player-room/me/combat/reactions/{request['id']}",
            json={"version": request["version"], "decision": "accept"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted"
        current_enemy = campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants/{enemy['id']}"
        ).json()
        current_actor = next(
            item
            for item in campaign_client.get(
                f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants"
            ).json()["items"]
            if item["entity_type"] == "character"
        )
        assert current_enemy["reaction_available"] is True
        assert current_actor["reaction_available"] is False
        assert current_enemy["hp"] < current_enemy["max_hp"]
    finally:
        player.close()


def test_entering_monster_reach_opens_one_structured_dm_window_for_player_move(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "进入威胁范围反应"}
    ).json()
    campaign_id = campaign["id"]
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/characters",
        json={"name": "进入者", "class_name": "战士", "hp": 20, "max_hp": 20},
    ).json()
    combat = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats", json={"name": "进入范围战斗"}
    ).json()
    actor = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
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
    monster = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": "范围守卫",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 4},
                "actions": [
                    {
                        "name": "进入反击",
                        "action_type": "reaction",
                        "reaction_event": "enters_reach",
                        "reaction_trigger": "当生物进入近战威胁范围时",
                        "range_ft": 5,
                    }
                ],
            },
        },
    ).json()
    opened = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/player-room/open", json={"hours": 4}
    ).json()
    player = TestClient(campaign_client.app)
    try:
        assert player.post(
            "/api/v1/player-room/join",
            json={"join_code": opened["join_code"], "display_name": "进入范围客户端"},
        ).status_code == 201
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
                "col": 3,
                "combatant_version": actor["version"],
            },
        )
        assert moved.status_code == 200, moved.text
        actions = campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/actions"
        ).json()["items"]
        windows = [
            item["result_json"]["action_window"]
            for item in actions
            if item["action_type"] == "eligible_action_window"
            and item["result_json"].get("action_window", {}).get("reaction_event")
            == "enters_reach"
        ]
        assert len(windows) == 1
        assert windows[0]["eligible_action_names"] == ["进入反击"]
        assert windows[0]["trigger_combatant_id"] == actor["id"]
        assert windows[0]["from_position"] == {"row": 2, "col": 2}
        assert windows[0]["to_position"] == {"row": 2, "col": 3}
        assert windows[0]["reaction_ranges_ft"] == {"进入反击": 5}
        assert monster["id"] != actor["id"]
        inside = player.get("/api/v1/player-room/me").json()["combat"]
        inside_actor = next(
            item for item in inside["combatants"] if item["id"] == inside["own_combatant_id"]
        )
        moved_out = player.post(
            "/api/v1/player-room/me/combat/move",
            json={
                "row": 2,
                "col": 2,
                "combatant_version": inside_actor["version"],
            },
        )
        assert moved_out.status_code == 200, moved_out.text
        outside = player.get("/api/v1/player-room/me").json()["combat"]
        outside_actor = next(
            item for item in outside["combatants"] if item["id"] == outside["own_combatant_id"]
        )
        moved_back = player.post(
            "/api/v1/player-room/me/combat/move",
            json={
                "row": 2,
                "col": 3,
                "combatant_version": outside_actor["version"],
            },
        )
        assert moved_back.status_code == 200, moved_back.text
        actions_after_reentry = campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/actions"
        ).json()["items"]
        assert sum(
            item["action_type"] == "eligible_action_window"
            and item["result_json"].get("action_window", {}).get("reaction_event")
            == "enters_reach"
            for item in actions_after_reentry
        ) == 1
    finally:
        player.close()
