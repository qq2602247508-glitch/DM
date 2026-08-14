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
from dnd_dm_assistant.domain.typed_spell_object_effect_lifecycle import (
    TypedSpellObjectEffectSpec,
    apply_typed_spell_object_effect,
)
from dnd_dm_assistant.infrastructure.database.models import Combatant, OperationTransaction

ROOT = Path(__file__).resolve().parents[2]
AUTHORED = ROOT / (
    "data/content-ir/authored/batch-II/core-phb-2024/spells/"
    "core-phb-2024-spell-b9db026fa1853bca5b6f1c13.json"
)
SPELL_ID = "core-phb-2024:spell:b9db026fa1853bca5b6f1c13"


def _runtime() -> dict[str, Any]:
    compiled = compile_spell_spec(SpellSpec.from_dict(json.loads(AUTHORED.read_text())))
    assert compiled["compile_status"] == "full"
    runtime = compiled["runtime_spell_definition"]
    assert isinstance(runtime, dict)
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    assert [
        item["consumer_id"]
        for item in resolve_production_consumers(
            content_kind="spell", runtime_schema_version="spell-runtime-1", blocks=blocks
        )
    ] == ["spell.object_effect.lifecycle.v1"]
    return runtime


def _spec() -> TypedSpellObjectEffectSpec:
    block = ContentIRRuntimeService._runtime_blocks(_runtime())["object_effect_lifecycle"][0]
    return TypedSpellObjectEffectSpec(
        content_id=SPELL_ID,
        source_record_id="b9db026fa1853bca5b6f1c13",
        source_fingerprint="a" * 64,
        clause_id="object_effect_lifecycle",
        source_id=SPELL_ID,
        range_ft=block["range_ft"],
        max_concurrent_noninstant=block["max_concurrent_noninstant"],
        modes=tuple(block["modes"]),
    )


def test_round_liii_source_contract_has_all_six_modes_and_generic_registry() -> None:
    runtime = _runtime()
    block = ContentIRRuntimeService._runtime_blocks(runtime)["object_effect_lifecycle"][0]
    assert block["range_ft"] == 10
    assert block["max_concurrent_noninstant"] == 3
    assert {item["mode"] for item in block["modes"]} == {
        "sensory_effect",
        "fire_play",
        "clean_or_soil",
        "minor_sensation",
        "magic_mark",
        "minor_creation",
    }


def test_round_liii_domain_validates_modes_size_expiry_slots_and_replay() -> None:
    spec = _spec()
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    state: dict[str, Any] = {"version": 0, "object_effects": []}
    state, sensory = apply_typed_spell_object_effect(
        spec,
        state=state,
        expected_version=0,
        now=now,
        mode="sensory_effect",
        target_kind="none",
        target_id=None,
        distance_ft=10,
        size_cubic_ft=None,
        nonliving=False,
        payload={"sensory_kind": "spark"},
        current_turn=4,
    )
    assert sensory.lifecycle == "instant"
    assert state["object_effects"] == []
    with pytest.raises(ValueError, match="one cubic foot"):
        apply_typed_spell_object_effect(
            spec,
            state=state,
            expected_version=1,
            now=now,
            mode="clean_or_soil",
            target_kind="object",
            target_id="obj",
            distance_ft=10,
            size_cubic_ft=1.1,
            nonliving=False,
            payload={"operation": "clean"},
            current_turn=4,
        )
    for index, mode in enumerate(("minor_sensation", "magic_mark", "minor_creation"), start=1):
        payload = (
            {"sensation": "warm"}
            if mode == "minor_sensation"
            else {"mark_kind": "sigil"}
            if mode == "magic_mark"
            else {
                "creation_kind": "trinket",
                "nonmagical": True,
                "no_damage": True,
                "no_value": True,
            }
        )
        state, receipt = apply_typed_spell_object_effect(
            spec,
            state=state,
            expected_version=state["version"],
            now=now,
            mode=mode,
            target_kind=(
                "nonliving_material"
                if mode == "minor_sensation"
                else "object"
                if mode == "magic_mark"
                else "creation_space"
            ),
            target_id=f"target-{index}",
            distance_ft=5,
            size_cubic_ft=1 if mode != "minor_creation" else 0.5,
            nonliving=mode == "minor_sensation",
            payload=payload,
            current_turn=4,
        )
        assert receipt.mode == mode
    with pytest.raises(ValueError, match="three different"):
        apply_typed_spell_object_effect(
            spec,
            state=state,
            expected_version=state["version"],
            now=now,
            mode="magic_mark",
            target_kind="surface",
            target_id="surface-4",
            distance_ft=5,
            size_cubic_ft=None,
            nonliving=False,
            payload={"mark_kind": "stain"},
            current_turn=4,
        )
    replay_state, replay = apply_typed_spell_object_effect(
        spec,
        state=state,
        expected_version=state["version"],
        now=now,
        mode="minor_creation",
        target_kind="creation_space",
        target_id="target-3",
        distance_ft=5,
        size_cubic_ft=0.5,
        nonliving=False,
        payload={
            "creation_kind": "trinket",
            "nonmagical": True,
            "no_damage": True,
            "no_value": True,
        },
        current_turn=4,
        prior_receipt=receipt,
    )
    assert replay_state == state
    assert replay.replayed is True
    with pytest.raises(ValueError, match="replay payload"):
        apply_typed_spell_object_effect(
            spec,
            state=state,
            expected_version=state["version"],
            now=now + timedelta(seconds=1),
            mode="minor_creation",
            target_kind="creation_space",
            target_id="target-3",
            distance_ft=5,
            size_cubic_ft=0.5,
            nonliving=False,
            payload={
                "creation_kind": "trinket",
                "nonmagical": True,
                "no_damage": True,
                "no_value": True,
            },
            current_turn=4,
            prior_receipt=receipt,
        )


def _setup(client: TestClient) -> dict[str, Any]:
    runtime = _runtime()
    campaign = client.post("/api/v1/campaigns", json={"name": "Round LIII object effect"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "object effect caster",
            "level": 1,
            "hp": 10,
            "max_hp": 10,
            "spellcasting": {"slots": {"1": {"current": 4, "max": 4}}},
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
    scene = client.post(f"{base}/scenes", json={"name": "object effect scene"}).json()
    client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = client.post(
        f"{base}/combats", json={"name": "object effect combat", "scene_id": scene["id"]}
    ).json()
    actor = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "object effect caster",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 10,
            "hp": 10,
            "max_hp": 10,
            "snapshot_json": {"grid_position": {"row": 5, "col": 5}},
        },
    ).json()
    return {"base": base, "character": character, "known": known, "combat": combat, "actor": actor}


def _body(scene: dict[str, Any], *, mode: str, key: str) -> dict[str, Any]:
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": 1,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "object_effect_mode": mode,
        "object_effect_target_kind": "object",
        "object_effect_target_id": f"object-{mode}",
        "object_effect_distance_ft": 10,
        "object_effect_size_cubic_ft": 1,
        "object_effect_operation": "clean",
        "object_effect_mark_kind": "sigil",
        "idempotency_key": key,
    }


def test_round_liii_api_receipt_snapshot_transaction_and_dismissal(
    campaign_client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setenv("DND_DM_OBJECT_EFFECT_NOW", "2026-08-14T12:00:00+00:00")
    scene = _setup(campaign_client)
    body = _body(scene, mode="magic_mark", key="round-liii-object-effect")
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_json = preview.json()
    assert preview_json["production_contract"]["consumers"] == [
        "spell.object_effect.lifecycle.v1"
    ]
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview_json["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["consumer"] == "spell.object_effect.lifecycle.v1"
    assert result["object_effect_receipt"]["mode"] == "magic_mark"
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
            "object_effect_mark_kind": "stain",
        },
    )
    assert drift.status_code == 400
    terminated = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/object-effect/terminate",
        json={
            **body,
            "actor_version": result["actor_version_after"],
            "object_effect_id": result["object_effect_receipt"]["effect_id"],
            "object_effect_termination_reason": "dismiss",
            "idempotency_key": "round-liii-object-dismiss",
        },
    )
    assert terminated.status_code == 200, terminated.text
    assert terminated.json()["object_effect_receipt"]["termination"] == "dismiss"
    engine = create_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    try:
        with Session(engine) as session:
            actor = session.scalar(select(Combatant).where(Combatant.id == scene["actor"]["id"]))
            operation = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.id == result["operation_transaction_id"]
                )
            )
            assert actor is not None and operation is not None
            assert actor.snapshot_json["object_effects"][0]["termination"] == "dismiss"
            assert operation.operation_type == "content_ir_object_effect_lifecycle"
            assert operation.after_snapshot["object_effect_receipt"] == result[
                "object_effect_receipt"
            ]
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("mode", "target_kind", "size", "extra"),
    [
        ("sensory_effect", "none", None, {"object_effect_sensory_kind": "spark"}),
        (
            "fire_play",
            "fire_source",
            None,
            {
                "object_effect_target_id": "torch-1",
                "object_effect_fire_source": "torch",
                "object_effect_operation": "ignite",
            },
        ),
        ("clean_or_soil", "object", 1, {"object_effect_operation": "clean"}),
        (
            "minor_sensation",
            "nonliving_material",
            1,
            {"object_effect_nonliving": True, "object_effect_sensation": "warm"},
        ),
        ("magic_mark", "surface", None, {"object_effect_mark_kind": "sigil"}),
        (
            "minor_creation",
            "creation_space",
            0.5,
            {
                "object_effect_creation_kind": "trinket",
                "object_effect_nonmagical": True,
                "object_effect_no_damage": True,
                "object_effect_no_value": True,
            },
        ),
    ],
)
def test_round_liii_api_executes_each_source_mode(
    campaign_client: TestClient,
    monkeypatch: Any,
    mode: str,
    target_kind: str,
    size: float | None,
    extra: dict[str, Any],
) -> None:
    monkeypatch.setenv("DND_DM_OBJECT_EFFECT_NOW", "2026-08-14T12:00:00+00:00")
    scene = _setup(campaign_client)
    body = {
        **_body(scene, mode=mode, key=f"round-liii-mode-{mode}"),
        "object_effect_target_kind": target_kind,
        "object_effect_size_cubic_ft": size,
        **extra,
    }
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["object_effect_receipt"]["mode"] == mode


def test_round_liii_api_rejects_mode_target_size_range_and_expiry(
    campaign_client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setenv("DND_DM_OBJECT_EFFECT_NOW", "2026-08-14T12:00:00+00:00")
    scene = _setup(campaign_client)
    body = _body(scene, mode="magic_mark", key="round-liii-boundaries")
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "object_effect_mode": "unsupported"},
    ).status_code == 422
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "object_effect_target_kind": "fire_source"},
    ).status_code == 400
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={
            **body,
            "object_effect_mode": "clean_or_soil",
            "object_effect_target_kind": "object",
            "object_effect_size_cubic_ft": 1.1,
            "object_effect_operation": "clean",
        },
    ).status_code == 400
    assert campaign_client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json={**body, "object_effect_distance_ft": 11},
    ).status_code == 400
    preview = campaign_client.post(f"{scene['base']}/content-ir/runtime/preview", json=body).json()
    confirmed = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview["preview_token"]},
    ).json()
    monkeypatch.setenv("DND_DM_OBJECT_EFFECT_NOW", "2026-08-14T13:00:00+00:00")
    expired = campaign_client.post(
        f"{scene['base']}/content-ir/runtime/object-effect/terminate",
        json={
            **body,
            "actor_version": confirmed["actor_version_after"],
            "object_effect_id": confirmed["object_effect_receipt"]["effect_id"],
            "object_effect_termination_reason": "expiry",
            "idempotency_key": "round-liii-expiry",
        },
    )
    assert expired.status_code == 200, expired.text
    assert expired.json()["object_effect_receipt"]["termination"] == "expiry"


def test_round_liii_api_enforces_three_noninstant_slots(
    campaign_client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setenv("DND_DM_OBJECT_EFFECT_NOW", "2026-08-14T12:00:00+00:00")
    scene = _setup(campaign_client)
    current = scene
    modes = (
        (
            "magic_mark",
            {"object_effect_target_kind": "surface", "object_effect_mark_kind": "sigil"},
        ),
        (
            "minor_sensation",
            {
                "object_effect_target_kind": "nonliving_material",
                "object_effect_nonliving": True,
                "object_effect_sensation": "warm",
            },
        ),
        (
            "minor_creation",
            {
                "object_effect_target_kind": "creation_space",
                "object_effect_size_cubic_ft": 0.5,
                "object_effect_creation_kind": "trinket",
                "object_effect_nonmagical": True,
                "object_effect_no_damage": True,
                "object_effect_no_value": True,
            },
        ),
    )
    for index, (mode, extra) in enumerate(modes):
        body = {
            **_body(current, mode=mode, key=f"round-liii-slot-{index}"),
            **extra,
        }
        preview = campaign_client.post(
            f"{current['base']}/content-ir/runtime/preview", json=body
        ).json()
        result = campaign_client.post(
            f"{current['base']}/content-ir/runtime/confirm",
            json={**body, "preview_token": preview["preview_token"]},
        )
        assert result.status_code == 200, result.text
        current = {
            **current,
            "character": {
                **current["character"],
                "version": result.json()["spell_cast"]["character_version_after"],
            },
            "actor": {
                **current["actor"],
                "version": result.json()["actor_version_after"],
            },
        }
