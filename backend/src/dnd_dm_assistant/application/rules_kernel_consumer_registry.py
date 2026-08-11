# ruff: noqa: E501
"""Closed rules-kernel consumer catalog.

Dispatch is based on protocol version, content kind and typed action/clause
kind.  Content names and source labels are data for provenance only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

KERNEL_REGISTRY_VERSION = "rules-kernel-consumer-registry-1"

_CONSUMERS: dict[str, dict[str, Any]] = {
    "kernel.content.typed": {
        "supported_schema_versions": ["rules-kernel-1", "spell-runtime-1", "feature-runtime-1"],
        "supported_content_kinds": ["spell", "feature", "feat", "item", "monster_action"],
        "supported_clause_types": [
            "damage", "healing", "temporary_hp", "apply_condition", "remove_condition",
            "area", "attack_roll", "saving_throw", "concentration", "duration", "modifier",
            "reaction_window",
        ],
        "required_fields": ["actor_id", "command_id"],
        "required_services": ["content_ir_runtime", "combat_engine", "spell_economy"],
        "required_spatial_queries": ["validate_target_range", "resolve_area_targets"],
        "required_choice_kinds": [],
        "required_adjudication_kinds": [],
        "transaction_boundary": "kernel_command_transaction_with_content_rollback",
        "cas_entities": ["actor", "targets", "scene", "combat", "resource"],
        "idempotency_scope": "campaign:rules-kernel:command",
        "snapshot_effects": ["content_state", "combat_state", "resource_state"],
        "scene_delta_types": ["update_health", "update_resource", "apply_condition", "set_concentration"],
    },
    "kernel.spatial.movement": {
        "supported_schema_versions": ["rules-kernel-1"],
        "supported_content_kinds": ["feature", "spell", "system"],
        "supported_clause_types": ["movement", "forced_movement", "teleport", "swap_positions"],
        "required_fields": ["actor_id", "spatial_intent"],
        "required_services": ["spatial_authority", "combat_engine"],
        "required_spatial_queries": ["validate_path", "validate_forced_movement", "validate_teleport_destination"],
        "required_choice_kinds": [],
        "required_adjudication_kinds": ["custom_movement"],
        "transaction_boundary": "multi_entity_movement_transaction",
        "cas_entities": ["actor", "targets", "scene", "combat"],
        "idempotency_scope": "campaign:rules-kernel:command",
        "snapshot_effects": ["position", "movement_budget", "combatant_version"],
        "scene_delta_types": ["move_entity", "teleport_entity"],
    },
    "kernel.entity.lifecycle": {
        "supported_schema_versions": ["rules-kernel-1"],
        "supported_content_kinds": ["spell", "feature", "monster_action", "system"],
        "supported_clause_types": ["summon_known_profile", "create_known_object", "create_known_hazard"],
        "required_fields": ["actor_id", "spatial_intent.entity_profile_id"],
        "required_services": ["compendium", "combat_engine", "scene"],
        "required_spatial_queries": ["is_space_occupied", "find_nearest_unoccupied_space"],
        "required_choice_kinds": [],
        "required_adjudication_kinds": ["custom_object"],
        "transaction_boundary": "entity_spawn_transaction",
        "cas_entities": ["actor", "scene", "combat", "entity_profile"],
        "idempotency_scope": "campaign:rules-kernel:command",
        "snapshot_effects": ["combatant", "scene_token", "initiative", "lifecycle_effect"],
        "scene_delta_types": ["spawn_entity", "despawn_entity", "create_object", "create_hazard"],
    },
    "kernel.choice.window": {
        "supported_schema_versions": ["rules-kernel-1"],
        "supported_content_kinds": ["spell", "feature", "feat", "item", "system"],
        "supported_clause_types": ["choice", "replacement_choice", "mode_choice", "resource_choice"],
        "required_fields": ["actor_id", "choice_inputs"],
        "required_services": ["choice_window_store"],
        "required_spatial_queries": [],
        "required_choice_kinds": ["fixed_options", "typed_asset_options", "target_options", "position_options", "replacement_choice", "mode_choice", "resource_choice"],
        "required_adjudication_kinds": [],
        "transaction_boundary": "choice_window_compare_and_swap",
        "cas_entities": ["actor", "targets", "choice_window"],
        "idempotency_scope": "campaign:rules-kernel:choice-window",
        "snapshot_effects": ["choice_resolution"],
        "scene_delta_types": ["emit_combat_log"],
    },
    "kernel.dm.adjudication": {
        "supported_schema_versions": ["rules-kernel-1", "dm-adjudication-1"],
        "supported_content_kinds": ["spell", "feature", "feat", "item", "monster_action", "system"],
        "supported_clause_types": ["target_semantics", "freeform_effect", "illusion", "environment", "custom_movement", "rule_exception"],
        "required_fields": ["actor_id"],
        "required_services": ["adjudication_window_store"],
        "required_spatial_queries": ["validate_target_range", "validate_area_origin"],
        "required_choice_kinds": [],
        "required_adjudication_kinds": ["target_semantics", "freeform_effect", "illusion_interpretation", "environment_interaction", "custom_object", "custom_movement", "rule_exception"],
        "transaction_boundary": "adjudication_compare_and_swap_then_command",
        "cas_entities": ["actor", "targets", "scene", "adjudication_window"],
        "idempotency_scope": "campaign:rules-kernel:adjudication",
        "snapshot_effects": ["adjudication_decision", "command_continuation"],
        "scene_delta_types": ["request_dm_adjudication", "emit_combat_log"],
    },
}


def kernel_consumer_descriptors() -> dict[str, dict[str, Any]]:
    return {key: dict(value) for key, value in sorted(_CONSUMERS.items())}


def resolve_kernel_consumer(
    *,
    runtime_schema_version: str,
    content_kind: str,
    clause_types: set[str],
    action_kind: str,
) -> dict[str, Any]:
    """Resolve exactly one closed consumer or fail closed."""

    candidates = []
    for consumer_id, descriptor in sorted(_CONSUMERS.items()):
        if runtime_schema_version not in descriptor["supported_schema_versions"]:
            continue
        if content_kind not in descriptor["supported_content_kinds"]:
            continue
        supported = set(descriptor["supported_clause_types"])
        if action_kind in supported or clause_types.intersection(supported):
            candidates.append((consumer_id, descriptor))
    if not candidates:
        raise ValueError(
            "no closed rules-kernel consumer for schema/content/clause contract"
        )
    action_matches = [item for item in candidates if action_kind in set(item[1]["supported_clause_types"])]
    if len(action_matches) == 1:
        consumer_id, descriptor = action_matches[0]
    elif len(candidates) == 1:
        consumer_id, descriptor = candidates[0]
    else:
        raise ValueError("ambiguous rules-kernel consumer contract")
    return {"consumer_id": consumer_id, **descriptor}


def validate_consumer_fields(consumer: Mapping[str, Any], command: Mapping[str, Any]) -> None:
    """Fail closed when a resolved consumer does not receive its contract fields."""

    for field in consumer.get("required_fields", []):
        if "." in field:
            value: Any = command
            for part in field.split("."):
                value = value.get(part) if isinstance(value, Mapping) else None
        else:
            value = command.get(field)
        if value is None or value == "":
            raise ValueError(f"rules-kernel command is missing required field: {field}")
