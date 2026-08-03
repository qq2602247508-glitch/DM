# ruff: noqa: E501
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
from dnd_dm_assistant.infrastructure.database.models import (
    EquipmentInstance,
    KnownSpell,
    PreparedSpell,
    ShopInventory,
    Wallet,
)


@pytest.fixture
def economy_client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path / 'economy.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    with TestClient(create_app(Settings(environment="test", database_url=url))) as client:
        client.database_url = url  # type: ignore[attr-defined]
        yield client


def _seed(client: TestClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    campaign = client.post("/api/v1/campaigns", json={"name": "经济"}).json()
    character = client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "法师",
            "hp": 8,
            "max_hp": 8,
            "spellcasting": {"slots": {"1": {"current": 2, "max": 2}}},
        },
    ).json()
    engine = create_engine(client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as s, s.begin():
        spell = KnownSpell(
            campaign_id=campaign["id"], character_id=character["id"], name="魔法飞弹", spell_level=1
        )
        equipment = EquipmentInstance(
            campaign_id=campaign["id"],
            character_id=character["id"],
            name="防御护甲",
            category="armor",
            armor_class=15,
        )
        wand = EquipmentInstance(
            campaign_id=campaign["id"],
            character_id=character["id"],
            name="魔杖",
            attunement_required=True,
            charges=2,
            max_charges=2,
        )
        wallet = Wallet(
            campaign_id=campaign["id"], character_id=character["id"], name="法师钱包", copper=100
        )
        shop = ShopInventory(
            campaign_id=campaign["id"],
            name="治疗药水",
            quantity=3,
            price_copper=25,
            metadata_json={"unit_weight_lb": 0.5},
        )
        s.add_all([spell, equipment, wand, wallet, shop])
        s.flush()
        s.add(PreparedSpell(character_id=character["id"], known_spell_id=spell.id, prepared=True))
        ids = {
            "spell": spell.id,
            "equipment": equipment.id,
            "wand": wand.id,
            "wallet": wallet.id,
            "shop": shop.id,
        }
    return campaign, character, ids


def test_dm_can_create_atomic_character_assets_and_shop_stock(
    economy_client: TestClient,
) -> None:
    campaign = economy_client.post(
        "/api/v1/campaigns", json={"name": "资产录入"}
    ).json()
    character = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "录入角色", "hp": 8, "max_hp": 8},
    ).json()
    prefix = f"/api/v1/campaigns/{campaign['id']}"
    spell = economy_client.post(
        f"{prefix}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": "护盾术",
            "spell_level": 1,
            "prepared": True,
        },
    )
    assert spell.status_code == 201
    character = economy_client.get(
        f"{prefix}/characters/{character['id']}"
    ).json()
    equipment = economy_client.post(
        f"{prefix}/characters/assets/equipment",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": "法杖",
            "category": "weapon",
            "quantity": 1,
        },
    )
    assert equipment.status_code == 201
    character = economy_client.get(
        f"{prefix}/characters/{character['id']}"
    ).json()
    wallet = economy_client.post(
        f"{prefix}/characters/assets/wallets",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "copper": 50,
        },
    )
    assert wallet.status_code == 201
    stock = economy_client.post(
        f"{prefix}/shop-inventory",
        json={"name": "治疗药水", "quantity": 2, "price_copper": 25},
    )
    assert stock.status_code == 201
    assets = economy_client.get(
        f"{prefix}/characters/{character['id']}/assets"
    ).json()
    assert assets["spells"][0]["prepared"] is True
    assert assets["equipment"][0]["name"] == "法杖"
    assert assets["wallet"]["copper"] == 50
    character = economy_client.get(
        f"{prefix}/characters/{character['id']}"
    ).json()
    assert character["spells"][0]["name"] == "护盾术"
    assert character["actions"][0]["name"] == "护盾术"
    assert character["inventory"][0]["name"] == "法杖"


def test_character_asset_mirrors_are_idempotent_and_preserve_preparation_rules(
    economy_client: TestClient,
) -> None:
    campaign = economy_client.post(
        "/api/v1/campaigns", json={"name": "同步验收"}
    ).json()
    character = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "验收法师", "hp": 8, "max_hp": 8},
    ).json()
    prefix = f"/api/v1/campaigns/{campaign['id']}"
    spell_payload = {
        "character_id": character["id"],
        "character_version": character["version"],
        "name": "火球术",
        "spell_level": 3,
        "prepared": False,
        "metadata_json": {
            "source_record_id": "fireball-2024",
            "character_spell": {
                "name": "火球术",
                "source_record_id": "fireball-2024",
                "damage_expression": "8d6",
            },
        },
    }
    assert economy_client.post(
        f"{prefix}/characters/assets/spells", json=spell_payload
    ).status_code == 201
    character = economy_client.get(
        f"{prefix}/characters/{character['id']}"
    ).json()
    assert [item["name"] for item in character["spells"]] == ["火球术"]
    assert character["actions"] == []
    duplicate = economy_client.post(
        f"{prefix}/characters/assets/spells",
        json={**spell_payload, "character_version": character["version"]},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["duplicate"] is True

    equipment_payload = {
        "character_id": character["id"],
        "character_version": character["version"],
        "name": "治疗药水",
        "category": "item",
        "quantity": 2,
        "metadata_json": {
            "source_record_id": "healing-potion-2024",
            "unit_weight_lb": 0.5,
            "price_cp": 5000,
        },
    }
    assert economy_client.post(
        f"{prefix}/characters/assets/equipment", json=equipment_payload
    ).status_code == 201
    character = economy_client.get(
        f"{prefix}/characters/{character['id']}"
    ).json()
    assert character["inventory"][0]["quantity"] == 2
    assert economy_client.post(
        f"{prefix}/characters/assets/equipment",
        json={**equipment_payload, "character_version": character["version"], "quantity": 1},
    ).status_code == 201
    character = economy_client.get(
        f"{prefix}/characters/{character['id']}"
    ).json()
    assert len(character["inventory"]) == 1
    assert character["inventory"][0]["quantity"] == 3


def test_spell_metadata_damage_is_mirrored_to_character_combat_action(
    economy_client: TestClient,
) -> None:
    campaign = economy_client.post("/api/v1/campaigns", json={"name": "伤害骰同步"}).json()
    character = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={"name": "雷鸣法师", "hp": 8, "max_hp": 8},
    ).json()
    prefix = f"/api/v1/campaigns/{campaign['id']}"
    created = economy_client.post(
        f"{prefix}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": "雷鸣波",
            "spell_level": 1,
            "prepared": True,
            "metadata_json": {
                "kind": "area_damage",
                "damage": "2d8 thunder",
                "save": "Constitution",
            },
        },
    )
    assert created.status_code == 201, created.text
    refreshed = economy_client.get(
        f"{prefix}/characters/{character['id']}"
    ).json()
    mirrored = next(item for item in refreshed["actions"] if item["name"] == "雷鸣波")
    assert mirrored["damage"] == "2d8 thunder"


def test_spell_and_equipment_preview_confirm_idempotent(economy_client: TestClient) -> None:
    campaign, character, ids = _seed(economy_client)
    spell_body = {
        "character_id": character["id"],
        "character_version": character["version"],
        "known_spell_id": ids["spell"],
        "slot_level": 1,
    }
    preview = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/spells/cast/preview", json=spell_body
    ).json()
    assert preview["slot_after"] == 1
    done = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/spells/cast/confirm",
        json={
            **spell_body,
            "preview_token": preview["preview_token"],
            "idempotency_key": "spell-0001",
        },
    )
    assert done.status_code == 200
    changed = economy_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    equip_body = {
        "character_id": character["id"],
        "character_version": changed["version"],
        "equipment_id": ids["equipment"],
        "operation": "equip",
    }
    equip_preview = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/equipment/preview", json=equip_body
    ).json()
    result = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/equipment/confirm",
        json={
            **equip_body,
            "preview_token": equip_preview["preview_token"],
            "idempotency_key": "armor-0001",
        },
    )
    assert result.status_code == 200
    assert (
        economy_client.get(
            f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
        ).json()["armor_class"]
        == 15
    )


def test_equipment_slots_block_two_handed_shield_and_untrained_armor(
    economy_client: TestClient,
) -> None:
    campaign = economy_client.post("/api/v1/campaigns", json={"name": "装备规则"}).json()
    character = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "装备测试员",
            "hp": 12,
            "max_hp": 12,
            "proficiencies": ["轻甲", "盾牌", "军用武器"],
        },
    ).json()
    engine = create_engine(economy_client.database_url)  # type: ignore[attr-defined]
    with Session(engine) as session, session.begin():
        rows = [
            EquipmentInstance(
                campaign_id=campaign["id"],
                character_id=character["id"],
                name="长剑",
                category="weapon",
            ),
            EquipmentInstance(
                campaign_id=campaign["id"],
                character_id=character["id"],
                name="盾牌",
                category="shield",
            ),
            EquipmentInstance(
                campaign_id=campaign["id"],
                character_id=character["id"],
                name="巨剑",
                category="weapon",
                metadata_json={"two_handed": True},
            ),
            EquipmentInstance(
                campaign_id=campaign["id"],
                character_id=character["id"],
                name="板甲",
                category="armor",
                armor_class=18,
                metadata_json={"armor_type": "heavy"},
            ),
            EquipmentInstance(
                campaign_id=campaign["id"],
                character_id=character["id"],
                name="镶钉皮甲",
                category="armor",
                armor_class=12,
                metadata_json={"armor_type": "light"},
            ),
        ]
        session.add_all(rows)
        session.flush()
        ids = {row.name: row.id for row in rows}

    def equip(name: str, slot: str) -> Any:
        current = economy_client.get(
            f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
        ).json()
        body = {
            "character_id": character["id"],
            "character_version": current["version"],
            "equipment_id": ids[name],
            "operation": "equip",
            "slot": slot,
        }
        preview = economy_client.post(
            f"/api/v1/campaigns/{campaign['id']}/equipment/preview", json=body
        )
        if preview.status_code != 200:
            return preview
        return economy_client.post(
            f"/api/v1/campaigns/{campaign['id']}/equipment/confirm",
            json={
                    **body,
                    "preview_token": preview.json()["preview_token"],
                    "idempotency_key": f"equip-{name}-{current['version']}",
                },
            )

    def unequip(name: str) -> Any:
        current = economy_client.get(
            f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
        ).json()
        body = {
            "character_id": character["id"],
            "character_version": current["version"],
            "equipment_id": ids[name],
            "operation": "unequip",
        }
        preview = economy_client.post(
            f"/api/v1/campaigns/{campaign['id']}/equipment/preview", json=body
        )
        assert preview.status_code == 200
        return economy_client.post(
            f"/api/v1/campaigns/{campaign['id']}/equipment/confirm",
            json={
                **body,
                "preview_token": preview.json()["preview_token"],
                "idempotency_key": f"unequip-{name}-{current['version']}",
            },
        )

    assert equip("长剑", "main_hand").status_code == 200
    assert equip("盾牌", "off_hand").status_code == 200
    blocked_two_handed = equip("巨剑", "main_hand")
    assert blocked_two_handed.status_code == 400
    assert "双手武器" in blocked_two_handed.json()["message"]
    blocked_heavy = equip("板甲", "armor")
    assert blocked_heavy.status_code == 400
    assert "护甲训练" in blocked_heavy.json()["message"]
    assert equip("镶钉皮甲", "armor").status_code == 200
    assert unequip("盾牌").status_code == 200
    after_shield_removed = economy_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert after_shield_removed["armor_class"] == 12
    assert equip("盾牌", "off_hand").status_code == 200
    assert unequip("镶钉皮甲").status_code == 200

    assets = economy_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}/assets"
    ).json()["equipment"]
    slots = {item["name"]: item["slot"] for item in assets if item["equipped"]}
    assert slots == {
        "长剑": "main_hand",
        "盾牌": "off_hand",
    }
    saved_character = economy_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}"
    ).json()
    assert saved_character["armor_class"] == 12


def test_attunement_cap_and_commerce_money_stock(economy_client: TestClient) -> None:
    campaign, character, ids = _seed(economy_client)
    trade = {
        "wallet_id": ids["wallet"],
        "wallet_version": 1,
        "shop_inventory_id": ids["shop"],
        "shop_version": 1,
        "quantity": 2,
        "direction": "buy",
    }
    preview = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/commerce/preview", json=trade
    ).json()
    assert preview["wallet_after"] == 50 and preview["stock_after"] == 1
    confirmed = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/commerce/confirm",
        json={**trade, "preview_token": preview["preview_token"], "idempotency_key": "shop-0001"},
    )
    assert confirmed.status_code == 200
    replay = economy_client.post(
        f"/api/v1/campaigns/{campaign['id']}/commerce/confirm",
        json={**trade, "preview_token": preview["preview_token"], "idempotency_key": "shop-0001"},
    )
    assert replay.status_code == 200
    assets = economy_client.get(
        f"/api/v1/campaigns/{campaign['id']}/characters/{character['id']}/assets"
    )
    assert assets.status_code == 200 and assets.json()["wallet"]["copper"] == 50
    assert any(row["name"] == "治疗药水" and row["quantity"] == 2 for row in assets.json()["equipment"])
