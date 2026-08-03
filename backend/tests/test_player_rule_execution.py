from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.models import Character, Event, SceneObject


def _campaign(client: TestClient, name: str) -> dict[str, Any]:
    response = client.post("/api/v1/campaigns", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _open_and_join(client: TestClient, campaign_id: str) -> None:
    opened = client.post(
        f"/api/v1/campaigns/{campaign_id}/player-room/open", json={"hours": 4}
    )
    assert opened.status_code == 200, opened.text
    joined = client.post(
        "/api/v1/player-room/join",
        json={"join_code": opened.json()["join_code"], "display_name": "规则执行玩家"},
    )
    assert joined.status_code == 201, joined.text


def _scene_object(campaign_client: TestClient, object_id: str) -> dict[str, Any]:
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        item = session.get(SceneObject, object_id)
        assert item is not None
        return {
            "state": item.state,
            "interaction": dict(item.interaction_json or {}),
            "metadata": dict(item.metadata_json or {}),
        }


def test_player_pr_spells_use_dm_confirmed_object_operations_and_structured_results(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "PR 法术执行团")
    root = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{root}/characters",
        json={
            "name": "伊莉丝",
            "class_name": "法师",
            "hp": 12,
            "max_hp": 12,
            "spells": [
                {"name": "敲击术", "range": "60尺"},
                {"name": "秘法锁", "range": "触及"},
                {"name": "光亮术", "range": "触及"},
                {"name": "黑暗术", "range": "60尺"},
                {"name": "修复术", "range": "触及"},
                {"name": "传讯术", "range": "120尺"},
                {"name": "短讯术", "range": "不限"},
                {"name": "通晓语言", "range": "自身"},
                {"name": "动物交谈", "range": "自身"},
                {"name": "预言术", "range": "自身"},
            ],
        },
    )
    assert character.status_code == 201, character.text
    character_data = character.json()
    scene = campaign_client.post(f"{root}/scenes", json={"name": "钟楼地窖"})
    assert scene.status_code == 201, scene.text
    scene_data = scene.json()
    assert campaign_client.post(
        f"{root}/scenes/{scene_data['id']}/grid",
        json={"width": 8, "height": 6, "cell_size_ft": 5, "mode": "exploration"},
    ).status_code == 201
    assert campaign_client.post(
        f"{root}/scenes/{scene_data['id']}/tokens",
        json={
            "entity_type": "character",
            "entity_id": character_data["id"],
            "label": character_data["name"],
            "row": 2,
            "col": 2,
        },
    ).status_code == 201
    door = campaign_client.post(
        f"{root}/scenes/{scene_data['id']}/objects",
        json={
            "object_type": "door",
            "label": "地窖铁门",
            "row": 2,
            "col": 3,
            "state": "closed",
            "visibility": "public",
            "interaction_json": {"locked": True},
        },
    )
    assert door.status_code == 201, door.text
    lantern = campaign_client.post(
        f"{root}/scenes/{scene_data['id']}/objects",
        json={
            "object_type": "light",
            "label": "熄灭的提灯",
            "row": 2,
            "col": 4,
            "state": "active",
            "visibility": "public",
        },
    )
    assert lantern.status_code == 201, lantern.text
    broken = campaign_client.post(
        f"{root}/scenes/{scene_data['id']}/objects",
        json={
            "object_type": "furniture",
            "label": "断裂的木箱",
            "row": 2,
            "col": 5,
            "state": "destroyed",
            "visibility": "public",
        },
    )
    assert broken.status_code == 201, broken.text

    _open_and_join(campaign_client, campaign["id"])
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character_data["id"]},
    ).status_code == 200
    assert campaign_client.post(
        f"{root}/player-room/live-state", json={"scene_id": scene_data["id"]}
    ).status_code == 200

    def plan(action_id: str, target_type: str, target_id: str | None, key: str) -> dict[str, Any]:
        response = campaign_client.post(
            "/api/v1/player-room/me/noncombat-actions/plan",
            json={
                "action_id": action_id,
                "target_type": target_type,
                "target_id": target_id,
                "idempotency_key": f"pr-spell-{key}",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    def accept(request: dict[str, Any]) -> dict[str, Any]:
        response = campaign_client.post(
            f"{root}/player-action-requests/{request['id']}/accept",
            json={"version": request["version"], "dm_note": "确认安全 PR 法术结果。"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    knock = plan("spell:0", "object", door.json()["id"], "knock-001")
    assert knock["payload_json"]["resolution"]["effect"] == "unlock_door"
    assert knock["payload_json"]["proposal"]["operation"] == "unlock_door"
    assert knock["payload_json"]["automation"]["apply_on_dm_accept"] is True
    assert _scene_object(campaign_client, door.json()["id"])["interaction"]["locked"] is True
    accepted_knock = accept(knock)
    assert accepted_knock["payload_json"]["automation"]["status"] == "applied"
    unlocked = _scene_object(campaign_client, door.json()["id"])
    assert unlocked["state"] == "closed"
    assert unlocked["interaction"]["locked"] is False
    assert unlocked["interaction"]["lock_state"] == "unlocked"

    arcane_lock = plan("spell:1", "object", door.json()["id"], "arcane-lock-001")
    accepted_arcane_lock = accept(arcane_lock)
    assert accepted_arcane_lock["payload_json"]["automation"]["result"]["locked"] is True
    relocked = _scene_object(campaign_client, door.json()["id"])
    assert relocked["interaction"]["locked"] is True
    assert relocked["interaction"]["lock_state"] == "arcane_locked"

    light = plan("spell:2", "object", lantern.json()["id"], "light-001")
    assert light["payload_json"]["proposal"]["operation"] == "illuminate_object"
    assert _scene_object(campaign_client, lantern.json()["id"])["metadata"] == {}
    accept(light)
    lit = _scene_object(campaign_client, lantern.json()["id"])
    assert lit["metadata"]["illumination"]["mode"] == "bright_light"
    assert lit["metadata"]["illumination"]["bright_radius_ft"] == 20

    darkness = plan("spell:3", "object", lantern.json()["id"], "darkness-001")
    accept(darkness)
    darkened = _scene_object(campaign_client, lantern.json()["id"])
    assert darkened["metadata"]["illumination"] == {
        "mode": "magical_darkness",
        "radius_ft": 15,
    }

    mending = plan("spell:4", "object", broken.json()["id"], "mending-001")
    accept(mending)
    repaired = _scene_object(campaign_client, broken.json()["id"])
    assert repaired["state"] == "destroyed"
    assert repaired["metadata"]["repaired"] is True

    for action_id, channel in (
        ("spell:5", "message"),
        ("spell:6", "sending"),
        ("spell:7", "comprehend_languages"),
        ("spell:8", "speak_with_animals"),
    ):
        request = plan(action_id, "self", None, f"{channel}-001")
        payload = request["payload_json"]
        assert payload["resolution"]["kind"] == "structured_communication"
        assert payload["resolution"]["channel"] == channel
        assert payload["proposal"]["result_type"] == channel
        assert payload["automation"] == {
            "status": "ready_for_dm_confirmation",
            "mode": "dm_confirmed_result",
            "operation": "record_structured_result",
            "apply_on_dm_accept": False,
            "requires_dm_confirmation": True,
        }

    divination = plan("spell:9", "self", None, "divination-001")
    assert divination["payload_json"]["automation"]["mode"] == "manual"
    assert divination["payload_json"]["automation"]["apply_on_dm_accept"] is False
    assert divination["payload_json"]["proposal"]["kind"] == "narrative"


def test_expertise_check_is_auditable_and_stale_character_rules_cannot_be_confirmed(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "非战斗检定版本团")
    root = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{root}/characters",
        json={
            "name": "洛文",
            "class_name": "游荡者",
            "level": 5,
            "hp": 24,
            "max_hp": 24,
            "ability_scores": {
                "strength": 8,
                "dexterity": 16,
                "constitution": 12,
                "intelligence": 16,
                "wisdom": 12,
                "charisma": 10,
            },
            "skills": {"调查": {"proficient": True, "expertise": True}},
        },
    ).json()
    scene = campaign_client.post(f"{root}/scenes", json={"name": "废弃档案室"}).json()
    assert campaign_client.post(
        f"{root}/scenes/{scene['id']}/grid",
        json={"width": 6, "height": 6, "cell_size_ft": 5, "mode": "exploration"},
    ).status_code == 201
    assert campaign_client.post(
        f"{root}/scenes/{scene['id']}/tokens",
        json={
            "entity_type": "character",
            "entity_id": character["id"],
            "label": character["name"],
            "row": 2,
            "col": 2,
        },
    ).status_code == 201
    _open_and_join(campaign_client, campaign["id"])
    assert campaign_client.post(
        "/api/v1/player-room/me/bind-character",
        json={"character_id": character["id"]},
    ).status_code == 200
    assert campaign_client.post(
        f"{root}/player-room/live-state", json={"scene_id": scene["id"]}
    ).status_code == 200

    def plan_and_roll(key: str) -> dict[str, Any]:
        planned = campaign_client.post(
            "/api/v1/player-room/me/noncombat-actions/plan",
            json={
                "action_id": "skill:调查",
                "target_type": "area",
                "target_id": None,
                "message": "我调查档案室里的异常痕迹。",
                "idempotency_key": key,
            },
        )
        assert planned.status_code == 201, planned.text
        resolution = planned.json()["payload_json"]["resolution"]
        assert resolution["modifier"] == 9
        assert resolution["modifier_reasons"] == ["智力调整值 +3", "专精 +6"]
        rolled = campaign_client.post(
            f"/api/v1/player-room/me/noncombat-actions/{planned.json()['id']}/roll",
            json={"version": planned.json()["version"], "raw_roll": 3},
        )
        assert rolled.status_code == 200, rolled.text
        assert rolled.json()["payload_json"]["resolution"]["total"] == 12
        assert rolled.json()["payload_json"]["resolution"]["success"] is True
        return rolled.json()

    resolved = plan_and_roll("expertise-check-current")
    accepted = campaign_client.post(
        f"{root}/player-action-requests/{resolved['id']}/accept",
        json={"version": resolved["version"], "dm_note": "确认这次调查结果。"},
    )
    assert accepted.status_code == 200, accepted.text
    confirmation = accepted.json()["payload_json"]["confirmation"]
    assert accepted.json()["status"] == "accepted"
    assert confirmation["planned_character_version"] == character["version"]
    assert confirmation["confirmed_character_version"] == character["version"]

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        events = session.scalars(
            select(Event).where(
                Event.campaign_id == campaign["id"],
                Event.event_type == "player_noncombat_action",
            )
        ).all()
        assert len(events) == 1
        assert events[0].metadata_json["resolution"]["modifier"] == 9
        assert events[0].metadata_json["resolution"]["total"] == 12

    stale_resolution = plan_and_roll("expertise-check-stale")
    with Session(engine) as session, session.begin():
        stored_character = session.get(Character, character["id"])
        assert stored_character is not None
        scores = dict(stored_character.ability_scores or {})
        scores["intelligence"] = 18
        stored_character.ability_scores = scores
        stored_character.skills = {"调查": {"proficient": True, "expertise": False}}
        stored_character.version += 1

    stale = campaign_client.post(
        f"{root}/player-action-requests/{stale_resolution['id']}/accept",
        json={"version": stale_resolution["version"], "dm_note": "角色规则已变化。"},
    )
    assert stale.status_code == 200, stale.text
    stale_payload = stale.json()["payload_json"]
    assert stale.json()["status"] == "stale"
    assert stale_payload["phase"] == "stale"
    stale_details = stale_payload["stale"]
    assert stale_details["reason"] == "character_version_changed"
    assert (
        stale_details["planned_character_version"] == stale_resolution["character_version"]
    )
    assert (
        stale_details["current_character_version"]
        == stale_resolution["character_version"] + 1
    )
    assert stale_details["detected_at"]
    replayed = campaign_client.post(
        f"{root}/player-action-requests/{stale_resolution['id']}/accept",
        json={"version": stale.json()["version"], "dm_note": "重复确认。"},
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["status"] == "stale"
    assert replayed.json()["version"] == stale.json()["version"]
    with Session(engine) as session:
        event_count = len(
            session.scalars(
                select(Event).where(
                    Event.campaign_id == campaign["id"],
                    Event.event_type == "player_noncombat_action",
                )
            ).all()
        )
        assert event_count == 1
