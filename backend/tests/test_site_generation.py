from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from dnd_dm_assistant.domain.site_generation import generate_site, layout_is_connected


def _request(**overrides: Any) -> dict[str, Any]:
    return {
        "site_type": "dungeon",
        "name": "低语矿坑",
        "brief": "一座被夺心魔实验污染的多层矿坑",
        "region_path": "深水城/海区",
        "maximum_levels": 4,
        "rooms_min": 4,
        "rooms_max": 8,
        "party_level": 5,
        "party_size": 4,
        "starting_difficulty": "low",
        "difficulty_growth": 2,
        "reward_rate": 1,
        "seed": 424242,
        **overrides,
    }


def test_site_generator_is_deterministic_connected_and_progressive() -> None:
    first = generate_site(_request())
    second = generate_site(_request())
    assert first == second
    assert len(first["levels"]) == 4
    assert len({str(level["layout"]) for level in first["levels"]}) == 4
    assert all(layout_is_connected(level["layout"]) for level in first["levels"])
    difficulty = {"low": 0, "moderate": 1, "high": 2}
    assert [difficulty[level["difficulty"]] for level in first["levels"]] == sorted(
        difficulty[level["difficulty"]] for level in first["levels"]
    )
    rewards = [level["reward_budget_gp"] for level in first["levels"]]
    assert rewards == sorted(rewards)
    assert any(
        monster["name"] == "夺心魔"
        for level in first["levels"]
        for monster in level["monster_plan"]
    )


def test_site_generation_api_persists_atomic_hierarchy_and_is_idempotent(
    campaign_client: TestClient,
) -> None:
    campaign_id = campaign_client.post("/api/v1/campaigns", json={"name": "地图原子化验收"}).json()[
        "id"
    ]
    preview_response = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/sites/generate/preview",
        json=_request(),
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    headers = {"X-Request-ID": "site-acceptance-424242"}
    created = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/sites/generate/confirm",
        headers=headers,
        json={"preview": preview},
    )
    assert created.status_code == 201, created.text
    site = created.json()
    assert len(site["levels"]) == 4
    assert all(level["rooms"] and level["connectors"] for level in site["levels"])
    repeated = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/sites/generate/confirm",
        headers=headers,
        json={"preview": preview},
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == site["id"]
    maps = campaign_client.get(f"/api/v1/campaigns/{campaign_id}/region-maps").json()["region_maps"]
    assert len(maps) == 1
    assert len(maps[0]["map_json"]["pois"]) == 1
    locations = campaign_client.get(f"/api/v1/campaigns/{campaign_id}/locations").json()["items"]
    names = {location["name"] for location in locations}
    assert {"深水城", "海区", "低语矿坑", "地下城第 1 层", "入口厅"} <= names

    other_campaign = campaign_client.post("/api/v1/campaigns", json={"name": "隔离团"}).json()
    forbidden = campaign_client.get(f"/api/v1/campaigns/{other_campaign['id']}/sites/{site['id']}")
    assert forbidden.status_code == 404
