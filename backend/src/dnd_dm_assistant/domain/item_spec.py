# ruff: noqa: E501
"""Closed-world ItemSpec IR and deterministic item consumer planning.

Items use the existing ``EquipmentInstance`` and ``Attunement`` persistence;
this module only supplies the typed authority that was missing from the first
Tasha inventory pass.  It never dispatches by an item name.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

ITEM_IR_SCHEMA_VERSION = "item-ir-1"
ITEM_SOURCE_TRUSTS = frozenset({"authored_ir", "verified_mapping", "generated_draft"})
ITEM_KINDS = frozenset(
    {
        "weapon",
        "armor",
        "wondrous_item",
        "spellcasting_focus",
        "consumable",
        "magic_tattoo",
        "tool",
        "accessory",
        "other_typed_item",
    }
)
ITEM_CLAUSE_TYPES = frozenset(
    {
        "equipment",
        "attunement",
        "passive_modifier",
        "charge",
        "charge_recovery",
        "granted_action",
        "granted_spell",
        "consumable",
        "triggered_effect",
        "damage",
        "healing",
        "temporary_hp",
        "condition",
        "resistance",
        "immunity",
        "tattoo_lifecycle",
        "resource_binding",
        "dm_choice",
    })
_RECOVERY_TRIGGERS = frozenset({"long_rest", "dawn", "short_rest", "manual", "none"})


class ItemIRValidationError(ValueError):
    """Raised when an ItemSpec violates the closed item contract."""


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ItemIRValidationError(f"{path} must be an object")
    return {str(key): value[key] for key in value}


def _required(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ItemIRValidationError(f"{path} must be a non-empty string")
    return value.strip()


def _optional(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _required(value, path)


def _strict(data: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ItemIRValidationError(f"{path} contains unknown fields: {', '.join(unknown)}")


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ItemSpec:
    schema_version: str
    item_id: str
    pack_id: str
    pack_version: str
    namespace: str
    ruleset_version: str
    name: str
    localized_name: str
    source_record_id: str
    source_path: str
    source_fragment: str
    source_fingerprint: str
    source_trust: str
    item_kind: str
    rarity: str | None
    requires_attunement: bool
    attunement_requirements: dict[str, Any]
    equipped_slot: str | None
    stack_policy: dict[str, Any]
    consumption_policy: dict[str, Any]
    charges: dict[str, Any]
    passive_modifiers: tuple[dict[str, Any], ...]
    granted_actions: tuple[dict[str, Any], ...]
    granted_spells: tuple[dict[str, Any], ...]
    triggered_effects: tuple[dict[str, Any], ...]
    damage: dict[str, Any] | None
    healing: dict[str, Any] | None
    temporary_hp: dict[str, Any] | None
    conditions: tuple[dict[str, Any], ...]
    resistances: tuple[dict[str, Any], ...]
    immunities: tuple[dict[str, Any], ...]
    resource_bindings: tuple[dict[str, Any], ...]
    duration: dict[str, Any] | None
    clauses: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version", "item_id", "pack_id", "pack_version", "namespace",
            "ruleset_version", "name", "localized_name", "source_record_id",
            "source_path", "source_fragment", "source_fingerprint", "source_trust",
            "item_kind", "rarity", "requires_attunement", "attunement_requirements",
            "equipped_slot", "stack_policy", "consumption_policy", "charges",
            "passive_modifiers", "granted_actions", "granted_spells", "triggered_effects",
            "damage", "healing", "temporary_hp", "conditions", "resistances", "immunities",
            "resource_bindings", "duration", "clauses", "evidence",
        }
    )
    _CLAUSE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"clause_id", "clause_type", "trigger", "action_economy", "parameters", "evidence"}
    )

    @classmethod
    def from_dict(cls, value: object, path: str = "item") -> ItemSpec:
        data = _mapping(value, path)
        _strict(data, cls._FIELDS, path)
        schema = _required(data.get("schema_version"), f"{path}.schema_version")
        if schema != ITEM_IR_SCHEMA_VERSION:
            raise ItemIRValidationError(f"{path}.schema_version {schema!r} is unsupported")
        item_kind = _required(data.get("item_kind"), f"{path}.item_kind")
        if item_kind not in ITEM_KINDS:
            raise ItemIRValidationError(f"{path}.item_kind {item_kind!r} is unsupported")
        source_trust = _required(data.get("source_trust"), f"{path}.source_trust")
        if source_trust not in ITEM_SOURCE_TRUSTS:
            raise ItemIRValidationError(f"{path}.source_trust {source_trust!r} is unsupported")
        raw_clauses = data.get("clauses")
        if not isinstance(raw_clauses, list) or not raw_clauses:
            raise ItemIRValidationError(f"{path}.clauses must contain at least one clause")
        clauses: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_clauses):
            clause = _mapping(raw, f"{path}.clauses[{index}]")
            _strict(clause, cls._CLAUSE_FIELDS, f"{path}.clauses[{index}]")
            clause_id = _required(clause.get("clause_id"), f"{path}.clauses[{index}].clause_id")
            if clause_id in seen:
                raise ItemIRValidationError(f"{path}.clauses contains duplicate clause_id {clause_id}")
            seen.add(clause_id)
            clause_type = _required(clause.get("clause_type"), f"{path}.clauses[{index}].clause_type")
            if clause_type not in ITEM_CLAUSE_TYPES:
                raise ItemIRValidationError(f"{path}.clauses[{index}].clause_type {clause_type!r} is unsupported")
            parameters = _mapping(clause.get("parameters", {}), f"{path}.clauses[{index}].parameters")
            clauses.append(
                {
                    "clause_id": clause_id,
                    "clause_type": clause_type,
                    "trigger": str(clause.get("trigger") or "always"),
                    "action_economy": str(clause.get("action_economy") or "none"),
                    "parameters": parameters,
                    "evidence": _mapping(clause.get("evidence", {}), f"{path}.clauses[{index}].evidence"),
                }
            )
        charges = _mapping(data.get("charges", {}), f"{path}.charges")
        if charges:
            maximum = charges.get("maximum")
            if maximum is not None and (not isinstance(maximum, int) or maximum < 0):
                raise ItemIRValidationError(f"{path}.charges.maximum must be a non-negative integer")
            recovery = charges.get("recovery_trigger")
            if recovery is not None and recovery not in _RECOVERY_TRIGGERS:
                raise ItemIRValidationError(f"{path}.charges.recovery_trigger is unsupported")
        if not isinstance(data.get("requires_attunement"), bool):
            raise ItemIRValidationError(f"{path}.requires_attunement must be boolean")
        return cls(
            schema_version=schema,
            item_id=_required(data.get("item_id"), f"{path}.item_id"),
            pack_id=_required(data.get("pack_id"), f"{path}.pack_id"),
            pack_version=_required(data.get("pack_version"), f"{path}.pack_version"),
            namespace=_required(data.get("namespace"), f"{path}.namespace"),
            ruleset_version=_required(data.get("ruleset_version"), f"{path}.ruleset_version"),
            name=_required(data.get("name"), f"{path}.name"),
            localized_name=_required(data.get("localized_name"), f"{path}.localized_name"),
            source_record_id=_required(data.get("source_record_id"), f"{path}.source_record_id"),
            source_path=_required(data.get("source_path"), f"{path}.source_path"),
            source_fragment=_required(data.get("source_fragment"), f"{path}.source_fragment"),
            source_fingerprint=_required(data.get("source_fingerprint"), f"{path}.source_fingerprint"),
            source_trust=source_trust,
            item_kind=item_kind,
            rarity=_optional(data.get("rarity"), f"{path}.rarity"),
            requires_attunement=bool(data["requires_attunement"]),
            attunement_requirements=_mapping(data.get("attunement_requirements", {}), f"{path}.attunement_requirements"),
            equipped_slot=_optional(data.get("equipped_slot"), f"{path}.equipped_slot"),
            stack_policy=_mapping(data.get("stack_policy", {}), f"{path}.stack_policy"),
            consumption_policy=_mapping(data.get("consumption_policy", {}), f"{path}.consumption_policy"),
            charges=charges,
            passive_modifiers=tuple(_mapping(item, f"{path}.passive_modifiers[{i}]") for i, item in enumerate(data.get("passive_modifiers", []))),
            granted_actions=tuple(_mapping(item, f"{path}.granted_actions[{i}]") for i, item in enumerate(data.get("granted_actions", []))),
            granted_spells=tuple(_mapping(item, f"{path}.granted_spells[{i}]") for i, item in enumerate(data.get("granted_spells", []))),
            triggered_effects=tuple(_mapping(item, f"{path}.triggered_effects[{i}]") for i, item in enumerate(data.get("triggered_effects", []))),
            damage=_mapping(data["damage"], f"{path}.damage") if data.get("damage") is not None else None,
            healing=_mapping(data["healing"], f"{path}.healing") if data.get("healing") is not None else None,
            temporary_hp=_mapping(data["temporary_hp"], f"{path}.temporary_hp") if data.get("temporary_hp") is not None else None,
            conditions=tuple(_mapping(item, f"{path}.conditions[{i}]") for i, item in enumerate(data.get("conditions", []))),
            resistances=tuple(_mapping(item, f"{path}.resistances[{i}]") for i, item in enumerate(data.get("resistances", []))),
            immunities=tuple(_mapping(item, f"{path}.immunities[{i}]") for i, item in enumerate(data.get("immunities", []))),
            resource_bindings=tuple(_mapping(item, f"{path}.resource_bindings[{i}]") for i, item in enumerate(data.get("resource_bindings", []))),
            duration=_mapping(data["duration"], f"{path}.duration") if data.get("duration") is not None else None,
            clauses=tuple(clauses),
            evidence=_mapping(data.get("evidence", {}), f"{path}.evidence"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "item_id": self.item_id,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "namespace": self.namespace,
            "ruleset_version": self.ruleset_version,
            "name": self.name,
            "localized_name": self.localized_name,
            "source_record_id": self.source_record_id,
            "source_path": self.source_path,
            "source_fragment": self.source_fragment,
            "source_fingerprint": self.source_fingerprint,
            "source_trust": self.source_trust,
            "item_kind": self.item_kind,
            "rarity": self.rarity,
            "requires_attunement": self.requires_attunement,
            "attunement_requirements": self.attunement_requirements,
            "equipped_slot": self.equipped_slot,
            "stack_policy": self.stack_policy,
            "consumption_policy": self.consumption_policy,
            "charges": self.charges,
            "passive_modifiers": list(self.passive_modifiers),
            "granted_actions": list(self.granted_actions),
            "granted_spells": list(self.granted_spells),
            "triggered_effects": list(self.triggered_effects),
            "damage": self.damage,
            "healing": self.healing,
            "temporary_hp": self.temporary_hp,
            "conditions": list(self.conditions),
            "resistances": list(self.resistances),
            "immunities": list(self.immunities),
            "resource_bindings": list(self.resource_bindings),
            "duration": self.duration,
            "clauses": list(self.clauses),
            "evidence": self.evidence,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


def compile_item_spec(spec: ItemSpec) -> dict[str, Any]:
    """Compile ItemSpec into consumer-shaped data without name dispatch."""

    blockers: list[str] = []
    if spec.source_trust == "generated_draft":
        blockers.append("generated_draft_requires_review")
    clause_types = {str(item["clause_type"]) for item in spec.clauses}
    if any(
        bool(item.get("parameters", {}).get("manual_review_required"))
        or bool(item.get("evidence", {}).get("manual_review_required"))
        for item in spec.clauses
    ):
        blockers.append("manual_clause_requires_dm_or_additional_typed_fields")
    if spec.requires_attunement and "attunement" not in clause_types:
        blockers.append("attunement_clause_missing")
    if spec.charges and "charge" not in clause_types:
        blockers.append("charge_clause_missing")
    try:
        from dnd_dm_assistant.application.content_ir_production_registry import (
            resolve_production_consumers,
        )

        consumers = resolve_production_consumers(
            content_kind="item",
            runtime_schema_version=ITEM_IR_SCHEMA_VERSION,
            blocks={"clauses": list(spec.clauses)},
        )
    except ValueError as exc:
        consumers = ()
        blockers.append(str(exc))
    status = "full" if not blockers and consumers else "partial"
    if not consumers:
        blockers.append("no_item_consumer")
    return {
        "schema_version": ITEM_IR_SCHEMA_VERSION,
        "item_id": spec.item_id,
        "item_fingerprint": spec.fingerprint(),
        "compile_status": status,
        "runtime_preview_full": status == "full",
        "consumer_ids": [str(item["consumer_id"]) for item in consumers],
        "clauses": list(spec.clauses),
        "blockers": sorted(set(blockers)),
        "source_trust": spec.source_trust,
    }


def item_runtime_projection(spec: ItemSpec) -> dict[str, Any]:
    """Return the small data projection stored on an EquipmentInstance."""

    compiled = compile_item_spec(spec)
    return {
        "runtime_schema_version": ITEM_IR_SCHEMA_VERSION,
        "item_id": spec.item_id,
        "item_fingerprint": spec.fingerprint(),
        "item_kind": spec.item_kind,
        "requires_attunement": spec.requires_attunement,
        "attunement_requirements": spec.attunement_requirements,
        "equipped_slot": spec.equipped_slot,
        "charges": spec.charges,
        "passive_modifiers": list(spec.passive_modifiers),
        "granted_actions": list(spec.granted_actions),
        "granted_spells": list(spec.granted_spells),
        "triggered_effects": list(spec.triggered_effects),
        "resistances": list(spec.resistances),
        "immunities": list(spec.immunities),
        "clauses": list(spec.clauses),
        "consumer_ids": compiled["consumer_ids"],
        "compile_status": compiled["compile_status"],
    }


def materialize_item_effects(
    equipment: list[Mapping[str, Any]],
    active_attunement_ids: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Project active typed item clauses for character/snapshot consumers."""

    passive: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    spells: list[dict[str, Any]] = []
    resistances: list[dict[str, Any]] = []
    immunities: list[dict[str, Any]] = []
    active_items: list[str] = []
    for row in equipment:
        item_id = str(row.get("id") or row.get("equipment_id") or "")
        raw_spec = row.get("item_spec")
        if not isinstance(raw_spec, Mapping):
            continue
        spec = dict(raw_spec)
        requires_attunement = bool(spec.get("requires_attunement"))
        active = bool(row.get("equipped")) or item_id in active_attunement_ids
        if requires_attunement and item_id not in active_attunement_ids:
            active = False
        if not active:
            continue
        active_items.append(item_id)
        passive.extend(dict(item, source_item_id=item_id) for item in spec.get("passive_modifiers", []) if isinstance(item, Mapping))
        actions.extend(dict(item, source_item_id=item_id) for item in spec.get("granted_actions", []) if isinstance(item, Mapping))
        spells.extend(dict(item, source_item_id=item_id) for item in spec.get("granted_spells", []) if isinstance(item, Mapping))
        resistances.extend(dict(item, source_item_id=item_id) for item in spec.get("resistances", []) if isinstance(item, Mapping))
        immunities.extend(dict(item, source_item_id=item_id) for item in spec.get("immunities", []) if isinstance(item, Mapping))
    return {
        "active_item_ids": sorted(active_items),
        "passive_modifiers": passive,
        "granted_actions": actions,
        "granted_spells": spells,
        "resistances": resistances,
        "immunities": immunities,
    }
