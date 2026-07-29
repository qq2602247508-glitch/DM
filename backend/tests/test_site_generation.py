from __future__ import annotations

from copy import deepcopy
from threading import Barrier, Lock, Thread
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.site_generation import generate_site, layout_is_connected
from dnd_dm_assistant.infrastructure.database.models import (
    AdventureSite,
    Location,
    Scene,
    SceneGrid,
    SceneObject,
    SceneToken,
)
from dnd_dm_assistant.infrastructure.database.site_service import SiteService


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


def test_buildings_and_dungeons_use_distinct_high_quality_layout_grammars() -> None:
    building = generate_site(
        _request(
            site_type="building",
            name="普罗宅邸",
            brief="带有主会客厅、卧室、书房、厨房和密室的旧贵族宅邸",
            maximum_levels=3,
        )
    )
    dungeon = generate_site(_request(maximum_levels=3))
    for level in building["levels"]:
        assert level["quality"]["score"] >= 88
        assert level["quality"]["algorithm"] == "building_wings_bsp"
        assert level["quality"]["largest_smallest_ratio"] >= 1.8
        assert level["quality"]["valid_connectors"] >= len(level["rooms"]) - 1
    for level in dungeon["levels"]:
        assert level["quality"]["score"] >= 88
        assert level["quality"]["algorithm"] == "dungeon_rooms_and_corridors"
        assert level["quality"]["valid_connectors"] >= len(level["rooms"]) - 1
    assert building["levels"][0]["layout"]["width"] != dungeon["levels"][0]["layout"]["width"]
    assert any(
        connector["connector_type"] == "secret_door"
        for level in dungeon["levels"]
        for connector in level["connectors"]
    )
    assert any(
        cell["kind"] == "stairs"
        for level in building["levels"]
        for cell in level["layout"]["cells"]
    )


def test_multilevel_tavern_has_irregular_wings_and_semantic_furnishings() -> None:
    tavern = generate_site(
        _request(
            site_type="building",
            name="铜壶与狮鹫酒馆",
            brief="三层临街酒馆，有公共大厅、吧台、后厨、客房、包间和地下酒窖",
            maximum_levels=3,
            rooms_min=6,
            rooms_max=8,
            seed=20260728,
        )
    )
    labels = {
        cell["label"]
        for level in tavern["levels"]
        for cell in level["layout"]["cells"]
        if cell["kind"] == "cover"
    }
    room_names = {room["name"] for level in tavern["levels"] for room in level["rooms"]}
    assert all(level["quality"]["outline"] == "l_shape" for level in tavern["levels"])
    assert all(level["quality"]["furniture_diversity"] >= 8 for level in tavern["levels"])
    assert {"公共大厅", "吧台", "厨房", "客房", "酒窖"} <= room_names
    assert {"桌椅", "吧台", "酒桶", "炉灶", "床铺"} <= labels


def test_layout_quality_gate_holds_across_many_seeds_and_themes() -> None:
    cases = (
        ("building", "两层酒馆与客房"),
        ("building", "被邪教徒占领的旧教堂"),
        ("dungeon", "亡灵墓穴与隐藏藏宝室"),
        ("dungeon", "地精洞穴、分叉通道和首领巢穴"),
    )
    scores: list[int] = []
    for site_type, brief in cases:
        for seed in range(20, 30):
            preview = generate_site(
                _request(
                    site_type=site_type,
                    name=brief,
                    brief=brief,
                    maximum_levels=2,
                    seed=seed,
                )
            )
            scores.extend(level["quality"]["score"] for level in preview["levels"])
    assert min(scores) >= 88


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
    engine = campaign_client.app.state.database_engine
    with Session(engine) as session:
        grids = list(
            session.scalars(
                select(SceneGrid)
                .join(Scene, SceneGrid.scene_id == Scene.id)
                .where(Scene.campaign_id == campaign_id)
            )
        )
        assert grids
        assert all(
            int(cell["row"]) >= 1 and int(cell["col"]) >= 1
            for grid in grids
            for cell in grid.layers_json["cells"]
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SceneToken)
                .join(Scene)
                .where(
                    Scene.campaign_id == campaign_id,
                    SceneToken.entity_type == "monster",
                )
            )
            > 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SceneObject)
                .join(Scene)
                .where(
                    Scene.campaign_id == campaign_id,
                    SceneObject.object_type == "treasure",
                )
            )
            > 0
        )
        for token in session.scalars(
            select(SceneToken)
            .join(Scene)
            .where(
                Scene.campaign_id == campaign_id,
                SceneToken.entity_type.in_(("monster", "npc")),
            )
        ):
            session.delete(token)
        for scene_object in session.scalars(
            select(SceneObject)
            .join(Scene)
            .where(
                Scene.campaign_id == campaign_id,
                SceneObject.object_type == "treasure",
            )
        ):
            session.delete(scene_object)
        session.commit()
    repaired = campaign_client.post(f"/api/v1/campaigns/{campaign_id}/sites/repair-scene-atoms")
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["tokens"] > 0
    assert repaired.json()["treasures"] > 0
    repeated_repair = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/sites/repair-scene-atoms"
    )
    assert repeated_repair.json()["tokens"] == 0
    assert repeated_repair.json()["treasures"] == 0

    other_campaign = campaign_client.post("/api/v1/campaigns", json={"name": "隔离团"}).json()
    forbidden = campaign_client.get(f"/api/v1/campaigns/{other_campaign['id']}/sites/{site['id']}")
    assert forbidden.status_code == 404


def test_site_preview_rejects_broken_cross_references_and_geometry() -> None:
    preview = generate_site(_request(maximum_levels=2))

    invalid = deepcopy(preview)
    invalid["site"]["maximum_levels"] = 3
    with pytest.raises(ValueError, match="maximum_levels"):
        SiteService._validate_preview(invalid)

    invalid = deepcopy(preview)
    invalid["levels"][0]["rooms"][1]["room_index"] = invalid["levels"][0]["rooms"][0]["room_index"]
    with pytest.raises(ValueError, match="room indexes"):
        SiteService._validate_preview(invalid)

    invalid = deepcopy(preview)
    invalid["levels"][0]["rooms"][0]["bounds"]["row"] = invalid["levels"][0]["layout"]["height"]
    with pytest.raises(ValueError, match="bounds exceed"):
        SiteService._validate_preview(invalid)

    invalid = deepcopy(preview)
    invalid["levels"][0]["rooms"][1]["bounds"] = deepcopy(
        invalid["levels"][0]["rooms"][0]["bounds"]
    )
    with pytest.raises(ValueError, match="must not overlap"):
        SiteService._validate_preview(invalid)

    invalid = deepcopy(preview)
    invalid["levels"][0]["connectors"][0]["to_level_index"] = 99
    with pytest.raises(ValueError, match="same level"):
        SiteService._validate_preview(invalid)

    invalid = deepcopy(preview)
    invalid["levels"][0]["connectors"][0]["to_room_index"] = 999
    with pytest.raises(ValueError, match="unknown target room"):
        SiteService._validate_preview(invalid)

    invalid = deepcopy(preview)
    connector = invalid["levels"][0]["connectors"][0]
    position = connector["position"]
    cell = next(
        cell
        for cell in invalid["levels"][0]["layout"]["cells"]
        if cell["row"] == position["row"] and cell["col"] == position["col"]
    )
    cell["kind"] = "floor"
    with pytest.raises(ValueError, match="connector position"):
        SiteService._validate_preview(invalid)


def test_site_delete_removes_managed_locations_scenes_grids_and_region_poi(
    campaign_client: TestClient,
) -> None:
    campaign_id = campaign_client.post(
        "/api/v1/campaigns", json={"name": "站点安全删除验收"}
    ).json()["id"]
    preview = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/sites/generate/preview",
        json=_request(maximum_levels=2),
    ).json()
    site = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/sites/generate/confirm",
        headers={"X-Request-ID": "site-delete-safety"},
        json={"preview": preview},
    ).json()
    room_location_id = site["levels"][0]["rooms"][0]["location_id"]
    child = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/locations",
        json={
            "name": "房间内的临时夹层",
            "parent_location_id": room_location_id,
            "depth": 6,
        },
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]
    scene = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes",
        json={"name": "夹层临时场景", "location_id": child_id},
    )
    assert scene.status_code == 201, scene.text
    scene_id = scene.json()["id"]
    grid = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/scenes/{scene_id}/grid",
        json={"width": 4, "height": 4, "cell_size_ft": 5},
    )
    assert grid.status_code == 201, grid.text

    generic_delete = campaign_client.delete(
        f"/api/v1/campaigns/{campaign_id}/locations/{site['location_id']}",
        params={"version": 1},
    )
    assert generic_delete.status_code == 400
    assert "adventure site endpoint" in generic_delete.text

    deleted = campaign_client.delete(
        f"/api/v1/campaigns/{campaign_id}/sites/{site['id']}",
        params={"version": site["version"]},
        headers={"X-Request-ID": "site-delete-safety-confirm"},
    )
    assert deleted.status_code == 204, deleted.text
    assert (
        campaign_client.get(f"/api/v1/campaigns/{campaign_id}/sites/{site['id']}").status_code
        == 404
    )
    maps = campaign_client.get(f"/api/v1/campaigns/{campaign_id}/region-maps").json()["region_maps"]
    assert maps[0]["map_json"]["pois"] == []
    assert maps[0]["map_json"]["roads"] == []

    engine = campaign_client.app.state.database_engine
    with Session(engine) as session:
        assert session.get(Location, child_id) is None
        assert session.get(Scene, scene_id) is None
        assert (
            session.scalar(
                select(func.count()).select_from(SceneGrid).where(SceneGrid.scene_id == scene_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Location)
                .where(Location.campaign_id == campaign_id, Location.parent_location_id.is_(None))
            )
            == 1
        )  # the region root remains; the generated site tree does not


def test_concurrent_site_confirm_with_same_request_is_gracefully_idempotent(
    campaign_client: TestClient,
) -> None:
    campaign_id = campaign_client.post(
        "/api/v1/campaigns", json={"name": "并发站点确认验收"}
    ).json()["id"]
    preview = generate_site(_request(maximum_levels=2))
    service = SiteService(campaign_client.app.state.database_engine)
    barrier = Barrier(2)
    lock = Lock()
    results: list[str] = []
    failures: list[BaseException] = []

    def confirm() -> None:
        try:
            barrier.wait()
            result = service.confirm(
                campaign_id,
                preview,
                request_id="site-concurrent-same-request",
            )
            with lock:
                results.append(str(result["id"]))
        except BaseException as exc:  # pragma: no cover - assertion reports details
            with lock:
                failures.append(exc)

    threads = [Thread(target=confirm), Thread(target=confirm)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert failures == []
    assert len(results) == 2
    assert len(set(results)) == 1
    with Session(campaign_client.app.state.database_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AdventureSite)
                .where(
                    AdventureSite.campaign_id == campaign_id,
                    AdventureSite.generation_request_id == "site-concurrent-same-request",
                )
            )
            == 1
        )


def test_concurrent_distinct_sites_preserve_both_region_pois(
    campaign_client: TestClient,
) -> None:
    campaign_id = campaign_client.post(
        "/api/v1/campaigns", json={"name": "并发区域地图验收"}
    ).json()["id"]
    previews = [
        generate_site(_request(name="东翼塔楼", maximum_levels=1, seed=7001)),
        generate_site(_request(name="西翼地窖", maximum_levels=1, seed=7002)),
    ]
    service = SiteService(campaign_client.app.state.database_engine)
    barrier = Barrier(2)
    lock = Lock()
    failures: list[BaseException] = []

    def confirm(index: int) -> None:
        try:
            barrier.wait()
            service.confirm(
                campaign_id,
                previews[index],
                request_id=f"site-concurrent-distinct-{index}",
            )
        except BaseException as exc:  # pragma: no cover - assertion reports details
            with lock:
                failures.append(exc)

    threads = [Thread(target=confirm, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert failures == []
    sites = service.list_sites(campaign_id)
    maps = service.list_region_maps(campaign_id)
    assert len(sites) == 2
    assert len(maps) == 1
    assert {poi["site_id"] for poi in maps[0]["map_json"]["pois"]} == {site["id"] for site in sites}
