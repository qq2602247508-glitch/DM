# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.rules_kernel_protocol import KernelPosition, RulesKernelCommand
from dnd_dm_assistant.domain.spatial_authority import DeterministicTestSpatialAuthority
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import (
    Campaign,
    Combat,
    Combatant,
    CompendiumEntry,
    OperationTransaction,
    Scene,
    SceneGrid,
)


def test_protocol_is_closed_and_versioned() -> None:
    command = RulesKernelCommand(
        command_id="command-1",
        idempotency_key="idempotency-1",
        campaign_id="campaign-1",
        actor_id="actor-1",
        content_id="typed-content-1",
        content_kind="spell",
    )
    assert command.schema_version == "rules-kernel-1"
    try:
        RulesKernelCommand.model_validate({**command.model_dump(), "unknown": True})
    except ValueError as exc:
        assert "extra" in str(exc)
    else:
        raise AssertionError("unknown protocol fields must fail closed")
    try:
        RulesKernelCommand.model_validate({**command.model_dump(), "schema_version": "rules-kernel-999"})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown protocol versions must fail closed")


def test_deterministic_spatial_authority_covers_footprints_and_path() -> None:
    authority = DeterministicTestSpatialAuthority(width=10, height=10, cell_size_ft=5)
    authority.blocked.add((3, 3))
    authority.cover_cells.add((2, 2))
    authority.add_entity("large", KernelPosition(row=1, col=1), size_cells=2)
    authority.add_entity("target", KernelPosition(row=1, col=5))
    assert authority.get_entity_bounds("large")["row_max"] == 2
    assert authority.distance_between("large", "target") == 15
    assert authority.has_line_of_sight("large", "target") is True
    assert authority.get_cover("large", "target") in {"none", "half"}
    assert authority.is_space_occupied(KernelPosition(row=1, col=1)) is True
    nearest = authority.find_nearest_unoccupied_space(KernelPosition(row=1, col=1))
    assert nearest != KernelPosition(row=1, col=1)
    path = authority.validate_path(
        "target",
        (KernelPosition(row=1, col=5), KernelPosition(row=2, col=5)),
        maximum_distance_ft=5,
    )
    assert path.legal is True


def _seed_kernel_graph(client: TestClient) -> dict[str, str]:
    engine = create_database_engine(client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        campaign = Campaign(name="Kernel test campaign")
        session.add(campaign)
        session.flush()
        scene = Scene(campaign_id=campaign.id, name="Kernel test scene")
        session.add(scene)
        session.flush()
        session.add(SceneGrid(scene_id=scene.id, width=10, height=10, cell_size_ft=5, mode="combat"))
        combat = Combat(campaign_id=campaign.id, scene_id=scene.id, name="Kernel combat")
        session.add(combat)
        session.flush()
        actor = Combatant(
            combat_id=combat.id,
            entity_type="character",
            entity_id="character-1",
            display_name="Caster",
            hp=20,
            max_hp=20,
            snapshot_json={"grid_position": {"row": 2, "col": 2, "elevation_ft": 0}, "size_cells": 1},
        )
        target = Combatant(
            combat_id=combat.id,
            entity_type="monster",
            entity_id="monster-1",
            display_name="Target",
            hp=20,
            max_hp=20,
            snapshot_json={"grid_position": {"row": 2, "col": 4, "elevation_ft": 0}, "size_cells": 1},
        )
        session.add_all([actor, target])
        profile = CompendiumEntry(
            campaign_id=campaign.id,
            entry_type="monster",
            name="Known Kernel Wolf",
            source_kind="official",
            rules_json={"display_name": "Kernel Wolf", "max_hp": 12, "armor_class": 13, "speed_ft": 30, "size_cells": 1},
        )
        session.add(profile)
        session.flush()
        return {"campaign_id": campaign.id, "scene_id": scene.id, "combat_id": combat.id, "actor_id": actor.id, "target_id": target.id, "profile_id": profile.id}


def _damage_command(ids: dict[str, str], command_id: str = "command-damage-1") -> dict[str, Any]:
    return {
        "schema_version": "rules-kernel-1",
        "command_id": command_id,
        "idempotency_key": f"idempotency-{command_id}",
        "campaign_id": ids["campaign_id"],
        "scene_id": ids["scene_id"],
        "combat_id": ids["combat_id"],
        "actor_id": ids["actor_id"],
        "content_id": "typed-content:damage",
        "content_kind": "spell",
        "action_kind": "content",
        "target_intent": {"target_ids": [ids["target_id"]], "target_kind": "one_creature"},
        "roll_inputs": {"resolution_total": 7},
        "expected_versions": {"actor_version": 1, "target_versions": {ids["target_id"]: 1}, "combat_version": 1, "scene_version": 1},
        "metadata": {"clause_types": ["damage"], "effects": [{"kind": "damage", "amount": 7, "damage_type": "force"}]},
    }


def test_rules_kernel_api_preview_confirm_replay_and_scene_cursor(campaign_client: TestClient) -> None:
    ids = _seed_kernel_graph(campaign_client)
    command = _damage_command(ids)
    preview = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "ready"
    confirmed = campaign_client.post(
        "/api/v1/rules-kernel/confirm",
        json={**command, "preview_version": preview.json()["preview_version"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["status"] == "confirmed"
    assert result["damage_results"][0]["hp_after"] == 13
    assert result["scene_delta"][0]["delta_type"] == "update_health"
    replay = campaign_client.post(
        "/api/v1/rules-kernel/confirm",
        json={**command, "preview_version": preview.json()["preview_version"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    deltas = campaign_client.get(
        "/api/v1/rules-kernel/scene-deltas",
        params={"campaign_id": ids["campaign_id"], "scene_id": ids["scene_id"]},
    )
    assert deltas.status_code == 200
    assert deltas.json()["next_cursor"] == 1
    assert len(deltas.json()["deltas"]) == 1
    query = campaign_client.post(
        "/api/v1/rules-kernel/scene-query",
        params={"campaign_id": ids["campaign_id"]},
        json={"schema_version": "scene-query-1", "query_id": "query-1", "scene_id": ids["scene_id"], "combat_id": ids["combat_id"], "query_kind": "distance", "entity_ids": [ids["actor_id"], ids["target_id"]]},
    )
    assert query.status_code == 200, query.text
    assert query.json()["result"] == 10


def test_choice_window_freezes_options_and_confirm_is_idempotent(campaign_client: TestClient) -> None:
    ids = _seed_kernel_graph(campaign_client)
    command = {
        **_damage_command(ids, "command-choice-1"),
        "content_kind": "system",
        "content_id": None,
        "action_kind": "choice",
        "metadata": {"clause_types": ["choice"], "choice": {"choice_kind": "fixed_options", "options": ["a", "b"], "minimum_choices": 1, "maximum_choices": 1}},
    }
    preview = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["status"] == "pending_choice"
    window_id = body["required_choices"][0]["choice_window_id"]
    resolved = campaign_client.post(
        f"/api/v1/rules-kernel/choices/{window_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "player", "actor_id": ids["actor_id"], "values": ["b"], "expected_version": 1, "idempotency_key": "choice-idem-1"},
    )
    assert resolved.status_code == 200, resolved.text
    resolved_replay = campaign_client.post(
        f"/api/v1/rules-kernel/choices/{window_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "player", "actor_id": ids["actor_id"], "values": ["b"], "expected_version": 2, "idempotency_key": "choice-idem-1"},
    )
    assert resolved_replay.status_code == 200, resolved_replay.text
    assert resolved_replay.json()["idempotent_replay"] is True
    confirmed = campaign_client.post(
        "/api/v1/rules-kernel/confirm",
        json={**command, "preview_version": 1, "confirmed_choices": [{"key": "selection", "values": ["b"]}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"


def test_dm_adjudication_requires_dm_and_then_continues(campaign_client: TestClient) -> None:
    ids = _seed_kernel_graph(campaign_client)
    command = {
        **_damage_command(ids, "command-adjudication-1"),
        "content_kind": "system",
        "content_id": "typed-content:freeform",
        "action_kind": "adjudication",
        "target_intent": {"target_kind": "freeform", "semantic": "freeform"},
        "expected_versions": {"actor_version": 1, "combat_version": 1, "scene_version": 1},
        "metadata": {"clause_types": ["target_semantics"], "adjudication": {"category": "target_semantics", "source_text_evidence": "A typed clause leaves the target relationship open.", "allowed_decision_schema": ["approved_targets", "notes"]}},
    }
    preview = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "pending_adjudication"
    adjudication_id = preview.json()["required_adjudications"][0]["adjudication_id"]
    player = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "player", "status": "approved"},
    )
    assert player.status_code == 400
    decision = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "dm", "expected_version": 1, "decision": {"adjudication_id": adjudication_id, "status": "approved", "approved_targets": [ids["target_id"]]}},
    )
    assert decision.status_code == 200, decision.text
    decision_replay = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={"permission": "dm", "decision": {"adjudication_id": adjudication_id, "status": "approved", "approved_targets": [ids["target_id"]]}},
    )
    assert decision_replay.status_code == 200, decision_replay.text
    assert decision_replay.json()["idempotent_replay"] is True
    confirmed = campaign_client.post(
        "/api/v1/rules-kernel/confirm",
        json={**command, "preview_version": 1, "adjudication_decisions": [{"adjudication_id": adjudication_id, "status": "approved", "approved_targets": [ids["target_id"]]}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"


def test_typed_adjudication_is_source_bound_and_emits_receipt(campaign_client: TestClient) -> None:
    ids = _seed_kernel_graph(campaign_client)
    source_binding = {
        "content_id": "core-phb-2024:spell:typed-seam",
        "source_record_id": "typed-seam-record",
        "source_fingerprint": "a" * 64,
        "clause_ids": ["core-phb-2024:spell:typed-seam:clause:target"],
    }
    typed_contract = {
        "decision_kind": "target_selection",
        "target_context": {
            "campaign_id": ids["campaign_id"],
            "scene_id": ids["scene_id"],
            "actor_id": ids["actor_id"],
            "target_kind": "single_entity",
            "target_id": ids["target_id"],
            "target_type": "creature",
        },
        "effect_envelope": {
            "allowed_effect_kinds": ["modifier"],
            "allowed_fields": ["stat", "operation", "value", "duration"],
            "duration": {"unit": "rounds", "value": 1},
            "source_semantics": ["typed-target"],
        },
        "source_binding": source_binding,
    }
    command = {
        **_damage_command(ids, "command-typed-adjudication-1"),
        "content_id": source_binding["content_id"],
        "action_kind": "adjudication",
        "target_intent": {
            "target_ids": [ids["target_id"]],
            "target_kind": "one_creature",
            "semantic": "typed",
        },
        "metadata": {
            "clause_types": ["target_semantics"],
            "adjudication": {
                "category": "target_semantics",
                "source_text_evidence": "Source-bound typed target contract.",
                "allowed_decision_schema": ["approved_targets", "notes"],
            },
            "typed_adjudication": typed_contract,
        },
    }
    preview = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert preview.status_code == 200, preview.text
    request = preview.json()["required_adjudications"][0]
    assert request["frozen_context"]["typed_contract"]["schema_version"] == "typed-adjudication-1"
    assert request["frozen_context"]["typed_contract"]["source_binding"] == source_binding
    adjudication_id = request["adjudication_id"]
    decision = {
        "adjudication_id": adjudication_id,
        "status": "approved",
        "approved_targets": [ids["target_id"]],
        "typed_contract": request["frozen_context"]["typed_contract"],
    }
    resolved = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={
            "permission": "dm",
            "expected_version": 1,
            "idempotency_key": "typed-adjudication-idem-1",
            "decision": decision,
        },
    )
    assert resolved.status_code == 200, resolved.text
    drift = campaign_client.post(
        f"/api/v1/rules-kernel/adjudications/{adjudication_id}/resolve",
        params={"campaign_id": ids["campaign_id"]},
        json={
            "permission": "dm",
            "idempotency_key": "typed-adjudication-idem-drift",
            "decision": decision,
        },
    )
    assert drift.status_code == 400
    assert "payload drift" in drift.text
    confirmed = campaign_client.post(
        "/api/v1/rules-kernel/confirm",
        json={**command, "preview_version": 1, "adjudication_decisions": [decision]},
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["operation_transaction_id"]
    assert result["adjudication_receipt"]["source_fingerprint"] == "a" * 64
    assert result["adjudication_receipt"]["producer_provenance"]["source_bound"] is True
    replay = campaign_client.post(
        "/api/v1/rules-kernel/confirm",
        json={**command, "preview_version": 1, "adjudication_decisions": [decision]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True

    engine = create_database_engine(campaign_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session:
        tx = session.get(OperationTransaction, result["operation_transaction_id"])
        assert tx is not None
        assert tx.after_snapshot["producer_provenance"]["contract_schema"] == "typed-adjudication-1"


def test_typed_adjudication_rejects_wrong_source_and_target_bindings(campaign_client: TestClient) -> None:
    ids = _seed_kernel_graph(campaign_client)
    command = {
        **_damage_command(ids, "command-typed-binding-1"),
        "content_id": "core-phb-2024:spell:typed-binding",
        "action_kind": "adjudication",
        "target_intent": {"target_kind": "one_creature", "target_ids": [ids["target_id"]]},
        "metadata": {
            "clause_types": ["target_semantics"],
            "adjudication": {"source_text_evidence": "Binding test."},
            "typed_adjudication": {
                "decision_kind": "target_selection",
                "target_context": {
                    "campaign_id": ids["campaign_id"],
                    "scene_id": ids["scene_id"],
                    "actor_id": ids["actor_id"],
                    "target_kind": "single_entity",
                    "target_id": ids["actor_id"],
                    "target_type": "creature",
                },
                "effect_envelope": {"allowed_effect_kinds": ["capability"]},
                "source_binding": {
                    "content_id": "different-content",
                    "source_record_id": "record",
                    "source_fingerprint": "b" * 64,
                    "clause_ids": ["clause"],
                },
            },
        },
    }
    response = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert response.status_code == 400
    assert "binding mismatch" in response.text


def test_known_profile_summon_uses_existing_combat_and_scene_records(campaign_client: TestClient) -> None:
    ids = _seed_kernel_graph(campaign_client)
    command = {
        **_damage_command(ids, "command-summon-1"),
        "content_kind": "spell",
        "content_id": "typed-content:summon",
        "action_kind": "summon_known_profile",
        "target_intent": {"target_kind": "none"},
        "expected_versions": {"actor_version": 1, "combat_version": 1, "scene_version": 1},
        "spatial_intent": {"destination": {"row": 4, "col": 4}, "entity_profile_id": ids["profile_id"], "movement_kind": "teleport"},
        "metadata": {"clause_types": ["summon_known_profile"]},
    }
    preview = campaign_client.post("/api/v1/rules-kernel/preview", json=command)
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post("/api/v1/rules-kernel/confirm", json={**command, "preview_version": 1})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["entity_results"][0]["profile_id"] == ids["profile_id"]
    assert confirmed.json()["scene_delta"][0]["delta_type"] == "spawn_entity"
