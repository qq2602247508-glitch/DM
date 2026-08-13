"""Closed capability catalog used by the Feature IR compiler.

Capabilities describe existing production consumers.  They do not execute
rules and deliberately carry no feature-specific branches.  A capability can
only participate in an automatic ``full`` result when its evidence and
production status are explicit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from dnd_dm_assistant.domain.feature_ir import canonical_json
from dnd_dm_assistant.domain.feature_operators import get_operator_contract

CAPABILITY_STATUSES = frozenset(
    {"production_closed", "production_partial", "manual_only", "deprecated", "unsupported"}
)


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    contract_version: str
    supported_operator: str
    supported_triggers: frozenset[str]
    supported_conditions: frozenset[str]
    supported_inputs: frozenset[str]
    supported_targets: frozenset[str]
    supported_duration: frozenset[str]
    producer: str
    consumer: str
    persisted_state: str
    action_economy_support: frozenset[str]
    resource_support: frozenset[str]
    idempotency_support: bool
    cas_support: bool
    ui_projection_support: bool
    production_status: str
    evidence_tests: tuple[str, ...]
    known_limitations: tuple[str, ...] = ()
    materializer_id: str | None = None

    def __post_init__(self) -> None:
        if self.production_status not in CAPABILITY_STATUSES:
            raise ValueError(f"unsupported capability status: {self.production_status}")
        if not self.capability_id.strip():
            raise ValueError("capability_id cannot be empty")
        if not self.supported_operator.strip():
            raise ValueError("supported_operator cannot be empty")
        if self.production_status == "production_closed":
            for field_name, values in (
                ("supported_triggers", self.supported_triggers),
                ("supported_conditions", self.supported_conditions),
                ("supported_inputs", self.supported_inputs),
                ("supported_targets", self.supported_targets),
                ("supported_duration", self.supported_duration),
                ("action_economy_support", self.action_economy_support),
                ("resource_support", self.resource_support),
            ):
                if "*" in values:
                    raise ValueError(
                        f"production_closed capability {self.capability_id} "
                        f"cannot use wildcard {field_name}"
                    )
            required = {
                "producer": self.producer,
                "consumer": self.consumer,
                "persisted_state": self.persisted_state,
            }
            if any(not value.strip() for value in required.values()):
                raise ValueError(
                    f"production_closed capability {self.capability_id} needs producer, "
                    "consumer and persisted_state"
                )
            if not self.idempotency_support or not self.cas_support:
                raise ValueError(
                    f"production_closed capability {self.capability_id} needs CAS and idempotency"
                )
            if not self.evidence_tests:
                raise ValueError(
                    f"production_closed capability {self.capability_id} needs evidence_tests"
                )
            contract = get_operator_contract(self.supported_operator)
            if contract is not None:
                if self.capability_id != contract.capability_id:
                    raise ValueError(
                        f"capability {self.capability_id} does not match "
                        f"operator contract {self.supported_operator}"
                    )
                if self.materializer_id != contract.materializer_id:
                    raise ValueError(
                        f"capability {self.capability_id} needs materializer "
                        f"{contract.materializer_id}"
                    )

    def supports(
        self,
        *,
        trigger: str,
        conditions: Iterable[str],
        inputs: Iterable[str],
        target: str | None,
        duration: str | None,
        action_economy: str,
        resource_operations: Iterable[str],
    ) -> tuple[str, ...]:
        errors: list[str] = []

        def check(value: str, supported: frozenset[str], label: str) -> None:
            if supported and "*" not in supported and value not in supported:
                errors.append(f"{label} {value!r} is unsupported by {self.capability_id}")

        check(trigger, self.supported_triggers, "trigger")
        for condition in conditions:
            if self.supported_conditions and "*" not in self.supported_conditions:
                if condition not in self.supported_conditions:
                    errors.append(f"condition {condition!r} is unsupported by {self.capability_id}")
        for input_kind in inputs:
            if self.supported_inputs and "*" not in self.supported_inputs:
                if input_kind not in self.supported_inputs:
                    errors.append(f"input {input_kind!r} is unsupported by {self.capability_id}")
        if target is not None:
            check(target, self.supported_targets, "target")
        if duration is not None:
            check(duration, self.supported_duration, "duration")
        check(action_economy, self.action_economy_support, "action economy")
        for operation in resource_operations:
            if self.resource_support and "*" not in self.resource_support:
                if operation not in self.resource_support:
                    errors.append(
                        f"resource operation {operation!r} is unsupported by {self.capability_id}"
                    )
        return tuple(errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "contract_version": self.contract_version,
            "supported_operator": self.supported_operator,
            "supported_triggers": sorted(self.supported_triggers),
            "supported_conditions": sorted(self.supported_conditions),
            "supported_inputs": sorted(self.supported_inputs),
            "supported_targets": sorted(self.supported_targets),
            "supported_duration": sorted(self.supported_duration),
            "producer": self.producer,
            "consumer": self.consumer,
            "persisted_state": self.persisted_state,
            "action_economy_support": sorted(self.action_economy_support),
            "resource_support": sorted(self.resource_support),
            "idempotency_support": self.idempotency_support,
            "cas_support": self.cas_support,
            "ui_projection_support": self.ui_projection_support,
            "production_status": self.production_status,
            "evidence_tests": list(self.evidence_tests),
            "known_limitations": list(self.known_limitations),
            "materializer_id": self.materializer_id,
        }


class CapabilityCatalog:
    """Deterministic registry of capability descriptors."""

    def __init__(self, descriptors: Iterable[CapabilityDescriptor] = ()) -> None:
        self._descriptors: dict[str, CapabilityDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: CapabilityDescriptor) -> None:
        existing = self._descriptors.get(descriptor.capability_id)
        if existing is not None and existing != descriptor:
            raise ValueError(f"duplicate capability_id: {descriptor.capability_id}")
        self._descriptors[descriptor.capability_id] = descriptor

    def get_for_operator(self, operator: str) -> tuple[CapabilityDescriptor, ...]:
        return tuple(
            descriptor
            for descriptor in self._descriptors.values()
            if descriptor.supported_operator == operator
        )

    def get(self, capability_id: str) -> CapabilityDescriptor | None:
        return self._descriptors.get(capability_id)

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(self._descriptors[key] for key in sorted(self._descriptors))

    def fingerprint(self) -> str:
        return canonical_json([item.to_dict() for item in self.descriptors()])

    def to_dict(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.descriptors()]

    def validation_errors(self) -> tuple[str, ...]:
        """Return closed-world catalog violations without mutating the catalog."""

        errors: list[str] = []
        for descriptor in self.descriptors():
            if descriptor.production_status != "production_closed":
                continue
            contract = get_operator_contract(descriptor.supported_operator)
            if contract is None:
                errors.append(f"{descriptor.capability_id}: missing operator contract")
                continue
            if descriptor.materializer_id != contract.materializer_id:
                errors.append(f"{descriptor.capability_id}: materializer mismatch")
            if descriptor.capability_id != contract.capability_id:
                errors.append(f"{descriptor.capability_id}: capability mismatch")
            for label, values in (
                ("triggers", descriptor.supported_triggers),
                ("conditions", descriptor.supported_conditions),
                ("inputs", descriptor.supported_inputs),
                ("targets", descriptor.supported_targets),
                ("duration", descriptor.supported_duration),
                ("action_economy", descriptor.action_economy_support),
                ("resources", descriptor.resource_support),
            ):
                if "*" in values:
                    errors.append(f"{descriptor.capability_id}: wildcard {label}")
        return tuple(errors)


_ALL_TRIGGERS = frozenset(
    {
        "advancement_confirmed",
        "combat_started",
        "initiative_rolled",
        "turn_started",
        "turn_ended",
        "action_declared",
        "action_resolved",
        "spell_cast",
        "attack_declared",
        "attack_hit",
        "attack_missed",
        "damage_before_apply",
        "damage_applied",
        "saving_throw",
        "ability_check",
        "short_rest_started",
        "short_rest_completed",
        "long_rest_started",
        "long_rest_completed",
        "resource_depleted",
        "zero_hp",
        "explicit_activation",
    }
)
_ALL_CONDITIONS = frozenset(
    {
        "actor_has_feature",
        "actor_has_state",
        "actor_lacks_state",
        "target_has_state",
        "target_matches_persisted_id",
        "first_round",
        "first_turn",
        "target_has_not_acted",
        "within_range",
        "visible",
        "audible",
        "equipped",
        "armor_category",
        "weapon_category",
        "spell_school",
        "spell_level_range",
        "spell_source",
        "damage_type",
        "action_tag",
        "once_per_turn",
        "once_per_target",
        "resource_is_zero",
    }
)
_ALL_TARGETS = frozenset(
    {"self", "one_creature", "ally", "enemy", "marked_target", "visible_creature", "aura"}
)
_ALL_DURATIONS = frozenset(
    {
        "current_turn",
        "current_round",
        "one_minute",
        "ten_minutes",
        "one_hour",
        "until_short_rest",
        "until_long_rest",
        "until_condition_ends",
        "permanent",
        "advancement_persistent",
    }
)
_ALL_ACTIONS = frozenset(
    {"automatic", "action", "bonus_action", "reaction", "none", "explicit_player_choice"}
)
_ALL_RESOURCES = frozenset(
    {
        "grant",
        "consume",
        "restore",
        "exchange",
        "set",
        "set_to_max",
        "short_rest",
        "long_rest",
        "turn",
        "event",
    }
)


def _descriptor(
    capability_id: str,
    operator: str,
    *,
    consumer: str,
    producer: str,
    persisted_state: str,
    status: str = "production_closed",
    targets: frozenset[str] = _ALL_TARGETS,
    durations: frozenset[str] = _ALL_DURATIONS,
    actions: frozenset[str] | None = None,
    inputs: frozenset[str] | None = None,
    resources: frozenset[str] | None = None,
    limitations: tuple[str, ...] = (),
    evidence: tuple[str, ...] = ("feature_runtime_contract_tests",),
) -> CapabilityDescriptor:
    contract = get_operator_contract(operator)
    supported_triggers = contract.compatible_triggers if contract is not None else _ALL_TRIGGERS
    supported_conditions = (
        contract.compatible_conditions if contract is not None else _ALL_CONDITIONS
    )
    supported_targets = contract.compatible_targets if contract is not None else targets
    supported_duration = contract.compatible_durations if contract is not None else durations
    supported_actions = (
        actions
        if actions is not None
        else (contract.compatible_action_economy if contract is not None else _ALL_ACTIONS)
    )
    supported_resources = (
        resources
        if resources is not None
        else (contract.compatible_resource_operations if contract is not None else _ALL_RESOURCES)
    )
    return CapabilityDescriptor(
        capability_id=capability_id,
        contract_version="1.0",
        supported_operator=operator,
        supported_triggers=supported_triggers,
        supported_conditions=supported_conditions,
        supported_inputs=(
            inputs
            if inputs is not None
            else frozenset(
                {"choice", "d20", "damage_total", "target_ids", "player_or_dm_choice"}
            )
        ),
        supported_targets=supported_targets,
        supported_duration=supported_duration,
        producer=producer,
        consumer=consumer,
        persisted_state=persisted_state,
        action_economy_support=supported_actions,
        resource_support=supported_resources,
        idempotency_support=True,
        cas_support=True,
        ui_projection_support=True,
        production_status=status,
        evidence_tests=evidence,
        known_limitations=limitations,
        materializer_id=contract.materializer_id if contract is not None else None,
    )


def default_capability_catalog() -> CapabilityCatalog:
    """Return the reviewed capability catalog for the current production tree."""

    closed: list[CapabilityDescriptor] = [
        _descriptor(
            "advancement.proficiency",
            "grant_proficiency",
            consumer="advancement_service.character_proficiency_registry",
            producer="advancement_service",
            persisted_state="character.proficiencies",
        ),
        _descriptor(
            "advancement.language",
            "grant_language",
            consumer="advancement_service.character_proficiency_registry",
            producer="advancement_service",
            persisted_state="character.languages",
        ),
        _descriptor(
            "advancement.spell",
            "grant_spell",
            consumer="advancement_service.spell_registry",
            producer="advancement_service",
            persisted_state="character.spells",
        ),
        _descriptor(
            "advancement.spell_list_expansion",
            "configure_spell_list_expansion",
            consumer="advancement_service.spell_catalog_validator",
            producer="advancement_service",
            persisted_state="character.features",
            evidence=("test_spell_list_expansion_runtime_contract",),
        ),
        _descriptor(
            "advancement.prepare_spell",
            "prepare_spell",
            consumer="advancement_service.spell_registry",
            producer="advancement_service",
            persisted_state="character.prepared_spells",
        ),
        _descriptor(
            "resource.lifecycle",
            "restore_resource",
            consumer="rest_service.character_resource_store",
            producer="rest_service",
            persisted_state="character.resources",
        ),
        _descriptor(
            "resource.profile",
            "set_resource_profile",
            consumer="character_resource_store",
            producer="advancement_service",
            persisted_state="character.resources",
        ),
        _descriptor(
            "resource.lifecycle.consume",
            "consume_resource",
            consumer="combat_and_advancement_resource_cas",
            producer="feature_action_or_event",
            persisted_state="character.resources",
        ),
        _descriptor(
            "resource.exchange",
            "exchange_resource",
            consumer="resource_exchange_cas",
            producer="feature_action_or_event",
            persisted_state="character.resources",
        ),
        _descriptor(
            "modifier.passive",
            "add_modifier",
            consumer="typed_modifier_resolvers",
            producer="feature_runtime_compiler",
            persisted_state="character.feature_runtime",
        ),
        _descriptor(
            "modifier.passive.v2",
            "grant_passive_modifier",
            consumer="feature_runtime_registry.combat_start_modifiers",
            producer="feature_runtime_compiler",
            persisted_state="character.feature_runtime",
            evidence=("test_feature_runtime_fanout",),
        ),
        _descriptor(
            "modifier.passive.set",
            "set_modifier",
            consumer="typed_modifier_resolvers",
            producer="feature_runtime_compiler",
            persisted_state="character.feature_runtime",
        ),
        _descriptor(
            "modifier.roll",
            "impose_advantage",
            consumer="d20_and_attack_context_resolvers",
            producer="feature_runtime_compiler",
            persisted_state="character.feature_runtime",
        ),
        _descriptor(
            "modifier.roll.disadvantage",
            "impose_disadvantage",
            consumer="d20_and_attack_context_resolvers",
            producer="feature_runtime_compiler",
            persisted_state="character.feature_runtime",
        ),
        _descriptor(
            "movement.mode",
            "grant_movement_mode",
            consumer="authoritative_grid_movement",
            producer="feature_runtime_compiler",
            persisted_state="combatant.snapshot_json",
        ),
        _descriptor(
            "movement.teleport",
            "teleport",
            consumer="authoritative_grid_movement",
            producer="feature_runtime_compiler",
            persisted_state="combatant.snapshot_json",
            targets=frozenset({"self"}),
            durations=frozenset({"current_turn"}),
            actions=frozenset({"bonus_action", "action", "reaction", "explicit_player_choice"}),
            resources=_ALL_RESOURCES,
            evidence=("test_psychic_teleport_materializes_typed_action_and_resource",),
        ),
        _descriptor(
            "sight.mode",
            "grant_sight_mode",
            consumer="combat_visibility_and_attack_context",
            producer="feature_runtime_compiler",
            persisted_state="combatant.snapshot_json",
        ),
        _descriptor(
            "damage.healing",
            "heal",
            consumer="typed_damage_healing_resolver",
            producer="healing_resolution",
            persisted_state="combatant.hp",
        ),
        _descriptor(
            "damage.temporary_hp",
            "grant_temporary_hp",
            consumer="damage_and_temporary_hp_resolver",
            producer="feature_event_or_rest",
            persisted_state="combatant.temporary_hp",
        ),
        _descriptor(
            "damage.modifier",
            "add_damage",
            consumer="typed_damage_healing_resolver",
            producer="damage_resolution",
            persisted_state="combat_action.damage",
        ),
        _descriptor(
            "damage.type",
            "replace_damage_type",
            consumer="typed_damage_healing_resolver",
            producer="spell_or_attack_resolution",
            persisted_state="combat_action.damage",
        ),
        _descriptor(
            "defense.resistance",
            "grant_resistance",
            consumer="damage_defense_resolver",
            producer="feature_runtime_compiler",
            persisted_state="combatant.damage_resistances",
        ),
        _descriptor(
            "defense.saving_throw_advantage",
            "grant_saving_throw_advantage",
            consumer="saving_throw_resolution",
            producer="feature_runtime_compiler",
            persisted_state="combatant.snapshot_json.feature_runtime",
            evidence=("test_spell_resistance_config_covers_magical_saves_and_damage",),
        ),
        _descriptor(
            "defense.immunity",
            "grant_immunity",
            consumer="condition_and_damage_defense_resolver",
            producer="feature_runtime_compiler",
            persisted_state="combatant.conditions_and_defenses",
        ),
        _descriptor(
            "state.lifecycle.activate",
            "activate_condition",
            consumer="feature_condition_lifecycle",
            producer="combat_feature_action",
            persisted_state="combatant.conditions",
        ),
        _descriptor(
            "state.lifecycle.remove",
            "remove_condition",
            consumer="feature_condition_lifecycle",
            producer="combat_boundary_or_feature_action",
            persisted_state="combatant.conditions",
        ),
        _descriptor(
            "modifier.timed",
            "create_timed_modifier",
            consumer="timed_feature_modifier_resolver",
            producer="feature_action_or_event",
            persisted_state="combatant.timed_feature_modifiers",
        ),
        _descriptor(
            "window.triggered_attack",
            "create_triggered_attack_window",
            consumer="triggered_attack_window_resolver",
            producer="combat_event_dispatch",
            persisted_state="combat_actions",
            targets=frozenset({"enemy", "marked_target", "one_creature"}),
            durations=frozenset({"current_turn", "current_round"}),
        ),
        _descriptor(
            "zero_hp.intervention",
            "zero_hp_intervention",
            consumer="zero_hp_damage_resolution",
            producer="damage_resolution",
            persisted_state="character_resource_and_combat_snapshot",
            targets=frozenset({"self"}),
            durations=frozenset({"current_turn", "current_round", "until_long_rest"}),
            actions=frozenset({"none", "automatic", "reaction", "explicit_player_choice"}),
            resources=_ALL_RESOURCES,
            evidence=("test_zero_hp_intervention",),
        ),
        _descriptor(
            "spell.healing_modifier",
            "spell_healing_modifier",
            consumer="spell_healing_resolution",
            producer="spell_cast_resolution",
            persisted_state="combatant.spell_context",
            targets=frozenset({"self", "ally", "one_creature"}),
            durations=frozenset({"permanent", "advancement_persistent"}),
            evidence=("test_spell_healing_modifier",),
        ),
        _descriptor(
            "spell.damage_modifier",
            "spell_damage_modifier",
            consumer="spell_damage_resolution",
            producer="spell_cast_resolution",
            persisted_state="combatant.spell_context",
            targets=frozenset({"self", "one_creature", "ally", "enemy"}),
            durations=frozenset({"permanent", "advancement_persistent"}),
            evidence=("test_spell_damage_modifier",),
        ),
        _descriptor(
            "spell.save_damage_modifier",
            "spell_save_damage_modifier",
            consumer="spell_save_damage_resolution",
            producer="spell_cast_resolution",
            persisted_state="combatant.spell_context",
            targets=frozenset({"self", "one_creature", "ally", "enemy"}),
            durations=frozenset({"permanent", "advancement_persistent"}),
            evidence=("test_spell_save_damage_modifier",),
        ),
        _descriptor(
            "spell.free_cast",
            "free_spell_cast",
            consumer="spell_economy_service",
            producer="advancement_service",
            persisted_state="character.resources_and_spells",
            durations=frozenset({"permanent", "advancement_persistent"}),
            resources=_ALL_RESOURCES,
            evidence=("test_spell_economy",),
        ),
        _descriptor(
            "window.reaction",
            "create_reaction_window",
            consumer="eligible_action_window_resolver",
            producer="combat_event_dispatch",
            persisted_state="combat_actions",
            actions=frozenset({"reaction", "explicit_player_choice"}),
        ),
        _descriptor(
            "attack.roll.intervention",
            "configure_attack_roll_intervention",
            consumer="player_attack_resolution",
            producer="feature_runtime_compiler",
            persisted_state="combatant.snapshot_json.feature_runtime",
            targets=frozenset({"self"}),
            durations=frozenset({"permanent", "advancement_persistent"}),
            evidence=("test_combat_inspiration_runtime_contract",),
        ),
        _descriptor(
            "target.authorized_information",
            "expose_authorized_target_information",
            consumer="combat_feature_action_target_defense_inspection",
            producer="feature_action",
            persisted_state="combat_action.result_json",
            targets=frozenset({"enemy", "marked_target", "one_creature"}),
            durations=frozenset({"current_turn", "permanent", "advancement_persistent"}),
            actions=frozenset({"none", "action", "bonus_action", "explicit_player_choice"}),
            evidence=("test_hunters_lore_target_defense_inspection",),
        ),
        _descriptor(
            "communication.mutual_comprehension",
            "grant_communication",
            consumer="communication_service",
            producer="feature_runtime_compiler",
            persisted_state="combat_action.result_json",
            evidence=("test_fathomless_underwater_mutual_comprehension",),
        ),
        _descriptor(
            "entity.lifecycle",
            "configure_entity_lifecycle",
            consumer="entity_lifecycle_service",
            producer="feature_runtime_compiler",
            persisted_state="entity.lifecycle.state",
            targets=frozenset({"self"}),
            durations=frozenset({"permanent", "advancement_persistent"}),
            inputs=frozenset(),
            evidence=("test_entity_lifecycle_runtime_contract",),
        ),
        _descriptor(
            "entity.senses",
            "configure_entity_senses",
            consumer="entity_sensory_profile_service",
            producer="feature_runtime_compiler",
            persisted_state="entity.lifecycle.sensory_profile",
            targets=frozenset({"self"}),
            durations=frozenset({"permanent", "advancement_persistent", "ten_minutes"}),
            actions=frozenset({"none", "bonus_action", "action"}),
            inputs=frozenset(),
            status="production_closed",
            evidence=(
                "test_content_ir_entity_senses_runtime",
                "test_content_ir_production_closure",
            ),
        ),
        _descriptor(
            "spell.remote_origin",
            "configure_remote_spell_origin",
            consumer="remote_spell_origin_resolver",
            producer="feature_runtime_compiler",
            persisted_state="combat_action.spell_origin_resolution",
            targets=frozenset({"one_creature", "multiple_creatures"}),
            durations=frozenset({"current_turn", "permanent", "advancement_persistent"}),
            inputs=frozenset(),
            actions=frozenset(
                {"none", "action", "bonus_action", "reaction", "explicit_player_choice"}
            ),
            evidence=("test_remote_spell_origin_runtime_contract",),
        ),
        _descriptor(
            "spell.slot.reactivation",
            "configure_spell_slot_reactivation",
            consumer="spell_slot_reactivation_service",
            producer="feature_runtime_compiler",
            persisted_state="entity.lifecycle.reactivation_state",
            targets=frozenset({"self"}),
            durations=frozenset({"permanent", "advancement_persistent"}),
            actions=frozenset({"none", "bonus_action"}),
            resources=frozenset({"long_rest", "consume"}),
            status="production_closed",
            evidence=(
                "test_content_ir_spell_slot_reactivation_runtime",
                "test_content_ir_production_closure",
            ),
        ),
        _descriptor(
            "spell.context",
            "override_spell_components",
            consumer="spell_economy_service",
            producer="spell_cast_resolution",
            persisted_state="combat_action.spell_context",
            evidence=("test_typed_spell_context_payment_and_components",),
        ),
        _descriptor(
            "spell.context.range",
            "override_spell_range",
            consumer="spell_economy_service",
            producer="spell_cast_resolution",
            persisted_state="combat_action.spell_context",
            status="production_partial",
            limitations=("施法距离覆盖尚未完成正式生产迁移。",),
            evidence=("spell_context_partial_contract",),
        ),
        _descriptor(
            "spell.context.payment",
            "override_spell_payment",
            consumer="spell_economy_service",
            producer="spell_cast_resolution",
            persisted_state="combat_action.spell_context",
            evidence=("test_typed_spell_context_payment_and_components",),
        ),
    ]
    return CapabilityCatalog(closed)
