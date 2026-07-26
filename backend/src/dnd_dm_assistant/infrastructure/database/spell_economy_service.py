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
            out["preview_token"] = _token({"data": data, "out": out, "version": c.version})
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
            }
            out["preview_token"] = _token(
                {"data": data, "out": out, "wv": w.version, "sv": item.version}
            )
            return out
