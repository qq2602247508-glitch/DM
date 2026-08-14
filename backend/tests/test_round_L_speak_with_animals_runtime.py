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
from dnd_dm_assistant.domain.typed_spell_communication_capabilities import CAPABILITY_SCHEMA

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
AUTHORED = ROOT / (
    "data/content-ir/authored/batch-II/core-phb-2024/spells/"
    "core-phb-2024-spell-d82624a42cf6c33ccec927b8.json"
)
SPELL_ID = "core-phb-2024:spell:d82624a42cf6c33ccec927b8"


def _runtime() -> dict[str, Any]:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    assert compiled["compile_status"] == "full"
    runtime = dict(compiled["runtime_spell_definition"])
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    consumers = resolve_production_consumers(
        content_kind="spell", runtime_schema_version="spell-runtime-1", blocks=blocks
    )
    assert [item["consumer_id"] for item in consumers] == [
        "spell.communication.capability.v1"
    ]
    return runtime


def _setup(client: TestClient) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Round L"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "施法者",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {"slots": {"1": {"current": 2, "max": 2}}},
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
    scene = client.post(f"{base}/scenes", json={"name": "Round L scene"}).json()
    client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = client.post(
        f"{base}/combats", json={"name": "Round L combat", "scene_id": scene["id"]}
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
    beast = client.post(
        f"{root}/combatants",
        json={
            "display_name": "乌鸦",
            "entity_type": "monster",
            "entity_id": "raven",
            "initiative": 10,
            "hp": 5,
            "max_hp": 5,
            "snapshot_json": {
                "grid_position": {"row": 5, "col": 6},
                "creature_type": "beast",
            },
        },
    ).json()
    return {
        "base": base,
        "character": character,
        "known": known,
        "combat": combat,
        "actor": actor,
        "beast": beast,
    }


def _body(scene: dict[str, Any], key: str, **overrides: object) -> dict[str, Any]:
    body = {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": 1,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "communication_beast_combatant_id": scene["beast"]["id"],
        "communication_beast_version": scene["beast"]["version"],
        "communication_influence_skill": "persuasion",
        "communication_information_scope": "surroundings_and_monsters",
        "communication_observation_age_hours": 24,
        "idempotency_key": key,
    }
    body.update(overrides)
    return body


def test_speak_with_animals_preview_confirm_replay_persists_capability(
    campaign_client: TestClient,
) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, "speak-with-animals-round-l")
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_json = preview.json()
    assert preview_json["production_contract"]["consumers"] == [
        "spell.communication.capability.v1"
    ]
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["consumer"] == "spell.communication.capability.v1"
    assert result["communication_capability_receipt"]["schema"] == CAPABILITY_SCHEMA
    assert result["communication"]["influence_action_skills"] == [
        "deception",
        "intimidation",
        "persuasion",
    ]
    assert result["communication"]["observation_age_hours"] == 24
    assert result["operation_transaction_id"]
    replay = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert replay.status_code == 200
    assert replay.json()["already_applied"] is True


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"communication_influence_skill": "animal_handling"}, "Influence skill"),
        ({"communication_information_scope": "other"}, "information scope"),
        ({"communication_observation_age_hours": 25}, "older than one day"),
    ],
)
def test_speak_with_animals_rejects_source_boundary_drift(
    campaign_client: TestClient, overrides: dict[str, object], needle: str
) -> None:
    scene = _setup(campaign_client)
    response = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=_body(scene, "speak-invalid-" + str(abs(hash(str(overrides))),), **overrides),
    )
    assert response.status_code in {400, 422}
    assert needle in str(response.json()) or response.status_code == 422


def test_speak_with_animals_rejects_non_beast_and_stale_cas(
    campaign_client: TestClient,
) -> None:
    scene = _setup(campaign_client)
    non_beast = campaign_client.post(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants",
        json={
            "display_name": "人类",
            "entity_type": "character",
            "entity_id": "human",
            "initiative": 5,
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {"grid_position": {"row": 6, "col": 6}},
        },
    ).json()
    invalid = _body(
        scene,
        "speak-human",
        communication_beast_combatant_id=non_beast["id"],
        communication_beast_version=non_beast["version"],
    )
    response = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=invalid)
    assert response.status_code == 400
    assert "not a beast" in str(response.json())
    stale = _body(scene, "speak-stale", communication_beast_version=2)
    response = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=stale)
    assert response.status_code == 409
