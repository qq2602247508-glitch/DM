from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = (
    ROOT
    / "data/content-ir/isolated-packs/tashas-cauldron-2026-08-12/feature-contract-batch-I"
    / "feature-runtime-registry/tashas-cauldron--source-7011166c19bd.json"
)


def _contract(feature_id: str) -> dict[str, Any]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return dict(payload["runtime_contracts"][feature_id])


def _apply(
    client: TestClient,
    base: str,
    character: dict[str, Any],
    feature_id: str,
    *,
    choices: dict[str, list[str]] | None = None,
    key: str,
) -> dict[str, Any]:
    body = {
        "content_kind": "advancement",
        "runtime_id": feature_id,
        "character_id": character["id"],
        "character_version": character["version"],
        "advancement_choices": choices or {},
        "runtime_contract": _contract(feature_id),
        "idempotency_key": key,
    }
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["production_contract"]["consumers"] == [
        "advancement_service.character_growth.v1"
    ]
    confirmed = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["production_runtime_full"] is True
    replay = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_body["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    return result


def test_typed_content_ir_advancement_consumes_fixed_and_selected_grants(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "Round V advancement consumer"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    fixed = campaign_client.post(
        f"{base}/characters",
        json={"name": "fixed growth", "class_name": "法师", "level": 3},
    ).json()
    _apply(
        campaign_client,
        base,
        fixed,
        "content.tashas-cauldron.round2.feature.bladesinger-training-in-sword-and-song",
        key="round-v-fixed-growth",
    )
    fixed_after = campaign_client.get(f"{base}/characters/{fixed['id']}").json()
    assert "one_handed_melee_weapon" in fixed_after["proficiencies"]
    assert any(
        item.get("feature_id")
        == "content.tashas-cauldron.round2.feature.bladesinger-training-in-sword-and-song"
        for item in fixed_after["features"]
    )

    selected = campaign_client.post(
        f"{base}/characters",
        json={"name": "selected growth", "class_name": "游侠", "level": 5},
    ).json()
    _apply(
        campaign_client,
        base,
        selected,
        "content.tashas-cauldron.round2.feature.ranger-canny",
        choices={"chosen_skill": ["stealth"], "chosen_language": ["Elvish"]},
        key="round-v-selected-growth",
    )
    selected_after = campaign_client.get(f"{base}/characters/{selected['id']}").json()
    assert selected_after["skills"]["stealth"]["proficient"] is True
    assert "语言：Elvish" in selected_after["proficiencies"]
