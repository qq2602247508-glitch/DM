# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    Attunement,
    Character,
    CurrencyTransaction,
    EquipmentInstance,
    KnownSpell,
    OperationTransaction,
    PreparedSpell,
    ShopInventory,
    Wallet,
)

RULE = "PHB 2024"


def _token(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


class SpellEconomyService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _character(session: Session, cid: str, char_id: str, version: int) -> Character:
        row = session.get(Character, char_id)
        if row is None or row.campaign_id != cid:
            raise StateNotFoundError("character not found in campaign")
        if row.version != version:
            raise VersionConflict("character", char_id, version, row.version)
        return row

    def character_assets(self, cid: str, character_id: str) -> dict[str, Any]:
        """Read model for the character sheet; mutations remain preview/confirm only."""
        with Session(self.engine) as s:
            character = s.get(Character, character_id)
            if character is None or character.campaign_id != cid:
                raise StateNotFoundError("character not found in campaign")
            spells = s.scalars(
                select(KnownSpell)
                .where(KnownSpell.character_id == character_id)
                .order_by(KnownSpell.spell_level, KnownSpell.name)
            ).all()
            prepared_ids = set(
                s.scalars(
                    select(PreparedSpell.known_spell_id).where(
                        PreparedSpell.character_id == character_id, PreparedSpell.prepared.is_(True)
                    )
                ).all()
            )
            equipment = s.scalars(
                select(EquipmentInstance)
                .where(EquipmentInstance.character_id == character_id)
                .order_by(EquipmentInstance.created_at, EquipmentInstance.id)
            ).all()
            active_ids = set(
                s.scalars(
                    select(Attunement.equipment_instance_id).where(
                        Attunement.character_id == character_id, Attunement.status == "active"
                    )
                ).all()
            )
            wallet = s.scalar(
                select(Wallet).where(Wallet.campaign_id == cid, Wallet.character_id == character_id)
            )
            return {
                "spells": [
                    {**serialize(row), "prepared": row.id in prepared_ids} for row in spells
                ],
                "equipment": [
                    {**serialize(row), "attuned": row.id in active_ids} for row in equipment
                ],
                "wallet": serialize(wallet) if wallet else None,
            }

    def shop_inventory(self, cid: str) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            return [
                serialize(row)
                for row in s.scalars(
                    select(ShopInventory)
                    .where(ShopInventory.campaign_id == cid)
                    .order_by(ShopInventory.name)
                ).all()
            ]

    def create_known_spell(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s, s.begin():
            character = self._character(
                s, cid, str(data.pop("character_id")), int(data.pop("character_version"))
            )
            prepared = bool(data.pop("prepared"))
            spell = KnownSpell(campaign_id=cid, character_id=character.id, **data)
            s.add(spell)
            s.flush()
            if prepared:
                s.add(
                    PreparedSpell(
                        known_spell_id=spell.id,
                        character_id=character.id,
                        prepared=True,
                    )
                )
            character.version += 1
            return {**serialize(spell), "prepared": prepared}

    def create_equipment(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s, s.begin():
            character = self._character(
                s, cid, str(data.pop("character_id")), int(data.pop("character_version"))
            )
            equipment = EquipmentInstance(
                campaign_id=cid, character_id=character.id, **data
            )
            s.add(equipment)
            character.version += 1
            s.flush()
            return serialize(equipment)

    def create_wallet(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s, s.begin():
            character = self._character(
                s, cid, str(data.pop("character_id")), int(data.pop("character_version"))
            )
            if s.scalar(
                select(Wallet).where(
                    Wallet.campaign_id == cid, Wallet.character_id == character.id
                )
            ):
                raise ValueError("character wallet already exists")
            wallet = Wallet(campaign_id=cid, character_id=character.id, **data)
            s.add(wallet)
            character.version += 1
            s.flush()
            return serialize(wallet)

    def create_shop_inventory(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s, s.begin():
            item = ShopInventory(campaign_id=cid, **data)
            s.add(item)
            s.flush()
            return serialize(item)

    def spell_preview(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s:
            c = self._character(s, cid, data["character_id"], data["character_version"])
            spell = s.get(KnownSpell, data["known_spell_id"])
            if spell is None or spell.character_id != c.id:
                raise StateNotFoundError("known spell not found")
            prepared = s.scalar(
                select(PreparedSpell).where(
                    PreparedSpell.character_id == c.id,
                    PreparedSpell.known_spell_id == spell.id,
                    PreparedSpell.prepared.is_(True),
                )
            )
            if spell.spell_level and prepared is None:
                raise ValueError("spell is not prepared")
            if data["slot_level"] < spell.spell_level:
                raise ValueError("slot level is below spell level")
            if not data["ritual"] and spell.spell_level and not data["material_available"]:
                raise ValueError("required material is unavailable")
            slots = (
                dict(c.spellcasting.get("slots", {})) if isinstance(c.spellcasting, dict) else {}
            )
            key = str(data["slot_level"])
            before = slots.get(key, {})
            current = int(before.get("current", 0)) if isinstance(before, dict) else 0
            if spell.spell_level and not data["ritual"] and current < 1:
                raise ValueError("spell slot unavailable")
            result = {
                "character_id": c.id,
                "spell": serialize(spell),
                "slot_level": data["slot_level"],
                "ritual": data["ritual"],
                "slot_before": current,
                "slot_after": current if data["ritual"] or spell.spell_level == 0 else current - 1,
                "concentration": data["concentration"],
                "rule_reference": RULE,
            }
            result["preview_token"] = _token({"data": data, "result": result, "version": c.version})
            return result

    def spell_confirm(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        key = str(data.pop("idempotency_key"))
        token = str(data.pop("preview_token"))
        data["idempotency_key"] = None
        data["preview_token"] = None
        with Session(self.engine) as s, s.begin():
            old = s.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == cid,
                    OperationTransaction.idempotency_key == f"spell:{key}",
                )
            )
            if old:
                return dict(old.after_snapshot)
            preview = self.spell_preview(cid, data)
            if preview["preview_token"] != token:
                raise VersionConflict("spell preview", "state", 1, 2)
            c = self._character(s, cid, data["character_id"], data["character_version"])
            slots = dict(c.spellcasting.get("slots", {}))
            slot = dict(slots.get(str(data["slot_level"]), {}))
            slot["current"] = preview["slot_after"]
            slots[str(data["slot_level"])] = slot
            c.spellcasting = {**c.spellcasting, "slots": slots}
            c.version += 1
            if data["concentration"]:
                c.resources = {
                    **c.resources,
                    "concentration": {"spell_id": data["known_spell_id"], "rule_reference": RULE},
                }
            out = {**preview, "confirmed": True}
            s.add(
                OperationTransaction(
                    campaign_id=cid,
                    operation_type="spell_cast",
                    idempotency_key=f"spell:{key}",
                    before_snapshot={},
                    after_snapshot=out,
                    source="system",
                    confirmed_at=datetime.now(UTC),
                )
            )
            return out

    def equipment_preview(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s:
            c = self._character(s, cid, data["character_id"], data["character_version"])
            e = s.get(EquipmentInstance, data["equipment_id"])
            if e is None or e.campaign_id != cid or e.character_id != c.id:
                raise StateNotFoundError("equipment not found")
            op = data["operation"]
            if op == "consume" and e.quantity < data["amount"]:
                raise ValueError("insufficient consumable quantity")
            if op == "use_charge" and (e.charges is None or e.charges < data["amount"]):
                raise ValueError("insufficient charges")
            if op == "attune":
                if not e.attunement_required:
                    raise ValueError("item does not require attunement")
                active = (
                    s.scalar(
                        select(func.count())
                        .select_from(Attunement)
                        .where(Attunement.character_id == c.id, Attunement.status == "active")
                    )
                    or 0
                )
                if active >= 3:
                    raise ValueError("attunement limit is 3")
            out = {
                "character_id": c.id,
                "equipment_id": e.id,
                "operation": op,
                "before": {
                    "quantity": e.quantity,
                    "charges": e.charges,
                    "equipped": e.equipped,
                    "armor_class": c.armor_class,
                },
                "rule_reference": RULE,
            }
            if op == "equip":
                out["after"] = {"equipped": True, "armor_class": e.armor_class or c.armor_class}
            elif op == "unequip":
                out["after"] = {
                    "equipped": False,
                    "armor_class": 10 if e.armor_class is not None else c.armor_class,
                }
            elif op == "consume":
                out["after"] = {"quantity": e.quantity - data["amount"]}
            elif op == "use_charge":
                out["after"] = {"charges": (e.charges or 0) - data["amount"]}
            elif op == "attune":
                out["after"] = {"attuned": True, "active_attunements": active + 1}
            elif op == "unattune":
                existing = s.scalar(
                    select(Attunement).where(
                        Attunement.equipment_instance_id == e.id, Attunement.status == "active"
                    )
                )
                if existing is None:
                    raise ValueError("item is not attuned")
                out["after"] = {"attuned": False}
            out["preview_token"] = _token({"data": data, "out": out, "version": c.version})
            return out

    def equipment_confirm(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        key = str(data.pop("idempotency_key"))
        token = str(data.pop("preview_token"))
        data["idempotency_key"] = None
        data["preview_token"] = None
        with Session(self.engine) as s, s.begin():
            old = s.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == cid,
                    OperationTransaction.idempotency_key == f"equipment:{key}",
                )
            )
            if old is not None:
                return dict(old.after_snapshot)
            # Recompute in the same transaction below; the public preview token protects DM intent.
            preview = self.equipment_preview(cid, data)
            if preview["preview_token"] != token:
                raise VersionConflict("equipment preview", "state", 1, 2)
            c = self._character(s, cid, data["character_id"], data["character_version"])
            e = s.get(EquipmentInstance, data["equipment_id"])
            if e is None:
                raise StateNotFoundError("equipment not found")
            op, amount = data["operation"], data["amount"]
            if op == "equip":
                e.equipped = True
                if e.armor_class is not None:
                    c.armor_class = e.armor_class
            elif op == "unequip":
                e.equipped = False
                if e.armor_class is not None:
                    c.armor_class = 10
            elif op == "consume":
                e.quantity -= amount
            elif op == "use_charge":
                assert e.charges is not None
                e.charges -= amount
            elif op == "attune":
                s.add(Attunement(character_id=c.id, equipment_instance_id=e.id, status="active"))
            elif op == "unattune":
                att = s.scalar(
                    select(Attunement).where(
                        Attunement.equipment_instance_id == e.id, Attunement.status == "active"
                    )
                )
                if att is None:
                    raise ValueError("item is not attuned")
                att.status = "ended"
                att.version += 1
            c.version += 1
            e.version += 1
            out = {
                **preview,
                "confirmed": True,
                "after": {**preview.get("after", {}), "armor_class": c.armor_class},
            }
            s.add(
                OperationTransaction(
                    campaign_id=cid,
                    operation_type=f"equipment_{op}",
                    idempotency_key=f"equipment:{key}",
                    before_snapshot=preview["before"],
                    after_snapshot=out,
                    source="dm",
                    confirmed_at=datetime.now(UTC),
                )
            )
            return out

    def commerce_preview(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s:
            w = s.get(Wallet, data["wallet_id"])
            item = s.get(ShopInventory, data["shop_inventory_id"])
            if w is None or item is None or w.campaign_id != cid or item.campaign_id != cid:
                raise StateNotFoundError("wallet or shop inventory not found")
            if w.version != data["wallet_version"]:
                raise VersionConflict("wallet", w.id, data["wallet_version"], w.version)
            if item.version != data["shop_version"]:
                raise VersionConflict("shop inventory", item.id, data["shop_version"], item.version)
            total = item.price_copper * data["quantity"] * data["price_modifier_bps"] // 10_000
            if data["direction"] == "buy" and (
                item.quantity < data["quantity"] or w.copper < total
            ):
                raise ValueError("insufficient stock or copper")
            character = s.get(Character, w.character_id) if w.character_id else None
            weight = float(item.metadata_json.get("unit_weight_lb", 0)) * data["quantity"]
            current_weight = float(item.metadata_json.get("current_weight_lb", 0))
            maximum_weight = None
            if character is not None:
                strength = int(
                    character.ability_scores.get("力量", character.ability_scores.get("str", 10))
                )
                maximum_weight = strength * 15
                if data["direction"] == "buy" and current_weight + weight > maximum_weight:
                    raise ValueError("purchase exceeds carrying capacity")
            out = {
                "wallet_id": w.id,
                "shop_inventory_id": item.id,
                "direction": data["direction"],
                "quantity": data["quantity"],
                "total_copper": total,
                "wallet_before": w.copper,
                "wallet_after": w.copper + (-total if data["direction"] == "buy" else total),
                "stock_before": item.quantity,
                "stock_after": item.quantity
                + (-data["quantity"] if data["direction"] == "buy" else data["quantity"]),
                "rule_reference": RULE,
                "weight_change_lb": weight if data["direction"] == "buy" else -weight,
                "maximum_weight_lb": maximum_weight,
            }
            out["preview_token"] = _token(
                {"data": data, "out": out, "wv": w.version, "sv": item.version}
            )
            return out

    def commerce_confirm(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        key = str(data.pop("idempotency_key"))
        token = str(data.pop("preview_token"))
        data["idempotency_key"] = None
        data["preview_token"] = None
        with Session(self.engine) as s, s.begin():
            old = s.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == cid,
                    OperationTransaction.idempotency_key == f"commerce:{key}",
                )
            )
            if old is not None:
                return dict(old.after_snapshot)
            preview = self.commerce_preview(cid, data)
            if preview["preview_token"] != token:
                raise VersionConflict("commerce preview", "state", 1, 2)
            wallet = s.get(Wallet, data["wallet_id"])
            item = s.get(ShopInventory, data["shop_inventory_id"])
            assert wallet is not None and item is not None
            total, qty = int(preview["total_copper"]), data["quantity"]
            buying = data["direction"] == "buy"
            wallet.copper += -total if buying else total
            item.quantity += -qty if buying else qty
            wallet.version += 1
            item.version += 1
            if buying and wallet.character_id:
                # A shop purchase becomes an owned atomic item immediately, so later
                # equip/consume/attune operations never act on a shop stock row.
                s.add(
                    EquipmentInstance(
                        campaign_id=cid,
                        character_id=wallet.character_id,
                        name=item.name,
                        category=str(item.metadata_json.get("category", "gear")),
                        quantity=qty,
                        metadata_json=dict(item.metadata_json),
                    )
                )
            # Every commercial movement records a signed copper ledger row.  The shop
            # is external, so the player wallet is the conserved campaign-side balance.
            s.add(
                CurrencyTransaction(
                    campaign_id=cid,
                    wallet_id=wallet.id,
                    amount_copper=-total if buying else total,
                    kind="purchase" if buying else "sale",
                    idempotency_key=f"commerce:{key}",
                    metadata_json={
                        "shop_inventory_id": item.id,
                        "quantity": qty,
                        "price_copper": total,
                    },
                )
            )
            out = {**preview, "confirmed": True}
            s.add(
                OperationTransaction(
                    campaign_id=cid,
                    operation_type="commerce",
                    idempotency_key=f"commerce:{key}",
                    before_snapshot={
                        "wallet": preview["wallet_before"],
                        "stock": preview["stock_before"],
                    },
                    after_snapshot=out,
                    source="dm",
                    confirmed_at=datetime.now(UTC),
                )
            )
            return out

    def split_preview(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s:
            source, target = (
                s.get(Wallet, data["source_wallet_id"]),
                s.get(Wallet, data["target_wallet_id"]),
            )
            if (
                source is None
                or target is None
                or source.campaign_id != cid
                or target.campaign_id != cid
            ):
                raise StateNotFoundError("wallet not found in campaign")
            if source.id == target.id:
                raise ValueError("source and target wallets must differ")
            if source.version != data["source_wallet_version"]:
                raise VersionConflict(
                    "source wallet", source.id, data["source_wallet_version"], source.version
                )
            if target.version != data["target_wallet_version"]:
                raise VersionConflict(
                    "target wallet", target.id, data["target_wallet_version"], target.version
                )
            if source.copper < data["copper"]:
                raise ValueError("insufficient copper")
            out = {
                "source_wallet_id": source.id,
                "target_wallet_id": target.id,
                "copper": data["copper"],
                "source_before": source.copper,
                "source_after": source.copper - data["copper"],
                "target_before": target.copper,
                "target_after": target.copper + data["copper"],
                "rule_reference": RULE,
            }
            out["preview_token"] = _token(
                {"data": data, "out": out, "sv": source.version, "tv": target.version}
            )
            return out

    def split_confirm(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        key, token = str(data.pop("idempotency_key")), str(data.pop("preview_token"))
        data["idempotency_key"] = None
        data["preview_token"] = None
        with Session(self.engine) as s, s.begin():
            old = s.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == cid,
                    OperationTransaction.idempotency_key == f"split:{key}",
                )
            )
            if old is not None:
                return dict(old.after_snapshot)
            preview = self.split_preview(cid, data)
            if preview["preview_token"] != token:
                raise VersionConflict("currency split preview", "state", 1, 2)
            source, target = (
                s.get(Wallet, data["source_wallet_id"]),
                s.get(Wallet, data["target_wallet_id"]),
            )
            assert source is not None and target is not None
            amount = data["copper"]
            source.copper -= amount
            target.copper += amount
            source.version += 1
            target.version += 1
            s.add_all(
                [
                    CurrencyTransaction(
                        campaign_id=cid,
                        wallet_id=source.id,
                        amount_copper=-amount,
                        kind="split",
                        idempotency_key=f"split:{key}:debit",
                    ),
                    CurrencyTransaction(
                        campaign_id=cid,
                        wallet_id=target.id,
                        amount_copper=amount,
                        kind="split",
                        idempotency_key=f"split:{key}:credit",
                    ),
                ]
            )
            out = {**preview, "confirmed": True}
            s.add(
                OperationTransaction(
                    campaign_id=cid,
                    operation_type="currency_split",
                    idempotency_key=f"split:{key}",
                    before_snapshot={
                        "source": preview["source_before"],
                        "target": preview["target_before"],
                    },
                    after_snapshot=out,
                    source="dm",
                    confirmed_at=datetime.now(UTC),
                )
            )
            return out
