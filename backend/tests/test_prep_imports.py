from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.prep_draft import PrepDraft
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Clue,
    Location,
    MonsterInstance,
    OperationTransaction,
    Quest,
    Scene,
    SceneGrid,
    SceneParticipant,
    WorldItem,
)
from dnd_dm_assistant.infrastructure.database.prep_import_service import PrepImportService


def _campaign(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/v1/campaigns", json={"name": "Atomic preparation"})
    assert response.status_code == 201
    return response.json()


def _creature(name: str, *, key: str) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "armor_class": 13,
        "hp": 9,
        "max_hp": 9,
        "speed": 30,
        "ability_scores": {
            "strength": 10,
            "dexterity": 12,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 8,
        },
        "challenge_rating": "1/4",
        "actions": [{"name": "Scimitar", "attack_bonus": 3, "damage": "1d6+1"}],
    }


def _draft() -> dict[str, Any]:
    npc = _creature("Mira the Keeper", key="npc.keeper")
    npc.update({"location_key": "loc.taproom", "goal": "Keep the guests safe"})
    monster = _creature("Goblin Scout", key="monster.scout")
    return {
        "schema_version": "1.0",
        "title": "A complete atomic draft",
        "locations": [
            {
                "key": "loc.tavern",
                "name": "Copper Cup Tavern",
                "depth": 1,
                "description": "A two-storey tavern.",
            },
            {
                "key": "loc.taproom",
                "name": "Copper Cup Taproom",
                "parent_location_key": "loc.tavern",
                "depth": 2,
                "interactive_objects": [{"name": "locked cashbox"}],
            },
        ],
        "npcs": [npc],
        "monsters": [monster],
        "quests": [
            {
                "key": "quest.rats",
                "name": "Noise in the Cellar",
                "giver_npc_key": "npc.keeper",
                "xp_reward": 100,
            }
        ],
        "clues": [
            {
                "key": "clue.symbol",
                "name": "Goblin Chalk Mark",
                "quest_key": "quest.rats",
                "dm_truth": "It marks the delivery entrance.",
            }
        ],
        "items": [
            {
                "key": "item.key",
                "name": "Cellar Key",
                "location_key": "loc.taproom",
                "quantity": 1,
                "unit_weight_lb": 0.1,
                "price_cp": 20,
            }
        ],
        "scenes": [
            {
                "key": "scene.ambush",
                "name": "Taproom Ambush",
                "location_key": "loc.taproom",
                "description": "The scout dives through the kitchen hatch.",
                "grid": {
                    "width": 18,
                    "height": 12,
                    "mode": "combat",
                    "layers_json": {"cells": [{"row": 2, "col": 3, "kind": "wall"}]},
                },
                "participants": [
                    {"entity_type": "npc", "entity_key": "npc.keeper"},
                    {"entity_type": "monster", "entity_key": "monster.scout"},
                ],
            }
        ],
    }


def test_preview_confirm_imports_everything_atomically(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client)
    path = f"/api/v1/campaigns/{campaign['id']}"
    request = {"draft": _draft(), "duplicate_strategy": "error"}

    validated = campaign_client.post(f"{path}/prep-drafts/validate", json=request)
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    assert validated.json()["summary"] == {
        "locations": 2,
        "scenes": 1,
        "npcs": 1,
        "monsters": 1,
        "quests": 1,
        "clues": 1,
        "items": 1,
    }

    preview = campaign_client.post(f"{path}/prep-imports/preview", json=request)
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["valid"] is True
    assert all(operation["action"] == "create" for operation in preview_body["operations"])

    confirm_request = {
        **request,
        "preview_token": preview_body["preview_token"],
        "idempotency_key": "complete-import-001",
    }
    confirmed = campaign_client.post(f"{path}/prep-imports/confirm", json=confirm_request)
    assert confirmed.status_code == 201
    body = confirmed.json()
    assert body["idempotent_replay"] is False
    assert body["created"] == preview_body["summary"]

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        taproom = session.get(Location, body["reference_map"]["locations"]["loc.taproom"])
        tavern = session.get(Location, body["reference_map"]["locations"]["loc.tavern"])
        scene = session.get(Scene, body["reference_map"]["scenes"]["scene.ambush"])
        npc = session.get(NPC, body["reference_map"]["npcs"]["npc.keeper"])
        clue = session.get(Clue, body["reference_map"]["clues"]["clue.symbol"])
        item = session.get(WorldItem, body["reference_map"]["items"]["item.key"])
        assert taproom is not None and tavern is not None
        assert taproom.parent_location_id == tavern.id
        assert npc is not None and npc.location_id == taproom.id
        assert clue is not None
        assert clue.quest_id == body["reference_map"]["quests"]["quest.rats"]
        assert item is not None and item.location_id == taproom.id
        assert scene is not None and scene.location_id == taproom.id
        grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene.id))
        assert grid is not None and (grid.width, grid.height, grid.mode) == (18, 12, "combat")
        participants = session.scalars(
            select(SceneParticipant).where(SceneParticipant.scene_id == scene.id)
        ).all()
        assert {(row.entity_type, row.entity_id) for row in participants} == {
            ("npc", body["reference_map"]["npcs"]["npc.keeper"]),
            ("monster", body["reference_map"]["monsters"]["monster.scout"]),
        }


def test_confirm_is_idempotent_and_rejects_key_reuse_for_other_draft(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client)
    path = f"/api/v1/campaigns/{campaign['id']}"
    request = {"draft": _draft(), "duplicate_strategy": "error"}
    preview = campaign_client.post(f"{path}/prep-imports/preview", json=request).json()
    payload = {
        **request,
        "preview_token": preview["preview_token"],
        "idempotency_key": "same-key-001",
    }
    first = campaign_client.post(f"{path}/prep-imports/confirm", json=payload)
    second = campaign_client.post(f"{path}/prep-imports/confirm", json=payload)
    assert first.status_code == second.status_code == 201
    assert second.json()["idempotent_replay"] is True
    assert second.json()["import_id"] == first.json()["import_id"]

    changed = deepcopy(_draft())
    changed["title"] = "Different input"
    changed_request = {"draft": changed, "duplicate_strategy": "create"}
    changed_preview = campaign_client.post(
        f"{path}/prep-imports/preview", json=changed_request
    ).json()
    conflict = campaign_client.post(
        f"{path}/prep-imports/confirm",
        json={
            **changed_request,
            "preview_token": changed_preview["preview_token"],
            "idempotency_key": "same-key-001",
        },
    )
    assert conflict.status_code == 409
    assert "idempotency key" in conflict.json()["message"]


def test_invalid_references_and_unknown_site_fields_never_write(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client)
    path = f"/api/v1/campaigns/{campaign['id']}"
    broken = _draft()
    broken["items"][0]["location_key"] = "loc.missing"
    validation = campaign_client.post(
        f"{path}/prep-drafts/validate",
        json={"draft": broken, "duplicate_strategy": "error"},
    )
    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert any(issue["code"] == "missing_reference" for issue in validation.json()["errors"])

    unknown_site = _draft()
    unknown_site["buildings"] = [{"name": "Must not be partly imported"}]
    rejected = campaign_client.post(
        f"{path}/prep-imports/preview",
        json={"draft": unknown_site, "duplicate_strategy": "error"},
    )
    assert rejected.status_code == 422

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Location)) == 0
        assert session.scalar(select(func.count()).select_from(Scene)) == 0


def test_duplicate_reuse_remaps_references_without_duplicate_rows(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client)
    path = f"/api/v1/campaigns/{campaign['id']}"
    existing = campaign_client.post(
        f"{path}/locations",
        json={"name": "Copper Cup Tavern", "depth": 1},
    )
    assert existing.status_code == 201
    request = {"draft": _draft(), "duplicate_strategy": "reuse"}
    preview = campaign_client.post(f"{path}/prep-imports/preview", json=request).json()
    operation = next(
        item
        for item in preview["operations"]
        if item["entity_type"] == "locations" and item["key"] == "loc.tavern"
    )
    assert operation["action"] == "reuse"
    confirmed = campaign_client.post(
        f"{path}/prep-imports/confirm",
        json={
            **request,
            "preview_token": preview["preview_token"],
            "idempotency_key": "reuse-import-001",
        },
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["reference_map"]["locations"]["loc.tavern"] == existing.json()["id"]
    assert confirmed.json()["reused"]["locations"] == 1
    assert confirmed.json()["created"]["locations"] == 1


def test_service_rolls_back_prior_creates_when_late_stage_fails(
    campaign_client: TestClient,
    monkeypatch: Any,
) -> None:
    campaign = _campaign(campaign_client)
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    service = PrepImportService(engine)
    draft = PrepDraft.model_validate(_draft())
    preview = service.preview(campaign["id"], draft, "error")

    def fail_items(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("synthetic late-stage failure")

    monkeypatch.setattr(PrepImportService, "_create_items", fail_items)
    try:
        service.confirm(
            campaign["id"],
            draft,
            "error",
            preview_token=preview["preview_token"],
            idempotency_key="rollback-import-001",
        )
    except ValueError as exc:
        assert "synthetic late-stage failure" in str(exc)
    else:
        raise AssertionError("confirm should have failed")

    with Session(engine) as session:
        for model in (
            Location,
            Scene,
            NPC,
            MonsterInstance,
            Quest,
            Clue,
            WorldItem,
            OperationTransaction,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0

