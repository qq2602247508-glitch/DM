from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.api.schemas import CombatActionCommand
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.campaign_state import VersionConflict
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService


@pytest.fixture
def combat_client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'combat.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as client:
        yield client


def _campaign(client: TestClient, name: str = "Combat") -> dict[str, Any]:
    response = client.post("/api/v1/campaigns", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _combatant(
    client: TestClient,
    campaign_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    combat_response = client.post(
        f"/api/v1/campaigns/{campaign_id}/combats",
        json={"name": "Rule Test"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    fighter_response = client.post(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Fire Guard",
            "hp": 20,
            "max_hp": 20,
            "temporary_hp": 3,
            "damage_resistances": ["fire"],
        },
    )
    assert fighter_response.status_code == 201, fighter_response.json()
    return combat, fighter_response.json()


def _fighter_path(campaign_id: str, combat_id: str, fighter_id: str) -> str:
    return (
        f"/api/v1/campaigns/{campaign_id}/combats/{combat_id}/combatants/{fighter_id}"
    )


def test_damage_preview_is_read_only(combat_client: TestClient) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    preview_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/preview"
    )

    preview = combat_client.post(
        preview_path,
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 9,
            "damage_type": "fire",
        },
    )

    assert preview.status_code == 200
    assert preview.json()["result"]["adjusted_damage"] == 4
    assert preview.json()["after"]["temporary_hp"] == 0
    assert preview.json()["after"]["hp"] == 19
    unchanged = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], fighter["id"])
    ).json()
    assert unchanged["temporary_hp"] == 3
    assert unchanged["hp"] == 20
    assert unchanged["version"] == 1


def test_mixed_damage_components_apply_defenses_independently(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Mixed damage")
    combat, fighter = _combatant(combat_client, campaign["id"])
    path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/actions/confirm"
    )
    payload = {
        "action_type": "damage",
        "target_combatant_id": fighter["id"],
        "target_version": fighter["version"],
        "amount": 11,
        "damage_components": [
            {"amount": 5, "damage_type": "fire"},
            {"amount": 6, "damage_type": "slashing"},
        ],
    }
    preview = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/actions/preview",
        json=payload,
    )
    assert preview.status_code == 200, preview.text
    preview_result = preview.json()["result"]
    assert preview_result["damage_type"] == "mixed"
    assert [item["damage_type"] for item in preview_result["damage_components"]] == [
        "fire",
        "slashing",
    ]
    assert preview_result["adjusted_damage"] == 8
    assert preview_result["temporary_hp_lost"] == 3
    assert preview_result["hp_lost"] == 5
    assert preview.json()["after"]["hp"] == 15
    assert preview.json()["after"]["temporary_hp"] == 0

    confirmed = combat_client.post(
        path,
        headers={"X-Request-ID": "mixed-damage-once"},
        json=payload,
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["action"]["result_json"]
    assert result["damage_type"] == "mixed"
    assert confirmed.json()["target"]["hp"] == 15
    assert confirmed.json()["target"]["temporary_hp"] == 0
    assert "实际扣除 8 点（原始报告 11 点）" in confirmed.json()["action"]["summary"]

    invalid = combat_client.post(
        path,
        headers={"X-Request-ID": "mixed-damage-invalid"},
        json={
            **payload,
            "target_version": confirmed.json()["target"]["version"],
            "amount": 10,
        },
    )
    assert invalid.status_code == 422

    ambiguous = combat_client.post(
        path,
        headers={"X-Request-ID": "mixed-damage-ambiguous"},
        json={
            **payload,
            "target_version": confirmed.json()["target"]["version"],
            "amount": 10,
            "damage_type": "mixed",
            "damage_components": [],
        },
    )
    assert ambiguous.status_code == 422


def test_conditional_damage_defense_requires_explicit_source_tag(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Conditional defenses")
    combat_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Conditional defense combat"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    target_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "非魔法抗性目标",
            "entity_type": "monster",
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "conditional_damage_defenses": [
                    {
                        "id": "nonmagical-slashing",
                        "condition": "nonmagical",
                        "operation": "resistance",
                        "damage_types": ["slashing"],
                    }
                ]
            },
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    base_payload = {
        "action_type": "damage",
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "amount": 10,
        "damage_type": "slashing",
    }
    unresolved = combat_client.post(f"{root}/actions/preview", json=base_payload)
    assert unresolved.status_code == 400, unresolved.text
    assert "damage_tags" in unresolved.json()["message"]

    tagged = combat_client.post(
        f"{root}/actions/confirm",
        headers={"X-Request-ID": "conditional-defense-tagged"},
        json={**base_payload, "damage_tags": ["nonmagical"]},
    )
    assert tagged.status_code == 200, tagged.text
    result = tagged.json()["action"]["result_json"]
    assert result["adjusted_damage"] == 5
    assert result["conditional_defenses_applied"] == [
        "nonmagical-slashing:resistance:slashing"
    ]
    assert tagged.json()["target"]["hp"] == 15


def test_mixed_damage_segments_use_their_own_conditional_source_tags(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Per segment tags")
    combat_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Per segment tags combat"},
    )
    combat = combat_response.json()
    target = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "条件防御目标",
            "entity_type": "monster",
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "conditional_damage_defenses": [
                    {
                        "id": "magical-fire",
                        "condition": "magical",
                        "operation": "resistance",
                        "damage_types": ["fire"],
                    },
                    {
                        "id": "nonmagical-fire",
                        "condition": "nonmagical",
                        "operation": "vulnerability",
                        "damage_types": ["fire"],
                    },
                ]
            },
        },
    ).json()
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    response = combat_client.post(
        f"{root}/actions/confirm",
        headers={"X-Request-ID": "per-segment-defense-tags"},
        json={
            "action_type": "damage",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 10,
            "damage_components": [
                {"amount": 5, "damage_type": "fire", "damage_tags": ["magical"]},
                {"amount": 5, "damage_type": "fire", "damage_tags": ["nonmagical"]},
            ],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["action"]["result_json"]
    assert result["adjusted_damage"] == 12
    assert response.json()["target"]["hp"] == 18
    assert result["damage_components"][0]["conditional_defenses_applied"] == [
        "magical-fire:resistance:fire"
    ]
    assert result["damage_components"][1]["conditional_defenses_applied"] == [
        "nonmagical-fire:vulnerability:fire"
    ]


def test_damage_event_ends_condition_with_explicit_target_damage_trigger(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Damage lifecycle")
    combat = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Damage lifecycle combat"},
    ).json()
    target = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={"display_name": "受伤目标", "hp": 20, "max_hp": 20},
    ).json()
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    effect = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "damage-lifecycle-effect"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "受伤即醒",
            "effect_type": "condition",
            "details_json": {
                "rule_block": {
                    "kind": "condition",
                    "condition": "隐形",
                    "operation": "apply",
                    "end_triggers": ["target_takes_damage"],
                },
                "applied_state": {"conditions": []},
            },
        },
    )
    assert effect.status_code == 200, effect.text
    target = effect.json()["target"]
    damage = combat_client.post(
        f"{root}/actions/confirm",
        headers={"X-Request-ID": "damage-lifecycle-hit"},
        json={
            "action_type": "damage",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 3,
            "damage_type": "slashing",
        },
    )
    assert damage.status_code == 200, damage.text
    result = damage.json()["action"]["result_json"]
    assert result["ended_predicated_effect_ids"] == [effect.json()["effect"]["id"]]
    assert "隐形" not in damage.json()["target"]["conditions"]


def test_multi_target_batch_preflights_later_version_before_writing_earlier_damage(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "批量伤害版本屏障")
    combat, first_target = _combatant(combat_client, campaign["id"])
    second_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={"display_name": "第二目标", "hp": 20, "max_hp": 20},
    )
    assert second_response.status_code == 201, second_response.text
    second_target = second_response.json()
    service = CombatEngineService(combat_client.app.state.database_engine)
    commands = [
        (
            CombatActionCommand(
                action_type="damage",
                target_combatant_id=first_target["id"],
                target_version=first_target["version"],
                amount=4,
                damage_type="fire",
            ),
            "batch-version-first",
        ),
        (
            CombatActionCommand(
                action_type="damage",
                target_combatant_id=second_target["id"],
                target_version=second_target["version"] + 1,
                amount=4,
                damage_type="fire",
            ),
            "batch-version-second-stale",
        ),
    ]

    with pytest.raises(VersionConflict):
        service.confirm_action_batch(campaign["id"], combat["id"], commands)

    refreshed = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants"
    )
    assert refreshed.status_code == 200
    by_id = {item["id"]: item for item in refreshed.json()["items"]}
    assert by_id[first_target["id"]]["hp"] == first_target["hp"]
    assert by_id[first_target["id"]]["version"] == first_target["version"]
    assert by_id[second_target["id"]]["hp"] == second_target["hp"]
    assert by_id[second_target["id"]]["version"] == second_target["version"]


def test_multi_target_batch_preflights_conditional_defense_before_first_target_write(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "批量伤害条件防御屏障")
    combat, first_target = _combatant(combat_client, campaign["id"])
    second_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "条件抗性目标",
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "conditional_damage_defenses": [
                    {
                        "id": "nonmagical-slashing",
                        "condition": "nonmagical",
                        "operation": "resistance",
                        "damage_types": ["slashing"],
                    }
                ]
            },
        },
    )
    assert second_response.status_code == 201, second_response.text
    second_target = second_response.json()
    service = CombatEngineService(combat_client.app.state.database_engine)
    commands = [
        (
            CombatActionCommand(
                action_type="damage",
                target_combatant_id=first_target["id"],
                target_version=first_target["version"],
                amount=4,
                damage_type="fire",
            ),
            "batch-defense-first",
        ),
        (
            CombatActionCommand(
                action_type="damage",
                target_combatant_id=second_target["id"],
                target_version=second_target["version"],
                amount=4,
                damage_type="slashing",
            ),
            "batch-defense-second",
        ),
    ]

    with pytest.raises(ValueError, match="damage_tags"):
        service.confirm_action_batch(campaign["id"], combat["id"], commands)

    refreshed = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants"
    )
    assert refreshed.status_code == 200
    by_id = {item["id"]: item for item in refreshed.json()["items"]}
    assert by_id[first_target["id"]]["hp"] == first_target["hp"]
    assert by_id[first_target["id"]]["version"] == first_target["version"]
    assert by_id[second_target["id"]]["hp"] == second_target["hp"]


def test_confirm_action_batch_applies_each_target_once_and_preserves_typed_segments(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "批量区域结算接口")
    combat_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "批量区域结算"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"

    actor_response = combat_client.post(
        f"{root}/combatants",
        json={
            "display_name": "区域施法者",
            "entity_type": "character",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
        },
    )
    first_response = combat_client.post(
        f"{root}/combatants",
        json={
            "display_name": "目标一",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    )
    second_response = combat_client.post(
        f"{root}/combatants",
        json={
            "display_name": "目标二",
            "initiative": 0,
            "hp": 20,
            "max_hp": 20,
        },
    )
    assert actor_response.status_code == 201
    assert first_response.status_code == 201
    assert second_response.status_code == 201
    actor = actor_response.json()
    first_target = first_response.json()
    second_target = second_response.json()

    response = combat_client.post(
        f"{root}/actions/confirm-batch",
        json={
            "items": [
                {
                    "idempotency_key": "area-batch-target-one",
                    "command": {
                        "action_type": "damage",
                        "actor_combatant_id": actor["id"],
                        "actor_version": actor["version"],
                        "action_cost": "action",
                        "action_name": "火球术",
                        "target_combatant_id": first_target["id"],
                        "target_version": first_target["version"],
                        "amount": 9,
                        "damage_type": "mixed",
                        "damage_components": [
                            {"amount": 4, "damage_type": "fire"},
                            {"amount": 5, "damage_type": "force"},
                        ],
                    },
                },
                {
                    "idempotency_key": "area-batch-target-two",
                    "command": {
                        "action_type": "damage",
                        "actor_combatant_id": actor["id"],
                        "actor_version": actor["version"] + 1,
                        "action_cost": "none",
                        "action_name": "火球术",
                        "target_combatant_id": second_target["id"],
                        "target_version": second_target["version"],
                        "amount": 9,
                        "damage_type": "mixed",
                        "damage_components": [
                            {"amount": 4, "damage_type": "fire"},
                            {"amount": 5, "damage_type": "force"},
                        ],
                    },
                },
            ]
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["target"]["hp"] == 11
    assert body["items"][1]["target"]["hp"] == 11
    assert body["items"][0]["actor"]["action_available"] is False
    assert body["items"][1]["actor"]["version"] == actor["version"] + 1
    segments = body["items"][0]["action"]["result_json"]["damage_components"]
    assert [
        (segment["damage_type"], segment["original_damage"], segment["adjusted_damage"])
        for segment in segments
    ] == [("fire", 4, 4), ("force", 5, 5)]

    actions = combat_client.get(f"{root}/actions")
    assert actions.status_code == 200
    assert len(actions.json()["items"]) == 2


def test_confirm_damage_is_atomic_logged_and_idempotent(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    confirm_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm"
    )
    payload = {
        "action_type": "damage",
        "target_combatant_id": fighter["id"],
        "target_version": fighter["version"],
        "amount": 9,
        "damage_type": "fire",
    }

    confirmed = combat_client.post(
        confirm_path,
        json=payload,
        headers={"X-Request-ID": "damage-once"},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["action"]["action_type"] == "damage"
    assert body["action"]["round_number"] == 1
    assert body["target"]["temporary_hp"] == 0
    assert body["target"]["hp"] == 19
    assert body["target"]["version"] == 2

    repeated = combat_client.post(
        confirm_path,
        json=payload,
        headers={"X-Request-ID": "damage-once"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["action"]["id"] == body["action"]["id"]
    assert repeated.json()["target"]["hp"] == 19
    actions = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions"
    )
    assert actions.status_code == 200
    assert len(actions.json()["items"]) == 1


def test_confirmed_attack_spends_action_and_blocks_repeat(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, actor = _combatant(combat_client, campaign["id"])
    promoted_actor = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={"initiative": 20},
    )
    assert promoted_actor.status_code == 200
    actor = promoted_actor.json()
    target_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "训练假人",
            "entity_type": "monster",
            "initiative": 0,
            "hp": 20,
            "max_hp": 20,
            "armor_class": 10,
        },
    )
    assert target_response.status_code == 201
    target = target_response.json()
    path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/actions/confirm"
    )
    first = combat_client.post(
        path,
        headers={"X-Request-ID": "spend-action-once"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_cost": "action",
            "action_name": "长剑",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 4,
            "damage_type": "slashing",
        },
    )
    assert first.status_code == 200, first.json()
    spent_actor = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], actor["id"])
    ).json()
    assert spent_actor["action_available"] is False
    updated_target = first.json()["target"]

    repeated = combat_client.post(
        path,
        headers={"X-Request-ID": "spend-action-twice"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": spent_actor["version"],
            "action_cost": "action",
            "action_name": "长剑",
            "target_combatant_id": target["id"],
            "target_version": updated_target["version"],
            "amount": 4,
            "damage_type": "slashing",
        },
    )
    assert repeated.status_code == 400
    assert "already been spent" in repeated.json()["message"]


def test_recharge_action_is_consumed_and_cannot_refresh_without_a_roll(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Recharge action")
    combat_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Recharge combat"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    monster = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "火焰巨兽",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "actions": [
                    {
                        "name": "火焰吐息",
                        "damage": "6d6",
                        "recharge": {"minimum": 5, "maximum": 6},
                    }
                ]
            },
        },
    ).json()
    target = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "冒险者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()
    path = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm"
    first = combat_client.post(
        path,
        headers={"X-Request-ID": "recharge-first"},
        json={
            "action_type": "damage",
            "actor_combatant_id": monster["id"],
            "actor_version": monster["version"],
            "action_cost": "action",
            "action_name": "火焰吐息",
            "recharge_key": "火焰吐息",
            "recharge_consume": True,
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 6,
            "damage_type": "fire",
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["action"]["result_json"]["recharge_consumed"] == "火焰吐息"
    spent = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], monster["id"])
    ).json()
    assert spent["snapshot_json"]["recharge_available"]["火焰吐息"] is False

    reset_action = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], monster["id"]),
        headers={"If-Match": f'"{spent["version"]}"'},
        json={"action_available": True},
    )
    assert reset_action.status_code == 200, reset_action.text
    blocked = combat_client.post(
        path,
        headers={"X-Request-ID": "recharge-second"},
        json={
            "action_type": "damage",
            "actor_combatant_id": monster["id"],
            "actor_version": reset_action.json()["version"],
            "action_cost": "action",
            "action_name": "火焰吐息",
            "recharge_key": "火焰吐息",
            "recharge_consume": True,
            "target_combatant_id": target["id"],
            "target_version": first.json()["target"]["version"],
            "amount": 6,
            "damage_type": "fire",
        },
    )
    assert blocked.status_code == 400
    assert "recharge action" in blocked.json()["message"]


def test_monster_turn_start_rolls_recharge_and_applies_structured_traits(
    combat_client: TestClient,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "dnd_dm_assistant.infrastructure.database.combat_service.secrets.randbelow",
        lambda upper: 4,
    )
    campaign = _campaign(combat_client, "Monster turn start")
    combat = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Recharge and traits"},
    ).json()
    combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Hero",
            "entity_type": "character",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    )
    monster = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Regenerating horror",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 5,
            "max_hp": 20,
            "snapshot_json": {
                "actions": [
                    {
                        "name": "Breath",
                        "action_type": "action",
                        "recharge": {"minimum": 5, "maximum": 6},
                    }
                ],
                "recharge_available": {"Breath": False},
                "resources": {"ward": 0},
                "turn_start_traits": [
                    {"name": "Regeneration", "kind": "heal", "amount": 6},
                    {
                        "name": "Bloodied frenzy",
                        "kind": "condition",
                        "condition": "狂暴",
                        "trigger": "always",
                    },
                    {
                        "name": "Renew ward",
                        "kind": "resource",
                        "resource_key": "ward",
                        "restore_to": 2,
                    },
                ],
            },
        },
    ).json()

    advanced = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "monster-turn-start"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    body = advanced.json()
    assert body["active_combatant"]["id"] == monster["id"]
    assert body["active_combatant"]["hp"] == 11
    assert "狂暴" in body["active_combatant"]["conditions"]
    assert body["active_combatant"]["snapshot_json"]["resources"]["ward"] == 2
    assert body["active_combatant"]["snapshot_json"]["recharge_available"]["Breath"] is True
    assert body["recharge_rolls"] == [
        {
            "action_name": "Breath",
            "roll": 5,
            "minimum": 5,
            "maximum": 6,
            "available": True,
        }
    ]
    assert {result["name"] for result in body["trait_results"]} == {
        "Regeneration",
        "Bloodied frenzy",
        "Renew ward",
    }


def test_monster_sequence_and_legendary_action_spend_exactly_once(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Advanced monster economy")
    combat = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats", json={"name": "Dragon fight"}
    ).json()
    hero = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={"display_name": "Hero", "entity_type": "character", "initiative": 20,
              "hp": 40, "max_hp": 40},
    ).json()
    dragon = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={"display_name": "Dragon", "entity_type": "monster", "initiative": 10,
              "hp": 100, "max_hp": 100},
    ).json()
    path = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm"
    legendary = combat_client.post(
        path,
        headers={"X-Request-ID": "legendary-window-once"},
        json={
            "action_type": "damage", "actor_combatant_id": dragon["id"],
            "actor_version": dragon["version"], "action_cost": "legendary_action",
            "legendary_cost": 2, "legendary_pool_max": 3, "action_name": "Tail",
            "target_combatant_id": hero["id"], "target_version": hero["version"],
            "amount": 5, "damage_type": "bludgeoning",
        },
    )
    assert legendary.status_code == 200, legendary.text
    assert legendary.json()["actor"]["snapshot_json"]["legendary_actions_remaining"] == 1
    repeated_window = combat_client.post(
        path,
        headers={"X-Request-ID": "legendary-window-twice"},
        json={
            "action_type": "damage", "actor_combatant_id": dragon["id"],
            "actor_version": legendary.json()["actor"]["version"],
            "action_cost": "legendary_action", "legendary_cost": 1,
            "legendary_pool_max": 3, "action_name": "Wing",
            "target_combatant_id": hero["id"],
            "target_version": legendary.json()["target"]["version"],
            "amount": 3, "damage_type": "bludgeoning",
        },
    )
    assert repeated_window.status_code == 400
    assert "already used" in repeated_window.json()["message"]

    reaction = combat_client.post(
        path,
        headers={"X-Request-ID": "monster-reaction-once"},
        json={
            "action_type": "damage", "actor_combatant_id": dragon["id"],
            "actor_version": legendary.json()["actor"]["version"],
            "action_cost": "reaction", "reaction_trigger": "Hero leaves its reach",
            "action_name": "Opportunity Attack", "target_combatant_id": hero["id"],
            "target_version": legendary.json()["target"]["version"], "amount": 2,
            "damage_type": "piercing",
        },
    )
    assert reaction.status_code == 200, reaction.text
    assert reaction.json()["actor"]["reaction_available"] is False

    lair = combat_client.post(
        path,
        headers={"X-Request-ID": "lair-round-once"},
        json={
            "action_type": "damage", "actor_combatant_id": dragon["id"],
            "actor_version": reaction.json()["actor"]["version"],
            "action_cost": "lair_action", "action_name": "Lair Tremor",
            "target_combatant_id": hero["id"],
            "target_version": reaction.json()["target"]["version"], "amount": 1,
            "damage_type": "bludgeoning",
        },
    )
    assert lair.status_code == 200, lair.text
    assert lair.json()["actor"]["snapshot_json"]["lair_action_round"] == 1


def test_advanced_action_windows_are_persisted_only_at_legal_turn_boundaries(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Advanced action timing")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "Advanced action timing combat"}
    ).json()
    high_guard = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "高先攻守卫",
            "entity_type": "character",
            "initiative": 25,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    dragon = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "窗口龙",
            "entity_type": "monster",
            "initiative": 15,
            "hp": 40,
            "max_hp": 40,
            "snapshot_json": {
                "actions": [
                    {
                        "name": "传奇尾击",
                        "action_type": "legendary_action",
                        "legendary_cost": 1,
                        "legendary_pool_max": 3,
                        "damage": "1d8",
                    },
                    {
                        "name": "巢穴震击",
                        "action_type": "lair_action",
                        "damage": "1d6",
                    },
                ],
                "legendary_actions_remaining": 3,
            },
        },
    ).json()
    low_guard = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "低先攻冒险者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    advance_path = f"{base}/combats/{combat['id']}/turns/advance"
    first = combat_client.post(
        advance_path,
        headers={"X-Request-ID": "advanced-window-lair"},
        json={"combat_version": combat["version"]},
    )
    assert first.status_code == 200, first.text
    assert first.json()["active_combatant"]["id"] == dragon["id"]
    first_actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    first_windows = [
        item["result_json"]["action_window"]
        for item in first_actions
        if item["action_type"] == "eligible_action_window"
    ]
    assert len(first_windows) == 1
    assert first_windows[0]["action_cost"] == "lair_action"
    assert first_windows[0]["trigger"] == "initiative_20"
    assert first_windows[0]["eligible_action_names"] == ["巢穴震击"]
    assert not any(window["action_cost"] == "legendary_action" for window in first_windows)

    current = combat_client.get(f"{base}/combats/{combat['id']}").json()
    second = combat_client.post(
        advance_path,
        headers={"X-Request-ID": "advanced-window-to-low"},
        json={"combat_version": current["version"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["active_combatant"]["id"] == low_guard["id"]
    second_actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    second_windows = [
        item["result_json"]["action_window"]
        for item in second_actions
        if item["action_type"] == "eligible_action_window"
    ]
    assert len(second_windows) == 1
    assert not any(window["action_cost"] == "legendary_action" for window in second_windows)

    current = combat_client.get(f"{base}/combats/{combat['id']}").json()
    third = combat_client.post(
        advance_path,
        headers={"X-Request-ID": "advanced-window-legendary"},
        json={"combat_version": current["version"]},
    )
    assert third.status_code == 200, third.text
    assert third.json()["active_combatant"]["id"] == high_guard["id"]
    third_actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    third_windows = [
        item["result_json"]["action_window"]
        for item in third_actions
        if item["action_type"] == "eligible_action_window"
    ]
    assert len(third_windows) == 2
    legendary_windows = [
        window for window in third_windows
        if window["action_cost"] == "legendary_action"
    ]
    assert len(legendary_windows) == 1
    assert legendary_windows[0]["trigger"] == "other_turn_end"
    assert legendary_windows[0]["trigger_combatant_id"] == low_guard["id"]
    assert legendary_windows[0]["active_combatant_id"] == high_guard["id"]

    repeated = combat_client.post(
        advance_path,
        headers={"X-Request-ID": "advanced-window-legendary"},
        json={"combat_version": current["version"]},
    )
    assert repeated.status_code == 200, repeated.text
    repeated_actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    assert sum(
        item["action_type"] == "eligible_action_window"
        for item in repeated_actions
    ) == 2


def test_structured_turn_end_reaction_window_excludes_reaction_owner_turn(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Structured turn-end reaction")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "Structured turn-end reaction combat"}
    ).json()
    high_guard = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "高先攻守卫",
            "entity_type": "character",
            "initiative": 25,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    monster = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "回合末反应怪",
            "entity_type": "monster",
            "initiative": 15,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "actions": [
                    {
                        "name": "回合末凝视",
                        "action_type": "reaction",
                        "reaction_event": "turn_end",
                        "reaction_trigger": "当另一个生物回合结束时",
                        "damage": "1d6",
                    }
                ]
            },
        },
    ).json()
    low_guard = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "低先攻冒险者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    advance_path = f"{base}/combats/{combat['id']}/turns/advance"
    first = combat_client.post(
        advance_path,
        headers={"X-Request-ID": "turn-end-reaction-first"},
        json={"combat_version": combat["version"]},
    )
    assert first.status_code == 200, first.text
    assert first.json()["active_combatant"]["id"] == monster["id"]
    first_actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    first_windows = [
        item["result_json"]["action_window"]
        for item in first_actions
        if item["action_type"] == "eligible_action_window"
    ]
    assert len(first_windows) == 1
    assert first_windows[0]["action_cost"] == "reaction"
    assert first_windows[0]["reaction_event"] == "turn_end"
    assert first_windows[0]["trigger"] == "other_turn_end"
    assert first_windows[0]["eligible_action_names"] == ["回合末凝视"]
    assert first_windows[0]["trigger_combatant_id"] == high_guard["id"]

    repeated = combat_client.post(
        advance_path,
        headers={"X-Request-ID": "turn-end-reaction-first"},
        json={"combat_version": combat["version"]},
    )
    assert repeated.status_code == 200, repeated.text
    repeated_actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    assert sum(
        item["action_type"] == "eligible_action_window"
        for item in repeated_actions
    ) == 1

    current = combat_client.get(f"{base}/combats/{combat['id']}").json()
    second = combat_client.post(
        advance_path,
        headers={"X-Request-ID": "turn-end-reaction-owner"},
        json={"combat_version": current["version"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["active_combatant"]["id"] == low_guard["id"]
    second_actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    assert sum(
        item["action_type"] == "eligible_action_window"
        for item in second_actions
    ) == 1


def test_structured_takes_damage_reaction_window_is_one_per_damage_event(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Structured damage reaction")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "Structured damage reaction combat"}
    ).json()
    attacker = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "伤害来源",
            "entity_type": "character",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    monster = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "受伤反应怪",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "actions": [
                    {
                        "name": "受伤反击",
                        "action_type": "reaction",
                        "reaction_event": "takes_damage",
                        "reaction_trigger": "受到伤害时",
                    }
                ]
            },
        },
    ).json()
    path = f"{base}/combats/{combat['id']}/actions/confirm"
    response = combat_client.post(
        path,
        headers={"X-Request-ID": "structured-damage-reaction"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "action_cost": "none",
            "action_name": "元素裂解",
            "target_combatant_id": monster["id"],
            "target_version": monster["version"],
            "amount": 11,
            "damage_components": [
                {"amount": 5, "damage_type": "fire"},
                {"amount": 6, "damage_type": "force"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    windows = [
        item["result_json"]["action_window"]
        for item in actions
        if item["action_type"] == "eligible_action_window"
    ]
    assert len(windows) == 1
    assert windows[0]["reaction_event"] == "takes_damage"
    assert windows[0]["trigger"] == "takes_damage"
    assert windows[0]["eligible_action_names"] == ["受伤反击"]
    assert windows[0]["trigger_combatant_id"] == attacker["id"]
    assert windows[0]["damaged_combatant_id"] == monster["id"]
    assert windows[0]["adjusted_damage"] == 11
    assert actions[-1]["request_json"]["damage_action_id"] == response.json()["action"]["id"]

    repeated = combat_client.post(
        path,
        headers={"X-Request-ID": "structured-damage-reaction"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "action_cost": "none",
            "action_name": "元素裂解",
            "target_combatant_id": monster["id"],
            "target_version": monster["version"],
            "amount": 11,
            "damage_components": [
                {"amount": 5, "damage_type": "fire"},
                {"amount": 6, "damage_type": "force"},
            ],
        },
    )
    assert repeated.status_code == 200, repeated.text
    actions_after_repeat = combat_client.get(
        f"{base}/combats/{combat['id']}/actions"
    ).json()["items"]
    assert sum(
        item["action_type"] == "eligible_action_window"
        for item in actions_after_repeat
    ) == 1


def test_structured_casts_spell_reaction_window_opens_before_player_save(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Structured spell reaction")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "Structured spell reaction combat"}
    ).json()
    caster = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "施法怪物",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 24,
            "max_hp": 24,
            "snapshot_json": {
                "actions": [
                    {
                        "name": "震爆术",
                        "action_type": "spellcasting",
                        "spell_level": 2,
                        "range_ft": 60,
                        "damage": "3d6",
                        "damage_type": "force",
                    }
                ]
            },
        },
    ).json()
    counterer = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "反制反应怪",
            "entity_type": "monster",
            "initiative": 15,
            "hp": 24,
            "max_hp": 24,
            "snapshot_json": {
                "actions": [
                    {
                        "name": "反制施法",
                        "action_type": "reaction",
                        "reaction_event": "casts_spell",
                        "reaction_trigger": "看到生物施放法术时",
                    }
                ]
            },
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "施法目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    pending = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending",
        headers={"X-Request-ID": "structured-casts-spell-prompt"},
        json={
            "actor_combatant_id": caster["id"],
            "actor_version": caster["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_cost": "action",
            "action_name": "震爆术",
            "resolution_type": "saving_throw",
            "dc": 14,
            "ability": "dexterity",
            "damage_on_failure": 11,
            "damage_type": "force",
            "description": "施法怪物开始施放震爆术。",
        },
    )
    assert pending.status_code == 200, pending.text
    actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    windows = [
        item["result_json"]["action_window"]
        for item in actions
        if item["action_type"] == "eligible_action_window"
    ]
    assert len(windows) == 1
    assert windows[0]["reaction_event"] == "casts_spell"
    assert windows[0]["trigger_action_type"] == "player_roll_prompt"
    assert windows[0]["trigger_action_name"] == "震爆术"
    assert windows[0]["trigger_combatant_id"] == caster["id"]
    assert windows[0]["eligible_action_names"] == ["反制施法"]
    window_action = next(
        item for item in actions if item["action_type"] == "eligible_action_window"
    )
    assert window_action["request_json"]["spell_action_id"] == pending.json()["action"]["id"]
    assert counterer["id"] != caster["id"]


def test_structured_reaction_event_must_match_monster_action(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Structured reaction event")
    combat = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats", json={"name": "Reaction event"}
    ).json()
    monster = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "守卫",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "actions": [
                    {
                        "name": "借机斩",
                        "action_type": "reaction",
                        "reaction_event": "leaves_reach",
                        "damage": "1d8",
                    }
                ]
            },
        },
    ).json()
    hero = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "冒险者",
            "entity_type": "character",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    path = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm"
    base = {
        "action_type": "damage",
        "actor_combatant_id": monster["id"],
        "actor_version": monster["version"],
        "action_cost": "reaction",
        "action_name": "借机斩",
        "reaction_trigger": "冒险者离开守卫的近战威胁范围",
        "target_combatant_id": hero["id"],
        "target_version": hero["version"],
        "amount": 4,
        "damage_type": "slashing",
    }
    missing = combat_client.post(
        path,
        headers={"X-Request-ID": "reaction-event-missing"},
        json=base,
    )
    assert missing.status_code == 400, missing.text
    assert "structured reaction_event" in missing.json()["message"]

    mismatch = combat_client.post(
        path,
        headers={"X-Request-ID": "reaction-event-mismatch"},
        json={**base, "reaction_event": "takes_damage"},
    )
    assert mismatch.status_code == 400, mismatch.text
    assert "does not match" in mismatch.json()["message"]

    confirmed = combat_client.post(
        path,
        headers={"X-Request-ID": "reaction-event-match"},
        json={**base, "reaction_event": "leaves_reach"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["action"]["result_json"]["action_window"] == {
        "action_cost": "reaction",
        "reaction_event": "leaves_reach",
        "reaction_trigger": "冒险者离开守卫的近战威胁范围",
    }
    assert confirmed.json()["target"]["hp"] == 16


def test_multiattack_sequence_records_independent_hits_and_targets(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Independent multiattack")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(f"{base}/combats", json={"name": "Hydra turn"}).json()
    hydra = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Hydra",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 100,
            "max_hp": 100,
        },
    ).json()
    hero_a = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Hero A",
            "entity_type": "character",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()
    hero_b = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Hero B",
            "entity_type": "character",
            "initiative": 5,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()
    path = f"{base}/combats/{combat['id']}/actions/confirm"
    sequence_id = "hydra-three-bites"

    missed = combat_client.post(
        path,
        headers={"X-Request-ID": "hydra-bite-0"},
        json={
            "action_type": "damage",
            "actor_combatant_id": hydra["id"],
            "actor_version": hydra["version"],
            "action_cost": "action",
            "action_name": "Multiattack · Bite 1",
            "target_combatant_id": hero_a["id"],
            "target_version": hero_a["version"],
            "amount": 0,
            "damage_type": "piercing",
            "is_attack": True,
            "sequence_id": sequence_id,
            "sequence_step": 0,
            "sequence_size": 3,
        },
    )
    assert missed.status_code == 200, missed.text
    assert missed.json()["target"]["hp"] == 30
    assert missed.json()["actor"]["action_available"] is False

    hit_a = combat_client.post(
        path,
        headers={"X-Request-ID": "hydra-bite-1"},
        json={
            "action_type": "damage",
            "actor_combatant_id": hydra["id"],
            "actor_version": missed.json()["actor"]["version"],
            "action_cost": "none",
            "action_name": "Multiattack · Bite 2",
            "target_combatant_id": hero_a["id"],
            "target_version": missed.json()["target"]["version"],
            "amount": 7,
            "damage_type": "piercing",
            "is_attack": True,
            "sequence_id": sequence_id,
            "sequence_step": 1,
            "sequence_size": 3,
        },
    )
    assert hit_a.status_code == 200, hit_a.text
    assert hit_a.json()["target"]["hp"] == 23

    hit_b = combat_client.post(
        path,
        headers={"X-Request-ID": "hydra-bite-2"},
        json={
            "action_type": "damage",
            "actor_combatant_id": hydra["id"],
            "actor_version": hit_a.json()["actor"]["version"],
            "action_cost": "none",
            "action_name": "Multiattack · Bite 3",
            "target_combatant_id": hero_b["id"],
            "target_version": hero_b["version"],
            "amount": 9,
            "damage_type": "piercing",
            "is_attack": True,
            "sequence_id": sequence_id,
            "sequence_step": 2,
            "sequence_size": 3,
        },
    )
    assert hit_b.status_code == 200, hit_b.text
    assert hit_b.json()["target"]["hp"] == 21
    assert hit_b.json()["actor"]["action_available"] is False


def test_multiattack_pauses_before_next_step_until_player_roll_is_confirmed(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Multiattack save pause")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(f"{base}/combats", json={"name": "Save pause"}).json()
    monster = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "多重攻击怪物",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "豁免目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    sequence_id = "multiattack-save-pause"
    prompt = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending",
        headers={"X-Request-ID": "multiattack-save-step-0"},
        json={
            "actor_combatant_id": monster["id"],
            "actor_version": monster["version"],
            "action_cost": "action",
            "action_name": "多重攻击 · 特殊击",
            "resolution_type": "saving_throw",
            "dc": 12,
            "ability": "dexterity",
            "damage_on_failure": 0,
            "sequence_id": sequence_id,
            "sequence_step": 0,
            "sequence_size": 2,
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "description": "第 1 击需要玩家进行敏捷豁免",
        },
    )
    assert prompt.status_code == 200, prompt.text
    prompt_action = prompt.json()["action"]

    blocked = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "multiattack-step-1-blocked"},
        json={
            "action_type": "damage",
            "actor_combatant_id": monster["id"],
            "actor_version": prompt.json()["actor"]["version"],
            "action_cost": "none",
            "action_name": "多重攻击 · 普通击",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 5,
            "damage_type": "piercing",
            "sequence_id": sequence_id,
            "sequence_step": 1,
            "sequence_size": 2,
        },
    )
    assert blocked.status_code == 400, blocked.text
    assert "previous player roll" in blocked.json()["message"]

    resolved = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/{prompt_action['id']}/confirm",
        headers={"X-Request-ID": "multiattack-save-step-0-confirm"},
        json={
            "action_version": prompt_action["version"],
            "roll_total": 12,
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["action"]["status"] == "confirmed"

    continued = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "multiattack-step-1-after-save"},
        json={
            "action_type": "damage",
            "actor_combatant_id": monster["id"],
            "actor_version": prompt.json()["actor"]["version"],
            "action_cost": "none",
            "action_name": "多重攻击 · 普通击",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 5,
            "damage_type": "piercing",
            "sequence_id": sequence_id,
            "sequence_step": 1,
            "sequence_size": 2,
        },
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["target"]["hp"] == 15


def test_attack_geometry_enforces_range_line_of_sight_and_half_cover_ac(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Attack geometry")
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": "Geometry room"}).json()
    grid = combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={
            "width": 8,
            "height": 8,
            "cell_size_ft": 5,
            "mode": "combat",
            "layers_json": {
                "cells": [{"row": 1, "col": 3, "kind": "cover"}]
            },
        },
    )
    assert grid.status_code == 201, grid.text
    combat = combat_client.post(
        f"{base}/combats",
        json={"name": "Geometry combat", "scene_id": scene["id"]},
    ).json()
    attacker = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Archer",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 1, "col": 1}},
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Covered hero",
            "entity_type": "character",
            "initiative": 10,
            "armor_class": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 1, "col": 4}},
        },
    ).json()
    path = f"{base}/combats/{combat['id']}/actions/confirm"
    common = {
        "action_type": "damage",
        "actor_combatant_id": attacker["id"],
        "actor_version": attacker["version"],
        "action_cost": "none",
        "action_name": "Longbow",
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "amount": 5,
        "damage_type": "piercing",
        "is_attack": True,
        "attack_range_ft": 120,
        "attack_roll_mode": "normal",
        "attack_adjudication_note": "服务器按权威网格校验距离、视线和掩体",
    }
    blocked_by_cover = combat_client.post(
        path,
        headers={"X-Request-ID": "cover-miss"},
        json={**common, "attack_roll_total": 11},
    )
    assert blocked_by_cover.status_code == 400
    assert "effective AC 12" in blocked_by_cover.json()["message"]

    hit = combat_client.post(
        path,
        headers={"X-Request-ID": "cover-hit"},
        json={**common, "attack_roll_total": 12},
    )
    assert hit.status_code == 200, hit.text
    contexts = hit.json()["action"]["result_json"]["attack_contexts"]
    assert "distance_ft:15" in contexts
    assert "line_of_sight:true" in contexts
    assert "cover:half" in contexts
    assert "effective_ac:12" in contexts
    assert hit.json()["target"]["hp"] == 15

    wall = combat_client.post(
        f"{base}/scenes/{scene['id']}/objects",
        json={
            "object_type": "wall",
            "label": "Stone wall",
            "row": 1,
            "col": 2,
        },
    )
    assert wall.status_code == 201, wall.text
    no_sight = combat_client.post(
        path,
        headers={"X-Request-ID": "wall-blocks-shot"},
        json={
            **common,
            "target_version": hit.json()["target"]["version"],
            "attack_roll_total": 20,
        },
    )
    assert no_sight.status_code == 400
    assert "no line of sight" in no_sight.json()["message"]


def test_condition_attack_contexts_require_explicit_advantage_ruling(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Condition attack contexts")
    combat, actor = _combatant(combat_client, campaign["id"])
    actor_response = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={"initiative": 20, "conditions": ["中毒"]},
    )
    assert actor_response.status_code == 200, actor_response.text
    actor = actor_response.json()
    target_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "受束缚目标",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "conditions": ["束缚", "目盲"],
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/actions/confirm"
    )
    attack = {
        "action_type": "damage",
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "action_cost": "none",
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "amount": 4,
        "damage_type": "slashing",
        "is_attack": True,
        "attack_roll_total": 15,
    }
    refused = combat_client.post(
        path,
        headers={"X-Request-ID": "condition-contexts-refused"},
        json=attack,
    )
    assert refused.status_code == 400
    assert "will not guess" in refused.json()["message"]

    resolved = combat_client.post(
        path,
        headers={"X-Request-ID": "condition-contexts-resolved"},
        json={
            **attack,
            "attack_roll_mode": "normal",
            "attack_adjudication_note": (
                "DM确认目标目盲且束缚提供优势、攻击者中毒提供劣势；优势与劣势相互抵消"
            ),
        },
    )
    assert resolved.status_code == 200, resolved.text
    contexts = resolved.json()["action"]["result_json"]["attack_contexts"]
    assert "attacker_poisoned" in contexts
    assert "target_blinded" in contexts
    assert "target_restrained" in contexts
    assert "attack_roll_rule:normal_due_to_cancellation" in contexts


def test_frightened_attack_disadvantage_requires_visible_fear_source(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Frightened source visibility")
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": "Fear room"}).json()
    grid = combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 6, "height": 6, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    combat = combat_client.post(
        f"{base}/combats", json={"name": "Fear source combat", "scene_id": scene["id"]}
    ).json()
    source = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "恐惧来源",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 1, "col": 1}},
        },
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "恐慌冒险者",
            "entity_type": "character",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 1, "col": 3}},
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "攻击目标",
            "entity_type": "monster",
            "initiative": 5,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 3, "col": 3}},
        },
    ).json()
    effect = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/confirm",
        headers={"X-Request-ID": "frightened-visible-source"},
        json={
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
            "source_combatant_id": source["id"],
            "source_version": source["version"],
            "name": "恐慌",
            "effect_type": "condition",
            "details_json": {
                "rule_block": {"kind": "condition", "condition": "frightened"},
                "applied_state": {"conditions": []},
            },
        },
    )
    assert effect.status_code == 200, effect.text
    attack_path = f"{base}/combats/{combat['id']}/actions/confirm"
    visible_attack = combat_client.post(
        attack_path,
        headers={"X-Request-ID": "frightened-visible-attack"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": effect.json()["target"]["version"],
            "action_cost": "none",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 1,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_roll_mode": "disadvantage",
            "attack_roll_total": 15,
        },
    )
    assert visible_attack.status_code == 200, visible_attack.text
    visible_contexts = visible_attack.json()["action"]["result_json"]["attack_contexts"]
    assert "attacker_frightened_source_visible" in visible_contexts
    assert "attack_roll_rule:disadvantage" in visible_contexts

    wall = combat_client.post(
        f"{base}/scenes/{scene['id']}/objects",
        json={"object_type": "wall", "label": "遮挡墙", "row": 1, "col": 2},
    )
    assert wall.status_code == 201, wall.text
    refreshed_actor = combat_client.get(
        f"{base}/combats/{combat['id']}/combatants/{actor['id']}"
    ).json()
    refreshed_target = combat_client.get(
        f"{base}/combats/{combat['id']}/combatants/{target['id']}"
    ).json()
    hidden_attack = combat_client.post(
        attack_path,
        headers={"X-Request-ID": "frightened-hidden-attack"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": refreshed_actor["version"],
            "action_cost": "none",
            "target_combatant_id": target["id"],
            "target_version": refreshed_target["version"],
            "amount": 1,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_roll_mode": "normal",
            "attack_roll_total": 15,
        },
    )
    assert hidden_attack.status_code == 200, hidden_attack.text
    hidden_contexts = hidden_attack.json()["action"]["result_json"]["attack_contexts"]
    assert "attacker_frightened_source_not_visible" in hidden_contexts
    assert "attack_roll_rule:disadvantage" not in hidden_contexts


def test_monster_cone_aoe_atomically_applies_distinct_saves_and_defenses(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Monster cone AoE")
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": "Cone room"}).json()
    grid = combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 10, "height": 10, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    combat = combat_client.post(
        f"{base}/combats",
        json={"name": "Breath weapon", "scene_id": scene["id"]},
    ).json()
    dragon = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Dragon",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 100,
            "max_hp": 100,
            "snapshot_json": {
                "grid_position": {"row": 5, "col": 1},
                "recharge_available": {"Flame cone": True},
            },
        },
    ).json()

    def add_target(
        name: str,
        row: int,
        col: int,
        defenses: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        return combat_client.post(
            f"{base}/combats/{combat['id']}/combatants",
            json={
                "display_name": name,
                "entity_type": (
                    "monster"
                    if defenses and "legendary_resistance" in defenses
                    else "character"
                ),
                "initiative": 10 - row,
                "hp": 40,
                "max_hp": 40,
                "snapshot_json": {
                    "grid_position": {"row": row, "col": col},
                    "advanced_defenses": defenses or {},
                },
            },
        ).json()

    normal = add_target("Normal", 5, 3)
    evasive = add_target("Evasive", 4, 3, {"evasion": True})
    resistant = add_target("Magic resistant", 6, 3, {"magic_resistance": True})
    reflexive = add_target(
        "Reflexive",
        3,
        3,
        {
            "reflex_defense": {
                "ability": "dexterity",
                "success_multiplier": 0,
                "failure_multiplier": 0.25,
            }
        },
    )
    legendary = add_target(
        "Legendary",
        5,
        4,
        {"legendary_resistance": {"remaining": 1, "maximum": 1}},
    )
    path = f"{base}/combats/{combat['id']}/monster-area-actions/confirm"
    payload = {
        "actor_combatant_id": dragon["id"],
        "actor_version": dragon["version"],
        "action_name": "Flame cone",
        "action_cost": "action",
        "shape": "cone",
        "size_ft": 20,
        "anchor_row": 5,
        "anchor_col": 5,
        "save_dc": 15,
        "save_ability": "dexterity",
        "damage_total": 20,
        "damage_type": "fire",
        "half_damage_on_save": True,
        "is_magical": True,
        "conditions_on_failure": ["震慑"],
        "condition_duration": "target_turn_end",
        "recharge_key": "Flame cone",
        "recharge_consume": True,
        "dm_geometry_note": "DM确认龙头朝东，使用20尺锥形并按权威网格覆盖全部单位",
        "targets": [
            {
                "target_combatant_id": normal["id"],
                "target_version": normal["version"],
                "roll_total": 10,
            },
            {
                "target_combatant_id": evasive["id"],
                "target_version": evasive["version"],
                "roll_total": 10,
            },
            {
                "target_combatant_id": resistant["id"],
                "target_version": resistant["version"],
                "roll_total": 18,
                "roll_totals": [5, 18],
            },
            {
                "target_combatant_id": legendary["id"],
                "target_version": legendary["version"],
                "roll_total": 5,
                "use_legendary_resistance": True,
            },
            {
                "target_combatant_id": reflexive["id"],
                "target_version": reflexive["version"],
                "roll_total": 5,
            },
        ],
    }
    incomplete = combat_client.post(
        path,
        headers={"X-Request-ID": "cone-aoe-missing-target"},
        json={**payload, "targets": payload["targets"][:-1]},
    )
    assert incomplete.status_code == 400
    assert "does not match authoritative geometry" in incomplete.json()["message"]
    unchanged_dragon = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], dragon["id"])
    ).json()
    assert unchanged_dragon["action_available"] is True
    assert unchanged_dragon["snapshot_json"]["recharge_available"]["Flame cone"] is True

    confirmed = combat_client.post(
        path,
        headers={"X-Request-ID": "cone-aoe-atomic"},
        json=payload,
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    by_name = {target["display_name"]: target for target in body["targets"]}
    assert by_name["Normal"]["hp"] == 20
    assert by_name["Evasive"]["hp"] == 30
    assert by_name["Magic resistant"]["hp"] == 30
    assert by_name["Legendary"]["hp"] == 30
    assert by_name["Reflexive"]["hp"] == 35
    assert "震慑" in by_name["Normal"]["conditions"]
    assert "震慑" in by_name["Evasive"]["conditions"]
    assert "震慑" not in by_name["Magic resistant"]["conditions"]
    assert "震慑" not in by_name["Legendary"]["conditions"]
    assert body["actor"]["action_available"] is False
    assert body["actor"]["snapshot_json"]["recharge_available"]["Flame cone"] is False
    assert by_name["Legendary"]["snapshot_json"]["advanced_defenses"][
        "legendary_resistance"
    ]["remaining"] == 0
    results = {
        result["target_name"]: result
        for result in body["action"]["result_json"]["target_results"]
    }
    assert results["Evasive"]["applied_defenses"] == ["evasion"]
    assert results["Magic resistant"]["applied_defenses"] == ["magic_resistance"]
    assert results["Legendary"]["applied_defenses"] == ["legendary_resistance"]
    assert results["Reflexive"]["applied_defenses"] == ["reflex_defense"]

    replay = combat_client.post(
        path,
        headers={"X-Request-ID": "cone-aoe-atomic"},
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    replay_by_name = {
        target["display_name"]: target for target in replay.json()["targets"]
    }
    assert replay_by_name["Normal"]["hp"] == 20


@pytest.mark.parametrize(
    ("shape", "anchor", "inside", "outside", "area_fields", "action_cost"),
    [
        ("line", (5, 5), (5, 4), (7, 4), {"width_ft": 5}, "reaction"),
        ("cube", (3, 3), (4, 4), (5, 5), {}, "lair_action"),
        ("sphere", (5, 5), (5, 6), (5, 8), {}, "lair_action"),
    ],
)
def test_monster_line_and_cube_aoe_use_server_geometry_and_window_resources(
    combat_client: TestClient,
    shape: str,
    anchor: tuple[int, int],
    inside: tuple[int, int],
    outside: tuple[int, int],
    area_fields: dict[str, int],
    action_cost: str,
) -> None:
    campaign = _campaign(combat_client, f"Monster {shape} AoE")
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": f"{shape} room"}).json()
    combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 10, "height": 10, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = combat_client.post(
        f"{base}/combats",
        json={"name": f"{shape} combat", "scene_id": scene["id"]},
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Area monster",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {"grid_position": {"row": 5, "col": 1}},
        },
    ).json()

    def add(name: str, position: tuple[int, int], initiative: int) -> dict[str, Any]:
        return combat_client.post(
            f"{base}/combats/{combat['id']}/combatants",
            json={
                "display_name": name,
                "entity_type": "character",
                "initiative": initiative,
                "hp": 20,
                "max_hp": 20,
                "snapshot_json": {
                    "grid_position": {"row": position[0], "col": position[1]}
                },
            },
        ).json()

    hit_target = add("Inside", inside, 10)
    safe_target = add("Outside", outside, 5)
    payload: dict[str, Any] = {
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "action_name": f"{shape} burst",
        "action_cost": action_cost,
        "shape": shape,
        "size_ft": 20 if shape == "line" else 10,
        "anchor_row": anchor[0],
        "anchor_col": anchor[1],
        "save_dc": 12,
        "save_ability": "constitution",
        "damage_total": 4,
        "damage_type": "thunder",
        "targets": [
            {
                "target_combatant_id": hit_target["id"],
                "target_version": hit_target["version"],
                "roll_total": 5,
            }
        ],
        "dm_geometry_note": f"DM确认{shape}区域锚点和方向",
        **area_fields,
    }
    if action_cost == "reaction":
        payload["reaction_trigger"] = "敌人进入符文射线"
    response = combat_client.post(
        f"{base}/combats/{combat['id']}/monster-area-actions/confirm",
        headers={"X-Request-ID": f"{shape}-window-first"},
        json=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["targets"][0]["id"] == hit_target["id"]
    assert body["targets"][0]["hp"] == 16
    unchanged = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], safe_target["id"])
    ).json()
    assert unchanged["hp"] == 20
    if action_cost == "reaction":
        assert body["actor"]["reaction_available"] is False
    else:
        assert body["actor"]["snapshot_json"]["lair_action_round"] == 1

    repeated_payload = {
        **payload,
        "actor_version": body["actor"]["version"],
        "targets": [
            {
                "target_combatant_id": hit_target["id"],
                "target_version": body["targets"][0]["version"],
                "roll_total": 5,
            }
        ],
    }
    repeated = combat_client.post(
        f"{base}/combats/{combat['id']}/monster-area-actions/confirm",
        headers={"X-Request-ID": f"{shape}-window-second"},
        json=repeated_payload,
    )
    assert repeated.status_code == 400
    expected = "already been spent" if action_cost == "reaction" else "already used"
    assert expected in repeated.json()["message"]


def test_dash_spends_action_and_adds_current_speed_to_movement(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Dash maneuver")
    combat, actor = _combatant(combat_client, campaign["id"])
    path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/maneuvers/confirm"
    )
    payload = {
        "action_type": "dash",
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
    }
    response = combat_client.post(
        path,
        headers={"X-Request-ID": "dash-once"},
        json=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"]["action_type"] == "dash"
    assert body["actor"]["action_available"] is False
    assert body["actor"]["movement_remaining_ft"] == 60
    assert body["action"]["result_json"]["movement_gained_ft"] == 30

    repeated = combat_client.post(
        path,
        headers={"X-Request-ID": "dash-once"},
        json=payload,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["already_applied"] is True
    assert repeated.json()["actor"]["movement_remaining_ft"] == 60


def test_stand_up_consumes_half_speed_and_removes_prone(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Stand maneuver")
    combat, actor = _combatant(combat_client, campaign["id"])
    patched = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={"conditions": ["倒地"], "movement_remaining_ft": 20},
    )
    assert patched.status_code == 200, patched.text
    actor = patched.json()
    response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/maneuvers/confirm",
        headers={"X-Request-ID": "stand-once"},
        json={
            "action_type": "stand_up",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()["actor"]
    assert "倒地" not in updated["conditions"]
    assert updated["movement_remaining_ft"] == 5
    assert updated["action_available"] is True


def test_grapple_requires_dm_outcome_applies_real_effect_and_can_end(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Grapple maneuver")
    combat, actor = _combatant(combat_client, campaign["id"])
    actor_response = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={"initiative": 20},
    )
    assert actor_response.status_code == 200, actor_response.text
    actor = actor_response.json()
    target_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "逃跑的地精",
            "initiative": 0,
            "hp": 7,
            "max_hp": 7,
            "speed_ft": 30,
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"

    missing_ruling = combat_client.post(
        f"{root}/maneuvers/confirm",
        headers={"X-Request-ID": "grapple-no-ruling"},
        json={
            "action_type": "grapple",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
        },
    )
    assert missing_ruling.status_code == 422

    grappled = combat_client.post(
        f"{root}/maneuvers/confirm",
        headers={"X-Request-ID": "grapple-success"},
        json={
            "action_type": "grapple",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "outcome": "success",
            "adjudication_note": "DM确认力量/敏捷对抗失败",
        },
    )
    assert grappled.status_code == 200, grappled.text
    body = grappled.json()
    assert body["target"]["speed_ft"] == 0
    assert "擒抱" in body["target"]["conditions"]
    assert body["effect"]["status"] == "active"

    ended = combat_client.post(
        f"{root}/effects/{body['effect']['id']}/end",
        headers={"X-Request-ID": "grapple-end"},
        json={
            "target_version": body["target"]["version"],
            "source_version": body["actor"]["version"],
            "reason": "目标挣脱擒抱",
        },
    )
    assert ended.status_code == 200, ended.text
    restored = ended.json()["target"]
    assert restored["speed_ft"] == 30
    assert "擒抱" not in restored["conditions"]


def test_shove_push_uses_explicit_distance_and_updates_grid_position(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Shove maneuver")
    combat, actor = _combatant(combat_client, campaign["id"])
    actor_patch = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], actor["id"]),
        headers={"If-Match": f'"{actor["version"]}"'},
        json={
            "initiative": 20,
            "snapshot_json": {"grid_position": {"row": 2, "col": 2}},
        },
    )
    assert actor_patch.status_code == 200, actor_patch.text
    actor = actor_patch.json()
    target_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "推撞目标",
            "initiative": 0,
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {"grid_position": {"row": 2, "col": 3}},
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()
    response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/maneuvers/confirm",
        headers={"X-Request-ID": "shove-push-success"},
        json={
            "action_type": "shove",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "outcome": "success",
            "shove_mode": "push",
            "push_distance_ft": 5,
            "adjudication_note": "DM确认目标未通过推撞豁免",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"]["result_json"]["moved_ft"] == 5
    assert body["target"]["snapshot_json"]["grid_position"] == {
        "row": 2,
        "col": 4,
    }


def test_compiled_modifier_is_applied_and_restored_when_effect_ends(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Compiled effect lifecycle")
    combat, target = _combatant(combat_client, campaign["id"])
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    confirm = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "compiled-ac-effect"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "树肤术",
            "effect_type": "buff",
            "details_json": {
                "rule_block": {
                    "id": "b100-modifier",
                    "kind": "modifier",
                    "stat": "armor_class",
                    "operation": "add",
                    "value": 5,
                    "scope": "all",
                }
            },
            "duration_unit": "rounds",
            "duration_value": 10,
        },
    )
    assert confirm.status_code == 200, confirm.text
    effect = confirm.json()["effect"]
    changed = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()
    assert changed["armor_class"] == target["armor_class"] + 5

    ended = combat_client.post(
        f"{root}/effects/{effect['id']}/end",
        headers={"X-Request-ID": "compiled-ac-effect-end"},
        json={
            "target_version": changed["version"],
            "reason": "法术结束",
        },
    )
    assert ended.status_code == 200, ended.text
    restored = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()
    assert restored["armor_class"] == target["armor_class"]


def test_compiled_condition_respects_condition_immunity_without_creating_effect(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Condition immunity boundary")
    combat, target = _combatant(combat_client, campaign["id"])
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    immune = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], target["id"]),
        headers={"If-Match": f'"{target["version"]}"'},
        json={"condition_immunities": ["poisoned"]},
    )
    assert immune.status_code == 200, immune.text
    target = immune.json()

    rejected = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "immune-compiled-condition"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "毒素诅咒",
            "effect_type": "condition",
            "details_json": {
                "rule_block": {
                    "kind": "condition",
                    "condition": "中毒",
                    "operation": "apply",
                }
            },
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "免疫状态" in rejected.json()["message"]

    unchanged = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()
    assert unchanged["conditions"] == []
    assert unchanged["version"] == target["version"]
    effects = combat_client.get(f"{root}/effects").json()
    assert effects["items"] == []

    unimmune = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], target["id"]),
        headers={"If-Match": f'"{target["version"]}"'},
        json={"condition_immunities": []},
    ).json()
    restrained = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "compiled-restrained-condition"},
        json={
            "target_combatant_id": unimmune["id"],
            "target_version": unimmune["version"],
            "name": "束缚",
            "effect_type": "condition",
            "details_json": {
                "rule_block": {
                    "kind": "condition",
                    "condition": "束缚",
                    "operation": "apply",
                }
            },
        },
    )
    assert restrained.status_code == 200, restrained.text
    restrained_target = restrained.json()["target"]
    assert restrained_target["speed_ft"] == 0
    assert restrained_target["movement_remaining_ft"] == 0
    ended = combat_client.post(
        f"{root}/effects/{restrained.json()['effect']['id']}/end",
        headers={"X-Request-ID": "compiled-restrained-condition-end"},
        json={
            "target_version": restrained_target["version"],
            "reason": "束缚结束",
        },
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["target"]["speed_ft"] == 30
    assert ended.json()["target"]["movement_remaining_ft"] == 30


def test_compiled_timed_effect_is_automatically_reversed_at_expiry(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Automatic effect expiry")
    combat, target = _combatant(combat_client, campaign["id"])
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    confirmed = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "auto-expiry-effect"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "飞行术",
            "effect_type": "buff",
            "details_json": {
                "rule_block": {
                    "kind": "modifier",
                    "stat": "speed_ft",
                    "operation": "add",
                    "value": 30,
                }
            },
            "duration_unit": "rounds",
            "duration_value": 1,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    changed = confirmed.json()["target"]
    assert changed["speed_ft"] == target["speed_ft"] + 30
    current_combat = combat_client.get(root).json()
    advanced = combat_client.post(
        f"{root}/turns/advance",
        headers={"X-Request-ID": "auto-expiry-advance"},
        json={"combat_version": current_combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["expiration_prompts"] == []
    assert len(advanced.json()["expired_rule_effects"]) == 1
    restored = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()
    assert restored["speed_ft"] == target["speed_ft"]
    effects = combat_client.get(f"{root}/effects").json()["items"]
    assert effects[0]["status"] == "ended"


def test_condition_alias_does_not_duplicate_or_remove_existing_state(
    combat_client: TestClient,
) -> None:
    """Chinese and English condition names share one lifecycle slot."""

    campaign = _campaign(combat_client, "Condition alias lifecycle")
    combat, target = _combatant(combat_client, campaign["id"])
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    seeded = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], target["id"]),
        headers={"If-Match": f'"{target["version"]}"'},
        json={"conditions": ["中毒"]},
    )
    assert seeded.status_code == 200, seeded.text
    target = seeded.json()

    applied = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "condition-alias-apply"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "Poisoned alias",
            "effect_type": "condition",
            "details_json": {
                "rule_block": {
                    "kind": "condition",
                    "condition": "poisoned",
                    "operation": "apply",
                }
            },
            "duration_unit": "until_removed",
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["target"]["conditions"] == ["中毒"]

    ended = combat_client.post(
        f"{root}/effects/{applied.json()['effect']['id']}/end",
        headers={"X-Request-ID": "condition-alias-end"},
        json={
            "target_version": applied.json()["target"]["version"],
            "reason": "别名来源结束",
        },
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["target"]["conditions"] == ["中毒"]


def test_structured_condition_round_duration_expires_and_restores_previous_states(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Condition lifecycle")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "Condition lifecycle combat"}
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Condition caster",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Already poisoned",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "conditions": ["中毒"],
        },
    ).json()
    path = f"{base}/combats/{combat['id']}/actions/confirm"
    applied = combat_client.post(
        path,
        headers={"X-Request-ID": "condition-round-apply"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 0,
            "damage_type": "force",
            "conditions_to_apply": ["束缚"],
            "condition_duration": "rounds",
            "condition_duration_value": 1,
        },
    )
    assert applied.status_code == 200, applied.text
    applied_target = applied.json()["target"]
    assert set(applied_target["conditions"]) == {"中毒", "束缚"}
    assert applied_target["speed_ft"] == 0
    assert applied_target["movement_remaining_ft"] == 0
    effect_ids = applied.json()["action"]["result_json"]["structured_effects"]["effect_ids"]
    assert effect_ids

    current = combat_client.get(f"{base}/combats/{combat['id']}").json()
    next_turn = combat_client.post(
        f"{base}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "condition-round-next"},
        json={"combat_version": current["version"]},
    )
    assert next_turn.status_code == 200, next_turn.text
    wrapped = combat_client.post(
        f"{base}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "condition-round-expire"},
        json={"combat_version": next_turn.json()["combat"]["version"]},
    )
    assert wrapped.status_code == 200, wrapped.text
    assert any(item["id"] in effect_ids for item in wrapped.json()["expired_rule_effects"])
    restored = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()
    assert "束缚" not in restored["conditions"]
    assert restored["speed_ft"] == 30
    assert restored["movement_remaining_ft"] == 30


def test_turn_start_condition_expiry_refreshes_new_turn_resources(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Turn-start condition expiry")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "Turn-start condition combat"}
    ).json()
    caster = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Condition caster",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Freed target",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    applied = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "turn-start-condition-apply"},
        json={
            "action_type": "damage",
            "actor_combatant_id": caster["id"],
            "actor_version": caster["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 0,
            "damage_type": "force",
            "conditions_to_apply": ["震慑"],
            "condition_duration": "target_turn_start",
        },
    )
    assert applied.status_code == 200, applied.text
    applied_target = applied.json()["target"]
    assert applied_target["action_available"] is False
    current = combat_client.get(f"{base}/combats/{combat['id']}").json()

    advanced = combat_client.post(
        f"{base}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "turn-start-condition-expire"},
        json={"combat_version": current["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    active = advanced.json()["active_combatant"]
    assert active["id"] == target["id"]
    assert "震慑" not in active["conditions"]
    assert active["action_available"] is True
    assert active["bonus_action_available"] is True
    assert active["reaction_available"] is True
    assert active["movement_remaining_ft"] == active["speed_ft"]


def test_explicit_condition_end_trigger_cleans_up_when_source_becomes_unconscious(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Predicated condition lifecycle")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Lifecycle combat"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()

    source_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "施法者",
            "entity_type": "character",
            "hp": 10,
            "max_hp": 10,
        },
    )
    target_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "被恐慌目标",
            "hp": 10,
            "max_hp": 10,
            "conditions": ["中毒"],
        },
    )
    assert source_response.status_code == target_response.status_code == 201
    source = source_response.json()
    target = target_response.json()
    effect_path = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/effects"
    created = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "predicated-condition"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "source_combatant_id": source["id"],
            "source_version": source["version"],
            "name": "恐慌来源",
            "effect_type": "condition",
            "details_json": {
                "rule_block": {
                    "kind": "condition",
                    "condition": "frightened",
                    "operation": "apply",
                    "end_triggers": ["source_unconscious"],
                },
                "applied_state": {"conditions": []},
            },
        },
    )
    assert created.status_code == 200, created.text
    assert "frightened" in created.json()["target"]["conditions"]

    dropped = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "source-drops-to-zero"},
        json={
            "action_type": "damage",
            "target_combatant_id": source["id"],
            "target_version": source["version"],
            "amount": 10,
            "damage_type": "fire",
        },
    )
    assert dropped.status_code == 200, dropped.text
    dropped_result = dropped.json()["action"]["result_json"]
    assert dropped_result["ended_predicated_effect_ids"] == [created.json()["effect"]["id"]]
    refreshed_target = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants/{target['id']}"
    ).json()
    assert "frightened" not in refreshed_target["conditions"]
    restored = combat_client.get(
        f"{base}/combats/{combat['id']}/combatants/{target['id']}"
    ).json()
    assert restored["conditions"] == ["中毒"]


def test_repeating_compiled_damage_ticks_at_turn_start_and_is_returned_to_client(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Repeating effect execution")
    combat, target = _combatant(combat_client, campaign["id"])
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    confirmed = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "compiled-dot-effect"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "持续灼烧",
            "effect_type": "damage_over_time",
            "details_json": {
                "rule_block": {
                    "id": "b100-damage",
                    "kind": "damage",
                    "expression": "1d4",
                    "damage_type": "fire",
                },
                "damage_expression": "1d4",
                "damage_type": "fire",
                "repeat": {"timing": "turn_start"},
            },
            "duration_unit": "rounds",
            "duration_value": 3,
            "trigger_timing": "turn_start",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    current_combat = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    ).json()
    advanced = combat_client.post(
        f"{root}/turns/advance",
        headers={"X-Request-ID": "compiled-dot-tick"},
        json={"combat_version": current_combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    body = advanced.json()
    assert len(body["effect_ticks"]) == 1
    result = body["effect_ticks"][0]["result"]
    assert 0 <= result["adjusted_damage"] <= 4
    assert result["damage_type"] == "fire"
    updated = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()
    assert updated["hp"] <= target["hp"]


def test_repeating_mixed_damage_ticks_keep_each_segment_and_defense(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Repeating mixed damage")
    combat, target = _combatant(combat_client, campaign["id"])
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    confirmed = combat_client.post(
        f"{root}/effects/confirm",
        headers={"X-Request-ID": "compiled-mixed-dot-effect"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "持续混合灼烧",
            "effect_type": "damage_over_time",
            "details_json": {
                "damage_components": [
                    {"expression": "3", "damage_type": "fire"},
                    {"expression": "4", "damage_type": "cold"},
                ],
                "rule_block": {
                    "kind": "damage",
                    "components": [
                        {"expression": "3", "damage_type": "fire"},
                        {"expression": "4", "damage_type": "cold"},
                    ],
                },
            },
            "duration_unit": "rounds",
            "duration_value": 3,
            "trigger_timing": "turn_start",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    current_combat = combat_client.get(root).json()
    advanced = combat_client.post(
        f"{root}/turns/advance",
        headers={"X-Request-ID": "compiled-mixed-dot-tick"},
        json={"combat_version": current_combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    result = advanced.json()["effect_ticks"][0]["result"]
    assert result["damage_type"] == "mixed"
    assert [item["damage_type"] for item in result["damage_components"]] == [
        "fire",
        "cold",
    ]
    assert [item["original_damage"] for item in result["damage_components"]] == [3, 4]
    # Fire resistance applies only to the fire segment; cold remains full.
    assert [item["adjusted_damage"] for item in result["damage_components"]] == [1, 4]
    assert result["adjusted_damage"] == 5


def test_repeating_damage_tick_opens_takes_damage_reaction_window(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Repeating damage reaction")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "Repeating damage reaction combat"}
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "持续受伤反应怪",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "actions": [
                    {
                        "name": "持续反击",
                        "action_type": "reaction",
                        "reaction_event": "takes_damage",
                    }
                ]
            },
        },
    ).json()
    effect = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/confirm",
        headers={"X-Request-ID": "repeating-damage-reaction-effect"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "持续火焰",
            "effect_type": "damage_over_time",
            "details_json": {
                "damage_expression": "4",
                "damage_type": "fire",
                "repeat": {"timing": "turn_start"},
            },
            "duration_unit": "rounds",
            "duration_value": 2,
            "trigger_timing": "turn_start",
        },
    )
    assert effect.status_code == 200, effect.text
    current = combat_client.get(f"{base}/combats/{combat['id']}").json()
    advanced = combat_client.post(
        f"{base}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "repeating-damage-reaction-advance"},
        json={"combat_version": current["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["effect_ticks"][0]["result"]["adjusted_damage"] == 4
    actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    windows = [
        item["result_json"]["action_window"]
        for item in actions
        if item["action_type"] == "eligible_action_window"
    ]
    assert len(windows) == 1
    assert windows[0]["trigger_action_type"] == "effect_tick"
    assert windows[0]["damaged_combatant_id"] == target["id"]


def test_repeating_compiled_state_ticks_reconcile_without_stacking(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Repeating state lifecycle")
    combat, target = _combatant(combat_client, campaign["id"])
    root = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"

    def add_effect(request_id: str, block: dict[str, Any], effect_type: str) -> None:
        nonlocal target
        response = combat_client.post(
            f"{root}/effects/confirm",
            headers={"X-Request-ID": request_id},
            json={
                "target_combatant_id": target["id"],
                "target_version": target["version"],
                "name": request_id,
                "effect_type": effect_type,
                "details_json": {
                    "rule_block": block,
                    "repeat": {"timing": "turn_start"},
                },
                "duration_unit": "rounds",
                "duration_value": 3,
                "trigger_timing": "turn_start",
            },
        )
        assert response.status_code == 200, response.text
        target = combat_client.get(
            _fighter_path(campaign["id"], combat["id"], target["id"])
        ).json()

    add_effect(
        "repeating-condition",
        {
            "id": "state-condition",
            "kind": "condition",
            "condition": "恐慌",
            "operation": "apply",
        },
        "condition",
    )
    add_effect(
        "repeating-defense",
        {
            "id": "state-defense",
            "kind": "defense",
            "operation": "resistance",
            "damage_types": ["cold"],
        },
        "buff",
    )
    add_effect(
        "repeating-ac",
        {
            "id": "state-ac",
            "kind": "modifier",
            "stat": "armor_class",
            "operation": "add",
            "value": 5,
        },
        "buff",
    )

    reset = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], target["id"]),
        headers={"If-Match": f'"{target["version"]}"'},
        json={
            "armor_class": 10,
            "conditions": [],
            "damage_resistances": [],
        },
    )
    assert reset.status_code == 200, reset.text
    target = reset.json()
    current_combat = combat_client.get(root).json()
    advanced = combat_client.post(
        f"{root}/turns/advance",
        headers={"X-Request-ID": "repeating-state-tick"},
        json={"combat_version": current_combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    body = advanced.json()
    assert len(body["effect_ticks"]) == 3
    assert all(
        tick["result"]["rule_block_kind"] in {"condition", "defense", "modifier"}
        for tick in body["effect_ticks"]
    )

    updated = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()
    assert "恐慌" in updated["conditions"]
    assert "cold" in updated["damage_resistances"]
    assert updated["armor_class"] == 15


def test_player_roll_prompt_records_actor_target_action_and_dm_confirmation(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, player = _combatant(combat_client, campaign["id"])
    monster_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "相位蜘蛛",
            "entity_type": "monster",
            "initiative": 30,
            "hp": 32,
            "max_hp": 32,
            "armor_class": 13,
        },
    )
    assert monster_response.status_code == 201
    monster = monster_response.json()

    pending = combat_client.post(
        (
            f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
            "/actions/player-rolls/pending"
        ),
        headers={"X-Request-ID": "phase-spider-bite"},
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
            "description": "玩家亲自掷体质豁免。",
        },
    )
    assert pending.status_code == 200, pending.json()
    action = pending.json()["action"]
    assert action["status"] == "previewed"
    assert action["request_json"]["actor_name"] == "相位蜘蛛"
    assert action["request_json"]["target_name"] == "Fire Guard"
    assert "相位蜘蛛 对 Fire Guard 使用「毒牙」" in action["summary"]
    assert "等待玩家进行 constitution豁免" in action["summary"]
    spent_actor = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], monster["id"])
    ).json()
    assert spent_actor["action_available"] is False

    preview = combat_client.post(
        (
            f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
            f"/actions/player-rolls/{action['id']}/preview"
        ),
        json={"action_version": action["version"], "roll_total": 9},
    )
    assert preview.status_code == 200
    assert preview.json()["resolution"]["success"] is False
    follow_up = preview.json()["resolution"]["follow_up_damage"]
    assert follow_up["actor_combatant_id"] == monster["id"]
    assert follow_up["target_combatant_id"] == player["id"]
    assert follow_up["amount"] == 7
    assert follow_up["action_name"] == "毒牙"
    assert "玩家骰总值 9 对抗 DC 11，失败" in follow_up["resolution_note"]

    confirmed = combat_client.post(
        (
            f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
            f"/actions/player-rolls/{action['id']}/confirm"
        ),
        headers={"X-Request-ID": "phase-spider-bite-roll"},
        json={
            "action_version": action["version"],
            "roll_total": 9,
            "dm_note": "玩家报告骰面为 9。",
        },
    )
    assert confirmed.status_code == 200
    resolved = confirmed.json()
    assert resolved["action"]["status"] == "confirmed"
    assert resolved["resolution"]["roll_total"] == 9
    assert resolved["resolution"]["success"] is False
    assert "Fire Guard 掷骰 9 对抗 DC 11，失败" in resolved["action"]["summary"]

    unchanged = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], player["id"])
    ).json()
    assert unchanged["hp"] == 20
    assert resolved["resolution"]["follow_up_damage"]["target_version"] == unchanged["version"]


def test_player_roll_prompt_requires_save_ability_and_damage_type(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, player = _combatant(combat_client, campaign["id"])
    path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/actions/player-rolls/pending"
    )
    invalid = combat_client.post(
        path,
        json={
            "actor_combatant_id": player["id"],
            "actor_version": player["version"],
            "target_combatant_id": player["id"],
            "target_version": player["version"],
            "action_name": "测试",
            "resolution_type": "saving_throw",
            "dc": 10,
            "damage_on_failure": 1,
        },
    )
    assert invalid.status_code == 422


def test_player_roll_prompt_batch_creates_all_3d_save_prompts_atomically(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Atomic 3D player saves")
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": "3D save chamber"}).json()
    grid = combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 10, "height": 10, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    combat = combat_client.post(
        f"{base}/combats",
        json={"name": "Atomic save combat", "scene_id": scene["id"]},
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "高空熔火术士",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 40,
            "max_hp": 40,
            "snapshot_json": {"grid_position": {"row": 4, "col": 2, "elevation_ft": 10}},
        },
    ).json()
    low_target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "近柱玩家",
            "entity_type": "character",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {"grid_position": {"row": 4, "col": 5, "elevation_ft": 10}},
        },
    ).json()
    raised_target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "低空玩家",
            "entity_type": "character",
            "initiative": 5,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {"grid_position": {"row": 5, "col": 5, "elevation_ft": 5}},
        },
    ).json()
    path = f"{base}/combats/{combat['id']}/actions/player-rolls/pending/batch"
    payload = {
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "action_cost": "action",
        "action_name": "熔火柱",
        "resolution_type": "saving_throw",
        "dc": 15,
        "ability": "dexterity",
        "damage_on_failure": 12,
        "damage_on_success": 6,
        "damage_type": "fire",
        "sequence_id": "molten-pillar",
        "sequence_step": 0,
        "sequence_size": 1,
        "area_shape": "cylinder",
        "area_size_ft": 20,
        "area_height_ft": 15,
        "area_anchor_row": 4,
        "area_anchor_col": 5,
        "area_anchor_height_ft": 0,
        "requires_explicit_elevation": True,
        "targets": [
            {
                "target_combatant_id": low_target["id"],
                "target_version": low_target["version"],
            },
            {
                "target_combatant_id": raised_target["id"],
                "target_version": raised_target["version"],
            },
        ],
    }

    response = combat_client.post(
        path,
        headers={"X-Request-ID": "atomic-3d-player-save"},
        json=payload,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["already_applied"] is False
    assert len(body["actions"]) == 2
    assert [action["target_combatant_ids"] for action in body["actions"]] == [
        [low_target["id"]],
        [raised_target["id"]],
    ]
    assert all(action["status"] == "previewed" for action in body["actions"])
    assert [
        action["request_json"]["area_geometry"]["elevation_ft"]
        for action in body["actions"]
    ] == [10, 5]
    assert {action["transaction_id"] for action in body["actions"]} == {
        body["transaction"]["id"]
    }
    assert body["actor"]["action_available"] is False
    assert body["actor"]["version"] == actor["version"] + 1

    replay = combat_client.post(
        path,
        headers={"X-Request-ID": "atomic-3d-player-save"},
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    assert [action["id"] for action in replay.json()["actions"]] == [
        action["id"] for action in body["actions"]
    ]


def test_player_roll_prompt_batch_target_conflict_has_no_side_effects(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Atomic save conflict")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(f"{base}/combats", json={"name": "Conflict combat"}).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "火焰巨人",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 40,
            "max_hp": 40,
        },
    ).json()
    first_target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "第一位玩家",
            "entity_type": "character",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()
    stale_target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "陈旧版本玩家",
            "entity_type": "character",
            "initiative": 5,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()

    response = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending/batch",
        headers={"X-Request-ID": "atomic-save-target-conflict"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_name": "烈焰爆发",
            "resolution_type": "saving_throw",
            "dc": 14,
            "ability": "dexterity",
            "damage_on_failure": 10,
            "damage_type": "fire",
            "targets": [
                {
                    "target_combatant_id": first_target["id"],
                    "target_version": first_target["version"],
                },
                {
                    "target_combatant_id": stale_target["id"],
                    "target_version": stale_target["version"] + 1,
                },
            ],
        },
    )

    assert response.status_code == 409, response.text
    unchanged_actor = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], actor["id"])
    ).json()
    assert unchanged_actor["version"] == actor["version"]
    assert unchanged_actor["action_available"] is True
    actions = combat_client.get(f"{base}/combats/{combat['id']}/actions")
    assert actions.status_code == 200, actions.text
    assert actions.json()["items"] == []


def test_player_roll_prompt_batch_consumes_action_economy_once(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Batch resource once")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(f"{base}/combats", json={"name": "Resource once combat"}).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "风暴法师",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()
    first_target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "玩家甲",
            "entity_type": "character",
            "initiative": 10,
            "hp": 24,
            "max_hp": 24,
        },
    ).json()
    second_target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "玩家乙",
            "entity_type": "character",
            "initiative": 5,
            "hp": 24,
            "max_hp": 24,
        },
    ).json()

    response = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending/batch",
        headers={"X-Request-ID": "batch-action-resource-once"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_cost": "action",
            "action_name": "连锁闪电",
            "resolution_type": "saving_throw",
            "dc": 15,
            "ability": "dexterity",
            "damage_on_failure": 8,
            "damage_type": "lightning",
            "targets": [
                {
                    "target_combatant_id": first_target["id"],
                    "target_version": first_target["version"],
                },
                {
                    "target_combatant_id": second_target["id"],
                    "target_version": second_target["version"],
                },
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["actions"]) == 2
    assert body["actor"]["action_available"] is False
    assert body["actor"]["version"] == actor["version"] + 1
    persisted_actor = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], actor["id"])
    ).json()
    assert persisted_actor["version"] == actor["version"] + 1
    assert persisted_actor["action_available"] is False


def test_player_roll_prompt_preserves_typed_damage_segments_through_follow_up(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Prompt mixed damage")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "Prompt mixed damage combat"}
    ).json()
    caster = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Monster caster",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Resistant target",
            "entity_type": "character",
            "initiative": 10,
            "hp": 50,
            "max_hp": 50,
            "damage_resistances": ["fire"],
            "damage_vulnerabilities": ["cold"],
        },
    ).json()
    root = f"{base}/combats/{combat['id']}"
    pending = combat_client.post(
        f"{root}/actions/player-rolls/pending",
        headers={"X-Request-ID": "prompt-mixed-segments"},
        json={
            "actor_combatant_id": caster["id"],
            "actor_version": caster["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_name": "Split blast",
            "resolution_type": "saving_throw",
            "dc": 15,
            "ability": "dexterity",
            "damage_components_on_failure": [
                {"amount": 7, "damage_type": "fire"},
                {"amount": 5, "damage_type": "cold"},
            ],
        },
    )
    assert pending.status_code == 200, pending.text
    action = pending.json()["action"]
    resolved = combat_client.post(
        f"{root}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "prompt-mixed-segments-roll"},
        json={"action_version": action["version"], "roll_total": 4},
    )
    assert resolved.status_code == 200, resolved.text
    resolution = resolved.json()["resolution"]
    assert resolution["damage"] == 12
    assert resolution["damage_type"] == "mixed"
    assert resolution["damage_components"] == [
        {"amount": 7, "damage_type": "fire"},
        {"amount": 5, "damage_type": "cold"},
    ]

    follow_up = resolution["follow_up_damage"]
    applied = combat_client.post(
        f"{root}/actions/confirm",
        headers={"X-Request-ID": "prompt-mixed-segments-damage"},
        json={
            **follow_up,
            "target_version": resolved.json()["target"]["version"],
        },
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()["action"]["result_json"]
    assert result["damage_type"] == "mixed"
    assert [item["adjusted_damage"] for item in result["damage_components"]] == [
        3,
        10,
    ]
    assert applied.json()["target"]["hp"] == 37


def test_save_defenses_override_outcome_and_consume_legendary_resistance(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Advanced save defenses")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(f"{base}/combats", json={"name": "Defense saves"}).json()
    caster = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Caster",
            "entity_type": "character",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    defender = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Ancient fiend",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 50,
            "max_hp": 50,
            "snapshot_json": {
                "advanced_defenses": {
                    "magic_resistance": True,
                    "evasion": True,
                    "legendary_resistance": {"remaining": 1, "maximum": 1},
                }
            },
        },
    ).json()
    root = f"{base}/combats/{combat['id']}"
    pending = combat_client.post(
        f"{root}/actions/player-rolls/pending",
        headers={"X-Request-ID": "advanced-save-prompt"},
        json={
            "actor_combatant_id": caster["id"],
            "actor_version": caster["version"],
            "target_combatant_id": defender["id"],
            "target_version": defender["version"],
            "action_name": "Arcane blast",
            "resolution_type": "saving_throw",
            "dc": 15,
            "ability": "dexterity",
            "damage_on_failure": 20,
            "damage_on_success": 10,
            "damage_type": "force",
            "is_magical": True,
        },
    )
    assert pending.status_code == 200, pending.text
    action = pending.json()["action"]

    missing_advantage_roll = combat_client.post(
        f"{root}/actions/player-rolls/{action['id']}/preview",
        json={"action_version": action["version"], "roll_total": 5},
    )
    assert missing_advantage_roll.status_code == 400
    assert "requires two reported save totals" in missing_advantage_roll.json()["message"]

    resolved = combat_client.post(
        f"{root}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "advanced-save-confirm"},
        json={
            "action_version": action["version"],
            "roll_total": 12,
            "roll_totals": [5, 12],
            "use_legendary_resistance": True,
        },
    )
    assert resolved.status_code == 200, resolved.text
    resolution = resolved.json()["resolution"]
    assert resolution["success"] is True
    assert resolution["damage"] == 0
    assert resolution["follow_up_damage"] is None
    assert resolution["applied_defenses"] == [
        "magic_resistance",
        "legendary_resistance",
        "evasion",
    ]
    assert resolution["defense_resource_consumed"] == {
        "resource": "legendary_resistance",
        "before": 1,
        "after": 0,
    }
    assert resolved.json()["target"]["snapshot_json"]["advanced_defenses"][
        "legendary_resistance"
    ]["remaining"] == 0


def test_healing_respects_max_hp_reduction(combat_client: TestClient) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    patch = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], fighter["id"]),
        headers={"If-Match": '"1"'},
        json={
            "hp": 10,
            "max_hp_reduction": 5,
        },
    )
    assert patch.status_code == 200
    healed = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "heal-once"},
        json={
            "action_type": "heal",
            "target_combatant_id": fighter["id"],
            "target_version": patch.json()["version"],
            "amount": 20,
        },
    )

    assert healed.status_code == 200
    assert healed.json()["target"]["hp"] == 15
    assert healed.json()["action"]["result_json"]["hp_gained"] == 5
    assert healed.json()["action"]["result_json"]["unapplied_healing"] == 15


def test_zero_hp_creates_death_track_and_natural_twenty_recovers(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    dropped = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "drop-to-zero"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 23,
            "damage_type": "force",
        },
    )
    assert dropped.status_code == 200
    assert dropped.json()["target"]["hp"] == 0
    assert "昏迷" in dropped.json()["target"]["conditions"]
    assert dropped.json()["action"]["result_json"]["condition_changes"] == [
        "added:unconscious"
    ]

    death_track_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        f"/combatants/{fighter['id']}/death-save"
    )
    track = combat_client.get(death_track_path)
    assert track.status_code == 200
    assert track.json()["successes"] == 0
    assert track.json()["failures"] == 0

    recovered = combat_client.post(
        f"{death_track_path}/confirm",
        headers={"X-Request-ID": "natural-twenty"},
        json={
            "target_version": dropped.json()["target"]["version"],
            "roll": 20,
        },
    )
    assert recovered.status_code == 200
    assert recovered.json()["target"]["hp"] == 1
    assert "昏迷" not in recovered.json()["target"]["conditions"]
    assert recovered.json()["death_save"]["successes"] == 0
    assert recovered.json()["death_save"]["failures"] == 0
    assert recovered.json()["action"]["result_json"]["hp_restored"] == 1
    assert recovered.json()["action"]["result_json"]["condition_changes"] == [
        "removed:unconscious"
    ]


def test_healing_removes_unconscious_and_resets_death_track(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Healing wakes combatant")
    combat, fighter = _combatant(combat_client, campaign["id"])
    base = f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
    dropped = combat_client.post(
        f"{base}/actions/confirm",
        headers={"X-Request-ID": "unconscious-heal-drop"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 23,
            "damage_type": "force",
        },
    )
    assert dropped.status_code == 200, dropped.text

    healed = combat_client.post(
        f"{base}/actions/confirm",
        headers={"X-Request-ID": "unconscious-heal-confirm"},
        json={
            "action_type": "heal",
            "target_combatant_id": fighter["id"],
            "target_version": dropped.json()["target"]["version"],
            "amount": 5,
        },
    )
    assert healed.status_code == 200, healed.text
    assert healed.json()["target"]["hp"] == 5
    assert "昏迷" not in healed.json()["target"]["conditions"]
    assert healed.json()["action"]["result_json"]["condition_changes"] == [
        "removed:unconscious"
    ]


def test_third_death_failure_marks_character_dead(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    fighter_path = _fighter_path(campaign["id"], combat["id"], fighter["id"])
    dropped = combat_client.patch(
        fighter_path,
        headers={"If-Match": '"1"'},
        json={"hp": 0},
    )
    assert dropped.status_code == 200
    target = dropped.json()
    death_track_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        f"/combatants/{fighter['id']}/death-save"
    )
    for index, roll in enumerate((2, 3, 4), start=1):
        saved = combat_client.post(
            f"{death_track_path}/confirm",
            headers={"X-Request-ID": f"failed-save-{index}"},
            json={
                "target_version": target["version"],
                "roll": roll,
            },
        )
        assert saved.status_code == 200
        target = saved.json()["target"]

    assert saved.json()["death_save"]["pending_death_confirmation"] is False
    assert saved.json()["death_save"]["dead"] is True


def test_three_successes_stabilize_and_stop_further_death_saves(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    fighter_path = _fighter_path(campaign["id"], combat["id"], fighter["id"])
    target = combat_client.patch(
        fighter_path,
        headers={"If-Match": '"1"'},
        json={"hp": 0},
    ).json()
    death_track_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        f"/combatants/{fighter['id']}/death-save"
    )
    for index in range(3):
        saved = combat_client.post(
            f"{death_track_path}/confirm",
            headers={"X-Request-ID": f"successful-save-{index}"},
            json={"target_version": target["version"], "roll": 10},
        )
        assert saved.status_code == 200
        target = saved.json()["target"]
    assert saved.json()["death_save"]["stable"] is True
    blocked = combat_client.post(
        f"{death_track_path}/confirm",
        headers={"X-Request-ID": "save-after-stable"},
        json={"target_version": target["version"], "roll": 10},
    )
    assert blocked.status_code == 400
    healed = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "heal-stable-combatant"},
        json={
            "action_type": "heal",
            "target_combatant_id": fighter["id"],
            "target_version": target["version"],
            "amount": 3,
        },
    )
    assert healed.status_code == 200
    assert healed.json()["target"]["hp"] == 3
    reset = combat_client.get(death_track_path).json()
    assert reset["stable"] is False
    assert reset["successes"] == 0


def test_damage_at_zero_adds_failures_critical_adds_two_and_healing_resets(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        f"/actions/confirm"
    )
    dropped = combat_client.post(
        path,
        headers={"X-Request-ID": "zero-damage-drop"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 23,
            "damage_type": "force",
        },
    )
    assert dropped.status_code == 200
    assert dropped.json()["death_save"]["failures"] == 0

    damaged = combat_client.post(
        path,
        headers={"X-Request-ID": "zero-damage-normal"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": dropped.json()["target"]["version"],
            "amount": 1,
            "damage_type": "force",
        },
    )
    assert damaged.status_code == 200
    assert damaged.json()["death_save"]["failures"] == 1
    assert damaged.json()["action"]["result_json"]["death_save"]["failures_added"] == 1

    healed = combat_client.post(
        path,
        headers={"X-Request-ID": "zero-damage-heal"},
        json={
            "action_type": "heal",
            "target_combatant_id": fighter["id"],
            "target_version": damaged.json()["target"]["version"],
            "amount": 5,
        },
    )
    assert healed.status_code == 200
    assert healed.json()["target"]["hp"] == 5
    track = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        f"/combatants/{fighter['id']}/death-save"
    ).json()
    assert track["failures"] == 0
    assert track["successes"] == 0
    assert track["dead"] is False

    dropped_again = combat_client.post(
        path,
        headers={"X-Request-ID": "zero-damage-drop-again"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": healed.json()["target"]["version"],
            "amount": 5,
            "damage_type": "force",
        },
    )
    failed_again = combat_client.post(
        path,
        headers={"X-Request-ID": "zero-damage-fail-again"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": dropped_again.json()["target"]["version"],
            "amount": 1,
            "damage_type": "force",
        },
    )
    critical = combat_client.post(
        path,
        headers={"X-Request-ID": "zero-damage-critical"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": failed_again.json()["target"]["version"],
            "amount": 1,
            "damage_type": "force",
            "critical_hit": True,
        },
    )
    assert critical.status_code == 200
    assert critical.json()["death_save"]["failures"] == 3
    assert critical.json()["death_save"]["dead"] is True
    ordinary_healing = combat_client.post(
        path,
        headers={"X-Request-ID": "cannot-heal-dead"},
        json={
            "action_type": "heal",
            "target_combatant_id": fighter["id"],
            "target_version": critical.json()["target"]["version"],
            "amount": 5,
        },
    )
    assert ordinary_healing.status_code == 400


def test_massive_damage_causes_immediate_death(combat_client: TestClient) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    damaged = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "massive-damage"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 43,
            "damage_type": "force",
        },
    )
    assert damaged.status_code == 200
    assert damaged.json()["target"]["hp"] == 0
    assert damaged.json()["death_save"]["dead"] is True
    assert damaged.json()["action"]["result_json"]["death_save"]["massive_damage"] is True


def test_all_monsters_at_zero_exposes_dm_confirmed_end_suggestion(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    monster = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Goblin",
            "entity_type": "monster",
            "hp": 3,
            "max_hp": 3,
        },
    ).json()
    before = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/end-condition"
    )
    assert before.status_code == 200
    assert before.json()["can_end"] is False
    assert {
        row["display_name"] for row in before.json()["remaining_hostiles"]
    } == {"Fire Guard", "Goblin"}

    first_defeated = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "defeat-first-monster"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 23,
            "damage_type": "slashing",
        },
    )
    assert first_defeated.status_code == 200
    assert first_defeated.json()["end_condition"]["can_end"] is False
    defeated = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "defeat-second-monster"},
        json={
            "action_type": "damage",
            "target_combatant_id": monster["id"],
            "target_version": monster["version"],
            "amount": 3,
            "damage_type": "slashing",
        },
    )
    assert defeated.status_code == 200
    condition = defeated.json()["end_condition"]
    assert condition["can_end"] is True
    assert condition["suggested_resolution_type"] == "victory"
    assert condition["requires_dm_confirmation"] is True


def test_advance_turn_restores_next_combatant_action_economy(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    second = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Scout",
            "initiative": -1,
            "hp": 8,
            "max_hp": 8,
            "speed_ft": 35,
            "movement_remaining_ft": 0,
            "action_available": False,
            "bonus_action_available": False,
            "reaction_available": False,
        },
    )
    assert second.status_code == 201

    advanced = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "next-turn"},
        json={"combat_version": combat["version"]},
    )

    assert advanced.status_code == 200
    assert advanced.json()["combat"]["current_turn_index"] == 1
    assert advanced.json()["combat"]["round_number"] == 1
    assert advanced.json()["active_combatant"]["id"] == second.json()["id"]
    assert advanced.json()["active_combatant"]["movement_remaining_ft"] == 35
    assert advanced.json()["active_combatant"]["action_available"] is True
    assert advanced.json()["active_combatant"]["bonus_action_available"] is True
    assert advanced.json()["active_combatant"]["reaction_available"] is True

    repeated = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "next-turn"},
        json={"combat_version": combat["version"]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["combat"]["current_turn_index"] == 1
    assert repeated.json()["action"]["id"] == advanced.json()["action"]["id"]


def test_defeated_monster_leaves_initiative_before_next_ai_turn(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "Defeated monster turn")
    combat, fighter = _combatant(combat_client, campaign["id"])
    monster = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "已倒下的熔火术士",
            "entity_type": "monster",
            "initiative": 30,
            "hp": 1,
            "max_hp": 1,
        },
    ).json()

    defeated = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "defeated-monster-action"},
        json={
            "action_type": "damage",
            "target_combatant_id": monster["id"],
            "target_version": monster["version"],
            "amount": 1,
            "damage_type": "fire",
        },
    )

    assert defeated.status_code == 200, defeated.json()
    assert defeated.json()["target"]["hp"] == 0
    assert defeated.json()["target"]["is_active"] is False
    assert defeated.json()["action"]["result_json"]["combatant_deactivated"] is True

    advanced = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "skip-defeated-monster"},
        json={"combat_version": combat["version"]},
    )

    assert advanced.status_code == 200, advanced.json()
    assert advanced.json()["active_combatant"]["id"] == fighter["id"]
    assert advanced.json()["active_combatant"]["id"] != monster["id"]


def test_advance_turn_waits_for_pending_player_roll(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, player = _combatant(combat_client, campaign["id"])
    first_monster = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "第一只相位蜘蛛",
            "entity_type": "monster",
            "initiative": 30,
            "hp": 32,
            "max_hp": 32,
        },
    ).json()
    second_monster = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "第二只相位蜘蛛",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 32,
            "max_hp": 32,
        },
    ).json()
    pending = combat_client.post(
        (
            f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
            "/actions/player-rolls/pending"
        ),
        headers={"X-Request-ID": "first-spider-save"},
        json={
            "actor_combatant_id": first_monster["id"],
            "actor_version": first_monster["version"],
            "target_combatant_id": player["id"],
            "target_version": player["version"],
            "action_name": "毒牙",
            "resolution_type": "saving_throw",
            "dc": 11,
            "ability": "constitution",
            "damage_on_failure": 7,
            "damage_on_success": 3,
            "damage_type": "poison",
            "description": "等待玩家完成第一只怪物的豁免。",
        },
    )
    assert pending.status_code == 200, pending.json()

    blocked = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "must-wait-for-player"},
        json={"combat_version": combat["version"]},
    )
    assert blocked.status_code == 400
    assert "玩家掷骰请求未结算" in blocked.json()["message"]

    action = pending.json()["action"]
    resolved = combat_client.post(
        (
            f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
            f"/actions/player-rolls/{action['id']}/confirm"
        ),
        headers={"X-Request-ID": "resolve-first-spider-save"},
        json={"action_version": action["version"], "roll_total": 15},
    )
    assert resolved.status_code == 200, resolved.json()

    advanced = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "advance-after-player-roll"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200, advanced.json()
    assert advanced.json()["active_combatant"]["id"] == second_monster["id"]


def test_reset_combat_restores_start_state_and_clears_log(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    second = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Reset Target",
            "entity_type": "monster",
            "initiative": -1,
            "hp": 12,
            "max_hp": 12,
        },
    )
    assert second.status_code == 201
    damaged = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "reset-damage"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 8,
            "damage_type": "fire",
        },
    )
    assert damaged.status_code == 200
    moved = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], fighter["id"]),
        headers={"If-Match": f'"{damaged.json()["target"]["version"]}"'},
        json={
            "conditions": ["prone"],
            "movement_remaining_ft": 5,
            "snapshot_json": {
                **damaged.json()["target"]["snapshot_json"],
                "grid_position": {"row": 7, "col": 9},
            },
        },
    )
    assert moved.status_code == 200
    advanced = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "reset-advance"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200
    assert advanced.json()["combat"]["current_turn_index"] == 1

    reset = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/reset",
        headers={"X-Request-ID": "reset-combat"},
        json={"combat_version": advanced.json()["combat"]["version"]},
    )
    assert reset.status_code == 200, reset.json()
    body = reset.json()
    assert body["combat"]["round_number"] == 1
    assert body["combat"]["current_turn_index"] == 0
    assert body["cleared_log"] is True
    restored = next(
        item for item in body["combatants"] if item["id"] == fighter["id"]
    )
    assert restored["hp"] == 20
    assert restored["temporary_hp"] == 3
    assert restored["conditions"] == []
    assert restored["movement_remaining_ft"] == 30
    assert restored["action_available"] is True
    assert "grid_position" not in restored["snapshot_json"]
    actions = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions"
    )
    assert actions.status_code == 200
    assert actions.json()["items"] == []

    stale = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/reset",
        headers={"X-Request-ID": "reset-combat-stale"},
        json={"combat_version": advanced.json()["combat"]["version"]},
    )
    assert stale.status_code == 409

    ended = combat_client.patch(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}",
        headers={"If-Match": f'"{body["combat"]["version"]}"'},
        json={"status": "ended"},
    )
    assert ended.status_code == 200
    reset_ended = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/reset",
        headers={"X-Request-ID": "reset-ended-combat"},
        json={"combat_version": ended.json()["version"]},
    )
    assert reset_ended.status_code == 200, reset_ended.json()
    assert reset_ended.json()["combat"]["status"] == "active"
    assert reset_ended.json()["combat"]["round_number"] == 1
    assert reset_ended.json()["combat"]["current_turn_index"] == 0

    reended = combat_client.patch(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}",
        headers={"If-Match": f'"{reset_ended.json()["combat"]["version"]}"'},
        json={"status": "ended"},
    )
    assert reended.status_code == 200
    archived = combat_client.patch(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}",
        headers={"If-Match": f'"{reended.json()["version"]}"'},
        json={"status": "archived"},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    reset_archived = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/reset",
        headers={"X-Request-ID": "reset-archived-combat"},
        json={"combat_version": archived.json()["version"]},
    )
    assert reset_archived.status_code == 400
    restored_archive = combat_client.patch(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}",
        headers={"If-Match": f'"{archived.json()["version"]}"'},
        json={"status": "ended"},
    )
    assert restored_archive.status_code == 200
    assert restored_archive.json()["status"] == "ended"


def test_new_concentration_previews_and_ends_previous_effect(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    effect_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/effects"
    )
    first_payload = {
        "target_combatant_id": fighter["id"],
        "target_version": fighter["version"],
        "source_combatant_id": fighter["id"],
        "name": "祝福术",
        "effect_type": "buff",
        "requires_concentration": True,
        "duration_unit": "rounds",
        "duration_value": 10,
    }
    first = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "first-concentration"},
        json=first_payload,
    )
    assert first.status_code == 200
    assert first.json()["effect"]["status"] == "active"
    fighter = first.json()["target"]
    assert fighter["concentration"]["effect_id"] == first.json()["effect"]["id"]

    second_payload = {
        **first_payload,
        "target_version": fighter["version"],
        "name": "隐形术",
    }
    preview = combat_client.post(f"{effect_path}/preview", json=second_payload)
    assert preview.status_code == 200
    assert preview.json()["effects_to_end"][0]["id"] == first.json()["effect"]["id"]
    listed_before = combat_client.get(effect_path).json()["items"]
    assert listed_before[0]["status"] == "active"

    second = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "second-concentration"},
        json=second_payload,
    )
    assert second.status_code == 200
    assert second.json()["ended_effects"][0]["status"] == "ended"
    assert second.json()["effect"]["name"] == "隐形术"
    assert second.json()["target"]["concentration"]["effect_id"] == second.json()["effect"]["id"]

    repeated = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "second-concentration"},
        json=second_payload,
    )
    assert repeated.status_code == 200
    assert repeated.json()["effect"]["id"] == second.json()["effect"]["id"]


def test_failed_concentration_check_ends_effect_from_damage_action(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    effect_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/effects"
    )
    concentrated = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "concentrate"},
        json={
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "source_combatant_id": fighter["id"],
            "name": "隐形术",
            "effect_type": "buff",
            "requires_concentration": True,
            "duration_unit": "concentration",
        },
    )
    assert concentrated.status_code == 200
    fighter = concentrated.json()["target"]
    damaged = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "concentration-damage"},
        json={
            "action_type": "damage",
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "amount": 12,
            "damage_type": "force",
        },
    )
    assert damaged.status_code == 200
    assert damaged.json()["action"]["result_json"]["concentration_check_dc"] == 10
    concentration_prompt = damaged.json()["concentration_prompts"][0]
    assert concentration_prompt["dc"] == 10
    actions = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions"
    ).json()["items"]
    pending = next(
        item for item in actions
        if item["action_type"] == "concentration_check_prompt"
    )
    assert pending["status"] == "previewed"
    blocked_advance = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "concentration-advance-blocked"},
        json={"combat_version": combat["version"]},
    )
    assert blocked_advance.status_code == 400
    assert "专注豁免请求未结算" in blocked_advance.json()["message"]

    resolved = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}"
        "/concentration/confirm",
        headers={"X-Request-ID": "failed-concentration"},
        json={
            "combatant_id": fighter["id"],
            "target_version": damaged.json()["target"]["version"],
            "damage_action_id": damaged.json()["action"]["id"],
            "roll_total": 9,
        },
    )

    assert resolved.status_code == 200
    assert resolved.json()["success"] is False
    assert resolved.json()["dc"] == 10
    assert resolved.json()["target"]["concentration"] == {}
    assert resolved.json()["ended_effects"][0]["status"] == "ended"
    actions_after = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/actions"
    ).json()["items"]
    resolved_prompt = next(
        item for item in actions_after
        if item["action_type"] == "concentration_check_prompt"
    )
    assert resolved_prompt["status"] == "confirmed"


def test_turn_advance_prompts_expired_effect_until_dm_ends_it(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    combat, fighter = _combatant(combat_client, campaign["id"])
    second = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={"display_name": "Second", "hp": 5, "max_hp": 5, "initiative": -1},
    )
    assert second.status_code == 201
    effect_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/effects"
    )
    created = combat_client.post(
        f"{effect_path}/confirm",
        headers={"X-Request-ID": "short-effect"},
        json={
            "target_combatant_id": fighter["id"],
            "target_version": fighter["version"],
            "name": "短暂目盲",
            "effect_type": "condition",
            "duration_unit": "rounds",
            "duration_value": 0,
            "trigger_timing": "turn_end",
        },
    )
    assert created.status_code == 200

    advanced = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "advance-with-expiry"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200
    assert advanced.json()["expiration_prompts"][0]["id"] == created.json()["effect"]["id"]
    listed = combat_client.get(effect_path).json()["items"]
    assert listed[0]["status"] == "active"

    ended = combat_client.post(
        f"{effect_path}/{created.json()['effect']['id']}/end",
        headers={"X-Request-ID": "end-short-effect"},
        json={
            "target_version": created.json()["target"]["version"],
            "reason": "持续时间结束，DM确认",
        },
    )
    assert ended.status_code == 200
    assert ended.json()["effect"]["status"] == "ended"


def test_combat_settlement_preview_and_confirm_are_atomic_and_once_only(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client)
    character_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "Aria", "hp": 20, "max_hp": 20},
    )
    assert character_response.status_code == 201
    character = character_response.json()
    combat_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats",
        json={"name": "Settlement"},
    )
    assert combat_response.status_code == 201
    combat = combat_response.json()
    fighter_response = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants",
        json={
            "display_name": character["name"],
            "entity_type": "character",
            "entity_id": character["id"],
            "hp": 5,
            "max_hp": 20,
            "conditions": ["poisoned"],
        },
    )
    assert fighter_response.status_code == 201
    fighter = fighter_response.json()
    ended_combat = combat_client.patch(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}",
        headers={"If-Match": '"1"'},
        json={"status": "ended"},
    )
    assert ended_combat.status_code == 200
    settlement_path = (
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/settlement"
    )
    payload = {
        "combat_version": ended_combat.json()["version"],
        "resolution_type": "victory",
        "xp_awards": [{"character_id": character["id"], "xp": 100}],
        "currency_awards": [{"character_id": character["id"], "copper": 275}],
        "loot_awards": [
            {
                "character_id": character["id"],
                "name": "哥布林首领的银钥匙",
                "description": "一把刻有营地徽记的银钥匙。",
                "quantity": 1,
                "unit_weight_lb": 0.1,
                "price_cp": 50,
            }
        ],
        "writebacks": [{
            "combatant_id": fighter["id"],
            "character_id": character["id"],
            "write_hp": True,
            "write_conditions": True,
        }],
    }
    preview = combat_client.post(f"{settlement_path}/preview", json=payload)
    assert preview.status_code == 200
    assert preview.json()["character_changes"][0]["before"]["hp"] == 20
    assert preview.json()["character_changes"][0]["after"]["hp"] == 5
    assert preview.json()["currency_changes"][0]["before_copper"] == 0
    assert preview.json()["currency_changes"][0]["after_copper"] == 275
    assert preview.json()["currency_changes"][0]["wallet_will_be_created"] is True
    assert preview.json()["loot_changes"][0]["name"] == "哥布林首领的银钥匙"
    assert preview.json()["total_copper"] == 275
    unchanged = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    )
    assert unchanged.json()["hp"] == 20
    assert unchanged.json()["experience"] == 0

    confirmed = combat_client.post(
        f"{settlement_path}/confirm",
        headers={"X-Request-ID": "settlement-once"},
        json=payload,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["settlement"]["status"] == "confirmed"
    assert confirmed.json()["characters"][0]["hp"] == 5
    assert confirmed.json()["characters"][0]["experience"] == 100
    assert confirmed.json()["wallets"][0]["copper"] == 275
    assert confirmed.json()["loot_items"][0]["name"] == "哥布林首领的银钥匙"
    conditions = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}/conditions"
    )
    assert conditions.status_code == 200
    assert conditions.json()["items"][0]["condition_name"] == "poisoned"

    repeated = combat_client.post(
        f"{settlement_path}/confirm",
        headers={"X-Request-ID": "settlement-once"},
        json=payload,
    )
    assert repeated.status_code == 200
    assert repeated.json()["settlement"]["id"] == confirmed.json()["settlement"]["id"]
    assert repeated.json()["wallets"][0]["copper"] == 275
    assert repeated.json()["loot_items"][0]["id"] == confirmed.json()["loot_items"][0]["id"]
    after = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert after["experience"] == 100
    inventory = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}/inventory"
    )
    assert inventory.status_code == 200
    assert inventory.json()["items"][0]["name"] == "哥布林首领的银钥匙"
    assert inventory.json()["total_weight_lb"] == 0.1

    reset_settled = combat_client.post(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/reset",
        headers={"X-Request-ID": "reset-settled-combat"},
        json={"combat_version": confirmed.json()["combat"]["version"]},
    )
    assert reset_settled.status_code == 200, reset_settled.json()
    assert reset_settled.json()["combat"]["status"] == "active"
    assert reset_settled.json()["combat"]["xp_awarded"] is True
    preserved = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert preserved["experience"] == 100
    preserved_inventory = combat_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}/inventory"
    ).json()
    assert preserved_inventory["items"][0]["id"] == inventory.json()["items"][0]["id"]


def test_generic_dm_action_applies_structured_forced_movement(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "DM compiled movement")
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": "Movement room"}).json()
    grid = combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 8, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    combat = combat_client.post(
        f"{base}/combats",
        json={"name": "DM movement combat", "scene_id": scene["id"]},
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "奥术师",
            "entity_type": "character",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 4, "col": 3}},
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "雷鸣波目标",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 4, "col": 4}},
        },
    ).json()
    response = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "dm-thunderwave-compiled-move"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_cost": "action",
            "action_name": "雷鸣波",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 0,
            "damage_type": "thunder",
            "forced_movement_distance_ft": 10,
            "forced_movement_direction": "away",
        },
    )
    assert response.status_code == 200, response.text
    movement = response.json()["action"]["result_json"]["structured_effects"]["movement"]
    assert movement["moved_ft"] == 10
    assert response.json()["target"]["snapshot_json"]["grid_position"] == {"row": 4, "col": 6}


def test_monster_area_action_resolves_mixed_damage_and_vertical_geometry(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "3D mixed area")
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": "3D room"}).json()
    grid = combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 10, "height": 10, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    combat = combat_client.post(
        f"{base}/combats", json={"name": "3D mixed combat", "scene_id": scene["id"]}
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "空中施法者",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "grid_position": {"row": 5, "col": 2, "elevation_ft": 10},
                "actions": [
                    {
                        "name": "熔火柱",
                        "action_type": "spellcasting",
                        "spell_level": 3,
                    }
                ],
            },
        },
    ).json()
    low = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "地面目标",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
            "damage_resistances": ["fire"],
            "snapshot_json": {
                "grid_position": {"row": 5, "col": 5, "elevation_ft": 10},
                "actions": [
                    {
                        "name": "区域受伤反击",
                        "action_type": "reaction",
                        "reaction_event": "takes_damage",
                        "reaction_trigger": "受到伤害时",
                    }
                ],
            },
        },
    ).json()
    high = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "高空目标",
            "entity_type": "character",
            "initiative": 5,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {"grid_position": {"row": 5, "col": 5, "elevation_ft": 30}},
        },
    ).json()
    counterer = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "区域反制怪",
            "entity_type": "monster",
            "initiative": 5,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": 1, "col": 1, "elevation_ft": 0},
                "actions": [
                    {
                        "name": "反制施法",
                        "action_type": "reaction",
                        "reaction_event": "casts_spell",
                    }
                ],
            },
        },
    ).json()
    path = f"{base}/combats/{combat['id']}/monster-area-actions/confirm"
    payload = {
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "action_name": "熔火柱",
        "action_cost": "action",
        "shape": "cylinder",
        "size_ft": 20,
        "height_ft": 15,
        "anchor_row": 5,
        "anchor_col": 5,
        "anchor_height_ft": 0,
        "save_dc": 15,
        "save_ability": "dexterity",
        "damage_total": 12,
        "damage_type": "fire",
        "damage_components": [
            {"amount": 6, "damage_type": "fire"},
            {"amount": 6, "damage_type": "force"},
        ],
        "half_damage_on_save": True,
        "targets": [
            {"target_combatant_id": low["id"], "target_version": low["version"], "roll_total": 5}
        ],
        "dm_geometry_note": "DM确认圆柱底面中心和垂直高度，排除高于柱体的目标",
    }
    response = combat_client.post(path, headers={"X-Request-ID": "3d-mixed-area"}, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [
        item["damage_type"]
        for item in body["action"]["result_json"]["target_results"][0]["damage"][
            "damage_components"
        ]
    ] == ["fire", "force"]
    # fire resistance halves only the fire component; force remains full.
    assert body["targets"][0]["hp"] == 21
    actions = combat_client.get(f"{base}/combats/{combat['id']}/actions").json()["items"]
    area_windows = [
        item["result_json"]["action_window"]
        for item in actions
        if item["action_type"] == "eligible_action_window"
    ]
    assert len(area_windows) == 2
    damage_windows = [
        window for window in area_windows if window["reaction_event"] == "takes_damage"
    ]
    spell_windows = [
        window for window in area_windows if window["reaction_event"] == "casts_spell"
    ]
    assert len(damage_windows) == 1
    assert damage_windows[0]["damaged_combatant_id"] == low["id"]
    assert len(spell_windows) == 1
    assert spell_windows[0]["trigger_combatant_id"] == actor["id"]
    assert spell_windows[0]["eligible_action_names"] == ["反制施法"]
    assert counterer["id"] != actor["id"]
    assert (
        combat_client.get(
            f"{base}/combats/{combat['id']}/combatants/{high['id']}"
        ).json()["hp"]
        == 30
    )


def test_player_roll_prompt_rejects_target_outside_authoritative_3d_area(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "3D prompt gate")
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": "3D prompt room"}).json()
    grid = combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 8, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    combat = combat_client.post(
        f"{base}/combats", json={"name": "3D prompt combat", "scene_id": scene["id"]}
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "空中施法者",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 4, "col": 2, "elevation_ft": 10}},
        },
    ).json()
    inside = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "柱内目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 4, "col": 5, "elevation_ft": 10}},
        },
    ).json()
    outside = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "柱外高空目标",
            "entity_type": "character",
            "initiative": 5,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 4, "col": 5, "elevation_ft": 30}},
        },
    ).json()
    root = f"{base}/combats/{combat['id']}"
    common = {
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "action_name": "熔火柱",
        "resolution_type": "saving_throw",
        "dc": 14,
        "ability": "dexterity",
        "damage_on_failure": 8,
        "damage_type": "fire",
        "area_shape": "cylinder",
        "area_size_ft": 20,
        "area_height_ft": 15,
        "area_anchor_row": 4,
        "area_anchor_col": 5,
        "area_anchor_height_ft": 0,
    }
    accepted = combat_client.post(
        f"{root}/actions/player-rolls/pending",
        headers={"X-Request-ID": "3d-prompt-inside"},
        json={**common, "target_combatant_id": inside["id"], "target_version": inside["version"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["action"]["request_json"]["area_geometry"]["elevation_ft"] == 10
    rejected = combat_client.post(
        f"{root}/actions/player-rolls/pending",
        headers={"X-Request-ID": "3d-prompt-outside"},
        json={**common, "target_combatant_id": outside["id"], "target_version": outside["version"]},
    )
    assert rejected.status_code == 400
    assert "outside the authoritative 3-D area" in rejected.json()["message"]

    # The direct DM-confirm path must enforce the same geometry gate.  The
    # player-side map preview is not an authority and must not be able to
    # smuggle a stale/out-of-volume target into ordinary action confirmation.
    current_actor = combat_client.get(
        f"{base}/combats/{combat['id']}/combatants/{actor['id']}"
    ).json()
    direct = combat_client.post(
        f"{root}/actions/confirm",
        headers={"X-Request-ID": "3d-direct-outside"},
        json={
            "action_type": "damage",
            "actor_combatant_id": current_actor["id"],
            "actor_version": current_actor["version"],
            "action_cost": "none",
            "action_name": "熔火柱",
            "target_combatant_id": outside["id"],
            "target_version": outside["version"],
            "amount": 8,
            "damage_type": "fire",
            "area_shape": "cylinder",
            "area_size_ft": 20,
            "area_height_ft": 15,
            "area_anchor_row": 4,
            "area_anchor_col": 5,
            "area_anchor_height_ft": 0,
            "requires_explicit_elevation": True,
        },
    )
    assert direct.status_code == 400
    assert "outside the authoritative 3-D area" in direct.json()["message"]


def test_until_save_effect_has_authoritative_repeat_save_lifecycle(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "repeat save lifecycle")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(f"{base}/combats", json={"name": "repeat save"}).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "被震慑者",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    effect = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/confirm",
        headers={"X-Request-ID": "repeat-save-create"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "震慑",
            "effect_type": "condition",
            "details_json": {
                "rule_block": {"kind": "condition", "condition": "震慑"}
            },
            "duration_unit": "until_save",
            "save_dc": 15,
            "save_ability": "constitution",
        },
    )
    assert effect.status_code == 200, effect.text
    created = effect.json()
    assert "震慑" in created["target"]["conditions"]
    saved = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/{created['effect']['id']}/save/confirm",
        headers={"X-Request-ID": "repeat-save-confirm"},
        json={
            "target_combatant_id": target["id"],
            "target_version": created["target"]["version"],
            "roll_total": 15,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["success"] is True
    assert saved.json()["effect"]["status"] == "ended"
    assert "震慑" not in saved.json()["target"]["conditions"]


def test_structured_condition_sources_keep_independent_lifecycles(
    combat_client: TestClient,
) -> None:
    """Repeated save outcomes must not collapse the second condition source."""

    campaign = _campaign(combat_client, "structured condition sources")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "structured condition sources"}
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "状态施加者",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "重复中毒目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    prompt_payload = {
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "action_cost": "none",
        "action_name": "毒素脉冲",
        "resolution_type": "saving_throw",
        "dc": 12,
        "ability": "constitution",
        "conditions_on_failure": ["中毒"],
        "condition_duration": "rounds",
        "condition_duration_value": 2,
        "damage_type": "poison",
        "description": "结构化状态来源回归",
    }
    first_prompt = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending",
        headers={"X-Request-ID": "structured-condition-prompt-1"},
        json={
            **prompt_payload,
            "target_combatant_id": target["id"],
            "target_version": target["version"],
        },
    )
    assert first_prompt.status_code == 200, first_prompt.text
    first_action = first_prompt.json()["action"]
    first_result = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/{first_action['id']}/confirm",
        headers={"X-Request-ID": "structured-condition-roll-1"},
        json={
            "action_version": first_action["version"],
            "roll_total": 1,
            "dm_note": "第一个状态来源",
        },
    )
    assert first_result.status_code == 200, first_result.text
    target = combat_client.get(
        f"{base}/combats/{combat['id']}/combatants/{target['id']}"
    ).json()
    assert "中毒" in target["conditions"]
    first_effect_id = first_result.json()["resolution"]["structured_effects"]["effect_ids"][0]

    second_prompt = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending",
        headers={"X-Request-ID": "structured-condition-prompt-2"},
        json={
            **prompt_payload,
            "target_combatant_id": target["id"],
            "target_version": target["version"],
        },
    )
    assert second_prompt.status_code == 200, second_prompt.text
    second_action = second_prompt.json()["action"]
    second_result = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/{second_action['id']}/confirm",
        headers={"X-Request-ID": "structured-condition-roll-2"},
        json={
            "action_version": second_action["version"],
            "roll_total": 1,
            "dm_note": "第二个状态来源",
        },
    )
    assert second_result.status_code == 200, second_result.text
    target = combat_client.get(
        f"{base}/combats/{combat['id']}/combatants/{target['id']}"
    ).json()
    second_effect_id = second_result.json()["resolution"]["structured_effects"]["effect_ids"][0]
    actor = combat_client.get(
        f"{base}/combats/{combat['id']}/combatants/{actor['id']}"
    ).json()
    assert first_effect_id != second_effect_id
    assert "中毒" in target["conditions"]

    ended_first = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/{first_effect_id}/end",
        headers={"X-Request-ID": "structured-condition-end-1"},
        json={
            "target_version": target["version"],
            "source_version": actor["version"],
            "reason": "第一个来源结束",
        },
    )
    assert ended_first.status_code == 200, ended_first.text
    assert "中毒" in ended_first.json()["target"]["conditions"]
    target = combat_client.get(
        f"{base}/combats/{combat['id']}/combatants/{target['id']}"
    ).json()
    actor = combat_client.get(
        f"{base}/combats/{combat['id']}/combatants/{actor['id']}"
    ).json()

    ended_second = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/{second_effect_id}/end",
        headers={"X-Request-ID": "structured-condition-end-2"},
        json={
            "target_version": target["version"],
            "source_version": actor["version"],
            "reason": "第二个来源结束",
        },
    )
    assert ended_second.status_code == 200, ended_second.text
    assert "中毒" not in ended_second.json()["target"]["conditions"]


def test_mixed_monster_area_damage_applies_evasion_to_each_segment(
    combat_client: TestClient,
) -> None:
    """A mixed save-based area must not bypass Evasion on explicit segments."""

    campaign = _campaign(combat_client, "mixed area evasion")
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = combat_client.post(f"{base}/scenes", json={"name": "evasion room"}).json()
    combat_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 8, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = combat_client.post(
        f"{base}/combats",
        json={"name": "mixed area evasion", "scene_id": scene["id"]},
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "区域施法怪物",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {"grid_position": {"row": 2, "col": 2}},
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "灵巧目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "grid_position": {"row": 4, "col": 4},
                "advanced_defenses": {"evasion": True},
            },
        },
    ).json()
    response = combat_client.post(
        f"{base}/combats/{combat['id']}/monster-area-actions/confirm",
        headers={"X-Request-ID": "mixed-area-evasion"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "action_name": "分裂爆裂",
            "action_cost": "action",
            "shape": "sphere",
            "size_ft": 15,
            "anchor_row": 4,
            "anchor_col": 4,
            "save_dc": 15,
            "save_ability": "dexterity",
            "damage_total": 14,
            "damage_type": "mixed",
            "damage_components": [
                {"amount": 8, "damage_type": "fire"},
                {"amount": 6, "damage_type": "force"},
            ],
            "targets": [
                {
                    "target_combatant_id": target["id"],
                    "target_version": target["version"],
                    "roll_total": 4,
                }
            ],
            "dm_geometry_note": "DM确认球形范围和目标",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["action"]["result_json"]["target_results"][0]
    assert result["applied_defenses"] == ["evasion"]
    assert [item["adjusted_damage"] for item in result["damage"]["damage_components"]] == [4, 3]
    assert response.json()["targets"][0]["hp"] == 23


def test_repeating_mixed_damage_uses_conditional_damage_defenses(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "repeating conditional defense")
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = combat_client.post(
        f"{base}/combats", json={"name": "repeating conditional defense"}
    ).json()
    actor = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "持续效果来源",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()
    target = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "狂暴目标",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "conditions": ["狂暴"],
            "snapshot_json": {
                "conditional_damage_defenses": [
                    {
                        "id": "rage-resistance",
                        "condition": "raging",
                        "operation": "resistance",
                        "damage_types": ["fire"],
                    }
                ]
            },
        },
    ).json()
    effect = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/confirm",
        headers={"X-Request-ID": "conditional-dot-create"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "source_combatant_id": actor["id"],
            "source_version": actor["version"],
            "name": "持续分裂火焰",
            "effect_type": "damage_over_time",
            "details_json": {
                "damage_components": [
                    {"expression": "4", "damage_type": "fire"},
                    {"expression": "3", "damage_type": "force"},
                ],
                "repeat": {"timing": "turn_start"},
            },
            "duration_unit": "rounds",
            "duration_value": 3,
            "trigger_timing": "turn_start",
        },
    )
    assert effect.status_code == 200, effect.text
    advanced = combat_client.post(
        f"{base}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "conditional-dot-tick"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    tick = advanced.json()["effect_ticks"][0]["result"]
    assert [item["adjusted_damage"] for item in tick["damage_components"]] == [2, 3]
    assert tick["conditional_defenses_applied"] == ["rage-resistance:resistance:fire"]
    assert advanced.json()["active_combatant"]["id"] == target["id"]


def test_condition_restrictions_stack_and_restore_shared_baseline(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "stacked condition restrictions")
    combat, target = _combatant(combat_client, campaign["id"])
    base = f"/api/v1/campaigns/{campaign['id']}"
    source = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "状态来源",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()

    def apply_effect(request_id: str, condition: str) -> dict[str, object]:
        nonlocal target, source
        response = combat_client.post(
            f"{base}/combats/{combat['id']}/effects/confirm",
            headers={"X-Request-ID": request_id},
            json={
                "target_combatant_id": target["id"],
                "target_version": target["version"],
                "source_combatant_id": source["id"],
                "source_version": source["version"],
                "name": request_id,
                "effect_type": "condition",
                "details_json": {
                    "rule_block": {
                        "kind": "condition",
                        "condition": condition,
                        "operation": "apply",
                    }
                },
                "duration_unit": "until_removed",
            },
        )
        assert response.status_code == 200, response.text
        target = response.json()["target"]
        source = combat_client.get(
            _fighter_path(campaign["id"], combat["id"], source["id"])
        ).json()
        return response.json()["effect"]

    stunned = apply_effect("stack-stunned", "震慑")
    assert target["action_available"] is False
    assert target["bonus_action_available"] is False
    assert target["reaction_available"] is False
    paralyzed = apply_effect("stack-paralyzed", "麻痹")
    assert target["action_available"] is False
    target = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()

    ended_stunned = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/{stunned['id']}/end",
        headers={"X-Request-ID": "end-stunned"},
        json={
            "target_version": target["version"],
            "source_version": source["version"],
            "reason": "震慑结束",
        },
    )
    assert ended_stunned.status_code == 200, ended_stunned.text
    target = ended_stunned.json()["target"]
    source = ended_stunned.json()["source"]
    assert target["action_available"] is False

    ended_paralyzed = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/{paralyzed['id']}/end",
        headers={"X-Request-ID": "end-paralyzed"},
        json={
            "target_version": target["version"],
            "source_version": source["version"],
            "reason": "麻痹结束",
        },
    )
    assert ended_paralyzed.status_code == 200, ended_paralyzed.text
    target = ended_paralyzed.json()["target"]
    source = ended_paralyzed.json()["source"]
    assert target["action_available"] is True
    assert target["bonus_action_available"] is True
    assert target["reaction_available"] is True

    target = combat_client.patch(
        _fighter_path(campaign["id"], combat["id"], target["id"]),
        headers={"If-Match": f'"{target["version"]}"'},
        json={"movement_remaining_ft": 20},
    ).json()
    restrained = apply_effect("stack-restrained", "束缚")
    grappled = apply_effect("stack-grappled", "擒抱")
    assert target["speed_ft"] == 0
    assert target["movement_remaining_ft"] == 0

    ended_restrained = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/{restrained['id']}/end",
        headers={"X-Request-ID": "end-restrained"},
        json={
            "target_version": target["version"],
            "source_version": source["version"],
            "reason": "束缚结束",
        },
    )
    assert ended_restrained.status_code == 200, ended_restrained.text
    target = ended_restrained.json()["target"]
    source = ended_restrained.json()["source"]
    assert target["speed_ft"] == 0

    ended_grappled = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/{grappled['id']}/end",
        headers={"X-Request-ID": "end-grappled"},
        json={
            "target_version": target["version"],
            "source_version": source["version"],
            "reason": "擒抱结束",
        },
    )
    assert ended_grappled.status_code == 200, ended_grappled.text
    target = ended_grappled.json()["target"]
    assert target["speed_ft"] == 30
    assert target["movement_remaining_ft"] == 20


def test_condition_matrix_changes_saves_and_petrified_damage(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "condition matrix")
    combat, target = _combatant(combat_client, campaign["id"])
    base = f"/api/v1/campaigns/{campaign['id']}"
    source = combat_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "状态施加者",
            "entity_type": "monster",
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()

    restrained = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/confirm",
        headers={"X-Request-ID": "matrix-restrained"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "source_combatant_id": source["id"],
            "source_version": source["version"],
            "name": "束缚",
            "effect_type": "condition",
            "details_json": {
                "rule_block": {
                    "kind": "condition",
                    "condition": "束缚",
                    "operation": "apply",
                }
            },
            "duration_unit": "until_removed",
        },
    )
    assert restrained.status_code == 200, restrained.text
    target = restrained.json()["target"]
    pending = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending",
        headers={"X-Request-ID": "matrix-dex-save"},
        json={
            "actor_combatant_id": source["id"],
            "actor_version": source["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_name": "束缚射线",
            "resolution_type": "saving_throw",
            "dc": 10,
            "ability": "dexterity",
            "damage_on_failure": 4,
            "damage_on_success": 0,
            "damage_type": "force",
            "description": "束缚目标进行敏捷豁免。",
        },
    )
    assert pending.status_code == 200, pending.text
    prompt = pending.json()["action"]
    source = pending.json()["actor"]
    preview = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/{prompt['id']}/preview",
        json={
            "action_version": prompt["version"],
            "roll_total": 15,
            "roll_totals": [5, 15],
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["resolution"]["roll_total"] == 5
    assert (
        "restrained_disadvantage_dexterity_save"
        in preview.json()["resolution"]["applied_defenses"]
    )
    target = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()

    ended = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/{restrained.json()['effect']['id']}/end",
        headers={"X-Request-ID": "matrix-end-restrained"},
        json={
            "target_version": target["version"],
            "source_version": source["version"],
            "reason": "束缚结束",
        },
    )
    assert ended.status_code == 200, ended.text
    target = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], target["id"])
    ).json()
    source = combat_client.get(
        _fighter_path(campaign["id"], combat["id"], source["id"])
    ).json()
    petrified = combat_client.post(
        f"{base}/combats/{combat['id']}/effects/confirm",
        headers={"X-Request-ID": "matrix-petrified"},
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "source_combatant_id": source["id"],
            "source_version": source["version"],
            "name": "石化",
            "effect_type": "condition",
            "details_json": {
                "rule_block": {
                    "kind": "condition",
                    "condition": "石化",
                    "operation": "apply",
                }
            },
            "duration_unit": "until_removed",
        },
    )
    assert petrified.status_code == 200, petrified.text
    target = petrified.json()["target"]
    damaged = combat_client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "matrix-petrified-damage"},
        json={
            "action_type": "damage",
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "amount": 10,
            "damage_type": "fire",
        },
    )
    assert damaged.status_code == 200, damaged.text
    assert damaged.json()["action"]["result_json"]["modifier"] == "resistance"
    assert damaged.json()["action"]["result_json"]["adjusted_damage"] == 5
    assert damaged.json()["target"]["hp"] == target["hp"] - 2


def test_direct_condition_patch_uses_lifecycle_restrictions(
    combat_client: TestClient,
) -> None:
    campaign = _campaign(combat_client, "direct condition lifecycle")
    combat, target = _combatant(combat_client, campaign["id"])
    path = _fighter_path(campaign["id"], combat["id"], target["id"])

    applied = combat_client.patch(
        path,
        headers={"If-Match": f'"{target["version"]}"'},
        json={"conditions": ["昏迷"]},
    )
    assert applied.status_code == 200, applied.text
    target = applied.json()
    assert target["conditions"] == ["昏迷"]
    assert target["action_available"] is False
    assert target["bonus_action_available"] is False
    assert target["reaction_available"] is False

    removed = combat_client.patch(
        path,
        headers={"If-Match": f'"{target["version"]}"'},
        json={"conditions": []},
    )
    assert removed.status_code == 200, removed.text
    target = removed.json()
    assert target["action_available"] is True
    assert target["bonus_action_available"] is True
    assert target["reaction_available"] is True
