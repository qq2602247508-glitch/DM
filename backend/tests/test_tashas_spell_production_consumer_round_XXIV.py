"""Round XXIV receipt tests for the generic typed summon spell consumer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import SpellSpec, compile_spell_spec
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import Combatant

ROOT = Path(__file__).resolve().parents[2]
SPELL_RECORDS = {
    "tashas-cauldron:spell:54c8c29188db1442473d9dc1": (
        ROOT
        / "data/content-ir/authored/batch-II/tashas-cauldron/spells/"
        / "tashas-cauldron-spell-54c8c29188db1442473d9dc1.json"
    ),
    "tashas-cauldron:spell:083419d9de551806a5ca9748": (
        ROOT
        / "data/content-ir/authored/batch-II/tashas-cauldron/spells/"
        / "tashas-cauldron-spell-083419d9de551806a5ca9748.json"
    ),
}


def _compiled_records() -> dict[
    str, tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]
]:
    result: dict[
        str, tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]
    ] = {}
    for spell_id, path in SPELL_RECORDS.items():
        authored = json.loads(path.read_text(encoding="utf-8"))
        compiled = compile_spell_spec(SpellSpec.from_dict(authored))
        assert compiled["compile_status"] == "full"
        runtime = compiled["runtime_spell_definition"]
        assert isinstance(runtime, dict)
        blocks = ContentIRRuntimeService._runtime_blocks(runtime)
        result[spell_id] = (authored, runtime, blocks)
    return result


def _setup(client: TestClient, spell_id: str) -> dict[str, Any]:
    _authored, runtime, _blocks = _compiled_records()[spell_id]
    campaign = client.post("/api/v1/campaigns", json={"name": "Round XXIV summon"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = client.post(
        f"{base}/characters",
        json={
            "name": "召唤施法者",
            "level": 5,
            "hp": 40,
            "max_hp": 40,
            "spellcasting": {
                "slots": {
                    "2": {"current": 2, "max": 2},
                    "3": {"current": 2, "max": 2},
                    "4": {"current": 2, "max": 2},
                }
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    known_response = client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime["name"],
            "spell_level": runtime["level"],
            "prepared": True,
            "metadata_json": {"content_ir_runtime": runtime},
        },
    )
    assert known_response.status_code == 201, known_response.text
    character = client.get(f"{base}/characters/{character['id']}").json()

    scene_response = client.post(f"{base}/scenes", json={"name": "Summon grid"})
    assert scene_response.status_code == 201, scene_response.text
    scene = scene_response.json()
    grid_response = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid_response.status_code == 201, grid_response.text
    combat_response = client.post(
        f"{base}/combats",
        json={"name": "Summon combat", "scene_id": scene["id"]},
    )
    assert combat_response.status_code == 201, combat_response.text
    combat = combat_response.json()
    combat_root = f"{base}/combats/{combat['id']}"
    actor_response = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "施法者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 40,
            "max_hp": 40,
            "snapshot_json": {"grid_position": {"row": 8, "col": 8}},
        },
    )
    assert actor_response.status_code == 201, actor_response.text
    enemy_response = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "敌人",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 40,
            "max_hp": 40,
            "snapshot_json": {"grid_position": {"row": 8, "col": 12}},
        },
    )
    assert enemy_response.status_code == 201, enemy_response.text
    return {
        "base": base,
        "character": character,
        "known_spell": known_response.json(),
        "combat": combat,
        "actor": actor_response.json(),
        "enemy": enemy_response.json(),
        "combat_root": combat_root,
        "runtime": runtime,
        "spell_id": spell_id,
    }


def _body(
    scene: dict[str, Any],
    *,
    key: str,
    choice: str,
    row: int = 8,
    col: int = 10,
) -> dict[str, Any]:
    return {
        "content_kind": "spell",
        "runtime_id": scene["spell_id"],
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known_spell"]["id"],
        "slot_level": scene["runtime"]["level"],
        "material_available": True,
        "concentration": True,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "summon_choice": choice,
        "destination_row": row,
        "destination_col": col,
        "idempotency_key": key,
    }


def _get_combatant(client: TestClient, scene: dict[str, Any], combatant_id: str) -> dict[str, Any]:
    return client.get(
        f"{scene['combat_root']}/combatants/{combatant_id}"
    ).json()


def test_both_tasha_summons_compile_and_resolve_shared_production_consumers() -> None:
    for _spell_id, (_authored, runtime, blocks) in _compiled_records().items():
        consumers = resolve_production_consumers(
            content_kind="spell",
            runtime_schema_version="spell-runtime-1",
            blocks=blocks,
        )
        assert [item["consumer_id"] for item in consumers] == [
            "spell.summon.v1",
            "spell_economy.concentration.v1",
        ]
        summon = blocks["effects"][0]
        assert summon["type"] == "summon_or_creation"
        assert summon["action_economy"] == "action"
        assert summon["requires_concentration"] is True
        assert blocks["target_selection"][0]["range_ft"] == 90
        assert blocks["target_selection"][0]["requires_unoccupied"] is True
        assert blocks["target_selection"][0]["visibility"] == "visible"
        assert "summon_or_creation" in {
            item["type"] for item in runtime["resolution"]["effects"]
        }


def test_summon_contract_fails_closed_for_choice_and_scales_structured_stat_block() -> None:
    records = _compiled_records()
    beast_runtime, beast_blocks = records[
        "tashas-cauldron:spell:54c8c29188db1442473d9dc1"
    ][1:]
    undead_runtime, undead_blocks = records[
        "tashas-cauldron:spell:083419d9de551806a5ca9748"
    ][1:]
    base = {
        "slot_level": 4,
        "destination_row": 8,
        "destination_col": 10,
    }
    try:
        ContentIRRuntimeService._spell_summon_contract(
            base,
            beast_blocks,
            runtime_id=beast_runtime["spell_id"],
            runtime_name=beast_runtime["name"],
            runtime_level=2,
            caster_level=5,
        )
    except ValueError as exc:
        assert "choice" in str(exc)
    else:
        raise AssertionError("missing summon choice must fail closed")

    beast = ContentIRRuntimeService._spell_summon_contract(
        {**base, "summon_choice": "land"},
        beast_blocks,
        runtime_id=beast_runtime["spell_id"],
        runtime_name=beast_runtime["name"],
        runtime_level=2,
        caster_level=5,
    )
    assert beast["template"]["hp"] == 40
    assert beast["template"]["armor_class"] == 15
    assert beast["template"]["movement_modes"] == [
        {"mode": "walk", "speed_ft": 30},
        {"mode": "climb", "speed_ft": 60},
    ]
    assert beast["duration_unit"] == "minutes"
    assert beast["duration_value"] == 60

    undead = ContentIRRuntimeService._spell_summon_contract(
        {**base, "summon_choice": "skeletal"},
        undead_blocks,
        runtime_id=undead_runtime["spell_id"],
        runtime_name=undead_runtime["name"],
        runtime_level=3,
        caster_level=5,
    )
    assert undead["template"]["hp"] == 30
    assert undead["template"]["armor_class"] == 15
    assert undead["template"]["damage_immunities"] == ["necrotic", "poison"]


def test_summon_preview_rejects_occupied_position_before_spell_payment(
    campaign_client: TestClient,
) -> None:
    scene = _setup(
        campaign_client,
        "tashas-cauldron:spell:54c8c29188db1442473d9dc1",
    )
    body = _body(scene, key="round-xxiv-occupied", choice="air", row=8, col=8)
    response = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    assert response.status_code == 400, response.text
    assert "occupied" in response.text
    character = campaign_client.get(
        f"{scene['base']}/characters/{scene['character']['id']}"
    ).json()
    assert character["spellcasting"]["slots"]["2"]["current"] == 2


def test_summon_confirm_persists_stat_block_defenses_actions_lifecycle_and_replay(
    campaign_client: TestClient,
) -> None:
    scene = _setup(
        campaign_client,
        "tashas-cauldron:spell:54c8c29188db1442473d9dc1",
    )
    body = _body(scene, key="round-xxiv-confirm", choice="land", row=8, col=10)
    preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    assert preview.status_code == 200, preview.text
    preview_json = preview.json()
    assert preview_json["production_contract"]["action_cost"] == "action"
    assert preview_json["production_contract"]["summon"]["geometry"]["distance_ft"] == 10

    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    payload = confirmed.json()
    assert payload["consumer"] == "spell.summon.v1"
    assert payload["production_runtime_full"] is True
    summon = payload["combat"]["combatant"]
    assert summon["initiative"] == scene["actor"]["initiative"]
    assert summon["armor_class"] == 13
    assert summon["max_hp"] == 30
    assert summon["damage_immunities"] == []
    assert summon["snapshot_json"]["movement_modes"] == [
        {"mode": "walk", "speed_ft": 30},
        {"mode": "climb", "speed_ft": 60},
    ]
    assert summon["snapshot_json"]["active_movement_modes"]["climb"] == 60
    assert summon["snapshot_json"]["actions"]
    assert summon["snapshot_json"]["default_behavior"]["on_no_command"] == "dodge"
    assert summon["snapshot_json"]["summon_position_policy"]["requires_unoccupied"] is True
    assert payload["combat"]["action"]["request_json"]["action_cost"] == "action"
    assert payload["combat"]["action"]["request_json"]["duration_unit"] == "minutes"
    assert payload["combat"]["action"]["request_json"]["duration_value"] == 60

    actor = _get_combatant(campaign_client, scene, scene["actor"]["id"])
    assert actor["action_available"] is False
    character = campaign_client.get(
        f"{scene['base']}/characters/{scene['character']['id']}"
    ).json()
    assert character["spellcasting"]["slots"]["2"]["current"] == 1

    effects = campaign_client.get(
        f"{scene['base']}/combats/{scene['combat']['id']}/effects"
    ).json()["items"]
    assert len(effects) == 1
    assert effects[0]["duration_unit"] == "minutes"
    assert effects[0]["duration_value"] == 60
    assert effects[0]["details_json"]["spell_id"] == scene["spell_id"]
    assert effects[0]["details_json"]["known_spell_id"] == scene["known_spell"]["id"]

    replay = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


def test_summon_confirm_rolls_back_spell_slot_when_action_economy_fails(
    campaign_client: TestClient,
) -> None:
    scene = _setup(
        campaign_client,
        "tashas-cauldron:spell:54c8c29188db1442473d9dc1",
    )
    blocked = campaign_client.patch(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants/{scene['actor']['id']}",
        json={"action_available": False, "version": scene["actor"]["version"]},
    )
    assert blocked.status_code == 200, blocked.text
    scene["actor"] = blocked.json()
    body = _body(scene, key="round-xxiv-action-rollback", choice="air")
    preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 400, confirmed.text
    character = campaign_client.get(
        f"{scene['base']}/characters/{scene['character']['id']}"
    ).json()
    assert character["spellcasting"]["slots"]["2"]["current"] == 2
    assert not [
        item
        for item in campaign_client.get(
            f"{scene['base']}/combats/{scene['combat']['id']}/combatants"
        ).json()["items"]
        if item["entity_type"] == "companion"
    ]


def test_summon_hp_zero_and_source_zero_end_real_lifecycle(
    campaign_client: TestClient,
) -> None:
    scene = _setup(
        campaign_client,
        "tashas-cauldron:spell:083419d9de551806a5ca9748",
    )
    body = _body(scene, key="round-xxiv-lifecycle", choice="ghostly", row=8, col=10)
    preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    summon = confirmed.json()["combat"]["combatant"]

    summon_damage = campaign_client.post(
        f"{scene['combat_root']}/actions/confirm",
        headers={"X-Request-ID": "round-xxiv-summon-zero"},
        json={
            "action_type": "damage",
            "target_combatant_id": summon["id"],
            "target_version": summon["version"],
            "actor_combatant_id": scene["enemy"]["id"],
            "actor_version": scene["enemy"]["version"],
            "action_cost": "none",
            "amount": summon["hp"],
            "damage_type": "force",
        },
    )
    assert summon_damage.status_code == 200, summon_damage.text
    assert _get_combatant(campaign_client, scene, summon["id"])["is_active"] is False

    scene2 = _setup(
        campaign_client,
        "tashas-cauldron:spell:083419d9de551806a5ca9748",
    )
    body2 = _body(scene2, key="round-xxiv-source-zero", choice="putrid", row=8, col=10)
    preview2 = campaign_client.post(
        f"{scene2['base']}/content-ir/runtime/preview",
        json=body2,
    )
    assert preview2.status_code == 200, preview2.text
    confirmed2 = campaign_client.post(
        f"{scene2['base']}/content-ir/runtime/confirm",
        json={**body2, "preview_token": preview2.json()["preview_token"]},
    )
    assert confirmed2.status_code == 200, confirmed2.text
    summon2 = confirmed2.json()["combat"]["combatant"]
    actor = _get_combatant(campaign_client, scene2, scene2["actor"]["id"])
    source_damage = campaign_client.post(
        f"{scene2['combat_root']}/actions/confirm",
        headers={"X-Request-ID": "round-xxiv-source-zero-damage"},
        json={
            "action_type": "damage",
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
            "actor_combatant_id": scene2["enemy"]["id"],
            "actor_version": scene2["enemy"]["version"],
            "action_cost": "none",
            "amount": actor["hp"],
            "damage_type": "force",
        },
    )
    assert source_damage.status_code == 200, source_damage.text
    assert _get_combatant(campaign_client, scene2, summon2["id"])["is_active"] is False


def test_summon_actions_are_available_to_existing_structured_combat_path(
    campaign_client: TestClient,
) -> None:
    scene = _setup(
        campaign_client,
        "tashas-cauldron:spell:54c8c29188db1442473d9dc1",
    )
    body = _body(scene, key="round-xxiv-action-persistence", choice="water")
    preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    summon = confirmed.json()["combat"]["combatant"]
    engine = create_database_engine(campaign_client.database_url)
    with Session(engine) as session:
        row = session.get(Combatant, summon["id"])
        assert row is not None
        profiles = CombatEngineService._eligible_attack_profiles_for_mode(row, "weapon_only")
        assert [item["action_name"] for item in profiles] == ["Maul"]
        assert row.armor_class == 13
        assert row.damage_resistances == []
        assert row.snapshot_json["actions"][1]["damage_type"] == "piercing"
    engine.dispose()


def test_player_summon_default_behavior_consumes_dodge_and_moves_away_from_danger(
    campaign_client: TestClient,
) -> None:
    scene = _setup(
        campaign_client,
        "tashas-cauldron:spell:54c8c29188db1442473d9dc1",
    )
    body = _body(scene, key="round-xxiv-default-behavior", choice="land", row=10, col=10)
    preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    summon = confirmed.json()["combat"]["combatant"]

    combat = campaign_client.get(scene["combat_root"]).json()
    payload: dict[str, Any] | None = None
    behavior: dict[str, Any] | None = None
    for advance_index in range(1, 5):
        advanced = campaign_client.post(
            f"{scene['combat_root']}/turns/advance",
            headers={
                "X-Request-ID": f"round-xxiv-default-behavior-advance-{advance_index}"
            },
            json={"combat_version": combat["version"]},
        )
        assert advanced.status_code == 200, advanced.text
        payload = advanced.json()
        candidate = payload.get("default_behavior")
        if isinstance(candidate, dict):
            behavior = candidate
            break
        combat = payload["combat"]
    assert payload is not None
    assert behavior is not None
    assert behavior["status"] == "applied"
    assert behavior["dodge"]["effect_id"]
    assert behavior["movement"]["policy"] == "move_away_from_danger"
    assert behavior["movement"]["moved_ft"] > 0
    assert behavior["danger_source_combatant_id"] == scene["enemy"]["id"]
    assert payload["active_combatant"]["id"] == summon["id"]

    current = _get_combatant(campaign_client, scene, summon["id"])
    assert current["action_available"] is False
    assert current["movement_remaining_ft"] < current["speed_ft"]
    assert current["snapshot_json"]["grid_position"] == behavior["movement"]["to"]
    effects = campaign_client.get(
        f"{scene['combat_root']}/effects"
    ).json()["items"]
    assert any(
        effect["id"] == behavior["dodge"]["effect_id"] and effect["status"] == "active"
        for effect in effects
    )
