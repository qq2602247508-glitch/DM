# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.equipment_rules import (
    armor_class_from_profile,
    armor_is_proficient,
    equipment_profile,
    weapon_proficiency_warning,
)
from dnd_dm_assistant.domain.item_spec import (
    ItemSpec,
    compile_item_spec,
    item_runtime_projection,
    materialize_item_effects,
)
from dnd_dm_assistant.domain.spell_rules import enrich_spell_action
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    Attunement,
    Character,
    CurrencyTransaction,
    EquipmentInstance,
    KnownSpell,
    OperationTransaction,
    PlayerRoom,
    PreparedSpell,
    RulesKernelAdjudicationWindow,
    SceneParticipant,
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

    @staticmethod
    def _has_expert_divination(character: Character) -> bool:
        for raw in character.features or []:
            if not isinstance(raw, dict):
                continue
            runtime = raw.get("runtime")
            registry = runtime.get("registry") if isinstance(runtime, dict) else None
            actions = registry.get("actions") if isinstance(registry, dict) else None
            if not isinstance(actions, dict):
                continue
            if any(
                isinstance(action, dict)
                and action.get("kind") == "spell_slot_recovery"
                and action.get("id") == "expert_divination_slot_recovery"
                for action in actions.values()
            ):
                return True
        return False

    @staticmethod
    def _has_ritual_spellbook_casting(character: Character) -> bool:
        for raw in character.features or []:
            if not isinstance(raw, dict):
                continue
            runtime = raw.get("runtime")
            registry = runtime.get("registry") if isinstance(runtime, dict) else None
            advancement = registry.get("advancement") if isinstance(registry, dict) else None
            if (
                isinstance(advancement, dict)
                and advancement.get("kind") == "ritual_spellbook_casting"
                and advancement.get("requires_ritual_tag") is True
                and advancement.get("requires_prepared") is False
            ):
                return True
        return False

    @classmethod
    def _unprepared_ritual_allowed(
        cls,
        character: Character,
        spell: KnownSpell,
        data: dict[str, Any],
    ) -> bool:
        metadata = dict(spell.metadata_json or {})
        ritual_tagged = metadata.get("ritual") is True
        spell_class = str(metadata.get("class_name") or "").strip()
        return bool(
            data.get("ritual")
            and ritual_tagged
            and spell_class in {"法师", "wizard", "Wizard"}
            and cls._has_ritual_spellbook_casting(character)
        )

    @staticmethod
    def _weapon_focus_allowed(character: Character, spell: KnownSpell) -> bool:
        spell_class = str((spell.metadata_json or {}).get("class_name") or "").strip()
        for raw in character.features or []:
            if not isinstance(raw, dict):
                continue
            runtime = raw.get("runtime")
            registry = runtime.get("registry") if isinstance(runtime, dict) else None
            spellcasting = registry.get("spellcasting") if isinstance(registry, dict) else None
            entries = spellcasting if isinstance(spellcasting, list) else [spellcasting]
            for entry in entries:
                if (
                    isinstance(entry, dict)
                    and entry.get("kind") == "spellcasting_focus_permission"
                    and entry.get("spell_class") == spell_class
                    and "weapon" in list(entry.get("allowed_equipment_kinds") or [])
                ):
                    return True
        return False

    @classmethod
    def _expert_divination_recovery(
        cls,
        character: Character,
        spell: KnownSpell,
        data: dict[str, Any],
    ) -> dict[str, int] | None:
        requested = data.get("recovery_slot_level")
        if requested is None:
            return None
        if data.get("ritual") or data.get("free_cast"):
            raise ValueError("专业预言必须通过消耗普通法术位施放，不能用于仪式或免费施法")
        if not cls._has_expert_divination(character):
            raise ValueError("角色没有可执行的专业预言法术位恢复合同")
        cast_level = int(spell.spell_level)
        recovery_level = int(requested)
        school = str((spell.metadata_json or {}).get("school") or "").strip().casefold()
        if cast_level < 2 or school not in {"divination", "预言", "预言学派"}:
            raise ValueError("专业预言只能在施放二环以上预言学派法术后使用")
        if recovery_level >= cast_level or recovery_level > 5:
            raise ValueError("专业预言只能恢复低于施法环阶且不超过五环的法术位")
        raw_slots = character.spellcasting.get("slots", {})
        slots = dict(raw_slots) if isinstance(raw_slots, dict) else {}
        raw_slot = slots.get(str(recovery_level), {})
        slot = dict(raw_slot) if isinstance(raw_slot, dict) else {}
        current = int(slot.get("current", 0))
        maximum = int(slot.get("max", current))
        if maximum < 1 or current >= maximum:
            raise ValueError("专业预言选择的法术位没有已消耗空间")
        return {
            "slot_level": recovery_level,
            "slot_before": current,
            "slot_after": current + 1,
            "slot_max": maximum,
        }

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
            equipment_rows = []
            for row in equipment:
                profile = equipment_profile(
                    row.name, row.category, dict(row.metadata_json), row.armor_class
                )
                row_payload = {
                    **serialize(row),
                    "attuned": row.id in active_ids,
                    "slot": row.metadata_json.get("equipment_slot"),
                    "profile": profile,
                }
                raw_item_spec = row.metadata_json.get("item_spec")
                if isinstance(raw_item_spec, dict):
                    row_payload["item_spec"] = raw_item_spec
                equipment_rows.append(row_payload)
            item_effects = materialize_item_effects(equipment_rows, active_ids)
            return {
                "spells": [
                    {**serialize(row), "prepared": row.id in prepared_ids} for row in spells
                ],
                "equipment": equipment_rows,
                "item_effects": item_effects,
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
            existing = s.scalar(
                select(KnownSpell).where(
                    KnownSpell.character_id == character.id,
                    func.lower(KnownSpell.name) == str(data["name"]).lower(),
                )
            )
            if existing is not None:
                is_prepared = s.scalar(
                    select(PreparedSpell).where(
                        PreparedSpell.character_id == character.id,
                        PreparedSpell.known_spell_id == existing.id,
                        PreparedSpell.prepared.is_(True),
                    )
                )
                return {
                    **serialize(existing),
                    "prepared": is_prepared is not None,
                    "duplicate": True,
                }
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
            metadata = dict(spell.metadata_json)
            raw_character_spell = metadata.get("character_spell")
            character_spell = (
                dict(raw_character_spell)
                if isinstance(raw_character_spell, dict)
                else {
                    "name": spell.name,
                    "spell_level": spell.spell_level,
                    "prepared": prepared,
                    "source_reference": spell.source_reference,
                    "source_record_id": metadata.get("source_record_id"),
                }
            )
            # DM/imported spell metadata historically stored the combat fields
            # at the top level. Preserve those fields when mirroring the spell
            # onto the character card; otherwise the player UI cannot show the
            # damage formula and the combat endpoint loses the damage type.
            for key in (
                "source_record_id",
                "source_path",
                "damage",
                "damage_expression",
                "damage_dice",
                "damage_type",
                "save_ability",
                "save_dc",
                "half_damage_on_save",
                "range",
                "description",
                "cost",
                "resource_key",
                "resource_cost",
                "resolution_kind",
                "rule_plan",
            ):
                if character_spell.get(key) in (None, "") and metadata.get(key) not in (None, ""):
                    character_spell[key] = metadata[key]
            character_spell.update(
                {
                    "name": spell.name,
                    "spell_level": spell.spell_level,
                    "prepared": prepared,
                }
            )
            character_spell = enrich_spell_action(
                character_spell,
                spellcasting=character.spellcasting,
            )
            spell_identity = str(
                character_spell.get("source_record_id") or character_spell["name"]
            )
            mirrored_spells = [
                item
                for item in character.spells
                if not (
                    isinstance(item, dict)
                    and str(item.get("source_record_id") or item.get("name") or "")
                    == spell_identity
                )
            ]
            mirrored_spells.append(character_spell)
            character.spells = mirrored_spells
            if spell.spell_level == 0 or prepared:
                mirrored_actions = [
                    item
                    for item in character.actions
                    if not (
                        isinstance(item, dict)
                        and str(item.get("source_record_id") or item.get("name") or "")
                        == spell_identity
                    )
                ]
                mirrored_actions.append(character_spell)
                character.actions = mirrored_actions
            character.version += 1
            return {**serialize(spell), "prepared": prepared}

    def create_equipment(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s, s.begin():
            character = self._character(
                s, cid, str(data.pop("character_id")), int(data.pop("character_version"))
            )
            metadata = dict(data.get("metadata_json") or {})
            raw_item_spec = metadata.get("item_spec")
            if raw_item_spec is not None:
                spec = ItemSpec.from_dict(raw_item_spec, "equipment.metadata_json.item_spec")
                compiled = compile_item_spec(spec)
                if compiled["compile_status"] != "full":
                    raise ValueError(
                        "ItemSpec is not production-ready: "
                        + ", ".join(compiled["blockers"])
                    )
                metadata["item_spec"] = item_runtime_projection(spec)
                metadata["item_spec_fingerprint"] = spec.fingerprint()
                data["metadata_json"] = metadata
                data["attunement_required"] = spec.requires_attunement
                if spec.charges:
                    data["max_charges"] = spec.charges.get("maximum")
                    data["charges"] = spec.charges.get("current", spec.charges.get("maximum"))
                data["category"] = str(data.get("category") or spec.item_kind)
            source_record_id = str(metadata.get("source_record_id") or "")
            existing = s.scalar(
                select(EquipmentInstance).where(
                    EquipmentInstance.character_id == character.id,
                    func.lower(EquipmentInstance.name) == str(data["name"]).lower(),
                )
            )
            if existing is not None:
                existing.quantity += int(data.get("quantity") or 1)
                existing.category = str(data.get("category") or existing.category)
                existing.armor_class = data.get("armor_class")
                existing.attunement_required = bool(
                    data.get("attunement_required", existing.attunement_required)
                )
                existing.charges = data.get("charges")
                existing.max_charges = data.get("max_charges")
                existing.metadata_json = {**existing.metadata_json, **metadata}
                equipment = existing
            else:
                equipment = EquipmentInstance(
                    campaign_id=cid, character_id=character.id, **data
                )
                s.add(equipment)
                s.flush()
            inventory = list(character.inventory)
            matching_index = next(
                (
                    index
                    for index, item in enumerate(inventory)
                    if isinstance(item, dict)
                    and (
                        (
                            source_record_id
                            and str(item.get("source_record_id") or "") == source_record_id
                        )
                        or str(item.get("name") or "").lower() == equipment.name.lower()
                    )
                ),
                None,
            )
            summary = {
                "name": equipment.name,
                "quantity": equipment.quantity,
                "category": equipment.category,
                "armor_class": equipment.armor_class,
                "attunement_required": equipment.attunement_required,
                "charges": equipment.charges,
                "max_charges": equipment.max_charges,
                **metadata,
            }
            if matching_index is None:
                inventory.append(summary)
            else:
                old_summary = inventory[matching_index]
                previous = dict(old_summary) if isinstance(old_summary, dict) else {}
                inventory[matching_index] = {
                    **previous,
                    **summary,
                }
            character.inventory = inventory
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
            if (
                spell.spell_level
                and prepared is None
                and not self._unprepared_ritual_allowed(c, spell, data)
            ):
                raise ValueError("spell is not prepared")
            focus_equipment_id = str(data.get("focus_equipment_id") or "").strip()
            focus_equipment: EquipmentInstance | None = None
            if focus_equipment_id:
                focus_equipment = s.get(EquipmentInstance, focus_equipment_id)
                if (
                    focus_equipment is None
                    or focus_equipment.character_id != c.id
                    or not focus_equipment.equipped
                ):
                    raise ValueError("selected spellcasting focus is not equipped by this character")
                profile = equipment_profile(
                    focus_equipment.name,
                    focus_equipment.category,
                    dict(focus_equipment.metadata_json or {}),
                    focus_equipment.armor_class,
                )
                if profile.get("kind") != "weapon":
                    raise ValueError("selected spellcasting focus is not a weapon")
                if not self._weapon_focus_allowed(c, spell):
                    raise ValueError("character cannot use a weapon as a focus for this spell class")
                warning = weapon_proficiency_warning(
                    focus_equipment.name,
                    list(c.proficiencies or []),
                )
                if warning:
                    raise ValueError(warning)
            if data["slot_level"] < spell.spell_level:
                raise ValueError("slot level is below spell level")
            free_cast_key = ""
            free_cast_cost = 0
            free_cast_before = 0
            if data.get("free_cast"):
                if data["slot_level"] != spell.spell_level:
                    raise ValueError("free cast must use the spell's base level")
                sheet_spell = next(
                    (
                        item
                        for item in c.spells or []
                        if isinstance(item, dict)
                        and (
                            str(item.get("source_record_id") or "")
                            == str(spell.metadata_json.get("source_record_id") or "")
                            or str(item.get("name") or "") == spell.name
                        )
                    ),
                    None,
                )
                if not isinstance(sheet_spell, dict):
                    raise ValueError("free cast spell metadata is missing")
                free_cast_key = str(sheet_spell.get("resource_key") or "").strip()
                free_cast_cost = int(sheet_spell.get("resource_cost") or 1)
                if not free_cast_key or free_cast_cost < 1:
                    raise ValueError("spell is not eligible for a free cast")
                raw_resource = c.resources.get(free_cast_key)
                resource = raw_resource if isinstance(raw_resource, dict) else {}
                free_cast_before = int(resource.get("current") or 0)
                if free_cast_before < free_cast_cost:
                    raise ValueError("free cast resource unavailable")
            if not data["ritual"] and spell.spell_level and not data["material_available"]:
                raise ValueError("required material is unavailable")
            raw_slots = c.spellcasting.get("slots", {})
            slots = dict(raw_slots) if isinstance(raw_slots, dict) else {}
            key = str(data["slot_level"])
            before = slots.get(key, {})
            current = int(before.get("current", 0)) if isinstance(before, dict) else 0
            if spell.spell_level and not data["ritual"] and not data.get("free_cast") and current < 1:
                raise ValueError("spell slot unavailable")
            result = {
                "character_id": c.id,
                "spell": serialize(spell),
                "slot_level": data["slot_level"],
                "ritual": data["ritual"],
                "slot_before": current,
                "slot_after": current
                if data["ritual"] or spell.spell_level == 0 or data.get("free_cast")
                else current - 1,
                "free_cast": bool(data.get("free_cast")),
                "free_cast_resource_key": free_cast_key or None,
                "free_cast_before": free_cast_before,
                "free_cast_after": (
                    free_cast_before - free_cast_cost if free_cast_key else free_cast_before
                ),
                "concentration": data["concentration"],
                "focus_equipment_id": focus_equipment.id if focus_equipment else None,
                "rule_reference": RULE,
            }
            recovery = self._expert_divination_recovery(c, spell, data)
            if recovery is not None:
                result["expert_divination_recovery"] = recovery
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
                replay = dict(old.after_snapshot or {})
                # ``character_after`` is an internal transaction snapshot for
                # rollback/audit.  It is deliberately not part of the public
                # spell-confirm response, so an idempotent replay is byte
                # identical to the first confirmation.
                replay.pop("character_after", None)
                return replay
            preview = self.spell_preview(cid, data)
            if preview["preview_token"] != token:
                raise VersionConflict("spell preview", "state", 1, 2)
            c = self._character(s, cid, data["character_id"], data["character_version"])
            before_character = {
                "character_id": c.id,
                "version": c.version,
                "spellcasting": dict(c.spellcasting or {}),
                "resources": dict(c.resources or {}),
            }
            before_concentration = dict(c.resources or {}).get("concentration")
            if preview.get("free_cast"):
                resource_key = str(preview.get("free_cast_resource_key") or "").strip()
                resources = dict(c.resources or {})
                raw_resource = resources.get(resource_key)
                resource = dict(raw_resource) if isinstance(raw_resource, dict) else {}
                before = int(resource.get("current") or 0)
                cost = before - int(preview.get("free_cast_after") or 0)
                if not resource_key or cost < 1 or before < cost:
                    raise ValueError("free cast resource changed before confirmation")
                resource["current"] = before - cost
                resources[resource_key] = resource
                c.resources = resources
            else:
                raw_slots = c.spellcasting.get("slots", {})
                slots = dict(raw_slots) if isinstance(raw_slots, dict) else {}
                raw_slot = slots.get(str(data["slot_level"]), {})
                slot = dict(raw_slot) if isinstance(raw_slot, dict) else {}
                slot["current"] = preview["slot_after"]
                slots[str(data["slot_level"])] = slot
                c.spellcasting = {**c.spellcasting, "slots": slots}
            recovery = preview.get("expert_divination_recovery")
            if isinstance(recovery, dict):
                recovery_level = int(recovery["slot_level"])
                raw_slots = c.spellcasting.get("slots", {})
                slots = dict(raw_slots) if isinstance(raw_slots, dict) else {}
                raw_recovery_slot = slots.get(str(recovery_level), {})
                recovery_slot = (
                    dict(raw_recovery_slot) if isinstance(raw_recovery_slot, dict) else {}
                )
                current = int(recovery_slot.get("current", 0))
                maximum = int(recovery_slot.get("max", current))
                if current != int(recovery["slot_before"]) or current >= maximum:
                    raise VersionConflict("spell slot", str(recovery_level), int(recovery["slot_before"]), current)
                recovery_slot["current"] = current + 1
                slots[str(recovery_level)] = recovery_slot
                c.spellcasting = {**c.spellcasting, "slots": slots}
            c.version += 1
            if data["concentration"]:
                c.resources = {
                    **c.resources,
                    "concentration": {"spell_id": data["known_spell_id"], "rule_reference": RULE},
                }
            out = {**preview, "confirmed": True}
            out["character_version_before"] = before_character["version"]
            out["character_version_after"] = c.version
            out["before_concentration"] = before_concentration
            out["after_concentration"] = dict(c.resources or {}).get("concentration")
            s.add(
                OperationTransaction(
                    campaign_id=cid,
                    operation_type="spell_cast",
                    idempotency_key=f"spell:{key}",
                    before_snapshot=before_character,
                    after_snapshot={
                        **out,
                        "character_after": {
                            "version": c.version,
                            "spellcasting": dict(c.spellcasting or {}),
                            "resources": dict(c.resources or {}),
                        },
                    },
                    source="system",
                    confirmed_at=datetime.now(UTC),
                )
            )
            return out

    def rollback_spell_cast(
        self,
        cid: str,
        *,
        idempotency_key: str,
        expected_character_version: int,
    ) -> dict[str, Any]:
        """Compensate a spell-economy commit when its combat consumer fails.

        The compensation itself is CAS guarded and recorded on the original
        transaction.  It is intentionally generic and is only used by the
        content-runtime coordinator after a downstream production consumer
        rejects the already-previewed action.
        """

        transaction_key = f"spell:{idempotency_key}"
        with Session(self.engine) as s, s.begin():
            transaction = s.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == cid,
                    OperationTransaction.idempotency_key == transaction_key,
                )
            )
            if transaction is None:
                raise StateNotFoundError("spell transaction not found")
            if transaction.status == "reverted":
                return {
                    "status": "already_reverted",
                    "idempotency_key": idempotency_key,
                    "transaction_id": transaction.id,
                }
            before = dict(transaction.before_snapshot or {})
            character_id = str(before.get("character_id") or "")
            character = s.get(Character, character_id)
            if character is None or character.campaign_id != cid:
                raise StateNotFoundError("spell rollback character not found")
            if character.version != expected_character_version:
                raise VersionConflict(
                    "character",
                    character.id,
                    expected_character_version,
                    character.version,
                )
            character.spellcasting = dict(before.get("spellcasting") or {})
            character.resources = dict(before.get("resources") or {})
            character.version += 1
            transaction.status = "reverted"
            transaction.reason = "content runtime downstream consumer rejected action"
            transaction.reverted_at = datetime.now(UTC)
            transaction.after_snapshot = {
                **dict(transaction.after_snapshot or {}),
                "rollback": {
                    "character_version_after": character.version,
                    "spellcasting": dict(character.spellcasting or {}),
                    "resources": dict(character.resources or {}),
                },
            }
            return {
                "status": "reverted",
                "idempotency_key": idempotency_key,
                "transaction_id": transaction.id,
                "character_id": character.id,
                "character_version": character.version,
            }

    @staticmethod
    def _equipment_armor_class(
        character: Character,
        equipped: Sequence[EquipmentInstance],
        *,
        add: EquipmentInstance | None = None,
        remove: EquipmentInstance | None = None,
    ) -> tuple[int, int]:
        relevant: list[tuple[EquipmentInstance, dict[str, Any]]] = []
        for row in equipped:
            profile = equipment_profile(
                row.name, row.category, dict(row.metadata_json), row.armor_class
            )
            if profile["kind"] in {"armor", "shield"}:
                relevant.append((row, profile))
        baseline = next(
            (
                int(value)
                for row, _profile in relevant
                for value in (
                    row.metadata_json.get("equipment_ac_baseline"),
                    row.metadata_json.get("armor_class_before_equip"),
                )
                if isinstance(value, int)
            ),
            None,
        )
        dexterity = int(character.ability_scores.get("dexterity", 10))
        dexterity_modifier = (dexterity - 10) // 2
        if baseline is None:
            if any(profile["kind"] == "armor" for _row, profile in relevant):
                class_name = str(character.class_name or "")
                wisdom_modifier = (
                    int(character.ability_scores.get("wisdom", 10)) - 10
                ) // 2
                constitution_modifier = (
                    int(character.ability_scores.get("constitution", 10)) - 10
                ) // 2
                baseline = (
                    10 + dexterity_modifier + wisdom_modifier
                    if "武僧" in class_name
                    else 10 + dexterity_modifier + constitution_modifier
                    if "野蛮人" in class_name
                    else 10 + dexterity_modifier
                )
            elif any(profile["kind"] == "shield" for _row, profile in relevant):
                baseline = max(10, character.armor_class - 2)
            else:
                baseline = character.armor_class

        after_rows = [
            row for row in equipped if remove is None or row.id != remove.id
        ]
        if add is not None and all(row.id != add.id for row in after_rows):
            after_rows.append(add)
        after_profiles = [
            equipment_profile(
                row.name, row.category, dict(row.metadata_json), row.armor_class
            )
            for row in after_rows
        ]
        armor_profile = next(
            (profile for profile in after_profiles if profile["kind"] == "armor"),
            None,
        )
        armor_ac = (
            armor_class_from_profile(armor_profile, dexterity_modifier)
            if armor_profile is not None
            else None
        )
        calculated = armor_ac if armor_ac is not None else baseline
        if any(profile["kind"] == "shield" for profile in after_profiles):
            calculated += 2
        return calculated, baseline

    def equipment_preview(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s:
            c = self._character(s, cid, data["character_id"], data["character_version"])
            e = s.get(EquipmentInstance, data["equipment_id"])
            if e is None or e.campaign_id != cid or e.character_id != c.id:
                raise StateNotFoundError("equipment not found")
            op = data["operation"]
            profile = equipment_profile(e.name, e.category, dict(e.metadata_json), e.armor_class)
            requested_slot = data.get("slot") or profile["default_slot"]
            warnings: list[str] = []
            equipped_all = s.scalars(
                select(EquipmentInstance).where(
                    EquipmentInstance.character_id == c.id,
                    EquipmentInstance.equipped.is_(True),
                )
            ).all()
            if op == "equip":
                if profile["kind"] == "consumable":
                    raise ValueError("消耗品不能装备；请使用或消耗它。")
                if e.equipped:
                    raise ValueError("item is already equipped")
                if requested_slot not in profile["allowed_slots"]:
                    raise ValueError(
                        f"{e.name}不能装备到{requested_slot}；允许位置："
                        + "、".join(profile["allowed_slots"])
                    )
                if (
                    profile["kind"] == "armor"
                    and profile["armor_type"]
                    and not armor_is_proficient(list(c.proficiencies), profile["armor_type"])
                ):
                    raise ValueError(
                        f"角色没有{profile['armor_type'] or '该类'}护甲训练，"
                        "玩家快捷装备已阻止；如采用房规请由 DM 调整。"
                    )
                if profile["kind"] == "shield" and "盾牌" not in {
                    str(value) for value in c.proficiencies
                }:
                    raise ValueError("角色没有盾牌训练，玩家快捷装备已阻止。")
                equipped = [current for current in equipped_all if current.id != e.id]
                occupied: dict[str, EquipmentInstance] = {}
                has_two_handed = False
                for current in equipped:
                    current_profile = equipment_profile(
                        current.name,
                        current.category,
                        dict(current.metadata_json),
                        current.armor_class,
                    )
                    current_slot = str(
                        current.metadata_json.get("equipment_slot")
                        or current_profile["default_slot"]
                    )
                    occupied[current_slot] = current
                    has_two_handed = has_two_handed or bool(current_profile["two_handed"])
                if profile["two_handed"] and (
                    "main_hand" in occupied or "off_hand" in occupied
                ):
                    raise ValueError("双手武器需要主手和副手都为空。")
                if has_two_handed and requested_slot in {"main_hand", "off_hand"}:
                    raise ValueError("当前双手武器占用两只手，请先卸下。")
                if requested_slot == "armor" and "armor" in occupied:
                    raise ValueError("同一时间只能穿着一套护甲。")
                if requested_slot in occupied:
                    raise ValueError(
                        f"{requested_slot}已由{occupied[requested_slot].name}占用，请先卸下。"
                    )
                if profile["kind"] == "weapon":
                    warning = weapon_proficiency_warning(e.name, list(c.proficiencies))
                    if warning:
                        warnings.append(warning)
            if op == "consume":
                if profile["kind"] != "consumable":
                    raise ValueError("只有消耗品可以使用或消耗。")
                if e.quantity < data["amount"]:
                    raise ValueError("insufficient consumable quantity")
            if op == "use_charge" and (e.charges is None or e.charges < data["amount"]):
                raise ValueError("insufficient charges")
            item_spec = e.metadata_json.get("item_spec")
            tattoo_lifecycle = self._typed_tattoo_lifecycle(item_spec)
            if op == "use_action":
                if not isinstance(item_spec, dict):
                    raise ValueError("item has no typed granted action")
                attuned = s.scalar(
                    select(Attunement).where(
                        Attunement.character_id == c.id,
                        Attunement.equipment_instance_id == e.id,
                        Attunement.status == "active",
                    )
                )
                if not e.equipped and attuned is None:
                    raise ValueError("item action requires the item to be equipped or attuned")
                actions = [item for item in item_spec.get("granted_actions", []) if isinstance(item, dict)]
                action_id = str(data.get("action_id") or "").strip()
                action = next((item for item in actions if str(item.get("action_id") or item.get("id") or "") == action_id), None)
                if action is None:
                    raise ValueError("requested item action is not in the typed ItemSpec")
                required = int(action.get("charge_cost") or 0)
                if required and (e.charges is None or e.charges < required):
                    raise ValueError("insufficient charges for item action")
            if op == "unequip" and not e.equipped:
                raise ValueError("item is not equipped")
            if op == "attune":
                if not e.attunement_required:
                    raise ValueError("item does not require attunement")
                existing_attunement = s.scalar(
                    select(Attunement).where(
                        Attunement.equipment_instance_id == e.id,
                        Attunement.status == "active",
                    )
                )
                if existing_attunement is not None:
                    raise ValueError("item is already attuned")
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
                "slot": requested_slot if op == "equip" else e.metadata_json.get("equipment_slot"),
                "profile": profile,
                "warnings": warnings,
                "before": {
                    "quantity": e.quantity,
                    "charges": e.charges,
                    "equipped": e.equipped,
                    "armor_class": c.armor_class,
                },
                "rule_reference": RULE,
            }
            if tattoo_lifecycle and op in {"attune", "unattune"}:
                out["before"]["tattoo_lifecycle"] = e.metadata_json.get(
                    "item_tattoo_lifecycle"
                )
            if op == "equip":
                after_ac, ac_baseline = self._equipment_armor_class(
                    c, equipped_all, add=e
                )
                out["after"] = {
                    "equipped": True,
                    "slot": requested_slot,
                    "armor_class": after_ac,
                    "equipment_ac_baseline": ac_baseline,
                }
            elif op == "unequip":
                after_ac, _ac_baseline = self._equipment_armor_class(
                    c, equipped_all, remove=e
                )
                out["after"] = {
                    "equipped": False,
                    "armor_class": after_ac,
                }
            elif op == "consume":
                out["after"] = {"quantity": e.quantity - data["amount"]}
            elif op == "use_charge":
                out["after"] = {"charges": (e.charges or 0) - data["amount"]}
            elif op == "use_action":
                action = next(
                    item
                    for item in item_spec.get("granted_actions", [])
                    if str(item.get("action_id") or item.get("id") or "")
                    == str(data.get("action_id") or "")
                )
                cost = int(action.get("charge_cost") or 0)
                out["after"] = {
                    "action_id": str(data.get("action_id")),
                    "charges": (e.charges - cost) if cost and e.charges is not None else e.charges,
                    "rules_kernel_consumer": "item.granted_action.v1",
                }
            elif op == "attune":
                out["after"] = {"attuned": True, "active_attunements": active + 1}
                if tattoo_lifecycle:
                    out["tattoo_lifecycle"] = {
                        "consumer_id": "item.attunement.v1",
                        "clause_id": tattoo_lifecycle["clause_id"],
                        "operation": tattoo_lifecycle["on_attune"],
                        "phase": "manifested",
                        "needle_state": "ink",
                        "effects_active": True,
                    }
                    out["after"]["tattoo_lifecycle"] = out["tattoo_lifecycle"]
            elif op == "unattune":
                existing = s.scalar(
                    select(Attunement).where(
                        Attunement.equipment_instance_id == e.id, Attunement.status == "active"
                    )
                )
                if existing is None:
                    raise ValueError("item is not attuned")
                out["after"] = {"attuned": False}
                if tattoo_lifecycle:
                    out["tattoo_lifecycle"] = {
                        "consumer_id": "item.attunement.v1",
                        "clause_id": tattoo_lifecycle["clause_id"],
                        "operation": tattoo_lifecycle["on_unattune"],
                        "phase": "needle_returned",
                        "needle_state": "needle",
                        "effects_active": False,
                    }
                    out["after"]["tattoo_lifecycle"] = out["tattoo_lifecycle"]
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
                e.metadata_json = {
                    **e.metadata_json,
                    "equipment_slot": preview["slot"],
                    "equipment_profile": preview["profile"],
                    "equipment_ac_baseline": preview["after"][
                        "equipment_ac_baseline"
                    ],
                }
                c.armor_class = int(preview["after"]["armor_class"])
            elif op == "unequip":
                e.equipped = False
                e.metadata_json = {
                    key: value
                    for key, value in e.metadata_json.items()
                    if key
                    not in {
                        "equipment_slot",
                        "armor_class_before_equip",
                        "equipment_ac_baseline",
                    }
                }
                c.armor_class = int(preview["after"]["armor_class"])
            elif op == "consume":
                e.quantity -= amount
            elif op == "use_charge":
                assert e.charges is not None
                e.charges -= amount
            elif op == "use_action":
                item_spec = e.metadata_json.get("item_spec")
                actions = item_spec.get("granted_actions", []) if isinstance(item_spec, dict) else []
                action = next(
                    item
                    for item in actions
                    if str(item.get("action_id") or item.get("id") or "")
                    == str(data.get("action_id") or "")
                )
                cost = int(action.get("charge_cost") or 0)
                if cost:
                    if e.charges is None or e.charges < cost:
                        raise ValueError("insufficient charges for item action")
                    e.charges -= cost
            elif op == "attune":
                old_attunement = s.scalar(
                    select(Attunement).where(Attunement.equipment_instance_id == e.id)
                )
                if old_attunement is None:
                    s.add(
                        Attunement(
                            character_id=c.id,
                            equipment_instance_id=e.id,
                            status="active",
                        )
                    )
                else:
                    old_attunement.status = "active"
                    old_attunement.version += 1
                if preview.get("tattoo_lifecycle"):
                    e.metadata_json = {
                        **e.metadata_json,
                        "item_tattoo_lifecycle": preview["tattoo_lifecycle"],
                    }
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
                if preview.get("tattoo_lifecycle"):
                    e.metadata_json = {
                        **e.metadata_json,
                        "item_tattoo_lifecycle": preview["tattoo_lifecycle"],
                    }
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

    @staticmethod
    def _typed_tattoo_lifecycle(item_spec: object) -> dict[str, str] | None:
        if not isinstance(item_spec, dict):
            return None
        for raw_clause in item_spec.get("clauses", []):
            if not isinstance(raw_clause, dict) or raw_clause.get("clause_type") != "tattoo_lifecycle":
                continue
            parameters = raw_clause.get("parameters")
            if not isinstance(parameters, dict):
                raise ValueError("tattoo lifecycle clause parameters must be typed")
            on_attune = str(parameters.get("on_attune") or "").strip()
            on_unattune = str(parameters.get("on_unattune") or "").strip()
            clause_id = str(raw_clause.get("clause_id") or "").strip()
            if not clause_id or not on_attune or not on_unattune:
                raise ValueError("tattoo lifecycle clause requires typed transitions")
            return {
                "clause_id": clause_id,
                "on_attune": on_attune,
                "on_unattune": on_unattune,
            }
        return None

    @staticmethod
    def _item_adjudication_clause(
        equipment: EquipmentInstance, clause_id: str
    ) -> dict[str, Any]:
        raw_spec = (equipment.metadata_json or {}).get("item_spec")
        if not isinstance(raw_spec, dict):
            raise ValueError("item DM continuation requires a typed ItemSpec")
        clauses = [item for item in raw_spec.get("clauses", []) if isinstance(item, dict)]
        clause = next(
            (item for item in clauses if str(item.get("clause_id") or "") == clause_id),
            None,
        )
        if clause is None:
            raise StateNotFoundError("typed item clause not found")
        evidence = clause.get("evidence")
        if not isinstance(evidence, dict) or not str(
            evidence.get("source_text") or evidence.get("source_excerpt") or ""
        ).strip():
            raise ValueError("item DM continuation requires source text evidence")
        return clause

    def item_adjudication_preview(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        """Open a durable DM window for one typed-but-ambiguous item clause."""

        key = str(data.get("idempotency_key") or "").strip()
        if len(key) < 8:
            raise ValueError("item adjudication idempotency_key is required")
        operation_key = f"item-dm:{key}"
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == cid,
                    OperationTransaction.idempotency_key == operation_key,
                )
            )
            if existing is not None:
                return dict(existing.after_snapshot or {})
            character = self._character(
                session,
                cid,
                str(data.get("character_id") or ""),
                int(data.get("character_version") or 0),
            )
            equipment = session.get(EquipmentInstance, str(data.get("equipment_id") or ""))
            if equipment is None or equipment.character_id != character.id:
                raise StateNotFoundError("item adjudication equipment not found")
            clause = self._item_adjudication_clause(
                equipment, str(data.get("clause_id") or "")
            )
            context = data.get("context") or {}
            if not isinstance(context, dict):
                raise ValueError("item adjudication context must be an object")
            allowed = [
                "approved_targets",
                "approved_duration",
                "approved_damage",
                "approved_condition",
                "approved_object_profile",
                "approved_exception",
            ]
            window = RulesKernelAdjudicationWindow(
                campaign_id=cid,
                source_command_id=f"item:{key}",
                content_id=str((equipment.metadata_json or {}).get("item_spec", {}).get("item_id") or equipment.name),
                actor_id=character.id,
                requested_by=str(data.get("requested_by") or "player"),
                category="freeform_effect",
                source_text_evidence=str(
                    clause.get("evidence", {}).get("source_text")
                    or clause.get("evidence", {}).get("source_excerpt")
                ),
                typed_known_effects=[
                    item
                    for item in (equipment.metadata_json or {}).get("item_spec", {}).get("clauses", [])
                    if isinstance(item, dict) and item.get("clause_id") != clause.get("clause_id")
                ],
                open_questions=[str(item) for item in data.get("open_questions", ["target_or_effect_context"])],
                allowed_decision_schema=allowed,
                frozen_context={
                    "character_id": character.id,
                    "character_version": character.version,
                    "equipment_id": equipment.id,
                    "equipment_version": equipment.version,
                    "item_id": str((equipment.metadata_json or {}).get("item_spec", {}).get("item_id") or ""),
                    "clause_id": clause.get("clause_id"),
                    "context": context,
                },
                expected_versions={
                    "character_version": character.version,
                    "equipment_version": equipment.version,
                },
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            session.add(window)
            session.flush()
            out = {
                "schema_version": "item-dm-continuation-1",
                "adjudication_id": window.id,
                "status": window.status,
                "item_id": window.content_id,
                "equipment_id": equipment.id,
                "clause_id": clause["clause_id"],
                "typed_known_effects": window.typed_known_effects,
                "open_questions": window.open_questions,
                "allowed_decision_schema": window.allowed_decision_schema,
                "frozen_context": window.frozen_context,
                "expected_versions": window.expected_versions,
            }
            out["preview_token"] = _token({"data": data, "out": out})
            session.add(
                OperationTransaction(
                    campaign_id=cid,
                    operation_type="item_dm_adjudication",
                    idempotency_key=operation_key,
                    status="pending",
                    before_snapshot={
                        "character_id": character.id,
                        "character_version": character.version,
                        "equipment_id": equipment.id,
                        "equipment_version": equipment.version,
                        "charges": equipment.charges,
                    },
                    after_snapshot=out,
                    source="dm",
                )
            )
            return out

    def item_adjudication_confirm(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        """Resolve the DM window, apply a typed charge cost, and record CAS state."""

        if str(data.get("permission") or "") != "dm":
            raise ValueError("only DM may resolve item adjudication")
        key = str(data.get("idempotency_key") or "").strip()
        if len(key) < 8:
            raise ValueError("item adjudication idempotency_key is required")
        operation_key = f"item-dm:{key}"
        decision = dict(data.get("decision") or {})
        with Session(self.engine) as session, session.begin():
            operation = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == cid,
                    OperationTransaction.idempotency_key == operation_key,
                )
            )
            if operation is None:
                raise StateNotFoundError("item adjudication transaction not found")
            if operation.status == "applied":
                return {**dict(operation.after_snapshot or {}), "idempotent_replay": True}
            window = session.get(RulesKernelAdjudicationWindow, str(data.get("adjudication_id") or ""))
            if window is None or window.campaign_id != cid:
                raise StateNotFoundError("item adjudication window not found")
            expected_window_version = int(data.get("expected_window_version") or 0)
            if expected_window_version != window.version:
                raise VersionConflict("item adjudication", window.id, expected_window_version, window.version)
            status = str(decision.get("status") or "")
            if status not in {"approved", "modified", "rejected"}:
                raise ValueError("item adjudication decision status is invalid")
            permitted = set(str(item) for item in window.allowed_decision_schema)
            unexpected = set(decision) - permitted - {"status", "notes"}
            if unexpected:
                raise ValueError("item decision contains fields outside allowed_decision_schema")
            equipment = session.get(EquipmentInstance, str(operation.before_snapshot.get("equipment_id") or ""))
            character = session.get(Character, str(operation.before_snapshot.get("character_id") or ""))
            if equipment is None or character is None:
                raise StateNotFoundError("item adjudication state not found")
            if character.version != int(operation.before_snapshot.get("character_version") or 0):
                raise VersionConflict("character", character.id, int(operation.before_snapshot.get("character_version") or 0), character.version)
            if equipment.version != int(operation.before_snapshot.get("equipment_version") or 0):
                raise VersionConflict("equipment_instance", equipment.id, int(operation.before_snapshot.get("equipment_version") or 0), equipment.version)
            clause = self._item_adjudication_clause(equipment, str(window.frozen_context.get("clause_id") or ""))
            change = {"charges_before": equipment.charges, "charges_after": equipment.charges, "charge_cost": 0}
            if status != "rejected":
                cost = int((clause.get("parameters") or {}).get("charge_cost") or 0)
                if cost and (equipment.charges is None or equipment.charges < cost):
                    raise ValueError("item adjudication charge is unavailable")
                if cost:
                    equipment.charges = int(equipment.charges or 0) - cost
                    change = {"charges_before": change["charges_before"], "charges_after": equipment.charges, "charge_cost": cost}
                    equipment.version += 1
                character.version += 1
            window.status = status
            window.dm_decision = decision
            window.version += 1
            out = {
                **dict(operation.after_snapshot or {}),
                "status": status,
                "decision": decision,
                "change": change,
                "character_version_after": character.version,
                "equipment_version_after": equipment.version,
                "confirmed": True,
            }
            operation.status = "applied"
            operation.after_snapshot = out
            operation.confirmed_at = datetime.now(UTC)
            return out

    def item_adjudication_rollback(
        self, cid: str, adjudication_id: str, expected_character_version: int, expected_equipment_version: int
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            window = session.get(RulesKernelAdjudicationWindow, adjudication_id)
            if window is None or window.campaign_id != cid:
                raise StateNotFoundError("item adjudication window not found")
            key = f"item-dm:{str(window.source_command_id).removeprefix('item:')}"
            operation = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == cid,
                    OperationTransaction.idempotency_key == key,
                )
            )
            if operation is None:
                raise StateNotFoundError("item adjudication transaction not found")
            if operation.status == "reverted":
                return {"status": "already_reverted", "adjudication_id": adjudication_id}
            character = session.get(Character, str(operation.before_snapshot.get("character_id") or ""))
            equipment = session.get(EquipmentInstance, str(operation.before_snapshot.get("equipment_id") or ""))
            if character is None or equipment is None:
                raise StateNotFoundError("item rollback state not found")
            if character.version != expected_character_version or equipment.version != expected_equipment_version:
                raise VersionConflict("item rollback", adjudication_id, expected_character_version, character.version)
            equipment.charges = operation.before_snapshot.get("charges")
            equipment.version += 1
            character.version += 1
            operation.status = "reverted"
            operation.reverted_at = datetime.now(UTC)
            operation.after_snapshot = {
                **dict(operation.after_snapshot or {}),
                "rollback": {
                    "character_version_after": character.version,
                    "equipment_version_after": equipment.version,
                    "charges": equipment.charges,
                },
            }
            return {
                "status": "reverted",
                "adjudication_id": adjudication_id,
                "character_version_after": character.version,
                "equipment_version_after": equipment.version,
            }

    @staticmethod
    def _player_shop_scope(
        session: Session,
        cid: str,
        room_id: str,
        character_id: str,
        data: dict[str, Any],
    ) -> tuple[Wallet, ShopInventory]:
        room = session.get(PlayerRoom, room_id)
        if room is None or room.campaign_id != cid or room.status != "active":
            raise StateNotFoundError("player room not found or inactive")
        if room.current_scene_id is None:
            raise ValueError("当前 Scene 没有公开商店")
        wallet = session.get(Wallet, data["wallet_id"])
        item = session.get(ShopInventory, data["shop_inventory_id"])
        if wallet is None or item is None or wallet.campaign_id != cid or item.campaign_id != cid:
            raise StateNotFoundError("wallet or shop inventory not found")
        if wallet.character_id != character_id:
            raise ValueError("只能使用绑定角色的钱包")
        metadata = dict(item.metadata_json)
        merchant_npc_id = str(metadata.get("merchant_npc_id") or "")
        if (
            str(metadata.get("scene_id") or "") != room.current_scene_id
            or not metadata.get("merchant_id")
            or not merchant_npc_id
        ):
            raise ValueError("该商品不在当前公开 Scene 的商店中")
        visible = session.scalar(
            select(SceneParticipant).where(
                SceneParticipant.scene_id == room.current_scene_id,
                SceneParticipant.entity_type == "npc",
                SceneParticipant.entity_id == merchant_npc_id,
                SceneParticipant.visible.is_(True),
            )
        )
        if visible is None:
            raise ValueError("该商店当前未向玩家公开")
        return wallet, item

    def _commerce_preview_in_session(
        self,
        session: Session,
        cid: str,
        data: dict[str, Any],
        *,
        player_scope: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        if player_scope is not None:
            wallet, item = self._player_shop_scope(
                session, cid, player_scope[0], player_scope[1], data
            )
        else:
            raw_wallet = session.get(Wallet, data["wallet_id"])
            raw_item = session.get(ShopInventory, data["shop_inventory_id"])
            if raw_wallet is None or raw_item is None or raw_wallet.campaign_id != cid or raw_item.campaign_id != cid:
                raise StateNotFoundError("wallet or shop inventory not found")
            wallet, item = raw_wallet, raw_item
        if wallet.version != data["wallet_version"]:
            raise VersionConflict("wallet", wallet.id, data["wallet_version"], wallet.version)
        if item.version != data["shop_version"]:
            raise VersionConflict("shop inventory", item.id, data["shop_version"], item.version)
        total = item.price_copper * data["quantity"] * data["price_modifier_bps"] // 10_000
        if data["direction"] == "buy" and (
            item.quantity < data["quantity"] or wallet.copper < total
        ):
            raise ValueError("insufficient stock or copper")
        character = session.get(Character, wallet.character_id) if wallet.character_id else None
        raw_weight = item.metadata_json.get("unit_weight_lb", 0)
        raw_current_weight = item.metadata_json.get("current_weight_lb", 0)
        weight = (
            float(raw_weight) if isinstance(raw_weight, (int, float, str)) else 0.0
        ) * data["quantity"]
        current_weight = (
            float(raw_current_weight)
            if isinstance(raw_current_weight, (int, float, str))
            else 0.0
        )
        maximum_weight = None
        if character is not None:
            strength = int(
                character.ability_scores.get("力量", character.ability_scores.get("str", 10))
            )
            maximum_weight = strength * 15
            if data["direction"] == "buy" and current_weight + weight > maximum_weight:
                raise ValueError("purchase exceeds carrying capacity")
        out = {
            "wallet_id": wallet.id,
            "shop_inventory_id": item.id,
            "direction": data["direction"],
            "quantity": data["quantity"],
            "total_copper": total,
            "wallet_before": wallet.copper,
            "wallet_after": wallet.copper + (-total if data["direction"] == "buy" else total),
            "stock_before": item.quantity,
            "stock_after": item.quantity
            + (-data["quantity"] if data["direction"] == "buy" else data["quantity"]),
            "rule_reference": RULE,
            "weight_change_lb": weight if data["direction"] == "buy" else -weight,
            "maximum_weight_lb": maximum_weight,
        }
        out["preview_token"] = _token(
            {"data": data, "out": out, "wv": wallet.version, "sv": item.version}
        )
        return out

    def commerce_preview(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._commerce_preview_in_session(session, cid, data)

    def player_commerce_preview(
        self, cid: str, room_id: str, character_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._commerce_preview_in_session(
                session, cid, data, player_scope=(room_id, character_id)
            )

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
            preview = self._commerce_preview_in_session(s, cid, data)
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

    def player_commerce_confirm(
        self, cid: str, room_id: str, character_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        key = str(data.pop("idempotency_key"))
        token = str(data.pop("preview_token"))
        data["idempotency_key"] = None
        data["preview_token"] = None
        with Session(self.engine) as session, session.begin():
            old = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == cid,
                    OperationTransaction.idempotency_key == f"player-commerce:{key}",
                )
            )
            if old is not None:
                return dict(old.after_snapshot)
            preview = self._commerce_preview_in_session(
                session,
                cid,
                data,
                player_scope=(room_id, character_id),
            )
            if preview["preview_token"] != token:
                raise VersionConflict("commerce preview", "state", 1, 2)
            wallet = session.get(Wallet, data["wallet_id"])
            item = session.get(ShopInventory, data["shop_inventory_id"])
            assert wallet is not None and item is not None
            total, quantity = int(preview["total_copper"]), data["quantity"]
            wallet.copper -= total
            item.quantity -= quantity
            wallet.version += 1
            item.version += 1
            session.add(
                EquipmentInstance(
                    campaign_id=cid,
                    character_id=character_id,
                    name=item.name,
                    category=str(item.metadata_json.get("category", "gear")),
                    quantity=quantity,
                    metadata_json=dict(item.metadata_json),
                )
            )
            session.add(
                CurrencyTransaction(
                    campaign_id=cid,
                    wallet_id=wallet.id,
                    amount_copper=-total,
                    kind="purchase",
                    idempotency_key=f"player-commerce:{key}",
                    metadata_json={
                        "shop_inventory_id": item.id,
                        "quantity": quantity,
                        "price_copper": total,
                        "player_room_id": room_id,
                    },
                )
            )
            out = {**preview, "confirmed": True}
            session.add(
                OperationTransaction(
                    campaign_id=cid,
                    operation_type="commerce",
                    idempotency_key=f"player-commerce:{key}",
                    before_snapshot={
                        "wallet": preview["wallet_before"],
                        "stock": preview["stock_before"],
                    },
                    after_snapshot=out,
                    source="game_table",
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
