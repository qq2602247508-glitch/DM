from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.engine import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import OperationTransaction

SOURCE_ID = "fixture:round-XXXVI-reactivation"
SOURCE_FP = "round-XXXVI-reactivation-fingerprint"
FEATURE_ID = "fixture:round-XXXVI-reactivation"


def _contract() -> dict[str, Any]:
    return {
        "automation_status": "full",
        "requires_dm_adjudication": False,
        "runtime_schema_version": "feature-runtime-1",
        "feature_name": "Fixture reactivation",
        "source_record_id": SOURCE_ID,
        "source_fingerprint": SOURCE_FP,
        "spell_slot_reactivations": [
            {
                "id": "reactivation",
                "feature_id": FEATURE_ID,
                "resolution_kind": "spell_slot_reactivation",
                "entity_binding": "entity_lifecycle",
                "spell_slot_resource_prefix": "spell_slots_",
                "source_provenance": {
                    "source_record_id": SOURCE_ID,
                    "source_fingerprint": SOURCE_FP,
                },
                "runtime_execution": {"status": "production_partial"},
            }
        ],
    }


def _setup(client: TestClient) -> tuple[str, dict[str, Any]]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Round XXXVI"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "Reactivation fixture",
            "class_name": "测试",
            "level": 6,
            "hp": 10,
            "max_hp": 10,
            "resources": {
                "spell_slots_1": {"current": 1, "max": 1},
                "spell_slots_9": {"current": 1, "max": 1},
            },
        },
    ).json()
    return base, character


def _body(
    character: dict[str, Any],
    *,
    event: str,
    operation_id: str,
    key: str,
    expected_version: int | None,
    payment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "content_kind": "advancement",
        "runtime_id": FEATURE_ID,
        "permission": "dm",
        "character_id": character["id"],
        "character_version": character["version"],
        "entity_id": "manifest-mind-fixture",
        "entity_lifecycle_event": event,
        "entity_lifecycle_expected_version": expected_version,
        "entity_lifecycle_metadata": {"owner_character_id": character["id"]},
        "operation_id": operation_id,
        "reactivation_payment": payment,
        "runtime_contract": _contract(),
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
    expected_version: int | None,
    payment: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    body = _body(
        character,
        event=event,
        operation_id=operation_id,
        key=key,
        expected_version=expected_version,
        payment=payment,
    )
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    confirm = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    assert confirm.status_code == 200, confirm.text
    return body, preview_body, confirm.json()


def test_real_reactivation_receipt_slot_payment_replay_and_long_rest(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    _, _, activated = _apply(
        campaign_client,
        base,
        character,
        event="activate",
        operation_id="activate-1",
        key="reactivation-activate-1",
        expected_version=None,
    )
    assert activated["spell_slot_reactivation"]["state"]["status"] == "active"
    current = campaign_client.get(f"{base}/characters/{character['id']}").json()
    _, _, deactivated = _apply(
        campaign_client,
        base,
        current,
        event="deactivate",
        operation_id="deactivate-1",
        key="reactivation-deactivate-1",
        expected_version=1,
    )
    assert deactivated["spell_slot_reactivation"]["state"]["status"] == "inactive"
    current = campaign_client.get(f"{base}/characters/{character['id']}").json()
    body, preview, paid = _apply(
        campaign_client,
        base,
        current,
        event="reactivate",
        operation_id="reactivate-1",
        key="reactivation-paid-1",
        expected_version=2,
        payment={
            "kind": "spell_slot_any_level",
            "resource_key": "spell_slots_9",
            "slot_level": 9,
            "amount": 1,
        },
    )
    assert paid["spell_slot_reactivation"]["payment"]["amount"] == 1
    assert campaign_client.get(f"{base}/characters/{character['id']}").json()[
        "resources"
    ]["spell_slots_9"]["current"] == 0
    replay = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview["preview_token"]},
    )
    assert replay.status_code == 200
    assert replay.json()["already_applied"] is True
    assert campaign_client.get(f"{base}/characters/{character['id']}").json()[
        "resources"
    ]["spell_slots_9"]["current"] == 0

    current = campaign_client.get(f"{base}/characters/{character['id']}").json()
    _, _, deactivated_again = _apply(
        campaign_client,
        base,
        current,
        event="deactivate",
        operation_id="deactivate-2",
        key="reactivation-deactivate-2",
        expected_version=3,
    )
    assert deactivated_again["spell_slot_reactivation"]["state"]["status"] == "inactive"
    current = campaign_client.get(f"{base}/characters/{character['id']}").json()
    rest_body = {
        "rest_type": "long",
        "duration_minutes": 480,
        "participants": [
            {
                "character_id": current["id"],
                "character_version": current["version"],
                "hit_dice": [],
            }
        ],
        "idempotency_key": "reactivation-long-rest-1",
    }
    rest_preview = campaign_client.post(f"{base}/rests/preview", json=rest_body)
    assert rest_preview.status_code == 200, rest_preview.text
    rest = campaign_client.post(
        f"{base}/rests/confirm",
        json={**rest_body, "preview_token": rest_preview.json()["preview_token"]},
    )
    assert rest.status_code == 200, rest.text
    after_rest = campaign_client.get(f"{base}/characters/{character['id']}").json()
    assert after_rest["resources"]["spell_slots_9"]["current"] == 0
    state = next(
        record["state"]
        for feature in after_rest["features"]
        for record in feature.get("runtime", {}).get("spell_slot_reactivations", [])
    )
    assert state["reactivation_available"] is True

    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        operations = session.scalars(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == base.rsplit("/", 1)[-1],
                OperationTransaction.idempotency_key.like("content-ir:reactivation-%"),
            )
        ).all()
    assert len(operations) == 4


def test_reactivation_fails_closed_for_slot_shortage_and_stale_cas(
    campaign_client: TestClient,
) -> None:
    base, character = _setup(campaign_client)
    _, _, _ = _apply(
        campaign_client,
        base,
        character,
        event="activate",
        operation_id="activate-shortage",
        key="reactivation-shortage-1",
        expected_version=None,
    )
    current = campaign_client.get(f"{base}/characters/{character['id']}").json()
    _, _, _ = _apply(
        campaign_client,
        base,
        current,
        event="deactivate",
        operation_id="deactivate-shortage",
        key="reactivation-shortage-2",
        expected_version=1,
    )
    current = campaign_client.get(f"{base}/characters/{character['id']}").json()
    body = _body(
        current,
        event="reactivate",
        operation_id="reactivate-shortage",
        key="reactivation-shortage-3",
        expected_version=2,
        payment={
            "kind": "spell_slot_any_level",
            "resource_key": "spell_slots_1",
            "slot_level": 1,
            "amount": 1,
        },
    )
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200
    patched = campaign_client.patch(
        f"{base}/characters/{current['id']}",
        json={
            "resources": {"spell_slots_1": {"current": 0, "max": 1}},
            "version": current["version"],
        },
    )
    assert patched.status_code == 200, patched.text
    failed = campaign_client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert failed.status_code == 409
    unchanged = campaign_client.get(f"{base}/characters/{current['id']}").json()
    assert unchanged["resources"]["spell_slots_1"]["current"] == 0
