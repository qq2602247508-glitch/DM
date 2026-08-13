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
    "spell.remote_origin.v1": {
        "content_kind": "spell",
        "runtime_schema_version": "spell-runtime-1",
        "clause_types": ("spell_origins", "target_selection"),
        "required_fields": (
            "origin_id",
            "target_combatant_id",
            "target_version",
            "actor_combatant_id",
            "actor_version",
        ),
        "required_services": ("content_ir_runtime.remote_spell_origin", "combat_engine.geometry"),
        "transaction_boundary": "spell_cast_with_origin_resolution_and_rollback_boundary",
        "cas_entities": ("character", "actor_combatant", "target_combatants"),
        "idempotency_scope": "campaign_content_ir_and_spell_cast",
        "snapshot_effects": ("origin_id", "distances_ft", "line_of_effect", "audit"),
    },
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
    "spell.cantrip_scaling.v1": {
        "content_kind": "spell",
        "runtime_schema_version": "spell-runtime-1",
        "clause_types": ("upcast", "damage"),
        "required_fields": ("caster_level", "resolution_total"),
        "required_services": ("content_ir_runtime.spell_scaling",),
        "transaction_boundary": "spell_cast_with_combat_rollback_boundary",
        "cas_entities": ("character", "actor_combatant", "target_combatants"),
        "idempotency_scope": "campaign_content_ir_and_spell_cast",
        "snapshot_effects": ("hp", "combatant_versions", "audit"),
    },
    "spell.timed_modifier.v1": {
        "content_kind": "spell",
        "runtime_schema_version": "spell-runtime-1",
        "clause_types": ("timed_modifier", "target_selection", "duration"),
        "required_fields": (
            "target_combatant_ids",
            "target_versions",
            "actor_combatant_id",
            "actor_version",
        ),
        "required_services": ("combat_engine.timed_spell_modifier",),
        "transaction_boundary": "spell_cast_with_timed_modifier_snapshot_and_rollback_boundary",
        "cas_entities": ("character", "actor_combatants", "target_combatants"),
        "idempotency_scope": "campaign_content_ir_and_spell_cast",
        "snapshot_effects": ("timed_spell_modifiers", "expiry", "audit"),
    },
    "spell.communication.route.v1": {
        "content_kind": "spell",
        "runtime_schema_version": "spell-runtime-1",
        "clause_types": ("communication_route", "target_selection"),
        "required_fields": (
            "target_combatant_id",
            "target_version",
            "actor_combatant_id",
            "actor_version",
        ),
        "required_services": ("combat_engine.communication_route",),
        "transaction_boundary": (
            "spell_cast_with_communication_route_snapshot_and_rollback_boundary"
        ),
        "cas_entities": ("actor_combatant", "target_combatant"),
        "idempotency_scope": "campaign_content_ir_and_spell_cast",
        "snapshot_effects": ("communication_routes", "private_reply", "audit"),
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
    "spell.defense.v1": {
        "content_kind": "spell",
        "runtime_schema_version": "spell-runtime-1",
        "clause_types": ("spell_modifier", "target_selection"),
        "required_fields": (
            "target_combatant_ids",
            "target_versions",
            "actor_combatant_id",
            "actor_version",
        ),
        "required_services": ("combat_engine.effect_lifecycle", "combat_engine.geometry"),
        "transaction_boundary": "spell_cast_with_grouped_effect_and_rollback_boundary",
        "cas_entities": ("character", "actor_combatant", "target_combatants"),
        "idempotency_scope": "campaign_content_ir_and_spell_cast",
        "snapshot_effects": (
            "damage_resistances",
            "saving_throw_modifiers",
            "combat_effect",
            "concentration",
            "audit",
        ),
    },
    "spell.summon.v1": {
        "content_kind": "spell",
        "runtime_schema_version": "spell-runtime-1",
        "clause_types": ("summon_or_creation", "target_selection"),
        "required_fields": (
            "character_id",
            "character_version",
            "known_spell_id",
            "slot_level",
            "combat_id",
            "actor_combatant_id",
            "actor_version",
            "summon_choice",
            "destination_row",
            "destination_col",
        ),
        "required_services": ("spell_economy", "combat_engine.summon_lifecycle"),
        "transaction_boundary": "spell_cast_with_summon_lifecycle_and_rollback_boundary",
        "cas_entities": ("character", "actor_combatant", "summon_combatants"),
        "idempotency_scope": "campaign_content_ir_and_spell_cast",
        "snapshot_effects": (
            "spell_slots",
            "action_economy",
            "summon_stat_block",
            "summon_initiative",
            "summon_lifecycle",
            "summon_default_behavior",
            "concentration",
            "audit",
        ),
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
    "entity.senses.v1": {
        "content_kind": "feature_or_advancement",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("entity_senses", "inspection"),
        "required_fields": (
            "entity_id",
            "actor_combatant_id",
            "actor_version",
            "target_combatant_id",
            "target_version",
        ),
        "required_services": (
            "content_ir_runtime.entity_senses",
            "combat_engine.geometry",
        ),
        "transaction_boundary": "entity_senses_preview_confirm_operation_transaction",
        "cas_entities": ("character", "actor_combatant", "target_combatant"),
        "idempotency_scope": "campaign_content_ir_and_entity_senses",
        "snapshot_effects": ("senses_receipt", "distance_ft", "line_of_sight", "audit"),
    },
    "telepathic.information.v1": {
        "content_kind": "feature",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("telepathic_information",),
        "required_fields": (
            "entity_id",
            "actor_combatant_id",
            "actor_version",
            "target_combatant_id",
            "target_version",
        ),
        "required_services": (
            "content_ir_runtime.telepathic_information",
            "content_ir_runtime.entity_senses",
            "combat_engine.geometry",
        ),
        "transaction_boundary": "telepathic_information_preview_confirm_operation_transaction",
        "cas_entities": ("character", "actor_combatant", "target_combatant"),
        "idempotency_scope": "campaign_content_ir_and_telepathic_information",
        "snapshot_effects": ("telepathic_receipt", "channels", "action_economy", "audit"),
    },
    "entity.spatial.v1": {
        "content_kind": "feature",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("entity_spatial",),
        "required_fields": (
            "entity_id",
            "actor_combatant_id",
            "actor_version",
            "destination_row",
            "destination_col",
        ),
        "required_services": (
            "content_ir_runtime.entity_spatial",
            "combat_engine.action_economy",
            "combat_engine.geometry",
        ),
        "transaction_boundary": "entity_spatial_preview_confirm_operation_transaction",
        "cas_entities": ("actor_combatant", "entity_spatial"),
        "idempotency_scope": "campaign_content_ir_and_entity_spatial",
        "snapshot_effects": ("entity_spatial_receipt", "position", "action_economy", "audit"),
    },
    "spell.slot.reactivation.v1": {
        "content_kind": "advancement",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("spell_slot_reactivations",),
        "required_fields": (
            "character_id",
            "character_version",
            "entity_id",
            "entity_lifecycle_event",
            "operation_id",
        ),
        "required_services": (
            "content_ir_runtime.spell_slot_reactivation",
            "rest_service",
            "operation_transaction",
        ),
        "transaction_boundary": "character_resource_lifecycle_and_operation_transaction",
        "cas_entities": ("character", "entity_lifecycle", "spell_slot_resource"),
        "idempotency_scope": "campaign_content_ir_and_reactivation",
        "snapshot_effects": ("entity_state", "spell_slots", "resource_receipt", "audit"),
    },
    "vessel.space.v1": {
        "content_kind": "advancement",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("vessel_spaces",),
        "required_fields": (
            "character_id",
            "character_version",
            "entity_lifecycle_event",
            "operation_id",
        ),
        "required_services": (
            "content_ir_runtime.vessel_space",
            "operation_transaction",
        ),
        "transaction_boundary": "character_vessel_lifecycle_and_operation_transaction",
        "cas_entities": ("character", "vessel_space", "contained_items"),
        "idempotency_scope": "campaign_content_ir_and_vessel_space",
        "snapshot_effects": (
            "vessel_state",
            "occupants",
            "item_relocation",
            "action_economy",
            "audit",
        ),
    },
    "vessel.external_sound.v1": {
        "content_kind": "advancement",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("vessel_external_sound",),
        "required_fields": (
            "character_id",
            "character_version",
            "event_id",
            "scene_id",
            "combat_id",
        ),
        "required_services": (
            "content_ir_runtime.vessel_external_sound",
            "operation_transaction",
        ),
        "transaction_boundary": "read_only_vessel_external_sound_event_receipt",
        "cas_entities": ("character", "vessel_space", "event"),
        "idempotency_scope": "campaign_content_ir_and_vessel_external_sound",
        "snapshot_effects": ("external_sound_receipt", "audit"),
    },
    "combat_engine.roll_intervention.v1": {
        "content_kind": "feature",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("roll_intervention",),
        "required_fields": (
            "actor_combatant_id",
            "actor_version",
            "runtime_id",
            "roll_total",
        ),
        "required_services": ("combat_service.roll_intervention",),
        "transaction_boundary": "combat_action_and_operation_transaction",
        "cas_entities": ("actor_combatant", "character_resource"),
        "idempotency_scope": "campaign_content_ir_and_roll_intervention",
        "snapshot_effects": ("initiative", "roll_result", "resources", "audit"),
    },
    "communication.mutual_comprehension.v1": {
        "content_kind": "feature",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("communication",),
        "required_fields": ("actor_combatant_id", "actor_version", "runtime_id"),
        "required_services": ("communication_service",),
        "transaction_boundary": "communication_readonly_and_operation_transaction",
        "cas_entities": ("actor_combatant", "target_combatant"),
        "idempotency_scope": "campaign_content_ir_and_communication",
        "snapshot_effects": ("communication", "audit"),
    },
    "combat_engine.feature_event_window.v1": {
        "content_kind": "feature",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("feature_event_window", "resource_exchange"),
        "required_fields": ("actor_combatant_id", "actor_version", "runtime_id"),
        "required_services": ("combat_engine.feature_event_window",),
        "transaction_boundary": "feature_event_window_and_operation_transaction",
        "cas_entities": ("actor_combatant", "target_combatant", "character_resource"),
        "idempotency_scope": "campaign_content_ir_and_feature_window",
        "snapshot_effects": ("feature_window", "resources", "combat_action", "audit"),
    },
    "spell.context.v1": {
        "content_kind": "feature",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": ("spell_context",),
        "required_fields": ("actor_combatant_id", "actor_version", "runtime_id"),
        "required_services": ("spell_economy", "combat_engine.feature_runtime"),
        "transaction_boundary": "spell_cast_with_context_and_rollback_boundary",
        "cas_entities": ("character", "actor_combatant", "spell_resource"),
        "idempotency_scope": "campaign_content_ir_and_spell_cast",
        "snapshot_effects": ("spell_context", "resources", "spell_slots", "audit"),
    },
    "advancement_service.character_growth.v1": {
        "content_kind": "advancement",
        "runtime_schema_version": "feature-runtime-1",
        "clause_types": (
            "advancement",
            "proficiencies",
            "prepared_spell_list",
            "spell_list_expansions",
        ),
        "required_fields": ("character_id", "character_version", "runtime_id"),
        "required_services": ("advancement_service",),
        "transaction_boundary": "character_snapshot_and_operation_transaction",
        "cas_entities": ("character",),
        "idempotency_scope": "campaign_content_ir_and_character_growth",
        "snapshot_effects": ("features", "proficiencies", "skills", "spells", "audit"),
    },
    "item.equipment_modifier.v1": {
        "content_kind": "item",
        "runtime_schema_version": "item-ir-1",
        "clause_types": ("equipment", "passive_modifier", "resistance", "immunity"),
        "required_fields": ("item_id", "character_id", "character_version"),
        "required_services": ("equipment_instance", "character_snapshot"),
        "transaction_boundary": "equipment_operation_and_character_snapshot",
        "cas_entities": ("character", "equipment_instance"),
        "idempotency_scope": "campaign_item_and_equipment_operation",
        "snapshot_effects": ("equipment", "armor_class", "passive_modifiers", "audit"),
    },
    "item.attunement.v1": {
        "content_kind": "item",
        "runtime_schema_version": "item-ir-1",
        "clause_types": ("attunement", "tattoo_lifecycle"),
        "required_fields": ("item_id", "character_id", "character_version"),
        "required_services": ("attunement", "character_snapshot"),
        "transaction_boundary": "attunement_operation_and_character_snapshot",
        "cas_entities": ("character", "attunement"),
        "idempotency_scope": "campaign_item_and_attunement_operation",
        "snapshot_effects": ("attunement", "item_effects", "audit"),
    },
    "item.charge_resource.v1": {
        "content_kind": "item",
        "runtime_schema_version": "item-ir-1",
        "clause_types": ("charge", "charge_recovery", "resource_binding"),
        "required_fields": ("item_id", "character_id", "character_version", "amount"),
        "required_services": ("equipment_instance", "operation_transaction"),
        "transaction_boundary": "charge_operation_and_equipment_instance",
        "cas_entities": ("character", "equipment_instance"),
        "idempotency_scope": "campaign_item_and_charge_operation",
        "snapshot_effects": ("charges", "resource_pool", "audit"),
    },
    "item.granted_action.v1": {
        "content_kind": "item",
        "runtime_schema_version": "item-ir-1",
        "clause_types": ("granted_action", "triggered_effect", "damage", "healing", "temporary_hp"),
        "required_fields": ("item_id", "character_id", "character_version", "action_id"),
        "required_services": ("rules_kernel", "operation_transaction"),
        "transaction_boundary": "item_action_and_operation_transaction",
        "cas_entities": ("character", "equipment_instance", "target"),
        "idempotency_scope": "campaign_item_action",
        "snapshot_effects": ("resources", "equipment_instance", "target_effects", "audit"),
    },
    "item.granted_spell.v1": {
        "content_kind": "item",
        "runtime_schema_version": "item-ir-1",
        "clause_types": ("granted_spell",),
        "required_fields": ("item_id", "character_id", "character_version", "spell_id"),
        "required_services": ("spell_economy", "known_spell"),
        "transaction_boundary": "item_spell_grant_and_operation_transaction",
        "cas_entities": ("character", "equipment_instance", "known_spell"),
        "idempotency_scope": "campaign_item_spell_grant",
        "snapshot_effects": ("known_spell", "prepared_spell", "audit"),
    },
    "item.consumable.v1": {
        "content_kind": "item",
        "runtime_schema_version": "item-ir-1",
        "clause_types": ("consumable",),
        "required_fields": ("item_id", "character_id", "character_version", "amount"),
        "required_services": ("equipment_instance", "operation_transaction"),
        "transaction_boundary": "consume_and_operation_transaction",
        "cas_entities": ("character", "equipment_instance"),
        "idempotency_scope": "campaign_item_consume",
        "snapshot_effects": ("quantity", "equipment_instance", "audit"),
    },
    "item.triggered_effect.v1": {
        "content_kind": "item",
        "runtime_schema_version": "item-ir-1",
        "clause_types": ("triggered_effect", "condition"),
        "required_fields": ("item_id", "character_id", "character_version", "trigger"),
        "required_services": ("rules_kernel", "operation_transaction"),
        "transaction_boundary": "item_trigger_and_effect_transaction",
        "cas_entities": ("character", "equipment_instance", "target"),
        "idempotency_scope": "campaign_item_trigger",
        "snapshot_effects": ("conditions", "effects", "audit"),
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
    "summon_or_creation",
    "temporary_hp",
    "timed_modifier",
    "upcast",
    "area",
    "spell_origins",
    "communication_route",
}

_ALLOWED_ITEM_CLAUSES = {
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
        if any(
            isinstance(_parameters(block).get("progression"), list)
            for block in blocks.get("upcast", [])
        ):
            if not _has_effect(blocks, "damage", "healing"):
                raise ValueError("spell scaling requires a typed damage or healing effect")
            resolved.append("spell.cantrip_scaling.v1")
        if blocks.get("saving_throw") and _has_effect(blocks, "damage"):
            resolved.append("combat_engine.damage_heal.v1")
        if blocks.get("concentration"):
            resolved.append("spell_economy.concentration.v1")
        if _has_effect(blocks, "spell_modifier"):
            resolved.append("spell.defense.v1")
        if _has_effect(blocks, "timed_modifier"):
            if not blocks.get("target_selection") or not blocks.get("duration"):
                raise ValueError("timed spell modifier requires typed target and duration")
            resolved.append("spell.timed_modifier.v1")
        if blocks.get("communication_route"):
            if not blocks.get("target_selection"):
                raise ValueError("communication route requires typed target selection")
            if len(blocks["communication_route"]) != 1:
                raise ValueError("spell runtime requires exactly one communication route contract")
            route = blocks["communication_route"][0]
            if route.get("resolution_kind") != "private_communication_route":
                raise ValueError("unsupported communication route resolution")
            resolved.append("spell.communication.route.v1")
        if _has_effect(blocks, "summon_or_creation"):
            if not blocks.get("target_selection"):
                raise ValueError("summon runtime requires a typed target selection")
            resolved.append("spell.summon.v1")
        if blocks.get("apply_condition"):
            resolved.append("combat_engine.condition_lifecycle.v1")
        if blocks.get("spell_origins"):
            if len(blocks["spell_origins"]) != 1:
                raise ValueError("spell runtime requires exactly one remote origin contract")
            origin = blocks["spell_origins"][0]
            if origin.get("resolution_kind") != "remote_spell_origin":
                raise ValueError("unsupported spell origin resolution")
            resolved.append("spell.remote_origin.v1")
        if not resolved:
            raise ValueError("spell runtime has no registered executable consumer")
        return tuple(dict(_CONSUMERS[item], consumer_id=item) for item in sorted(set(resolved)))

    if content_kind == "feature":
        if runtime_schema_version not in {"feature-runtime-1", ""}:
            raise ValueError("unsupported Content IR feature runtime schema")
        resolved: list[str] = []
        if blocks.get("spell_context"):
            resolved.append("spell.context.v1")
        if blocks.get("feature_event_window"):
            resolved.append("combat_engine.feature_event_window.v1")
        if blocks.get("roll_intervention"):
            resolved.append("combat_engine.roll_intervention.v1")
        if blocks.get("communication"):
            resolved.append("communication.mutual_comprehension.v1")
        if blocks.get("telepathic_information"):
            resolved.append("telepathic.information.v1")
        if blocks.get("entity_spatial"):
            resolved.append("entity.spatial.v1")
        if blocks.get("entity_senses"):
            resolved.append("entity.senses.v1")
        if blocks.get("entity_lifecycles") or blocks.get("resources") or blocks.get(
            "advancement"
        ) or blocks.get("proficiencies") or blocks.get("prepared_spell_list") or blocks.get(
            "spell_list_expansions"
        ):
            resolved.append("advancement_service.character_growth.v1")
        if blocks.get("spell_slot_reactivations"):
            resolved.append("spell.slot.reactivation.v1")
        if blocks.get("vessel_spaces"):
            resolved.append("vessel.space.v1")
        if blocks.get("spell_origins"):
            resolved.append("spell.remote_origin.v1")
        if blocks.get("attack_rider"):
            resolved.append("combat_engine.damage_heal.v1")
        if blocks.get("feature_action"):
            resolved.append("combat_engine.feature_action.v1")
        if blocks.get("condition_removal"):
            resolved.append("combat_engine.condition_lifecycle.v1")
        if blocks.get("timed_modifier") or blocks.get("passive_registry"):
            resolved.append("combat_engine.feature_action.v1")
        if not resolved:
            raise ValueError("feature runtime has no registered executable consumer")
        return tuple(
            dict(_CONSUMERS[item], consumer_id=item)
            for item in sorted(set(resolved))
        )
        raise ValueError("feature runtime has no registered executable consumer")

    if content_kind == "item":
        if runtime_schema_version != "item-ir-1":
            raise ValueError("unsupported Content IR item runtime schema")
        raw_clauses = blocks.get("clauses")
        if not isinstance(raw_clauses, list) or not raw_clauses:
            raise ValueError("item runtime requires typed clauses")
        clause_types = {
            str(item.get("clause_type") or "")
            for item in raw_clauses
            if isinstance(item, Mapping)
        }
        unknown = clause_types - _ALLOWED_ITEM_CLAUSES
        if unknown:
            raise ValueError("unknown item clauses: " + ",".join(sorted(unknown)))
        resolved: list[str] = []
        if clause_types & {"equipment", "passive_modifier", "resistance", "immunity"}:
            resolved.append("item.equipment_modifier.v1")
        if clause_types & {"attunement", "tattoo_lifecycle"}:
            resolved.append("item.attunement.v1")
        if clause_types & {"charge", "charge_recovery", "resource_binding"}:
            resolved.append("item.charge_resource.v1")
        if clause_types & {"granted_action", "damage", "healing", "temporary_hp"}:
            resolved.append("item.granted_action.v1")
        if "granted_spell" in clause_types:
            resolved.append("item.granted_spell.v1")
        if "consumable" in clause_types:
            resolved.append("item.consumable.v1")
        if clause_types & {"triggered_effect", "condition"}:
            resolved.append("item.triggered_effect.v1")
        if "dm_choice" in clause_types:
            resolved.append("item.triggered_effect.v1")
        if not resolved:
            raise ValueError("item runtime has no registered executable consumer")
        return tuple(dict(_CONSUMERS[item], consumer_id=item) for item in sorted(set(resolved)))

    if content_kind == "advancement":
        if runtime_schema_version != "feature-runtime-1":
            raise ValueError("unsupported Content IR advancement runtime schema")
        allowed = {
            "advancement",
            "proficiencies",
            "prepared_spell_list",
            "resources",
            "entity_lifecycles",
            "entity_senses",
            "spell_slot_reactivations",
            "spell_list_expansions",
            "vessel_spaces",
            "vessel_external_sound",
        }
        unknown = set(blocks) - allowed
        if unknown:
            raise ValueError("unknown advancement runtime sections: " + ",".join(sorted(unknown)))
        if not any(blocks.get(section) for section in allowed):
            raise ValueError("advancement runtime has no registered executable consumer")
        resolved: list[str] = []
        if blocks.get("entity_senses"):
            resolved.append("entity.senses.v1")
        if blocks.get("spell_slot_reactivations"):
            resolved.append("spell.slot.reactivation.v1")
        if blocks.get("vessel_spaces"):
            resolved.append("vessel.space.v1")
        if blocks.get("vessel_external_sound"):
            resolved.append("vessel.external_sound.v1")
        if any(
            blocks.get(section)
            for section in (
                "advancement",
                "proficiencies",
                "prepared_spell_list",
                "resources",
                "entity_lifecycles",
                "spell_list_expansions",
            )
        ):
            resolved.append("advancement_service.character_growth.v1")
        if not resolved:
            raise ValueError("advancement runtime has no registered executable consumer")
        return tuple(
            dict(_CONSUMERS[item], consumer_id=item)
            for item in sorted(set(resolved))
        )

    raise ValueError("content_kind must be spell, feature, item, or advancement")
