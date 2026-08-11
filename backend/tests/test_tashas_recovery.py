# ruff: noqa: E501
from __future__ import annotations

import hashlib
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_pack_runtime_registry import (
    ContentPackRuntimeRegistry,
)
from dnd_dm_assistant.application.tashas_recovery import (
    build_template_catalog,
)
from dnd_dm_assistant.domain.item_spec import (
    ItemIRValidationError,
    ItemSpec,
    compile_item_spec,
    materialize_item_effects,
)
from dnd_dm_assistant.infrastructure.database.models import EquipmentInstance
from dnd_dm_assistant.infrastructure.database.rest_service import RestService


def _item_spec() -> dict[str, Any]:
    return {
        "schema_version": "item-ir-1",
        "item_id": "content.tashas-cauldron.item.test-charge-wand",
        "pack_id": "tashas-cauldron",
        "pack_version": "whole-pack-2026-08-11",
        "namespace": "dnd.tashas.recovery.item",
        "ruleset_version": "2024",
        "name": "测试充能法器",
        "localized_name": "测试充能法器",
        "source_record_id": "test-source-record",
        "source_path": "塔莎的万事坩埚/测试物品.html",
        "source_fragment": "1",
        "source_fingerprint": hashlib.sha256(b"test-item").hexdigest(),
        "source_trust": "authored_ir",
        "item_kind": "wondrous_item",
        "rarity": "珍稀",
        "requires_attunement": True,
        "attunement_requirements": {"required": True, "requirements_text": "任意生物"},
        "equipped_slot": "worn",
        "stack_policy": {"mode": "unique_instance"},
        "consumption_policy": {"mode": "charges"},
        "charges": {
            "maximum": 2,
            "current": 1,
            "recovery_trigger": "long_rest",
            "recovery_amount": "all",
        },
        "passive_modifiers": [],
        "granted_actions": [
            {"action_id": "test:ping", "action_economy": "action", "charge_cost": 1}
        ],
        "granted_spells": [],
        "triggered_effects": [],
        "damage": None,
        "healing": None,
        "temporary_hp": None,
        "conditions": [],
        "resistances": [],
        "immunities": [],
        "resource_bindings": [],
        "duration": None,
        "clauses": [
            {
                "clause_id": "test:equipment",
                "clause_type": "equipment",
                "trigger": "item_lifecycle",
                "action_economy": "none",
                "parameters": {"equipped_slot": "worn"},
                "evidence": {"source_text": "测试物品"},
            },
            {
                "clause_id": "test:attunement",
                "clause_type": "attunement",
                "trigger": "attunement_confirmed",
                "action_economy": "none",
                "parameters": {"required": True},
                "evidence": {"source_text": "需同调"},
            },
            {
                "clause_id": "test:charge",
                "clause_type": "charge",
                "trigger": "item_lifecycle",
                "action_economy": "none",
                "parameters": {"maximum": 2},
                "evidence": {"source_text": "2发充能"},
            },
            {
                "clause_id": "test:recovery",
                "clause_type": "charge_recovery",
                "trigger": "long_rest",
                "action_economy": "none",
                "parameters": {"recovery_trigger": "long_rest", "recovery_amount": "all"},
                "evidence": {"source_text": "长休恢复"},
            },
            {
                "clause_id": "test:action",
                "clause_type": "granted_action",
                "trigger": "item_action_requested",
                "action_economy": "action",
                "parameters": {"action_id": "test:ping", "charge_cost": 1},
                "evidence": {"source_text": "以一个动作"},
            },
        ],
        "evidence": {"review_status": "reviewed", "source_text_sha256": hashlib.sha256(b"test-item").hexdigest()},
    }


def test_item_spec_is_closed_and_resolves_generic_consumers() -> None:
    spec = ItemSpec.from_dict(_item_spec())
    compiled = compile_item_spec(spec)
    assert compiled["compile_status"] == "full"
    assert compiled["consumer_ids"] == [
        "item.attunement.v1",
        "item.charge_resource.v1",
        "item.equipment_modifier.v1",
        "item.granted_action.v1",
    ]
    with pytest.raises(ItemIRValidationError, match="unsupported"):
        ItemSpec.from_dict({**_item_spec(), "item_kind": "named_item"})
    with pytest.raises(ItemIRValidationError, match="unknown fields"):
        ItemSpec.from_dict({**_item_spec(), "name_branch": "bad"})
    invalid_clause = {**_item_spec(), "clauses": [{**_item_spec()["clauses"][0], "clause_type": "name_branch"}]}
    with pytest.raises(ItemIRValidationError, match="unsupported"):
        ItemSpec.from_dict(invalid_clause)
    assert not any("name" in item for item in compiled["consumer_ids"])


def test_item_effects_require_attunement_and_registry_is_closed() -> None:
    spec = ItemSpec.from_dict(_item_spec())
    projection = {
        "id": "equipment-1",
        "equipped": False,
        "item_spec": {
            **spec.to_dict(),
            "passive_modifiers": [{"modifier": "test", "value": 1}],
            "granted_actions": [{"action_id": "test:ping"}],
        },
    }
    assert materialize_item_effects([projection]) == {
        "active_item_ids": [],
        "passive_modifiers": [],
        "granted_actions": [],
        "granted_spells": [],
        "resistances": [],
        "immunities": [],
    }
    active = materialize_item_effects([projection], {"equipment-1"})
    assert active["active_item_ids"] == ["equipment-1"]
    assert active["granted_actions"][0]["source_item_id"] == "equipment-1"
    with pytest.raises(ValueError, match="unknown item clauses"):
        resolve_production_consumers(
            content_kind="item",
            runtime_schema_version="item-ir-1",
            blocks={"clauses": [{"clause_type": "name_branch"}]},
        )


def test_tashas_catalogs_have_real_denominators() -> None:
    from pathlib import Path

    from dnd_dm_assistant.application.content_ir_workbench import load_records
    from dnd_dm_assistant.application.tashas_recovery import build_item_spec_catalog
    from dnd_dm_assistant.application.tashas_whole_pack import (
        build_migration,
        select_source_records,
    )

    root = Path(__file__).resolve().parents[2]
    migration = build_migration(root)
    records = select_source_records(load_records(root / "data/generated-content/dnd5e_chm/json"))
    item_catalog = build_item_spec_catalog(migration["atoms"], records)
    assert item_catalog["item_spec_total"] == 47
    assert item_catalog["item_spec_typed"] == 47
    assert item_catalog["name_branch_count"] == 0
    assert sum(item["content_kind"] == "magic_tattoo" for item in migration["atoms"]) == 11
    templates = build_template_catalog(migration["atoms"], {"cluster_count": 15}, item_catalog)
    assert templates["template_total"] >= 15


def test_tasha_isolated_registry_keeps_item_layers_separate() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    registry = ContentPackRuntimeRegistry(
        root / "data/content-ir/isolated-packs/tashas-cauldron-2026-08-11"
    )
    summary = registry.reload()
    assert summary["formal_apply"] is False
    assert summary["entry_total"] == 47
    assert summary["compile_full"] == 37
    assert summary["runtime_preview_full"] == 37
    assert summary["isolated_runtime_validated"] == 37
    assert summary["registered_production_full"] == 0
    assert summary["game_usable"] == 0
    first = registry.lookup(summary["isolated_runtime_validated_ids"][0])
    assert first is not None
    assert first["status_layers"]["isolated_runtime_validated"] is True
    assert first["status_layers"]["registered_production_full"] is False


def test_item_charge_recovery_is_typed_and_dawn_is_not_a_rest(tmp_path: Any) -> None:
    # The service helper is deliberately exercised against an isolated SQLite
    # database; it must not be coupled to the formal project database.
    from dnd_dm_assistant.infrastructure.database.models import Base, Campaign, Character

    engine = create_engine(f"sqlite:///{tmp_path / 'item-recovery.db'}")
    Base.metadata.create_all(engine)
    spec = ItemSpec.from_dict(_item_spec())
    with Session(engine) as session, session.begin():
        campaign = Campaign(name="isolated-item-recovery", enabled_content_packs=["tashas-cauldron"])
        session.add(campaign)
        session.flush()
        character = Character(campaign_id=campaign.id, name="typed item tester", level=1, hp=8, max_hp=8)
        session.add(character)
        session.flush()
        equipment = EquipmentInstance(
            campaign_id=campaign.id,
            character_id=character.id,
            name=spec.name,
            category=spec.item_kind,
            attunement_required=True,
            charges=0,
            max_charges=2,
            metadata_json={"item_spec": spec.to_dict()},
        )
        session.add(equipment)
        session.flush()
        short = RestService._item_charge_recovery(session, character, effective_type="short", completed=True)
        long = RestService._item_charge_recovery(session, character, effective_type="long", completed=True)
        assert short == []
        assert long[0]["after"] == 2


def test_typed_item_api_uses_attunement_action_and_idempotency(campaign_client: Any) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "typed item API"}).json()
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "typed item character", "hp": 8, "max_hp": 8},
    ).json()
    created = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/assets/equipment",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": "测试充能法器",
            "metadata_json": {"item_spec": _item_spec()},
        },
    )
    assert created.status_code == 201, created.text
    equipment = created.json()
    attune_body = {
        "character_id": character["id"],
        "character_version": character["version"] + 1,
        "equipment_id": equipment["id"],
        "operation": "attune",
    }
    preview = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/equipment/preview", json=attune_body
    )
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/equipment/confirm",
        json={**attune_body, "preview_token": preview.json()["preview_token"], "idempotency_key": "item-attune-1"},
    )
    assert confirmed.status_code == 200, confirmed.text
    replay = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/equipment/confirm",
        json={**attune_body, "preview_token": preview.json()["preview_token"], "idempotency_key": "item-attune-1"},
    )
    assert replay.status_code == 200
    current = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    action_body = {
        "character_id": character["id"],
        "character_version": current["version"],
        "equipment_id": equipment["id"],
        "operation": "use_action",
        "action_id": "test:ping",
    }
    action_preview = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/equipment/preview", json=action_body
    )
    assert action_preview.status_code == 200, action_preview.text
    assert action_preview.json()["after"]["charges"] == 0
    current = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    dm_preview = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/equipment/adjudication/preview",
        json={
            "character_id": character["id"],
            "character_version": current["version"],
            "equipment_id": equipment["id"],
            "clause_id": "test:action",
            "context": {"target_policy": "self"},
            "idempotency_key": "item-dm-action-1",
        },
    )
    assert dm_preview.status_code == 200, dm_preview.text
    dm = dm_preview.json()
    dm_confirm = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/equipment/adjudication/confirm",
        json={
            "adjudication_id": dm["adjudication_id"],
            "permission": "dm",
            "expected_window_version": 1,
            "idempotency_key": "item-dm-action-1",
            "decision": {"status": "approved", "approved_targets": []},
        },
    )
    assert dm_confirm.status_code == 200, dm_confirm.text
    dm_result = dm_confirm.json()
    assert dm_result["confirmed"] is True
    rollback = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/equipment/adjudication/{dm['adjudication_id']}/rollback",
        json={
            "expected_character_version": dm_result["character_version_after"],
            "expected_equipment_version": dm_result["equipment_version_after"],
        },
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["status"] == "reverted"


def test_history_backed_advancement_downgrade_rebuilds_via_cas(campaign_client: Any) -> None:
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "growth loop"}).json()
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "growth tester",
            "class_name": "战士",
            "level": 1,
            "experience": 300,
            "hp": 10,
            "max_hp": 10,
            "ability_scores": {"strength": 16, "constitution": 14},
            "class_levels": {"战士": 1},
        },
    ).json()
    prefix = f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    first = campaign_client.post(
        f"{prefix}/advancement/preview",
        json={"character_version": character["version"], "class_name": "战士"},
    )
    assert first.status_code == 200, first.text
    first_confirm = campaign_client.post(
        f"{prefix}/advancement/confirm",
        json={
            "character_version": character["version"],
            "class_name": "战士",
            "preview_token": first.json()["preview_token"],
            "idempotency_key": "growth-level-two",
        },
    )
    assert first_confirm.status_code == 200, first_confirm.text
    current = campaign_client.get(prefix).json()
    second = campaign_client.post(
        f"{prefix}/advancement/preview",
        json={
            "character_version": current["version"],
            "class_name": "战士",
            "subclass_name": "勇士",
            "dm_override_reason": "isolated growth loop fixture",
        },
    )
    assert second.status_code == 200, second.text
    second_confirm = campaign_client.post(
        f"{prefix}/advancement/confirm",
        json={
            "character_version": current["version"],
            "class_name": "战士",
            "subclass_name": "勇士",
            "dm_override_reason": "isolated growth loop fixture",
            "preview_token": second.json()["preview_token"],
            "idempotency_key": "growth-level-three",
        },
    )
    assert second_confirm.status_code == 200, second_confirm.text
    current = campaign_client.get(prefix).json()
    down_preview = campaign_client.post(
        f"{prefix}/advancement/downgrade/preview",
        json={"character_version": current["version"], "target_level": 2},
    )
    assert down_preview.status_code == 200, down_preview.text
    down_confirm = campaign_client.post(
        f"{prefix}/advancement/downgrade/confirm",
        json={
            "character_version": current["version"],
            "target_level": 2,
            "preview_token": down_preview.json()["preview_token"],
            "idempotency_key": "growth-downgrade-two",
        },
    )
    assert down_confirm.status_code == 200, down_confirm.text
    assert campaign_client.get(prefix).json()["level"] == 2


def test_character_pack_pin_is_campaign_scoped_and_immutable(campaign_client: Any) -> None:
    campaign = campaign_client.post(
        "/api/v1/campaigns",
        json={
            "name": "pack pin",
            "enabled_content_packs": ["tashas-cauldron"],
            "allow_legacy": True,
        },
    ).json()
    character = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "pinned character"},
    ).json()
    pinned = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}/content-pack-pin",
        json={
            "character_version": character["version"],
            "content_pack_pins": ["tashas-cauldron"],
            "allow_legacy": True,
        },
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["immutable"] is True
    changed = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    different = campaign_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}/content-pack-pin",
        json={
            "character_version": changed["version"],
            "content_pack_pins": [],
            "allow_legacy": True,
        },
    )
    assert different.status_code == 400
