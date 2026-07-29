from __future__ import annotations

from fastapi.testclient import TestClient


def test_official_compendium_filters_before_pagination_and_only_returns_atoms(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "官方图鉴质量验收团"}).json()
    root = f"/api/v1/campaigns/{campaign['id']}/compendium"
    druid_page_one = campaign_client.get(
        f"{root}?entry_type=spell&class_name=德鲁伊&page=1&page_size=10"
    ).json()
    druid_page_two = campaign_client.get(
        f"{root}?entry_type=spell&class_name=德鲁伊&page=2&page_size=10"
    ).json()
    assert druid_page_one["total"] > 20
    assert len(druid_page_one["items"]) == 10
    assert len(druid_page_two["items"]) == 10
    assert all(
        "德鲁伊" in item["filters_json"]["classes"]
        for item in [*druid_page_one["items"], *druid_page_two["items"]]
    )
    class_facets = druid_page_one["facets"]["class_name"]
    assert "德鲁伊" in class_facets
    assert all("仪式" not in value and "TCE" not in value for value in class_facets)
    all_spell_names = {
        item["name"]
        for page in range(1, 30)
        for item in campaign_client.get(
            f"{root}?entry_type=spell&page={page}&page_size=100"
        ).json()["items"]
    }
    assert not {"牧师", "施法距离", "创作法术", "职业法术列表"} & all_spell_names
    detect_magic = campaign_client.get(
        f"{root}?entry_type=spell&text=侦测魔法&page_size=100"
    ).json()["items"]
    assert detect_magic
    assert all("侦测毒性和疾病" not in item["description"] for item in detect_magic)
    druid_level_two = campaign_client.get(
        f"{root}?entry_type=spell&class_name=德鲁伊&spell_level=2&page=2&page_size=10"
    ).json()
    assert druid_level_two["total"] > 10
    assert druid_level_two["items"]
    assert all(item["filters_json"]["spell_level"] == 2 for item in druid_level_two["items"])

    equipment = campaign_client.get(f"{root}?entry_type=equipment&page_size=100").json()["items"]
    assert equipment
    assert not {"财富", "词条", "饰品"} & {item["name"] for item in equipment}
    assert all(item["filters_json"]["atomic_item"] for item in equipment)
    assert all(
        item["filters_json"]["category"] in {"weapon", "armor", "shield"} for item in equipment
    )

    magic_items = campaign_client.get(
        f"{root}?entry_type=item&category=wondrous&rarity=传说&page_size=100"
    ).json()
    assert magic_items["items"]
    assert all(item["name"] != "传说" for item in magic_items["items"])
    assert all(item["name"] != "神器" for item in magic_items["items"])
    assert all(
        item["filters_json"]["category"] == "wondrous" and item["filters_json"]["rarity"] == "传说"
        for item in magic_items["items"]
    )
    magic_weapons = campaign_client.get(
        f"{root}?entry_type=item&category=weapon&text=魔法武器&page_size=100"
    ).json()["items"]
    assert {(item["name"], item["filters_json"]["rarity"]) for item in magic_weapons} >= {
        ("魔法武器 +1", "非普通"),
        ("魔法武器 +2", "珍稀"),
        ("魔法武器 +3", "极珍稀"),
    }
    universal_solvent = campaign_client.get(
        f"{root}?entry_type=item&text=万溶剂&page_size=100"
    ).json()["items"]
    assert universal_solvent
    assert all("乳白" in item["description"] for item in universal_solvent)
    assert all("卡牌通常存放" not in item["description"] for item in universal_solvent)


def test_generated_compendium_templates_are_reusable_instances(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "图鉴原子验收团"}).json()
    root = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{root}/characters",
        json={
            "name": "焰羽",
            "class_name": "法师",
            "level": 8,
            "hp": 42,
            "max_hp": 42,
        },
    ).json()
    scene = campaign_client.post(f"{root}/scenes", json={"name": "熔炉大厅"}).json()

    equipment_preview = campaign_client.post(
        f"{root}/compendium/generate/preview",
        json={
            "mode": "equipment_set",
            "entry_type": "equipment",
            "prompt": "火龙指甲锻造套装",
            "applicable_level": 8,
        },
    )
    assert equipment_preview.status_code == 200, equipment_preview.text
    preview = equipment_preview.json()
    assert len(preview["entries"]) == 3
    assert all("原创" in entry["tags"] for entry in preview["entries"])
    confirmed = campaign_client.post(
        f"{root}/compendium/generate/confirm",
        json={"preview": preview},
    )
    assert confirmed.status_code == 201, confirmed.text
    equipment = next(
        item for item in confirmed.json()["items"] if item["entry_type"] == "equipment"
    )
    granted = campaign_client.post(
        f"{root}/compendium/{equipment['id']}/instantiate",
        json={"target_type": "character", "target_id": character["id"]},
    )
    assert granted.status_code == 201, granted.text
    inventory = campaign_client.get(f"{root}/items?owner_character_id={character['id']}").json()[
        "items"
    ]
    assert any(item["name"] == equipment["name"] for item in inventory)

    monster_preview = campaign_client.post(
        f"{root}/compendium/generate/preview",
        json={
            "mode": "monster_family",
            "entry_type": "monster",
            "prompt": "灰烬蜥族",
            "applicable_level": 8,
        },
    ).json()
    monsters = campaign_client.post(
        f"{root}/compendium/generate/confirm",
        json={"preview": monster_preview},
    ).json()["items"]
    assert len(monsters) == 4
    arrival = campaign_client.post(
        f"{root}/compendium/{monsters[-1]['id']}/instantiate",
        json={"target_type": "scene", "target_id": scene["id"]},
    )
    assert arrival.status_code == 201, arrival.text
    participants = campaign_client.get(f"{root}/scenes/{scene['id']}/participants").json()["items"]
    assert any(item["entity_type"] == "monster" for item in participants)


def test_site_generation_can_derive_party_and_room_scale_from_characters(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "角色地下城验收团"}).json()
    root = f"/api/v1/campaigns/{campaign['id']}"
    wizard = campaign_client.post(
        f"{root}/characters",
        json={"name": "法师", "class_name": "法师", "level": 10, "hp": 50, "max_hp": 50},
    ).json()
    fighter = campaign_client.post(
        f"{root}/characters",
        json={"name": "战士", "class_name": "战士", "level": 8, "hp": 76, "max_hp": 76},
    ).json()
    response = campaign_client.post(
        f"{root}/sites/generate/preview",
        json={
            "site_type": "dungeon",
            "name": "龙爪熔炉",
            "brief": "火山地下城、锻炉、岩浆桥与火蜥蜴巢穴",
            "region_path": "深水城/山麓",
            "maximum_levels": 2,
            "rooms_min": 4,
            "rooms_max": 6,
            "party_level": 1,
            "party_size": 1,
            "character_ids": [wizard["id"], fighter["id"]],
            "starting_difficulty": "moderate",
            "difficulty_growth": 1,
            "monster_density": 70,
            "reward_rate": 1.5,
            "overall_scale": "large",
            "minimum_room_size": "medium",
            "maximum_room_size": "huge",
            "generate_npcs": True,
            "generate_monsters": True,
            "generate_loot": True,
            "seed": 20260729,
        },
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["site"]["party_size"] == 2
    assert preview["site"]["party_level"] == 9
    assert preview["site"]["character_ids"] == [wizard["id"], fighter["id"]]
    assert all(level["layout"]["width"] >= 60 for level in preview["levels"])
    assert all(
        max(room["bounds"]["width"] * room["bounds"]["height"] for room in level["rooms"]) >= 64
        for level in preview["levels"]
    )
    assert all(level["monster_plan"] for level in preview["levels"])
    assert all(level["npc_plan"] for level in preview["levels"])
    assert all(level["reward_plan"] for level in preview["levels"])
    loot_names = {item["name"] for level in preview["levels"] for item in level["reward_plan"]}
    assert "与队伍环级相符的法术卷轴" in loot_names
    assert "精制武器或护甲材料" in loot_names


def test_merchant_generation_creates_grouped_stock_and_original_atoms(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "商店验收团"}).json()
    root = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{root}/characters",
        json={"name": "伊奥", "class_name": "法师", "level": 5, "hp": 28, "max_hp": 28},
    ).json()
    location = campaign_client.post(
        f"{root}/locations", json={"name": "长桥市场", "depth": 1}
    ).json()
    scene = campaign_client.post(
        f"{root}/scenes",
        json={"name": "月灯杂货铺", "location_id": location["id"]},
    ).json()
    response = campaign_client.post(
        f"{root}/merchants/generate/preview",
        json={
            "name": "月灯杂货铺",
            "brief": "给五级法师准备的奥术远行补给",
            "location_id": location["id"],
            "scene_id": scene["id"],
            "categories": ["magic"],
            "item_tier": "uncommon",
            "character_ids": [character["id"]],
            "stock_size": 4,
            "allow_original": True,
        },
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert len(preview["stock"]) == 4
    assert preview["summary"]["original_atoms"] == 4
    confirmed = campaign_client.post(
        f"{root}/merchants/generate/confirm",
        json={"preview": preview},
    )
    assert confirmed.status_code == 201, confirmed.text
    shops = campaign_client.get(f"{root}/merchants").json()["items"]
    assert len(shops) == 1
    assert shops[0]["name"] == "月灯杂货铺"
    assert len(shops[0]["stock"]) == 4
    originals = campaign_client.get(
        f"{root}/compendium?source_kind=original&entry_type=item"
    ).json()
    assert originals["total"] >= 4
