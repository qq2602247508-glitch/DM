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
