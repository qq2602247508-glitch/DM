from __future__ import annotations

from fastapi.testclient import TestClient


def _preview_confirm(
    client: TestClient, campaign_id: str, operation: dict[str, object], key: str
) -> None:
    body = {"operations": [operation], "idempotency_key": key}
    preview = client.post(
        f"/api/v1/campaigns/{campaign_id}/narrative/preview", json=body
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/api/v1/campaigns/{campaign_id}/narrative/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text


def test_narrative_runtime_persists_progress_until_threshold(
    campaign_client: TestClient,
) -> None:
    campaign_id = campaign_client.post(
        "/api/v1/campaigns", json={"name": "Persistent challenge"}
    ).json()["id"]
    base: dict[str, object] = {
        "kind": "runtime",
        "runtime_id": "runtime-1",
        "mode": "skill_challenge",
        "title": "穿越燃烧的桥",
        "target_successes": 2,
        "target_failures": 2,
    }
    _preview_confirm(campaign_client, campaign_id, base, "runtime-create-1")
    _preview_confirm(
        campaign_client,
        campaign_id,
        {
            "kind": "runtime",
            "runtime_id": "runtime-1",
            "mode": "skill_challenge",
            "success_delta": 1,
        },
        "runtime-success-1",
    )
    response = campaign_client.get(
        f"/api/v1/campaigns/{campaign_id}/narrative/runtimes"
    )
    assert response.status_code == 200
    runtime = response.json()["items"][0]
    assert runtime["successes"] == 1
    assert runtime["failures"] == 0
    assert runtime["status"] == "active"

    _preview_confirm(
        campaign_client,
        campaign_id,
        {
            "kind": "runtime",
            "runtime_id": "runtime-1",
            "mode": "skill_challenge",
            "success_delta": 1,
        },
        "runtime-success-2",
    )
    runtime = campaign_client.get(
        f"/api/v1/campaigns/{campaign_id}/narrative/runtimes"
    ).json()["items"][0]
    assert runtime["successes"] == 2
    assert runtime["status"] == "succeeded"

