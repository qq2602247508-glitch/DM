from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_simulation_fixture_uses_real_combat_and_player_room(campaign_client: TestClient) -> None:
    missing = campaign_client.get("/api/v1/simulations/current")
    assert missing.status_code == 404

    prepared = campaign_client.post("/api/v1/simulations/prepare")
    assert prepared.status_code == 200, prepared.text
    state = prepared.json()
    assert state["campaign"]["name"] == "【系统】召唤物与法术战斗模拟"
    assert state["scene"]["name"] == "模拟战斗：元素熔炉"
    assert state["combat"]["name"] == "模拟战斗：熔炉门厅"
    assert len(state["combatants"]) == 3
    assert state["companion"]["name"] == "小火元素（模拟模板）"
    assert state["player_join_code"]
    assert state["player_room"]["current_combat_id"] == state["combat"]["id"]

    join = campaign_client.post(
        "/api/v1/player-room/join",
        json={"join_code": state["player_join_code"], "display_name": "模拟玩家"},
    )
    assert join.status_code == 201, join.text

    snapshot = campaign_client.get("/api/v1/player-room/me")
    assert snapshot.status_code == 200, snapshot.text
    player_state = snapshot.json()
    assert player_state["campaign"]["id"] == state["campaign"]["id"]
    assert player_state["combat"]["id"] == state["combat"]["id"]
    options = player_state["available_characters"]
    simulation_character = next(item for item in options if item["id"] == state["character"]["id"])

    bound = campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": simulation_character["id"]},
    )
    assert bound.status_code == 200, bound.text

    bound_snapshot = campaign_client.get("/api/v1/player-room/me")
    assert bound_snapshot.status_code == 200, bound_snapshot.text
    bound_state: dict[str, Any] = bound_snapshot.json()
    assert bound_state["character"]["id"] == state["character"]["id"]
    assert bound_state["combat"]["own_combatant_id"]
    assert any(item["name"] == "熔火术士·AI" for item in bound_state["combat"]["combatants"])
    mage = next(item for item in state["combatants"] if item["display_name"] == "熔火术士·AI")
    mage_action_names = {item["name"] for item in mage["snapshot_json"]["actions"]}
    assert {"熔火射线", "熔炉爆裂"}.issubset(mage_action_names)
    player_actions = state["combatants"][0]["snapshot_json"]["actions"]
    fire_bolt = next(item for item in player_actions if item["name"] == "火焰箭")
    assert fire_bolt["damage_type"] == "fire"
    fire_bolt_damage = next(
        block for block in fire_bolt["rule_plan"]["blocks"] if block["kind"] == "damage"
    )
    assert fire_bolt_damage["damage_type"] == "fire"
    thunderwave = next(item for item in player_actions if item["name"] == "雷鸣波")
    thunderwave_move = next(
        block for block in thunderwave["rule_plan"]["blocks"] if block["kind"] == "move"
    )
    assert thunderwave_move["movement_type"] == "forced"
    assert thunderwave_move["distance_ft"] == 10
    assert thunderwave_move["direction"] == "away"
    fireball = next(item for item in player_actions if item["name"] == "火球术")
    assert fireball["area_shape"] == "sphere"
    assert fireball["area_size_ft"] == 20
    assert fireball["range_ft"] == 150
    assert fireball["save_ability"] == "dexterity"
    assert fireball["save_dc"] == 14
    assert fireball["half_damage_on_save"] is True
    assert fireball["affects_multiple_targets"] is True
    magic_missile = next(item for item in player_actions if item["name"] == "魔法飞弹")
    assert magic_missile["damage"] == "3d4+3"
    assert magic_missile["damage_type"] == "force"
    assert magic_missile["auto_hit"] is True
    assert any(
        block["kind"] == "auto_hit"
        for block in magic_missile["rule_plan"]["blocks"]
    )
    assert any(
        item["name"] == "魔法飞弹"
        and item["auto_hit"] is True
        for item in bound_state["character"]["spells"]
    )

    summoned = campaign_client.post(
        "/api/v1/player-room/me/combat/summon",
        json={
            "companion_id": state["companion"]["id"],
            "action_name": "召唤小火元素",
            "count": 1,
            "position": {"row": 6, "col": 5},
            "idempotency_key": "simulation-summon-test",
        },
    )
    assert summoned.status_code == 200, summoned.text
    after_summon = campaign_client.get("/api/v1/player-room/me")
    assert after_summon.status_code == 200, after_summon.text
    after_summon_state = after_summon.json()
    assert len(after_summon_state["combat"]["combatants"]) == 4
    assert any(
        item["name"] == "小火元素（模拟模板）"
        for item in after_summon_state["combat"]["combatants"]
    )
    summoned_view = next(
        item
        for item in after_summon_state["combat"]["combatants"]
        if item["name"] == "小火元素（模拟模板）"
    )
    assert summoned_view["controller"] == "player"
    assert summoned_view["is_own"] is True
    assert summoned_view["owner_character_id"] == state["character"]["id"]
    full_combatants = campaign_client.get(
        f"/api/v1/campaigns/{state['campaign']['id']}/combats/{state['combat']['id']}/combatants"
    ).json()["items"]
    summoned_unit = next(
        item for item in full_combatants
        if item["display_name"] == "小火元素（模拟模板）"
    )
    assert summoned_unit["snapshot_json"]["grid_position"] == {"row": 6, "col": 5}

    # The DM reset button uses the normal combat reset endpoint.  It must
    # remove a runtime summon rather than leaving a position-less stale unit
    # in initiative for the next AI area action.
    current_before_dm_reset = campaign_client.get(
        f"/api/v1/campaigns/{state['campaign']['id']}/combats"
    ).json()["items"][0]
    dm_reset = campaign_client.post(
        f"/api/v1/campaigns/{state['campaign']['id']}/combats/{state['combat']['id']}/reset",
        headers={"X-Request-ID": "simulation-dm-reset-clears-summon"},
        json={"combat_version": current_before_dm_reset["version"]},
    )
    assert dm_reset.status_code == 200, dm_reset.text
    assert len(dm_reset.json()["combatants"]) == 3
    assert all(
        item["entity_type"] != "companion"
        for item in dm_reset.json()["combatants"]
    )

    reset = campaign_client.post("/api/v1/simulations/reset")
    assert reset.status_code == 200, reset.text
    reset_state = reset.json()
    assert reset_state["combat"]["round_number"] == 1
    assert len(reset_state["combatants"]) == 3
    assert all(
        item["hp"] == item["snapshot_json"]["combat_start_state"]["hp"]
        for item in reset_state["combatants"]
    )
    player_after_reset = next(
        item for item in reset_state["combatants"] if item["display_name"] == "模拟玩家·奥术师"
    )
    assert player_after_reset["concentration"] == {}
    assert player_after_reset["snapshot_json"]["grid_position"] == {"row": 6, "col": 2}
    mage_after_reset = next(
        item for item in reset_state["combatants"] if item["display_name"] == "熔火术士·AI"
    )
    reset_mage_action_names = {
        item["name"] for item in mage_after_reset["snapshot_json"]["actions"]
    }
    assert {"熔火射线", "熔炉爆裂"}.issubset(reset_mage_action_names)
    assert mage_after_reset["snapshot_json"]["grid_position"] == {"row": 5, "col": 4}
    assert reset_state["character"]["resources"]["spell_slots_2"]["current"] == 3

    thunderwave = campaign_client.post(
        f"/api/v1/campaigns/{state['campaign']['id']}/combats/{state['combat']['id']}/actions/confirm",
        headers={"X-Request-ID": "simulation-thunderwave-forced-movement"},
        json={
            "action_type": "damage",
            "actor_combatant_id": player_after_reset["id"],
            "actor_version": player_after_reset["version"],
            "action_cost": "action",
            "action_name": "雷鸣波",
            "target_combatant_id": mage_after_reset["id"],
            "target_version": mage_after_reset["version"],
            "amount": 8,
            "damage_type": "thunder",
            "forced_movement_distance_ft": 10,
            "forced_movement_direction": "away",
        },
    )
    assert thunderwave.status_code == 200, thunderwave.text
    movement = thunderwave.json()["action"]["result_json"]["structured_effects"]["movement"]
    assert movement["moved_ft"] == 10
    assert movement["from"] == {"row": 5, "col": 4}
    assert movement["to"] != movement["from"]

    current_combat = campaign_client.get(
        f"/api/v1/campaigns/{state['campaign']['id']}/combats"
    ).json()["items"][0]
    combat_reset = campaign_client.post(
        f"/api/v1/campaigns/{state['campaign']['id']}/combats/{state['combat']['id']}/reset",
        headers={"X-Request-ID": "simulation-combat-reset-position"},
        json={"combat_version": current_combat["version"]},
    )
    assert combat_reset.status_code == 200, combat_reset.text
    reset_player = next(
        item for item in combat_reset.json()["combatants"]
        if item["display_name"] == "模拟玩家·奥术师"
    )
    reset_mage = next(
        item for item in combat_reset.json()["combatants"]
        if item["display_name"] == "熔火术士·AI"
    )
    assert reset_player["snapshot_json"]["grid_position"] == {"row": 6, "col": 2}
    assert reset_mage["snapshot_json"]["grid_position"] == {"row": 5, "col": 4}

    actions = campaign_client.get(
        f"/api/v1/campaigns/{state['campaign']['id']}/combats/{state['combat']['id']}/actions"
    )
    assert actions.status_code == 200, actions.text
    assert actions.json()["items"] == []
