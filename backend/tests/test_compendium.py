from __future__ import annotations

from fastapi.testclient import TestClient


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
    inventory = campaign_client.get(
        f"{root}/items?owner_character_id={character['id']}"
    ).json()["items"]
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
    participants = campaign_client.get(
        f"{root}/scenes/{scene['id']}/participants"
    ).json()["items"]
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
        max(
            room["bounds"]["width"] * room["bounds"]["height"]
            for room in level["rooms"]
        )
        >= 64
        for level in preview["levels"]
    )
    assert all(level["monster_plan"] for level in preview["levels"])
    assert all(level["npc_plan"] for level in preview["levels"])
    assert all(level["reward_plan"] for level in preview["levels"])
    loot_names = {
        item["name"] for level in preview["levels"] for item in level["reward_plan"]
    }
    assert "与队伍环级相符的法术卷轴" in loot_names
    assert "精制武器或护甲材料" in loot_names
