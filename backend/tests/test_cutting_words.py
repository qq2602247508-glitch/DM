from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.advancement_choices import subclass_feature_runtime_definition


@pytest.fixture
def client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'cutting-words.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _runtime() -> dict[str, Any]:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "语出惊人",
            "class_name": "吟游诗人",
            "class_level": 3,
            "source_record_id": "test-cutting-words",
        }
    )
    assert runtime is not None
    return runtime


def test_cutting_words_runtime_is_full_with_three_branches() -> None:
    runtime = _runtime()
    assert runtime["automation_status"] == "full"
    assert set(runtime["actions"]) == {
        "cutting_words_attack",
        "cutting_words_check",
        "cutting_words_damage",
    }
    assert runtime["actions"]["cutting_words_attack"]["kind"] == "attack_resolution_intervention"
    assert runtime["actions"]["cutting_words_check"]["kind"] == "roll_intervention"
    assert runtime["actions"]["cutting_words_damage"]["kind"] == "feature_action"


def test_cutting_words_attack_branch_subtracts_die_and_can_force_miss(client: TestClient) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Cutting Words Attack"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Cutting room"}).json()
    assert (
        client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 10, "height": 8, "cell_size_ft": 5, "mode": "combat"},
        ).status_code
        == 201
    )
    combat = client.post(
        f"{base}/combats",
        json={"name": "Cutting combat", "scene_id": scene["id"]},
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "强盗",
            "entity_type": "monster",
            "initiative": 18,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "enemy",
                "grid_position": {"row": 2, "col": 2},
            },
        },
    ).json()
    target = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "卫士",
            "entity_type": "character",
            "initiative": 12,
            "hp": 30,
            "max_hp": 30,
            "armor_class": 15,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 2, "col": 3},
            },
        },
    ).json()
    bard = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "逸闻诗人",
            "entity_type": "character",
            "initiative": 10,
            "hp": 24,
            "max_hp": 24,
            "armor_class": 14,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 3, "col": 2},
                "resources": {
                    "bardic_inspiration": {
                        "label": "诗人激励",
                        "current": 2,
                        "max": 2,
                        "maximum": 2,
                    }
                },
                "feature_dice": {"bardic_inspiration_die": {"value": "D8", "available": True}},
                "feature_runtime": {
                    **_runtime(),
                    "resources": {
                        "bardic_inspiration": {"current": 2, "max": 2},
                        "bardic_inspiration_die": {"value": "D8"},
                    },
                },
            },
        },
    ).json()
    paused = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "cutting-words-attack"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_cost": "none",
            "amount": 9,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 16,
        },
    )
    assert paused.status_code == 200, paused.text
    body = paused.json()
    assert body["phase"] == "awaiting_attack_intervention"
    window = body["pending_attack_intervention"]
    assert window["actor_combatant_id"] == bard["id"]
    assert window["result_json"]["action_window"]["feature_id"] == "cutting_words_attack"
    resolved = client.post(
        f"{base}/combats/{combat['id']}/reactions/attack-resolution/resolve",
        headers={"X-Request-ID": "cutting-words-attack-accept"},
        json={
            "window_id": window["id"],
            "window_version": window["version"],
            "decision": "accept",
            "feature_id": "cutting_words_attack",
            "inputs": {"bardic_die": 4},
        },
    )
    assert resolved.status_code == 200, resolved.text
    result = resolved.json()
    assert result["target"]["hp"] == 30
    assert result["action"]["result_json"]["attack_resolution"]["hit"] is False
    assert result["action"]["result_json"]["attack_resolution"]["effective_attack_total"] == 12


def test_cutting_words_damage_branch_opens_for_nearby_bard(client: TestClient) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Cutting Words Damage"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Damage room"}).json()
    assert (
        client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 10, "height": 8, "cell_size_ft": 5, "mode": "combat"},
        ).status_code
        == 201
    )
    combat = client.post(
        f"{base}/combats",
        json={"name": "Damage combat", "scene_id": scene["id"]},
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "法师",
            "entity_type": "monster",
            "initiative": 15,
            "hp": 18,
            "max_hp": 18,
            "snapshot_json": {
                "disposition": "enemy",
                "grid_position": {"row": 4, "col": 4},
            },
        },
    ).json()
    target = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "友军",
            "entity_type": "character",
            "initiative": 11,
            "hp": 28,
            "max_hp": 28,
            "armor_class": 13,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 4, "col": 5},
            },
        },
    ).json()
    bard = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "逸闻诗人",
            "entity_type": "character",
            "initiative": 9,
            "hp": 22,
            "max_hp": 22,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 5, "col": 4},
                "resources": {
                    "bardic_inspiration": {
                        "label": "诗人激励",
                        "current": 1,
                        "max": 1,
                        "maximum": 1,
                    }
                },
                "feature_runtime": {
                    **_runtime(),
                    "resources": {
                        "bardic_inspiration": {"current": 1, "max": 1},
                        "bardic_inspiration_die": {"value": "D8"},
                    },
                },
            },
        },
    ).json()
    # Non-attack damage still opens cutting-words damage branch for visible attacker.
    paused = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "cutting-words-damage"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_cost": "none",
            "amount": 10,
            "damage_type": "fire",
            "is_attack": False,
        },
    )
    assert paused.status_code == 200, paused.text
    body = paused.json()
    assert body["phase"] == "awaiting_reaction"
    window = body["pending_reaction"]
    assert window["actor_combatant_id"] == bard["id"]
    assert window["result_json"]["action_window"]["feature_id"] == "cutting_words_damage"
    resolved = client.post(
        f"{base}/combats/{combat['id']}/reactions/pre-damage/resolve",
        headers={"X-Request-ID": "cutting-words-damage-accept"},
        json={
            "reaction_window_id": window["id"],
            "reaction_window_version": window["version"],
            "decision": "accept",
            "feature_id": "cutting_words_damage",
            "inputs": {"bardic_die": 6},
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["target"]["hp"] == 24


def test_cutting_words_check_branch_reduces_successful_ability_check(client: TestClient) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Cutting Words Check"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Check room"}).json()
    assert (
        client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 10, "height": 8, "cell_size_ft": 5, "mode": "combat"},
        ).status_code
        == 201
    )
    combat = client.post(
        f"{base}/combats",
        json={"name": "Check combat", "scene_id": scene["id"]},
    ).json()
    roller = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "撬门者",
            "entity_type": "character",
            "initiative": 12,
            "hp": 20,
            "max_hp": 20,
            "armor_class": 12,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 2, "col": 2},
                "ability_scores": {"strength": 16},
            },
        },
    ).json()
    bard = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "逸闻诗人",
            "entity_type": "character",
            "initiative": 9,
            "hp": 22,
            "max_hp": 22,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 2, "col": 3},
                "resources": {
                    "bardic_inspiration": {
                        "label": "诗人激励",
                        "current": 2,
                        "max": 2,
                        "maximum": 2,
                    }
                },
                "feature_runtime": {
                    **_runtime(),
                    "resources": {
                        "bardic_inspiration": {"current": 2, "max": 2},
                        "bardic_inspiration_die": {"value": "D8"},
                    },
                },
            },
        },
    ).json()
    prompt = client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending",
        headers={"X-Request-ID": "cutting-words-check-prompt"},
        json={
            "actor_combatant_id": roller["id"],
            "actor_version": roller["version"],
            "target_combatant_id": roller["id"],
            "target_version": roller["version"],
            "action_cost": "none",
            "action_name": "撬开大门",
            "resolution_type": "ability_check",
            "ability": "strength",
            "ability_check_proficient": True,
            "dc": 15,
        },
    )
    assert prompt.status_code == 200, prompt.text
    action = prompt.json()["action"]
    opened = client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "cutting-words-check-open"},
        json={"action_version": action["version"], "roll_total": 18},
    )
    assert opened.status_code == 200, opened.text
    resolution = opened.json()["resolution"]
    assert resolution["phase"] == "awaiting_roll_intervention"
    assert any(
        item["id"] == "cutting_words_check"
        and item["reactor_combatant_id"] == bard["id"]
        for item in resolution["roll_intervention_window"]
    )

    # Failed checks must not open a success-only cutting-words window.
    failed_prompt = client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/pending",
        headers={"X-Request-ID": "cutting-words-check-fail-prompt"},
        json={
            "actor_combatant_id": roller["id"],
            "actor_version": roller["version"],
            "target_combatant_id": roller["id"],
            "target_version": roller["version"],
            "action_cost": "none",
            "action_name": "撬开大门",
            "resolution_type": "ability_check",
            "ability": "strength",
            "ability_check_proficient": True,
            "dc": 15,
        },
    )
    assert failed_prompt.status_code == 200, failed_prompt.text
    failed_action = failed_prompt.json()["action"]
    failed = client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/{failed_action['id']}/confirm",
        headers={"X-Request-ID": "cutting-words-check-fail-open"},
        json={"action_version": failed_action["version"], "roll_total": 6},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["resolution"]["phase"] == "resolved"
    assert not any(
        item.get("id") == "cutting_words_check"
        for item in failed.json()["resolution"].get("roll_intervention_window", [])
    )

    resolved = client.post(
        f"{base}/combats/{combat['id']}/actions/player-rolls/{action['id']}/confirm",
        headers={"X-Request-ID": "cutting-words-check-confirm"},
        json={
            "action_version": opened.json()["action"]["version"],
            "roll_total": 18,
            "roll_intervention_id": "cutting_words_check",
            "roll_intervention_reactor_id": bard["id"],
            "roll_intervention_inputs": {"bardic_die": 6},
        },
    )
    assert resolved.status_code == 200, resolved.text
    final = resolved.json()["resolution"]
    assert final["success"] is False
    assert final["roll_total"] == 12
    assert final["generic_resource_consumed"] == {
        "key": "bardic_inspiration",
        "cost": 1,
        "before": 2,
        "after": 1,
    }
    bard_after = next(
        item
        for item in client.get(f"{base}/combats/{combat['id']}/combatants").json()["items"]
        if item["id"] == bard["id"]
    )
    assert bard_after["reaction_available"] is False
