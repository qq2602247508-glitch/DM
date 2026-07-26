from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.encounters import (
    AddEntityCondition,
    AddSceneEntity,
    EncounterAdjustmentDraft,
    RemoveEntity,
    ScheduleReinforcement,
    SetEntityHp,
)


@pytest.fixture
def encounter_client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'encounter.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as client:
        yield client


def _campaign(client: TestClient, name: str) -> dict[str, Any]:
    response = client.post("/api/v1/campaigns", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _scene(client: TestClient, campaign_id: str, name: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes",
        json={"name": name, "status": "active"},
    )
    assert response.status_code == 201
    return response.json()


def _monster(client: TestClient, campaign_id: str, name: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/campaigns/{campaign_id}/monsters",
        json={"name": name, "hp": 30, "max_hp": 30, "armor_class": 13},
    )
    assert response.status_code == 201
    return response.json()


def _combat_with_monster(
    client: TestClient,
    campaign_id: str,
    scene_id: str,
    monster_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    participant = client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes/{scene_id}/participants",
        json={"entity_type": "monster", "entity_id": monster_id},
    )
    assert participant.status_code == 201
    started = client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes/{scene_id}/start-combat",
        json={"name": "遭遇测试"},
    )
    assert started.status_code == 201
    combat = started.json()["combat"]
    combatants = client.get(
        f"/api/v1/campaigns/{campaign_id}/combats/{combat['id']}/combatants"
    ).json()["items"]
    assert len(combatants) == 1
    return combat, combatants[0]


def test_encounter_adjustment_accepts_all_supported_operations() -> None:
    draft = EncounterAdjustmentDraft(
        title="破坏仪式产生的后果",
        reason="玩家提前摧毁祭坛，敌方失去增援并受到削弱。",
        difficulty_shift=-1,
        operations=(
            RemoveEntity(
                entity_type="monster",
                entity_id="monster-guard",
                reason="两名守卫被提前引走。",
            ),
            AddSceneEntity(
                entity_type="npc",
                entity_id="npc-priest",
                reason="获救牧师加入战斗。",
            ),
            SetEntityHp(
                entity_type="monster",
                entity_id="monster-boss",
                hp=42,
                reason="仪式反噬造成伤害。",
            ),
            AddEntityCondition(
                entity_type="monster",
                entity_id="monster-boss",
                condition="无法召唤阴影",
                reason="召唤法阵已被破坏。",
            ),
            ScheduleReinforcement(
                entity_type="monster",
                entity_id="monster-cultist",
                round=3,
                quantity=2,
                reason="幸存者第三轮才抵达。",
            ),
        ),
    )

    assert [operation.kind for operation in draft.operations] == [
        "remove_entity",
        "add_scene_entity",
        "set_entity_hp",
        "add_entity_condition",
        "schedule_reinforcement",
    ]
    assert draft.difficulty_shift == -1


@pytest.mark.parametrize("difficulty_shift", [-2, 2])
def test_encounter_adjustment_rejects_invalid_difficulty_shift(
    difficulty_shift: int,
) -> None:
    with pytest.raises(ValidationError):
        EncounterAdjustmentDraft(
            title="非法难度",
            reason="超出允许范围。",
            difficulty_shift=difficulty_shift,
            operations=(),
        )


def test_encounter_adjustment_rejects_more_than_eight_operations() -> None:
    operation = RemoveEntity(
        entity_type="monster",
        entity_id="monster-guard",
        reason="守卫不能参战。",
    )

    with pytest.raises(ValidationError):
        EncounterAdjustmentDraft(
            title="过多操作",
            reason="单份草案必须保持可审核。",
            difficulty_shift=0,
            operations=(operation,) * 9,
        )


def test_encounter_operation_rejects_invalid_kind_and_entity_type() -> None:
    with pytest.raises(ValidationError):
        EncounterAdjustmentDraft.model_validate(
            {
                "title": "非法操作",
                "reason": "AI 不能自由执行数据库操作。",
                "difficulty_shift": 0,
                "operations": [
                    {
                        "kind": "delete_campaign",
                        "entity_type": "campaign",
                        "entity_id": "campaign-1",
                        "reason": "不允许",
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    ("operation_type", "kwargs"),
    [
        (
            SetEntityHp,
            {
                "entity_type": "monster",
                "entity_id": "monster-1",
                "hp": -1,
                "reason": "HP 不能为负。",
            },
        ),
        (
            ScheduleReinforcement,
            {
                "entity_type": "monster",
                "entity_id": "monster-1",
                "round": 0,
                "quantity": 1,
                "reason": "增援轮次至少为一。",
            },
        ),
        (
            ScheduleReinforcement,
            {
                "entity_type": "monster",
                "entity_id": "monster-1",
                "round": 2,
                "quantity": 0,
                "reason": "增援数量至少为一。",
            },
        ),
    ],
)
def test_encounter_operation_rejects_invalid_numeric_bounds(
    operation_type: type[SetEntityHp] | type[ScheduleReinforcement],
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        operation_type(**kwargs)


def test_create_list_and_idempotently_reject_encounter_adjustment(
    encounter_client: TestClient,
) -> None:
    campaign = _campaign(encounter_client, "Waterdeep")
    scene = _scene(encounter_client, campaign["id"], "Old Church")
    path = f"/api/v1/campaigns/{campaign['id']}/encounter-adjustments"

    created_response = encounter_client.post(
        path,
        json={
            "scene_id": scene["id"],
            "title": "祭坛被破坏",
            "reason": "敌人无法按计划获得增援。",
            "difficulty_shift": -1,
            "operations": [],
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["status"] == "pending"
    assert created["version"] == 1

    listed = encounter_client.get(path)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [created["id"]]

    reject_path = f"{path}/{created['id']}/reject"
    rejected = encounter_client.post(
        reject_path,
        headers={"If-Match": '"1"'},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["version"] == 2

    repeated = encounter_client.post(
        reject_path,
        headers={"If-Match": '"1"'},
    )
    assert repeated.status_code == 200
    assert repeated.json()["version"] == 2


def test_create_encounter_adjustment_rejects_cross_campaign_scene(
    encounter_client: TestClient,
) -> None:
    first = _campaign(encounter_client, "First")
    second = _campaign(encounter_client, "Second")
    foreign_scene = _scene(encounter_client, second["id"], "Foreign Scene")

    response = encounter_client.post(
        f"/api/v1/campaigns/{first['id']}/encounter-adjustments",
        json={
            "scene_id": foreign_scene["id"],
            "title": "跨战役草案",
            "reason": "必须拒绝。",
            "difficulty_shift": 0,
            "operations": [],
        },
    )

    assert response.status_code == 404


def test_apply_encounter_adjustment_changes_combatant_once(
    encounter_client: TestClient,
) -> None:
    campaign = _campaign(encounter_client, "Apply")
    scene = _scene(encounter_client, campaign["id"], "Sanctum")
    monster = _monster(encounter_client, campaign["id"], "Cult Leader")
    combat, combatant = _combat_with_monster(
        encounter_client,
        campaign["id"],
        scene["id"],
        monster["id"],
    )
    path = f"/api/v1/campaigns/{campaign['id']}/encounter-adjustments"
    proposal = encounter_client.post(
        path,
        json={
            "scene_id": scene["id"],
            "combat_id": combat["id"],
            "title": "仪式反噬",
            "reason": "首领受伤且失去召唤能力。",
            "difficulty_shift": -1,
            "operations": [
                {
                    "kind": "set_entity_hp",
                    "entity_type": "monster",
                    "entity_id": monster["id"],
                    "hp": 18,
                    "reason": "仪式反噬。",
                },
                {
                    "kind": "add_entity_condition",
                    "entity_type": "monster",
                    "entity_id": monster["id"],
                    "condition": "无法召唤阴影",
                    "reason": "法阵被毁。",
                },
            ],
        },
    ).json()

    apply_path = f"{path}/{proposal['id']}/apply"
    applied = encounter_client.post(
        apply_path,
        headers={"If-Match": '"1"', "X-Request-ID": "apply-once"},
    )
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"

    changed = encounter_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/"
        f"combatants/{combatant['id']}"
    ).json()
    assert changed["hp"] == 18
    assert changed["conditions"] == [
        {
            "name": "无法召唤阴影",
            "source": f"encounter_adjustment:{proposal['id']}",
        }
    ]

    repeated = encounter_client.post(
        apply_path,
        headers={"If-Match": '"1"', "X-Request-ID": "apply-once"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["version"] == applied.json()["version"]


def test_apply_encounter_adjustment_is_atomic_on_invalid_hp(
    encounter_client: TestClient,
) -> None:
    campaign = _campaign(encounter_client, "Atomic")
    scene = _scene(encounter_client, campaign["id"], "Crypt")
    monster = _monster(encounter_client, campaign["id"], "Guardian")
    combat, combatant = _combat_with_monster(
        encounter_client,
        campaign["id"],
        scene["id"],
        monster["id"],
    )
    path = f"/api/v1/campaigns/{campaign['id']}/encounter-adjustments"
    proposal = encounter_client.post(
        path,
        json={
            "scene_id": scene["id"],
            "combat_id": combat["id"],
            "title": "非法生命值",
            "reason": "第二项失败时第一项也不能落库。",
            "difficulty_shift": 0,
            "operations": [
                {
                    "kind": "add_entity_condition",
                    "entity_type": "monster",
                    "entity_id": monster["id"],
                    "condition": "标记",
                    "reason": "用于验证回滚。",
                },
                {
                    "kind": "set_entity_hp",
                    "entity_type": "monster",
                    "entity_id": monster["id"],
                    "hp": 999,
                    "reason": "超过最大生命。",
                },
            ],
        },
    ).json()

    failed = encounter_client.post(
        f"{path}/{proposal['id']}/apply",
        headers={"If-Match": '"1"', "X-Request-ID": "apply-rollback"},
    )
    assert failed.status_code == 400

    unchanged = encounter_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/"
        f"combatants/{combatant['id']}"
    ).json()
    assert unchanged["hp"] == 30
    assert unchanged["conditions"] == []
    listed = encounter_client.get(path).json()["items"]
    assert listed[0]["status"] == "pending"


def test_applied_scene_adjustment_is_consumed_by_first_combat(
    encounter_client: TestClient,
) -> None:
    campaign = _campaign(encounter_client, "Future")
    scene = _scene(encounter_client, campaign["id"], "Gate")
    monster = _monster(encounter_client, campaign["id"], "Gate Guard")
    participant = encounter_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/participants",
        json={"entity_type": "monster", "entity_id": monster["id"]},
    )
    assert participant.status_code == 201
    path = f"/api/v1/campaigns/{campaign['id']}/encounter-adjustments"
    proposal = encounter_client.post(
        path,
        json={
            "scene_id": scene["id"],
            "title": "提前下毒",
            "reason": "守卫在战斗开始时已受伤。",
            "difficulty_shift": -1,
            "operations": [
                {
                    "kind": "set_entity_hp",
                    "entity_type": "monster",
                    "entity_id": monster["id"],
                    "hp": 12,
                    "reason": "毒药生效。",
                }
            ],
        },
    ).json()
    applied = encounter_client.post(
        f"{path}/{proposal['id']}/apply",
        headers={"If-Match": '"1"', "X-Request-ID": "apply-future"},
    )
    assert applied.status_code == 200
    assert applied.json()["combat_id"] is None

    started = encounter_client.post(
        f"/api/v1/campaigns/{campaign['id']}/scenes/{scene['id']}/start-combat",
        json={"name": "城门战斗"},
    )
    assert started.status_code == 201
    combat = started.json()["combat"]
    combatants = encounter_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/combatants"
    ).json()["items"]
    assert combatants[0]["hp"] == 12

    consumed = encounter_client.get(path).json()["items"][0]
    assert consumed["combat_id"] == combat["id"]


def test_revert_restores_combatant_before_xp_settlement(
    encounter_client: TestClient,
) -> None:
    campaign = _campaign(encounter_client, "Revert")
    scene = _scene(encounter_client, campaign["id"], "Hall")
    monster = _monster(encounter_client, campaign["id"], "Champion")
    combat, combatant = _combat_with_monster(
        encounter_client,
        campaign["id"],
        scene["id"],
        monster["id"],
    )
    path = f"/api/v1/campaigns/{campaign['id']}/encounter-adjustments"
    proposal = encounter_client.post(
        path,
        json={
            "scene_id": scene["id"],
            "combat_id": combat["id"],
            "title": "削弱冠军",
            "reason": "玩家提前破坏了护符。",
            "difficulty_shift": -1,
            "operations": [
                {
                    "kind": "set_entity_hp",
                    "entity_type": "monster",
                    "entity_id": monster["id"],
                    "hp": 10,
                    "reason": "护符反噬。",
                },
                {
                    "kind": "add_entity_condition",
                    "entity_type": "monster",
                    "entity_id": monster["id"],
                    "condition": "护符失效",
                    "reason": "无法获得保护。",
                },
            ],
        },
    ).json()
    applied = encounter_client.post(
        f"{path}/{proposal['id']}/apply",
        headers={"If-Match": '"1"', "X-Request-ID": "apply-revert"},
    ).json()

    reverted = encounter_client.post(
        f"{path}/{proposal['id']}/revert",
        headers={"If-Match": f'"{applied["version"]}"', "X-Request-ID": "revert-once"},
    )
    assert reverted.status_code == 200
    assert reverted.json()["status"] == "reverted"

    restored = encounter_client.get(
        f"/api/v1/campaigns/{campaign['id']}/combats/{combat['id']}/"
        f"combatants/{combatant['id']}"
    ).json()
    assert restored["hp"] == 30
    assert restored["conditions"] == []

    repeated = encounter_client.post(
        f"{path}/{proposal['id']}/revert",
        headers={"If-Match": f'"{applied["version"]}"', "X-Request-ID": "revert-once"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["version"] == reverted.json()["version"]
