"""Closed production registry for reviewed Content IR consumers.

The registry is intentionally data-shaped.  Runtime dispatch selects a
consumer from the typed clause contract, never from a spell or feature name.
Unknown schemas, clause keys, and required fields fail closed before a real
character or combat row can be changed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PRODUCTION_REGISTRY_VERSION = "content-ir-production-registry-1"

_CONSUMERS: dict[str, dict[str, Any]] = {
    "combat_engine.damage_heal.v1": {
        "content_kind": "spell_or_feature",
        "runtime_schema_version": "spell-runtime-1|feature-runtime-1",
        "clause_types": ("damage", "healing", "temporary_hp", "attack_rider"),
        "required_fields": ("target_combatant_id", "target_version", "resolution_total"),
        "required_services": ("combat_engine",),
        "transaction_boundary": "combat_action_and_operation_transaction",
        "cas_entities": ("actor_combatant", "target_combatant"),
        "idempotency_scope": "campaign_content_ir_and_combat_action",
        "snapshot_effects": ("hp", "temporary_hp", "combatant_version", "audit"),
    },
    "combat_engine.area_damage.v1": {
        "content_kind": "spell",
        "runtime_schema_version": "spell-runtime-1",
        "clause_types": ("area", "damage", "saving_throw"),
        "required_fields": ("area_shape", "area_size_ft", "area_anchor_row", "area_anchor_col"),
        "required_services": ("combat_engine.area_geometry", "combat_engine.batch"),
        "transaction_boundary": "preflight_then_combat_action_batch",
        "cas_entities": ("actor_combatant", "target_combatants"),
        "idempotency_scope": "campaign_content_ir_and_each_combat_action",
        "snapshot_effects": ("hp", "temporary_hp", "conditions", "combatant_versions", "audit"),
    },
    "combat_engine.condition_lifecycle.v1": {
        "content_kind": "spell_or_feature",
        "runtime_schema_version": "spell-runtime-1|feature-runtime-1",
        "clause_types": ("apply_condition", "condition_removal"),
        "required_fields": ("target_combatant_id", "target_version", "condition"),
        "required_services": ("combat_engine.effect_lifecycle",),
        "transaction_boundary": "combat_action_and_effect_transaction",
        "cas_entities": ("actor_combatant", "target_combatant"),
        "idempotency_scope": "campaign_content_ir_and_combat_action",
        "snapshot_effects": ("conditions", "combat_effect", "expiry", "concentration", "audit"),
    },
    "spell_economy.concentration.v1": {
        "content_kind": "spell",
        "runtime_schema_version": "spell-runtime-1",
        "clause_types": ("concentration",),
        "required_fields": ("character_id", "character_version", "known_spell_id", "slot_level"),
        "required_services": ("spell_economy", "combat_engine.effect_lifecycle"),
        "transaction_boundary": "spell_cast_with_rollback_boundary",
        "cas_entities": ("character", "actor_combatant"),
        "idempotency_scope": "campaign_content_ir_and_spell_cast",
        "snapshot_effects": ("spell_slots", "concentration", "combat_effect", "audit"),
    },
    "combat_engine.feature_action.v1": {
        "content_kind": "feature",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("feature_action", "timed_modifier", "passive_registry"),
        "required_fields": ("actor_combatant_id", "actor_version", "runtime_id"),
        "required_services": ("combat_engine.feature_action",),
        "transaction_boundary": "feature_action_and_operation_transaction",
        "cas_entities": ("actor_combatant", "target_combatant", "character_resource"),
        "idempotency_scope": "campaign_content_ir_and_combat_action",
        "snapshot_effects": ("feature_state", "resources", "timed_modifiers", "audit"),
    },
}

_ALLOWED_SPELL_BLOCKS = {
    "attack_roll",
    "concentration",
    "duration",
    "effects",
    "healing",
    "saving_throw",
    "target_selection",
    "temporary_hp",
    "upcast",
    "area",
}


def production_consumer_descriptors() -> dict[str, dict[str, Any]]:
    """Return a stable copy for audit/report generation."""

    return {key: dict(value) for key, value in sorted(_CONSUMERS.items())}


def _parameters(block: Mapping[str, Any]) -> dict[str, Any]:
    raw = block.get("parameters")
    return dict(raw) if isinstance(raw, Mapping) else dict(block)


def _has_effect(blocks: Mapping[str, list[dict[str, Any]]], *types: str) -> bool:
    wanted = set(types)
    for block in blocks.get("effects", []):
        parameters = _parameters(block)
        if str(parameters.get("type") or "") in wanted:
            return True
    return any(blocks.get(item) for item in wanted if item in blocks)


def resolve_production_consumers(
    *,
    content_kind: str,
    runtime_schema_version: str,
    blocks: Mapping[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], ...]:
    """Resolve the closed set of consumers for one runtime definition.

    This function deliberately rejects an unknown resolution section instead
    of silently treating it as narrative content.  It also requires at least
    one executable clause, so compile/preview success cannot be promoted by
    metadata alone.
    """

    if content_kind == "spell":
        if runtime_schema_version != "spell-runtime-1":
            raise ValueError("unsupported Content IR spell runtime schema")
        unknown = set(blocks) - _ALLOWED_SPELL_BLOCKS
        if unknown:
            raise ValueError("unknown spell runtime sections: " + ",".join(sorted(unknown)))
        resolved: list[str] = []
        if _has_effect(blocks, "damage", "healing", "temporary_hp"):
            resolved.append("combat_engine.damage_heal.v1")
        if blocks.get("area"):
            if not _has_effect(blocks, "damage"):
                raise ValueError("area runtime requires a typed damage effect")
            resolved.append("combat_engine.area_damage.v1")
        if blocks.get("saving_throw") and _has_effect(blocks, "damage"):
            resolved.append("combat_engine.damage_heal.v1")
        if blocks.get("concentration"):
            resolved.append("spell_economy.concentration.v1")
        if blocks.get("apply_condition"):
            resolved.append("combat_engine.condition_lifecycle.v1")
        if not resolved:
            raise ValueError("spell runtime has no registered executable consumer")
        return tuple(dict(_CONSUMERS[item], consumer_id=item) for item in sorted(set(resolved)))

    if content_kind == "feature":
        if runtime_schema_version not in {"feature-runtime-1", ""}:
            raise ValueError("unsupported Content IR feature runtime schema")
        if blocks.get("attack_rider") or blocks.get("feature_action"):
            key = (
                "combat_engine.damage_heal.v1"
                if blocks.get("attack_rider")
                else "combat_engine.feature_action.v1"
            )
            return (dict(_CONSUMERS[key], consumer_id=key),)
        if blocks.get("condition_removal"):
            return (
                dict(
                    _CONSUMERS["combat_engine.condition_lifecycle.v1"],
                    consumer_id="combat_engine.condition_lifecycle.v1",
                ),
            )
        if blocks.get("timed_modifier") or blocks.get("passive_registry"):
            return (
                dict(
                    _CONSUMERS["combat_engine.feature_action.v1"],
                    consumer_id="combat_engine.feature_action.v1",
                ),
            )
        raise ValueError("feature runtime has no registered executable consumer")

    raise ValueError("content_kind must be spell or feature")
