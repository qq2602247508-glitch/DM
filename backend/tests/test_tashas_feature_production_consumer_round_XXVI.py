from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_production_evidence import (
    load_production_runtime_evidence,
)
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.tashas_whole_pack import (
    PACK_ID,
    build_migration,
    existing_project_production_ids,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XXVI-2026-08-12.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXVII.json"
AMBUSH_PATH = (
    ROOT
    / "data/content-ir/authored/official-packs/tashas-cauldron/features/features/"
    "content-tashas-cauldron-feature-battle-master-ambush.json"
)


def _ambush_contract() -> tuple[FeatureSpec, dict[str, Any]]:
    payload = json.loads(AMBUSH_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: value for key, value in payload.items() if key in FeatureSpec._FIELDS},
        path=str(AMBUSH_PATH),
    )
    compiled = FeatureCompiler(status_authority="compiler").compile(spec)
    assert compiled.compile_status == "full", compiled.blockers
    return spec, materialize_runtime_definition(spec, compiled)


def test_round_xxvi_receipt_matches_current_pack_projection() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    migration = build_migration(ROOT)
    feature_id = "content.tashas-cauldron.feature.battle-master.ambush"

    assert report["all_required_checks_passed"] is True
    assert results["all_required_checks_passed"] is True
    assert report["selected_feature_ids"] == [feature_id]
    assert results["production_runtime_full_ids"] == [feature_id]
    assert report["production_consumer"] == "combat_engine.roll_intervention.v1"
    assert results["evidence_by_id"][feature_id]["typed_consumer"] == (
        "combat_engine.roll_intervention.v1"
    )
    assert report["formal_registry_written"] is False
    assert report["formal_database_written"] is False
    assert report["name_branch_count"] == 0
    assert all(value is True for value in report["checks"].values())
    assert all(value is True for value in results["checks"].values())
    assert migration["production_full"] == 103
    assert migration["dm_assisted"] == 2
    assert migration["game_usable"] == 105
    assert migration["compile_only"] == 0
    assert migration["content_id_funnel"]["relation_holds"] is True
    assert len(load_production_runtime_evidence(ROOT, pack_id=PACK_ID)) == 146
    assert len(existing_project_production_ids(ROOT)) == 204


def test_ambush_is_typed_as_two_generic_roll_intervention_clauses() -> None:
    spec, contract = _ambush_contract()

    assert {clause.clause_id for clause in spec.clauses} == {
        "ambush:stealth",
        "ambush:initiative",
    }
    actions = contract["actions"]
    assert set(actions) == {"ambush:stealth", "ambush:initiative"}

    stealth = actions["ambush:stealth"]
    initiative = actions["ambush:initiative"]
    assert stealth["kind"] == "roll_intervention"
    assert stealth["trigger"] == "after_d20_test"
    assert stealth["source_trigger"] == "ability_check"
    assert stealth["eligibility"]["test_kinds"] == ["ability_check", "skill_check"]
    assert stealth["eligibility"]["abilities"] == ["dexterity"]
    assert stealth["eligibility"]["skills"] == ["stealth"]

    assert initiative["kind"] == "roll_intervention"
    assert initiative["trigger"] == "after_d20_test"
    assert initiative["source_trigger"] == "initiative_rolled"
    assert initiative["eligibility"]["test_kinds"] == ["initiative"]
    consumers = resolve_production_consumers(
        content_kind="feature",
        runtime_schema_version="feature-runtime-1",
        blocks={"roll_intervention": [initiative]},
    )
    assert [item["consumer_id"] for item in consumers] == [
        "combat_engine.roll_intervention.v1"
    ]


def test_ambush_initiative_window_is_confirmed_through_http_and_replayed(
    campaign_client: Any,
    monkeypatch: Any,
) -> None:
    from dnd_dm_assistant.infrastructure.database import world_service

    _spec, contract = _ambush_contract()
    runtime = {
        "actions": contract["actions"],
        "resources": {
            "superiority_dice": {
                "key": "superiority_dice",
                "current": 4,
                "max": 4,
                "value": "d8",
            }
        },
        "progression": {"class_levels": {"战士": 3}},
    }
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "Tasha Round XXVI initiative intervention"},
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "伏击战斗大师",
            "class_name": "战士",
            "level": 3,
            "ability_scores": {"dexterity": 14},
            "resources": {
                "superiority_dice": {"current": 4, "max": 4, "value": "d8"}
            },
            "features": [
                {
                    "name": "战技选项：伏击",
                    "kind": "maneuver",
                    "class_name": "战士",
                    "class_level": 3,
                    "runtime": {"automation_status": "full", "registry": runtime},
                }
            ],
            "hp": 20,
            "max_hp": 20,
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    npc_response = campaign_client.post(
        f"{base}/npcs",
        json={
            "name": "训练木桩",
            "ability_scores": {"dexterity": 10},
            "hp": 8,
            "max_hp": 8,
        },
    )
    assert npc_response.status_code == 201, npc_response.text
    scene = campaign_client.post(f"{base}/scenes", json={"name": "伏击先攻场"}).json()
    for entity_type, entity_id in (
        ("character", character["id"]),
        ("npc", npc_response.json()["id"]),
    ):
        response = campaign_client.post(
            f"{base}/scenes/{scene['id']}/participants",
            json={"entity_type": entity_type, "entity_id": entity_id},
        )
        assert response.status_code == 201, response.text

    rolls = iter((9, 10, 8, 11))
    monkeypatch.setattr(world_service.secrets, "randbelow", lambda _upper: next(rolls))
    started = campaign_client.post(
        f"{base}/scenes/{scene['id']}/start-combat",
        json={},
    )
    assert started.status_code == 201, started.text
    character_roll = next(
        item
        for item in started.json()["initiative_rolls"]
        if item["entity_id"] == character["id"]
    )
    assert character_roll["pending_intervention"] is True
    window = character_roll["initiative_intervention_window"]
    assert [item["id"] for item in window] == ["ambush:initiative"]
    action_id = character_roll["initiative_action_id"]
    expected_total = character_roll["total"] + 7

    action = campaign_client.get(f"{base}/combats/{started.json()['combat']['id']}/actions").json()[
        "items"
    ]
    prompt = next(item for item in action if item["id"] == action_id)
    combat_root = f"{base}/combats/{started.json()['combat']['id']}"
    confirmed = campaign_client.post(
        f"{combat_root}/initiative-rolls/{action_id}/confirm",
        headers={"X-Request-ID": "tashas-round-XXVI-ambush-confirm"},
        json={
            "action_version": prompt["version"],
            "use_intervention": True,
            "intervention_id": "ambush:initiative",
            "intervention_inputs": {"superiority_die_roll": 7},
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    resolution = confirmed.json()["resolution"]
    assert resolution["effective_total"] == expected_total
    assert resolution["generic_resource_consumed"] == {
        "key": "superiority_dice",
        "cost": 1,
        "before": 4,
        "after": 3,
    }

    replay = campaign_client.post(
        f"{combat_root}/initiative-rolls/{action_id}/confirm",
        headers={"X-Request-ID": "tashas-round-XXVI-ambush-confirm"},
        json={
            "action_version": prompt["version"],
            "use_intervention": True,
            "intervention_id": "ambush:initiative",
            "intervention_inputs": {"superiority_die_roll": 7},
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["resolution"] == resolution
    persisted = campaign_client.get(f"{base}/characters/{character['id']}").json()
    assert persisted["resources"]["superiority_dice"]["current"] == 3


def test_ambush_stealth_branch_uses_the_same_generic_roll_consumer(
    campaign_client: Any,
) -> None:
    _spec, contract = _ambush_contract()
    runtime = {
        "actions": {"ambush:stealth": contract["actions"]["ambush:stealth"]},
        "resources": {
            "superiority_dice": {
                "key": "superiority_dice",
                "current": 4,
                "max": 4,
                "value": "d8",
            }
        },
        "progression": {"class_levels": {"战士": 3}},
    }
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "Tasha Round XXVI stealth intervention"},
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "隐匿伏击者",
            "class_name": "战士",
            "level": 3,
            "resources": {
                "superiority_dice": {"current": 4, "max": 4, "value": "d8"}
            },
            "features": [
                {
                    "name": "伏击",
                    "kind": "maneuver",
                    "class_name": "战士",
                    "class_level": 3,
                    "runtime": {"automation_status": "full", "registry": runtime},
                }
            ],
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    combat = campaign_client.post(f"{base}/combats", json={"name": "隐匿检定"}).json()
    actor = campaign_client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "隐匿伏击者",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "ability_scores": {"dexterity": 14},
                "feature_runtime": runtime,
            },
        },
    ).json()
    root = f"{base}/combats/{combat['id']}"
    pending = campaign_client.post(
        f"{root}/actions/player-rolls/pending",
        headers={"X-Request-ID": "tashas-round-XXVI-stealth-pending"},
        json={
            "actor_combatant_id": actor["id"],
            "actor_version": actor["version"],
            "target_combatant_id": actor["id"],
            "target_version": actor["version"],
            "action_cost": "none",
            "action_name": "隐匿",
            "resolution_type": "skill_check",
            "ability": "dexterity",
            "skill": "stealth",
            "dc": 20,
        },
    )
    assert pending.status_code == 200, pending.text
    opened = campaign_client.post(
        f"{root}/actions/player-rolls/{pending.json()['action']['id']}/confirm",
        headers={"X-Request-ID": "tashas-round-XXVI-stealth-open"},
        json={"action_version": pending.json()["action"]["version"], "roll_total": 12},
    )
    assert opened.status_code == 200, opened.text
    window = opened.json()["resolution"]["roll_intervention_window"]
    assert [item["id"] for item in window] == ["ambush:stealth"]


def test_initiative_intervention_can_be_declined_without_resource_mutation(
    campaign_client: Any,
    monkeypatch: Any,
) -> None:
    from dnd_dm_assistant.infrastructure.database import world_service

    _spec, contract = _ambush_contract()
    runtime = {
        "actions": {"ambush:initiative": contract["actions"]["ambush:initiative"]},
        "resources": {
            "superiority_dice": {
                "key": "superiority_dice",
                "current": 4,
                "max": 4,
                "value": "d8",
            }
        },
        "progression": {"class_levels": {"战士": 3}},
    }
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={"name": "Tasha Round XXVI decline initiative intervention"},
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{base}/characters",
        json={
            "name": "放弃伏击",
            "class_name": "战士",
            "level": 3,
            "resources": {
                "superiority_dice": {"current": 4, "max": 4, "value": "d8"}
            },
            "features": [
                {
                    "name": "伏击",
                    "kind": "maneuver",
                    "class_name": "战士",
                    "class_level": 3,
                    "runtime": {"automation_status": "full", "registry": runtime},
                }
            ],
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    scene = campaign_client.post(f"{base}/scenes", json={"name": "放弃窗口"}).json()
    participant = campaign_client.post(
        f"{base}/scenes/{scene['id']}/participants",
        json={"entity_type": "character", "entity_id": character["id"]},
    )
    assert participant.status_code == 201, participant.text
    monkeypatch.setattr(world_service.secrets, "randbelow", lambda _upper: 9)
    started = campaign_client.post(f"{base}/scenes/{scene['id']}/start-combat", json={})
    assert started.status_code == 201, started.text
    roll = started.json()["initiative_rolls"][0]
    combat_id = started.json()["combat"]["id"]
    action = campaign_client.get(f"{base}/combats/{combat_id}/actions").json()["items"][0]
    response = campaign_client.post(
        f"{base}/combats/{combat_id}/initiative-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "tashas-round-XXVI-decline"},
        json={"action_version": action["version"], "use_intervention": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["resolution"]["effective_total"] == roll["total"]
    persisted = campaign_client.get(f"{base}/characters/{character['id']}").json()
    assert persisted["resources"]["superiority_dice"]["current"] == 4
