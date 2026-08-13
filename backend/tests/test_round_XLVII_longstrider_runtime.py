from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import SpellSpec, compile_spell_spec

ROOT = Path(__file__).resolve().parents[2]
SPELL_PATH = (
    ROOT
    / "data/content-ir/authored/batch-II/core-phb-2024/spells/"
    "core-phb-2024-spell-6f5b6f21ffa22e705a9bd6cb.json"
)
SPELL_ID = "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb"


def _runtime() -> dict[str, Any]:
    authored = json.loads(SPELL_PATH.read_text(encoding="utf-8"))
    result = compile_spell_spec(SpellSpec.from_dict(authored))
    assert result["compile_status"] == "full"
    return result["runtime_spell_definition"]


def _setup(client: Any) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Longstrider"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "施法者",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {
                "slots": {
                    "1": {"current": 3, "max": 3},
                    "2": {"current": 3, "max": 3},
                }
            },
        },
    ).json()
    runtime = _runtime()
    known = client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime["name"],
            "spell_level": 1,
            "prepared": True,
            "metadata_json": {"content_ir_runtime": runtime},
        },
    ).json()
    character = client.get(f"{base}/characters/{character['id']}").json()
    scene = client.post(f"{base}/scenes", json={"name": "Longstrider scene"}).json()
    client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = client.post(
        f"{base}/combats", json={"name": "Longstrider combat", "scene_id": scene["id"]}
    ).json()
    root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "施法者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 5, "col": 5}},
        },
    ).json()
    targets = []
    for index, position in enumerate(((5, 6), (6, 5), (7, 5)), start=1):
        targets.append(
            client.post(
                f"{root}/combatants",
                json={
                    "display_name": f"目标{index}",
                    "entity_type": "character",
                    "initiative": 10 - index,
                    "hp": 20,
                    "max_hp": 20,
                    "snapshot_json": {"grid_position": {"row": position[0], "col": position[1]}},
                },
            ).json()
        )
    return {
        "base": base,
        "character": character,
        "known": known,
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
) -> dict[str, Any]:
    targets = scene["targets"]
    first = targets[target_indexes[0]]
    extra = [targets[index] for index in target_indexes[1:]]
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": slot_level,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": first["id"],
        "target_version": first["version"],
        "target_combatant_ids": [item["id"] for item in extra],
        "target_versions": {item["id"]: item["version"] for item in [first, *extra]},
        "target_willing_by_id": {item["id"]: True for item in [first, *extra]},
        "idempotency_key": key,
    }


def test_longstrider_source_bound_runtime_preview_confirm_replay_and_receipt(
    campaign_client: Any,
) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, key="longstrider-round-xlvii-1", slot_level=2, target_indexes=[0, 1])
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["production_contract"]["consumers"] == ["spell.timed_modifier.v1"]
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["production_runtime_full"] is True
    assert result["upcast"]["maximum_target_count"] == 2
    assert len(result["timed_modifier_receipts"]) == 2
    assert all(item["expires_at"].endswith("+00:00") for item in result["timed_modifier_receipts"])
    replay = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


def test_longstrider_rejects_unwilling_target_and_payload_drift(campaign_client: Any) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, key="longstrider-round-xlvii-2", slot_level=1, target_indexes=[0])
    unwilling = {**body, "target_willing_by_id": {scene["targets"][0]["id"]: False}}
    response = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=unwilling)
    assert response.status_code == 400
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    drift = {**body, "target_willing_by_id": {scene["targets"][0]["id"]: False}}
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**drift, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 400


def test_longstrider_rejects_stale_target_cas_and_wrong_slot(campaign_client: Any) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, key="longstrider-round-xlvii-3", slot_level=1, target_indexes=[0])
    stale = {**body, "target_version": body["target_version"] + 1}
    assert (
        campaign_client.post(
            f"{scene['base']}/content-ir/runtime/preview", json=stale
        ).status_code
        == 409
    )
    wrong_slot = {**body, "slot_level": 0}
    assert (
        campaign_client.post(
            f"{scene['base']}/content-ir/runtime/preview", json=wrong_slot
        ).status_code
        == 400
    )


def test_longstrider_registry_and_compiled_source_are_typed() -> None:
    runtime = _runtime()
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    assert [item["type"] for item in blocks["effects"]] == ["timed_modifier"]
    assert blocks["target_selection"][0]["kind"] == "one_creature"
    assert blocks["upcast"][0]["target_count_increment"] == 1
