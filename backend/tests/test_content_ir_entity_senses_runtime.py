from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

SOURCE_ID = "fixture:entity-senses-runtime"
SOURCE_FINGERPRINT = "entity-senses-runtime-fingerprint"
FEATURE_ID = "fixture:entity-senses-runtime"


def _runtime() -> dict[str, Any]:
    return {
        "automation_status": "full",
        "requires_dm_adjudication": False,
        "runtime_schema_version": "feature-runtime-1",
        "feature_name": "Fixture entity senses",
        "source_record_id": SOURCE_ID,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "entity_lifecycles": [
            {
                "resolution_kind": "entity_lifecycle",
                "entity_type": "spectral_object",
                "source_provenance": {
                    "source_record_id": SOURCE_ID,
                    "source_fingerprint": SOURCE_FINGERPRINT,
                },
                "max_entries": 1,
                "runtime_execution": {"status": "ready"},
            }
        ],
        "entity_senses": [
            {
                "resolution_kind": "entity_senses",
                "entity_binding": "entity_lifecycle",
                "senses": {"hearing": True, "darkvision_ft": 60, "light_radius_ft": 10},
                "form": {
                    "schema": "entity.form.v1",
                    "intangible": True,
                    "occupies_space": False,
                    "appearance": ["spectral dossier", "stack of writing"],
                },
                "source_provenance": {
                    "source_record_id": SOURCE_ID,
                    "source_fingerprint": SOURCE_FINGERPRINT,
                },
                "runtime_execution": {"status": "ready"},
            }
        ],
        "actions": {
            FEATURE_ID: {
                "kind": "feature_action",
                "feature_id": FEATURE_ID,
                "automation_status": "full",
                "availability": "any_time_readonly",
                "action_cost": "none",
                "target": "self",
                "target_policy": {"mode": "self"},
                "resolution_kind": "inspection",
                "information_kind": "manifest_mind_senses",
                "effects": [
                    {
                        "kind": "inspect_authorized_information",
                        "information_kind": "manifest_mind_senses",
                        "range_ft": 60,
                        "visibility": "owner",
                    }
                ],
            }
        },
    }


def _setup(
    client: TestClient,
    *,
    with_scene: bool = True,
) -> tuple[str, str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Entity senses"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={"name": "Senses owner", "class_name": "Wizard", "level": 1},
    ).json()
    runtime = _runtime()
    body = {
        "content_kind": "advancement",
        "runtime_id": FEATURE_ID,
        "permission": "dm",
        "character_id": character["id"],
        "character_version": character["version"],
        "entity_id": "spectral-object",
        "entity_lifecycle_event": "create",
        "entity_lifecycle_metadata": {"owner_character_id": character["id"]},
        "operation_id": "senses-create",
        "runtime_contract": runtime,
        "idempotency_key": "senses-create-key",
    }
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    character = client.get(f"{base}/characters/{character['id']}").json()
    enter_body = {
        **body,
        "character_version": character["version"],
        "entity_lifecycle_event": "enter",
        "entity_lifecycle_expected_version": 1,
        "operation_id": "senses-enter",
        "idempotency_key": "senses-enter-key",
    }
    enter_preview = client.post(f"{base}/content-ir/runtime/preview", json=enter_body)
    assert enter_preview.status_code == 200, enter_preview.text
    enter_confirmed = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**enter_body, "preview_token": enter_preview.json()["preview_token"]},
    )
    assert enter_confirmed.status_code == 200, enter_confirmed.text
    character = client.get(f"{base}/characters/{character['id']}").json()
    scene = (
        client.post(f"{base}/scenes", json={"name": "Senses scene"}).json()
        if with_scene
        else None
    )
    if scene is not None:
        grid = client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
        )
        assert grid.status_code == 201, grid.text
    combat = client.post(
        f"{base}/combats",
        json={"name": "Senses combat", **({"scene_id": scene["id"]} if scene else {})},
    ).json()
    root = f"{base}/combats/{combat['id']}"
    persisted_runtime = next(
        item["runtime"] for item in character["features"] if item["feature_id"] == FEATURE_ID
    )
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Owner",
            "entity_type": "character",
            "entity_id": character["id"],
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "grid_position": {"row": 1, "col": 1},
                "feature_runtime": persisted_runtime["registry"]
                | {
                    "entity_lifecycles": persisted_runtime["entity_lifecycles"],
                    "entity_senses": persisted_runtime["entity_senses"],
                },
            },
        },
    ).json()
    spectral = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Spectral object",
            "entity_type": "npc",
            "entity_id": "spectral-object",
            "hp": 1,
            "max_hp": 1,
            "initiative": 15,
            "snapshot_json": {"grid_position": {"row": 1, "col": 2}},
        },
    ).json()
    target = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Target",
            "entity_type": "monster",
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {"grid_position": {"row": 1, "col": 5}},
        },
    ).json()
    return base, combat["id"], actor, target, spectral


def _inspection_body(
    combat_id: str,
    actor: dict[str, Any],
    target: dict[str, Any],
    *,
    entity_id: str = "spectral-object",
    key: str = "senses-inspection-key",
) -> dict[str, Any]:
    return {
        "content_kind": "feature",
        "runtime_id": FEATURE_ID,
        "permission": "player",
        "combat_id": combat_id,
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "entity_id": entity_id,
        "idempotency_key": key,
    }


def test_entity_senses_real_consumer_receipt_and_replay(campaign_client: TestClient) -> None:
    base, combat_id, actor, target, spectral = _setup(campaign_client)
    body = _inspection_body(combat_id, actor, actor)
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    receipt = preview.json()["entity_senses"]
    assert receipt["channels"] == ["hearing", "vision"]
    assert receipt["distance_ft"] == 5
    assert receipt["line_of_sight"] is True
    confirmed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["production_runtime_full"] is True
    assert confirmed.json()["consumer"] == "combat_engine.feature_action.v1"
    assert confirmed.json()["entity_senses"] == receipt
    replay = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


def test_entity_senses_persists_typed_spectral_form_contract(campaign_client: TestClient) -> None:
    base, _combat_id, actor, _target, _spectral = _setup(campaign_client)
    character = campaign_client.get(f"{base}/characters/{actor['entity_id']}").json()
    feature = next(
        item for item in character["features"] if item["feature_id"] == FEATURE_ID
    )
    senses = feature["runtime"]["entity_senses"][0]
    assert senses["form"] == {
        "schema": "entity.form.v1",
        "intangible": True,
        "occupies_space": False,
        "appearance": ["spectral dossier", "stack of writing"],
    }


def test_entity_senses_fails_closed_for_inactive_unauthorized_and_missing_space(
    campaign_client: TestClient,
) -> None:
    base, combat_id, actor, target, spectral = _setup(campaign_client)
    body = _inspection_body(combat_id, actor, actor)
    character = campaign_client.get(f"{base}/characters/{actor['entity_id']}").json()
    expire_body = {
        "content_kind": "advancement",
        "runtime_id": FEATURE_ID,
        "permission": "dm",
        "character_id": character["id"],
        "character_version": character["version"],
        "entity_id": "spectral-object",
        "entity_lifecycle_event": "exit",
        "entity_lifecycle_expected_version": 2,
        "entity_lifecycle_metadata": {"owner_character_id": character["id"]},
        "operation_id": "senses-exit",
        "runtime_contract": _runtime(),
        "idempotency_key": "senses-exit-key",
    }
    expire_preview = campaign_client.post(
        f"{base}/content-ir/runtime/preview", json=expire_body
    )
    assert expire_preview.status_code == 200, expire_preview.text
    expire_confirm = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**expire_body, "preview_token": expire_preview.json()["preview_token"]},
    )
    assert expire_confirm.status_code == 200, expire_confirm.text
    character = campaign_client.get(f"{base}/characters/{actor['entity_id']}").json()
    expire_body = {
        **expire_body,
        "character_version": character["version"],
        "entity_lifecycle_event": "expire",
        "entity_lifecycle_expected_version": 3,
        "operation_id": "senses-expire",
        "idempotency_key": "senses-expire-key",
    }
    expire_preview = campaign_client.post(
        f"{base}/content-ir/runtime/preview", json=expire_body
    )
    assert expire_preview.status_code == 200, expire_preview.text
    expire_confirm = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**expire_body, "preview_token": expire_preview.json()["preview_token"]},
    )
    assert expire_confirm.status_code == 200, expire_confirm.text
    response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert response.status_code == 400
    assert "active entity lifecycle" in response.text

    unauthorized = _inspection_body(
        combat_id, actor, target, entity_id="forged-entity", key="forged-key"
    )
    response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=unauthorized)
    assert response.status_code == 400
    assert "not authorized" in response.text


def test_entity_senses_stale_actor_cas_and_out_of_range_fail_closed(
    campaign_client: TestClient,
) -> None:
    base, combat_id, actor, target, spectral = _setup(campaign_client)
    body = _inspection_body(combat_id, actor, actor)
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    bumped = campaign_client.patch(
        f"{base}/combats/{body['combat_id']}/combatants/{actor['id']}",
        headers={"If-Match": f'"{actor["version"]}"'},
        json={"display_name": "Owner bumped"},
    )
    assert bumped.status_code == 200, bumped.text
    stale = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert stale.status_code == 409, stale.text


def test_entity_senses_fails_closed_without_authoritative_scene(
    campaign_client: TestClient,
) -> None:
    base, combat_id, actor, target, spectral = _setup(campaign_client, with_scene=False)
    body = _inspection_body(combat_id, actor, actor)
    response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert response.status_code == 400, response.text
    assert "authoritative combat scene" in response.text
