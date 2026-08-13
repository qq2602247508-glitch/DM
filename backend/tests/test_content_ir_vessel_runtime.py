from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.domain.vessel_external_sound import resolve_vessel_external_sound
from dnd_dm_assistant.infrastructure.database.engine import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import (
    Event,
    OperationTransaction,
    VesselSpace,
    WorldItem,
)

SOURCE_ID = "98620543cf94e974361c6567"
SOURCE_FINGERPRINT = "e81b718b2ee8728e75cf77c2f00c33312a283a9e12d3654d9bb377a64ec745c7"
FEATURE_ID = "fixture:vessel-runtime"


def _contract() -> dict[str, Any]:
    return {
        "automation_status": "full",
        "requires_dm_adjudication": False,
        "runtime_schema_version": "feature-runtime-1",
        "feature_name": "Fixture vessel",
        "source_record_id": SOURCE_ID,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "vessel_spaces": [
            {
                "feature_id": FEATURE_ID,
                "id": "vessel-space",
                "resolution_kind": "vessel_space",
                "runtime_execution": {"status": "ready"},
                "space_contract": {
                    "schema": "vessel.space.v1",
                    "max_occupants": 1,
                    "duration_hours": 2,
                    "exit_size_cells": 1,
                },
                "appearance_options": ["oil_lamp", "urn"],
                "source_provenance": {
                    "source_record_id": SOURCE_ID,
                    "source_fingerprint": SOURCE_FINGERPRINT,
                },
            }
        ],
    }


def _external_sound_contract() -> dict[str, Any]:
    return {
        "automation_status": "full",
        "requires_dm_adjudication": False,
        "runtime_schema_version": "feature-runtime-1",
        "feature_name": "Fixture vessel external sound",
        "source_record_id": SOURCE_ID,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "vessel_external_sound": {
            "feature_id": FEATURE_ID,
            "id": "vessel-external-sound",
            "resolution_kind": "vessel_external_sound",
            "runtime_execution": {"status": "ready"},
            "sound_contract": {
                "schema": "vessel.external_sound.v1",
                "channel": "hearing",
                "source_facts_authority": "asserted_input",
                "state_mutated": False,
                "producer_bound": True,
            },
            "source_provenance": {
                "source_record_id": SOURCE_ID,
                "source_fingerprint": SOURCE_FINGERPRINT,
            },
        },
    }


def _setup(client: TestClient) -> tuple[str, dict[str, Any]]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Vessel runtime"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={"name": "Vessel fixture", "class_name": "测试", "level": 1},
    ).json()
    location = client.post(
        f"{base}/locations",
        json={"name": "Vessel location"},
    ).json()
    scene = client.post(
        f"{base}/scenes",
        json={"name": "Vessel scene", "status": "active", "location_id": location["id"]},
    ).json()
    client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 8, "height": 8, "mode": "combat"},
    )
    combat = client.post(
        f"{base}/combats",
        json={"name": "Vessel combat", "scene_id": scene["id"], "status": "active"},
    ).json()
    vessel_id = f"{FEATURE_ID}:vessel"
    actor = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Vessel owner",
            "entity_type": "character",
            "entity_id": character["id"],
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 2, "elevation_ft": 0},
            },
        },
    ).json()
    vessel = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Genie vessel",
            "entity_type": "marker",
            "entity_id": vessel_id,
            "hp": 1,
            "max_hp": 1,
            "snapshot_json": {
                "grid_position": {"row": 2, "col": 3, "elevation_ft": 0},
                "owner_character_id": character["id"],
                "owner_combatant_id": actor["id"],
            },
        },
    ).json()
    item = client.post(
        f"{base}/items",
        json={
            "name": "Vessel item",
            "owner_character_id": character["id"],
            "metadata_json": {"fixture": True},
        },
    ).json()
    character["_scene_id"] = scene["id"]
    character["_location_id"] = location["id"]
    character["_combat_id"] = combat["id"]
    character["_actor_id"] = actor["id"]
    character["_vessel_id"] = vessel["id"]
    character["_item_id"] = item["id"]
    return base, character


def _create_real_destroy_producer(
    client: TestClient,
    base: str,
    character: dict[str, Any],
    *,
    entity_id: str,
) -> str:
    current = client.get(f"{base}/characters/{character['id']}").json()
    created = client.post(
        f"{base}/characters/assets/equipment",
        json={
            "character_id": character["id"],
            "character_version": current["version"],
            "name": f"Destroy producer {entity_id}",
            "category": "gear",
            "metadata_json": {"entity_id": entity_id},
        },
    )
    assert created.status_code == 201, created.text
    equipment = created.json()
    current = client.get(f"{base}/characters/{character['id']}").json()
    request = {
        "character_id": character["id"],
        "character_version": current["version"],
        "equipment_id": equipment["id"],
        "operation": "destroy",
        "amount": 1,
    }
    preview = client.post(f"{base}/equipment/preview", json=request)
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"{base}/equipment/confirm",
        json={
            **request,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": f"real-destroy-{entity_id}",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    engine = create_database_engine(client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        producer = session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == base.rsplit("/", 1)[-1],
                OperationTransaction.idempotency_key
                == f"equipment:real-destroy-{entity_id}",
            )
        )
        assert producer is not None
        assert producer.operation_type == "equipment_destroy"
        assert producer.status == "applied"
        return producer.id


def _body(
    character: dict[str, Any],
    *,
    event: str,
    operation_id: str,
    key: str,
    expected_version: int | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "content_kind": "advancement",
        "runtime_id": FEATURE_ID,
        "permission": "dm",
        "character_id": character["id"],
        "character_version": character["version"],
        "scene_id": character["_scene_id"],
        "combat_id": character["_combat_id"],
        "entity_lifecycle_event": event,
        "entity_lifecycle_expected_version": expected_version,
        "entity_lifecycle_metadata": metadata,
        "operation_id": operation_id,
        "runtime_contract": _contract(),
        "idempotency_key": key,
    }


def _apply(
    client: TestClient,
    base: str,
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["vessel_space"]["schema"] == "vessel.space.v1"
    confirmed = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return preview_body, confirmed.json()


def test_real_content_ir_vessel_runtime_receipts_cover_lifecycle_and_long_rest(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"

    _, created = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="create",
            operation_id="vessel-create",
            key="vessel-create-key",
            expected_version=None,
            metadata={"vessel_appearance": "oil_lamp", "vessel_id": vessel_id},
        ),
    )
    assert created["operation_transaction_id"]
    character = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    state = created["vessel_space"]["state"]
    assert state["status"] == "outside"
    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        formal = session.scalar(
            select(VesselSpace).where(VesselSpace.vessel_id == vessel_id)
        )
        assert formal is not None
        assert formal.campaign_id == base.rsplit("/", 1)[-1]
        assert formal.owner_character_id == character["id"]
        assert formal.source_record_id == SOURCE_ID
        assert formal.source_fingerprint == SOURCE_FINGERPRINT
        assert formal.status == "outside"
        assert formal.version == state["version"]
        assert formal.occupants_json == []
        assert formal.items_json == []

    _, entered = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="enter",
            operation_id="vessel-enter",
            key="vessel-enter-key",
            expected_version=state["version"],
            metadata={
                "vessel_id": vessel_id,
                "vessel_subject_ids": [character["_actor_id"]],
                "vessel_item_ids": [character["_item_id"]],
                "vessel_facts": {
                    "vessel_touched": True,
                    "all_creatures_voluntary": True,
                    "all_creatures_visible": True,
                },
            },
        ),
    )
    character = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    state = entered["vessel_space"]["state"]
    assert state["status"] == "inside"
    assert state["occupants"] == [character["_actor_id"]]
    assert state["items"] == [character["_item_id"]]
    with Session(engine) as session:
        formal = session.scalar(
            select(VesselSpace).where(VesselSpace.vessel_id == vessel_id)
        )
        assert formal is not None
        assert formal.status == "inside"
        assert formal.version == state["version"]
        assert formal.occupants_json == [character["_actor_id"]]
        assert formal.items_json == [character["_item_id"]]
    item_after_enter = campaign_client.get(
        f"{base}/items?owner_character_id={character['id']}"
    ).json()["items"][0]
    assert item_after_enter["metadata_json"]["vessel_container_id"] == vessel_id

    _, exited = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="exit",
            operation_id="vessel-exit",
            key="vessel-exit-key",
            expected_version=state["version"],
            metadata={
                "vessel_id": vessel_id,
                "vessel_subject_ids": [character["_actor_id"]],
                "vessel_facts": {
                },
            },
        ),
    )
    character = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    state = exited["vessel_space"]["state"]
    assert state["status"] == "outside"
    assert state["items"] == [character["_item_id"]]
    exit_position = exited["vessel_space"]["position_receipts"][0]
    assert exit_position["destination_entity_id"] == character["_actor_id"]
    assert exit_position["after"]["version"] == exit_position["before"]["version"] + 1
    assert (
        exit_position["after"]["snapshot_json"]["grid_position"]
        == exit_position["to"]
    )
    item_after_exit = campaign_client.get(
        f"{base}/items?owner_character_id={character['id']}"
    ).json()["items"][0]
    assert item_after_exit["metadata_json"]["vessel_container_id"] == vessel_id
    assert "vessel_relocated_from" not in item_after_exit["metadata_json"]

    blocked = _body(
        character,
        event="enter",
        operation_id="vessel-enter-again",
        key="vessel-enter-again-key",
        expected_version=state["version"],
        metadata={
            "vessel_id": vessel_id,
                "vessel_subject_ids": [character["_actor_id"]],
                "vessel_facts": {
                    "vessel_touched": True,
                    "all_creatures_voluntary": True,
                    "all_creatures_visible": True,
                },
        },
    )
    blocked_response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=blocked)
    assert blocked_response.status_code == 400
    assert "available action" in blocked_response.text

    _, reset = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="long_rest",
            operation_id="vessel-long-rest",
            key="vessel-long-rest-key",
            expected_version=state["version"],
            metadata={"vessel_id": vessel_id},
        ),
    )
    assert reset["vessel_space"]["state"]["entry_used_since_long_rest"] is False

    replay_body = _body(
        character,
        event="long_rest",
        operation_id="vessel-long-rest",
        key="vessel-long-rest-key",
        expected_version=state["version"],
        metadata={"vessel_id": vessel_id},
    )
    replay_body["preview_token"] = reset["preview_token"]
    replay = campaign_client.post(f"{base}/content-ir/runtime/confirm", json=replay_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


def test_formal_vessel_cas_conflict_rolls_back_character_and_item(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"
    _, created = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="create",
            operation_id="formal-cas-create",
            key="formal-cas-create-key",
            expected_version=None,
            metadata={"vessel_id": vessel_id, "vessel_appearance": "urn"},
        ),
    )
    character = {**character, **campaign_client.get(f"{base}/characters/{character['id']}").json()}
    request = _body(
        character,
        event="enter",
        operation_id="formal-cas-enter",
        key="formal-cas-enter-key",
        expected_version=created["vessel_space"]["state"]["version"],
        metadata={
            "vessel_id": vessel_id,
            "vessel_subject_ids": [character["_actor_id"]],
            "vessel_item_ids": [character["_item_id"]],
            "vessel_facts": {
                "vessel_touched": True,
                "all_creatures_voluntary": True,
                "all_creatures_visible": True,
            },
        },
    )
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=request)
    assert preview.status_code == 200, preview.text
    with Session(create_database_engine(campaign_client.database_url)) as session:  # type: ignore[attr-defined]
        session.execute(
            update(VesselSpace)
            .where(VesselSpace.vessel_id == vessel_id)
            .values(version=VesselSpace.version + 1)
        )
        session.commit()
    confirmed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**request, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 409, confirmed.text
    with Session(create_database_engine(campaign_client.database_url)) as session:  # type: ignore[attr-defined]
        formal = session.scalar(select(VesselSpace).where(VesselSpace.vessel_id == vessel_id))
        assert formal is not None
        assert formal.status == "outside"
        item = session.get(WorldItem, character["_item_id"])
        assert item is not None
        assert "vessel_container_id" not in (item.metadata_json or {})


def test_new_service_instance_recovers_vessel_state_from_formal_row(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"
    _, created = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="create",
            operation_id="recovery-create",
            key="recovery-create-key",
            expected_version=None,
            metadata={"vessel_id": vessel_id, "vessel_appearance": "urn"},
        ),
    )
    current = campaign_client.get(f"{base}/characters/{character['id']}").json()
    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    # Deliberately corrupt only the legacy feature snapshot. The formal row is
    # the authoritative source for a fresh runtime service.
    from dnd_dm_assistant.infrastructure.database.models import Character

    with Session(engine) as session, session.begin():
        persisted = session.get(Character, character["id"])
        assert persisted is not None
        features = list(persisted.features or [])
        for feature in features:
            if isinstance(feature, dict) and feature.get("feature_id") == FEATURE_ID:
                runtime = dict(feature.get("runtime") or {})
                records = list(runtime.get("vessel_spaces") or [])
                for record in records:
                    if isinstance(record, dict) and record.get("vessel_id") == vessel_id:
                        record["state"] = {
                            **dict(record.get("state") or {}),
                            "status": "inside",
                            "occupants": ["stale-feature-only"],
                            "version": 999,
                        }
                runtime["vessel_spaces"] = records
                feature["runtime"] = runtime
        persisted.features = features
        persisted.version += 1
        current["version"] = persisted.version

    request = _body(
        {**character, **current},
        event="enter",
        operation_id="recovery-enter",
        key="recovery-enter-key",
        expected_version=created["vessel_space"]["state"]["version"],
        metadata={
            "vessel_id": vessel_id,
            "vessel_subject_ids": [character["_actor_id"]],
            "vessel_facts": {
                "vessel_touched": True,
                "all_creatures_voluntary": True,
                "all_creatures_visible": True,
            },
        },
    )
    preview = ContentIRRuntimeService(engine).preview(
        base.rsplit("/", 1)[-1],
        request,
    )
    assert preview["vessel_space"]["state"]["version"] == 2
    assert preview["vessel_space"]["state"]["status"] == "inside"
    assert preview["vessel_space"]["state"]["occupants"] == [character["_actor_id"]]


def test_vessel_runtime_rejects_forged_authority_and_owner_mismatch(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"
    forged = _body(
        character,
        event="create",
        operation_id="vessel-forged-create",
        key="vessel-forged-create-key",
        expected_version=None,
        metadata={
            "vessel_id": vessel_id,
            "vessel_appearance": "urn",
            "vessel_facts": {"source_owner": True},
        },
    )
    response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=forged)
    assert response.status_code == 400
    assert "caller-supplied authority booleans" in response.text

    mismatched = _body(
        character,
        event="create",
        operation_id="vessel-owner-mismatch",
        key="vessel-owner-mismatch-key",
        expected_version=None,
        metadata={"vessel_id": vessel_id, "vessel_appearance": "urn"},
    )
    mismatched["entity_lifecycle_metadata"]["vessel_id"] = "not-the-bound-vessel"
    response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=mismatched)
    assert response.status_code == 404
    assert "vessel entity binding" in response.text


def test_vessel_external_sound_rejects_terminated_state() -> None:
    state = {
        "status": "destroyed",
        "owner_character_id": "owner",
        "occupants": ["owner-combatant"],
    }
    try:
        resolve_vessel_external_sound(
            state,
            vessel_id="vessel",
            owner_character_id="owner",
            inside_occupant_id="owner-combatant",
            scene_id="scene",
            combat_id="combat",
            vessel_entity_id="vessel-entity",
            channel="hearing",
        )
    except ValueError as exc:
        assert "active inside vessel" in str(exc)
    else:
        raise AssertionError("terminated vessel must fail closed")


def test_vessel_external_sound_active_owner_is_blocked_without_sound_producer() -> None:
    receipt = resolve_vessel_external_sound(
        {
            "status": "inside",
            "owner_character_id": "owner",
            "occupants": ["owner-combatant"],
        },
        vessel_id="vessel",
        owner_character_id="owner",
        inside_occupant_id="owner-combatant",
        scene_id="scene",
        combat_id="combat",
        vessel_entity_id="vessel-entity",
        channel="hearing",
    ).as_dict()
    assert receipt["schema"] == "vessel.external_sound.v1"
    assert receipt["status"] == "blocked"
    assert receipt["blocked_reason"] == (
        "no authoritative sound event producer or event_id receipt"
    )
    assert receipt["channel"] == "hearing"
    assert receipt["sound_events"] == []
    assert receipt["state_mutated"] is False


def test_vessel_external_sound_rejects_outsider_and_non_hearing_channel() -> None:
    state = {
        "status": "inside",
        "owner_character_id": "owner",
        "occupants": ["owner-combatant"],
    }
    try:
        resolve_vessel_external_sound(
            state,
            vessel_id="vessel",
            owner_character_id="other-owner",
            inside_occupant_id="outsider-combatant",
            scene_id="scene",
            combat_id="combat",
            vessel_entity_id="vessel-entity",
            channel="hearing",
        )
    except ValueError as exc:
        assert "occupant is not inside" in str(exc)
    else:
        raise AssertionError("outsider must fail closed")
    try:
        resolve_vessel_external_sound(
            state,
            vessel_id="vessel",
            owner_character_id="owner",
            inside_occupant_id="owner-combatant",
            scene_id="scene",
            combat_id="combat",
            vessel_entity_id="vessel-entity",
            channel="vision",
        )
    except ValueError as exc:
        assert "hearing channel only" in str(exc)
    else:
        raise AssertionError("vision must fail closed")


def test_vessel_external_sound_real_event_e2e_resolves_and_replays(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"
    _, created = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="create",
            operation_id="sound-e2e-create",
            key="sound-e2e-create-key",
            expected_version=None,
            metadata={"vessel_id": vessel_id, "vessel_appearance": "urn"},
        ),
    )
    character = {**character, **campaign_client.get(f"{base}/characters/{character['id']}").json()}
    _, entered = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="enter",
            operation_id="sound-e2e-enter",
            key="sound-e2e-enter-key",
            expected_version=created["vessel_space"]["state"]["version"],
            metadata={
                "vessel_id": vessel_id,
                "vessel_subject_ids": [character["_actor_id"]],
                "vessel_facts": {
                    "vessel_touched": True,
                    "all_creatures_voluntary": True,
                    "all_creatures_visible": True,
                },
            },
        ),
    )
    character = {**character, **campaign_client.get(f"{base}/characters/{character['id']}").json()}
    event_payload = {
        "title": "A bell rings outside",
        "description": "A real persisted sound event.",
        "scene_id": character["_scene_id"],
        "combat_id": character["_combat_id"],
        "location_id": character["_location_id"],
        "visibility": "players",
        "source_producer": "test.real_event_producer",
        "source_record_id": SOURCE_ID,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "source_facts": {"kind": "bell", "authoritative": True},
        "idempotency_key": "real-audible-sound-e2e",
    }
    event_response = campaign_client.post(
        f"{base}/events/audible-sound",
        json=event_payload,
    )
    assert event_response.status_code == 201, event_response.text
    event = event_response.json()
    assert event["metadata_json"]["producer_operation_id"]
    identical_replay = campaign_client.post(
        f"{base}/events/audible-sound",
        json=event_payload,
    )
    assert identical_replay.status_code == 201, identical_replay.text
    assert identical_replay.json()["id"] == event["id"]
    conflicting_replay = campaign_client.post(
        f"{base}/events/audible-sound",
        json={**event_payload, "title": "A forged bell"},
    )
    assert conflicting_replay.status_code == 400
    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 1
        assert (
            session.scalar(
                select(func.count()).select_from(OperationTransaction).where(
                    OperationTransaction.idempotency_key
                    == "event-audible-sound:real-audible-sound-e2e"
                )
            )
            == 1
        )
    body = {
        "content_kind": "advancement",
        "runtime_id": FEATURE_ID,
        "permission": "player",
        "character_id": character["id"],
        "character_version": character["version"],
        "scene_id": character["_scene_id"],
        "combat_id": character["_combat_id"],
        "event_id": event["id"],
        "runtime_contract": _external_sound_contract(),
        "entity_lifecycle_metadata": {"vessel_id": vessel_id},
        "idempotency_key": "sound-e2e-read-key",
    }
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    receipt = preview.json()["vessel_external_sound"]
    assert receipt["status"] == "resolved"
    assert receipt["event_id"] == event["id"]
    assert receipt["source_producer"] == "test.real_event_producer"
    assert receipt["channel"] == "hearing"
    assert receipt["sound_events"] == [{"event_id": event["id"]}]
    assert receipt["state_mutated"] is False
    confirmed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    output = confirmed.json()
    assert output["consumer"] == "vessel.external_sound.v1"
    assert output["vessel_external_sound"]["status"] == "resolved"
    assert output["state_mutated"] is False
    replay = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True

    note = campaign_client.post(
        f"{base}/events",
        json={
            "title": "Ordinary note",
            "event_type": "note",
            "visibility": "players",
            "metadata_json": {
                "scene_id": character["_scene_id"],
                "combat_id": character["_combat_id"],
            },
        },
    )
    assert note.status_code == 201, note.text
    non_audible = campaign_client.post(
        f"{base}/content-ir/runtime/preview",
        json={**body, "event_id": note.json()["id"], "idempotency_key": "sound-note-key"},
    )
    assert non_audible.status_code == 400
    assert "not audible_sound" in non_audible.text

    wrong_combat = campaign_client.post(
        f"{base}/content-ir/runtime/preview",
        json={**body, "combat_id": "wrong-combat-id", "idempotency_key": "sound-combat-key"},
    )
    assert wrong_combat.status_code == 404

    other_location = campaign_client.post(
        f"{base}/locations",
        json={"name": "Other sound location"},
    )
    assert other_location.status_code == 201, other_location.text
    wrong_location_event = campaign_client.post(
        f"{base}/events",
        json={
            "title": "Wrong location sound",
            "event_type": "audible_sound",
            "location_id": other_location.json()["id"],
            "visibility": "players",
            "metadata_json": {
                "scene_id": character["_scene_id"],
                "combat_id": character["_combat_id"],
                "source_producer": "test.real_event_producer",
                "source_record_id": SOURCE_ID,
                "source_fingerprint": SOURCE_FINGERPRINT,
                "source_facts": {"kind": "bell", "authoritative": True},
            },
        },
    )
    assert wrong_location_event.status_code == 422, wrong_location_event.text

    wrong_location_producer = campaign_client.post(
        f"{base}/events/audible-sound",
        json={
            "title": "Wrong location sound",
            "scene_id": character["_scene_id"],
            "combat_id": character["_combat_id"],
            "location_id": other_location.json()["id"],
            "visibility": "players",
            "source_producer": "test.real_event_producer",
            "source_record_id": SOURCE_ID,
            "source_fingerprint": SOURCE_FINGERPRINT,
            "source_facts": {"kind": "bell", "authoritative": True},
            "idempotency_key": "sound-location-key",
        },
    )
    assert wrong_location_producer.status_code == 400
    assert "binding" in wrong_location_producer.text


def test_vessel_external_sound_direct_db_tampering_fails_closed(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"
    _, created = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="create",
            operation_id="tamper-create",
            key="tamper-create-key",
            expected_version=None,
            metadata={"vessel_id": vessel_id, "vessel_appearance": "urn"},
        ),
    )
    character = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    _apply(
        campaign_client,
        base,
        _body(
            character,
            event="enter",
            operation_id="tamper-enter",
            key="tamper-enter-key",
            expected_version=created["vessel_space"]["state"]["version"],
            metadata={
                "vessel_id": vessel_id,
                "vessel_subject_ids": [character["_actor_id"]],
                "vessel_facts": {
                    "vessel_touched": True,
                    "all_creatures_voluntary": True,
                    "all_creatures_visible": True,
                },
            },
        ),
    )
    character = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    event_response = campaign_client.post(
        f"{base}/events/audible-sound",
        json={
            "title": "Tamper target",
            "scene_id": character["_scene_id"],
            "combat_id": character["_combat_id"],
            "location_id": character["_location_id"],
            "visibility": "players",
            "source_producer": "test.tamper_producer",
            "source_record_id": SOURCE_ID,
            "source_fingerprint": SOURCE_FINGERPRINT,
            "source_facts": {"kind": "bell"},
            "idempotency_key": "tamper-sound-key",
        },
    )
    assert event_response.status_code == 201, event_response.text
    event = event_response.json()
    operation_id = event["metadata_json"]["producer_operation_id"]
    body = {
        "content_kind": "advancement",
        "runtime_id": FEATURE_ID,
        "permission": "player",
        "character_id": character["id"],
        "character_version": character["version"],
        "scene_id": character["_scene_id"],
        "combat_id": character["_combat_id"],
        "event_id": event["id"],
        "runtime_contract": _external_sound_contract(),
        "entity_lifecycle_metadata": {"vessel_id": vessel_id},
        "idempotency_key": "tamper-preview-key",
    }
    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]

    with Session(engine) as session:
        session.execute(
            update(OperationTransaction)
            .where(OperationTransaction.id == operation_id)
            .values(status="pending")
        )
        session.commit()
    not_applied = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert not_applied.status_code in {404, 409}
    assert "resolved" not in not_applied.text

    with Session(engine) as session:
        session.execute(
            update(OperationTransaction)
            .where(OperationTransaction.id == operation_id)
            .values(status="applied", operation_type="forged_operation")
        )
        session.commit()
    wrong_type = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert wrong_type.status_code == 400
    assert "operation type" in wrong_type.text

    with Session(engine) as session:
        operation = session.get(OperationTransaction, operation_id)
        assert operation is not None
        tampered_after = dict(operation.after_snapshot or {})
        tampered_after["source_facts"] = {"kind": "forged"}
        session.execute(
            update(OperationTransaction)
            .where(OperationTransaction.id == operation_id)
            .values(operation_type="event_audible_sound", after_snapshot=tampered_after)
        )
        session.commit()
    binding_mismatch = campaign_client.post(
        f"{base}/content-ir/runtime/preview",
        json={**body, "idempotency_key": "tamper-binding-key"},
    )
    assert binding_mismatch.status_code == 400
    assert "binding" in binding_mismatch.text


def test_vessel_external_sound_event_validation_fails_closed(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    common = {
        "title": "Invalid sound",
        "event_type": "audible_sound",
        "visibility": "players",
        "metadata_json": {
            "scene_id": character["_scene_id"],
            "combat_id": character["_combat_id"],
            "source_producer": "test.producer",
            "source_record_id": SOURCE_ID,
            "source_fingerprint": SOURCE_FINGERPRINT,
            "source_facts": {"authoritative": True},
        },
    }
    missing_source = {**common, "metadata_json": {**common["metadata_json"], "source_facts": {}}}
    assert campaign_client.post(f"{base}/events", json=missing_source).status_code == 422
    dm_visible = {**common, "visibility": "dm"}
    assert campaign_client.post(f"{base}/events", json=dm_visible).status_code == 422
    caller_payload = {
        **common,
        "metadata_json": {**common["metadata_json"], "sound_events": [{"fake": True}]},
    }
    assert campaign_client.post(f"{base}/events", json=caller_payload).status_code == 422


def test_vessel_external_sound_patch_cannot_mutate_producer_provenance(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    event = campaign_client.post(
        f"{base}/events/audible-sound",
        json={
            "title": "Patch-protected sound",
            "scene_id": character["_scene_id"],
            "combat_id": character["_combat_id"],
            "location_id": character["_location_id"],
            "visibility": "players",
            "source_producer": "test.real_event_producer",
            "source_record_id": SOURCE_ID,
            "source_fingerprint": SOURCE_FINGERPRINT,
            "source_facts": {"kind": "bell"},
            "idempotency_key": "patch-protected-sound",
        },
    )
    assert event.status_code == 201, event.text
    version = event.json()["version"]
    response = campaign_client.patch(
        f"{base}/events/{event.json()['id']}",
        headers={"If-Match": str(version)},
        json={
            "metadata_json": {
                **event.json()["metadata_json"],
                "source_facts": {"kind": "forged"},
            },
            "version": version,
        },
    )
    assert response.status_code == 400
    assert "provenance" in response.text


def test_vessel_external_sound_rejects_non_audible_event_and_wrong_binding(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    common_metadata = {
        "scene_id": character["_scene_id"],
        "combat_id": character["_combat_id"],
        "source_producer": "test.real_event_producer",
        "source_record_id": SOURCE_ID,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "source_facts": {"kind": "bell", "authoritative": True},
    }
    note = campaign_client.post(
        f"{base}/events",
        json={
            "title": "Not a sound",
            "event_type": "note",
            "visibility": "players",
            "metadata_json": common_metadata,
        },
    )
    assert note.status_code == 201, note.text
    other_location = campaign_client.post(
        f"{base}/locations",
        json={"name": "Other location"},
    )
    assert other_location.status_code == 201, other_location.text
    forged = campaign_client.post(
        f"{base}/events",
        json={
            "title": "Audible event",
            "event_type": "audible_sound",
            "location_id": other_location.json()["id"],
            "visibility": "players",
            "metadata_json": common_metadata,
        },
    )
    assert forged.status_code == 422, forged.text
    # The runtime binding is exercised after vessel entry in the success test;
    # these producer-side fixtures verify that non-audible events remain ordinary
    # notes and that a location mismatch is representable but not trusted.
    assert note.json()["event_type"] == "note"


def test_vessel_runtime_requires_authoritative_scene_and_combat_binding(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    body = _body(
        character,
        event="create",
        operation_id="vessel-no-binding",
        key="vessel-no-binding-key",
        expected_version=None,
        metadata={
            "vessel_id": f"{FEATURE_ID}:vessel",
            "vessel_appearance": "ring",
        },
    )
    body.pop("scene_id")
    body.pop("combat_id")
    response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert response.status_code == 400
    assert "scene_id and combat_id" in response.text


def test_destroy_relocates_all_items_from_real_equipment_producer(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"
    second = campaign_client.post(
        f"{base}/items",
        json={
            "name": "Second vessel item",
            "owner_character_id": character["id"],
            "metadata_json": {"fixture": True},
        },
    )
    assert second.status_code == 201, second.text
    _, created = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="create",
            operation_id="destroy-create",
            key="destroy-create-key",
            expected_version=None,
            metadata={"vessel_id": vessel_id, "vessel_appearance": "urn"},
        ),
    )
    character = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    state = created["vessel_space"]["state"]
    _, entered = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="enter",
            operation_id="destroy-enter",
            key="destroy-enter-key",
            expected_version=state["version"],
            metadata={
                "vessel_id": vessel_id,
                "vessel_subject_ids": [character["_actor_id"]],
                "vessel_item_ids": [character["_item_id"], second.json()["id"]],
                "vessel_facts": {
                    "vessel_touched": True,
                    "all_creatures_voluntary": True,
                    "all_creatures_visible": True,
                },
            },
        ),
    )
    character = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    producer_id = _create_real_destroy_producer(
        campaign_client,
        base,
        character,
        entity_id=vessel_id,
    )
    character = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    destroy_body = _body(
        character,
        event="destroy",
        operation_id="destroy-vessel",
        key="destroy-vessel-key",
        expected_version=entered["vessel_space"]["state"]["version"],
        metadata={
            "vessel_id": vessel_id,
            "producer_operation_id": producer_id,
        },
    )
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=destroy_body)
    assert preview.status_code == 200, preview.text
    vessel_preview = preview.json()["vessel_space"]
    assert vessel_preview["producer_receipt"]["operation_type"] == "equipment_destroy"
    receipts = vessel_preview["item_receipts"]
    assert len(receipts) == 2
    destinations = [receipt["position_receipt"]["to"] for receipt in receipts]
    assert len({(item["row"], item["col"]) for item in destinations}) == 2
    assert all(
        receipt["after"]["version"] == receipt["before"]["version"] + 1
        for receipt in receipts
    )
    confirmed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**destroy_body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["vessel_space"]["state"]["status"] == "destroyed"
    items = campaign_client.get(f"{base}/items?owner_character_id={character['id']}").json()[
        "items"
    ]
    relocated_ids = {character["_item_id"], second.json()["id"]}
    relocated = {
        item["id"]: item for item in items if item["id"] in relocated_ids
    }
    assert all("vessel_container_id" not in item["metadata_json"] for item in relocated.values())
    assert all(
        item["metadata_json"]["vessel_relocated_from"] == vessel_id
        for item in relocated.values()
    )

    replay = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**destroy_body, "preview_token": preview.json()["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


def test_destroy_requires_matching_real_producer_and_missing_producer_fails_closed(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"
    _, created = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="create",
            operation_id="destroy-negative-create",
            key="destroy-negative-create-key",
            expected_version=None,
            metadata={"vessel_id": vessel_id, "vessel_appearance": "urn"},
        ),
    )
    current = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    missing = _body(
        current,
        event="destroy",
        operation_id="destroy-missing-producer",
        key="destroy-missing-producer-key",
        expected_version=created["vessel_space"]["state"]["version"],
        metadata={"vessel_id": vessel_id},
    )
    response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=missing)
    assert response.status_code == 400
    assert "producer receipt" in response.text

    wrong_id = _create_real_destroy_producer(
        campaign_client,
        base,
        current,
        entity_id="different-vessel",
    )
    current = {
        **current,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    mismatch = _body(
        current,
        event="destroy",
        operation_id="destroy-mismatch-producer",
        key="destroy-mismatch-producer-key",
        expected_version=created["vessel_space"]["state"]["version"],
        metadata={"vessel_id": vessel_id, "producer_operation_id": wrong_id},
    )
    response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=mismatch)
    assert response.status_code == 400, response.text
    assert "not bound" in response.text


def test_destroy_item_cas_conflict_rolls_back_vessel_and_character(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"
    _, created = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="create",
            operation_id="destroy-cas-create",
            key="destroy-cas-create-key",
            expected_version=None,
            metadata={"vessel_id": vessel_id, "vessel_appearance": "urn"},
        ),
    )
    current = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    _, entered = _apply(
        campaign_client,
        base,
        _body(
            current,
            event="enter",
            operation_id="destroy-cas-enter",
            key="destroy-cas-enter-key",
            expected_version=created["vessel_space"]["state"]["version"],
            metadata={
                "vessel_id": vessel_id,
                "vessel_subject_ids": [character["_actor_id"]],
                "vessel_item_ids": [character["_item_id"]],
                "vessel_facts": {
                    "vessel_touched": True,
                    "all_creatures_voluntary": True,
                    "all_creatures_visible": True,
                },
            },
        ),
    )
    current = {
        **current,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    producer_id = _create_real_destroy_producer(
        campaign_client,
        base,
        current,
        entity_id=vessel_id,
    )
    current = {
        **current,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    body = _body(
        current,
        event="destroy",
        operation_id="destroy-cas",
        key="destroy-cas-key",
        expected_version=entered["vessel_space"]["state"]["version"],
        metadata={"vessel_id": vessel_id, "producer_operation_id": producer_id},
    )
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    before_character = campaign_client.get(f"{base}/characters/{character['id']}").json()
    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        item = session.get(WorldItem, character["_item_id"])
        assert item is not None
        item.version += 1
    confirmed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 409, confirmed.text
    after_character = campaign_client.get(f"{base}/characters/{character['id']}").json()
    assert after_character["version"] == before_character["version"]
    assert after_character["features"] == before_character["features"]
    items = campaign_client.get(f"{base}/items?owner_character_id={character['id']}").json()[
        "items"
    ]
    item_after = next(item for item in items if item["id"] == character["_item_id"])
    assert item_after["metadata_json"]["vessel_container_id"] == vessel_id
    assert item_after["version"] == preview.json()["vessel_space"]["item_receipts"][0]["before"][
        "version"
    ] + 1
    assert (
        campaign_client.get(f"{base}/characters/{character['id']}").json()["features"][-1][
            "runtime"
        ]["vessel_spaces"][0]["state"]["status"]
        == "inside"
    )


def test_owner_death_relocates_items_with_source_bound_receipts(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    vessel_id = f"{FEATURE_ID}:vessel"
    second = campaign_client.post(
        f"{base}/items",
        json={
            "name": "Owner death vessel item",
            "owner_character_id": character["id"],
            "metadata_json": {"fixture": True},
        },
    )
    assert second.status_code == 201, second.text
    _, created = _apply(
        campaign_client,
        base,
        _body(
            character,
            event="create",
            operation_id="owner-death-create",
            key="owner-death-create",
            expected_version=None,
            metadata={"vessel_id": vessel_id, "vessel_appearance": "urn"},
        ),
    )
    current = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    _, entered = _apply(
        campaign_client,
        base,
        _body(
            current,
            event="enter",
            operation_id="owner-death-enter",
            key="owner-death-enter",
            expected_version=created["vessel_space"]["state"]["version"],
            metadata={
                "vessel_id": vessel_id,
                "vessel_subject_ids": [character["_actor_id"]],
                "vessel_item_ids": [character["_item_id"], second.json()["id"]],
                "vessel_facts": {
                    "vessel_touched": True,
                    "all_creatures_voluntary": True,
                    "all_creatures_visible": True,
                },
            },
        ),
    )
    current = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    combatant = campaign_client.get(
        f"{base}/combats/{current['_combat_id']}/combatants/{current['_actor_id']}"
    )
    assert combatant.status_code == 200, combatant.text
    death = campaign_client.post(
        f"{base}/combats/{current['_combat_id']}/actions/confirm",
        json={
            "action_type": "damage",
            "target_combatant_id": current["_actor_id"],
            "target_version": combatant.json()["version"],
            "amount": 20,
            "damage_type": "force",
        },
        headers={"X-Request-ID": "owner-death-vessel-producer"},
    )
    assert death.status_code == 200, death.text
    assert death.json()["death_save"]["dead"] is True
    current = {
        **character,
        **campaign_client.get(f"{base}/characters/{character['id']}").json(),
    }
    body = _body(
        current,
        event="owner_death",
        operation_id="owner-death-vessel",
        key="owner-death-vessel",
        expected_version=entered["vessel_space"]["state"]["version"],
        metadata={
            "vessel_id": vessel_id,
            "producer_operation_id": death.json()["action"]["transaction_id"],
        },
    )
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    vessel_preview = preview.json()["vessel_space"]
    receipts = vessel_preview["item_receipts"]
    assert len(receipts) == 2
    assert all(
        receipt["after"]["version"] == receipt["before"]["version"] + 1
        for receipt in receipts
    )
    destinations = [receipt["position_receipt"]["to"] for receipt in receipts]
    assert len({(item["row"], item["col"]) for item in destinations}) == 2
    confirmed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["vessel_space"]["state"]["status"] == "removed"
    moved_actor = campaign_client.get(
        f"{base}/combats/{current['_combat_id']}/combatants/{current['_actor_id']}"
    )
    assert moved_actor.status_code == 200, moved_actor.text
    assert moved_actor.json()["version"] == (
        vessel_preview["position_receipts"][0]["before"]["version"] + 1
    )
    replay = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
