from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database.models import KnownSpell, PreparedSpell


@pytest.fixture
def client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    database_url = f"sqlite:///{tmp_path / 'attack-sequences.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as test_client:
        test_client.database_url = database_url  # type: ignore[attr-defined]
        yield test_client


def _combat(client: TestClient) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Attack sequence"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    combat = client.post(f"{base}/combats", json={"name": "Sequence combat"}).json()
    attacker = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "双击战士",
            "entity_type": "character",
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "feature_runtime": {"combat_start": {"attack_action_count": 2}}
            },
        },
    ).json()
    target = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "训练假人",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()
    return base, combat["id"], attacker, target


def test_attack_sequence_pays_once_and_resolves_each_slot_with_cas(
    client: TestClient,
) -> None:
    base, combat_id, attacker, target = _combat(client)
    started = client.post(
        f"{base}/combats/{combat_id}/attack-sequences/start",
        headers={"X-Request-ID": "sequence-start"},
        json={"actor_combatant_id": attacker["id"], "actor_version": attacker["version"]},
    )
    assert started.status_code == 200, started.text
    start_body = started.json()
    sequence = start_body["sequence"]
    metadata = sequence["result_json"]["attack_sequence"]
    assert metadata["total_slots"] == 2
    assert start_body["actor"]["action_available"] is False

    first = client.post(
        f"{base}/combats/{combat_id}/actions/confirm",
        headers={"X-Request-ID": "sequence-hit-1"},
        json={
            "action_type": "damage",
            "actor_combatant_id": attacker["id"],
            "actor_version": start_body["actor"]["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_cost": "parent_action_part",
            "action_name": "长剑",
            "amount": 4,
            "damage_type": "slashing",
            "is_attack": True,
            "is_weapon_attack": True,
            "attack_roll_total": 18,
            "attack_sequence_id": sequence["id"],
            "attack_sequence_version": sequence["version"],
            "attack_sequence_slot_index": 0,
        },
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["target"]["hp"] == 26
    sequence_result = first_body["action"]["result_json"]["attack_sequence"]
    assert sequence_result["remaining_slots"] == 1
    assert sequence_result["status"] == "open"

    replay = client.post(
        f"{base}/combats/{combat_id}/actions/confirm",
        headers={"X-Request-ID": "sequence-hit-1"},
        json={
            **first_body["action"]["request_json"],
            "target_version": first_body["target"]["version"],
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["action"]["id"] == first_body["action"]["id"]
    assert replay.json()["target"]["hp"] == 26

    stale = client.post(
        f"{base}/combats/{combat_id}/actions/confirm",
        headers={"X-Request-ID": "sequence-hit-stale"},
        json={
            **first_body["action"]["request_json"],
            "target_version": first_body["target"]["version"],
            "attack_sequence_slot_index": 1,
        },
    )
    assert stale.status_code == 409, stale.text

    second = client.post(
        f"{base}/combats/{combat_id}/actions/confirm",
        headers={"X-Request-ID": "sequence-hit-2"},
        json={
            **first_body["action"]["request_json"],
            "target_version": first_body["target"]["version"],
            "attack_sequence_version": sequence_result["sequence_version"],
            "attack_sequence_slot_index": 1,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["target"]["hp"] == 22
    assert second.json()["action"]["result_json"]["attack_sequence"]["status"] == "completed"


def test_attack_sequence_cancel_is_idempotent(client: TestClient) -> None:
    base, combat_id, attacker, _target = _combat(client)
    started = client.post(
        f"{base}/combats/{combat_id}/attack-sequences/start",
        headers={"X-Request-ID": "cancel-start"},
        json={"actor_combatant_id": attacker["id"], "actor_version": attacker["version"]},
    ).json()
    sequence = started["sequence"]
    payload = {"sequence_id": sequence["id"], "sequence_version": sequence["version"]}
    cancelled = client.post(
        f"{base}/combats/{combat_id}/attack-sequences/{sequence['id']}/cancel",
        headers={"X-Request-ID": "cancel-sequence"},
        json=payload,
    )
    assert cancelled.status_code == 200, cancelled.text
    metadata = cancelled.json()["sequence"]["result_json"]["attack_sequence"]
    assert metadata["status"] == "cancelled"
    assert {slot["status"] for slot in metadata["slots"]} == {"cancelled"}
    replay = client.post(
        f"{base}/combats/{combat_id}/attack-sequences/{sequence['id']}/cancel",
        headers={"X-Request-ID": "cancel-sequence"},
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["sequence"]["version"] == cancelled.json()["sequence"]["version"]


def test_war_magic_replaces_one_slot_with_authoritative_wizard_cantrip(
    client: TestClient,
) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "War magic"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={"name": "奥法骑士", "hp": 30, "max_hp": 30},
    ).json()
    engine = create_engine(client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        spell = KnownSpell(
            campaign_id=campaign["id"],
            character_id=character["id"],
            name="火焰箭",
            spell_level=0,
            metadata_json={
                "character_spell": {
                    "name": "火焰箭",
                    "cost": "动作",
                    "class_name": "法师",
                }
            },
        )
        session.add(spell)
        session.flush()
        spell_id = spell.id
    combat = client.post(f"{base}/combats", json={"name": "War magic combat"}).json()
    actor = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "奥法骑士",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "feature_runtime": {
                    "combat_start": {
                        "attack_action_count": 2,
                        "attack_slot_replacements": [
                            {
                                "id": "replace_attack_with_wizard_cantrip",
                                "kind": "replace_attack_with_spell",
                                "slot_cost": 1,
                                "spell_levels": [0],
                                "spellcasting_classes": ["法师", "wizard"],
                                "uses_per_sequence": 1,
                            }
                        ],
                    }
                }
            },
        },
    ).json()
    target = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "稻草人",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    started = client.post(
        f"{base}/combats/{combat['id']}/attack-sequences/start",
        headers={"X-Request-ID": "war-magic-start"},
        json={"actor_combatant_id": actor["id"], "actor_version": actor["version"]},
    ).json()
    sequence = started["sequence"]
    cast_result = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "war-magic-cast"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": started["actor"]["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_cost": "parent_action_part",
            "action_name": "火焰箭",
            "amount": 5,
            "damage_type": "fire",
            "is_attack": True,
            "is_spell_attack": True,
            "attack_roll_total": 18,
            "attack_sequence_id": sequence["id"],
            "attack_sequence_version": sequence["version"],
            "attack_sequence_slot_indices": [0],
            "attack_sequence_replacement_kind": "replace_attack_with_spell",
            "attack_sequence_replacement_policy_id": "replace_attack_with_wizard_cantrip",
            "attack_sequence_known_spell_id": spell_id,
        },
    )
    assert cast_result.status_code == 200, cast_result.text
    result = cast_result.json()["action"]["result_json"]["attack_sequence"]
    assert result["resolved_slot_indices"] == [0]
    assert result["remaining_slots"] == 1


def test_improved_war_magic_atomically_consumes_two_slots_and_one_spell_slot(
    client: TestClient,
) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Improved war magic"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "高阶奥法骑士",
            "hp": 40,
            "max_hp": 40,
            "resources": {
                "spell_slots_1": {"current": 2, "max": 2, "label": "1环法术位"}
            },
        },
    ).json()
    engine = create_engine(client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        spell = KnownSpell(
            campaign_id=campaign["id"],
            character_id=character["id"],
            name="燃烧之手",
            spell_level=1,
            metadata_json={
                "character_spell": {
                    "name": "燃烧之手",
                    "cost": "动作",
                    "class_name": "法师",
                }
            },
        )
        session.add(spell)
        session.flush()
        session.add(
            PreparedSpell(
                character_id=character["id"],
                known_spell_id=spell.id,
                prepared=True,
            )
        )
        spell_id = spell.id
    combat = client.post(f"{base}/combats", json={"name": "Improved combat"}).json()
    actor = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "高阶奥法骑士",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 40,
            "max_hp": 40,
            "snapshot_json": {
                "resources": {
                    "spell_slots_1": {"current": 2, "max": 2, "label": "1环法术位"}
                },
                "feature_runtime": {
                    "combat_start": {
                        "attack_action_count": 3,
                        "attack_slot_replacements": [
                            {
                                "id": "replace_two_attacks_with_wizard_spell",
                                "kind": "replace_attack_with_spell",
                                "slot_cost": 2,
                                "spell_levels": [1, 2],
                                "spellcasting_classes": ["法师", "wizard"],
                                "uses_per_sequence": 1,
                            }
                        ],
                    }
                },
            },
        },
    ).json()
    target = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "目标",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 30,
            "max_hp": 30,
        },
    ).json()
    started = client.post(
        f"{base}/combats/{combat['id']}/attack-sequences/start",
        headers={"X-Request-ID": "improved-start"},
        json={"actor_combatant_id": actor["id"], "actor_version": actor["version"]},
    ).json()
    sequence = started["sequence"]
    cast_result = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "improved-cast"},
        json={
            "action_type": "damage",
            "actor_combatant_id": actor["id"],
            "actor_version": started["actor"]["version"],
            "target_combatant_id": target["id"],
            "target_version": target["version"],
            "action_cost": "parent_action_part",
            "action_name": "燃烧之手",
            "amount": 8,
            "damage_type": "fire",
            "resource_key": "spell_slots_1",
            "resource_cost": 1,
            "attack_sequence_id": sequence["id"],
            "attack_sequence_version": sequence["version"],
            "attack_sequence_slot_indices": [0, 1],
            "attack_sequence_replacement_kind": "replace_attack_with_spell",
            "attack_sequence_replacement_policy_id": "replace_two_attacks_with_wizard_spell",
            "attack_sequence_known_spell_id": spell_id,
        },
    )
    assert cast_result.status_code == 200, cast_result.text
    body = cast_result.json()
    assert body["action"]["result_json"]["attack_sequence"]["remaining_slots"] == 1
    assert body["actor"]["snapshot_json"]["resources"]["spell_slots_1"]["current"] == 1
    refreshed = client.get(f"{base}/characters/{character['id']}").json()
    assert refreshed["resources"]["spell_slots_1"]["current"] == 1


def test_turn_advance_expires_unspent_attack_slots(client: TestClient) -> None:
    base, combat_id, attacker, _target = _combat(client)
    started = client.post(
        f"{base}/combats/{combat_id}/attack-sequences/start",
        headers={"X-Request-ID": "expire-start"},
        json={"actor_combatant_id": attacker["id"], "actor_version": attacker["version"]},
    ).json()
    combat = client.get(f"{base}/combats/{combat_id}").json()
    advanced = client.post(
        f"{base}/combats/{combat_id}/turns/advance",
        headers={"X-Request-ID": "expire-advance"},
        json={"combat_version": combat["version"]},
    )
    assert advanced.status_code == 200, advanced.text
    assert started["sequence"]["id"] in advanced.json()["expired_attack_sequence_ids"]
    actions = client.get(f"{base}/combats/{combat_id}/actions").json()["items"]
    sequence = next(item for item in actions if item["id"] == started["sequence"]["id"])
    metadata = sequence["result_json"]["attack_sequence"]
    assert metadata["status"] == "expired"
    assert {slot["status"] for slot in metadata["slots"]} == {"expired"}


def test_commander_strike_consumes_slot_and_die_then_ally_reaction_adds_damage(
    client: TestClient,
) -> None:
    campaign = client.post("/api/v1/campaigns", json={"name": "Commander strike"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    resource = {
        "current": 2,
        "max": 4,
        "value": "d8",
        "die_size": 8,
        "resource_kind": "superiority_dice",
    }
    commander_character = client.post(
        f"{base}/characters",
        json={
            "name": "战斗大师",
            "hp": 30,
            "max_hp": 30,
            "resources": {"superiority_dice": resource},
        },
    ).json()
    combat = client.post(f"{base}/combats", json={"name": "Commander combat"}).json()
    commander = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "战斗大师",
            "entity_type": "character",
            "entity_id": commander_character["id"],
            "initiative": 20,
            "hp": 30,
            "max_hp": 30,
            "snapshot_json": {
                "disposition": "ally",
                "resources": {"superiority_dice": resource},
                "feature_runtime": {
                    "combat_start": {
                        "attack_action_count": 2,
                        "attack_slot_replacements": [
                            {
                                "id": "battle_master:commander_strike",
                                "kind": "replace_attack_with_ally_attack",
                                "maneuver_id": "commander_strike",
                                "slot_cost": 1,
                                "payment": {"resource_kind": "superiority_dice"},
                            }
                        ],
                    }
                },
            },
        },
    ).json()
    ally = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "受令盟友",
            "entity_type": "character",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {
                "disposition": "ally",
                "actions": [
                    {
                        "name": "长剑",
                        "is_weapon_attack": True,
                        "melee_weapon_attack": True,
                        "range": "5尺",
                    }
                ],
            },
        },
    ).json()
    enemy = client.post(
        f"{base}/combats/{combat['id']}/combatants",
        json={
            "display_name": "敌人",
            "entity_type": "monster",
            "initiative": 5,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"disposition": "enemy"},
        },
    ).json()
    started = client.post(
        f"{base}/combats/{combat['id']}/attack-sequences/start",
        headers={"X-Request-ID": "commander-start"},
        json={
            "actor_combatant_id": commander["id"],
            "actor_version": commander["version"],
        },
    ).json()
    sequence = started["sequence"]
    opened = client.post(
        f"{base}/combats/{combat['id']}/attack-sequences/{sequence['id']}/commander-strike",
        headers={"X-Request-ID": "commander-open"},
        json={
            "sequence_id": sequence["id"],
            "sequence_version": sequence["version"],
            "actor_combatant_id": commander["id"],
            "actor_version": started["actor"]["version"],
            "slot_index": 0,
            "ally_combatant_id": ally["id"],
            "ally_version": ally["version"],
            "superiority_die_total": 5,
        },
    )
    assert opened.status_code == 200, opened.text
    opened_body = opened.json()
    assert opened_body["sequence"]["result_json"]["attack_sequence"]["remaining_slots"] == 1
    assert opened_body["actor"]["snapshot_json"]["resources"]["superiority_dice"][
        "current"
    ] == 1
    window = opened_body["window"]
    attack = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "commander-ally-hit"},
        json={
            "action_type": "damage",
            "actor_combatant_id": ally["id"],
            "actor_version": ally["version"],
            "target_combatant_id": enemy["id"],
            "target_version": enemy["version"],
            "action_cost": "reaction",
            "action_name": "长剑",
            "reaction_trigger": "战斗大师以攻击槽和卓越骰发出指令",
            "amount": 4,
            "damage_type": "slashing",
            "is_attack": True,
            "is_weapon_attack": True,
            "attack_range_ft": 5,
            "attack_d20": 12,
            "attack_roll_total": 18,
            "triggered_attack_window_id": window["id"],
            "triggered_attack_window_version": window["version"],
        },
    )
    assert attack.status_code == 200, attack.text
    assert attack.json()["target"]["hp"] == 11
    assert attack.json()["actor"]["reaction_available"] is False
    assert attack.json()["action"]["result_json"]["attack_resolution"][
        "triggered_attack_damage_bonus"
    ]["amount"] == 5
    replay = client.post(
        f"{base}/combats/{combat['id']}/actions/confirm",
        headers={"X-Request-ID": "commander-ally-hit"},
        json=attack.json()["action"]["request_json"],
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["target"]["hp"] == 11
