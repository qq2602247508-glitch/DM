"""Round XXIII receipt tests for the generic typed spell defense consumer."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import SpellSpec, compile_spell_spec
from dnd_dm_assistant.domain.combat import resolve_damage
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import Combat, Combatant

ROOT = Path(__file__).resolve().parents[2]
SPELL_PATH = (
    ROOT
    / "data/content-ir/authored/batch-II/tashas-cauldron/spells/"
    / "tashas-cauldron-spell-b4ea0dc1907dd5ac08666af3.json"
)
SPELL_ID = "tashas-cauldron:spell:b4ea0dc1907dd5ac08666af3"


def _runtime() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    authored = json.loads(SPELL_PATH.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    assert compiled["compile_status"] == "full"
    runtime = compiled["runtime_spell_definition"]
    assert isinstance(runtime, dict)
    return runtime, ContentIRRuntimeService._runtime_blocks(runtime)


def _setup(
    client: Any,
    *,
    positions: list[tuple[int, int]],
    slots: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Intellect Fortress"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = client.post(
        f"{base}/characters",
        json={
            "name": "防护施法者",
            "level": 5,
            "hp": 30,
            "max_hp": 30,
            "spellcasting": slots
            or {
                "slots": {
                    "3": {"current": 2, "max": 2},
                    "4": {"current": 2, "max": 2},
                }
            },
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    runtime, _blocks = _runtime()
    known_response = client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime["name"],
            "spell_level": 3,
            "prepared": True,
            "metadata_json": {"content_ir_runtime": runtime},
        },
    )
    assert known_response.status_code == 201, known_response.text
    character = client.get(f"{base}/characters/{character['id']}").json()

    scene_response = client.post(f"{base}/scenes", json={"name": "Defense grid"})
    assert scene_response.status_code == 201, scene_response.text
    scene = scene_response.json()
    grid_response = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    assert grid_response.status_code == 201, grid_response.text
    combat_response = client.post(
        f"{base}/combats",
        json={"name": "Defense combat", "scene_id": scene["id"]},
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
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {"grid_position": {"row": 8, "col": 8}},
        },
    )
    assert actor_response.status_code == 201, actor_response.text
    actor = actor_response.json()
    targets: list[dict[str, Any]] = []
    for index, (row, col) in enumerate(positions, start=1):
        response = client.post(
            f"{combat_root}/combatants",
            json={
                "display_name": f"盟友{index}",
                "entity_type": "character",
                "initiative": 10 - index,
                "hp": 20,
                "max_hp": 20,
                "snapshot_json": {"grid_position": {"row": row, "col": col}},
            },
        )
        assert response.status_code == 201, response.text
        targets.append(response.json())
    return {
        "base": base,
        "campaign": campaign,
        "character": character,
        "known_spell": known_response.json(),
        "combat": combat,
        "actor": actor,
        "targets": targets,
    }


def _body(
    scene: dict[str, Any],
    *,
    key: str,
    slot_level: int,
    target_indexes: list[int],
    concentration: bool = True,
) -> dict[str, Any]:
    targets = scene["targets"]
    first = targets[target_indexes[0]]
    target_ids = [targets[index]["id"] for index in target_indexes[1:]]
    target_versions = {targets[index]["id"]: targets[index]["version"] for index in target_indexes}
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known_spell"]["id"],
        "slot_level": slot_level,
        "concentration": concentration,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": first["id"],
        "target_version": first["version"],
        "target_combatant_ids": target_ids,
        "target_versions": target_versions,
        "idempotency_key": key,
    }


def _get_target(client: Any, scene: dict[str, Any], target_id: str) -> dict[str, Any]:
    return client.get(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants/{target_id}"
    ).json()


def test_intellect_fortress_compiles_to_typed_defense_consumers() -> None:
    runtime, blocks = _runtime()
    assert runtime["spell_id"] == SPELL_ID
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=blocks,
    )
    assert [item["consumer_id"] for item in consumers] == [
        "spell.defense.v1",
        "spell_economy.concentration.v1",
    ]
    contract = ContentIRRuntimeService._spell_defense_contract(
        {
            "target_combatant_id": "target",
            "target_version": 1,
            "slot_level": 4,
        },
        blocks,
        runtime_id=SPELL_ID,
        runtime_level=3,
        caster_level=5,
    )
    assert contract is not None
    assert contract["maximum_target_count"] == 2
    assert contract["range_ft"] == 30
    assert contract["max_target_distance_ft"] == 30
    assert {item["operation"] for item in contract["rule_block"]["components"]} == {
        "resistance",
        "advantage",
    }


def test_round_xxiii_validator_receipt_is_green() -> None:
    result_path = ROOT / "data/content-ir/compiled/production-runtime-results-XXV.json"
    report_path = (
        ROOT
        / "reports/tashas-spell-production-consumer-round-XXIII-2026-08-12.json"
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result["all_required_checks_passed"] is True
    assert result["production_runtime_full_ids"] == [SPELL_ID]
    assert result["checks"]["typed_defense_consumer"] is True
    assert result["checks"]["formal_database_unchanged"] is True
    assert result["checks"]["formal_registry_unchanged"] is True
    assert result["checks"]["name_branch_free"] is True
    assert all(value is True for value in result["checks"].values())
    assert report["all_required_checks_passed"] is True
    assert report["production_runtime_full_ids"] == [SPELL_ID]
    assert report["formal_database_written"] is False
    assert report["formal_registry_written"] is False
    assert report["name_branch_count"] == 0


def test_intellect_fortress_persists_and_consumes_compound_defense(
    campaign_client: Any,
) -> None:
    scene = _setup(campaign_client, positions=[(8, 9)])
    body = _body(scene, key="round-xxiii-single", slot_level=3, target_indexes=[0])
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["consumer"] == "spell.defense.v1"
    assert confirmed.json()["production_runtime_full"] is True

    target = _get_target(campaign_client, scene, scene["targets"][0]["id"])
    actor = _get_target(campaign_client, scene, scene["actor"]["id"])
    effects_response = campaign_client.get(
        f"{scene['base']}/combats/{scene['combat']['id']}/effects"
    )
    assert effects_response.status_code == 200, effects_response.text
    effects = effects_response.json()["items"]
    assert len(effects) == 1
    assert effects[0]["details_json"]["rule_block"]["kind"] == "defense_bundle"
    assert target["damage_resistances"] == ["psychic"]
    modifiers = target["snapshot_json"]["rule_modifiers"]
    assert any(
        value.get("stat") == "saving_throw"
        and value.get("operation") == "advantage"
        and set(value.get("abilities") or []) == {"intelligence", "wisdom", "charisma"}
        for value in modifiers.values()
        if isinstance(value, dict)
    )
    assert actor["concentration"]["effect_ids"] == [effects[0]["id"]]

    engine = create_database_engine(campaign_client.database_url)
    with Session(engine) as session:
        target_row = session.get(Combatant, target["id"])
        combat_row = session.get(Combat, scene["combat"]["id"])
        assert target_row is not None and combat_row is not None
        resistances, _vulnerabilities, _immunities, applied, unresolved = (
            CombatEngineService._damage_defenses(
                target_row,
                SimpleNamespace(damage_tags=[], is_magical=True),
                ["psychic"],
                session=session,
                combat_id=combat_row.id,
            )
        )
        assert "psychic" in resistances
        assert unresolved == []
        assert any(SPELL_ID in item for item in applied)
        reduced = resolve_damage(
            amount=11,
            current_hp=20,
            temporary_hp=0,
            damage_type="psychic",
            resistances=tuple(resistances),
            vulnerabilities=(),
            immunities=(),
        )
        assert reduced.adjusted_damage == 5
        for ability in ("intelligence", "wisdom", "charisma"):
            save = CombatEngineService._resolve_save_defenses(
                target_row,
                dc=15,
                ability=ability,
                roll_total=5,
                roll_totals=[5, 16],
                damage_on_success=0,
                damage_on_failure=0,
                is_magical=False,
                use_legendary_resistance=False,
                use_feature_reroll=False,
                consume=False,
                session=session,
                combat=combat_row,
            )
            assert save["effective_roll_total"] == 16
            assert any(SPELL_ID in item for item in save["applied_defenses"])
    engine.dispose()


def test_intellect_fortress_enforces_upcast_range_and_group_distance(
    campaign_client: Any,
) -> None:
    scene = _setup(
        campaign_client,
        positions=[(2, 14), (14, 2), (8, 15)],
    )
    valid = _body(scene, key="round-xxiii-upcast", slot_level=4, target_indexes=[0, 1])
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=valid)
    assert preview.status_code == 400, preview.text
    assert "30 ft" in preview.text

    # Each target is at most 30 ft from the caster, but the two targets are
    # 60 ft apart; this exercises the explicit group-distance clause.
    group_distance = _body(
        scene,
        key="round-xxiii-group-distance",
        slot_level=4,
        target_indexes=[0, 1],
    )
    scene["targets"][1]["snapshot_json"]["grid_position"] = {"row": 14, "col": 2}
    group_preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=group_distance,
    )
    assert group_preview.status_code == 400, group_preview.text

    # A 4th-level slot permits two targets; a 3rd target is rejected before
    # spell economy or combat state can be changed.
    over_cap = _body(
        scene,
        key="round-xxiii-over-cap",
        slot_level=4,
        target_indexes=[0, 1, 2],
    )
    over_cap_preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=over_cap,
    )
    assert over_cap_preview.status_code == 400, over_cap_preview.text
    assert "at most 2" in over_cap_preview.text


def test_intellect_fortress_replay_replacement_and_group_end(campaign_client: Any) -> None:
    scene = _setup(campaign_client, positions=[(8, 9), (8, 10)])
    first = _body(scene, key="round-xxiii-first", slot_level=3, target_indexes=[0])
    first_preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=first,
    )
    assert first_preview.status_code == 200, first_preview.text
    first_confirm = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**first, "preview_token": first_preview.json()["preview_token"]},
    )
    assert first_confirm.status_code == 200, first_confirm.text

    scene["character"] = campaign_client.get(
        f"{scene['base']}/characters/{scene['character']['id']}"
    ).json()
    scene["actor"] = _get_target(campaign_client, scene, scene["actor"]["id"])
    scene["targets"][0] = _get_target(campaign_client, scene, scene["targets"][0]["id"])
    scene["targets"][1] = _get_target(campaign_client, scene, scene["targets"][1]["id"])
    second = _body(scene, key="round-xxiii-second", slot_level=3, target_indexes=[1])
    second_preview = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=second,
    )
    assert second_preview.status_code == 200, second_preview.text
    second_confirm = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**second, "preview_token": second_preview.json()["preview_token"]},
    )
    assert second_confirm.status_code == 200, second_confirm.text
    replay = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**second, "preview_token": second_preview.json()["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True

    old_target = _get_target(campaign_client, scene, scene["targets"][0]["id"])
    new_target = _get_target(campaign_client, scene, scene["targets"][1]["id"])
    assert old_target["damage_resistances"] == []
    assert new_target["damage_resistances"] == ["psychic"]
    actor = _get_target(campaign_client, scene, scene["actor"]["id"])
    active_effects = [
        item
        for item in campaign_client.get(
            f"{scene['base']}/combats/{scene['combat']['id']}/effects"
        ).json()["items"]
        if item["status"] == "active"
    ]
    assert len(active_effects) == 1
    end = campaign_client.post(
        f"{scene['base']}/combats/{scene['combat']['id']}/effects/{active_effects[0]['id']}/end",
        json={
            "target_version": new_target["version"],
            "source_version": actor["version"],
            "reason": "Round XXIII test ends concentration group",
        },
    )
    assert end.status_code == 200, end.text
    assert len(end.json()["ended_effects"]) == 1
    assert _get_target(campaign_client, scene, new_target["id"])["damage_resistances"] == []
    after_actor = _get_target(campaign_client, scene, scene["actor"]["id"])
    assert after_actor["concentration"] == {}
    after_character = campaign_client.get(
        f"{scene['base']}/characters/{scene['character']['id']}"
    ).json()
    assert "concentration" not in after_character["resources"]
