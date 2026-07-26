from fastapi.testclient import TestClient


def test_two_groups_are_isolated_and_one_session_runs_end_to_end(
    campaign_client: TestClient,
) -> None:
    """Acceptance path: group -> prep atoms -> scene -> combat -> XP -> story."""
    group_a = campaign_client.post(
        "/api/v1/campaigns", json={"name": "验收 A 团"}
    ).json()
    group_b = campaign_client.post(
        "/api/v1/campaigns", json={"name": "验收 B 团"}
    ).json()
    a = f"/api/v1/campaigns/{group_a['id']}"
    b = f"/api/v1/campaigns/{group_b['id']}"

    hero = campaign_client.post(
        f"{a}/characters",
        json={
            "name": "阿岚",
            "race": "人类",
            "class_name": "战士",
            "level": 1,
            "armor_class": 16,
            "hp": 12,
            "max_hp": 12,
            "ability_scores": {"strength": 16, "dexterity": 12},
        },
    ).json()
    campaign_client.post(
        f"{b}/characters",
        json={"name": "贝雅", "class_name": "法师", "hp": 7, "max_hp": 7},
    )
    assert [row["name"] for row in campaign_client.get(f"{a}/characters").json()["items"]] == [
        "阿岚"
    ]
    assert [row["name"] for row in campaign_client.get(f"{b}/characters").json()["items"]] == [
        "贝雅"
    ]
    assert campaign_client.get(f"{b}/characters/{hero['id']}").status_code == 404

    location = campaign_client.post(
        f"{a}/locations",
        json={"name": "被班恩信徒占领的旧教堂", "description": "D&D 5e 冒险地点"},
    ).json()
    npc = campaign_client.post(
        f"{a}/npcs",
        json={"name": "获救的侍僧", "hp": 6, "max_hp": 6, "armor_class": 10},
    ).json()
    monster = campaign_client.post(
        f"{a}/monsters",
        json={
            "name": "班恩邪教守卫",
            "armor_class": 12,
            "hp": 8,
            "max_hp": 8,
            "challenge_rating": "1/4",
        },
    ).json()
    quest = campaign_client.post(
        f"{a}/quests",
        json={
            "name": "肃清旧教堂",
            "description": "救出侍僧并击败守卫",
            "xp_reward": 50,
        },
    ).json()
    scene = campaign_client.post(
        f"{a}/scenes",
        json={"name": "教堂中殿", "location_id": location["id"]},
    ).json()
    for entity_type, entity_id in (
        ("character", hero["id"]),
        ("npc", npc["id"]),
        ("monster", monster["id"]),
    ):
        assert campaign_client.post(
            f"{a}/scenes/{scene['id']}/participants",
            json={"entity_type": entity_type, "entity_id": entity_id},
        ).status_code == 201

    started = campaign_client.post(f"{a}/scenes/{scene['id']}/start-combat", json={})
    assert started.status_code == 201
    combat = started.json()["combat"]
    combatants = campaign_client.get(
        f"{a}/combats/{combat['id']}/combatants"
    ).json()["items"]
    monster_fighter = next(row for row in combatants if row["entity_id"] == monster["id"])

    damage = campaign_client.post(
        f"{a}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "acceptance-defeat-monster"},
        json={
            "action_type": "damage",
            "target_combatant_id": monster_fighter["id"],
            "target_version": monster_fighter["version"],
            "amount": 20,
            "damage_type": "slashing",
        },
    )
    assert damage.status_code == 200
    assert damage.json()["target"]["hp"] == 0

    advanced = campaign_client.post(
        f"{a}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "acceptance-next-turn"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200
    ended = campaign_client.patch(
        f"{a}/combats/{combat['id']}",
        headers={"If-Match": f'"{advanced.json()["combat"]["version"]}"'},
        json={"status": "ended"},
    )
    assert ended.status_code == 200
    hero_fighter = next(row for row in combatants if row["entity_id"] == hero["id"])
    settlement_payload = {
        "combat_version": ended.json()["version"],
        "resolution_type": "victory",
        "xp_awards": [{"character_id": hero["id"], "xp": 50}],
        "writebacks": [
            {
                "combatant_id": hero_fighter["id"],
                "character_id": hero["id"],
                "write_hp": True,
                "write_conditions": True,
            }
        ],
    }
    preview = campaign_client.post(
        f"{a}/combats/{combat['id']}/settlement/preview", json=settlement_payload
    )
    assert preview.status_code == 200
    assert preview.json()["scene_entity_changes"][0]["before"]["hp"] == 8
    assert preview.json()["scene_entity_changes"][0]["after"]["hp"] == 0
    settled = campaign_client.post(
        f"{a}/combats/{combat['id']}/settlement/confirm",
        headers={"X-Request-ID": "acceptance-settlement"},
        json=settlement_payload,
    )
    assert settled.status_code == 200
    assert settled.json()["characters"][0]["experience"] == 50
    remaining_participants = campaign_client.get(
        f"{a}/scenes/{scene['id']}/participants"
    ).json()["items"]
    defeated = next(row for row in remaining_participants if row["entity_id"] == monster["id"])
    assert defeated["role"] == "defeated"
    assert defeated["entity"]["hp"] == 0
    monster_atom = next(
        row
        for row in campaign_client.get(f"{a}/monsters").json()["items"]
        if row["id"] == monster["id"]
    )
    assert monster_atom["hp"] == 0
    next_combat = campaign_client.post(
        f"{a}/scenes/{scene['id']}/start-combat",
        json={"name": "结算后再次进入战斗"},
    )
    assert next_combat.status_code == 201
    next_combatants = campaign_client.get(
        f"{a}/combats/{next_combat.json()['combat']['id']}/combatants"
    ).json()["items"]
    assert monster["id"] not in {row["entity_id"] for row in next_combatants}

    completed = campaign_client.patch(
        f"{a}/quests/{quest['id']}",
        headers={"If-Match": f'"{quest["version"]}"'},
        json={"status": "completed", "xp_awarded": True},
    )
    assert completed.status_code == 200
    progressed = campaign_client.post(
        f"{a}/events",
        json={
            "title": "战斗结束，继续推进",
            "event_type": "session_progress",
            "description": "侍僧指出地窖入口，跑团回到探索阶段。",
            "location_id": location["id"],
            "metadata_json": {"scene_id": scene["id"], "game_table": True},
        },
    )
    assert progressed.status_code == 201
    assert campaign_client.get(f"{b}/events").json()["items"] == []
