from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from dnd_dm_assistant.infrastructure.database import combat_service


def test_summon_enters_initiative_once_and_keeps_controller_boundary(
    campaign_client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "召唤测试"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    hero = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "施法者",
            "ability_scores": {"dexterity": 16},
            "hp": 12,
            "max_hp": 12,
        },
    ).json()
    other = campaign_client.post(
        f"{base}/characters",
        json={"name": "另一位角色", "ability_scores": {"dexterity": 10}, "hp": 8, "max_hp": 8},
    ).json()
    monster = campaign_client.post(
        f"{base}/monsters",
        json={"name": "召唤来源怪物", "hp": 10, "max_hp": 10, "armor_class": 12},
    ).json()
    scene = campaign_client.post(f"{base}/scenes", json={"name": "召唤竞技场"}).json()
    grid = campaign_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 10, "height": 8, "cell_size_ft": 5, "mode": "combat", "layers_json": {}},
    )
    assert grid.status_code == 201
    for entity_type, entity_id in (("character", hero["id"]), ("monster", monster["id"])):
        assert campaign_client.post(
            f"{base}/scenes/{scene['id']}/participants",
            json={"entity_type": entity_type, "entity_id": entity_id},
        ).status_code == 201
    companion = campaign_client.post(
        f"{base}/companions",
        json={
            "owner_character_id": hero["id"],
            "name": "战斗魔宠",
            "companion_type": "summon",
            "template_json": {
                "ability_scores": {"dexterity": 14},
                "actions": [{"name": "撕咬", "damage": "1d6 piercing", "range": "5尺"}],
            },
            "hp": 7,
            "max_hp": 7,
            "armor_class": 13,
            "speed": 30,
        },
    ).json()
    other_companion = campaign_client.post(
        f"{base}/companions",
        json={
            "owner_character_id": other["id"],
            "name": "不属于你的召唤物",
            "companion_type": "summon",
            "hp": 4,
            "max_hp": 4,
            "armor_class": 10,
            "speed": 30,
        },
    ).json()
    player_companion = campaign_client.post(
        f"{base}/companions",
        json={
            "owner_character_id": hero["id"],
            "name": "玩家可控召唤物",
            "companion_type": "summon",
            "hp": 5,
            "max_hp": 5,
            "armor_class": 11,
            "speed": 30,
        },
    ).json()
    started = campaign_client.post(f"{base}/scenes/{scene['id']}/start-combat", json={})
    assert started.status_code == 201
    combat = started.json()["combat"]
    combat_id = combat["id"]
    initiative_rolls: list[int] = []

    def fixed_randbelow(upper: int) -> int:
        initiative_rolls.append(upper)
        return 9

    monkeypatch.setattr(combat_service.secrets, "randbelow", fixed_randbelow)

    dm_summon = campaign_client.post(
        f"{base}/combats/{combat_id}/summons",
        headers={"X-Request-ID": "summon-dm-1"},
        json={
            "companion_id": companion["id"],
            "controller": "dm",
            "disposition": "enemy",
            "initiative_mode": "independent",
        },
    )
    assert dm_summon.status_code == 200, dm_summon.text
    dm_fighter = dm_summon.json()["combatant"]
    assert dm_fighter["entity_type"] == "companion"
    assert dm_fighter["snapshot_json"]["controller"] == "dm"
    assert dm_fighter["snapshot_json"]["disposition"] == "enemy"
    assert dm_fighter["initiative"] == 12
    assert dm_fighter["snapshot_json"]["initiative_mode"] == "independent"
    assert dm_summon.json()["action"]["result_json"]["initiative_roll"] == 10
    assert initiative_rolls == [20]

    repeated = campaign_client.post(
        f"{base}/combats/{combat_id}/summons",
        headers={"X-Request-ID": "summon-dm-1"},
        json={
            "companion_id": companion["id"],
            "controller": "dm",
            "disposition": "enemy",
            "initiative_mode": "independent",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["combatant"]["id"] == dm_fighter["id"]
    assert len(
        [
            row
            for row in campaign_client.get(f"{base}/combats/{combat_id}/combatants").json()["items"]
            if row["entity_type"] == "companion"
        ]
    ) == 1

    rows = campaign_client.get(
        f"{base}/combats/{combat_id}/combatants"
    ).json()["items"]
    source = next(
        row
        for row in rows
        if row["entity_type"] == "monster" and row["entity_id"] == monster["id"]
    )
    before_shared = campaign_client.get(f"{base}/combats/{combat_id}").json()
    before_order = sorted(
        rows,
        key=lambda row: (-row["initiative"], row["created_at"], row["id"]),
    )
    active_id = before_order[before_shared["current_turn_index"]]["id"]
    shared = campaign_client.post(
        f"{base}/combats/{combat_id}/summons",
        headers={"X-Request-ID": "summon-shared-1"},
        json={
            "name": "共享先攻灵体",
            "controller": "dm",
            "source_combatant_id": source["id"],
            "initiative_mode": "shared_with_source",
            "hp": 6,
            "max_hp": 6,
            "armor_class": 12,
            "speed_ft": 30,
        },
    )
    assert shared.status_code == 200, shared.text
    shared_payload = shared.json()
    assert shared_payload["combatant"]["initiative"] == source["initiative"]
    assert (
        shared_payload["combatant"]["snapshot_json"]["initiative_mode"]
        == "shared_with_source"
    )
    assert shared_payload["action"]["result_json"]["initiative_roll"] is None
    assert shared_payload["action"]["result_json"]["dexterity_modifier"] is None
    assert initiative_rolls == [20]
    repeated_shared = campaign_client.post(
        f"{base}/combats/{combat_id}/summons",
        headers={"X-Request-ID": "summon-shared-1"},
        json={
            "name": "共享先攻灵体",
            "controller": "dm",
            "source_combatant_id": source["id"],
            "initiative_mode": "shared_with_source",
            "hp": 6,
            "max_hp": 6,
            "armor_class": 12,
            "speed_ft": 30,
        },
    )
    assert repeated_shared.status_code == 200, repeated_shared.text
    assert repeated_shared.json()["already_applied"] is True
    assert repeated_shared.json()["combatant"]["id"] == shared_payload["combatant"]["id"]
    assert initiative_rolls == [20]

    after_shared = campaign_client.get(f"{base}/combats/{combat_id}").json()
    after_rows = campaign_client.get(
        f"{base}/combats/{combat_id}/combatants"
    ).json()["items"]
    after_order = sorted(
        after_rows,
        key=lambda row: (-row["initiative"], row["created_at"], row["id"]),
    )
    assert after_order[after_shared["current_turn_index"]]["id"] == active_id

    count_before_rejections = len(after_rows)
    version_before_rejections = after_shared["version"]
    missing_source = campaign_client.post(
        f"{base}/combats/{combat_id}/summons",
        headers={"X-Request-ID": "summon-shared-no-source"},
        json={
            "name": "没有来源的共享召唤",
            "initiative_mode": "shared_with_source",
            "hp": 4,
            "max_hp": 4,
            "armor_class": 10,
            "speed_ft": 30,
        },
    )
    assert missing_source.status_code == 400
    assert "必须提供当前战斗中的来源单位" in missing_source.text

    not_applicable = campaign_client.post(
        f"{base}/combats/{combat_id}/summons",
        headers={"X-Request-ID": "summon-not-applicable"},
        json={
            "name": "非战斗召唤效果",
            "initiative_mode": "not_applicable",
            "hp": 1,
            "max_hp": 1,
            "armor_class": 10,
            "speed_ft": 0,
        },
    )
    assert not_applicable.status_code == 400
    assert "不能加入战斗" in not_applicable.text
    assert len(
        campaign_client.get(f"{base}/combats/{combat_id}/combatants").json()["items"]
    ) == count_before_rejections
    assert (
        campaign_client.get(f"{base}/combats/{combat_id}").json()["version"]
        == version_before_rejections
    )
    assert initiative_rolls == [20]
    combat = campaign_client.get(f"{base}/combats/{combat_id}").json()

    # Move the active turn to the owner before exercising player-controlled
    # summon validation.  The service keeps the active combatant identity
    # stable even when a new initiative card is inserted.
    for _ in range(10):
        rows = campaign_client.get(f"{base}/combats/{combat_id}/combatants").json()["items"]
        ordered = sorted(rows, key=lambda row: (-row["initiative"], row["created_at"], row["id"]))
        active = ordered[combat["current_turn_index"]]
        if active["entity_type"] == "character" and active["entity_id"] == hero["id"]:
            break
        advanced = campaign_client.post(
            f"{base}/combats/{combat_id}/turns/advance",
            headers={"X-Request-ID": f"summon-advance-{_}"},
            json={"combat_version": combat["version"]},
        )
        assert advanced.status_code == 200, advanced.text
        combat = advanced.json()["combat"]
    else:
        raise AssertionError("test could not reach the owner turn")

    player_summon = campaign_client.post(
        f"{base}/combats/{combat_id}/summons",
        headers={"X-Request-ID": "summon-player-1"},
        json={
            "companion_id": player_companion["id"],
            "controller": "player",
            "owner_character_id": hero["id"],
            "source_combatant_id": active["id"],
            "disposition": "ally",
        },
    )
    assert player_summon.status_code == 200, player_summon.text
    player_fighter = player_summon.json()["combatant"]
    assert player_fighter["snapshot_json"]["controller"] == "player"
    assert player_fighter["snapshot_json"]["owner_character_id"] == hero["id"]
    assert player_fighter["snapshot_json"]["disposition"] == "ally"
    assert player_fighter["snapshot_json"]["initiative_mode"] == "independent"
    assert initiative_rolls == [20, 20]

    unauthorized = campaign_client.post(
        f"{base}/combats/{combat_id}/summons",
        headers={"X-Request-ID": "summon-player-other-owner"},
        json={
            "companion_id": other_companion["id"],
            "controller": "player",
            "owner_character_id": other["id"],
            "source_combatant_id": active["id"],
            "disposition": "ally",
        },
    )
    assert unauthorized.status_code == 400
    assert "替其他玩家控制" in unauthorized.text


def test_player_summon_uses_initiative_mode_from_rule_block(
    campaign_client: TestClient,
) -> None:
    def summon_plan(
        name: str,
        initiative_mode: str,
        enters_combat: bool,
        *,
        count_expression: str | None = None,
    ) -> dict:
        block = {
            "id": "summon-0",
            "kind": "summon",
            "creature_ref": name,
            "count": 1,
            "controller": "caster",
            "enters_combat": enters_combat,
            "initiative_mode": initiative_mode,
        }
        if count_expression is not None:
            block.pop("count")
            block["count_expression"] = count_expression
        return {
            "schema_version": "1.0",
            "source_kind": "action",
            "source_name": name,
            "blocks": [block],
            "root_block_ids": ["summon-0"],
            "automation_confidence": "exact",
            "automation_ready": True,
            "unresolved_reasons": [],
            "warnings": [],
        }

    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "玩家召唤先攻模式"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    hero = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "召唤师",
            "ability_scores": {"dexterity": 12},
            "hp": 10,
            "max_hp": 10,
            "actions": [
                {
                    "name": "非战斗召唤",
                    "rule_plan": summon_plan(
                        "非战斗召唤", "not_applicable", False
                    ),
                },
                {
                    "name": "共享先攻召唤",
                    "rule_plan": summon_plan(
                        "共享先攻召唤", "shared_with_source", True
                    ),
                },
                {
                    "name": "离散数量召唤",
                    "rule_plan": summon_plan(
                        "离散数量召唤",
                        "independent",
                        True,
                        count_expression="1d6：2/4/8只（按法术表决定）",
                    ),
                },
            ],
        },
    ).json()
    noncombat_companion = campaign_client.post(
        f"{base}/companions",
        json={
            "owner_character_id": hero["id"],
            "name": "非战斗仆役",
            "companion_type": "summon",
            "hp": 1,
            "max_hp": 1,
            "armor_class": 10,
            "speed": 30,
        },
    ).json()
    shared_companion = campaign_client.post(
        f"{base}/companions",
        json={
            "owner_character_id": hero["id"],
            "name": "共享先攻伙伴",
            "companion_type": "summon",
            "hp": 5,
            "max_hp": 5,
            "armor_class": 12,
            "speed": 30,
        },
    ).json()
    scene = campaign_client.post(
        f"{base}/scenes", json={"name": "单人召唤场景"}
    ).json()
    assert campaign_client.post(
        f"{base}/scenes/{scene['id']}/participants",
        json={"entity_type": "character", "entity_id": hero["id"]},
    ).status_code == 201
    started = campaign_client.post(
        f"{base}/scenes/{scene['id']}/start-combat", json={}
    )
    assert started.status_code == 201, started.text
    combat = started.json()["combat"]
    source = campaign_client.get(
        f"{base}/combats/{combat['id']}/combatants"
    ).json()["items"][0]

    opened = campaign_client.post(f"{base}/player-room/open", json={"hours": 1})
    assert opened.status_code == 200, opened.text
    live_state = campaign_client.post(
        f"{base}/player-room/live-state",
        json={"scene_id": scene["id"], "combat_id": combat["id"]},
    )
    assert live_state.status_code == 200, live_state.text
    player = TestClient(campaign_client.app)
    try:
        joined = player.post(
            "/api/v1/player-room/join",
            json={"join_code": opened.json()["join_code"], "display_name": "召唤师玩家"},
        )
        assert joined.status_code == 201, joined.text
        bound = player.post(
            "/api/v1/player-room/me/bind-character",
            json={"character_id": hero["id"]},
        )
        assert bound.status_code == 200, bound.text

        rejected = player.post(
            "/api/v1/player-room/me/combat/summon",
            json={
                "companion_id": noncombat_companion["id"],
                "action_name": "非战斗召唤",
                "idempotency_key": "player-not-applicable",
            },
        )
        assert rejected.status_code == 400
        assert "不是独立战斗单位" in rejected.text
        invalid_count = player.post(
            "/api/v1/player-room/me/combat/summon",
            json={
                "companion_id": shared_companion["id"],
                "action_name": "离散数量召唤",
                "count": 3,
                "idempotency_key": "player-invalid-summon-count",
            },
        )
        assert invalid_count.status_code == 400
        assert "2、4、8" in invalid_count.text
        source_after_rejection = next(
            row
            for row in campaign_client.get(
                f"{base}/combats/{combat['id']}/combatants"
            ).json()["items"]
            if row["id"] == source["id"]
        )
        assert source_after_rejection["action_available"] is True

        shared = player.post(
            "/api/v1/player-room/me/combat/summon",
            json={
                "companion_id": shared_companion["id"],
                "action_name": "共享先攻召唤",
                "idempotency_key": "player-shared-summon",
            },
        )
        assert shared.status_code == 200, shared.text
        payload = shared.json()
        assert payload["combatant"]["initiative"] == source["initiative"]
        assert (
            payload["combatant"]["snapshot_json"]["initiative_mode"]
            == "shared_with_source"
        )
        assert payload["action"]["request_json"]["initiative_mode"] == "shared_with_source"
        assert payload["action"]["result_json"]["initiative_roll"] is None
    finally:
        player.close()


def test_dm_end_summon_is_idempotent_and_keeps_turn_on_successor(
    campaign_client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "召唤结束测试"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(
        f"{base}/combats",
        json={"name": "召唤结束先攻"},
    ).json()
    for name, initiative in (("先行动者", 20), ("后继行动者", 10)):
        created = campaign_client.post(
            f"{base}/combats/{combat['id']}/combatants",
            json={
                "display_name": name,
                "initiative": initiative,
                "hp": 10,
                "max_hp": 10,
            },
        )
        assert created.status_code == 201, created.text

    monkeypatch.setattr(combat_service.secrets, "randbelow", lambda _upper: 14)
    summoned = campaign_client.post(
        f"{base}/combats/{combat['id']}/summons",
        headers={"X-Request-ID": "summon-to-end"},
        json={
            "name": "短暂灵体",
            "initiative_mode": "independent",
            "hp": 5,
            "max_hp": 5,
            "armor_class": 12,
            "speed_ft": 30,
        },
    )
    assert summoned.status_code == 200, summoned.text
    summon = summoned.json()["combatant"]
    assert summon["initiative"] == 15

    current_combat = campaign_client.get(
        f"{base}/combats/{combat['id']}"
    ).json()
    advanced = campaign_client.post(
        f"{base}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "advance-to-summon"},
        json={"combat_version": current_combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["active_combatant"]["id"] == summon["id"]

    endpoint = f"{base}/combats/{combat['id']}/summons/{summon['id']}/end"
    ended = campaign_client.post(
        endpoint,
        headers={"X-Request-ID": "end-summon-once"},
        json={"summon_version": summon["version"] + 1, "reason": "DM 结束召唤"},
    )
    assert ended.status_code == 200, ended.text
    payload = ended.json()
    assert payload["summon"]["is_active"] is False
    assert payload["action"]["action_type"] == "end_summon"
    assert payload["action"]["dm_override"] is True
    assert payload["action"]["result_json"]["active_combatant_id"] is not None
    assert payload["already_applied"] is False

    active_rows = [
        row
        for row in campaign_client.get(
            f"{base}/combats/{combat['id']}/combatants"
        ).json()["items"]
        if row["is_active"]
    ]
    ordered = sorted(
        active_rows,
        key=lambda row: (-row["initiative"], row["created_at"], row["id"]),
    )
    assert ordered[payload["combat"]["current_turn_index"]]["display_name"] == "后继行动者"

    repeated = campaign_client.post(
        endpoint,
        headers={"X-Request-ID": "end-summon-once"},
        json={"summon_version": summon["version"] + 1, "reason": "DM 结束召唤"},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["already_applied"] is True
    assert repeated.json()["action"]["id"] == payload["action"]["id"]


def test_damage_to_zero_ends_summon_without_death_save(
    campaign_client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "召唤物归零测试"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(
        f"{base}/combats",
        json={"name": "召唤物生命归零"},
    ).json()
    actor_response = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "施法者",
            "initiative": 20,
            "hp": 10,
            "max_hp": 10,
        },
    )
    assert actor_response.status_code == 201, actor_response.text

    monkeypatch.setattr(combat_service.secrets, "randbelow", lambda _upper: 9)
    summoned = campaign_client.post(
        f"{base}/combats/{combat['id']}/summons",
        headers={"X-Request-ID": "summon-zero-hp"},
        json={
            "name": "脆弱灵体",
            "initiative_mode": "independent",
            "hp": 5,
            "max_hp": 5,
            "armor_class": 12,
            "speed_ft": 30,
        },
    )
    assert summoned.status_code == 200, summoned.text
    summon = summoned.json()["combatant"]

    confirmed = campaign_client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "damage-summon-to-zero"},
        json={
            "action_type": "damage",
            "target_combatant_id": summon["id"],
            "target_version": summon["version"],
            "amount": 5,
            "damage_type": "force",
            "action_cost": "none",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    payload = confirmed.json()
    assert payload["target"]["hp"] == 0
    assert payload["target"]["is_active"] is False
    assert payload["death_save"] is None
    assert payload["action"]["result_json"]["summon_ended"] is True
    assert payload["action"]["result_json"]["summon_end_reason"] == "生命值降至0"
    assert "召唤物生命归零，已离开战斗" in payload["action"]["summary"]

    active_rows = campaign_client.get(
        f"{base}/combats/{combat['id']}/combatants"
    ).json()["items"]
    assert all(
        row["id"] != summon["id"]
        for row in active_rows
        if row["is_active"]
    )


def test_summon_count_creates_independent_units_and_replays_them(
    campaign_client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "多单位召唤测试"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(
        f"{base}/combats", json={"name": "多单位召唤先攻"}
    ).json()
    monkeypatch.setattr(combat_service.secrets, "randbelow", lambda _upper: 9)
    request = {
        "name": "恶魔",
        "count": 3,
        "initiative_mode": "independent",
        "hp": 8,
        "max_hp": 8,
        "armor_class": 13,
        "speed_ft": 30,
    }
    created = campaign_client.post(
        f"{base}/combats/{combat['id']}/summons",
        headers={"X-Request-ID": "summon-count-three"},
        json=request,
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert len(payload["combatants"]) == 3
    assert [item["display_name"] for item in payload["combatants"]] == [
        "恶魔 1",
        "恶魔 2",
        "恶魔 3",
    ]
    assert payload["action"]["target_combatant_ids"] == [
        item["id"] for item in payload["combatants"]
    ]
    assert payload["action"]["result_json"]["count"] == 3
    assert payload["action"]["result_json"]["initiative_rolls"] == [10, 10, 10]
    repeated = campaign_client.post(
        f"{base}/combats/{combat['id']}/summons",
        headers={"X-Request-ID": "summon-count-three"},
        json=request,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["already_applied"] is True
    assert [item["id"] for item in repeated.json()["combatants"]] == [
        item["id"] for item in payload["combatants"]
    ]


def test_ending_linked_effect_ends_summon_and_repairs_turn_index(
    campaign_client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "召唤效果联动"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(
        f"{base}/combats",
        json={"name": "持续效果先攻"},
    ).json()
    regulars: list[dict] = []
    for name, initiative in (("施法者", 20), ("后继行动者", 10)):
        created = campaign_client.post(
            f"{base}/combats/{combat['id']}/combatants",
            json={
                "display_name": name,
                "initiative": initiative,
                "hp": 10,
                "max_hp": 10,
            },
        )
        assert created.status_code == 201, created.text
        regulars.append(created.json())

    monkeypatch.setattr(combat_service.secrets, "randbelow", lambda _upper: 14)
    summoned = campaign_client.post(
        f"{base}/combats/{combat['id']}/summons",
        headers={"X-Request-ID": "summon-with-effect"},
        json={
            "name": "持续灵体",
            "hp": 5,
            "max_hp": 5,
            "armor_class": 12,
            "speed_ft": 30,
        },
    )
    assert summoned.status_code == 200, summoned.text
    summon = summoned.json()["combatant"]
    current_combat = campaign_client.get(
        f"{base}/combats/{combat['id']}"
    ).json()
    advanced = campaign_client.post(
        f"{base}/combats/{combat['id']}/turns/advance",
        headers={"X-Request-ID": "advance-to-effect-summon"},
        json={"combat_version": current_combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    summon = advanced.json()["active_combatant"]

    effect = campaign_client.post(
        f"{base}/combats/{combat['id']}/effects/confirm",
        headers={"X-Request-ID": "link-summon-effect"},
        json={
            "target_combatant_id": regulars[0]["id"],
            "target_version": regulars[0]["version"],
            "name": "召唤维持",
            "effect_type": "buff",
            "duration_unit": "rounds",
            "duration_value": 2,
            "ends_summon_combatant_id": summon["id"],
            "summon_version": summon["version"],
        },
    )
    assert effect.status_code == 200, effect.text
    effect_payload = effect.json()
    assert (
        effect_payload["effect"]["details_json"]["ends_summon_combatant_id"]
        == summon["id"]
    )

    ended = campaign_client.post(
        f"{base}/combats/{combat['id']}/effects/{effect_payload['effect']['id']}/end",
        headers={"X-Request-ID": "end-linked-summon-effect"},
        json={
            "target_version": effect_payload["target"]["version"],
            "reason": "持续效果结束",
        },
    )
    assert ended.status_code == 200, ended.text
    payload = ended.json()
    assert payload["effect"]["status"] == "ended"
    assert [row["id"] for row in payload["ended_summons"]] == [summon["id"]]
    assert payload["ended_summons"][0]["is_active"] is False
    assert payload["action"]["result_json"]["ended_summon_ids"] == [summon["id"]]

    active_rows = [
        row
        for row in campaign_client.get(
            f"{base}/combats/{combat['id']}/combatants"
        ).json()["items"]
        if row["is_active"]
    ]
    ordered = sorted(
        active_rows,
        key=lambda row: (-row["initiative"], row["created_at"], row["id"]),
    )
    assert ordered[payload["combat"]["current_turn_index"]]["display_name"] == "后继行动者"

    repeated = campaign_client.post(
        f"{base}/combats/{combat['id']}/effects/{effect_payload['effect']['id']}/end",
        headers={"X-Request-ID": "end-linked-summon-effect"},
        json={
            "target_version": effect_payload["target"]["version"],
            "reason": "持续效果结束",
        },
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["action"]["id"] == payload["action"]["id"]


def test_summon_linked_duration_ends_summon_on_turn_advance(
    campaign_client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "召唤持续时间测试"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(
        f"{base}/combats",
        json={"name": "召唤持续时间先攻"},
    ).json()
    source = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={"display_name": "施法者", "initiative": 20, "hp": 10, "max_hp": 10},
    ).json()
    monkeypatch.setattr(combat_service.secrets, "randbelow", lambda _upper: 14)
    summoned = campaign_client.post(
        f"{base}/combats/{combat['id']}/summons",
        headers={"X-Request-ID": "summon-duration"},
        json={
            "name": "一轮灵体",
            "hp": 5,
            "max_hp": 5,
            "armor_class": 12,
            "speed_ft": 30,
        },
    )
    assert summoned.status_code == 200, summoned.text
    summon = summoned.json()["combatant"]

    effect = campaign_client.post(
        f"{base}/combats/{combat['id']}/effects/confirm",
        headers={"X-Request-ID": "summon-duration-effect"},
        json={
            "target_combatant_id": source["id"],
            "target_version": source["version"],
            "name": "一轮召唤维持",
            "effect_type": "buff",
            "duration_unit": "rounds",
            "duration_value": 1,
            "ends_summon_combatant_id": summon["id"],
            "summon_version": summon["version"],
        },
    )
    assert effect.status_code == 200, effect.text

    current = campaign_client.get(f"{base}/combats/{combat['id']}").json()
    ended_summons: list[str] = []
    for index in range(4):
        advanced = campaign_client.post(
            f"{base}/combats/{combat['id']}/turns/advance",
            headers={"X-Request-ID": f"summon-duration-advance-{index}"},
            json={"combat_version": current["version"]},
        )
        assert advanced.status_code == 200, advanced.text
        payload = advanced.json()
        ended_summons.extend(payload.get("ended_summons", []))
        current = payload["combat"]
        if ended_summons:
            break

    assert ended_summons and ended_summons[0]["id"] == summon["id"]
    assert ended_summons[0]["is_active"] is False
    assert current["current_turn_index"] >= 0
    assert payload["active_combatant"]["display_name"] == source["display_name"]


def test_concentration_source_zero_hp_immediately_ends_all_summons(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "专注来源归零清理"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(
        f"{base}/combats", json={"name": "专注召唤来源归零"}
    ).json()
    source = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "专注施法者",
            "entity_type": "character",
            "initiative": 20,
            "hp": 10,
            "max_hp": 10,
        },
    ).json()
    created = campaign_client.post(
        f"{base}/combats/{combat['id']}/summons",
        headers={"X-Request-ID": "concentration-summon-group"},
        json={
            "name": "专注灵体",
            "count": 2,
            "controller": "dm",
            "disposition": "ally",
            "source_combatant_id": source["id"],
            "initiative_mode": "shared_with_source",
            "hp": 6,
            "max_hp": 6,
            "armor_class": 12,
            "speed_ft": 30,
            "requires_concentration": True,
            "duration_unit": "until_removed",
        },
    )
    assert created.status_code == 200, created.text
    summon_ids = [row["id"] for row in created.json()["combatants"]]
    lifecycle_id = created.json()["action"]["result_json"]["lifecycle_effect_id"]

    refreshed_source = campaign_client.get(
        f"{base}/combats/{combat['id']}/combatants/{source['id']}"
    ).json()
    damaged = campaign_client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "concentration-source-zero"},
        json={
            "action_type": "damage",
            "target_combatant_id": source["id"],
            "target_version": refreshed_source["version"],
            "amount": 10,
            "damage_type": "force",
            "action_cost": "none",
        },
    )
    assert damaged.status_code == 200, damaged.text
    result = damaged.json()["action"]["result_json"]
    assert result["ended_predicated_effect_ids"] == [lifecycle_id]
    assert set(result["ended_predicated_summon_ids"]) == set(summon_ids)
    assert "concentration_prompts" not in damaged.json() or not damaged.json()[
        "concentration_prompts"
    ]

    rows = campaign_client.get(
        f"{base}/combats/{combat['id']}/combatants"
    ).json()["items"]
    assert all(not row["is_active"] for row in rows if row["id"] in summon_ids)
    active_rows = [row for row in rows if row["is_active"]]
    current = campaign_client.get(f"{base}/combats/{combat['id']}").json()
    ordered = sorted(
        active_rows,
        key=lambda row: (-row["initiative"], row["created_at"], row["id"]),
    )
    assert ordered[current["current_turn_index"]]["id"] == source["id"]

    effects = campaign_client.get(f"{base}/combats/{combat['id']}/effects").json()
    lifecycle = next(row for row in effects["items"] if row["id"] == lifecycle_id)
    assert lifecycle["status"] == "ended"
    assert lifecycle["end_reason"] == "状态来源陷入昏迷"


def test_direct_unconscious_edit_ends_concentration_summons(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns", json={"name": "直接昏迷清理"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = campaign_client.post(
        f"{base}/combats", json={"name": "DM 状态编辑清理"}
    ).json()
    source = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "被 DM 设置昏迷的施法者",
            "entity_type": "character",
            "initiative": 20,
            "hp": 10,
            "max_hp": 10,
            "conditions": [],
        },
    ).json()
    created = campaign_client.post(
        f"{base}/combats/{combat['id']}/summons",
        headers={"X-Request-ID": "direct-unconscious-summon"},
        json={
            "name": "状态编辑灵体",
            "count": 2,
            "controller": "dm",
            "disposition": "ally",
            "source_combatant_id": source["id"],
            "initiative_mode": "shared_with_source",
            "hp": 4,
            "max_hp": 4,
            "armor_class": 11,
            "speed_ft": 30,
            "requires_concentration": True,
            "duration_unit": "until_removed",
        },
    )
    assert created.status_code == 200, created.text
    summon_ids = [row["id"] for row in created.json()["combatants"]]
    lifecycle_id = created.json()["action"]["result_json"]["lifecycle_effect_id"]

    refreshed_source = campaign_client.get(
        f"{base}/combats/{combat['id']}/combatants/{source['id']}"
    ).json()
    patched = campaign_client.patch(
        f"{base}/combats/{combat['id']}/combatants/{source['id']}",
        headers={"X-Request-ID": "direct-unconscious-source"},
        json={
            "conditions": ["unconscious"],
            "version": refreshed_source["version"],
        },
    )
    assert patched.status_code == 200, patched.text
    assert "unconscious" in patched.json()["conditions"]

    rows = campaign_client.get(
        f"{base}/combats/{combat['id']}/combatants"
    ).json()["items"]
    assert all(not row["is_active"] for row in rows if row["id"] in summon_ids)
    effects = campaign_client.get(f"{base}/combats/{combat['id']}/effects").json()
    lifecycle = next(row for row in effects["items"] if row["id"] == lifecycle_id)
    assert lifecycle["status"] == "ended"
    assert lifecycle["end_reason"] == "状态来源陷入昏迷"
