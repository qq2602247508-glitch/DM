from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings


@pytest.fixture
def combat_client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'combat-lifecycle.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as client:
        yield client


def _setup(client: TestClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    campaign_response = client.post("/api/v1/campaigns", json={"name": "Action lifecycle"})
    assert campaign_response.status_code == 201
    campaign = campaign_response.json()
    combat_response = client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Lifecycle combat"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    actor_response = client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Actor",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "speed_ft": 30,
        },
    )
    assert actor_response.status_code == 201
    return campaign, combat, actor_response.json()


def _root(campaign: dict[str, Any], combat: dict[str, Any]) -> str:
    return f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"


def _combatant_path(campaign: dict[str, Any], combat: dict[str, Any], combatant_id: str) -> str:
    return f"{_root(campaign, combat)}/combatants/{combatant_id}"


def _add_combatant(
    client: TestClient,
    campaign: dict[str, Any],
    combat: dict[str, Any],
    *,
    name: str,
    initiative: int,
) -> dict[str, Any]:
    response = client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": name,
            "initiative": initiative,
            "hp": 20,
            "max_hp": 20,
            "speed_ft": 30,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    ("condition", "expected_movement"),
    [
        ("incapacitated", 30),
        ("昏迷", 0),
        ("stunned", 0),
        ("麻痹", 0),
        ("petrified", 0),
    ],
)
def test_action_blocking_conditions_reject_real_actions(
    combat_client: TestClient,
    condition: str,
    expected_movement: int,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={"conditions": [condition]},
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()

    blocked = combat_client.post(
        f"{_root(campaign, combat)}/maneuvers/confirm",
        headers={"X-Request-ID": "blocked-condition"},
        json={
            "action_type": "dash",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
        },
    )

    assert blocked.status_code == 400
    assert "cannot take actions" in blocked.json()["message"]
    unchanged = combat_client.get(_combatant_path(campaign, combat, actor["id"])).json()
    # The rejected maneuver does not consume anything; the condition itself
    # still owns the action restriction until it is removed.
    assert unchanged["action_available"] is False
    assert unchanged["movement_remaining_ft"] == expected_movement


def test_dodge_and_prone_force_explicit_attack_ruling_then_dodge_expires(
    combat_client: TestClient,
) -> None:
    campaign, combat, defender = _setup(combat_client)
    attacker = _add_combatant(combat_client, campaign, combat, name="Attacker", initiative=10)
    prone = combat_client.patch(
        _combatant_path(campaign, combat, attacker["id"]),
        headers={"If-Match": f'"{attacker["version"]}"'},
        json={"conditions": ["prone"]},
    )
    assert prone.status_code == 200
    attacker = prone.json()
    dodged = combat_client.post(
        f"{_root(campaign, combat)}/maneuvers/confirm",
        headers={"X-Request-ID": "dodge-state"},
        json={
            "action_type": "dodge",
            "actor_combatant_id": defender["id"],
            "actor_version": defender["version"],
        },
    )
    assert dodged.status_code == 200, dodged.text
    defender = dodged.json()["actor"]
    assert "闪避" in defender["conditions"]

    advanced = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "to-prone-attacker"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    attacker = advanced.json()["active_combatant"]
    attack_payload = {
        "action_type": "damage",
        "is_attack": True,
        "action_cost": "action",
        "actor_combatant_id": attacker["id"],
        "actor_version": attacker["version"],
        "target_combatant_id": defender["id"],
        "target_version": defender["version"],
        "amount": 3,
        "damage_type": "slashing",
    }
    refused = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "attack-without-ruling"},
        json=attack_payload,
    )
    assert refused.status_code == 400
    assert "will not guess" in refused.json()["message"]

    resolved = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "attack-with-ruling"},
        json={
            **attack_payload,
            "attack_roll_mode": "disadvantage",
            "attack_adjudication_note": (
                "DM确认攻击者倒地且目标正在闪避；最终以劣势命中后结算伤害"
            ),
        },
    )
    assert resolved.status_code == 200, resolved.text
    contexts = resolved.json()["action"]["result_json"]["attack_contexts"]
    assert "attacker_prone" in contexts
    assert "target_dodging" in contexts
    defender = resolved.json()["target"]

    expired = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "dodge-next-turn"},
        json={"combat_version": advanced.json()["combat"]["version"]},
    )
    assert expired.status_code == 200, expired.text
    assert expired.json()["active_combatant"]["id"] == defender["id"]
    assert "闪避" not in expired.json()["active_combatant"]["conditions"]
    assert any(
        effect["id"] == dodged.json()["effect"]["id"]
        for effect in expired.json()["ended_runtime_effects"]
    )


def test_incapacitation_ends_dodge_before_the_next_attack(
    combat_client: TestClient,
) -> None:
    campaign, combat, defender = _setup(combat_client)
    attacker = _add_combatant(combat_client, campaign, combat, name="攻击者", initiative=10)
    dodged = combat_client.post(
        f"{_root(campaign, combat)}/maneuvers/confirm",
        headers={"X-Request-ID": "dodge-before-incapacitation"},
        json={
            "action_type": "dodge",
            "actor_combatant_id": defender["id"],
            "actor_version": defender["version"],
        },
    )
    assert dodged.status_code == 200, dodged.text
    defender = dodged.json()["actor"]
    dodge_effect_id = dodged.json()["effect"]["id"]
    assert "闪避" in defender["conditions"]

    incapacitated = combat_client.patch(
        _combatant_path(campaign, combat, defender["id"]),
        headers={"If-Match": f'"{defender["version"]}"'},
        json={"conditions": ["失能"]},
    )
    assert incapacitated.status_code == 200, incapacitated.text
    defender = incapacitated.json()
    assert defender["conditions"] == ["失能"]
    effects = combat_client.get(f"{_root(campaign, combat)}/effects").json()["items"]
    dodge_effect = next(item for item in effects if item["id"] == dodge_effect_id)
    assert dodge_effect["status"] == "ended"
    assert dodge_effect["end_reason"] == "闪避因失能结束"

    advanced = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "advance-after-dodge-break"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    attacker = advanced.json()["active_combatant"]
    attack = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "attack-after-dodge-break"},
        json={
            "action_type": "damage",
            "is_attack": True,
            "action_cost": "action",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": defender["id"],
            "target_version": defender["version"],
            "amount": 3,
            "damage_type": "slashing",
            "attack_roll_total": 15,
        },
    )
    assert attack.status_code == 200, attack.text
    assert "target_dodging" not in attack.json()["action"]["result_json"].get(
        "attack_contexts",
        [],
    )


def test_same_condition_from_two_effect_sources_has_independent_lifecycles(
    combat_client: TestClient,
) -> None:
    campaign, combat, target = _setup(combat_client)
    root = _root(campaign, combat)
    block = {
        "rule_block": {
            "kind": "condition",
            "condition": "中毒",
            "operation": "apply",
        }
    }

    first = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "condition-source-1"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "毒箭余毒",
            "effect_type": "condition",
            "details_json": block,
            "duration_unit": "rounds",
            "duration_value": 2,
        },
    )
    assert first.status_code == 200, first.text
    target = first.json()["target"]
    second = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "condition-source-2"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "毒雾",
            "effect_type": "condition",
            "details_json": block,
            "duration_unit": "rounds",
            "duration_value": 3,
        },
    )
    assert second.status_code == 200, second.text
    target = second.json()["target"]
    assert "中毒" in target["conditions"]

    ended_first = combat_client.post(
        f"{root}/effects/{first.json()['effect']['id']}/end",
        headers={"X-Request-ID": "condition-end-1"},
        json={"target_version": target["version"], "reason": "第一来源结束"},
    )
    assert ended_first.status_code == 200, ended_first.text
    target = ended_first.json()["target"]
    assert "中毒" in target["conditions"]

    ended_second = combat_client.post(
        f"{root}/effects/{second.json()['effect']['id']}/end",
        headers={"X-Request-ID": "condition-end-2"},
        json={"target_version": target["version"], "reason": "第二来源结束"},
    )
    assert ended_second.status_code == 200, ended_second.text
    assert "中毒" not in ended_second.json()["target"]["conditions"]


def test_compiled_feature_actions_change_combat_state_and_use_extra_action_budget(
    combat_client: TestClient,
) -> None:
    campaign_response = combat_client.post(
        "/api/v1/campaigns", json={"name": "Feature runtime"}
    )
    assert campaign_response.status_code == 201
    campaign = campaign_response.json()
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "职业特性测试者",
            "class_name": "战士",
            "hp": 20,
            "max_hp": 20,
            "resources": {
                "second_wind": {"current": 1, "max": 1},
                "rage": {"current": 1, "max": 1},
                "action_surge": {"current": 1, "max": 1},
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    registry = {
        "schema_version": "1.0",
        "combat_start": {
            "defenses": [
                {
                    "id": "rage:physical_resistance",
                    "condition": "raging",
                    "operation": "resistance",
                    "damage_types": ["bludgeoning", "piercing", "slashing"],
                }
            ]
        },
        "resources": {},
        "actions": {
            "second_wind": {
                "id": "second_wind",
                "name": "回气",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "second_wind",
                "resource_cost": 1,
                "target": "self",
                "resolution_kind": "healing",
                "healing": "1d10+1",
            },
            "rage": {
                "id": "rage",
                "name": "狂暴",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "rage",
                "resource_cost": 1,
                "target": "self",
                "effects": [{"kind": "activate_condition", "condition": "raging"}],
            },
            "action_surge": {
                "id": "action_surge",
                "name": "动作如潮",
                "kind": "feature_action",
                "action_cost": "none",
                "resource_key": "action_surge",
                "resource_cost": 1,
                "target": "self",
                "effects": [{"kind": "grant_action_budget", "amount": 1}],
            },
        },
    }
    combat_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Feature combat"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    actor_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "职业特性测试者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 5,
            "max_hp": 20,
            "snapshot_json": {
                "feature_runtime": registry,
                "conditional_damage_defenses": registry["combat_start"]["defenses"],
            },
        },
    )
    assert actor_response.status_code == 201, actor_response.text
    actor = actor_response.json()
    enemy_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "测试敌人",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
        },
    )
    assert enemy_response.status_code == 201
    enemy = enemy_response.json()

    feature_path = f"{_root(campaign, combat)}/feature-actions/confirm"
    healed = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "feature-second-wind"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "second_wind",
            "healing_total": 8,
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert healed.status_code == 200, healed.text
    actor = healed.json()["actor"]
    assert actor["hp"] == 13
    assert actor["bonus_action_available"] is False
    assert healed.json()["result"]["resource_after"] == 0

    spent_action = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "feature-spend-action"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_cost": "action",
            "target_combatant_id": enemy["id"],
            "target_version": enemy["version"],
            "amount": 1,
            "damage_type": "slashing",
        },
    )
    assert spent_action.status_code == 200, spent_action.text
    actor = spent_action.json()["actor"]
    enemy = spent_action.json()["target"]
    surged = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "feature-action-surge"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "action_surge",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert surged.status_code == 200, surged.text
    actor = surged.json()["actor"]
    assert actor["snapshot_json"]["extra_action_budget"] == 1
    extra_attack = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "feature-extra-action"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_cost": "action",
            "target_combatant_id": enemy["id"],
            "target_version": enemy["version"],
            "amount": 2,
            "damage_type": "slashing",
        },
    )
    assert extra_attack.status_code == 200, extra_attack.text
    assert extra_attack.json()["actor"]["snapshot_json"]["extra_action_budget"] == 0


def test_compiled_feature_condition_updates_action_economy(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "snapshot_json": {
                "feature_runtime": {
                    "actions": {
                        "stun_self": {
                            "name": "震慑自己（测试）",
                            "kind": "feature_action",
                            "action_cost": "none",
                            "target": "self",
                            "effects": [
                                {
                                    "kind": "activate_condition",
                                    "condition": "震慑",
                                }
                            ],
                        }
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()

    applied = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "feature-condition-restrictions"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "stun_self",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert applied.status_code == 200, applied.text
    updated = applied.json()["actor"]
    assert "震慑" in updated["conditions"]
    assert updated["action_available"] is False
    assert updated["bonus_action_available"] is False
    assert updated["reaction_available"] is False
    assert updated["speed_ft"] == 0
    assert updated["movement_remaining_ft"] == 0


def test_rage_feature_automatically_applies_physical_resistance(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "狂暴者",
            "class_name": "野蛮人",
            "resources": {"rage": {"current": 1, "max": 1}},
        },
    )
    assert character_response.status_code == 201
    character = character_response.json()
    combatant = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "snapshot_json": {
                "feature_runtime": {
                    "actions": {
                        "rage": {
                            "name": "狂暴",
                            "kind": "feature_action",
                            "action_cost": "bonus_action",
                            "resource_key": "rage",
                            "resource_cost": 1,
                            "target": "self",
                            "effects": [{"kind": "activate_condition", "condition": "raging"}],
                        }
                    }
                },
                "conditional_damage_defenses": [
                    {
                        "id": "rage:physical_resistance",
                        "condition": "raging",
                        "operation": "resistance",
                        "damage_types": ["slashing"],
                    }
                ],
            },
        },
    )
    assert combatant.status_code == 200, combatant.text
    actor = combatant.json()
    rage = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "rage-feature"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "rage",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert rage.status_code == 200, rage.text
    actor = rage.json()["actor"]
    assert "raging" in actor["conditions"]
    damage = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "rage-resistance"},
        json={
            "action_type": "damage",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
            "amount": 9,
            "damage_type": "slashing",
        },
    )
    assert damage.status_code == 200, damage.text
    assert damage.json()["action"]["result_json"]["adjusted_damage"] == 4


def test_hide_requires_dm_result_and_search_reveals_runtime_state(
    combat_client: TestClient,
) -> None:
    campaign, combat, hider = _setup(combat_client)
    searcher = _add_combatant(combat_client, campaign, combat, name="Searcher", initiative=10)
    hidden = combat_client.post(
        f"{_root(campaign, combat)}/maneuvers/confirm",
        headers={"X-Request-ID": "hide-confirmed"},
        json={
            "action_type": "hide",
            "actor_combatant_id": hider["id"],
            "actor_version": hider["version"],
            "outcome": "success",
            "adjudication_note": "DM确认已有足够遮蔽，敏捷（隐匿）检定成功",
        },
    )
    assert hidden.status_code == 200, hidden.text
    hider = hidden.json()["actor"]
    assert "隐藏" in hider["conditions"]

    advanced = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "to-searcher"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200
    searcher = advanced.json()["active_combatant"]
    searched = combat_client.post(
        f"{_root(campaign, combat)}/maneuvers/confirm",
        headers={"X-Request-ID": "search-confirmed"},
        json={
            "action_type": "search",
            "actor_combatant_id": searcher["id"],
            "actor_version": searcher["version"],
            "target_combatant_id": hider["id"],
            "target_version": hider["version"],
            "outcome": "success",
            "adjudication_note": "DM确认感知检定超过隐匿结果，目标被发现",
        },
    )
    assert searched.status_code == 200, searched.text
    assert searched.json()["action"]["result_json"]["revealed"] is True
    assert "隐藏" not in searched.json()["target"]["conditions"]
    assert searched.json()["effect"] is None


def test_help_is_versioned_and_consumed_by_adjudicated_attack(
    combat_client: TestClient,
) -> None:
    campaign, combat, helper = _setup(combat_client)
    ally = _add_combatant(combat_client, campaign, combat, name="Ally", initiative=10)
    enemy = _add_combatant(combat_client, campaign, combat, name="Enemy", initiative=0)
    helped = combat_client.post(
        f"{_root(campaign, combat)}/maneuvers/confirm",
        headers={"X-Request-ID": "help-ally"},
        json={
            "action_type": "help",
            "actor_combatant_id": helper["id"],
            "actor_version": helper["version"],
            "target_combatant_id": ally["id"],
            "target_version": ally["version"],
            "help_trigger": "Ally 对 Enemy 的下一次攻击",
            "adjudication_note": "DM确认协助方式可行且目标在可协助范围内",
        },
    )
    assert helped.status_code == 200, helped.text
    help_effect = helped.json()["effect"]
    assert "受助" in helped.json()["target"]["conditions"]

    advanced = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "to-helped-ally"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200
    ally = advanced.json()["active_combatant"]
    attacked = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "consume-help"},
        json={
            "action_type": "damage",
            "is_attack": True,
            "action_cost": "action",
            "actor_combatant_id": ally["id"],
            "actor_version": ally["version"],
            "target_combatant_id": enemy["id"],
            "target_version": enemy["version"],
            "amount": 4,
            "damage_type": "piercing",
            "help_effect_id": help_effect["id"],
            "help_effect_version": help_effect["version"],
            "attack_roll_mode": "advantage",
            "attack_adjudication_note": "DM确认 Help 适用于本次攻击并以优势命中",
        },
    )
    assert attacked.status_code == 200, attacked.text
    assert help_effect["id"] in attacked.json()["action"]["result_json"]["consumed_effect_ids"]
    updated_ally = combat_client.get(_combatant_path(campaign, combat, ally["id"])).json()
    assert "受助" not in updated_ally["conditions"]
    effects = combat_client.get(f"{_root(campaign, combat)}/effects").json()["items"]
    assert next(row for row in effects if row["id"] == help_effect["id"])["status"] == "ended"


def test_ready_trigger_spends_reaction_off_turn_and_ends_state(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    _add_combatant(combat_client, campaign, combat, name="Trigger source", initiative=10)
    prepared = combat_client.post(
        f"{_root(campaign, combat)}/maneuvers/confirm",
        headers={"X-Request-ID": "ready-prepare"},
        json={
            "action_type": "ready",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "ready_trigger": "敌人进入门口",
            "ready_response": "射出一箭",
            "adjudication_note": "DM确认触发和响应均明确可执行",
        },
    )
    assert prepared.status_code == 200, prepared.text
    actor = prepared.json()["actor"]
    ready_effect = prepared.json()["effect"]

    advanced = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "ready-off-turn"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200
    triggered = combat_client.post(
        f"{_root(campaign, combat)}/maneuvers/confirm",
        headers={"X-Request-ID": "ready-trigger"},
        json={
            "action_type": "ready",
            "ready_phase": "trigger",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "ready_effect_id": ready_effect["id"],
            "ready_effect_version": ready_effect["version"],
            "outcome": "success",
            "adjudication_note": "DM确认敌人已进入门口，触发成立",
        },
    )
    assert triggered.status_code == 200, triggered.text
    assert triggered.json()["actor"]["reaction_available"] is False
    assert "准备" not in triggered.json()["actor"]["conditions"]
    assert triggered.json()["effect"]["status"] == "ended"
    assert triggered.json()["action"]["result_json"]["prepared_response"] == "射出一箭"


def test_turn_start_enforces_stunned_economy_and_turn_end_save_is_a_prompt(
    combat_client: TestClient,
) -> None:
    campaign, combat, first = _setup(combat_client)
    second = _add_combatant(combat_client, campaign, combat, name="Stunned target", initiative=10)
    stunned = combat_client.patch(
        _combatant_path(campaign, combat, second["id"]),
        headers={"If-Match": f'"{second["version"]}"'},
        json={"conditions": ["stunned"]},
    )
    assert stunned.status_code == 200
    second = stunned.json()
    save_effect = combat_client.post(
        f"{_root(campaign, combat)}/effects/confirm",
        headers={"X-Request-ID": "until-save-effect"},
        json={
            "target_combatant_id": first["id"],
            "target_version": first["version"],
            "name": "等待回合末豁免",
            "effect_type": "condition",
            "duration_unit": "until_save",
            "save_dc": 14,
            "save_ability": "wisdom",
        },
    )
    assert save_effect.status_code == 200, save_effect.text
    advanced = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "to-stunned-with-save-prompt"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    active = advanced.json()["active_combatant"]
    assert active["id"] == second["id"]
    assert active["movement_remaining_ft"] == 0
    assert active["action_available"] is False
    assert active["bonus_action_available"] is False
    assert active["reaction_available"] is False
    prompt = next(
        row
        for row in advanced.json()["effect_prompts"]
        if row["effect_id"] == save_effect.json()["effect"]["id"]
    )
    assert prompt["timing"] == "turn_end"
    assert prompt["save_dc"] == 14
    assert prompt["pending_action_id"]
    assert save_effect.json()["effect"]["status"] == "active"

    blocked = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "blocked-by-repeat-save"},
        json={"combat_version": advanced.json()["combat"]["version"]},
    )
    assert blocked.status_code == 400, blocked.text
    assert "回合末重复豁免请求未结算" in blocked.json()["message"]

    resolved = combat_client.post(
        f"{_root(campaign, combat)}/effects/{save_effect.json()['effect']['id']}"
        "/save/confirm",
        headers={"X-Request-ID": "resolve-persisted-repeat-save"},
        json={
            "target_combatant_id": first["id"],
            "target_version": save_effect.json()["target"]["version"],
            "roll_total": 14,
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["success"] is True

    continued = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "after-repeat-save"},
        json={"combat_version": advanced.json()["combat"]["version"]},
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["active_combatant"]["id"] == first["id"]


def test_feature_condition_respects_condition_immunity(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "condition_immunities": ["狂暴"],
            "snapshot_json": {
                "feature_runtime": {
                    "actions": {
                        "rage": {
                            "name": "狂暴",
                            "kind": "feature_action",
                            "action_cost": "bonus_action",
                            "target": "self",
                            "effects": [
                                {"kind": "activate_condition", "condition": "raging"}
                            ],
                        }
                    }
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    rejected = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "immune-feature-condition"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "rage",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "免疫状态" in rejected.json()["message"]
    unchanged = combat_client.get(
        _combatant_path(campaign, combat, actor["id"])
    ).json()
    assert unchanged["conditions"] == []
    assert unchanged["bonus_action_available"] is True


def test_use_item_consumes_owned_inventory_and_spends_action(
    combat_client: TestClient,
) -> None:
    campaign_response = combat_client.post(
        "/api/v1/campaigns", json={"name": "物品动作验收团"}
    )
    campaign = campaign_response.json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = combat_client.post(
        f"{base}/characters",
        json={"name": "持有者", "class_name": "战士", "hp": 20, "max_hp": 20},
    ).json()
    combat = combat_client.post(f"{base}/combats", json={"name": "物品战斗"}).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "持有者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    item = combat_client.post(
        f"{base}/items",
        json={
            "name": "治疗药水",
            "category": "potion",
            "quantity": 1,
            "owner_character_id": character["id"],
        },
    ).json()

    response = combat_client.post(
        f"{base}/combats/{combat['id']}/maneuvers/confirm",
        headers={"X-Request-ID": "use-item-confirmed"},
        json={
            "action_type": "use_item",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "item_id": item["id"],
            "item_version": item["version"],
            "outcome": "success",
            "adjudication_note": "DM 确认使用治疗药水；治疗效果由法术/物品规则另行结算",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["action"]["result_json"]["item_consumed"] is True
    assert response.json()["actor"]["action_available"] is False
    remaining_items = combat_client.get(
        f"{base}/items?owner_character_id={character['id']}"
    ).json()["items"]
    assert remaining_items == []


def test_object_interaction_changes_scene_object_state_with_version_check(
    combat_client: TestClient,
) -> None:
    campaign = combat_client.post(
        "/api/v1/campaigns", json={"name": "物件互动验收团"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": "门厅"}).json()
    grid_response = combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 8, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid_response.status_code == 201, grid_response.text
    scene_object_response = combat_client.post(
        f"{base}/scenes/{scene['id']}/objects",
        json={"object_type": "door", "label": "铁门", "row": 1, "col": 1, "state": "closed"},
    )
    assert scene_object_response.status_code == 201, scene_object_response.text
    scene_object = scene_object_response.json()
    combat = combat_client.post(
        f"{base}/combats", json={"name": "门厅战斗", "scene_id": scene["id"]}
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={"display_name": "开门者", "initiative": 20, "hp": 20, "max_hp": 20},
    ).json()

    response = combat_client.post(
        f"{base}/combats/{combat['id']}/maneuvers/confirm",
        headers={"X-Request-ID": "object-interaction-confirmed"},
        json={
            "action_type": "object_interaction",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "object_id": scene_object["id"],
            "object_version": scene_object["version"],
            "object_state": "open",
            "outcome": "success",
            "adjudication_note": "DM 确认角色拉开铁门",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["action"]["result_json"]["object_state_after"] == "open"
    assert response.json()["object"]["state"] == "open"
