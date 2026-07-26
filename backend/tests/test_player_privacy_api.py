# ruff: noqa: E501, E702

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.models import NPC, Scene, SceneGrid, SceneObject


def _contains(value: object, forbidden: str) -> bool:
    if isinstance(value, dict):
        return forbidden in value or any(_contains(item, forbidden) for item in value.values())
    if isinstance(value, list):
        return any(_contains(item, forbidden) for item in value)
    return value == forbidden


def test_player_projection_is_an_explicit_privacy_boundary(campaign_client: Any) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "Private Ravenloft"}).json()
    cid = campaign["id"]
    character = campaign_client.post(
        f"/api/v1/campaigns/{cid}/characters",
        json={"name": "Ireena", "hp": 8, "max_hp": 8, "notes": "DM_SECRET_CHARACTER_NOTE"},
    ).json()
    campaign_client.post(
        f"/api/v1/campaigns/{cid}/events",
        json={"title": "Public toast", "event_type": "note", "visibility": "players"},
    )
    campaign_client.post(
        f"/api/v1/campaigns/{cid}/events",
        json={"title": "DM_SECRET_EVENT", "event_type": "note", "visibility": "dm"},
    )
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        scene = Scene(campaign_id=cid, name="Crypt", status="active", notes="DM_SECRET_SCENE")
        session.add(scene)
        session.flush()
        session.add(
            SceneGrid(
                scene_id=scene.id,
                width=2,
                height=2,
                dm_description="DM_SECRET_GRID",
                layers_json={"dm_secret": True},
            )
        )
        session.add(
            SceneObject(
                scene_id=scene.id,
                object_type="trap",
                label="DM_SECRET_TRAP",
                row=1,
                col=1,
                visibility="hidden",
            )
        )
        session.add(
            SceneObject(
                scene_id=scene.id,
                object_type="door",
                label="Door",
                row=1,
                col=2,
                visibility="public",
                metadata_json={"dm_secret": True},
            )
        )
        session.add(
            NPC(
                campaign_id=cid,
                name="DM_SECRET_NPC",
                hp=1,
                max_hp=1,
                secrets="DM_SECRET_NPC",
                known_information="DM_SECRET_KNOWLEDGE",
            )
        )
    view = campaign_client.get(f"/api/v1/player/campaigns/{cid}/view")
    assert view.status_code == 200
    payload = view.json()
    rendered = str(payload)
    for secret in (
        "DM_SECRET_CHARACTER_NOTE",
        "DM_SECRET_EVENT",
        "DM_SECRET_SCENE",
        "DM_SECRET_GRID",
        "DM_SECRET_TRAP",
        "DM_SECRET_NPC",
        "DM_SECRET_KNOWLEDGE",
    ):
        assert secret not in rendered
    assert "dm_description" not in payload["scene"]["grid"]
    assert "layers_json" not in payload["scene"]["grid"]
    assert not _contains(payload, "metadata_json")
    player_character = campaign_client.get(
        f"/api/v1/player/campaigns/{cid}/characters/{character['id']}"
    )
    assert player_character.status_code == 200
    assert "notes" not in player_character.json()


def test_player_action_is_idempotent_request_and_never_mutates_character(
    campaign_client: Any,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "Requests"}).json()
    cid = campaign["id"]
    character = campaign_client.post(
        f"/api/v1/campaigns/{cid}/characters", json={"name": "Paladin", "hp": 12, "max_hp": 12}
    ).json()
    body = {
        "character_id": character["id"],
        "character_version": character["version"],
        "player_key": "table-1",
        "action_type": "attack",
        "message": "Attack the goblin",
        "payload_json": {"target": "goblin"},
        "idempotency_key": "player-request-0001",
    }
    first = campaign_client.post(f"/api/v1/player/campaigns/{cid}/action-requests", json=body)
    second = campaign_client.post(f"/api/v1/player/campaigns/{cid}/action-requests", json=body)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "pending"
    assert (
        campaign_client.get(f"/api/v1/campaigns/{cid}/characters/{character['id']}").json()[
            "version"
        ]
        == 1
    )
    accepted = campaign_client.post(
        f"/api/v1/campaigns/{cid}/player-action-requests/{first.json()['id']}/accept",
        json={"version": 1, "dm_note": "Resolve on table"},
    )
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    assert (
        campaign_client.get(f"/api/v1/campaigns/{cid}/characters/{character['id']}").json()[
            "version"
        ]
        == 1
    )


def test_only_published_handouts_enter_player_api(campaign_client: Any) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "Handouts"}).json()
    cid = campaign["id"]
    hidden = campaign_client.post(
        f"/api/v1/campaigns/{cid}/handouts",
        json={"title": "DM plan", "body": "DM_SECRET_HANDOUT", "published": False},
    )
    shown = campaign_client.post(
        f"/api/v1/campaigns/{cid}/handouts",
        json={"title": "Letter", "body": "Meet at dawn", "published": True},
    )
    assert hidden.status_code == 201 and shown.status_code == 201
    handouts = campaign_client.get(f"/api/v1/player/campaigns/{cid}/view").json()["handouts"]
    assert [item["title"] for item in handouts] == ["Letter"]
