from __future__ import annotations

from fastapi.testclient import TestClient


def test_advanced_phase_previews_execute_through_combat_action_api(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "高级怪物动作窗口团"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(f"{base}/combats", json={"name": "龙巢窗口"}).json()
    hero = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "冒险者",
            "entity_type": "character",
            "initiative": 20,
            "hp": 40,
            "max_hp": 40,
            "snapshot_json": {"disposition": "ally"},
        },
    ).json()
    dragon = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "黑龙",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 120,
            "max_hp": 120,
            "snapshot_json": {
                "disposition": "enemy",
                "actions": [
                    {
                        "name": "借机尾击",
                        "action_type": "reaction",
                        "reaction_event": "leaves_reach",
                        "attack_bonus": 9,
                        "damage": "1d8+5",
                    },
                    {
                        "name": "传奇尾击",
                        "action_type": "legendary_action",
                        "legendary_cost": 1,
                        "legendary_pool_max": 3,
                        "attack_bonus": 9,
                        "damage": "2d8+5",
                    },
                    {
                        "name": "巢穴震击",
                        "action_type": "lair_action",
                        "save_dc": 15,
                        "save_ability": "dexterity",
                        "damage": "2d6",
                    },
                ],
            },
        },
    ).json()
    preview_path = f"{base}/combats/{combat['id']}/monster-ai/preview"

    for phase, action_type in (
        ("reaction", "reaction"),
        ("legendary", "legendary_action"),
        ("lair", "lair_action"),
    ):
        preview = campaign_client.post(
            preview_path,
            json={
                "actor_combatant_id": dragon["id"],
                "actor_version": dragon["version"],
                "phase": phase,
                **(
                    {"reaction_event": "leaves_reach"}
                    if phase == "reaction"
                    else {}
                ),
            },
        )
        assert preview.status_code == 200, preview.text
        plan = preview.json()["plan"]
        assert plan["action_type"] == action_type
        assert plan["target_ids"] == [hero["id"]]
        assert preview.json()["requires_confirmation"] is True

    confirm_path = f"{base}/combats/{combat['id']}/actions/confirm"
    reaction = campaign_client.post(
        confirm_path,
        headers={"X-Request-ID": "ui-reaction-window"},
        json={
            "action_type": "damage",
            "actor_combatant_id": dragon["id"],
            "actor_version": dragon["version"],
            "action_cost": "reaction",
            "reaction_trigger": "冒险者离开黑龙的近战威胁范围",
            "reaction_event": "leaves_reach",
            "action_name": "借机尾击",
            "target_combatant_id": hero["id"],
            "target_version": hero["version"],
            "amount": 4,
            "damage_type": "bludgeoning",
        },
    )
    assert reaction.status_code == 200, reaction.text
    assert reaction.json()["actor"]["reaction_available"] is False
    reaction_action = reaction.json()["action"]
    assert "反应触发：冒险者离开黑龙的近战威胁范围" in reaction_action["summary"]
    assert reaction_action["result_json"]["action_window"] == {
        "action_cost": "reaction",
        "reaction_event": "leaves_reach",
        "reaction_trigger": "冒险者离开黑龙的近战威胁范围",
    }

    legendary = campaign_client.post(
        confirm_path,
        headers={"X-Request-ID": "ui-legendary-window"},
        json={
            "action_type": "damage",
            "actor_combatant_id": dragon["id"],
            "actor_version": reaction.json()["actor"]["version"],
            "action_cost": "legendary_action",
            "legendary_cost": 1,
            "legendary_pool_max": 3,
            "action_name": "传奇尾击",
            "target_combatant_id": hero["id"],
            "target_version": reaction.json()["target"]["version"],
            "amount": 6,
            "damage_type": "bludgeoning",
        },
    )
    assert legendary.status_code == 200, legendary.text
    assert legendary.json()["actor"]["snapshot_json"]["legendary_actions_remaining"] == 2
    legendary_action = legendary.json()["action"]
    assert "传奇动作窗口（消耗 1 点；动作池 3）" in legendary_action["summary"]
    assert legendary_action["result_json"]["action_window"] == {
        "action_cost": "legendary_action",
        "legendary_cost": 1,
        "legendary_pool_max": 3,
    }

    lair = campaign_client.post(
        confirm_path,
        headers={"X-Request-ID": "ui-lair-window"},
        json={
            "action_type": "damage",
            "actor_combatant_id": dragon["id"],
            "actor_version": legendary.json()["actor"]["version"],
            "action_cost": "lair_action",
            "action_name": "巢穴震击",
            "target_combatant_id": hero["id"],
            "target_version": legendary.json()["target"]["version"],
            "amount": 3,
            "damage_type": "thunder",
        },
    )
    assert lair.status_code == 200, lair.text
    assert lair.json()["actor"]["snapshot_json"]["lair_action_round"] == 1
    lair_action = lair.json()["action"]
    assert "巢穴动作窗口（本轮先攻20）" in lair_action["summary"]
    assert lair_action["result_json"]["action_window"] == {
        "action_cost": "lair_action",
    }


def test_monster_ai_preview_chooses_live_enemy_and_requires_confirmation(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "怪物 AI 验收团"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(f"{base}/combats", json={"name": "AI 战斗"}).json()
    monster = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "火蜥蜴",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "disposition": "enemy",
                "grid_position": {"row": 1, "col": 1},
                "actions": [
                    {"name": "爪击", "action_type": "action", "damage": "1d6"},
                ],
            },
        },
    ).json()
    player = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "冒险者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 2},
            },
        },
    ).json()

    response = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/preview",
        json={
            "actor_combatant_id": monster["id"],
            "actor_version": monster["version"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"]["action_name"] == "爪击"
    assert body["plan"]["target_ids"] == [player["id"]]
    assert body["requires_confirmation"] is True


def test_enemy_basic_ai_summon_preview_chooses_live_player_target(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "敌方召唤物 AI 验收团"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(f"{base}/combats", json={"name": "敌方召唤物 AI"}).json()
    summon = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "敌方火元素",
            "entity_type": "companion",
            "initiative": 20,
            "hp": 18,
            "max_hp": 18,
            "snapshot_json": {
                "controller": "dm",
                "disposition": "enemy",
                "enemy_ai_mode": "basic",
                "grid_position": {"row": 1, "col": 1},
                "actions": [
                    {
                        "name": "灼热爪击",
                        "action_type": "action",
                        "damage": "1d6+2",
                        "damage_type": "fire",
                        "range": "5尺",
                    }
                ],
            },
        },
    ).json()
    player = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "冒险者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 2},
            },
        },
    ).json()

    response = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/preview",
        json={
            "actor_combatant_id": summon["id"],
            "actor_version": summon["version"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["actor_policy"] == "enemy_summon_basic"
    assert body["plan"]["action_name"] == "灼热爪击"
    assert body["plan"]["target_ids"] == [player["id"]]


def test_advanced_ai_preview_matches_lair_and_legendary_windows(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "高级动作窗口一致性团"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(
        f"{base}/combats", json={"name": "窗口一致性战斗"}
    ).json()
    _guard = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "高先攻观察者",
            "entity_type": "character",
            "initiative": 30,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    dragon = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "窗口龙",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 40,
            "max_hp": 40,
            "snapshot_json": {
                "disposition": "enemy",
                "actions": [
                    {
                        "name": "巢穴震击",
                        "action_type": "lair_action",
                        "damage": "1d6",
                    },
                    {
                        "name": "传奇尾击",
                        "action_type": "legendary_action",
                        "legendary_cost": 1,
                        "legendary_pool_max": 3,
                        "damage": "1d8",
                    },
                ],
                "legendary_actions_remaining": 3,
            },
        },
    ).json()
    _hero = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "冒险者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"disposition": "ally"},
        },
    ).json()

    lair_preview = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/preview",
        json={
            "actor_combatant_id": dragon["id"],
            "actor_version": dragon["version"],
            "phase": "lair",
        },
    )
    assert lair_preview.status_code == 200, lair_preview.text
    assert lair_preview.json()["plan"] is None

    advanced = campaign_client.post(
        f"{base}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "advanced-window-to-dragon"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["active_combatant"]["id"] == dragon["id"]
    active_dragon = advanced.json()["active_combatant"]
    legendary_preview = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/preview",
        json={
            "actor_combatant_id": dragon["id"],
            "actor_version": active_dragon["version"],
            "phase": "legendary",
        },
    )
    assert legendary_preview.status_code == 200, legendary_preview.text
    assert legendary_preview.json()["plan"] is None


def test_confirmed_monster_tactics_persist_and_drive_preview(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "怪物战术确认团"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(f"{base}/combats", json={"name": "战术战斗"}).json()
    monster = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "战术队长",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "disposition": "enemy",
                "actions": [
                    {
                        "name": "长弓",
                        "action_type": "action",
                        "damage": "1d8+3",
                        "range_ft": 150,
                    }
                ],
            },
        },
    ).json()
    fighter = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "战士",
            "entity_type": "character",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {"disposition": "ally"},
        },
    ).json()
    wizard = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "法师",
            "entity_type": "character",
            "initiative": 5,
            "hp": 8,
            "max_hp": 20,
            "snapshot_json": {"disposition": "ally"},
        },
    ).json()

    confirmed = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/tactics/confirm",
        headers={"X-Request-ID": "focus-wizard"},
        json={
            "actor_combatant_id": monster["id"],
            "actor_version": monster["version"],
            "strategy": "focus_fire",
            "focus_target_id": wizard["id"],
            "reason": "DM确认队长识别出施法者并命令集火",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["actor"]["snapshot_json"]["ai_tactics"]["focus_target_id"] == wizard["id"]
    assert body["action"]["action_type"] == "monster_ai_tactics"

    preview = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/preview",
        json={
            "actor_combatant_id": monster["id"],
            "actor_version": body["actor"]["version"],
            "tactics": "tactical",
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["plan"]["target_ids"] == [wizard["id"]]
    assert fighter["id"] != wizard["id"]

    replay = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/tactics/confirm",
        headers={"X-Request-ID": "focus-wizard"},
        json={
            "actor_combatant_id": monster["id"],
            "actor_version": monster["version"],
            "strategy": "focus_fire",
            "focus_target_id": wizard["id"],
            "reason": "DM确认队长识别出施法者并命令集火",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


def test_low_hp_retreat_plan_executes_disengage_once(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "怪物撤退执行团"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(f"{base}/combats", json={"name": "撤退战斗"}).json()
    monster = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "受伤守卫",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 5,
            "max_hp": 30,
            "snapshot_json": {"disposition": "enemy", "actions": []},
        },
    ).json()
    campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "追击者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"disposition": "ally"},
        },
    )
    refused = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/retreat/confirm",
        headers={"X-Request-ID": "retreat-without-plan"},
        json={
            "actor_combatant_id": monster["id"],
            "actor_version": monster["version"],
        },
    )
    assert refused.status_code == 400
    assert "no active retreat plan" in refused.json()["message"]

    tactics = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/tactics/confirm",
        headers={"X-Request-ID": "retreat-threshold"},
        json={
            "actor_combatant_id": monster["id"],
            "actor_version": monster["version"],
            "strategy": "adaptive",
            "retreat_threshold_pct": 25,
            "reason": "DM确认守卫低于四分之一生命时撤退",
        },
    )
    assert tactics.status_code == 200, tactics.text
    actor = tactics.json()["actor"]

    confirmed = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/retreat/confirm",
        headers={"X-Request-ID": "execute-retreat-once"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
        },
    )

    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["action"]["action_type"] == "disengage"
    assert "movement" not in body["action"]["result_json"]
    assert body["actor"]["action_available"] is False
    assert body["effect"]["details_json"]["runtime_state"]["name"] == "disengage"
    assert body["effect"]["details_json"]["runtime_state"]["expires"] == "turn_end"
    assert "撤离" in body["actor"]["conditions"]

    replay = campaign_client.post(
        f"{base}/combats/{combat['id']}/monster-ai/retreat/confirm",
        headers={"X-Request-ID": "execute-retreat-once"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    assert replay.json()["action"]["id"] == body["action"]["id"]


def test_reaction_save_prompt_keeps_trigger_after_player_resolution(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "反应审计团"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(f"{base}/combats", json={"name": "反应豁免"}).json()
    hero = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "冒险者",
            "entity_type": "character",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    dragon = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "黑龙",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 100,
            "max_hp": 100,
        },
    ).json()
    trigger = "冒险者离开黑龙的近战威胁范围"
    prompt = campaign_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending",
        headers={"X-Request-ID": "reaction-save-prompt"},
        json={
            "actor_combatant_id": dragon["id"],
            "actor_version": dragon["version"],
            "target_combatant_id": hero["id"],
            "target_version": hero["version"],
            "action_cost": "reaction",
            "action_name": "酸液反击",
            "resolution_type": "saving_throw",
            "dc": 13,
            "ability": "dexterity",
            "damage_on_failure": 7,
            "damage_type": "acid",
            "reaction_trigger": trigger,
            "reaction_event": "leaves_reach",
            "description": "DM确认反应已经触发",
        },
    )
    assert prompt.status_code == 200, prompt.text
    prompt_action = prompt.json()["action"]
    assert trigger in prompt_action["summary"]
    assert prompt_action["result_json"]["action_window"]["reaction_trigger"] == trigger

    resolved = campaign_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/{prompt_action['id']}/confirm",
        headers={"X-Request-ID": "reaction-save-resolve"},
        json={"action_version": prompt_action["version"], "roll_total": 5},
    )
    assert resolved.status_code == 200, resolved.text
    resolved_action = resolved.json()["action"]
    assert trigger in resolved_action["summary"]
    assert resolved_action["result_json"]["action_window"] == {
        "action_cost": "reaction",
        "reaction_event": "leaves_reach",
        "reaction_trigger": trigger,
    }
    follow_up = resolved.json()["resolution"]["follow_up_damage"]
    assert follow_up["amount"] == 7
    damage = campaign_client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "reaction-save-follow-up"},
        json=follow_up,
    )
    assert damage.status_code == 200, damage.text
    assert damage.json()["target"]["hp"] == 13
