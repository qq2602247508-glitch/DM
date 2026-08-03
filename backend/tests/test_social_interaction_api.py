from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.exploration import resolve_social_attitude
from dnd_dm_assistant.infrastructure.database.models import (
    NPCMemory,
    OperationTransaction,
    WorldClock,
)


def _social_paths(campaign_id: str, npc_id: str) -> tuple[str, str]:
    base = f"/api/v1/campaigns/{campaign_id}/npcs/{npc_id}/social"
    return f"{base}/preview", f"{base}/confirm"


def test_social_attitude_transition_normalizes_and_clamps() -> None:
    improved = resolve_social_attitude("敌对", "improve")
    assert (improved.before, improved.after, improved.effective_delta) == (
        "hostile",
        "indifferent",
        1,
    )

    capped = resolve_social_attitude("friendly", "improve")
    assert capped.after == "friendly"
    assert capped.effective_delta == 0

    normalized = resolve_social_attitude("suspicious", "unchanged")
    assert normalized.before == normalized.after == "indifferent"
    assert normalized.normalized_from_nonstandard is True


def test_social_preview_confirm_persists_attitude_memory_and_world_time(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "社交确认", "current_time": "2026-08-01T12:00:00+00:00"},
    ).json()
    campaign_id = campaign["id"]
    base = f"/api/v1/campaigns/{campaign_id}"
    npc = campaign_client.post(
        f"{base}/npcs",
        json={"name": "守门人", "attitude": "hostile"},
    ).json()
    preview_path, confirm_path = _social_paths(campaign_id, npc["id"])
    body = {
        "npc_version": npc["version"],
        "outcome": "improve",
        "minutes": 15,
        "summary": "队伍归还了遗失的徽记。",
        "memory_kind": "favor",
        "tags": ["gate", "badge"],
    }

    preview_response = campaign_client.post(preview_path, json=body)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["requires_confirmation"] is True
    assert preview["npc"]["attitude"] == {
        "before": "hostile",
        "after": "indifferent",
        "requested_delta": 1,
        "effective_delta": 1,
    }
    assert preview["world_time"]["after"].startswith("2026-08-01T12:15:00")

    # Preview is read-only: no attitude change or memory is committed yet.
    assert campaign_client.get(f"{base}/npcs/{npc['id']}").json()["attitude"] == "hostile"

    confirm_body = {
        **body,
        "preview_token": preview["preview_token"],
        "idempotency_key": "social-gatekeeper-0001",
    }
    confirmed = campaign_client.post(confirm_path, json=confirm_body)
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["idempotent_replay"] is False
    assert result["npc"]["attitude"] == "indifferent"
    assert result["npc"]["version"] == npc["version"] + 1
    assert result["npc_memory"]["summary"] == body["summary"]
    assert result["npc_memory"]["attitude_delta"] == 1
    assert result["world_time"].startswith("2026-08-01T12:15:00")

    replay = campaign_client.post(confirm_path, json=confirm_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["operation_transaction_id"] == result["operation_transaction_id"]

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        memory = session.scalar(select(NPCMemory).where(NPCMemory.npc_id == npc["id"]))
        assert memory is not None
        assert memory.memory_kind == "favor"
        assert memory.tags == ["gate", "badge"]
        assert memory.attitude_delta == 1

        clock = session.scalar(select(WorldClock).where(WorldClock.campaign_id == campaign_id))
        assert clock is not None
        assert clock.current_time is not None
        assert clock.current_time.replace(tzinfo=None) == datetime(2026, 8, 1, 12, 15)

        transaction = session.get(OperationTransaction, result["operation_transaction_id"])
        assert transaction is not None
        assert transaction.operation_type == "social_interaction"
        before_npc = cast(dict[str, object], transaction.before_snapshot["npc"])
        after_npc = cast(dict[str, object], transaction.after_snapshot["npc"])
        assert before_npc["attitude"] == "hostile"
        assert after_npc["attitude"] == "indifferent"
        assert (
            session.scalar(
                select(func.count()).select_from(NPCMemory).where(NPCMemory.npc_id == npc["id"])
            )
            == 1
        )


def test_social_confirm_rejects_a_stale_npc_preview(
    campaign_client: TestClient,
) -> None:
    campaign_id = campaign_client.post("/api/v1/campaigns", json={"name": "社交并发"}).json()["id"]
    base = f"/api/v1/campaigns/{campaign_id}"
    npc = campaign_client.post(f"{base}/npcs", json={"name": "船长", "attitude": "neutral"}).json()
    preview_path, confirm_path = _social_paths(campaign_id, npc["id"])
    body = {
        "npc_version": npc["version"],
        "outcome": "improve",
        "summary": "队伍提供了安全航线。",
    }
    preview = campaign_client.post(preview_path, json=body).json()
    changed = campaign_client.patch(
        f"{base}/npcs/{npc['id']}",
        json={"attitude": "friendly", "version": npc["version"]},
    )
    assert changed.status_code == 200, changed.text

    stale = campaign_client.post(
        confirm_path,
        json={
            **body,
            "preview_token": preview["preview_token"],
            "idempotency_key": "social-captain-stale-0001",
        },
    )
    assert stale.status_code == 409

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(NPCMemory).where(NPCMemory.npc_id == npc["id"])
            )
            == 0
        )
