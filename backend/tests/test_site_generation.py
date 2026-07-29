from __future__ import annotations

from copy import deepcopy
from threading import Barrier, Lock, Thread
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.site_generation import generate_site, layout_is_connected
from dnd_dm_assistant.domain.site_theme import compile_theme
from dnd_dm_assistant.infrastructure.database.models import (
    AdventureSite,
    Location,
    Scene,
    SceneGrid,
    SceneObject,
    SceneParticipant,
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


def test_site_generator_uses_fresh_random_seed_unless_dm_locks_one() -> None:
    random_request = _request()
    random_request.pop("seed")
    first = generate_site(random_request)
    second = generate_site(random_request)
    assert first["site"]["seed"] != second["site"]["seed"]

    locked = _request(seed=771122)
    assert generate_site(locked) == generate_site(locked)


def test_fungal_prompt_retrieves_official_myconids_from_compendium(
    campaign_client: TestClient,
) -> None:
    campaign_id = campaign_client.post(
        "/api/v1/campaigns", json={"name": "蕈人图鉴检索验收"}
    ).json()["id"]
    response = campaign_client.post(
        f"/api/v1/campaigns/{campaign_id}/sites/generate/preview",
        json=_request(
            name="蕈人幽穴",
            brief="藏在深林的地下城，充满了蕈人相关怪物",
            maximum_levels=2,
            seed=12345,
        ),
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["site"]["theme"] == "fungal"
    monsters = [monster for level in preview["levels"] for monster in level["monster_plan"]]
    assert monsters
    assert all(monster["source"] == "official_compendium" for monster in monsters)
    assert all(monster["compendium_entry_id"] for monster in monsters)
    assert all("蕈人" in monster["name"] for monster in monsters)


def test_sahuagin_prompt_drives_rooms_palette_monsters_and_loot() -> None:
    preview = generate_site(
        _request(
            name="潮鳞巢穴",
            brief="蓝色潮湿的渔人地下城，全部由鲨华鱼人占据，有育卵池与潮汐祭坛",
            maximum_levels=3,
            party_level=8,
            rooms_min=6,
            rooms_max=8,
            seed=74013,
        )
    )
    assert preview["site"]["theme"] == "sahuagin"
    assert preview["site"]["theme_profile"]["palette"] == "ocean"
    room_names = {room["name"] for level in preview["levels"] for room in level["rooms"]}
    assert {"潮门入口", "育卵池", "珊瑚藏宝室"} & room_names
    monster_names = {
        monster["name"] for level in preview["levels"] for monster in level["monster_plan"]
    }
    assert monster_names
    assert monster_names <= {
        "鲨华鱼人",
        "鲨华祭司",
        "寻猎鲨",
        "鲨华女祭司",
        "鲨华鱼人男爵",
        "底栖魔鱼",
    }
    assert all(level["visual_theme"]["palette"] == "ocean" for level in preview["levels"])
    assert any(
        "潮汐" in reward["name"] or "鲨华" in reward["name"] or "珊瑚" in reward["name"]
        for level in preview["levels"]
        for reward in level["reward_plan"]
    )


@pytest.mark.parametrize(
    ("name", "brief", "theme", "palette", "expected_terms"),
    (
        (
            "沉没的绿鳞神庙",
            "剧毒沼泽与沉没神庙，蜥蜴人与孢子植物盘踞其中",
            "swamp",
            "toxic",
            {"毒雾", "孢子", "蜥蜴人"},
        ),
        (
            "紫水晶矿洞",
            "奥术晶体持续共鸣，矿道遍布巨大晶簇",
            "crystal",
            "crystal",
            {"晶", "奥术", "共鸣"},
        ),
        (
            "废弃矮人钟楼",
            "齿轮、蒸汽机关与失控自动机占据每一层",
            "clockwork",
            "brass",
            {"齿轮", "蒸汽", "机械"},
        ),
    ),
)
def test_semantic_theme_compiler_drives_distinct_dungeon_content(
    name: str,
    brief: str,
    theme: str,
    palette: str,
    expected_terms: set[str],
) -> None:
    preview = generate_site(
        _request(name=name, brief=brief, maximum_levels=2, rooms_min=7, rooms_max=8)
    )
    assert preview["site"]["theme"] == theme
    assert preview["site"]["theme_profile"]["palette"] == palette
    assert preview["site"]["theme_profile"]["source_kind"] == "preset"
    content = " ".join(
        [
            *(room["name"] for level in preview["levels"] for room in level["rooms"]),
            *(
                cell["label"]
                for level in preview["levels"]
                for cell in level["layout"]["cells"]
                if cell["kind"] == "cover"
            ),
            *preview["site"]["theme_profile"]["monster_queries"],
            *preview["site"]["theme_profile"]["loot_queries"],
        ]
    )
    assert sum(term in content for term in expected_terms) >= 2
    assert all(level["visual_theme"]["palette"] == palette for level in preview["levels"])


def test_unknown_theme_is_stable_compiled_and_never_generic_amber() -> None:
    text = "会唱歌的纸月迷宫，墨水河流记录每个来客遗忘的名字"
    descriptor = compile_theme(f"纸月迷宫 {text}")
    repeated = compile_theme(f"纸月迷宫 {text}")
    assert descriptor == repeated
    assert descriptor.theme_id.startswith("custom-")
    assert descriptor.source_kind == "compiled"
    assert descriptor.palette != "amber"
    assert descriptor.keywords
    preview = generate_site(
        _request(name="纸月迷宫", brief=text, maximum_levels=1, rooms_min=7, rooms_max=7)
    )
    assert preview["site"]["theme"] == descriptor.theme_id
    assert preview["site"]["theme_profile"]["source_kind"] == "compiled"
    assert preview["levels"][0]["visual_theme"]["palette"] == descriptor.palette
    assert any(descriptor.keywords[0] in room["name"] for room in preview["levels"][0]["rooms"])


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
    assert {"深水城", "海区", "低语矿坑", "地下城第 1 层", "污染入口"} <= names
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
        assert all(grid.layers_json.get("theme") for grid in grids)
        assert all(grid.layers_json.get("visual_theme") for grid in grids)
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

    first_level = site["levels"][0]
    with Session(engine) as session:
        scene = session.scalar(select(Scene).where(Scene.location_id == first_level["location_id"]))
        assert scene is not None
        monster_tokens = list(
            session.scalars(
                select(SceneToken).where(
                    SceneToken.scene_id == scene.id,
                    SceneToken.entity_type == "monster",
                )
            )
        )
        assert monster_tokens
        room_index = int(monster_tokens[0].metadata_json["room_index"])
        room_entity_ids = {
            token.entity_id
            for token in monster_tokens
            if int(token.metadata_json["room_index"]) == room_index
        }
        assert all(not token.visible for token in monster_tokens)
        scene_id = scene.id

    dm_grid = campaign_client.get(f"/api/v1/campaigns/{campaign_id}/scenes/{scene_id}/grid")
    assert dm_grid.status_code == 200, dm_grid.text
    assert room_entity_ids <= {token["entity_id"] for token in dm_grid.json()["tokens"]}

    revealed = campaign_client.put(
        f"/api/v1/campaigns/{campaign_id}/sites/{site['id']}"
        f"/levels/{first_level['level_index']}/rooms/{room_index}/visibility",
        json={"visible": True},
    )
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["visibility"] == "revealed"
    with Session(engine) as session:
        assert all(
            token.visible
            for token in session.scalars(
                select(SceneToken).where(
                    SceneToken.scene_id == scene_id,
                    SceneToken.entity_id.in_(room_entity_ids),
                )
            )
        )
        assert all(
            participant.visible
            for participant in session.scalars(
                select(SceneParticipant).where(
                    SceneParticipant.scene_id == scene_id,
                    SceneParticipant.entity_id.in_(room_entity_ids),
                )
            )
        )
    persisted = campaign_client.get(f"/api/v1/campaigns/{campaign_id}/sites/{site['id']}").json()
    room = next(
        room for room in persisted["levels"][0]["rooms"] if room["room_index"] == room_index
    )
    assert room["encounter_json"]["visibility"] == "revealed"

    hidden = campaign_client.put(
        f"/api/v1/campaigns/{campaign_id}/sites/{site['id']}"
        f"/levels/{first_level['level_index']}/rooms/{room_index}/visibility",
        json={"visible": False},
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["visibility"] == "hidden"

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
