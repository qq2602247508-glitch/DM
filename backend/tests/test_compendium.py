from __future__ import annotations

from fastapi.testclient import TestClient

from dnd_dm_assistant.application.official_compendium import _monster_actions
from dnd_dm_assistant.application.rule_block_compiler import compile_rule_blocks_dict


def test_monster_actions_keep_action_economy_and_recharge_metadata() -> None:
    text = """
动作
多重攻击。该生物进行两次爪击。
爪击。近战攻击检定：+7，触及5尺，命中造成（2d6+4）挥砍伤害。
火焰吐息（充能 5-6）。锥形区域内进行DC 15的敏捷豁免，失败受到（8d6）火焰伤害，成功减半。
反应
借机攻击。当一个生物离开该生物的近战范围时，该生物进行一次近战攻击。
护体反应。当该生物被攻击命中时，它进行一次反击。
传奇动作
该生物每轮可以进行3个传奇动作。
尾击。消耗1个传奇动作，触及10尺，命中：受到（2d8）钝击伤害。
巢穴动作
地面震动。每个生物进行DC 14的力量豁免，失败倒地。
"""

    actions = _monster_actions(text)

    by_name = {item["name"]: item for item in actions}
    assert by_name["多重攻击"]["action_type"] == "action"
    assert by_name["多重攻击"]["multiattack"] is True
    assert by_name["多重攻击"]["multiattack_count"] == 2
    assert by_name["多重攻击"]["multiattack_components"] == [
        {"action_name": "爪击", "count": 2}
    ]
    assert by_name["火焰吐息"]["recharge"] == {"minimum": 5, "maximum": 6}
    assert by_name["借机攻击"]["action_type"] == "reaction"
    assert by_name["借机攻击"]["reaction_event"] == "leaves_reach"
    assert by_name["护体反应"]["reaction_event"] == "hit_by_attack"
    assert by_name["尾击"]["action_type"] == "legendary_action"
    assert by_name["尾击"]["legendary_cost"] == 1
    assert by_name["尾击"]["legendary_pool_max"] == 3
    assert by_name["地面震动"]["action_type"] == "lair_action"


def test_monster_action_parser_keeps_area_and_exact_condition_duration() -> None:
    actions = _monster_actions(
        """
动作
心灵震爆（充能5-6）。该生物发出60尺锥形能量；范围内每个生物进行DC15的智力豁免，失败受到（6d8+4）心灵伤害并震慑，直到该生物的下个回合结束，成功伤害减半。
"""
    )

    blast = actions[0]
    assert blast["area_shape"] == "cone"
    assert blast["area_size_ft"] == 60
    assert blast["affects_multiple_targets"] is True
    assert blast["conditions_on_failure"] == ["震慑"]
    assert blast["condition_duration"] == "actor_turn_end"


def test_monster_action_parser_normalizes_digit_spacing_before_area_compilation() -> None:
    actions = _monster_actions(
        """
动作
恶咒爆裂Hex Blast（充能5~6）。恐怖之物释放出3 0 尺锥状暗蚀能量。
每个区域内的生物必须进行DC 15 的体质豁免，失败的生物受到4 5 （7d 12 ）暗蚀伤害，
成功的生物则受到一半伤害。
"""
    )

    blast = actions[0]
    assert blast["area_shape"] == "cone"
    assert blast["area_size_ft"] == 30
    plan = compile_rule_blocks_dict(
        {
            "name": blast["name"],
            **blast,
            "resolution_kind": "damage",
        },
        source_kind="monster_action",
    )
    assert plan["automation_confidence"] in {"exact", "partial", "manual"}
    target = next(block for block in plan["blocks"] if block["kind"] == "target")
    assert target["shape"] == "cone"
    assert target["size_ft"] == 30

    line_plan = compile_rule_blocks_dict(
        {
            "name": "棘丛喷发",
            "area_shape": "line",
            "area_size_ft": 90,
            "description": "90 尺长、1 0 尺宽的线状区域。",
        },
        source_kind="monster_action",
    )
    line_target = next(block for block in line_plan["blocks"] if block["kind"] == "target")
    assert line_target["size_ft"] == 90
    assert line_target["width_ft"] == 10


def test_official_compendium_filters_before_pagination_and_only_returns_atoms(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "官方图鉴质量验收团", "allow_legacy": True},
    ).json()
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
    assert all(item["filters_json"]["category"] != "adventuring_gear" for item in equipment)
    assert any(item["filters_json"]["item_kind"] == "magic_equipment" for item in equipment)

    magic_items = campaign_client.get(
        f"{root}?entry_type=equipment&category=wondrous&rarity=传说&page_size=100"
    ).json()
    assert magic_items["items"]
    assert all(item["name"] != "传说" for item in magic_items["items"])
    assert all(item["name"] != "神器" for item in magic_items["items"])
    assert all(
        item["filters_json"]["category"] == "wondrous" and item["filters_json"]["rarity"] == "传说"
        for item in magic_items["items"]
    )
    magic_weapons = campaign_client.get(
        f"{root}?entry_type=equipment&category=weapon&text=魔法武器&page_size=100"
    ).json()["items"]
    assert {(item["name"], item["filters_json"]["rarity"]) for item in magic_weapons} >= {
        ("魔法武器 +1", "非普通"),
        ("魔法武器 +2", "珍稀"),
        ("魔法武器 +3", "极珍稀"),
    }
    universal_solvent = campaign_client.get(
        f"{root}?entry_type=equipment&text=万溶剂&page_size=100"
    ).json()["items"]
    assert universal_solvent
    assert all("乳白" in item["description"] for item in universal_solvent)
    assert all("卡牌通常存放" not in item["description"] for item in universal_solvent)
    mundane_items = campaign_client.get(f"{root}?entry_type=item&page_size=100").json()["items"]
    assert mundane_items
    assert all(item["filters_json"]["item_kind"] == "mundane_item" for item in mundane_items)
    assert all(item["filters_json"]["item_function"] for item in mundane_items)
    mundane_names = {item["name"] for item in mundane_items}
    assert not {
        "一环卷轴",
        "戏法卷轴",
        "治疗药水",
        "强酸",
        "炽火胶",
        "基础毒药",
        "圣水",
    } & mundane_names
    for combat_consumable in ("一环卷轴", "治疗药水", "强酸"):
        matches = campaign_client.get(
            f"{root}?entry_type=equipment&text={combat_consumable}&page_size=100"
        ).json()["items"]
        assert any(item["name"] == combat_consumable for item in matches)
        assert all(item["filters_json"]["item_function"] for item in matches)

    current_spells = campaign_client.get(
        f"{root}?entry_type=spell&sort_by=level&page_size=100"
    ).json()
    legacy_spells = campaign_client.get(
        f"{root}?entry_type=spell&include_legacy=true&page_size=100"
    ).json()
    assert all(
        item["filters_json"]["edition"] in {"2024", "2025"}
        for item in current_spells["items"]
    )
    assert legacy_spells["total"] > current_spells["total"]
    assert [
        item["filters_json"]["spell_level"] for item in current_spells["items"]
    ] == sorted(item["filters_json"]["spell_level"] for item in current_spells["items"])

    class_entries = campaign_client.get(
        f"{root}?entry_type=feature&content_type=classes&sort_by=class&page_size=100"
    ).json()["items"]
    assert class_entries
    assert all(item["filters_json"]["class_name"] for item in class_entries)
    assert all(
        item["filters_json"]["feature_kind"] in {"class", "subclass"}
        for item in class_entries
    )


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


def test_official_monster_defenses_are_visible_as_typed_rule_blocks(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "伤害类型验收团", "allow_legacy": True},
    ).json()
    root = f"/api/v1/campaigns/{campaign['id']}/compendium"
    response = campaign_client.get(
        f"{root}?entry_type=monster&text=毒虫罗斯魔&include_legacy=true&page_size=100"
    )
    assert response.status_code == 200, response.text
    entry = next(item for item in response.json()["items"] if item["name"] == "毒虫罗斯魔")
    rules = entry["rules_json"]
    assert set(rules["damage_resistances"]) >= {"bludgeoning", "cold", "fire"}
    assert set(rules["damage_immunities"]) >= {"acid", "poison"}
    plan = rules["rule_plan"]
    assert plan["source_kind"] == "monster"
    assert {block["operation"] for block in plan["blocks"] if block["kind"] == "defense"} == {
        "resistance",
        "immunity",
    }


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
    rewards = [item for level in preview["levels"] for item in level["reward_plan"]]
    assert any(item["source_kind"] == "official" for item in rewards)
    assert all(item["name"] != "与队伍环级相符的法术卷轴" for item in rewards)
    assert all(item["name"] != "精制武器或护甲材料" for item in rewards)


def test_sahuagin_site_prefers_theme_matching_official_reward_atoms(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "渔人战利品验收团"}).json()
    root = f"/api/v1/campaigns/{campaign['id']}"
    preview = campaign_client.post(
        f"{root}/sites/generate/preview",
        json={
            "site_type": "dungeon",
            "name": "潮鳞巢穴",
            "brief": "蓝色潮湿的渔人地下城，全部由鲨华鱼人占据，有育卵池与潮汐祭坛",
            "region_path": "深水城/海区",
            "maximum_levels": 2,
            "rooms_min": 5,
            "rooms_max": 7,
            "party_level": 5,
            "party_size": 4,
            "starting_difficulty": "moderate",
            "difficulty_growth": 1,
            "monster_density": 70,
            "reward_rate": 1.2,
            "overall_scale": "large",
            "minimum_room_size": "medium",
            "maximum_room_size": "huge",
            "generate_npcs": True,
            "generate_monsters": True,
            "generate_loot": True,
            "seed": 20260729,
        },
    ).json()
    official_rewards = [
        reward
        for level in preview["levels"]
        for reward in level["reward_plan"]
        if reward.get("source_kind") == "official"
    ]
    assert official_rewards
    assert any(
        any(
            keyword in reward["name"]
            for keyword in ("水下", "水上", "水手", "海", "鱼", "珍珠", "三叉戟")
        )
        for reward in official_rewards
    )


def test_merchant_generation_uses_real_atoms_before_original_fallback(
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
    assert preview["summary"]["official_atoms"] == 4
    assert preview["summary"]["original_atoms"] == 0
    assert len({item["name"] for item in preview["stock"]}) == 4
    assert all("定制货品" not in item["name"] for item in preview["stock"])
    assert all(item["price_copper"] > 0 for item in preview["stock"])
    confirmed = campaign_client.post(
        f"{root}/merchants/generate/confirm",
        json={"preview": preview},
    )
    assert confirmed.status_code == 201, confirmed.text
    shops = campaign_client.get(f"{root}/merchants").json()["items"]
    assert len(shops) == 1
    assert shops[0]["name"] == "月灯杂货铺"
    assert len(shops[0]["stock"]) == 4
    originals = campaign_client.get(f"{root}/compendium?source_kind=original").json()
    assert originals["total"] == 0


def test_level_twelve_wizard_consumables_are_real_and_rerollable(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "消耗品商店团"}).json()
    root = f"/api/v1/campaigns/{campaign['id']}"
    wizard = campaign_client.post(
        f"{root}/characters",
        json={"name": "艾琳", "class_name": "法师", "level": 12, "hp": 58, "max_hp": 58},
    ).json()
    base = {
        "name": "规则图鉴商店",
        "brief": "为当前队伍提供实用冒险装备",
        "categories": ["consumable"],
        "item_tier": "common",
        "character_ids": [wizard["id"]],
        "stock_size": 12,
        "allow_original": True,
    }
    first = campaign_client.post(
        f"{root}/merchants/generate/preview", json={**base, "seed": 17}
    ).json()
    second = campaign_client.post(
        f"{root}/merchants/generate/preview", json={**base, "seed": 23}
    ).json()
    assert first["summary"]["official_atoms"] == 12
    assert first["summary"]["original_atoms"] == 0
    assert len({item["name"] for item in first["stock"]}) == 12
    assert all("定制货品" not in item["name"] for item in first["stock"])
    assert {item["name"] for item in first["stock"]} != {
        item["name"] for item in second["stock"]
    }
