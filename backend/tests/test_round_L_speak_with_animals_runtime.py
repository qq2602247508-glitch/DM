from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import SpellSpec, compile_spell_spec
from dnd_dm_assistant.domain.typed_spell_communication_capabilities import CAPABILITY_SCHEMA
from dnd_dm_assistant.infrastructure.database.models import Combatant, OperationTransaction

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


def _setup(client: TestClient, runtime_override: dict[str, Any] | None = None) -> dict[str, Any]:
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
    runtime = runtime_override or _runtime()
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


def _confirm(client: TestClient, scene: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_json = preview.json()
    confirmed = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def _db_state(client: TestClient, scene: dict[str, Any], key: str) -> dict[str, Any]:
    engine = create_engine(client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        actor = session.get(Combatant, scene["actor"]["id"])
        beast = session.get(Combatant, scene["beast"]["id"])
        transaction = session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == scene["base"].rsplit("/", 1)[-1],
                OperationTransaction.idempotency_key == f"content-ir:{key}:capability",
            )
        )
        count = session.scalar(
            select(func.count()).select_from(OperationTransaction).where(
                OperationTransaction.campaign_id == scene["base"].rsplit("/", 1)[-1],
                OperationTransaction.idempotency_key == f"content-ir:{key}:capability",
            )
        )
        assert actor is not None and beast is not None and transaction is not None
        return {
            "actor_version": actor.version,
            "beast_version": beast.version,
            "actor_snapshot": dict(actor.snapshot_json or {}),
            "transaction": transaction,
            "transaction_count": int(count or 0),
        }


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


def test_round_l_capability_persistence_receipt_and_behavioral_boundaries(
    campaign_client: TestClient,
) -> None:
    scene = _setup(campaign_client)
    result = _confirm(
        campaign_client,
        scene,
        _body(scene, "round-l-boundary", communication_observation_age_hours=24),
    )
    receipt = result["communication_capability_receipt"]
    assert receipt["source_record_id"] == _runtime()["source"]["source_record_id"]
    assert receipt["source_fingerprint"] == _runtime()["source"]["source_fingerprint"]
    assert receipt["clause_id"] == "communication_capability"
    assert receipt["duration_unit"] == "minutes"
    assert receipt["duration_value"] == 10
    assert receipt["influence_action_skills"] == ["deception", "intimidation", "persuasion"]
    assert receipt["expires_at"] != receipt["started_at"]
    from datetime import datetime

    assert (
        datetime.fromisoformat(receipt["expires_at"])
        - datetime.fromisoformat(receipt["started_at"])
    ).total_seconds() == 600
    state = _db_state(campaign_client, scene, "round-l-boundary")
    capabilities = state["actor_snapshot"]["communication_capabilities"]
    assert capabilities == [
        {
            "capability_id": f"{SPELL_ID}:self:beast",
            "clause_id": "communication_capability",
            "content_id": SPELL_ID,
            "creature_kind": "beast",
            "duration_unit": "minutes",
            "duration_value": 10,
            "expires_at": receipt["expires_at"],
            "influence_action_skills": ["deception", "intimidation", "persuasion"],
            "information_scope": "surroundings_and_monsters",
            "recent_observation_hours": 24,
            "source_fingerprint": receipt["source_fingerprint"],
            "source_record_id": receipt["source_record_id"],
            "started_at": receipt["started_at"],
            "target_scope": "self",
        }
    ]
    assert result["communication"]["observation_age_hours"] == 24
    assert result["communication"]["recent_observation_boundary_hours"] == 24


def test_round_l_replay_is_exact_and_payload_drift_rejected(
    campaign_client: TestClient,
) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, "round-l-replay")
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    before = _db_state(campaign_client, scene, "round-l-replay")
    replay = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["communication_capability_receipt"] == confirmed.json()[
        "communication_capability_receipt"
    ]
    assert replay.json()["operation_transaction_id"] == confirmed.json()[
        "operation_transaction_id"
    ]
    after = _db_state(campaign_client, scene, "round-l-replay")
    assert after["transaction_count"] == before["transaction_count"] == 1
    assert after["actor_version"] == before["actor_version"]
    assert after["beast_version"] == before["beast_version"]
    drift = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={
            **body,
            "preview_token": preview.json()["preview_token"],
            "communication_influence_skill": "deception",
        },
    )
    assert drift.status_code == 400
    assert "replay payload" in str(drift.json())


def _bump_version(client: TestClient, combatant_id: str) -> None:
    engine = create_engine(client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        session.execute(
            update(Combatant)
            .where(Combatant.id == combatant_id)
            .values(version=Combatant.version + 1)
        )


def test_round_l_character_cas_rejects_after_preview(campaign_client: TestClient) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, "round-l-character-cas")
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    response = campaign_client.patch(
        f"{scene['base']}/characters/{scene['character']['id']}",
        headers={"If-Match": str(scene["character"]["version"])},
        json={"hp": 19},
    )
    assert response.status_code == 200, response.text
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 409


def test_round_l_actor_cas_rejects_after_preview(campaign_client: TestClient) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, "round-l-actor-cas")
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    _bump_version(campaign_client, scene["actor"]["id"])
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 409


def test_round_l_beast_cas_rejects_after_preview(campaign_client: TestClient) -> None:
    scene = _setup(campaign_client)
    body = _body(scene, "round-l-beast-cas")
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    _bump_version(campaign_client, scene["beast"]["id"])
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 409


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_fingerprint", "z" * 64),
        ("clause_id", ""),
        ("duration_value", 11),
        ("creature_kind", "celestial"),
        ("target_scope", "ally"),
        ("influence_action_skills", ["deception", "persuasion"]),
    ],
)
def test_round_l_invalid_runtime_contract_rejects(
    campaign_client: TestClient, field: str, value: object
) -> None:
    runtime = _runtime()
    if field == "source_fingerprint":
        runtime["source"]["source_fingerprint"] = value
    else:
        for clause in runtime["resolution"]["communication_capability"]:
            clause[field] = value
    scene = _setup(campaign_client, runtime)
    response = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=_body(scene, f"round-l-invalid-{field}"),
    )
    assert response.status_code == 400, response.text
