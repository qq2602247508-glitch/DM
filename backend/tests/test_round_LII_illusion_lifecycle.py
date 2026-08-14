from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import SpellSpec, compile_spell_spec
from dnd_dm_assistant.domain.typed_spell_illusion_lifecycle import (
    TypedSpellIllusionSpec,
    apply_typed_spell_illusion,
    inspect_typed_spell_illusion,
    terminate_typed_spell_illusion,
)
from dnd_dm_assistant.infrastructure.database.models import Combatant, OperationTransaction

ROOT = Path(__file__).resolve().parents[2]
AUTHORED = ROOT / (
    "data/content-ir/authored/batch-II/core-phb-2024/spells/"
    "core-phb-2024-spell-83b7d94b77f332dd71310bbe.json"
)
SPELL_ID = "core-phb-2024:spell:83b7d94b77f332dd71310bbe"


def _runtime() -> dict[str, Any]:
    compiled = compile_spell_spec(SpellSpec.from_dict(json.loads(AUTHORED.read_text())))
    assert compiled["compile_status"] == "full"
    runtime = compiled["runtime_spell_definition"]
    assert isinstance(runtime, dict)
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=blocks,
    )
    assert [item["consumer_id"] for item in consumers] == ["spell.illusion.lifecycle.v1"]
    return runtime


def _spec() -> TypedSpellIllusionSpec:
    return TypedSpellIllusionSpec(
        content_id=SPELL_ID,
        source_record_id="83b7d94b77f332dd71310bbe",
        source_fingerprint="3" * 64,
        clause_id="illusion_lifecycle",
        source_id=SPELL_ID,
        target_id="actor",
        target_scope="self",
        duration_unit="hours",
        duration_value=1,
        height_delta_ft=-1,
        body_shape="variable",
        limb_arrangement="preserve",
        carried_envelope=("clothing", "armor", "weapons"),
        area_scope="caster-chosen illusion envelope",
        physical_inspection="passes_through",
        research_action="research",
        investigation_skill="intelligence_investigation",
        save_dc=14,
    )


def test_round_lii_source_contract_covers_bounds_and_registry() -> None:
    runtime = _runtime()
    block = ContentIRRuntimeService._runtime_blocks(runtime)["illusion_lifecycle"][0]
    assert runtime["source"]["source_record_id"] == "83b7d94b77f332dd71310bbe"
    assert len(runtime["source"]["source_fingerprint"]) == 64
    assert block["height_delta_range_ft"] == [-1, 1]
    assert block["limb_arrangement"] == "preserve"
    assert set(block["carried_envelope"]) == {"clothing", "armor", "weapons"}
    assert block["area_scope"] == "caster-chosen illusion envelope"


def test_round_lii_physical_inspection_and_research_use_persisted_save_dc() -> None:
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    state, receipt = apply_typed_spell_illusion(
        _spec(), state={"version": 0, "illusion_envelopes": []}, expected_version=0, now=now
    )
    row = state["illusion_envelopes"][0]
    assert row["height_delta_ft"] == -1
    assert row["limb_arrangement"] == "preserve"
    assert row["carried_envelope"] == ["clothing", "armor", "weapons"]
    assert row["area_scope"] == "caster-chosen illusion envelope"
    assert receipt.expires_at == (now + timedelta(hours=1)).isoformat()
    assert inspect_typed_spell_illusion(
        state,
        illusion_id=receipt.illusion_id,
        research_action="research",
        investigation_total=14,
        now=now + timedelta(minutes=5),
    )["discerned"] is True
    assert inspect_typed_spell_illusion(
        state,
        illusion_id=receipt.illusion_id,
        research_action="research",
        investigation_total=13,
        now=now + timedelta(minutes=5),
    )["discerned"] is False
    assert row["physical_inspection_result"] == "passes_through"
    assert row["save_dc"] == 14
    with pytest.raises(ValueError, match="research"):
        inspect_typed_spell_illusion(
            state,
            illusion_id=receipt.illusion_id,
            research_action="search",
            investigation_total=20,
            now=now,
        )


def test_round_lii_expiry_and_explicit_termination_are_state_transitions() -> None:
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    state, receipt = apply_typed_spell_illusion(
        _spec(), state={"version": 0, "illusion_envelopes": []}, expected_version=0, now=now
    )
    with pytest.raises(ValueError, match="expired"):
        inspect_typed_spell_illusion(
            state,
            illusion_id=receipt.illusion_id,
            research_action="research",
            investigation_total=20,
            now=now + timedelta(hours=1),
        )
    terminated = terminate_typed_spell_illusion(
        state, expected_version=1, illusion_id=receipt.illusion_id, reason="terminate"
    )
    assert terminated["version"] == 2
    assert terminated["illusion_envelopes"][0]["termination"] == "terminate"


def test_illusion_replay_rejects_payload_drift() -> None:
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    state, receipt = apply_typed_spell_illusion(
        _spec(), state={"version": 0, "illusion_envelopes": []}, expected_version=0, now=now
    )
    replay_state, replay = apply_typed_spell_illusion(
        _spec(),
        state=state,
        expected_version=1,
        now=now,
        prior_receipt=receipt,
    )
    assert replay_state == state
    assert replay.replayed is True
    with pytest.raises(ValueError, match="replay payload"):
        apply_typed_spell_illusion(
            _spec(),
            state=state,
            expected_version=1,
            now=now + timedelta(seconds=1),
            prior_receipt=receipt,
        )


def _setup(client: TestClient) -> dict[str, Any]:
    runtime = _runtime()
    campaign = client.post("/api/v1/campaigns", json={"name": "Round LII illusion"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "illusion caster",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {"slots": {"1": {"current": 2, "max": 2}}},
        },
    ).json()
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
    scene = client.post(f"{base}/scenes", json={"name": "illusion scene"}).json()
    client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = client.post(
        f"{base}/combats", json={"name": "illusion combat", "scene_id": scene["id"]}
    ).json()
    root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "illusion caster",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 5, "col": 5}},
        },
    ).json()
    return {"base": base, "character": character, "known": known, "combat": combat, "actor": actor}


def test_illusion_api_preview_confirm_persists_cas_transaction_and_replay(
    campaign_client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setenv("DND_DM_ILLUSION_NOW", "2026-08-14T12:00:00+00:00")
    scene = _setup(campaign_client)
    body = {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": 1,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "illusion_save_dc": 14,
        "illusion_height_delta_ft": -1,
        "illusion_body_shape": "variable",
        "illusion_limb_arrangement": "preserve",
        "illusion_carried_envelope": ["clothing", "armor", "weapons"],
        "illusion_area_scope": "caster-chosen illusion envelope",
        "illusion_research_action": "research",
        "illusion_investigation_total": 14,
        "idempotency_key": "round-lii-illusion",
    }
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_json = preview.json()
    assert preview_json["production_contract"]["consumers"] == ["spell.illusion.lifecycle.v1"]
    assert (
        preview_json["production_contract"]["illusion_lifecycle"][
            "physical_inspection_result"
        ]
        == "passes_through"
    )
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["consumer"] == "spell.illusion.lifecycle.v1"
    assert result["illusion_receipt"]["physical_inspection_result"] == "passes_through"
    assert result["inspection"]["discerned"] is True
    assert result["operation_transaction_id"]
    replay = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True
    drift = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"], "illusion_save_dc": 15},
    )
    assert drift.status_code == 400
    inspection = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/illusion/inspect",
        json={**body, "actor_version": result["actor_version_after"]},
    )
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()["inspection"]["discerned"] is True
    failed_inspection = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/illusion/inspect",
        json={
            **body,
            "actor_version": result["actor_version_after"],
            "illusion_investigation_total": 13,
        },
    )
    assert failed_inspection.status_code == 200
    assert failed_inspection.json()["inspection"]["discerned"] is False
    monkeypatch.setenv("DND_DM_ILLUSION_NOW", "2026-08-14T13:00:00+00:00")
    expired_inspection = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/illusion/inspect",
        json={**body, "actor_version": result["actor_version_after"]},
    )
    assert expired_inspection.status_code == 400
    monkeypatch.setenv("DND_DM_ILLUSION_NOW", "2026-08-14T12:00:00+00:00")
    terminated = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/illusion/terminate",
        json={
            **body,
            "actor_version": result["actor_version_after"],
            "idempotency_key": "round-lii-illusion-termination",
            "illusion_termination_reason": "terminate",
        },
    )
    assert terminated.status_code == 200, terminated.text
    assert terminated.json()["termination"] == "terminate"
    assert terminated.json()["persisted_snapshot"]["illusion_version"] == 2

    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    try:
        with Session(engine) as session:
            actor = session.scalar(
                select(Combatant).where(Combatant.id == scene["actor"]["id"])
            )
            operation = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.id == result["operation_transaction_id"]
                )
            )
            assert actor is not None
            assert operation is not None
            snapshot = actor.snapshot_json
            assert actor.version == scene["actor"]["version"] + 2
            assert snapshot["illusion_version"] == 2
            assert snapshot["illusion_envelopes"][0]["expires_at"] == result[
                "illusion_receipt"
            ]["expires_at"]
            assert snapshot["illusion_envelopes"][0]["termination"] == "terminate"
            assert operation.operation_type == "content_ir_illusion_lifecycle"
            assert operation.idempotency_key == "content-ir:round-lii-illusion:illusion"
            assert operation.after_snapshot["illusion_receipt"] == result["illusion_receipt"]
            termination_operation = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.id == terminated.json()["operation_transaction_id"]
                )
            )
            assert termination_operation is not None
            assert termination_operation.operation_type == "content_ir_illusion_termination"
    finally:
        engine.dispose()


def test_round_lii_api_rejects_cas_and_contract_boundaries(
    campaign_client: TestClient,
) -> None:
    scene = _setup(campaign_client)
    body = {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": 1,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "illusion_save_dc": 14,
        "illusion_height_delta_ft": -1,
        "illusion_body_shape": "variable",
        "illusion_limb_arrangement": "preserve",
        "illusion_carried_envelope": ["clothing", "armor", "weapons"],
        "illusion_area_scope": "caster-chosen illusion envelope",
        "idempotency_key": "round-lii-boundary",
    }
    stale_character = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "character_version": body["character_version"] - 1},
    )
    assert stale_character.status_code == 409
    stale_actor = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "actor_version": body["actor_version"] + 1},
    )
    assert stale_actor.status_code == 409
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "illusion_height_delta_ft": -2},
    ).status_code == 422
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "illusion_limb_arrangement": "change"},
    ).status_code == 422
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "illusion_carried_envelope": ["clothing"]},
    ).status_code == 400
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "illusion_area_scope": ""},
    ).status_code == 422

    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "runtime_id": "unbound-source-contract"},
    ).status_code == 400
