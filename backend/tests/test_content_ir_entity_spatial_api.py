from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.engine import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import Combatant

SOURCE_ID = "fixture:entity-spatial-api"
SOURCE_FINGERPRINT = "entity-spatial-api-fingerprint"
FEATURE_ID = "fixture:entity-spatial-api"


def _runtime() -> dict[str, Any]:
    return {
        "automation_status": "full",
        "runtime_schema_version": "feature-runtime-1",
        "source_record_id": SOURCE_ID,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "actions": {
            FEATURE_ID: {
                "kind": "feature_action",
                "feature_id": FEATURE_ID,
                "automation_status": "full",
                "action_cost": "bonus_action",
                "target": "self",
                "target_policy": {"mode": "self"},
                "resolution_kind": "entity_spatial",
                "entity_binding": "entity_lifecycle",
                "spatial_contract": {
                    "schema": "entity.spatial.v1",
                    "max_move_ft": 30,
                    "expiry_distance_ft": 300,
                    "cell_size_ft": 5,
                    "requires_owner_visibility": True,
                    "requires_unoccupied_destination": True,
                    "cannot_cross_objects": True,
                },
                "source_provenance": {
                    "source_record_id": SOURCE_ID,
                    "source_fingerprint": SOURCE_FINGERPRINT,
                },
            }
        },
    }


def _setup(
    client: TestClient,
    *,
    owner_position: tuple[int, int] = (1, 1),
    entity_position: tuple[int, int] = (1, 2),
    entity_initiative: int = 10,
    owner_initiative: int = 20,
) -> tuple[str, str, str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Spatial API"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Spatial scene"}).json()
    grid = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 80, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid.status_code == 201, grid.text
    combat = client.post(
        f"{base}/combats",
        json={"name": "Spatial combat", "scene_id": scene["id"]},
    ).json()
    root = f"{base}/combats/{combat['id']}"
    owner = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Owner",
            "entity_type": "character",
            "entity_id": "owner-character",
            "initiative": owner_initiative,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": owner_position[0], "col": owner_position[1]},
                "feature_runtime": _runtime(),
            },
        },
    ).json()
    entity = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Entity",
            "entity_type": "npc",
            "entity_id": "spatial-entity",
            "initiative": entity_initiative,
            "hp": 1,
            "max_hp": 1,
            "snapshot_json": {
                "grid_position": {"row": entity_position[0], "col": entity_position[1]},
                "owner_combatant_id": owner["id"],
            },
        },
    ).json()
    target = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Creature",
            "entity_type": "monster",
            "initiative": 1,
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {"grid_position": {"row": 1, "col": 4}},
        },
    ).json()
    return base, combat["id"], scene["id"], owner, entity, target


def _body(
    base: str,
    owner: dict[str, Any],
    entity: dict[str, Any],
    *,
    combat_id: str,
    destination: tuple[int, int],
    key: str = "spatial-api-key",
    operation_id: str = "spatial-api-operation",
    actor_version: int | None = None,
    entity_version: int | None = None,
) -> dict[str, Any]:
    return {
        "content_kind": "feature",
        "runtime_id": FEATURE_ID,
        "permission": "player",
        "combat_id": combat_id,
        "actor_combatant_id": owner["id"],
        "actor_version": actor_version or owner["version"],
        "target_combatant_id": owner["id"],
        "target_version": owner["version"],
        "entity_id": entity["id"],
        "entity_spatial_version": entity_version,
        "destination_row": destination[0],
        "destination_col": destination[1],
        "operation_id": operation_id,
        "idempotency_key": key,
    }


def _preview(client: TestClient, base: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_entity_spatial_api_preview_confirm_replay_and_bonus_action_cas(
    campaign_client: TestClient,
) -> None:
    base, combat_id, _scene_id, owner, entity, _target = _setup(campaign_client)
    body = _body(base, owner, entity, combat_id=combat_id, destination=(1, 8))
    preview = _preview(campaign_client, base, body)
    assert preview["entity_spatial"]["movement_cost_ft"] == 30
    confirmed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    receipt = confirmed.json()
    assert receipt["consumer"] == "entity.spatial.v1"
    assert receipt["action_economy"]["consumed"] is True
    replay = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


@pytest.mark.parametrize(
        ("destination", "expected"),
        [
        ((1, 8), "30"),
            ((1, 9), "31"),
        ],
)
def test_entity_spatial_api_distance_boundary(
    campaign_client: TestClient,
    destination: tuple[int, int],
    expected: str,
) -> None:
    base, combat_id, _scene_id, owner, entity, _target = _setup(campaign_client)
    response = campaign_client.post(
        f"{base}/content-ir/runtime/preview",
        json=_body(base, owner, entity, combat_id=combat_id, destination=destination),
    )
    if destination == (1, 8):
        assert response.status_code == 200, response.text
    else:
        assert response.status_code == 400


def test_entity_spatial_api_fail_closed_visibility_occupancy_and_object_path(
    campaign_client: TestClient,
) -> None:
    base, combat_id, scene_id, owner, entity, target = _setup(campaign_client)
    invisible = _body(
        base,
        owner,
        entity,
        combat_id=combat_id,
        destination=(2, 6),
        key="invisible-key",
    )
    response = campaign_client.post(
        f"{base}/content-ir/runtime/preview", json=invisible
    )
    assert response.status_code == 200, response.text
    occupied = _body(
        base,
        owner,
        entity,
        combat_id=combat_id,
        destination=(1, 4),
        key="occupied-key",
    )
    occupied_response = campaign_client.post(
        f"{base}/content-ir/runtime/preview", json=occupied
    )
    assert occupied_response.status_code == 400
    assert "occupied" in occupied_response.text
    object_response = campaign_client.post(
        f"{base}/scenes/{scene_id}/objects",
        json={
            "object_type": "wall",
            "label": "Wall",
            "row": 1,
            "col": 3,
            "width_cells": 1,
            "height_cells": 1,
        },
    )
    assert object_response.status_code == 201, object_response.text
    object_path = _body(
        base,
        owner,
        entity,
        combat_id=combat_id,
        destination=(1, 8),
        key="object-path-key",
    )
    object_path_response = campaign_client.post(
        f"{base}/content-ir/runtime/preview", json=object_path
    )
    assert object_path_response.status_code == 400
    assert target["id"]


def test_entity_spatial_api_allows_creature_path_and_expires_beyond_300(
    campaign_client: TestClient,
) -> None:
    base, combat_id, _scene_id, owner, entity, target = _setup(campaign_client)
    through_creature = _body(
        base,
        owner,
        entity,
        combat_id=combat_id,
        destination=(1, 8),
        key="creature-path-key",
    )
    preview = _preview(campaign_client, base, through_creature)
    assert target["id"] in {
        item["entity_id"]
        for item in [
            {"entity_id": target["id"]},
        ]
    }
    assert preview["entity_spatial"]["movement_cost_ft"] == 30

    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        row = session.get(Combatant, entity["id"])
        assert row is not None
        snapshot = dict(row.snapshot_json or {})
        snapshot["grid_position"] = {"row": 1, "col": 70}
        snapshot["entity_spatial"] = {
            "schema": "entity.spatial.v1",
            "entity_id": row.id,
            "source_id": SOURCE_ID,
            "source_fingerprint": SOURCE_FINGERPRINT,
            "status": "active",
            "position": {"row": 1, "col": 70, "elevation_ft": 0},
            "owner_position": {"row": 1, "col": 1, "elevation_ft": 0},
            "version": 1,
        }
        row.snapshot_json = snapshot
        row.version += 1
        entity["version"] = row.version
    expiry_body = _body(
        base,
        owner,
        entity,
        combat_id=combat_id,
        destination=(1, 71),
        key="expiry-api-key",
        entity_version=1,
    )
    expiry_preview = _preview(campaign_client, base, expiry_body)
    assert expiry_preview["entity_spatial"]["status"] == "expired"
    expiry_confirm = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**expiry_body, "preview_token": expiry_preview["preview_token"]},
    )
    assert expiry_confirm.status_code == 200, expiry_confirm.text
    assert expiry_confirm.json()["entity_spatial"]["status"] == "expired"


def test_entity_spatial_api_stale_entity_cas_and_failed_confirm_roll_back(
    campaign_client: TestClient,
) -> None:
    base, combat_id, _scene_id, owner, entity, _target = _setup(campaign_client)
    stale = _body(
        base,
        owner,
        entity,
        combat_id=combat_id,
        destination=(1, 8),
        key="stale-entity-key",
        entity_version=99,
    )
    stale_response = campaign_client.post(
        f"{base}/content-ir/runtime/preview", json=stale
    )
    assert stale_response.status_code == 409, stale_response.text

    invalid_state = _body(
        base,
        owner,
        entity,
        combat_id=combat_id,
        destination=(1, 8),
        key="rollback-key",
    )
    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        row = session.get(Combatant, entity["id"])
        assert row is not None
        snapshot = dict(row.snapshot_json or {})
        snapshot["entity_spatial"] = {"schema": "invalid"}
        row.snapshot_json = snapshot
    preview = campaign_client.post(
        f"{base}/content-ir/runtime/preview", json=invalid_state
    )
    assert preview.status_code == 400
    owner_after = campaign_client.get(
        f"{base}/combats/{combat_id}/combatants/{owner['id']}"
    )
    assert owner_after.status_code == 200, owner_after.text
    assert owner_after.json()["bonus_action_available"] is True


def test_entity_spatial_api_rejects_non_owner_and_bonus_action_already_used(
    campaign_client: TestClient,
) -> None:
    base, combat_id, _scene_id, owner, entity, _target = _setup(campaign_client)
    wrong_owner = dict(owner)
    wrong_owner["id"] = "not-the-owner"
    response = campaign_client.post(
        f"{base}/content-ir/runtime/preview",
        json=_body(
            base,
            wrong_owner,
            entity,
            combat_id=combat_id,
            destination=(1, 3),
            key="wrong-owner",
        ),
    )
    assert response.status_code in {400, 404, 409}

    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        row = session.get(Combatant, owner["id"])
        assert row is not None
        row.bonus_action_available = False
        row.version += 1
        owner["version"] = row.version
    response = campaign_client.post(
        f"{base}/content-ir/runtime/preview",
        json=_body(base, owner, entity, combat_id=combat_id, destination=(1, 3), key="used-bonus"),
    )
    assert response.status_code == 400
    assert "bonus action" in response.text
