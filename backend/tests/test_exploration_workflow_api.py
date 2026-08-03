from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.models import WorldClock


def _campaign(campaign_client: TestClient, name: str) -> tuple[dict[str, object], str]:
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": name, "current_time": "2026-08-01T12:00:00+00:00"},
    ).json()
    return campaign, f"/api/v1/campaigns/{campaign['id']}"


def _character(campaign_client: TestClient, base: str, name: str = "Aria") -> dict[str, object]:
    response = campaign_client.post(
        f"{base}/characters",
        json={"name": name, "hp": 12, "max_hp": 12},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _scene_with_grid(campaign_client: TestClient, base: str) -> dict[str, object]:
    scene_response = campaign_client.post(f"{base}/scenes", json={"name": "古井"})
    assert scene_response.status_code == 201, scene_response.text
    scene = scene_response.json()
    grid_response = campaign_client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 6, "height": 6, "mode": "exploration"},
    )
    assert grid_response.status_code == 201, grid_response.text
    return scene


def test_travel_preview_confirm_persists_encounter_and_world_clock(
    campaign_client: TestClient,
) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "旅行闭环", "current_time": "2026-08-01T12:00:00+00:00"},
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    start = campaign_client.post(f"{base}/locations", json={"name": "起点"}).json()
    destination = campaign_client.post(
        f"{base}/locations", json={"name": "终点"}
    ).json()
    patched = campaign_client.patch(
        base,
        json={"current_location_id": start["id"], "version": campaign["version"]},
    )
    assert patched.status_code == 200, patched.text

    body = {
        "to_location_id": destination["id"],
        "distance_miles": 3,
        "pace": "normal",
        "encounter": {
            "title": "路边的乌鸦",
            "outcome": "avoided",
            "summary": "队伍绕开了路边的可疑乌鸦群。",
            "visibility": "players",
        },
    }
    preview_response = campaign_client.post(f"{base}/travel/preview", json=body)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["duration_minutes"] == 60
    assert preview["requires_confirmation"] is True

    confirm_body = {
        **body,
        "preview_token": preview["preview_token"],
        "idempotency_key": "travel-encounter-0001",
    }
    confirmed = campaign_client.post(f"{base}/travel/confirm", json=confirm_body)
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["idempotent_replay"] is False
    assert result["location_id"] == destination["id"]
    assert result["world_time"].startswith("2026-08-01T13:00:00")
    assert result["travel_encounter"]["title"] == "路边的乌鸦"

    replay = campaign_client.post(f"{base}/travel/confirm", json=confirm_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True


def test_travel_preview_expires_when_origin_or_world_clock_changes(
    campaign_client: TestClient,
) -> None:
    campaign, base = _campaign(campaign_client, "旅行并发保护")
    start = campaign_client.post(f"{base}/locations", json={"name": "起点"}).json()
    other = campaign_client.post(f"{base}/locations", json={"name": "岔路"}).json()
    destination = campaign_client.post(f"{base}/locations", json={"name": "终点"}).json()
    moved = campaign_client.patch(
        base,
        json={"current_location_id": start["id"], "version": campaign["version"]},
    )
    assert moved.status_code == 200, moved.text

    body = {"to_location_id": destination["id"], "distance_miles": 3, "pace": "normal"}
    preview = campaign_client.post(f"{base}/travel/preview", json=body)
    assert preview.status_code == 200, preview.text

    relocated = campaign_client.patch(
        base,
        json={"current_location_id": other["id"], "version": moved.json()["version"]},
    )
    assert relocated.status_code == 200, relocated.text
    stale = campaign_client.post(
        f"{base}/travel/confirm",
        json={
            **body,
            "preview_token": preview.json()["preview_token"],
            "idempotency_key": "travel-stale-origin-0001",
        },
    )
    assert stale.status_code == 409, stale.text


def test_resolution_preview_does_not_materialize_or_advance_world_clock(
    campaign_client: TestClient,
) -> None:
    campaign, base = _campaign(campaign_client, "预览只读")
    character = _character(campaign_client, base)
    response = campaign_client.post(
        f"{base}/chases/preview",
        json={
            "title": "巷口追逐",
            "outcome": "success",
            "summary": "队伍暂时甩开追兵。",
            "minutes": 5,
            "character_effects": [
                {
                    "character_id": character["id"],
                    "character_version": character["version"],
                    "damage": 1,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["world_time"]["after"].startswith("2026-08-01T12:05:00")
    assert campaign_client.get(f"{base}/characters/{character['id']}").json()["hp"] == 12

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        clock = session.scalar(select(WorldClock).where(WorldClock.campaign_id == campaign["id"]))
        assert clock is None


def test_chase_confirmation_applies_effects_advances_time_and_replays_once(
    campaign_client: TestClient,
) -> None:
    _, base = _campaign(campaign_client, "追逐闭环")
    character = _character(campaign_client, base)
    body = {
        "title": "屋顶追逐",
        "outcome": "success",
        "target_successes": 2,
        "target_failures": 2,
        "minutes": 1,
        "summary": "阿莉娅越过烟囱，缩短了距离。",
        "visibility": "players",
        "character_effects": [
            {
                "character_id": character["id"],
                "character_version": character["version"],
                "damage": 3,
            }
        ],
    }
    preview_response = campaign_client.post(f"{base}/chases/preview", json=body)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["chase"]["status"] == "active"
    assert campaign_client.get(f"{base}/characters/{character['id']}").json()["hp"] == 12

    confirmed_response = campaign_client.post(
        f"{base}/chases/confirm",
        json={
            **body,
            "preview_token": preview["preview_token"],
            "idempotency_key": "chase-rooftops-0001",
        },
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    confirmed = confirmed_response.json()
    assert confirmed["idempotent_replay"] is False
    assert confirmed["chase"]["metadata_json"]["successes"] == 1
    assert confirmed["world_time"].startswith("2026-08-01T12:01:00")
    assert confirmed["character_effects"][0]["character"]["hp"] == 9
    assert campaign_client.get(f"{base}/events").json()["items"][0]["visibility"] == "players"

    replay = campaign_client.post(
        f"{base}/chases/confirm",
        json={
            **body,
            "preview_token": preview["preview_token"],
            "idempotency_key": "chase-rooftops-0001",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert campaign_client.get(f"{base}/characters/{character['id']}").json()["hp"] == 9
    assert len(campaign_client.get(f"{base}/chases").json()["items"]) == 1


def test_trap_and_environment_hazard_confirm_real_scene_effects(
    campaign_client: TestClient,
) -> None:
    campaign, base = _campaign(campaign_client, "陷阱与环境")
    character = _character(campaign_client, base)
    scene = _scene_with_grid(campaign_client, base)
    trap_response = campaign_client.post(
        f"{base}/scenes/{scene['id']}/objects",
        json={"object_type": "trap", "label": "坠石机关", "row": 2, "col": 2, "visibility": "dm"},
    )
    assert trap_response.status_code == 201, trap_response.text
    trap = trap_response.json()
    trap_body = {
        "trap_version": trap["version"],
        "outcome": "disarmed",
        "result_state": "disarmed",
        "minutes": 2,
        "summary": "队伍切断了坠石机关的拉线。",
        "visibility": "players",
        "character_effects": [
            {
                "character_id": character["id"],
                "character_version": character["version"],
                "damage": 2,
            }
        ],
    }
    trap_preview_response = campaign_client.post(
        f"{base}/scenes/{scene['id']}/traps/{trap['id']}/preview", json=trap_body
    )
    assert trap_preview_response.status_code == 200, trap_preview_response.text
    trap_preview = trap_preview_response.json()
    assert trap_preview["requires_confirmation"] is True
    grid = campaign_client.get(f"{base}/scenes/{scene['id']}/grid").json()
    assert grid["objects"][0]["state"] == "active"

    trap_confirm_body = {
        **trap_body,
        "preview_token": trap_preview["preview_token"],
        "idempotency_key": "trap-falling-stones-0001",
    }
    trap_confirm_response = campaign_client.post(
        f"{base}/scenes/{scene['id']}/traps/{trap['id']}/confirm",
        json=trap_confirm_body,
    )
    assert trap_confirm_response.status_code == 200, trap_confirm_response.text
    trap_confirmed = trap_confirm_response.json()
    assert trap_confirmed["trap"]["state"] == "disarmed"
    assert trap_confirmed["character_effects"][0]["character"]["hp"] == 10
    assert trap_confirmed["event"]["visibility"] == "players"

    trap_replay = campaign_client.post(
        f"{base}/scenes/{scene['id']}/traps/{trap['id']}/confirm",
        json=trap_confirm_body,
    )
    assert trap_replay.status_code == 200, trap_replay.text
    assert trap_replay.json()["idempotent_replay"] is True
    stale_trap = campaign_client.post(
        f"{base}/scenes/{scene['id']}/traps/{trap['id']}/confirm",
        json={**trap_confirm_body, "idempotency_key": "trap-falling-stones-stale"},
    )
    assert stale_trap.status_code == 409, stale_trap.text

    hazard_response = campaign_client.post(
        f"{base}/scenes/{scene['id']}/objects",
        json={"object_type": "terrain", "label": "塌陷地面", "row": 3, "col": 3},
    )
    assert hazard_response.status_code == 201, hazard_response.text
    hazard = hazard_response.json()
    damaged_character = campaign_client.get(f"{base}/characters/{character['id']}").json()
    hazard_body = {
        "name": "塌陷地面",
        "object_id": hazard["id"],
        "object_version": hazard["version"],
        "object_state": "destroyed",
        "minutes": 5,
        "summary": "地面坍塌后被标记为不可通行。",
        "visibility": "dm",
        "character_effects": [
            {
                "character_id": character["id"],
                "character_version": damaged_character["version"],
                "damage": 3,
                "condition_name": "prone",
            }
        ],
    }
    hazard_preview_response = campaign_client.post(
        f"{base}/scenes/{scene['id']}/hazards/preview", json=hazard_body
    )
    assert hazard_preview_response.status_code == 200, hazard_preview_response.text
    hazard_preview = hazard_preview_response.json()
    hazard_confirm_response = campaign_client.post(
        f"{base}/scenes/{scene['id']}/hazards/confirm",
        json={
            **hazard_body,
            "preview_token": hazard_preview["preview_token"],
            "idempotency_key": "hazard-collapse-0001",
        },
    )
    assert hazard_confirm_response.status_code == 200, hazard_confirm_response.text
    hazard_confirmed = hazard_confirm_response.json()
    assert hazard_confirmed["object"]["state"] == "destroyed"
    assert hazard_confirmed["character_effects"][0]["character"]["hp"] == 7
    assert hazard_confirmed["character_effects"][0]["condition"]["condition_name"] == "prone"
    assert hazard_confirmed["world_time"].startswith("2026-08-01T12:07:00")
    shared_log = campaign_client.get(
        f"/api/v1/player/campaigns/{campaign['id']}/view"
    ).json()["shared_log"]
    assert any(item["title"] == "坠石机关" for item in shared_log)
    assert all(item["title"] != "塌陷地面" for item in shared_log)


def test_affliction_confirmation_tracks_apply_and_cure_with_versions(
    campaign_client: TestClient,
) -> None:
    _, base = _campaign(campaign_client, "疾病闭环")
    character = _character(campaign_client, base)
    apply_body = {
        "operation": "apply",
        "character_id": character["id"],
        "character_version": character["version"],
        "affliction_type": "poison",
        "condition_name": "蛇毒",
        "source": "黑沼蛇",
        "summary": "蛇毒开始侵蚀伤口。",
        "damage": 2,
        "max_hp_reduction": 1,
        "minutes": 5,
        "visibility": "players",
    }
    preview_response = campaign_client.post(f"{base}/afflictions/preview", json=apply_body)
    assert preview_response.status_code == 200, preview_response.text
    assert campaign_client.get(f"{base}/characters/{character['id']}").json()["hp"] == 12
    apply_confirm_body = {
        **apply_body,
        "preview_token": preview_response.json()["preview_token"],
        "idempotency_key": "affliction-snake-poison-0001",
    }
    confirmed_response = campaign_client.post(
        f"{base}/afflictions/confirm",
        json=apply_confirm_body,
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    applied = confirmed_response.json()
    assert applied["character"]["hp"] == 10
    assert applied["character"]["max_hp_reduction"] == 1
    assert applied["condition"]["details"]["affliction_type"] == "poison"
    assert applied["event"]["visibility"] == "players"
    apply_replay = campaign_client.post(f"{base}/afflictions/confirm", json=apply_confirm_body)
    assert apply_replay.status_code == 200, apply_replay.text
    assert apply_replay.json()["idempotent_replay"] is True

    cure_body = {
        "operation": "cure",
        "character_id": character["id"],
        "character_version": applied["character"]["version"],
        "condition_id": applied["condition"]["id"],
        "condition_version": applied["condition"]["version"],
        "affliction_type": "poison",
        "condition_name": "蛇毒",
        "summary": "解毒剂中和了蛇毒。",
        "minutes": 10,
    }
    cure_preview = campaign_client.post(f"{base}/afflictions/preview", json=cure_body)
    assert cure_preview.status_code == 200, cure_preview.text
    cured_response = campaign_client.post(
        f"{base}/afflictions/confirm",
        json={
            **cure_body,
            "preview_token": cure_preview.json()["preview_token"],
            "idempotency_key": "affliction-snake-cure-0001",
        },
    )
    assert cured_response.status_code == 200, cured_response.text
    cured = cured_response.json()
    assert cured["condition"]["details"]["status"] == "cured"
    assert cured["world_time"].startswith("2026-08-01T12:15:00")


def test_downtime_and_npc_morale_confirm_resources_and_combat_state(
    campaign_client: TestClient,
) -> None:
    _, base = _campaign(campaign_client, "休整与士气")
    character = _character(campaign_client, base)
    wallet_response = campaign_client.post(
        f"{base}/characters/assets/wallets",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "copper": 40,
        },
    )
    assert wallet_response.status_code == 201, wallet_response.text
    current_character = campaign_client.get(f"{base}/characters/{character['id']}").json()
    activity_response = campaign_client.post(
        f"{base}/downtime-activities",
        json={
            "character_id": character["id"],
            "activity_type": "crafting",
            "title": "修复盾牌",
            "status": "active",
            "duration_days": 3,
            "daily_cost_cp": 7,
        },
    )
    assert activity_response.status_code == 201, activity_response.text
    activity = activity_response.json()
    downtime_body = {
        "activity_version": activity["version"],
        "character_version": current_character["version"],
        "progress_days": 2,
        "xp_award": 25,
        "summary": "阿莉娅花了两天修复盾牌。",
        "visibility": "players",
    }
    downtime_preview = campaign_client.post(
        f"{base}/downtime/{activity['id']}/preview", json=downtime_body
    )
    assert downtime_preview.status_code == 200, downtime_preview.text
    downtime_confirm_body = {
        **downtime_body,
        "preview_token": downtime_preview.json()["preview_token"],
        "idempotency_key": "downtime-repair-shield-0001",
    }
    downtime_confirmed_response = campaign_client.post(
        f"{base}/downtime/{activity['id']}/confirm",
        json=downtime_confirm_body,
    )
    assert downtime_confirmed_response.status_code == 200, downtime_confirmed_response.text
    downtime_confirmed = downtime_confirmed_response.json()
    assert downtime_confirmed["activity"]["progress_days"] == 2
    assert downtime_confirmed["wallet"]["copper"] == 26
    assert downtime_confirmed["character"]["experience"] == 25
    assert downtime_confirmed["world_time"].startswith("2026-08-03T12:00:00")
    downtime_replay = campaign_client.post(
        f"{base}/downtime/{activity['id']}/confirm",
        json=downtime_confirm_body,
    )
    assert downtime_replay.status_code == 200, downtime_replay.text
    assert downtime_replay.json()["idempotent_replay"] is True

    npc_response = campaign_client.post(
        f"{base}/npcs",
        json={"name": "走私者", "hp": 6, "max_hp": 6},
    )
    assert npc_response.status_code == 201, npc_response.text
    npc = npc_response.json()
    combat_response = campaign_client.post(f"{base}/combats", json={"name": "码头交锋"})
    assert combat_response.status_code == 201, combat_response.text
    combat = combat_response.json()
    combatant_response = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": npc["name"],
            "entity_type": "npc",
            "entity_id": npc["id"],
            "initiative": 12,
            "hp": 6,
            "max_hp": 6,
        },
    )
    assert combatant_response.status_code == 201, combatant_response.text
    morale_body = {
        "npc_version": npc["version"],
        "outcome": "surrender",
        "combat_id": combat["id"],
        "combat_version": combat["version"],
        "leave_combat": True,
        "minutes": 1,
        "summary": "走私者丢下匕首，举手投降。",
        "visibility": "players",
    }
    morale_preview = campaign_client.post(
        f"{base}/npcs/{npc['id']}/morale/preview",
        json=morale_body,
    )
    assert morale_preview.status_code == 200, morale_preview.text
    assert morale_preview.json()["combat"]["will_leave"] is True
    morale_confirmed_response = campaign_client.post(
        f"{base}/npcs/{npc['id']}/morale/confirm",
        json={
            **morale_body,
            "preview_token": morale_preview.json()["preview_token"],
            "idempotency_key": "morale-smuggler-surrender-0001",
        },
    )
    assert morale_confirmed_response.status_code == 200, morale_confirmed_response.text
    morale_confirmed = morale_confirmed_response.json()
    assert morale_confirmed["npc"]["status"] == "surrendered"
    assert morale_confirmed["combat_result"]["left_combat"] is True
    assert morale_confirmed["combatant"]["is_active"] is False
    assert morale_confirmed["event"]["visibility"] == "players"

    retreat_npc_response = campaign_client.post(
        f"{base}/npcs",
        json={"name": "望风者", "hp": 4, "max_hp": 4},
    )
    assert retreat_npc_response.status_code == 201, retreat_npc_response.text
    retreat_npc = retreat_npc_response.json()
    retreat_combatant_response = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": retreat_npc["name"],
            "entity_type": "npc",
            "entity_id": retreat_npc["id"],
            "initiative": 9,
            "hp": 4,
            "max_hp": 4,
        },
    )
    assert retreat_combatant_response.status_code == 201, retreat_combatant_response.text
    current_combat = campaign_client.get(f"{base}/combats/{combat['id']}").json()
    retreat_body = {
        "npc_version": retreat_npc["version"],
        "outcome": "retreat",
        "combat_id": combat["id"],
        "combat_version": current_combat["version"],
        "leave_combat": True,
        "minutes": 1,
        "summary": "望风者从码头小巷撤退。",
    }
    retreat_preview = campaign_client.post(
        f"{base}/npcs/{retreat_npc['id']}/morale/preview",
        json=retreat_body,
    )
    assert retreat_preview.status_code == 200, retreat_preview.text
    retreat_confirmed = campaign_client.post(
        f"{base}/npcs/{retreat_npc['id']}/morale/confirm",
        json={
            **retreat_body,
            "preview_token": retreat_preview.json()["preview_token"],
            "idempotency_key": "morale-lookout-retreat-0001",
        },
    )
    assert retreat_confirmed.status_code == 200, retreat_confirmed.text
    assert retreat_confirmed.json()["npc"]["status"] == "retreated"
    assert retreat_confirmed.json()["combat_result"]["left_combat"] is True

    replay = campaign_client.post(
        f"{base}/npcs/{npc['id']}/morale/confirm",
        json={
            **morale_body,
            "preview_token": morale_preview.json()["preview_token"],
            "idempotency_key": "morale-smuggler-surrender-0001",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
