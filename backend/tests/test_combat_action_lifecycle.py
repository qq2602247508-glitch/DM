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
from dnd_dm_assistant.domain.advancement_choices import (
    subclass_feature_runtime_definition,
    subclass_runtime_grants,
)
from dnd_dm_assistant.domain.feature_runtime import feature_runtime_definition


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


def _relentless_rage_intervention() -> dict[str, Any]:
    return {
        "id": "relentless_rage:zero_hit_points_save",
        "kind": "zero_hp_intervention",
        "trigger": "would_drop_to_zero_hit_points",
        "eligibility": {
            "entity_types": ["character"],
            "required_conditions": ["raging"],
            "level": {
                "class_names": ["野蛮人", "barbarian"],
                "minimum": 1,
                "bind_as": "barbarian_level",
            },
        },
        "saving_throw": {
            "ability": "constitution",
            "initial_dc": 10,
            "increase_after_success": 5,
        },
        "success": {"kind": "restore_hit_points", "amount": "2*barbarian_level"},
        "failure": {"kind": "continue_zero_hp_lifecycle"},
        "exceptions": ["outright_death"],
        "state": {
            "key": "relentless_rage_state",
            "current_dc_field": "current_dc",
            "reset_reason": "short_or_long_rest",
        },
        "resets": ["short_rest", "long_rest"],
        "presentation": {
            "action_name": "坚韧狂暴",
            "result_key": "relentless_rage",
            "prompt_idempotency_prefix": "relentless-rage-save",
            "prompt_result_id_key": "relentless_rage_save_prompt_id",
        },
    }


def test_guarded_mind_turn_start_clears_selected_condition_and_replays_idempotently(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "意念守护测试者",
            "class_name": "战士",
            "resources": {
                "psionic_dice:战士": {
                    "label": "战士灵能骰",
                    "current": 8,
                    "max": 8,
                    "die_size": 8,
                    "resource_kind": "psionic_dice",
                }
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    registry = {
        "combat_start": {
            "defenses": [
                {
                    "id": "guarded_mind:psychic_resistance",
                    "kind": "damage_resistance",
                    "damage_types": ["psychic"],
                    "applies_when": "always",
                }
            ]
        },
        "actions": {
            "guarded_mind_clear": {
                "id": "guarded_mind_clear",
                "name": "意念守护（清除控制）",
                "kind": "feature_action",
                "action_cost": "none",
                "activation_window": "turn_start",
                "resource_key": "psionic_dice:战士",
                "resource_cost": 1,
                "target": "self",
                "resolution_kind": "condition_removal",
                "condition_removal_options": ["charmed", "frightened"],
                "effects": [{"kind": "condition_removal"}],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action",
                    "effect_kinds": ["condition_removal"],
                },
            }
        },
    }
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "conditions": ["charmed", "frightened"],
            "snapshot_json": {
                "feature_runtime": registry,
                "conditional_damage_defenses": registry["combat_start"]["defenses"],
            },
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    feature_path = f"{_root(campaign, combat)}/feature-actions/confirm"
    request_id = "guarded-mind-clear-charmed"
    resolved = combat_client.post(
        feature_path,
        headers={"X-Request-ID": request_id},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "guarded_mind_clear",
            "condition_to_remove": "charmed",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["actor"]["conditions"] == ["frightened"]
    assert body["result"]["resource_key"] == "psionic_dice:战士"
    assert body["result"]["resource_before"] == 8
    assert body["result"]["resource_after"] == 7
    replay = combat_client.post(
        feature_path,
        headers={"X-Request-ID": request_id},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "guarded_mind_clear",
            "condition_to_remove": "charmed",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    assert replay.json()["actor"]["conditions"] == ["frightened"]
    assert replay.json()["actor"]["version"] == body["actor"]["version"]


def test_peerless_athlete_consumes_channel_divinity_once_and_persists_all_modifiers(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "绝伦健将测试者",
            "class_name": "圣武士",
            "level": 3,
            "resources": {
                "channel_divinity": {
                    "label": "引导神力",
                    "current": 2,
                    "max": 2,
                    "recovery": "short_rest",
                }
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    runtime = subclass_feature_runtime_definition(
        {
            "name": "绝伦健将 Peerless",
            "class_name": "圣武士",
            "subclass_name": "荣耀之誓",
            "class_level": 3,
        }
    )
    assert runtime is not None
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "snapshot_json": {"feature_runtime": runtime},
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    request = {
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "feature_id": "peerless_athlete",
        "target_combatant_id": actor["id"],
        "target_version": actor["version"],
    }
    feature_path = f"{_root(campaign, combat)}/feature-actions/confirm"
    resolved = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "peerless-athlete-0001"},
        json=request,
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["result"]["resource_key"] == "channel_divinity"
    assert body["result"]["resource_before"] == 2
    assert body["result"]["resource_after"] == 1
    modifiers = body["actor"]["snapshot_json"]["timed_feature_modifiers"]
    assert len(modifiers) == 3
    assert {item["modifier"]["stat"] for item in modifiers} == {
        "skill_check",
        "jump_distance_ft",
    }
    assert {
        item["modifier"].get("skill")
        for item in modifiers
        if item["modifier"]["stat"] == "skill_check"
    } == {"运动", "特技"}
    assert all(item["expires_on"] == "long_rest" for item in modifiers)

    replay = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "peerless-athlete-0001"},
        json=request,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    assert replay.json()["actor"]["version"] == body["actor"]["version"]

    conflict = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "peerless-athlete-0002"},
        json=request,
    )
    assert conflict.status_code == 409, conflict.text


def test_batch_buff_condition_gates_flight_and_resistance_end_to_end(
    combat_client: TestClient,
) -> None:
    """One generated batch entry runs through the real feature-action chain.

    神之狂暴 activates a long-rest-bounded condition; the movement-mode and
    damage-resistance resolvers consume the gated entries only while the
    condition is active.  Replay is idempotent and a stale version is rejected.
    """

    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "神之狂暴测试者",
            "class_name": "野蛮人",
            "level": 14,
            "speed_ft": 30,
            "resources": {
                "divine_rage": {
                    "label": "神之狂暴",
                    "current": 1,
                    "max": 1,
                    "recovery": "long_rest",
                }
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    grants = subclass_runtime_grants(
        {
            "name": "狂热者道途",
            "feature_definitions": [
                {
                    "id": "fanatic:14:divine-rage",
                    "name": "神之狂暴 Rage of the Gods",
                    "class_level": 14,
                    "description": (
                        "当你激活狂暴时，你可以呈现出圣斗士姿态。持续1分钟。"
                        "处于圣斗士姿态期间，你具有飞行速度和暗蚀、心灵、光耀抗性。"
                    ),
                }
            ],
        },
        class_name="野蛮人",
        target_class_level=14,
        current_class_level=14,
    )
    grant = next(item for item in grants["grants"] if item["class_level"] == 14)
    runtime = grant["runtime"]["registry"]
    action_id = "野蛮人:狂热者道途:divine_rage"
    assert action_id in runtime["actions"]
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "speed_ft": 30,
            "snapshot_json": {"feature_runtime": runtime},
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    request = {
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "feature_id": action_id,
        "target_combatant_id": actor["id"],
        "target_version": actor["version"],
    }
    feature_path = f"{_root(campaign, combat)}/feature-actions/confirm"
    resolved = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "divine-rage-0001"},
        json=request,
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert "divine_rage" in body["actor"]["conditions"]
    assert body["result"]["resource_key"] == "divine_rage"
    assert body["result"]["resource_before"] == 1
    assert body["result"]["resource_after"] == 0
    actor = body["actor"]
    advanced = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "divine-rage-advance"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    refreshed = combat_client.get(_combatant_path(campaign, combat, actor["id"]))
    assert refreshed.status_code == 200, refreshed.text
    actor = refreshed.json()
    assert "divine_rage" in actor["conditions"]
    movement_modes = actor["snapshot_json"].get("active_movement_modes") or {}
    assert movement_modes.get("fly") == 30

    replay = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "divine-rage-0001"},
        json=request,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    assert "divine_rage" in replay.json()["actor"]["conditions"]

    conflict = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "divine-rage-0002"},
        json={**request, "actor_version": actor["version"] + 1},
    )
    assert conflict.status_code == 409, conflict.text


def test_rage_activation_grants_vitality_surge_temporary_hp(
    combat_client: TestClient,
) -> None:
    """圣树活力 fires on rage activation through the generic trigger hook."""

    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "圣树活力测试者",
            "class_name": "野蛮人",
            "level": 3,
            "hp": 20,
            "max_hp": 20,
            "resources": {
                "rage": {
                    "label": "狂暴",
                    "current": 2,
                    "max": 2,
                    "recovery": "long_rest",
                }
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    grants = subclass_runtime_grants(
        {
            "name": "世界树道途",
            "feature_definitions": [
                {
                    "id": "world-tree:3:vitality",
                    "name": "圣树活力",
                    "class_level": 3,
                    "description": "当你激活狂暴时，你获得等于你野蛮人等级的临时生命值。",
                }
            ],
        },
        class_name="野蛮人",
        target_class_level=3,
        current_class_level=3,
    )
    vitality_grant = next(
        item for item in grants["grants"] if item["class_level"] == 3
    )
    vitality_runtime = vitality_grant["runtime"]["registry"]
    assert "after_rage_activation" in [
        str(trigger.get("event")) for trigger in vitality_runtime.get("triggers", [])
    ]
    rage_runtime = feature_runtime_definition(
        feature_name="狂暴",
        class_name="野蛮人",
        class_level=1,
    )
    assert rage_runtime is not None
    merged_runtime = {
        "combat_start": {
            "modifiers": [
                *((rage_runtime.get("combat_start") or {}).get("modifiers") or ()),
                *((vitality_runtime.get("combat_start") or {}).get("modifiers") or ()),
            ],
            "defenses": [
                *((rage_runtime.get("combat_start") or {}).get("defenses") or ()),
                *((vitality_runtime.get("combat_start") or {}).get("defenses") or ()),
            ],
        },
        "resources": dict(rage_runtime.get("resources") or {}),
        "actions": {
            **dict(rage_runtime.get("actions") or {}),
            **dict(vitality_runtime.get("actions") or {}),
        },
        "triggers": [
            *list(rage_runtime.get("triggers") or ()),
            *list(vitality_runtime.get("triggers") or ()),
        ],
        "attack_riders": [],
    }
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "snapshot_json": {
                "feature_runtime": merged_runtime,
                "equipment": [],
                "class_levels": {"野蛮人": 3},
            },
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    rage_action_id = next(
        key for key, value in merged_runtime["actions"].items() if value.get("id") == "rage"
    )
    feature_path = f"{_root(campaign, combat)}/feature-actions/confirm"
    resolved = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "rage-vitality-0001"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": rage_action_id,
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert "raging" in body["actor"]["conditions"]
    assert body["actor"]["temporary_hp"] == 3
    assert body["result"]["rage_activation_triggers"][0]["effects"][0][
        "temporary_hp_after"
    ] == 3


def _lay_on_hands_fixture(
    client: TestClient,
    *,
    target_conditions: list[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    campaign, combat, _ = _setup(client)
    character_response = client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "圣疗状态测试者",
            "class_name": "圣武士",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "resources": {
                "lay_on_hands": {
                    "label": "圣疗",
                    "current": 20,
                    "max": 25,
                    "recovery": "long_rest",
                }
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    runtime_action = {
        "id": "lay_on_hands",
        "name": "圣疗",
        "kind": "feature_action",
        "action_cost": "bonus_action",
        "resource_key": "lay_on_hands",
        "resource_cost": 0,
        "resource_cost_mode": "amount_or_condition",
        "condition_cure_cost": 5,
        "condition_cure_options": [
            "blinded",
            "charmed",
            "deafened",
            "diseased",
            "frightened",
            "paralyzed",
            "poisoned",
            "stunned",
        ],
        "target": "ally_or_self",
        "resolution_kind": "healing",
        "healing_formula": "lay_on_hands_pool",
        "effects": [{"kind": "healing"}, {"kind": "condition_cure"}],
    }
    paladin_response = client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "圣疗状态测试者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 30,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 1},
                "feature_runtime": {"actions": {"lay_on_hands": runtime_action}},
            },
        },
    )
    assert paladin_response.status_code == 201, paladin_response.text
    paladin = paladin_response.json()
    target_response = client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "待解除状态盟友",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "conditions": target_conditions,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 2},
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    return campaign, combat, paladin, target_response.json(), character


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


def test_failed_player_save_persists_feature_reroll_window_before_resolution(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "不屈目标",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "feature_saving_throw_rerolls": [
                    {"feature_id": "indomitable", "source": "不屈", "available": True}
                ]
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    prompt = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/pending",
        headers={"X-Request-ID": "reroll-window-prompt"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_name": "恐惧波动",
            "resolution_type": "saving_throw",
            "dc": 15,
            "ability": "wisdom",
            "damage_on_failure": 12,
            "damage_type": "psychic",
        },
    )
    assert prompt.status_code == 200, prompt.text
    action = prompt.json()["action"]

    first = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "reroll-window-first"},
        json={"action_version": action["version"], "roll_total": 5},
    )
    assert first.status_code == 200, first.text
    assert first.json()["resolution"]["phase"] == "awaiting_feature_reroll"
    assert first.json()["action"]["status"] == "previewed"
    assert first.json()["target"]["hp"] == 20
    assert first.json()["action"]["result_json"]["feature_reroll_window"]["source"] == "不屈"

    second = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "reroll-window-second"},
        json={
            "action_version": first.json()["action"]["version"],
            "roll_total": 5,
            "roll_totals": [5, 18],
            "use_feature_reroll": True,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["resolution"]["phase"] == "resolved"
    assert second.json()["resolution"]["success"] is True
    assert second.json()["resolution"]["feature_reroll_consumed"]["after"] == 0
    assert second.json()["target"]["hp"] == 20


def test_stroke_of_luck_replaces_failed_d20_and_consumes_authoritative_resource(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "幸运一击测试者",
            "class_name": "游荡者",
            "level": 20,
            "resources": {"stroke_of_luck": {"current": 1, "max": 1}},
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    runtime_action = {
        "id": "stroke_of_luck",
        "name": "幸运一击",
        "kind": "feature_action",
        "action_cost": "none",
        "resource_key": "stroke_of_luck",
        "resource_cost": 1,
        "target": "self",
        "resolution_kind": "d20_replacement",
        "activation_window": "after_failed_d20_test",
        "trigger": {"event": "d20_test_failed", "timing": "after_result"},
        "replacement": {"d20_roll": 20},
        "effects": [{"kind": "replace_d20_roll", "replacement": 20}],
        "runtime_execution": {
            "status": "ready",
            "consumer": "player_roll_resolution",
        },
    }
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "幸运一击测试者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "feature_runtime": {
                    "actions": {"stroke_of_luck": runtime_action},
                    "resources": {"stroke_of_luck": {"current": 1, "max": 1}},
                }
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    prompt_body = {
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "action_cost": "none",
        "action_name": "困难检定",
        "resolution_type": "ability_check",
        "dc": 15,
        "ability": "dexterity",
    }
    prompt = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/pending",
        headers={"X-Request-ID": "stroke-prompt"},
        json=prompt_body,
    )
    assert prompt.status_code == 200, prompt.text
    action = prompt.json()["action"]

    first = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "stroke-first"},
        json={"action_version": action["version"], "roll_total": 5},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["resolution"]["phase"] == "awaiting_stroke_of_luck"
    assert first_body["resolution"]["stroke_of_luck_window"]["original_roll_total"] == 5
    assert first_body["target"]["hp"] == 20

    second = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "stroke-second"},
        json={
            "action_version": first_body["action"]["version"],
            "roll_total": 5,
            "use_stroke_of_luck": True,
            "stroke_of_luck_total": 18,
        },
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["resolution"]["phase"] == "resolved"
    assert body["resolution"]["success"] is True
    assert body["resolution"]["roll_total"] == 18
    assert body["resolution"]["reported_roll_totals"] == [5]
    assert body["resolution"]["stroke_of_luck_total"] == 18
    assert body["resolution"]["stroke_of_luck_consumed"]["before"] == 1
    assert body["resolution"]["stroke_of_luck_consumed"]["after"] == 0

    character_after = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    )
    assert character_after.status_code == 200, character_after.text
    assert character_after.json()["resources"]["stroke_of_luck"]["current"] == 0

    replay = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "stroke-second-replay"},
        json={
            "action_version": first_body["action"]["version"],
            "roll_total": 5,
            "use_stroke_of_luck": True,
            "stroke_of_luck_total": 18,
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["resolution"]["stroke_of_luck_consumed"]["after"] == 0
    assert replay.json()["target"]["hp"] == 20

    no_resource_prompt = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/pending",
        headers={"X-Request-ID": "stroke-no-resource-prompt"},
        json={**prompt_body, "target_version": target["version"]},
    )
    assert no_resource_prompt.status_code == 200, no_resource_prompt.text
    no_resource_action = no_resource_prompt.json()["action"]
    no_resource = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{no_resource_action['id']}/confirm",
        headers={"X-Request-ID": "stroke-no-resource-confirm"},
        json={"action_version": no_resource_action["version"], "roll_total": 5},
    )
    assert no_resource.status_code == 200, no_resource.text
    assert no_resource.json()["resolution"]["phase"] == "resolved"
    assert no_resource.json()["resolution"].get("stroke_of_luck_window") is None


def test_bardic_inspiration_player_roll_api_adds_and_consumes_die(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "激励骰玩家",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "feature_dice": {
                    "bardic_inspiration_die": {
                        "source": "吟游诗人激励",
                        "value": "D6",
                        "available": True,
                    }
                }
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    prompt = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/pending",
        headers={"X-Request-ID": "bardic-api-prompt"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_name": "关键说服",
            "resolution_type": "ability_check",
            "dc": 15,
            "ability": "charisma",
        },
    )
    assert prompt.status_code == 200, prompt.text
    action = prompt.json()["action"]

    confirmed = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "bardic-api-confirm"},
        json={
            "action_version": action["version"],
            "roll_total": 10,
            "bardic_inspiration_total": 5,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["resolution"]["roll_total"] == 15
    assert body["resolution"]["success"] is True
    assert body["resolution"]["feature_dice_consumed"]["value"] == 5
    assert (
        body["target"]["snapshot_json"]["feature_dice"]["bardic_inspiration_die"][
            "available"
        ]
        is False
    )


def test_bardic_inspiration_rejects_duplicate_available_die_without_spending(
    combat_client: TestClient,
) -> None:
    campaign, combat, _ = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "重复激励测试诗人",
            "class_name": "吟游诗人",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "resources": {
                "bardic_inspiration": {
                    "label": "吟游诗人激励",
                    "current": 2,
                    "max": 2,
                }
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    action = {
        "id": "bardic_inspiration",
        "name": "吟游诗人激励",
        "kind": "feature_action",
        "action_cost": "bonus_action",
        "resource_key": "bardic_inspiration",
        "resource_cost": 1,
        "target": "ally_or_self",
        "target_policy": {
            "mode": "ally_or_self",
            "same_faction": True,
            "range_ft": 60,
        },
        "resolution_kind": "grant_dice",
        "effects": [{"kind": "grant_roll_die", "die_key": "bardic_inspiration_die"}],
    }
    registry = {
        "resources": {
            "bardic_inspiration_die": {"value": "D8"},
        },
        "actions": {"bardic_inspiration": action},
    }
    bard_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "重复激励测试诗人",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 30,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 1},
                "feature_runtime": registry,
            },
        },
    )
    assert bard_response.status_code == 201, bard_response.text
    bard = bard_response.json()
    existing_target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "已有激励骰目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 2},
                "feature_dice": {
                    "bardic_inspiration_die": {
                        "source": "先前吟游诗人",
                        "value": "D8",
                        "available": True,
                    }
                },
            },
        },
    )
    assert existing_target_response.status_code == 201, existing_target_response.text
    existing_target = existing_target_response.json()

    rejected = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "bardic-duplicate-die"},
        json={
            "actor_combatant_id": bard["id"],
            "actor_version": bard["version"],
            "feature_id": "bardic_inspiration",
            "target_combatant_id": existing_target["id"],
            "target_version": existing_target["version"],
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "不能同时持有两枚同类职业骰" in rejected.text

    unchanged_bard = combat_client.get(
        _combatant_path(campaign, combat, bard["id"])
    ).json()
    assert unchanged_bard["version"] == bard["version"]
    assert unchanged_bard["bonus_action_available"] is True
    unchanged_character = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert unchanged_character["resources"]["bardic_inspiration"]["current"] == 2
    unchanged_target = combat_client.get(
        _combatant_path(campaign, combat, existing_target["id"])
    ).json()
    assert (
        unchanged_target["snapshot_json"]["feature_dice"]["bardic_inspiration_die"][
            "available"
        ]
        is True
    )

    consumed_target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "已消费激励骰目标",
            "entity_type": "character",
            "initiative": 5,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 3},
                "feature_dice": {
                    "bardic_inspiration_die": {
                        "source": "先前吟游诗人",
                        "value": "D8",
                        "available": False,
                    }
                },
            },
        },
    )
    assert consumed_target_response.status_code == 201, consumed_target_response.text
    consumed_target = consumed_target_response.json()
    granted = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "bardic-grant-after-consumed"},
        json={
            "actor_combatant_id": bard["id"],
            "actor_version": bard["version"],
            "feature_id": "bardic_inspiration",
            "target_combatant_id": consumed_target["id"],
            "target_version": consumed_target["version"],
        },
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["result"]["roll_die_granted"] == {
        "die_key": "bardic_inspiration_die",
        "value": "D8",
    }
    assert granted.json()["actor"]["bonus_action_available"] is False
    assert combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()["resources"]["bardic_inspiration"]["current"] == 1
    assert (
        granted.json()["target"]["snapshot_json"]["feature_dice"][
            "bardic_inspiration_die"
        ]["available"]
        is True
    )


def test_feature_resource_reroll_opens_after_failure_and_uses_second_roll(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "不屈资源角色",
            "class_name": "战士",
            "level": 9,
            "hp": 20,
            "max_hp": 20,
            "resources": {"indomitable": {"current": 1, "max": 1}},
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "自动不屈目标",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    registry = {
        "resources": {"indomitable": {"current": 1, "max": 1}},
        "actions": {
            "indomitable": {
                "id": "indomitable",
                "name": "不屈",
                "kind": "feature_action",
                "resource_key": "indomitable",
                "resource_cost": 1,
                "resolution_kind": "saving_throw_reroll",
                "activation_window": "after_failed_saving_throw",
            }
        },
    }
    patched = combat_client.patch(
        _combatant_path(campaign, combat, target["id"]),
        headers={"If-Match": f'"{target["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "snapshot_json": {"feature_runtime": registry},
        },
    )
    assert patched.status_code == 200, patched.text
    target = patched.json()
    prompt = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/pending",
        headers={"X-Request-ID": "resource-reroll-prompt"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_name": "恐惧波动",
            "resolution_type": "saving_throw",
            "dc": 15,
            "ability": "wisdom",
            "damage_on_failure": 12,
            "damage_type": "psychic",
        },
    )
    assert prompt.status_code == 200, prompt.text
    action = prompt.json()["action"]
    first = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "resource-reroll-first"},
        json={"action_version": action["version"], "roll_total": 5},
    )
    assert first.status_code == 200, first.text
    window = first.json()["resolution"]["feature_reroll_window"]
    assert window["feature_id"] == "indomitable"
    assert window["resource_key"] == "indomitable"
    second = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "resource-reroll-second"},
        json={
            "action_version": first.json()["action"]["version"],
            "roll_total": 18,
            "roll_totals": [18, 5],
            "use_feature_reroll": True,
        },
    )
    assert second.status_code == 200, second.text
    resolution = second.json()["resolution"]
    assert resolution["phase"] == "resolved"
    assert resolution["success"] is False
    assert resolution["roll_total"] == 5
    assert resolution["feature_reroll_consumed"]["resource"] == "indomitable"
    assert resolution["damage"] == 12
    character_after = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    )
    assert character_after.status_code == 200, character_after.text
    assert character_after.json()["resources"]["indomitable"]["current"] == 0


def test_countercharm_opens_unique_ally_reaction_and_consumes_reaction_on_advantage(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "魅惑目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 1},
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    bard_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "反迷惑吟游诗人",
            "entity_type": "character",
            "initiative": 5,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 2},
                "feature_runtime": {
                    "actions": {
                        "countercharm": {
                            "id": "countercharm",
                            "name": "反迷惑",
                            "kind": "feature_action",
                            "action_cost": "reaction",
                            "resolution_kind": "saving_throw_reroll",
                            "activation_window": "after_failed_saving_throw",
                        }
                    }
                },
            },
        },
    )
    assert bard_response.status_code == 201, bard_response.text
    bard = bard_response.json()

    prompt = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/pending",
        headers={"X-Request-ID": "countercharm-prompt"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_name": "魅惑凝视",
            "resolution_type": "saving_throw",
            "dc": 15,
            "ability": "wisdom",
            "damage_on_failure": 12,
            "damage_type": "psychic",
            "conditions_on_failure": ["魅惑"],
            "condition_duration": "rounds",
            "condition_duration_value": 1,
        },
    )
    assert prompt.status_code == 200, prompt.text
    action = prompt.json()["action"]
    first = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "countercharm-first"},
        json={"action_version": action["version"], "roll_total": 5},
    )
    assert first.status_code == 200, first.text
    window = first.json()["resolution"]["feature_reroll_window"]
    assert window["feature_id"] == "countercharm"
    assert window["reroll_mode"] == "advantage"
    assert window["reaction_combatant_id"] == bard["id"]
    assert first.json()["target"]["hp"] == 20

    second = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "countercharm-second"},
        json={
            "action_version": first.json()["action"]["version"],
            "roll_total": 18,
            "roll_totals": [5, 18],
            "use_feature_reroll": True,
        },
    )
    assert second.status_code == 200, second.text
    resolution = second.json()["resolution"]
    assert resolution["success"] is True
    assert resolution["roll_total"] == 18
    assert resolution["damage"] == 0
    assert resolution["feature_reroll_consumed"] == {
        "feature_id": "countercharm",
        "resource": "reaction",
        "before": True,
        "after": False,
        "reaction_combatant_id": bard["id"],
    }
    bard_after = combat_client.get(
        _combatant_path(campaign, combat, bard["id"])
    ).json()
    assert bard_after["reaction_available"] is False


def test_lay_on_hands_heals_adjacent_ally_and_spends_pool_amount(
    combat_client: TestClient,
) -> None:
    campaign, combat, _ = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "圣疗圣武士",
            "class_name": "圣武士",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "resources": {
                "lay_on_hands": {
                    "label": "圣疗",
                    "current": 20,
                    "max": 25,
                    "recovery": "long_rest",
                }
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    paladin_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "圣疗圣武士",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 30,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 1},
                "feature_runtime": {
                    "actions": {
                        "lay_on_hands": {
                            "id": "lay_on_hands",
                            "name": "圣疗",
                            "kind": "feature_action",
                            "action_cost": "bonus_action",
                            "resource_key": "lay_on_hands",
                            "resource_cost": 0,
                            "resource_cost_mode": "amount",
                            "target": "ally_or_self",
                            "resolution_kind": "healing",
                            "healing_formula": "lay_on_hands_pool",
                            "effects": [{"kind": "healing"}],
                        }
                    }
                },
            },
        },
    )
    assert paladin_response.status_code == 201, paladin_response.text
    paladin = paladin_response.json()
    ally_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "受伤盟友",
            "entity_type": "character",
            "initiative": 10,
            "hp": 5,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 2},
            },
        },
    )
    assert ally_response.status_code == 201, ally_response.text
    ally = ally_response.json()

    confirmed = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "lay-on-hands-adjacent"},
        json={
            "actor_combatant_id": paladin["id"],
            "actor_version": paladin["version"],
            "feature_id": "lay_on_hands",
            "healing_total": 10,
            "target_combatant_id": ally["id"],
            "target_version": ally["version"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["result"]
    assert result["healing"]["hp_gained"] == 10
    assert result["healing"]["remaining_hp"] == 15
    assert result["resource_before"] == 20
    assert result["resource_after"] == 10
    assert confirmed.json()["target"]["hp"] == 15
    updated_character = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert updated_character["resources"]["lay_on_hands"]["current"] == 10


def test_lay_on_hands_cures_poison_and_spends_fixed_pool_amount_idempotently(
    combat_client: TestClient,
) -> None:
    campaign, combat, paladin, target, character = _lay_on_hands_fixture(
        combat_client,
        target_conditions=["中毒"],
    )
    payload = {
        "actor_combatant_id": paladin["id"],
        "actor_version": paladin["version"],
        "feature_id": "lay_on_hands",
        "condition_to_cure": "poisoned",
        "target_combatant_id": target["id"],
        "target_version": target["version"],
    }
    confirmed = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "lay-on-hands-cure-poison"},
        json=payload,
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["result"]
    assert result["condition_cure"] == {
        "condition": "poisoned",
        "removed": True,
        "ended_effect_ids": [],
    }
    assert result["resource_before"] == 20
    assert result["resource_after"] == 15
    assert "中毒" not in confirmed.json()["target"]["conditions"]
    updated_character = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert updated_character["resources"]["lay_on_hands"]["current"] == 15

    replay = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "lay-on-hands-cure-poison"},
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    assert combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()["resources"]["lay_on_hands"]["current"] == 15


def test_lay_on_hands_rejects_curing_absent_condition_without_spending_pool(
    combat_client: TestClient,
) -> None:
    campaign, combat, paladin, target, character = _lay_on_hands_fixture(
        combat_client,
        target_conditions=["疾病"],
    )
    rejected = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "lay-on-hands-cure-absent"},
        json={
            "actor_combatant_id": paladin["id"],
            "actor_version": paladin["version"],
            "feature_id": "lay_on_hands",
            "condition_to_cure": "poisoned",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "没有要解除" in rejected.text
    assert combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()["resources"]["lay_on_hands"]["current"] == 20
    assert "疾病" in combat_client.get(
        _combatant_path(campaign, combat, target["id"])
    ).json()["conditions"]


def test_lay_on_hands_cures_extended_condition_from_restoring_touch(
    combat_client: TestClient,
) -> None:
    campaign, combat, paladin, target, character = _lay_on_hands_fixture(
        combat_client,
        target_conditions=["震慑"],
    )
    payload = {
        "actor_combatant_id": paladin["id"],
        "actor_version": paladin["version"],
        "feature_id": "lay_on_hands",
        "condition_to_cure": "stunned",
        "target_combatant_id": target["id"],
        "target_version": target["version"],
    }
    confirmed = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "lay-on-hands-cure-stunned"},
        json=payload,
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["result"]
    assert result["condition_cure"] == {
        "condition": "stunned",
        "removed": True,
        "ended_effect_ids": [],
    }
    assert result["resource_before"] == 20
    assert result["resource_after"] == 15
    assert "震慑" not in confirmed.json()["target"]["conditions"]
    assert combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()["resources"]["lay_on_hands"]["current"] == 15


def test_countercharm_requires_and_honors_selected_reactor_when_two_are_eligible(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "多重反迷惑目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 1, "col": 1},
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    reactor_ids: list[str] = []
    for index, initiative in enumerate((5, 4), start=1):
        response = combat_client.post(
            f"{_root(campaign, combat)}/combatants",
            json={
                "display_name": f"候选吟游诗人{index}",
                "entity_type": "character",
                "initiative": initiative,
                "hp": 20,
                "max_hp": 20,
                "snapshot_json": {
                    "disposition": "ally",
                    "grid_position": {"row": 1, "col": index + 1},
                    "feature_runtime": {
                        "actions": {
                            ("countercharm" if index == 1 else "fearward"): {
                                "id": "countercharm" if index == 1 else "fearward",
                                "name": "反迷惑" if index == 1 else "恐惧守望",
                                "kind": "feature_action",
                                "action_cost": "reaction",
                                "resolution_kind": "saving_throw_reroll",
                                "activation_window": "after_failed_saving_throw",
                                "trigger": {
                                    "event": "saving_throw_failed",
                                    "conditions": ["charmed", "frightened"],
                                    "range_ft": 30,
                                },
                                "reroll_mode": "advantage",
                            }
                        }
                    },
                },
            },
        )
        assert response.status_code == 201, response.text
        reactor_ids.append(response.json()["id"])

    prompt = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/pending",
        headers={"X-Request-ID": "countercharm-multiple-prompt"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_name": "魅惑凝视",
            "resolution_type": "saving_throw",
            "dc": 15,
            "ability": "wisdom",
            "damage_on_failure": 12,
            "damage_type": "psychic",
            "conditions_on_failure": ["魅惑"],
            "condition_duration": "rounds",
            "condition_duration_value": 1,
        },
    )
    assert prompt.status_code == 200, prompt.text
    action = prompt.json()["action"]
    first = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "countercharm-multiple-first"},
        json={"action_version": action["version"], "roll_total": 5},
    )
    assert first.status_code == 200, first.text
    window = first.json()["resolution"]["feature_reroll_window"]
    assert {item["reaction_combatant_id"] for item in window["reaction_candidates"]} == set(
        reactor_ids
    )

    second = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "countercharm-multiple-second"},
        json={
            "action_version": first.json()["action"]["version"],
            "roll_total": 18,
            "roll_totals": [5, 18],
            "use_feature_reroll": True,
            "feature_reroll_reactor_id": reactor_ids[1],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["resolution"]["success"] is True
    assert second.json()["resolution"]["feature_reroll_consumed"][
        "reaction_combatant_id"
    ] == reactor_ids[1]
    first_reactor = combat_client.get(
        _combatant_path(campaign, combat, reactor_ids[0])
    ).json()
    second_reactor = combat_client.get(
        _combatant_path(campaign, combat, reactor_ids[1])
    ).json()
    assert first_reactor["reaction_available"] is True
    assert second_reactor["reaction_available"] is False


def test_poisoned_skill_check_cancels_structured_advantage_through_api(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "中毒检定者",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "conditions": ["poisoned"],
            "snapshot_json": {
                "rule_modifiers": {
                    "skill_check:self:stealth": {
                        "stat": "skill_check",
                        "scope": "self",
                        "operation": "advantage",
                        "source": "可靠协助",
                    }
                }
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    prompt = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/pending",
        headers={"X-Request-ID": "poisoned-skill-check-api"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_name": "潜行",
            "resolution_type": "skill_check",
            "skill": "隐匿",
            "dc": 15,
        },
    )
    assert prompt.status_code == 200, prompt.text
    action = prompt.json()["action"]
    confirmed = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "poisoned-skill-check-roll"},
        json={
            "action_version": action["version"],
            "roll_total": 5,
            "roll_totals": [5, 18],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    resolution = confirmed.json()["resolution"]
    assert resolution["roll_total"] == 5
    assert resolution["success"] is False
    assert resolution["applied_defenses"] == [
        "ability_check_advantage_disadvantage_cancelled",
        "condition:poisoned_disadvantage_check",
    ]


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
                "actions": [
                    {"name": "火球术", "is_spell": True},
                    {"name": "挥砍", "action_type": "action"},
                ],
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
    assert actor["snapshot_json"]["action_surge_turn_key"] == "1:0"
    repeated_surge = combat_client.post(
        feature_path,
        headers={"X-Request-ID": "feature-action-surge-repeat"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "action_surge",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert repeated_surge.status_code == 400
    assert "每回合只能使用一次" in repeated_surge.json()["message"]
    magic_action = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "feature-extra-magic-action"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_cost": "action",
            "action_name": "火球术",
            "target_combatant_id": enemy["id"],
            "target_version": enemy["version"],
            "amount": 2,
            "damage_type": "fire",
        },
    )
    assert magic_action.status_code == 400
    assert "不能用于施放法术" in magic_action.json()["message"]
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


def test_relentless_endurance_prevents_zero_hp_and_consumes_long_rest_resource(
    combat_client: TestClient,
) -> None:
    campaign, combat, defender = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "不屈耐力测试者",
            "species": "兽人",
            "resources": {"relentless_endurance": {"current": 1, "max": 1}},
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    defense_registry = {
        "resources": {
            "relentless_endurance": {"current": 1, "max": 1},
        },
        "combat_start": {
            "defenses": [
                {
                    "id": "relentless_endurance:drop_to_one_hit_point",
                    "resource_key": "relentless_endurance",
                    "resource_cost": 1,
                    "trigger": "would_drop_to_zero_hit_points",
                    "on_success": {"hit_points": 1},
                }
            ]
        },
    }
    patched = combat_client.patch(
        _combatant_path(campaign, combat, defender["id"]),
        headers={"If-Match": f'"{defender["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "snapshot_json": {"feature_runtime": defense_registry},
        },
    )
    assert patched.status_code == 200, patched.text
    defender = patched.json()
    attacker = _add_combatant(
        combat_client,
        campaign,
        combat,
        name="致命攻击者",
        initiative=10,
    )
    damage = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "relentless-endurance-damage"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "action_cost": "none",
            "action_name": "巨斧",
            "target_combatant_id": defender["id"],
            "target_version": defender["version"],
            "amount": 30,
            "damage_type": "slashing",
        },
    )
    assert damage.status_code == 200, damage.text
    body = damage.json()
    assert body["target"]["hp"] == 1
    assert "昏迷" not in body["target"]["conditions"]
    assert body["action"]["result_json"]["feature_defense"]["resource_after"] == 0
    character_after = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    )
    assert character_after.status_code == 200, character_after.text
    assert character_after.json()["resources"]["relentless_endurance"]["current"] == 0


def test_relentless_rage_opens_save_restores_hp_increases_dc_and_preserves_death_save(
    combat_client: TestClient,
) -> None:
    campaign, combat, _ = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "坚韧狂暴测试者",
            "class_name": "野蛮人",
            "level": 5,
            "class_levels": {"野蛮人": 5},
            "hp": 20,
            "max_hp": 20,
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    defense = _relentless_rage_intervention()
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "坚韧狂暴测试者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 10,
            "hp": 10,
            "max_hp": 20,
            "conditions": ["raging"],
            "snapshot_json": {
                "feature_runtime": {
                    "progression": {"class_levels": {"野蛮人": 5}},
                    "combat_start": {"defenses": [defense]},
                }
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    attacker = _add_combatant(
        combat_client,
        campaign,
        combat,
        name="坚韧狂暴攻击者",
        initiative=20,
    )

    first_damage = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "relentless-rage-damage-1"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "action_cost": "none",
            "action_name": "重击",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 10,
            "damage_type": "slashing",
        },
    )
    assert first_damage.status_code == 200, first_damage.text
    first_body = first_damage.json()
    assert first_body["phase"] == "awaiting_feature_save"
    assert first_body["target"]["hp"] == 0
    assert "昏迷" in first_body["target"]["conditions"]
    prompt = first_body["feature_save_prompt"]
    assert prompt["action_type"] == "player_roll_prompt"
    assert prompt["request_json"]["dc"] == 10

    success = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{prompt['id']}/confirm",
        headers={"X-Request-ID": "relentless-rage-save-1"},
        json={"action_version": prompt["version"], "roll_total": 15},
    )
    assert success.status_code == 200, success.text
    success_body = success.json()
    assert success_body["target"]["hp"] == 10
    assert "昏迷" not in success_body["target"]["conditions"]
    assert success_body["resolution"]["relentless_rage"]["hit_points_restored"] == 10
    assert success_body["resolution"]["relentless_rage"]["dc_after_success"] == 15
    assert success_body["death_save"]["failures"] == 0
    target = success_body["target"]

    second_damage = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "relentless-rage-damage-2"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "action_cost": "none",
            "action_name": "重击",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 10,
            "damage_type": "slashing",
        },
    )
    assert second_damage.status_code == 200, second_damage.text
    second_prompt = second_damage.json()["feature_save_prompt"]
    assert second_prompt["request_json"]["dc"] == 15
    second_failure = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{second_prompt['id']}/confirm",
        headers={"X-Request-ID": "relentless-rage-save-2"},
        json={"action_version": second_prompt["version"], "roll_total": 14},
    )
    assert second_failure.status_code == 200, second_failure.text
    second_body = second_failure.json()
    assert second_body["target"]["hp"] == 0
    assert second_body["resolution"]["relentless_rage"]["death_save_unchanged"] is True
    assert second_body["death_save"]["failures"] == 0


def test_relentless_rage_does_not_open_on_massive_damage(
    combat_client: TestClient,
) -> None:
    campaign, combat, _ = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "坚韧狂暴致死测试者",
            "class_name": "野蛮人",
            "level": 5,
            "class_levels": {"野蛮人": 5},
            "hp": 20,
            "max_hp": 20,
        },
    )
    character = character_response.json()
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "坚韧狂暴致死测试者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 10,
            "hp": 1,
            "max_hp": 20,
            "conditions": ["raging"],
            "snapshot_json": {
                "feature_runtime": {
                    "progression": {"class_levels": {"野蛮人": 5}},
                    "combat_start": {
                        "defenses": [
                            _relentless_rage_intervention()
                        ]
                    },
                }
            },
        },
    )
    target = target_response.json()
    attacker = _add_combatant(
        combat_client,
        campaign,
        combat,
        name="致死攻击者",
        initiative=20,
    )
    damage = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "relentless-rage-massive"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "action_cost": "none",
            "action_name": "致死重击",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 21,
            "damage_type": "slashing",
        },
    )
    assert damage.status_code == 200, damage.text
    body = damage.json()
    assert "phase" not in body
    assert body["target"]["hp"] == 0
    assert body["death_save"]["dead"] is True
    assert body["death_save"]["failures"] == 3


def test_zero_hp_intervention_executor_accepts_a_second_configuration(
    combat_client: TestClient,
) -> None:
    campaign, combat, _ = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "通用干预测试者",
            "class_name": "战士",
            "level": 1,
            "class_levels": {"战士": 1},
            "hp": 12,
            "max_hp": 12,
            "resources": {
                "fixture_resolve": {"label": "测试干预次数", "current": 1, "max": 1}
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    test_intervention = {
        "id": "fixture:last_stand_save",
        "kind": "zero_hp_intervention",
        "trigger": "would_drop_to_zero_hit_points",
        "eligibility": {
            "entity_types": ["character"],
            "factions": ["ally"],
            "required_conditions": ["focused"],
            "resource": {"key": "fixture_resolve", "minimum": 1},
        },
        "saving_throw": {
            "ability": "wisdom",
            "initial_dc": 12,
            "increase_after_success": 2,
        },
        "success": {"kind": "restore_hit_points", "amount": "3"},
        "failure": {"kind": "continue_zero_hp_lifecycle"},
        "exceptions": ["outright_death"],
        "state": {"key": "fixture_last_stand_state", "current_dc_field": "save_dc"},
        "resets": ["long_rest"],
        "presentation": {
            "action_name": "测试背水一战",
            "result_key": "fixture_last_stand",
            "prompt_idempotency_prefix": "fixture-last-stand",
        },
    }
    target_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "通用干预测试者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 10,
            "hp": 6,
            "max_hp": 12,
            "conditions": ["focused"],
            "snapshot_json": {
                "feature_runtime": {"combat_start": {"defenses": [test_intervention]}},
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    attacker = _add_combatant(
        combat_client, campaign, combat, name="通用干预攻击者", initiative=20
    )
    damage = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "fixture-zero-hp-damage"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "action_cost": "none",
            "action_name": "测试伤害",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 6,
            "damage_type": "force",
        },
    )
    assert damage.status_code == 200, damage.text
    prompt = damage.json()["feature_save_prompt"]
    assert prompt["request_json"]["action_name"] == "测试背水一战"
    assert prompt["request_json"]["ability"] == "wisdom"
    assert prompt["request_json"]["dc"] == 12
    request = {"action_version": prompt["version"], "roll_total": 12}
    save = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{prompt['id']}/confirm",
        headers={"X-Request-ID": "fixture-zero-hp-save"},
        json=request,
    )
    assert save.status_code == 200, save.text
    save_body = save.json()
    assert save_body["target"]["hp"] == 3
    assert save_body["resolution"]["zero_hp_intervention"]["feature_id"] == (
        "fixture:last_stand_save"
    )
    assert save_body["resolution"]["fixture_last_stand"]["dc_after_success"] == 14
    assert save_body["target"]["snapshot_json"]["fixture_last_stand_state"][
        "save_dc"
    ] == 14
    replay = combat_client.post(
        f"{_root(campaign, combat)}/actions/player-rolls/{prompt['id']}/confirm",
        headers={"X-Request-ID": "fixture-zero-hp-save"},
        json=request,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["target"]["hp"] == 3


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
                            "requirements": ["not_wearing_heavy_armor"],
                            "effects": [{"kind": "activate_condition", "condition": "raging"}],
                        }
                    }
                },
                "equipment": [],
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


def test_starry_form_activation_enables_full_of_stars_resistance(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "星辰德鲁伊",
            "class_name": "德鲁伊",
            "resources": {"wild_shape": {"current": 1, "max": 2}},
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "snapshot_json": {
                "feature_runtime": {
                    "actions": {
                        "starry_form": {
                            "name": "星耀形态",
                            "kind": "feature_action",
                            "action_cost": "bonus_action",
                            "resource_key": "wild_shape",
                            "resource_cost": 1,
                            "target": "self",
                            "resolution_kind": "condition",
                            "runtime_execution": {
                                "status": "ready",
                                "consumer": "combat_feature_action",
                                "effect_kinds": ["activate_duration_condition"],
                            },
                            "effects": [
                                {
                                    "kind": "activate_duration_condition",
                                    "condition": "starry_form",
                                    "duration_unit": "minutes",
                                    "duration_value": 10,
                                }
                            ],
                        }
                    },
                    "combat_start": {
                        "defenses": [
                            {
                                "id": "subclass:full_of_stars:physical_resistance",
                                "kind": "damage_resistance",
                                "damage_types": ["slashing"],
                                "applies_when": "always",
                                "required_conditions": ["starry_form"],
                            }
                        ]
                    },
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()

    before = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "full-of-stars-before"},
        json={
            "action_type": "damage",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
            "amount": 9,
            "damage_type": "slashing",
        },
    )
    assert before.status_code == 200, before.text
    assert before.json()["action"]["result_json"]["adjusted_damage"] == 9
    refreshed = combat_client.get(_combatant_path(campaign, combat, actor["id"]))
    assert refreshed.status_code == 200, refreshed.text
    actor = refreshed.json()

    activated = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "starry-form-activation"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "starry_form",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert activated.status_code == 200, activated.text
    actor = activated.json()["actor"]
    assert "starry_form" in actor["conditions"]
    assert activated.json()["result"]["resource_after"] == 0

    damage = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "full-of-stars-after"},
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


def test_rage_feature_ends_when_turn_has_no_attack_or_damage(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    _add_combatant(combat_client, campaign, combat, name="狂暴目标", initiative=10)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "持续狂暴者",
            "class_name": "野蛮人",
            "resources": {"rage": {"current": 1, "max": 1}},
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    patched = combat_client.patch(
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
                            "runtime_execution": {
                                "status": "ready",
                                "consumer": "combat_feature_action",
                                "effect_kinds": ["activate_duration_condition"],
                            },
                            "effects": [
                                {
                                    "kind": "activate_duration_condition",
                                    "condition": "raging",
                                    "duration_unit": "minutes",
                                    "duration_value": 1,
                                }
                            ],
                        }
                    }
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    activated = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "rage-duration"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "rage",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert activated.status_code == 200, activated.text
    activated_body = activated.json()
    assert "raging" in activated_body["actor"]["conditions"]
    assert activated_body["result"]["duration"] == {
        "unit": "minutes",
        "value": 1,
        "ends_round": 11,
    }

    first_advance = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "rage-start-turn"},
        json={"combat_version": combat["version"]},
    )
    assert first_advance.status_code == 200, first_advance.text
    second_advance = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "rage-middle-turn"},
        json={"combat_version": first_advance.json()["combat"]["version"]},
    )
    assert second_advance.status_code == 200, second_advance.text
    advanced = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "rage-no-activity-turn"},
        json={"combat_version": second_advance.json()["combat"]["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    body = advanced.json()
    assert body["active_combatant"] is not None
    actor_after = combat_client.get(
        _combatant_path(campaign, combat, actor["id"])
    )
    assert actor_after.status_code == 200, actor_after.text
    actor_state = actor_after.json()
    assert "raging" not in actor_state["conditions"], actor_state["snapshot_json"]
    assert "rage_activity" not in actor_state["snapshot_json"]


def test_innate_sorcery_consumes_resource_and_expires_after_one_minute(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "先天术法测试者",
            "class_name": "术士",
            "resources": {"innate_sorcery": {"current": 1, "max": 2}},
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "snapshot_json": {
                "feature_runtime": {
                    "actions": {
                        "innate_sorcery": {
                            "name": "先天术法",
                            "kind": "feature_action",
                            "action_cost": "bonus_action",
                            "resource_key": "innate_sorcery",
                            "resource_cost": 1,
                            "target": "self",
                            "resolution_kind": "condition",
                            "runtime_execution": {
                                "status": "ready",
                                "consumer": "combat_feature_action",
                                "effect_kinds": ["activate_duration_condition"],
                            },
                            "effects": [
                                {
                                    "kind": "activate_duration_condition",
                                    "condition": "innate_sorcery",
                                    "duration_unit": "minutes",
                                    "duration_value": 1,
                                }
                            ],
                        }
                    }
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    activated = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "innate-sorcery-duration"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "innate_sorcery",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert activated.status_code == 200, activated.text
    body = activated.json()
    assert body["result"]["resource_before"] == 1
    assert body["result"]["resource_after"] == 0
    assert "innate_sorcery" in body["actor"]["conditions"]
    assert body["result"]["duration"] == {
        "unit": "minutes",
        "value": 1,
        "ends_round": 11,
    }

    combat_version = combat["version"]
    last_advance: dict[str, Any] | None = None
    for index in range(10):
        advanced = combat_client.post(
            f"{_root(campaign, combat)}/turns/advance",
            headers={"X-Request-ID": f"innate-sorcery-turn-{index}"},
            json={"combat_version": combat_version},
        )
        assert advanced.status_code == 200, advanced.text
        last_advance = advanced.json()
        combat_version = last_advance["combat"]["version"]

    assert last_advance is not None
    assert "innate_sorcery" not in last_advance["active_combatant"]["conditions"]
    assert any(
        item["id"] == body["result"]["effect_id"]
        for item in last_advance["ended_runtime_effects"]
    )


def test_rage_feature_rejects_explicit_heavy_armor(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "重甲狂战士", "class_name": "野蛮人"},
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    patched = combat_client.patch(
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
                            "target": "self",
                            "requirements": ["not_wearing_heavy_armor"],
                            "effects": [{
                                "kind": "activate_condition",
                                "condition": "raging",
                            }],
                        }
                    }
                },
                "equipment": [{
                    "category": "armor",
                    "equipment_profile": {"armor_type": "heavy"},
                }],
            },
        },
    )
    assert patched.status_code == 200, patched.text
    rejected = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "rage-heavy-armor"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": patched.json()["version"],
            "feature_id": "rage",
            "target_combatant_id": actor["id"],
            "target_version": patched.json()["version"],
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "重甲" in rejected.text


def test_reckless_feature_action_expires_at_actor_turn_start(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    _add_combatant(combat_client, campaign, combat, name="目标", initiative=10)
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "snapshot_json": {
                "feature_runtime": {
                    "actions": {
                        "reckless_attack": {
                            "name": "鲁莽攻击",
                            "kind": "feature_action",
                            "action_cost": "none",
                            "target": "self",
                            "resolution_kind": "condition",
                            "runtime_execution": {
                                "status": "ready",
                                "consumer": "combat_feature_action",
                                "effect_kinds": ["activate_timed_condition"],
                            },
                            "effects": [
                                {
                                    "kind": "activate_timed_condition",
                                    "condition": "reckless_attack",
                                    "expires": "turn_start",
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
    activated = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "reckless-feature"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "reckless_attack",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert activated.status_code == 200, activated.text
    actor = activated.json()["actor"]
    assert "reckless_attack" in actor["conditions"]
    effect_id = activated.json()["action"]["result_json"]["effect_id"]

    next_turn = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "reckless-next-unit"},
        json={"combat_version": combat["version"]},
    )
    assert next_turn.status_code == 200, next_turn.text
    expired = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "reckless-next-round"},
        json={"combat_version": next_turn.json()["combat"]["version"]},
    )
    assert expired.status_code == 200, expired.text
    assert "reckless_attack" not in expired.json()["active_combatant"]["conditions"]
    assert any(item["id"] == effect_id for item in expired.json()["ended_runtime_effects"])


def test_steady_aim_zeroes_movement_and_is_consumed_by_next_attack(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    enemy = _add_combatant(combat_client, campaign, combat, name="稳定瞄准目标", initiative=10)
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "snapshot_json": {
                "feature_runtime": {
                    "actions": {
                        "steady_aim": {
                            "name": "稳定瞄准",
                            "kind": "feature_action",
                            "action_cost": "bonus_action",
                            "target": "self",
                            "resolution_kind": "condition",
                            "runtime_execution": {
                                "status": "ready",
                                "consumer": "combat_feature_action",
                                "effect_kinds": ["activate_timed_condition"],
                            },
                            "effects": [
                                {
                                    "kind": "activate_timed_condition",
                                    "condition": "steady_aim",
                                    "expires": "turn_end",
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

    activated = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "steady-aim-activate"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "steady_aim",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert activated.status_code == 200, activated.text
    actor = activated.json()["actor"]
    assert "steady_aim" in actor["conditions"]
    assert actor["movement_remaining_ft"] == 0
    assert actor["bonus_action_available"] is False

    first_attack = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "steady-aim-attack-1"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_cost": "action",
            "target_combatant_id": enemy["id"],
            "target_version": enemy["version"],
            "amount": 3,
            "damage_type": "piercing",
            "is_attack": True,
            "attack_roll_mode": "advantage",
            "attack_roll_total": 12,
        },
    )
    assert first_attack.status_code == 200, first_attack.text
    first_result = first_attack.json()["action"]["result_json"]
    assert "feature:稳定瞄准" in next(
        item
        for item in first_result["attack_contexts"]
        if item.startswith("attack_roll_advantage_sources:")
    )
    assert first_result["consumed_effect_ids"] == [
        activated.json()["result"]["effect_id"]
    ]
    actor = first_attack.json()["actor"]
    enemy = first_attack.json()["target"]
    assert "steady_aim" not in actor["conditions"]

    second_attack = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "steady-aim-attack-2"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_cost": "none",
            "target_combatant_id": enemy["id"],
            "target_version": enemy["version"],
            "amount": 3,
            "damage_type": "piercing",
            "is_attack": True,
            "attack_roll_mode": "advantage",
            "attack_roll_total": 12,
        },
    )
    assert second_attack.status_code == 200, second_attack.text
    second_result = second_attack.json()["action"]["result_json"]
    assert "feature:稳定瞄准" not in " ".join(second_result.get("attack_contexts", []))


def test_steady_aim_requires_unspent_movement_and_expires_at_turn_end(
    combat_client: TestClient,
) -> None:
    campaign, combat, actor = _setup(combat_client)
    _add_combatant(combat_client, campaign, combat, name="稳定瞄准回合目标", initiative=10)
    registry = {
        "actions": {
            "steady_aim": {
                "name": "稳定瞄准",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "target": "self",
                "effects": [
                    {
                        "kind": "activate_timed_condition",
                        "condition": "steady_aim",
                        "expires": "turn_end",
                    }
                ],
            }
        }
    }
    patched = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={"movement_remaining_ft": 25, "snapshot_json": {"feature_runtime": registry}},
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    rejected = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "steady-aim-after-move"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "steady_aim",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert rejected.status_code == 400
    assert "尚未移动" in rejected.text

    restored = combat_client.patch(
        _combatant_path(campaign, combat, actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={"movement_remaining_ft": 30},
    )
    assert restored.status_code == 200, restored.text
    actor = restored.json()
    activated = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "steady-aim-expiry-activate"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "steady_aim",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
        },
    )
    assert activated.status_code == 200, activated.text
    actor = activated.json()["actor"]
    first_next = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "steady-aim-expiry-next-unit"},
        json={"combat_version": combat["version"]},
    )
    assert first_next.status_code == 200, first_next.text
    second_next = combat_client.post(
        f"{_root(campaign, combat)}/turns/advance",
        headers={"X-Request-ID": "steady-aim-expiry-next-round"},
        json={"combat_version": first_next.json()["combat"]["version"]},
    )
    assert second_next.status_code == 200, second_next.text
    assert "steady_aim" not in second_next.json()["active_combatant"]["conditions"]


def test_moonlight_step_resets_from_spell_slot_teleports_and_grants_one_attack_advantage(
    combat_client: TestClient,
) -> None:
    campaign_response = combat_client.post(
        "/api/v1/campaigns", json={"name": "月光飞步生命周期"}
    )
    assert campaign_response.status_code == 201
    campaign = campaign_response.json()
    scene = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes", json={"name": "月光靶场"}
    ).json()
    grid = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 4, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "月光德鲁伊",
            "class_name": "fixture",
            "resources": {
                "moonlight_step": {"current": 0, "max": 1},
                "spell_slots_2": {"current": 1, "max": 1},
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    combat_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "月光战斗", "scene_id": scene["id"]},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    registry = {
        "actions": {
            "moonlight_step": {
                "name": "月光飞步",
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "moonlight_step",
                "resource_cost": 1,
                "target": "self",
                "reset_options": {
                    "minimum_spell_slot_level": 2,
                    "maximum_spell_slot_level": 9,
                    "amount": 1,
                },
                "effects": [
                    {"kind": "teleport", "max_distance_ft": 30},
                    {
                        "kind": "activate_timed_condition",
                        "condition": "moonlight_step",
                        "expires": "turn_end",
                    },
                ],
            }
        }
    }
    actor_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "月光德鲁伊",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 2},
                "feature_runtime": registry,
            },
        },
    )
    assert actor_response.status_code == 201, actor_response.text
    actor = actor_response.json()
    enemy_response = combat_client.post(
        f"{_root(campaign, combat)}/combatants",
        json={
            "display_name": "月光目标",
            "entity_type": "monster",
            "initiative": 10,
            "armor_class": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 2, "col": 3}},
        },
    )
    assert enemy_response.status_code == 201, enemy_response.text
    enemy = enemy_response.json()

    activated = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "moonlight-step-activate"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "feature_id": "moonlight_step",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
            "destination_row": 2,
            "destination_col": 4,
            "reset_spell_slot_level": 2,
        },
    )
    assert activated.status_code == 200, activated.text
    body = activated.json()
    actor = body["actor"]
    assert actor["snapshot_json"]["grid_position"] == {"row": 2, "col": 4}
    assert body["result"]["resource_reset"]["spell_slot_key"] == "spell_slots_2"
    assert body["result"]["resource_after"] == 0
    assert "moonlight_step" in actor["conditions"]

    replay = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "moonlight-step-activate"},
        json={
            "actor_combatant_id": actor_response.json()["id"],
            "actor_version": actor_response.json()["version"],
            "feature_id": "moonlight_step",
            "target_combatant_id": actor_response.json()["id"],
            "target_version": actor_response.json()["version"],
            "destination_row": 2,
            "destination_col": 4,
            "reset_spell_slot_level": 2,
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["action"]["id"] == body["action"]["id"]

    attack = combat_client.post(
        f"{_root(campaign, combat)}/actions/confirm",
        headers={"X-Request-ID": "moonlight-step-attack"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_cost": "action",
            "target_combatant_id": enemy["id"],
            "target_version": enemy["version"],
            "amount": 1,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_roll_total": 15,
            "attack_roll_mode": "advantage",
        },
    )
    assert attack.status_code == 200, attack.text
    result = attack.json()["action"]["result_json"]
    assert "feature:月光飞步" in next(
        item
        for item in result["attack_contexts"]
        if item.startswith("attack_roll_advantage_sources:")
    )
    assert "moonlight_step" not in attack.json()["actor"]["conditions"]


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


def test_self_restoration_removes_one_selected_condition_idempotently(
    combat_client: TestClient,
) -> None:
    campaign, combat, generic_actor = _setup(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "返本还元测试者", "class_name": "武僧", "level": 10},
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    registry = {
        "actions": {
            "self_restoration": {
                "id": "self_restoration",
                "name": "返本还元",
                "kind": "feature_action",
                "action_cost": "none",
                "target": "self",
                "resolution_kind": "condition_removal",
                "activation_window": "turn_end",
                "allowed_conditions": ["charmed", "frightened", "poisoned"],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action",
                    "effect_kinds": ["condition_removal"],
                },
                "effects": [{"kind": "condition_removal"}],
            }
        }
    }
    patched = combat_client.patch(
        _combatant_path(campaign, combat, generic_actor["id"]),
        headers={"If-Match": f'"{generic_actor["version"]}"'},
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "conditions": ["中毒", "恐慌"],
            "snapshot_json": {"feature_runtime": registry},
        },
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    payload = {
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "feature_id": "self_restoration",
        "condition_to_remove": "poisoned",
        "target_combatant_id": actor["id"],
        "target_version": actor["version"],
    }
    confirmed = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "self-restoration-poisoned"},
        json=payload,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["result"]["condition_removal"] == {
        "condition": "poisoned",
        "removed": True,
        "ended_effect_ids": [],
    }
    assert confirmed.json()["target"]["conditions"] == ["恐慌"]
    replay = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "self-restoration-poisoned"},
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    absent = combat_client.post(
        f"{_root(campaign, combat)}/feature-actions/confirm",
        headers={"X-Request-ID": "self-restoration-absent"},
        json={
            **payload,
            "actor_version": confirmed.json()["actor"]["version"],
            "target_version": confirmed.json()["target"]["version"],
        },
    )
    assert absent.status_code == 400, absent.text
