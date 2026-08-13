from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.engine import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import OperationTransaction

SOURCE_ID = "fixture:entity-lifecycle-runtime"
SOURCE_FINGERPRINT = "entity-lifecycle-runtime-fingerprint"
FEATURE_ID = "fixture:entity-lifecycle-runtime"


def _contract(*, provenance: bool = True) -> dict[str, Any]:
    block: dict[str, Any] = {
        "id": "entity-lifecycle",
        "resolution_kind": "entity_lifecycle",
        "entity_type": "spectral_object",
        "lifecycle_schema": "entity.lifecycle.v1",
        "lifecycle_states": ["created", "entered", "exited", "expired"],
        "lifecycle_events": ["create", "enter", "exit", "expire"],
        "source_provenance": {
            "source_record_id": SOURCE_ID,
            "source_fingerprint": SOURCE_FINGERPRINT,
        }
        if provenance
        else {},
        "max_entries": 1,
        "runtime_execution": {"status": "ready"},
    }
    return {
        "automation_status": "full",
        "requires_dm_adjudication": False,
        "runtime_schema_version": "feature-runtime-1",
        "feature_name": "Fixture lifecycle",
        "source_record_id": SOURCE_ID,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "entity_lifecycles": [block],
    }


def _placement_contract() -> dict[str, Any]:
    contract = _contract()
    contract["entity_lifecycles"][0]["initial_placement"] = {
        "max_distance_ft": 60,
        "destination_unoccupied": True,
        "source_object_held": True,
    }
    return contract


def _setup(client: TestClient) -> tuple[str, dict[str, Any]]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Lifecycle runtime"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={"name": "Lifecycle fixture", "class_name": "测试", "level": 1},
    ).json()
    return base, character


def _body(
    character: dict[str, Any],
    *,
    event: str,
    operation_id: str,
    key: str,
    expected_lifecycle_version: int | None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "content_kind": "advancement",
        "runtime_id": FEATURE_ID,
        "permission": "dm",
        "character_id": character["id"],
        "character_version": character["version"],
        "entity_id": "entity-fixture-001",
        "entity_lifecycle_event": event,
        "entity_lifecycle_expected_version": expected_lifecycle_version,
        "entity_lifecycle_metadata": {"owner_character_id": character["id"]},
        "operation_id": operation_id,
        "runtime_contract": contract or _contract(),
        "idempotency_key": key,
    }


def _apply(
    client: TestClient,
    base: str,
    character: dict[str, Any],
    *,
    event: str,
    operation_id: str,
    key: str,
    expected_lifecycle_version: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    body = _body(
        character,
        event=event,
        operation_id=operation_id,
        key=key,
        expected_lifecycle_version=expected_lifecycle_version,
    )
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["entity_lifecycle"]["schema"] == "entity.lifecycle.v1"
    confirmed = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return preview_body, confirmed.json()


def _real_termination_producer(
    client: TestClient,
    base: str,
    character: dict[str, Any],
    reason: str,
) -> tuple[str, dict[str, Any]]:
    combat = client.post(f"{base}/combats", json={"name": f"producer-{reason}"}).json()
    if reason == "dispel_magic":
        target = client.post(
            f"{base}/combats/{combat['id']}/combatants",
            json={
                "display_name": "Manifested entity",
                "entity_type": "spectral_object",
                "initiative": 20,
                "hp": 10,
                "max_hp": 10,
                "entity_id": "entity-fixture-001",
            },
        ).json()
        effect = client.post(
            f"{base}/combats/{combat['id']}/effects/confirm",
            json={
                "target_combatant_id": target["id"],
                "target_version": target["version"],
                "name": "Manifest Mind",
                "effect_type": "aura",
                "details_json": {"entity_lifecycle_entity_id": "entity-fixture-001"},
            },
            headers={"X-Request-ID": "producer-dispel-add"},
        )
        assert effect.status_code == 200, effect.text
        ended = client.post(
            f"{base}/combats/{combat['id']}/effects/{effect.json()['effect']['id']}/end",
            json={
                "target_version": effect.json()["target"]["version"],
                "reason": "Dispel Magic",
            },
            headers={"X-Request-ID": "producer-dispel-end"},
        )
        assert ended.status_code == 200, ended.text
        return ended.json()["action"]["transaction_id"], ended.json()
    if reason == "owner_died":
        owner = client.post(
            f"{base}/combats/{combat['id']}/combatants",
            json={
                "display_name": "Owner",
                "entity_type": "character",
                "entity_id": character["id"],
                "initiative": 20,
                "hp": 1,
                "max_hp": 1,
            },
        ).json()
        damage = client.post(
            f"{base}/combats/{combat['id']}/actions/confirm",
            json={
                "action_type": "damage",
                "target_combatant_id": owner["id"],
                "target_version": owner["version"],
                "amount": 2,
                "damage_type": "force",
            },
            headers={"X-Request-ID": "producer-owner-damage"},
        )
        assert damage.status_code == 200, damage.text
        assert damage.json()["death_save"]["dead"] is True
        result = damage.json()
        result["death_save"] = {"dead": True}
        return result["action"]["transaction_id"], result
    if reason == "owner_dismissed":
        owner = client.post(
            f"{base}/combats/{combat['id']}/combatants",
            json={
                "display_name": "Owner",
                "entity_type": "character",
                "entity_id": character["id"],
                "initiative": 20,
                "hp": 10,
                "max_hp": 10,
            },
        ).json()
        summon = client.post(
            f"{base}/combats/{combat['id']}/summons",
            json={
                "name": "Manifested entity",
                "controller": "player",
                "owner_character_id": character["id"],
                "source_combatant_id": owner["id"],
                "source_version": owner["version"],
                "initiative_mode": "shared_with_source",
                "action_cost": "none",
                "hp": 5,
                "max_hp": 5,
                "armor_class": 10,
                "speed_ft": 30,
                "template_json": {"entity_id": "entity-fixture-001"},
            },
            headers={"X-Request-ID": "producer-dismiss-add"},
        )
        assert summon.status_code == 200, summon.text
        summon_body = summon.json()["combatant"]
        ended = client.post(
            f"{base}/combats/{combat['id']}/summons/{summon_body['id']}/end",
            json={
                "summon_version": summon_body["version"],
                "actor": "player",
                "action_cost": "bonus_action",
                "reason": "Owner bonus action dismissal",
            },
            headers={"X-Request-ID": "producer-dismiss-end"},
        )
        assert ended.status_code == 200, ended.text
        return ended.json()["action"]["transaction_id"], ended.json()
    raise AssertionError(f"unsupported real producer reason: {reason}")


def test_entity_lifecycle_real_service_receipt_chain_and_replay(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    current = character
    receipts: list[dict[str, Any]] = []
    first_confirm_body: dict[str, Any] | None = None
    for index, event in enumerate(("create", "enter", "exit", "expire"), start=1):
        preview_body, confirmed = _apply(
            campaign_client,
            base,
            current,
            event=event,
            operation_id=f"lifecycle-op-{index}",
            key=f"lifecycle-runtime-{index}",
            expected_lifecycle_version=None if index == 1 else index - 1,
        )
        receipts.append(confirmed["entity_lifecycle"])
        if index == 1:
            first_confirm_body = _body(
                character,
                event=event,
                operation_id=f"lifecycle-op-{index}",
                key=f"lifecycle-runtime-{index}",
                expected_lifecycle_version=None,
            )
            first_confirm_body["preview_token"] = preview_body["preview_token"]
        assert confirmed["production_runtime_full"] is True
        current = campaign_client.get(f"{base}/characters/{current['id']}").json()
        assert current["version"] == character["version"] + index

    assert [item["state"]["status"] for item in receipts] == [
        "created",
        "entered",
        "exited",
        "expired",
    ]
    assert receipts[-1]["state"]["source_id"] == SOURCE_ID
    assert receipts[-1]["state"]["source_fingerprint"] == SOURCE_FINGERPRINT

    replay = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json=first_confirm_body,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True

    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        operations = session.scalars(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == base.rsplit("/", 1)[-1],
                OperationTransaction.operation_type == "content_ir_advancement",
            )
        ).all()
    assert len(operations) == 4


def test_entity_lifecycle_real_service_fails_closed_for_invalid_state_payload_and_stale_cas(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    _, created = _apply(
        campaign_client,
        base,
        character,
        event="create",
        operation_id="invalid-state-create",
        key="invalid-state-create",
        expected_lifecycle_version=None,
    )
    after_create = campaign_client.get(f"{base}/characters/{character['id']}").json()
    invalid_body = _body(
        after_create,
        event="exit",
        operation_id="invalid-exit",
        key="invalid-exit",
        expected_lifecycle_version=1,
    )
    invalid = campaign_client.post(
        f"{base}/content-ir/runtime/preview", json=invalid_body
    )
    assert invalid.status_code == 400
    assert "cannot exit from status created" in invalid.text

    stale_body = _body(
        after_create,
        event="enter",
        operation_id="stale-enter",
        key="stale-enter",
        expected_lifecycle_version=1,
    )
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=stale_body)
    assert preview.status_code == 200, preview.text
    latest = campaign_client.get(f"{base}/characters/{character['id']}").json()
    _, _ = _apply(
        campaign_client,
        base,
        latest,
        event="enter",
        operation_id="fresh-enter",
        key="fresh-enter",
        expected_lifecycle_version=1,
    )
    stale = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**stale_body, "preview_token": preview.json()["preview_token"]},
    )
    assert stale.status_code == 409, stale.text

    current_after_enter = campaign_client.get(f"{base}/characters/{character['id']}").json()
    drift_body = _body(
        current_after_enter,
        event="enter",
        operation_id="fresh-enter",
        key="fresh-enter-drift",
        expected_lifecycle_version=2,
    )
    drift_body["entity_lifecycle_metadata"] = {"different": True}
    drift = campaign_client.post(f"{base}/content-ir/runtime/preview", json=drift_body)
    assert drift.status_code == 400
    assert "replay payload" in drift.text or "version conflict" in drift.text


@pytest.mark.parametrize("missing", ["source_record_id", "source_fingerprint"])
def test_entity_lifecycle_real_service_requires_provenance(
    campaign_client: TestClient,
    missing: str,
) -> None:
    base, character = _setup(campaign_client)
    contract = _contract()
    contract["entity_lifecycles"][0]["source_provenance"].pop(missing)
    response = campaign_client.post(
        f"{base}/content-ir/runtime/preview",
        json=_body(
            character,
            event="create",
            operation_id=f"missing-{missing}",
            key=f"missing-{missing}",
            expected_lifecycle_version=None,
            contract=contract,
        ),
    )
    assert response.status_code == 400
    assert "source provenance" in response.text


@pytest.mark.parametrize(
    ("reason", "operation_type", "after"),
    [
        (
            "dispel_magic",
            "combat_end_effect",
            {
                "effect_id": "effect-1",
                "entity_ids": ["entity-fixture-001"],
                "status": "ended",
                "end_reason": "Dispel Magic",
            },
        ),
        (
            "source_object_destroyed",
            "equipment_destroy",
            {
                "state": "destroyed",
                "equipment_id": "equipment-1",
                "entity_id": "entity-fixture-001",
            },
        ),
        (
            "owner_died",
            "combat_confirm_death",
            {
                "owner_character_id": "owner-placeholder",
                "dead": True,
            },
        ),
        (
            "owner_dismissed",
            "combat_end_summon",
            {
                "entity_id": "entity-fixture-001",
                "reason": "owner bonus action dismissal",
            },
        ),
    ],
)
def test_termination_runtime_requires_real_producer_receipt_and_is_idempotent(
    campaign_client: TestClient,
    reason: str,
    operation_type: str,
    after: dict[str, Any],
) -> None:
    base, character = _setup(campaign_client)
    current = character
    for index, event in enumerate(("create", "enter", "exit"), start=1):
        _, _ = _apply(
            campaign_client,
            base,
            current,
            event=event,
            operation_id=f"termination-setup-{index}",
            key=f"termination-setup-{index}",
            expected_lifecycle_version=None if index == 1 else index - 1,
        )
        current = campaign_client.get(f"{base}/characters/{character['id']}").json()

    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    if reason == "source_object_destroyed":
        created_equipment = campaign_client.post(
            f"{base}/characters/assets/equipment",
            json={
                "character_id": character["id"],
                "character_version": current["version"],
                "name": "Awakened spellbook",
                "category": "gear",
                "metadata_json": {"entity_id": "entity-fixture-001"},
            },
        )
        assert created_equipment.status_code == 201, created_equipment.text
        equipment = created_equipment.json()
        current = campaign_client.get(f"{base}/characters/{character['id']}").json()
        destroy_body = {
            "character_id": character["id"],
            "character_version": current["version"],
            "equipment_id": equipment["id"],
            "operation": "destroy",
            "amount": 1,
        }
        destroy_preview = campaign_client.post(
            f"{base}/equipment/preview", json=destroy_body
        )
        assert destroy_preview.status_code == 200, destroy_preview.text
        destroy = campaign_client.post(
            f"{base}/equipment/confirm",
            json={
                **destroy_body,
                "preview_token": destroy_preview.json()["preview_token"],
                "idempotency_key": "producer-spellbook-destroy",
            },
        )
        assert destroy.status_code == 200, destroy.text
        with Session(engine) as session:
            producer = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == base.rsplit("/", 1)[-1],
                    OperationTransaction.idempotency_key == "equipment:producer-spellbook-destroy",
                )
            )
            assert producer is not None
            producer_id = producer.id
        current = campaign_client.get(f"{base}/characters/{character['id']}").json()
    else:
        producer_id, producer_result = _real_termination_producer(
            campaign_client,
            base,
            character,
            reason,
        )
        if reason == "owner_died":
            assert producer_result["death_save"]["dead"] is True
        if reason == "owner_dismissed":
            assert producer_result["action"]["request_json"]["action_cost"] == "bonus_action"
            owner = campaign_client.get(
                f"{base}/combats/{producer_result['combat']['id']}/combatants/"
                f"{producer_result['action']['actor_combatant_id']}"
            )
            assert owner.status_code == 200, owner.text
            assert owner.json()["bonus_action_available"] is False

    body = _body(
        current,
        event="terminate",
        operation_id=f"termination-{reason}",
        key=f"termination-{reason}",
        expected_lifecycle_version=3,
    )
    body["entity_lifecycle_metadata"] = {
        "owner_character_id": character["id"],
        "termination_reason": reason,
        "producer_operation_id": producer_id,
    }
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["entity_lifecycle"]["state"]["status"] == "terminated"
    confirmed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["entity_lifecycle"]["state"]["termination_reason"] == reason
    expected_operation_type = (
        "combat_damage" if reason == "owner_died" else operation_type
    )
    assert (
        confirmed.json()["entity_lifecycle"]["producer_receipt"]["operation_type"]
        == expected_operation_type
    )

    replay = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True

    stale = dict(body)
    stale["idempotency_key"] = f"stale-{reason}"
    stale["operation_id"] = f"stale-{reason}"
    stale["entity_lifecycle_expected_version"] = 3
    stale["preview_token"] = preview.json()["preview_token"]
    stale_response = campaign_client.post(f"{base}/content-ir/runtime/confirm", json=stale)
    assert stale_response.status_code == 409, stale_response.text


def test_termination_runtime_rejects_failed_or_unbound_producer_without_mutation(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    _, created = _apply(
        campaign_client,
        base,
        character,
        event="create",
        operation_id="termination-negative-create",
        key="termination-negative-create",
        expected_lifecycle_version=None,
    )
    current = campaign_client.get(f"{base}/characters/{character['id']}").json()
    combat = campaign_client.post(f"{base}/combats", json={"name": "failed-dispel"}).json()
    target = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "Manifested entity",
            "entity_type": "spectral_object",
            "initiative": 20,
            "hp": 10,
            "max_hp": 10,
            "entity_id": "entity-fixture-001",
        },
    ).json()
    effect = campaign_client.post(
        f"{base}/combats/{combat['id']}/effects/confirm",
        json={
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "name": "Manifest Mind",
            "effect_type": "aura",
            "details_json": {"entity_lifecycle_entity_id": "entity-fixture-001"},
        },
        headers={"X-Request-ID": "failed-dispel-add"},
    )
    assert effect.status_code == 200, effect.text
    failed = campaign_client.post(
        f"{base}/combats/{combat['id']}/effects/{effect.json()['effect']['id']}/end",
        json={
            "target_version": target["version"],
            "reason": "Dispel Magic",
        },
        headers={"X-Request-ID": "failed-dispel-end"},
    )
    assert failed.status_code == 409, failed.text
    producer_id = "missing-after-failed-producer"
    body = _body(
        current,
        event="terminate",
        operation_id="termination-negative",
        key="termination-negative",
        expected_lifecycle_version=1,
    )
    body["entity_lifecycle_metadata"] = {
        "owner_character_id": character["id"],
        "termination_reason": "dispel_magic",
        "producer_operation_id": producer_id,
    }
    response = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert response.status_code == 404
    unchanged = campaign_client.get(f"{base}/characters/{character['id']}").json()
    assert unchanged["version"] == current["version"]
    assert unchanged["features"] == current["features"]


def test_entity_lifecycle_initial_placement_receipt_requires_authoritative_facts(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    body = _body(
        character,
        event="create",
        operation_id="placement-create",
        key="placement-create-key",
        expected_lifecycle_version=None,
        contract=_placement_contract(),
    )
    body["entity_lifecycle_metadata"] = {
        "owner_character_id": character["id"],
        "initial_placement": {
            "distance_from_owner_ft": 60,
            "destination_unoccupied": True,
            "source_object_held": True,
        },
    }
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["entity_lifecycle"]["state"]["metadata"]["initial_placement"] == {
        "distance_from_owner_ft": 60,
        "destination_unoccupied": True,
        "source_object_held": True,
    }
    confirmed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["entity_lifecycle"]["state"]["status"] == "created"
    assert confirmed.json()["production_runtime_full"] is True

    missing_fact = {
        **body,
        "character_version": campaign_client.get(
            f"{base}/characters/{character['id']}"
        ).json()["version"],
        "entity_id": "entity-fixture-002",
        "operation_id": "placement-missing-fact",
        "idempotency_key": "placement-missing-fact-key",
        "entity_lifecycle_metadata": {
            "owner_character_id": character["id"],
            "initial_placement": {
                "distance_from_owner_ft": 61,
                "destination_unoccupied": True,
                "source_object_held": True,
            },
        },
    }
    rejected = campaign_client.post(
        f"{base}/content-ir/runtime/preview", json=missing_fact
    )
    assert rejected.status_code == 400
    assert "exceeds range" in rejected.text
