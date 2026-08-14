from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import SpellSpec, compile_spell_spec
from dnd_dm_assistant.domain.typed_spell_communication_routes import (
    COMMUNICATION_ROUTE_SCHEMA,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
AUTHORED = ROOT / (
    "data/content-ir/authored/batch-II/core-phb-2024/spells/"
    "core-phb-2024-spell-dd9cb25c63b7e13194c7d01c.json"
)
SPELL_ID = "core-phb-2024:spell:dd9cb25c63b7e13194c7d01c"


def _setup(client: TestClient, runtime: dict[str, Any]) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Round XLIX"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "施法者",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {"slots": {"0": {"current": 3, "max": 3}}},
        },
    ).json()
    known = client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime["name"],
            "spell_level": 0,
            "prepared": True,
            "metadata_json": {"content_ir_runtime": runtime},
        },
    ).json()
    character = client.get(f"{base}/characters/{character['id']}").json()
    scene = client.post(f"{base}/scenes", json={"name": "Round XLIX scene"}).json()
    client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 40, "height": 40, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = client.post(
        f"{base}/combats", json={"name": "Round XLIX combat", "scene_id": scene["id"]}
    ).json()
    combat_root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{combat_root}/combatants",
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
    for index, position in enumerate(((5, 6), (6, 5)), start=1):
        targets.append(
            client.post(
                f"{combat_root}/combatants",
                json={
                    "display_name": f"目标{index}",
                    "entity_type": "character",
                    "entity_id": f"target-{index}",
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


def _runtime() -> dict:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    assert compiled["compile_status"] == "full"
    runtime = dict(compiled["runtime_spell_definition"])
    assert "communication_route" in ContentIRRuntimeService._runtime_blocks(runtime)
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=ContentIRRuntimeService._runtime_blocks(runtime),
    )
    assert [item["consumer_id"] for item in consumers] == ["spell.communication.route.v1"]
    return runtime


def _body(scene: dict, key: str, **overrides: object) -> dict:
    target = scene["targets"][0]
    body = {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": 0,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "target_versions": {target["id"]: target["version"]},
        "communication_visible": True,
        "communication_message_fingerprint": "b" * 64,
        "idempotency_key": key,
    }
    body.update(overrides)
    return body


def test_message_preview_confirm_replay_persists_private_route(
    campaign_client: TestClient,
) -> None:
    scene = _setup(campaign_client, _runtime())
    body = _body(scene, "message-round-xlix")
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_json = preview.json()
    assert preview_json["runtime_preview_full"] is True
    assert preview_json["production_contract"]["consumers"] == ["spell.communication.route.v1"]
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["production_runtime_full"] is True
    assert result["consumer"] == "spell.communication.route.v1"
    assert result["communication_route_receipt"]["schema"] == COMMUNICATION_ROUTE_SCHEMA
    assert result["communication_route_receipt"]["delivered_to"] == scene["targets"][0]["id"]
    assert result["communication_route_receipt"]["private_reply_to"] == scene["actor"]["id"]
    assert result["operation_transaction_id"]

    replay = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True

    drift = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={
            **body,
            "preview_token": preview_json["preview_token"],
            "communication_message_fingerprint": "c" * 64,
        },
    )
    assert drift.status_code == 400


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"communication_visible": False, "communication_familiar": False}, "visibility"),
        ({"communication_visible": False, "communication_familiar": True}, None),
        (
            {
                "communication_visible": False,
                "communication_familiar": True,
                "communication_barrier_present": True,
                "communication_barrier_thickness_ft": 2,
                "communication_barrier_material": "stone",
            },
            "too thick",
        ),
        (
            {
                "communication_visible": False,
                "communication_familiar": False,
                "communication_barrier_present": True,
                "communication_barrier_thickness_ft": 1,
                "communication_barrier_material": "stone",
            },
            "familiarity",
        ),
        ({"communication_sender_in_magical_silence": True}, "silence"),
        ({"communication_target_in_magical_silence": True}, "silence"),
    ],
)
def test_message_route_fail_closed(
    campaign_client: TestClient, overrides: dict[str, object], needle: str | None
) -> None:
    scene = _setup(campaign_client, _runtime())
    body = _body(scene, "message-fail-" + str(abs(hash(str(overrides)))), **overrides)
    response = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if needle is None:
        assert response.status_code == 200, response.text
    else:
        assert response.status_code == 400, response.text
        error = response.json()
        assert needle in str(error.get("detail") or error.get("message"))


def test_message_route_rejects_range_and_cas(campaign_client: TestClient) -> None:
    scene = _setup(campaign_client, _runtime())
    far = _body(scene, "message-range", communication_visible=True)
    response = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**far, "communication_distance_ft": 121},
    )
    assert response.status_code == 400
    far_target = campaign_client.post(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants",
        json={
            "display_name": "远处目标",
            "entity_type": "character",
            "entity_id": "far-target",
            "initiative": 5,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 40, "col": 40}},
        },
    ).json()
    out_of_range = _body(
        scene,
        "message-out-of-range",
        communication_visible=True,
        target_combatant_id=far_target["id"],
        target_version=far_target["version"],
        target_versions={far_target["id"]: far_target["version"]},
    )
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview", json=out_of_range
    ).status_code == 400
    stale = _body(scene, "message-stale", character_version=1)
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview", json=stale
    ).status_code == 409


def test_message_route_rejects_wrong_runtime_and_target_binding(
    campaign_client: TestClient,
) -> None:
    scene = _setup(campaign_client, _runtime())
    wrong_runtime = _body(
        scene, "message-wrong-runtime", runtime_id="core-phb-2024:spell:not-message"
    )
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview", json=wrong_runtime
    ).status_code == 400
    wrong_target = _body(
        scene,
        "message-wrong-target",
        target_combatant_id="missing-target",
        target_version=1,
        target_versions={"missing-target": 1},
    )
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview", json=wrong_target
    ).status_code == 404
