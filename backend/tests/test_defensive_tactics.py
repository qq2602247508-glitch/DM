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
    database_url = f"sqlite:///{tmp_path / 'defensive-tactics.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _runtime() -> dict[str, Any]:
    runtime = subclass_feature_runtime_definition(
        {
            "name": "防守战术",
            "class_name": "游侠",
            "class_level": 7,
            "source_record_id": "test-defensive-tactics",
        }
    )
    assert runtime is not None
    return runtime


def test_defensive_tactics_runtime_is_full() -> None:
    runtime = _runtime()
    assert runtime["automation_status"] == "full"
    action = runtime["actions"]["defensive_tactics_choice"]
    assert action["kind"] == "rest_choice"
    assert set(action["choice_options"]) == {"escape_the_horde", "multiattack_defense"}


def _setup(
    client: TestClient, name: str, selected: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    campaign = client.post("/api/v1/campaigns", json={"name": name}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    scene = client.post(f"{base}/scenes", json={"name": "Horde room"}).json()
    assert (
        client.post(
            f"{base}/scenes/{scene['id']}/grid",
            json={"width": 12, "height": 10, "cell_size_ft": 5, "mode": "combat"},
        ).status_code
        == 201
    )
    combat = client.post(
        f"{base}/combats",
        json={"name": "Defensive combat", "scene_id": scene["id"]},
    ).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "兽人",
            "entity_type": "monster",
            "initiative": 18,
            "hp": 30,
            "max_hp": 30,
            "armor_class": 13,
            "snapshot_json": {
                "disposition": "enemy",
                "grid_position": {"row": 2, "col": 2},
            },
        },
    ).json()
    ranger = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "猎人",
            "entity_type": "character",
            "initiative": 10,
            "hp": 36,
            "max_hp": 36,
            "armor_class": 16,
            "snapshot_json": {
                "disposition": "ally",
                "grid_position": {"row": 2, "col": 3},
                "resources": {
                    "defensive_tactics": {
                        "label": "防守战术",
                        "selected": selected,
                    }
                },
                "feature_runtime": {
                    **_runtime(),
                    "resources": {
                        "defensive_tactics": {"selected": selected},
                    },
                },
            },
        },
    ).json()
    return combat, attacker, ranger, base


def test_escape_the_horde_imposes_disadvantage_on_opportunity_attack(client: TestClient) -> None:
    combat, attacker, ranger, base = _setup(client, "Escape the Horde", "escape_the_horde")
    # A normal attack without reaction trigger does NOT get the disadvantage.
    normal = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "escape-normal"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": ranger["id"],
            "target_version": ranger["version"],
            "action_cost": "none",
            "amount": 4,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 17,
            "attack_roll_mode": "normal",
        },
    )
    assert normal.status_code == 200, normal.text
    assert normal.json()["target"]["hp"] == 32

    # Opportunity attack with reaction trigger gets disadvantage: player/DM
    # must submit two d20 totals and the engine picks the lower one.
    second = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "escape-opportunity"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": ranger["id"],
            "target_version": normal.json()["target"]["version"],
            "action_cost": "reaction",
            "reaction_event": "leaves_reach",
            "reaction_trigger": "借机攻击",
            "amount": 4,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 17,
            "attack_roll_mode": "normal",
            "attack_adjudication_note": "借机攻击",
        },
    )
    # The attack context now demands disadvantage mode; the strict consumer
    # rejects a normal-mode opportunity attack, proving the source is real.
    assert second.status_code == 400, second.text
    assert "attack_roll_mode conflicts" in second.text


def test_multiattack_defense_imposes_disadvantage_on_same_attacker_second_attack(
    client: TestClient,
) -> None:
    combat, attacker, ranger, base = _setup(client, "Multiattack Defense", "multiattack_defense")
    first = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "multiattack-first"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": ranger["id"],
            "target_version": ranger["version"],
            "action_cost": "none",
            "amount": 6,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 18,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["target"]["hp"] == 30
    ranger_after_first = next(
        item
        for item in client.get(f"{base}/combats/{combat['id']}/combatants").json()["items"]
        if item["id"] == ranger["id"]
    )
    hits = ranger_after_first["snapshot_json"].get("multiattack_defense_hits")
    assert isinstance(hits, dict) and any(
        attacker["id"] in value for value in hits.values()
    )

    # Second attack by the same attacker must be resolved under disadvantage.
    second = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "multiattack-second"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": attacker["version"],
            "target_combatant_id": ranger["id"],
            "target_version": ranger_after_first["version"],
            "action_cost": "none",
            "amount": 6,
            "damage_type": "slashing",
            "is_attack": True,
            "attack_range_ft": 5,
            "attack_roll_total": 18,
            "attack_roll_mode": "normal",
            "attack_adjudication_note": "多重防御后续攻击",
        },
    )
    assert second.status_code == 400, second.text
    assert "attack_roll_mode conflicts" in second.text
