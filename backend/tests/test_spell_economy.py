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
