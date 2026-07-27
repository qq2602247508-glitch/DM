from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient


def _character(
    client: TestClient,
    campaign_id: str,
    name: str,
    *,
    action_name: str = "长剑",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/campaigns/{campaign_id}/characters",
        json={
            "name": name,
            "race": "人类",
            "class_name": "战士",
            "background": "士兵",
            "armor_class": 16,
            "speed": 30,
            "ability_scores": {"strength": 16, "dexterity": 12, "constitution": 14},
            "hp": 12,
            "max_hp": 12,
            "actions": [
                {
                    "name": action_name,
                    "description": "近战武器攻击",
                    "damage": "1d8+力量 挥砍",
                    "damage_type": "挥砍",
                    "range": "5尺",
                    "cost": "动作",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _join(client: TestClient, code: str, display_name: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/player-room/join",
        json={"join_code": code, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_two_independent_player_sessions_share_table_combat_and_settlement(
    campaign_client: TestClient,
) -> None:
    """Two real cookies can play the same public encounter without leaking sheets."""

    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "双玩家联机验收"}
    ).json()
    campaign_id = campaign["id"]
    hero_a = _character(campaign_client, campaign_id, "玩家甲")
    hero_b = _character(campaign_client, campaign_id, "玩家乙")
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes",
        json={"name": "公开酒馆", "description": "玩家可见的酒馆大厅"},
    ).json()
    grid = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes/{scene['id']}/grid",
        json={
            "width": 10,
            "height": 8,
            "cell_size_ft": 5,
            "mode": "combat",
            "public_description": "吧台和大厅",
            "layers_json": {"cells": []},
        },
    )
    assert grid.status_code == 201
    monster = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/monsters",
        json={"name": "地精", "armor_class": 12, "hp": 5, "max_hp": 5},
    ).json()
    for entity_id in (hero_a["id"], hero_b["id"], monster["id"]):
        entity_type = "monster" if entity_id == monster["id"] else "character"
        assert campaign_client.post(
            f"/api/v1/campaigns/{campaign_id}/scenes/{scene['id']}/participants",
            json={"entity_type": entity_type, "entity_id": entity_id},
        ).status_code == 201
    started = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes/{scene['id']}/start-combat",
        json={"name": "酒馆遭遇"},
    )
    assert started.status_code == 201, started.text
    combat = started.json()["combat"]
    combatants = campaign_client.get(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants"
    ).json()["items"]
    by_entity = {item["entity_id"]: item for item in combatants}
    # Make the active order and positions deterministic while retaining snapshots.
    positions = {
        hero_a["id"]: (7, 2),
        hero_b["id"]: (7, 6),
        monster["id"]: (7, 3),
    }
    initiatives = {hero_a["id"]: 30, hero_b["id"]: 20, monster["id"]: 10}
    for entity_id, fighter in by_entity.items():
        patched = campaign_client.patch(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants/{fighter['id']}",
            headers={"If-Match": f'"{fighter["version"]}"'},
            json={
                "initiative": initiatives[entity_id],
                "snapshot_json": {
                    **fighter["snapshot_json"],
                    "grid_position": {
                        "row": positions[entity_id][0],
                        "col": positions[entity_id][1],
                    },
                },
            },
        )
        assert patched.status_code == 200, patched.text
        by_entity[entity_id] = patched.json()

    opened = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/player-room/open", json={"hours": 4}
    ).json()
    player_a = TestClient(campaign_client.app)
    player_b = TestClient(campaign_client.app)
    try:
        _join(player_a, opened["join_code"], "甲的浏览器")
        _join(player_b, opened["join_code"], "乙的浏览器")
        assert player_a.post(
            "/api/v1/player-room/me/bind-character",
            json={"character_id": hero_a["id"]},
        ).status_code == 200
        assert player_b.post(
            "/api/v1/player-room/me/bind-character",
            json={"character_id": hero_b["id"]},
        ).status_code == 200
        for player in (player_a, player_b):
            live = campaign_client.post(
                f"/api/v1/campaigns/{campaign_id}/player-room/live-state",
                json={"scene_id": scene["id"], "combat_id": combat["id"]},
            )
            assert live.status_code == 200
            snapshot = player.get("/api/v1/player-room/me")
            assert snapshot.status_code == 200
            assert snapshot.json()["table"]["scene"]["id"] == scene["id"]
            assert snapshot.json()["table"]["scene"]["grid"]["public_description"] == "吧台和大厅"

        view_a = player_a.get("/api/v1/player-room/me").json()
        view_b = player_b.get("/api/v1/player-room/me").json()
        assert view_a["character"]["id"] == hero_a["id"]
        assert view_b["character"]["id"] == hero_b["id"]
        assert view_a["character"]["id"] != view_b["character"]["id"]
        assert hero_b["id"] not in str(view_a["character"])
        assert hero_a["id"] not in str(view_b["character"])
        assert view_a["combat"]["is_my_turn"] is True
        assert view_b["combat"]["is_my_turn"] is False

        attack = player_a.post(
            "/api/v1/player-room/me/combat/attack",
            json={
                "target_combatant_id": by_entity[monster["id"]]["id"],
                "action_name": "长剑",
                "attack_total": 20,
                "damage_total": 4,
                "end_turn_after": True,
                "idempotency_key": "lan-a-first-attack",
            },
        )
        assert attack.status_code == 200, attack.text
        assert attack.json()["target_count"] == 1
        assert player_b.get("/api/v1/player-room/me").json()["combat"]["is_my_turn"] is True
        assert any(
            item["health_status"] in {"重伤", "受伤", "状态良好"}
            for item in player_b.get("/api/v1/player-room/me").json()["combat"]["combatants"]
            if item["name"] == "地精"
        )

        b_turn = player_b.get("/api/v1/player-room/me").json()["combat"]
        ended_b = player_b.post(
            "/api/v1/player-room/me/combat/end-turn",
            json={
                "combat_version": b_turn["version"],
                "idempotency_key": "lan-b-end-turn",
            },
        )
        assert ended_b.status_code == 200, ended_b.text
        monster_turn = player_a.get("/api/v1/player-room/me").json()["combat"]
        assert monster_turn["active_combatant_id"] == by_entity[monster["id"]]["id"]
        monster_version = next(
            item["version"]
            for item in monster_turn["combatants"]
            if item["id"] == by_entity[monster["id"]]["id"]
        )
        player_fighter_id = by_entity[hero_a["id"]]["id"]
        player_fighter = next(
            item for item in monster_turn["combatants"] if item["id"] == player_fighter_id
        )
        pending = campaign_client.post(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/actions/player-rolls/pending",
            json={
                "actor_combatant_id": by_entity[monster["id"]]["id"],
                "actor_version": monster_version,
                "target_combatant_id": player_fighter["id"],
                "target_version": player_fighter["version"],
                "action_name": "毒牙",
                "resolution_type": "saving_throw",
                "dc": 11,
                "ability": "constitution",
                "damage_on_failure": 2,
                "damage_type": "poison",
            },
        )
        assert pending.status_code == 200, pending.text
        action = pending.json()["action"]
        assert player_a.get("/api/v1/player-room/me").json()["combat"]["pending_rolls"]
        assert player_b.get("/api/v1/player-room/me").json()["combat"]["pending_rolls"] == []
        rolled = player_a.post(
            f"/api/v1/player-room/me/combat/player-rolls/{action['id']}",
            json={
                "action_version": action["version"],
                "roll_total": 20,
                "idempotency_key": "lan-a-save-roll",
            },
        )
        assert rolled.status_code == 200, rolled.text
        assert player_a.get("/api/v1/player-room/me").json()["combat"]["is_my_turn"] is True

        current = player_a.get("/api/v1/player-room/me").json()["combat"]
        monster_fighter = next(
            item for item in current["combatants"] if item["id"] == by_entity[monster["id"]]["id"]
        )
        final_attack = player_a.post(
            "/api/v1/player-room/me/combat/attack",
            json={
                "target_combatant_id": monster_fighter["id"],
                "action_name": "长剑",
                "attack_total": 20,
                "damage_total": 2,
                "end_turn_after": False,
                "idempotency_key": "lan-a-final-attack",
            },
        )
        assert final_attack.status_code == 200, final_attack.text
        latest = campaign_client.get(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}"
        ).json()
        ended = campaign_client.patch(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}",
            headers={"If-Match": f'"{latest["version"]}"'},
            json={"status": "ended"},
        )
        assert ended.status_code == 200, ended.text
        awards = {
            "combat_version": ended.json()["version"],
            "resolution_type": "victory",
            "xp_awards": [
                {"character_id": hero_a["id"], "xp": 25},
                {"character_id": hero_b["id"], "xp": 25},
            ],
            "writebacks": [
                {
                    "combatant_id": by_entity[hero_a["id"]]["id"],
                    "character_id": hero_a["id"],
                    "write_hp": True,
                },
                {
                    "combatant_id": by_entity[hero_b["id"]]["id"],
                    "character_id": hero_b["id"],
                    "write_hp": True,
                },
            ],
        }
        settled = campaign_client.post(
            f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/settlement/confirm",
            headers={"X-Request-ID": "lan-settlement"},
            json=awards,
        )
        assert settled.status_code == 200, settled.text
        assert {item["experience"] for item in settled.json()["characters"]} == {25}
        assert player_a.get("/api/v1/player-room/me").json()["character"]["experience"] == 25
        assert player_b.get("/api/v1/player-room/me").json()["character"]["experience"] == 25
        assert player_a.get("/api/v1/player-room/me").json()["combat"]["status"] == "ended"
    finally:
        player_a.close()
        player_b.close()
