"""Feature IR compiler and legacy shadow adapter.

The compiler is a satisfiability checker, not a second rules engine.  It
resolves every IR effect against the closed capability catalog and emits
canonical runtime blocks only for clauses that have a production consumer.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from dnd_dm_assistant.application.feature_materializers import (
    MaterializerRegistry,
    default_materializer_registry,
)
from dnd_dm_assistant.domain.feature_capabilities import (
    CapabilityCatalog,
    CapabilityDescriptor,
    default_capability_catalog,
)
from dnd_dm_assistant.domain.feature_ir import (
    ClauseSpec,
    FeatureSpec,
    canonical_json,
)
from dnd_dm_assistant.domain.feature_operators import get_operator_contract


@dataclass(frozen=True)
class ClauseCompileResult:
    clause_id: str
    status: str
    capability_ids: tuple[str, ...]
    generated_block: dict[str, Any] | None
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "status": self.status,
            "capability_ids": list(self.capability_ids),
            "generated_block": self.generated_block,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class CompileResult:
    feature_id: str
    compile_status: str
    clause_results: tuple[ClauseCompileResult, ...]
    generated_runtime_blocks: tuple[dict[str, Any], ...]
    required_inputs: tuple[dict[str, Any], ...]
    required_persistence: tuple[str, ...]
    required_ui: tuple[str, ...]
    required_tests: tuple[str, ...]
    dependencies: tuple[str, ...]
    unsupported_operators: tuple[str, ...]
    unsupported_conditions: tuple[str, ...]
    unsupported_combinations: tuple[str, ...]
    manual_boundaries: tuple[str, ...]
    evidence: tuple[str, ...]
    source_trust: str
    blockers: tuple[str, ...]
    status_authority: str
    legacy_adapter_used: bool
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "compile_status": self.compile_status,
            "clause_results": [item.to_dict() for item in self.clause_results],
            "generated_runtime_blocks": list(self.generated_runtime_blocks),
            "required_inputs": list(self.required_inputs),
            "required_persistence": list(self.required_persistence),
            "required_ui": list(self.required_ui),
            "required_tests": list(self.required_tests),
            "dependencies": list(self.dependencies),
            "unsupported_operators": list(self.unsupported_operators),
            "unsupported_conditions": list(self.unsupported_conditions),
            "unsupported_combinations": list(self.unsupported_combinations),
            "manual_boundaries": list(self.manual_boundaries),
            "evidence": list(self.evidence),
            "source_trust": self.source_trust,
            "blockers": list(self.blockers),
            "status_authority": self.status_authority,
            "legacy_adapter_used": self.legacy_adapter_used,
            "fingerprint": self.fingerprint,
        }


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _duration_kind(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        raw = value.get("kind") or value.get("duration")
        return str(raw) if raw else None
    return None


def _compile_effect(
    clause: ClauseSpec,
    operator: str,
    parameters: Mapping[str, Any],
    catalog: CapabilityCatalog,
    materializers: MaterializerRegistry,
) -> tuple[CapabilityDescriptor | None, tuple[str, ...]]:
    contract = get_operator_contract(operator)
    if contract is None:
        return None, (f"unsupported operator: {operator}",)
    parameter_validation = contract.validate_parameters(parameters)
    if not parameter_validation.valid:
        return None, tuple(f"invalid_parameters: {item}" for item in parameter_validation.errors)
    candidates = catalog.get_for_operator(operator)
    if not candidates:
        return None, (f"unsupported operator: {operator}",)
    conditions = tuple(item.kind for item in clause.conditions)
    inputs = tuple(item.kind for item in clause.required_inputs)
    target = clause.targeting.kind if clause.targeting else None
    duration = _duration_kind(clause.duration)
    if operator == "remove_condition" and clause.trigger in {
        "short_rest_started",
        "short_rest_completed",
        "long_rest_started",
        "long_rest_completed",
    }:
        if str(parameters.get("condition") or "").strip() != "exhaustion":
            return None, ("rest remove_condition only supports exhaustion",)
        if target not in {None, "self"}:
            return None, ("rest remove_condition only supports self target",)
    resource_operations = tuple(
        item.operation for item in (*clause.resource_costs, *clause.resource_recovery)
    )
    partial_errors: list[str] = []
    for descriptor in candidates:
        contract_errors = contract.validate_clause(
            trigger=clause.trigger,
            conditions=conditions,
            activation=clause.activation,
            action_economy=clause.action_economy,
            target=target,
            duration=duration,
            resource_operations=resource_operations,
        )
        if contract_errors:
            partial_errors.extend(contract_errors)
            continue
        errors = descriptor.supports(
            trigger=clause.trigger,
            conditions=conditions,
            inputs=inputs,
            target=target,
            duration=duration,
            action_economy=clause.action_economy,
            resource_operations=resource_operations,
        )
        if not errors and descriptor.production_status == "production_closed":
            if materializers.get(descriptor.materializer_id) is None:
                partial_errors.append(f"materializer_missing: {descriptor.materializer_id}")
                continue
            return descriptor, ()
        if errors:
            partial_errors.extend(errors)
        elif descriptor.production_status != "production_closed":
            partial_errors.append(
                f"capability {descriptor.capability_id} is {descriptor.production_status}"
            )
    return None, _unique(partial_errors)


class FeatureCompiler:
    """Compile FeatureSpec values against a reviewed capability catalog."""

    def __init__(
        self,
        catalog: CapabilityCatalog | None = None,
        *,
        available_feature_ids: Iterable[str] = (),
        status_authority: str = "compiler",
        materializers: MaterializerRegistry | None = None,
    ) -> None:
        self.catalog = catalog or default_capability_catalog()
        self.available_feature_ids = frozenset(str(item) for item in available_feature_ids)
        self.materializers = materializers or default_materializer_registry()
        if status_authority not in {"compiler", "shadow_candidate", "legacy"}:
            raise ValueError("status_authority must be compiler, shadow_candidate or legacy")
        self.status_authority = status_authority

    def compile(
        self,
        spec: FeatureSpec,
        *,
        legacy_adapter_used: bool = False,
    ) -> CompileResult:
        clause_results: list[ClauseCompileResult] = []
        generated: list[dict[str, Any]] = []
        required_inputs: list[dict[str, Any]] = []
        required_persistence: list[str] = []
        required_ui: list[str] = []
        required_tests: list[str] = []
        unsupported_operators: list[str] = []
        unsupported_conditions: list[str] = []
        unsupported_combinations: list[str] = []
        manual_boundaries: list[str] = []
        evidence: list[str] = []
        dependency_blockers: list[str] = []
        schema_blockers: list[str] = []

        if self.available_feature_ids:
            for dependency in spec.dependencies:
                if dependency not in self.available_feature_ids:
                    dependency_blockers.append(f"missing dependency: {dependency}")

        if spec.source_completeness == "unstructured":
            manual_boundaries.append("source is unstructured")
        elif spec.source_completeness == "incomplete":
            dependency_blockers.append("source is incomplete")
        if spec.source_trust not in {"authored_ir", "verified_mapping"}:
            dependency_blockers.append("source_trust_not_verified")

        for clause in spec.clauses:
            clause_capabilities: list[str] = []
            clause_blockers: list[str] = []
            clause_manual = str(clause.audit.get("manual_boundary") or "").strip()
            if clause_manual:
                clause_manual = f"{clause.clause_id}: {clause_manual}"
                manual_boundaries.append(clause_manual)

            for condition in clause.conditions:
                if not condition.kind.strip():
                    unsupported_conditions.append(f"{clause.clause_id}: empty condition")

            for input_spec in clause.required_inputs:
                required_inputs.append(
                    {
                        "clause_id": clause.clause_id,
                        "key": input_spec.key,
                        "kind": input_spec.kind,
                        "parameters": input_spec.parameters,
                    }
                )
                if input_spec.parameters.get("requires_ui"):
                    required_ui.append(str(input_spec.parameters["requires_ui"]))

            for effect in clause.effects:
                descriptor, errors = _compile_effect(
                    clause,
                    effect.operator,
                    effect.parameters,
                    self.catalog,
                    self.materializers,
                )
                if descriptor is None:
                    clause_blockers.extend(errors)
                    schema_blockers.extend(
                        f"{clause.clause_id}: {item}"
                        for item in errors
                        if item.startswith("invalid_parameters:")
                    )
                    if any(item.startswith("unsupported operator:") for item in errors):
                        unsupported_operators.append(effect.operator)
                    if any("condition " in item for item in errors):
                        unsupported_conditions.extend(
                            f"{clause.clause_id}: {condition.kind}"
                            for condition in clause.conditions
                        )
                    if any("unsupported" in item for item in errors):
                        unsupported_combinations.append(f"{clause.clause_id}: {effect.operator}")
                    continue
                clause_capabilities.append(descriptor.capability_id)
                evidence.extend(descriptor.evidence_tests)
                required_persistence.append(descriptor.persisted_state)
                if not descriptor.ui_projection_support:
                    required_ui.append(descriptor.consumer)
                generated.append(
                    {
                        "clause_id": clause.clause_id,
                        "operator": effect.operator,
                        "parameters": effect.parameters,
                        "trigger": clause.trigger,
                        "activation": clause.activation,
                        "action_economy": clause.action_economy,
                        "targeting": clause.targeting.to_dict() if clause.targeting else None,
                        "capability_id": descriptor.capability_id,
                        "contract_version": descriptor.contract_version,
                        "materializer_id": descriptor.materializer_id,
                    }
                )

            clause_status = "full" if not clause_blockers and not clause_manual else "partial"
            clause_results.append(
                ClauseCompileResult(
                    clause_id=clause.clause_id,
                    status=clause_status,
                    capability_ids=_unique(clause_capabilities),
                    generated_block=(
                        generated[-1] if clause_status == "full" and generated else None
                    ),
                    blockers=_unique((*clause_blockers, clause_manual)),
                )
            )

        statuses = {item.status for item in clause_results}
        if schema_blockers:
            compile_status = "invalid"
        elif manual_boundaries:
            compile_status = "manual"
        elif dependency_blockers or statuses != {"full"}:
            compile_status = "partial"
        else:
            compile_status = "full"

        evidence = list(_unique(evidence))
        required_persistence = list(_unique(required_persistence))
        required_ui = list(_unique(required_ui))
        required_tests = list(_unique(evidence))
        blockers = (
            *dependency_blockers,
            *unsupported_operators,
            *unsupported_conditions,
            *unsupported_combinations,
            *manual_boundaries,
        )
        if compile_status == "full" and not evidence:
            compile_status = "partial"
            blockers = (*blockers, "no production evidence")
        blockers = _unique((*blockers, *schema_blockers))
        result_without_fingerprint = {
            "feature_id": spec.feature_id,
            "compile_status": compile_status,
            "clause_results": [item.to_dict() for item in clause_results],
            "generated_runtime_blocks": generated,
            "required_inputs": required_inputs,
            "required_persistence": required_persistence,
            "required_ui": required_ui,
            "required_tests": required_tests,
            "dependencies": list(spec.dependencies),
            "unsupported_operators": list(_unique(unsupported_operators)),
            "unsupported_conditions": list(_unique(unsupported_conditions)),
            "unsupported_combinations": list(_unique(unsupported_combinations)),
            "manual_boundaries": list(_unique(manual_boundaries)),
            "evidence": evidence,
            "source_trust": spec.source_trust,
            "blockers": list(_unique(blockers)),
            "status_authority": self.status_authority,
            "legacy_adapter_used": legacy_adapter_used,
        }
        fingerprint = hashlib.sha256(
            canonical_json(result_without_fingerprint).encode("utf-8")
        ).hexdigest()
        return CompileResult(
            feature_id=spec.feature_id,
            compile_status=compile_status,
            clause_results=tuple(clause_results),
            generated_runtime_blocks=tuple(generated),
            required_inputs=tuple(required_inputs),
            required_persistence=tuple(required_persistence),
            required_ui=tuple(required_ui),
            required_tests=tuple(required_tests),
            dependencies=spec.dependencies,
            unsupported_operators=_unique(unsupported_operators),
            unsupported_conditions=_unique(unsupported_conditions),
            unsupported_combinations=_unique(unsupported_combinations),
            manual_boundaries=_unique(manual_boundaries),
            evidence=tuple(evidence),
            source_trust=spec.source_trust,
            blockers=_unique(blockers),
            status_authority=self.status_authority,
            legacy_adapter_used=legacy_adapter_used,
            fingerprint=fingerprint,
        )


_LEGACY_SECTION_OPERATORS = {
    "proficiencies": "grant_proficiency",
    "advancement": "grant_spell",
    "resources": "restore_resource",
    "combat_modifiers": "add_modifier",
    "combat_defenses": "grant_resistance",
    "movement_modes": "grant_movement_mode",
    "actions": "create_timed_modifier",
    "triggers": "create_timed_modifier",
    "attack_riders": "add_damage",
    "spellcasting": "grant_spell",
    "prepared_spell_list": "prepare_spell",
    "attack_action_count": "add_modifier",
}


def legacy_feature_spec_from_audit_row(row: Mapping[str, Any]) -> tuple[FeatureSpec, bool]:
    """Adapt one existing audit row into shadow IR without changing its status.

    This is intentionally a conservative bridge: unknown runtime sections are
    represented as unsupported clauses, never guessed into a generic effect.
    The resulting spec is used for parity reports and pilot authority only.
    """

    feature_name = str(row.get("feature_name") or "").strip()
    scope = str(row.get("scope") or "unknown")
    level = row.get("level")
    source_record_id = str(row.get("source_record_id") or f"{scope}:{feature_name}:{level}")
    sections = [str(item) for item in row.get("runtime_sections") or ()]
    clauses: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        operator = _LEGACY_SECTION_OPERATORS.get(section)
        effect = (
            {
                "operator": operator,
                "parameters": {"legacy_section": section},
            }
            if operator
            else {
                "operator": f"legacy_unsupported:{section}",
                "parameters": {"legacy_section": section},
            }
        )
        clauses.append(
            {
                "clause_id": f"legacy:{section}:{index}",
                "trigger": "advancement_confirmed",
                "conditions": [],
                "activation": "automatic",
                "action_economy": "none",
                "resource_costs": [],
                "resource_recovery": [],
                "required_inputs": [],
                "targeting": {"kind": "self", "parameters": {}},
                "effects": [effect],
                "duration": "advancement_persistent",
                "expiry": None,
                "stacking": None,
                "frequency": None,
                "persistence": "character.feature_runtime",
                "visibility": "owner",
                "audit": {"legacy_section": section},
            }
        )
    if not clauses:
        clauses = [
            {
                "clause_id": "legacy:no_runtime_section",
                "trigger": "advancement_confirmed",
                "conditions": [],
                "activation": "automatic",
                "action_economy": "none",
                "resource_costs": [],
                "resource_recovery": [],
                "required_inputs": [],
                "targeting": {"kind": "self", "parameters": {}},
                "effects": [
                    {
                        "operator": "legacy_unsupported:no_runtime_section",
                        "parameters": {},
                    }
                ],
                "duration": "advancement_persistent",
                "expiry": None,
                "stacking": None,
                "frequency": None,
                "persistence": "character.feature_runtime",
                "visibility": "owner",
                "audit": {"legacy_adapter": True},
            }
        ]
    spec = FeatureSpec.from_dict(
        {
            "schema_version": "feature-ir-1",
            "feature_id": f"legacy:{scope}:{source_record_id}:{level}:{feature_name}",
            "namespace": "legacy.local",
            "pack_id": "legacy-local-rules",
            "pack_version": "2026-08-09",
            "ruleset_version": "2024",
            "source_record_id": source_record_id,
            "source_name": feature_name,
            "localized_names": {"zh-CN": feature_name},
            "class_name": row.get("class_name"),
            "subclass_name": row.get("subclass_name"),
            "level": level,
            "source_completeness": (
                "complete" if row.get("source_parse") == "description_located" else "incomplete"
            ),
            "clauses": clauses,
            "dependencies": [],
            "compatibility": {"legacy_runtime_sections": sections},
        },
        path="legacy_feature",
    )
    return spec, True


def compile_feature_spec(
    spec: FeatureSpec,
    *,
    catalog: CapabilityCatalog | None = None,
    available_feature_ids: Iterable[str] = (),
) -> CompileResult:
    return FeatureCompiler(
        catalog,
        available_feature_ids=available_feature_ids,
    ).compile(spec)


_RUNTIME_SECTION_BY_OPERATOR = {
    "grant_proficiency": "proficiencies",
    "grant_language": "proficiencies",
    "grant_spell": "advancement",
    "prepare_spell": "prepared_spell_list",
    "restore_resource": "resources",
    "set_resource_profile": "resources",
    "consume_resource": "resources",
    "exchange_resource": "resources",
    "add_modifier": "combat_modifiers",
    "set_modifier": "combat_modifiers",
    "impose_advantage": "combat_modifiers",
    "impose_disadvantage": "combat_modifiers",
    "grant_movement_mode": "movement_modes",
    "teleport": "actions",
    "grant_sight_mode": "combat_modifiers",
    "heal": "actions",
    "grant_temporary_hp": "triggers",
    "add_damage": "attack_riders",
    "replace_damage_type": "combat_modifiers",
    "grant_resistance": "combat_defenses",
    "grant_saving_throw_advantage": "combat_defenses",
    "grant_immunity": "combat_defenses",
    "activate_condition": "actions",
    "remove_condition": "triggers",
    "create_timed_modifier": "actions",
    "create_reaction_window": "triggers",
    "create_triggered_attack_window": "triggers",
}


def materialize_runtime_definition(
    spec: FeatureSpec,
    result: CompileResult,
    *,
    catalog: CapabilityCatalog | None = None,
    materializers: MaterializerRegistry | None = None,
) -> dict[str, Any]:
    """Turn a full compile result into existing typed runtime sections.

    This adapter only assembles canonical blocks.  The actual advancement,
    combat, rest and spell consumers remain the sources of truth.  A partial
    result is rejected so callers cannot accidentally expose an incomplete
    feature as a runtime action.
    """

    if result.feature_id != spec.feature_id:
        raise ValueError("compile result does not belong to feature spec")
    if result.compile_status != "full":
        raise ValueError("only a full compile result can be materialized")
    capability_catalog = catalog or default_capability_catalog()
    materializer_registry = materializers or default_materializer_registry()
    clauses = {clause.clause_id: clause for clause in spec.clauses}
    explicit_clause_effects: dict[str, list[dict[str, Any]]] = {}
    for clause in spec.clauses:
        if clause.trigger != "explicit_activation":
            continue
        explicit_clause_effects[clause.clause_id] = [
            dict(effect.to_dict()) for effect in clause.effects
        ]
    definition: dict[str, Any] = {
        "combat_start": {"modifiers": [], "defenses": [], "movement_modes": []},
        "spell_context": [],
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "proficiencies": [],
        "advancement": None,
        "prepared_spell_list": None,
        "entity_lifecycles": [],
        "spell_origins": [],
    }
    for index, block in enumerate(result.generated_runtime_blocks):
        operator = str(block.get("operator") or "")
        capability_id = str(block.get("capability_id") or "")
        descriptor = capability_catalog.get(capability_id)
        if descriptor is None:
            raise ValueError(f"unknown capability in compile result: {capability_id}")
        clause_id = str(block.get("clause_id") or "")
        clause = clauses.get(clause_id)
        if clause is None:
            raise ValueError(f"compile result references unknown clause: {clause_id}")
        materialized = materializer_registry.materialize(
            spec=spec,
            clause=clause,
            operator=operator,
            parameters=block.get("parameters") or {},
            descriptor=descriptor,
            index=index,
        )
        section = materialized.section
        entry = materialized.entry
        clause_effects = explicit_clause_effects.get(clause_id, [])
        consume_effect = next(
            (
                dict(effect.get("parameters") or {})
                for effect in clause_effects
                if effect.get("operator") == "consume_resource"
            ),
            None,
        )
        if (
            operator in {"heal", "grant_temporary_hp", "teleport"}
            and clause.trigger == "explicit_activation"
        ):
            # These operators are ordinary production feature actions.  The
            # generic combat consumer needs the same action envelope as an
            # older hand-authored feature, while the formula/target/resource
            # remain data carried by the materialized block.
            entry["kind"] = "feature_action"
            entry["target"] = str(clause.targeting.kind if clause.targeting else "self")
            if operator == "teleport":
                entry["resolution_kind"] = "teleport"
                entry["target_policy"] = {"mode": "self"}
            else:
                entry["resolution_kind"] = (
                    "temporary_healing" if operator == "grant_temporary_hp" else "healing"
                )
                entry["healing"] = str(
                    entry.get("formula")
                    or entry.get("healing")
                    or entry.get("healing_formula")
                    or ""
                )
            if consume_effect:
                entry["resource_key"] = str(consume_effect.get("resource_key") or "")
                entry["resource_cost"] = int(consume_effect.get("amount") or 1)
            section = "actions"
        if section == "combat_modifiers":
            definition["combat_start"]["modifiers"].append(entry)
        elif section == "spell_context":
            definition["spell_context"].append(entry)
        elif section == "combat_defenses":
            definition["combat_start"]["defenses"].append(entry)
            if operator == "zero_hp_intervention":
                resource_key = str(entry.get("resource_key") or "")
                if resource_key:
                    definition["resources"][resource_key] = {
                        "key": resource_key,
                        "label": spec.source_name,
                        "max": 1,
                        "recovery": entry.get("reset", "long_rest"),
                        "recovery_events": [
                            {
                                "rest": entry.get("reset", "long_rest"),
                                "operation": "set_to_max",
                            }
                        ],
                        "automation_status": "full",
                        "requires_dm_adjudication": False,
                    }
        elif section == "movement_modes":
            # Keep the typed block in the passive registry as well as the
            # explicit action. Its ``applies_when`` predicate prevents a
            # premature grant, while the action handles temporary activation.
            definition["combat_start"]["movement_modes"].append(entry)
            if clause.trigger == "explicit_activation":
                # An explicitly activated movement clause is an action, not a
                # passive combat-start grant. The same typed movement block is
                # carried by the action so the combat consumer can persist its
                # duration and CAS transition.
                action_id = f"{spec.feature_id}:activate:{clause.clause_id}"
                consume_effect = next(
                    (
                        dict(effect.to_dict()).get("parameters") or {}
                        for effect in clause.effects
                        if effect.operator == "consume_resource"
                    ),
                    None,
                )
                consume_key = (
                    str(consume_effect.get("resource_key") or "").strip()
                    if isinstance(consume_effect, dict)
                    else ""
                )
                action = next(
                    (
                        candidate
                        for candidate in definition["actions"].values()
                        if isinstance(candidate, dict)
                        and consume_key
                        and str(candidate.get("resource_key") or "").strip() == consume_key
                    ),
                    None,
                )
                if not isinstance(action, dict):
                    action = definition["actions"].get(spec.feature_id)
                if not isinstance(action, dict):
                    action = {
                        "id": action_id,
                        "feature_id": spec.feature_id,
                        "feature_name": spec.source_name,
                        "name": spec.source_name,
                        "kind": "feature_action",
                        "action_cost": clause.action_economy,
                        "target": "self",
                        "target_policy": {"mode": "self"},
                        "resolution_kind": "movement_mode_activation",
                        "effects": [],
                        "automation_status": "full",
                        "requires_dm_adjudication": False,
                        "runtime_execution": {
                            "status": "ready",
                            "consumer": "combat_feature_action",
                            "contract_version": "feature-action-movement-mode-1",
                        },
                    }
                    definition["actions"][spec.feature_id] = action
                action["effects"].append(
                    {
                        "kind": "activate_movement_mode",
                        "mode": entry.get("mode"),
                        "speed_source": entry.get("speed_source"),
                        "speed_ft": entry.get("speed_ft"),
                        "speed_multiplier": entry.get("speed_multiplier"),
                        "applies_when": entry.get("applies_when"),
                        "duration": clause.duration,
                    }
                )
                if isinstance(consume_effect, dict) and consume_effect.get("resource_key"):
                    action["resource_key"] = str(consume_effect["resource_key"])
                    action["resource_cost"] = int(consume_effect.get("amount") or 1)
        elif section == "actions":
            if operator == "activate_condition" and clause_id in explicit_clause_effects:
                entry["kind"] = "feature_action"
                entry["target"] = str(
                    clause.targeting.kind if clause.targeting is not None else "self"
                )
                consume = next(
                    (
                        effect.get("parameters", {})
                        for effect in explicit_clause_effects[clause_id]
                        if effect.get("operator") == "consume_resource"
                    ),
                    None,
                )
                if consume:
                    entry["resource_key"] = str(consume.get("resource_key") or "")
                    entry["resource_cost"] = int(consume.get("amount") or 1)
                effects: list[dict[str, Any]] = []
                for effect in explicit_clause_effects[clause_id]:
                    params = dict(effect.get("parameters") or {})
                    operator = str(effect.get("operator") or "")
                    if operator == "activate_condition":
                        effects.append(
                            {
                                "kind": "activate_duration_condition",
                                "condition": str(params.get("condition") or ""),
                                "duration_unit": "minutes",
                                "duration_value": 1,
                            }
                        )
                if effects:
                    entry["effects"] = effects
            definition["actions"][str(entry["id"])] = entry
        elif section == "triggers" and operator in {"heal", "grant_temporary_hp"}:
            # Non-explicit trigger blocks stay trigger blocks.  Explicit
            # healing/temp-HP blocks were promoted above so player/DM
            # activation goes through the production feature-action endpoint.
            definition["triggers"].append(entry)
        elif section in {"proficiencies", "triggers", "attack_riders"}:
            target = definition[section]
            if isinstance(target, list):
                target.append(entry)
        elif section == "resources":
            definition["resources"][str(entry.get("key") or entry["id"])] = entry
        elif section == "entity_lifecycles":
            definition["entity_lifecycles"].append(entry)
        elif section == "spell_origins":
            definition["spell_origins"].append(entry)
        elif section == "advancement":
            existing = definition["advancement"]
            if existing is None:
                definition["advancement"] = entry
                continue
            # A single feature may grant several spells (or several grants
            # with distinct free-cast resources).  Keep one canonical
            # advancement envelope for the existing character consumer while
            # preserving each materialized grant's metadata for resolution.
            merged = dict(existing)
            existing_spells = [str(item) for item in existing.get("spells", [])]
            new_spells = [str(item) for item in entry.get("spells", [])]
            merged["spells"] = list(dict.fromkeys((*existing_spells, *new_spells)))
            existing_grants = existing.get("spell_grants")
            if not isinstance(existing_grants, list):
                existing_grants = [dict(existing)]
            new_grants = entry.get("spell_grants")
            if isinstance(new_grants, list):
                existing_grants.extend(
                    dict(item) for item in new_grants if isinstance(item, Mapping)
                )
            else:
                existing_grants.append(dict(entry))
            merged["spell_grants"] = existing_grants
            for key in (
                "grant_class",
                "source_class",
                "casting_ability",
                "grant_mode",
                "ritual_only",
                "free_cast_resource_key",
                "auto_save",
            ):
                if existing.get(key) != entry.get(key):
                    merged.pop(key, None)
            definition["advancement"] = merged
        elif section == "prepared_spell_list":
            existing = definition["prepared_spell_list"]
            if existing is None:
                definition["prepared_spell_list"] = entry
                continue
            merged = dict(existing)
            existing_spells = [str(item) for item in existing.get("spells", [])]
            new_spells = [str(item) for item in entry.get("spells", [])]
            merged["spells"] = list(dict.fromkeys((*existing_spells, *new_spells)))
            existing_grants = existing.get("spell_grants")
            if not isinstance(existing_grants, list):
                existing_grants = [dict(existing)]
            new_grants = entry.get("spell_grants")
            if isinstance(new_grants, list):
                existing_grants.extend(
                    dict(item) for item in new_grants if isinstance(item, Mapping)
                )
            else:
                existing_grants.append(dict(entry))
            merged["spell_grants"] = existing_grants
            for key in ("source_class", "preparation_mode"):
                if existing.get(key) != entry.get(key):
                    merged.pop(key, None)
            definition["prepared_spell_list"] = merged

    # Event-window and resource-exchange clauses are actions even when their
    # source contract is represented by a trigger/resource block.  Project
    # them into one generic action envelope so the combat service can consume
    # the typed window without interpreting a feature name.
    for clause in spec.clauses:
        if clause.trigger == "advancement_confirmed":
            continue
        effects = [dict(effect.to_dict()) for effect in clause.effects]
        consume = next(
            (
                dict(effect.get("parameters") or {})
                for effect in effects
                if effect.get("operator") == "consume_resource"
            ),
            None,
        )
        window_effect = next(
            (
                effect
                for effect in effects
                if effect.get("operator")
                in {"create_reaction_window", "create_triggered_attack_window"}
            ),
            None,
        )
        exchange_effect = next(
            (
                dict(effect.get("parameters") or {})
                for effect in effects
                if effect.get("operator") == "exchange_resource"
            ),
            None,
        )
        if window_effect is not None:
            operator = str(window_effect.get("operator") or "")
            parameters = dict(window_effect.get("parameters") or {})
            raw_policy = parameters.get("target_policy")
            raw_policy = dict(raw_policy) if isinstance(raw_policy, Mapping) else {}
            if operator == "create_triggered_attack_window":
                target_mode = "enemy"
                policy_mode = str(raw_policy.get("mode") or "enemy")
                if policy_mode in {"triggering_enemy", "chosen_enemy"}:
                    policy_mode = "enemy"
                attack_profile = dict(parameters.get("attack_profile") or {})
                attack_profile.setdefault("mode", "weapon_only")
                window_spec = {
                    "window_type": "triggered_attack_window",
                    "window_kind": str(parameters.get("window_kind") or "typed_attack"),
                    "event": clause.trigger,
                    "expires": clause.duration,
                    "action_cost": str(parameters.get("reaction_type") or clause.action_economy),
                    "target_policy": {**raw_policy, "mode": policy_mode},
                    "attack_profile": attack_profile,
                    "parent_action": parameters.get("parent_action"),
                }
                resolution_kind = "triggered_attack_window"
            else:
                target_mode = "ally_or_self"
                window_spec = {
                    "window_type": "reaction_window",
                    "window_kind": str(parameters.get("window_kind") or "typed_reaction"),
                    "event": clause.trigger,
                    "expires": clause.duration,
                    "action_cost": str(clause.action_economy or "reaction"),
                    "target_policy": raw_policy,
                }
                resolution_kind = "reaction_window"
            action = {
                "id": f"{spec.feature_id}:activate:{clause.clause_id}",
                "feature_id": spec.feature_id,
                "feature_name": spec.source_name,
                "name": spec.source_name,
                "class_name": spec.class_name or "unclassified",
                "class_level": spec.level or 0,
                "kind": "feature_action",
                "operator": operator,
                "clause_id": clause.clause_id,
                "trigger": clause.trigger,
                "action_cost": window_spec["action_cost"],
                "target": target_mode,
                "target_policy": {
                    "mode": target_mode,
                    "typed_policy": window_spec["target_policy"],
                },
                "resolution_kind": resolution_kind,
                "window_spec": window_spec,
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_event_window",
                    "contract_version": "feature-event-window-1",
                    "persistence": "combat_actions",
                },
            }
            if isinstance(consume, dict) and consume.get("resource_key"):
                action["resource_key"] = str(consume["resource_key"])
                action["resource_cost"] = int(consume.get("amount") or 1)
            definition["actions"][spec.feature_id] = action
        elif exchange_effect is not None:
            action = {
                "id": f"{spec.feature_id}:activate:{clause.clause_id}",
                "feature_id": spec.feature_id,
                "feature_name": spec.source_name,
                "name": spec.source_name,
                "class_name": spec.class_name or "unclassified",
                "class_level": spec.level or 0,
                "kind": "feature_action",
                "operator": "exchange_resource",
                "clause_id": clause.clause_id,
                "trigger": clause.trigger,
                "action_cost": clause.action_economy,
                "target": "self",
                "target_policy": {"mode": "self"},
                "resolution_kind": "resource_exchange",
                "resource_exchange": exchange_effect,
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_resource_exchange",
                    "contract_version": "feature-resource-exchange-1",
                    "persistence": "character.resources",
                },
            }
            definition["actions"][spec.feature_id] = action
    definition.setdefault("automation_status", "full")
    definition.setdefault("requires_dm_adjudication", False)
    return definition
