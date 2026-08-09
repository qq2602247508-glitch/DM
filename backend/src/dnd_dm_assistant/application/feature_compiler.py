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
    catalog: CapabilityCatalog,
) -> tuple[CapabilityDescriptor | None, tuple[str, ...]]:
    candidates = catalog.get_for_operator(operator)
    if not candidates:
        return None, (f"unsupported operator: {operator}",)
    conditions = tuple(item.kind for item in clause.conditions)
    inputs = tuple(item.kind for item in clause.required_inputs)
    target = clause.targeting.kind if clause.targeting else None
    duration = _duration_kind(clause.duration)
    resource_operations = tuple(
        item.operation for item in (*clause.resource_costs, *clause.resource_recovery)
    )
    partial_errors: list[str] = []
    for descriptor in candidates:
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
    ) -> None:
        self.catalog = catalog or default_capability_catalog()
        self.available_feature_ids = frozenset(str(item) for item in available_feature_ids)
        if status_authority not in {"compiler", "legacy"}:
            raise ValueError("status_authority must be compiler or legacy")
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

        if self.available_feature_ids:
            for dependency in spec.dependencies:
                if dependency not in self.available_feature_ids:
                    dependency_blockers.append(f"missing dependency: {dependency}")

        if spec.source_completeness == "unstructured":
            manual_boundaries.append("source is unstructured")
        elif spec.source_completeness == "incomplete":
            dependency_blockers.append("source is incomplete")

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
                descriptor, errors = _compile_effect(clause, effect.operator, self.catalog)
                if descriptor is None:
                    clause_blockers.extend(errors)
                    if any(item.startswith("unsupported operator:") for item in errors):
                        unsupported_operators.append(effect.operator)
                    if any("condition " in item for item in errors):
                        unsupported_conditions.extend(
                            f"{clause.clause_id}: {condition.kind}"
                            for condition in clause.conditions
                        )
                    if any("unsupported" in item for item in errors):
                        unsupported_combinations.extend(
                            f"{clause.clause_id}: {effect.operator}"
                        )
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
                    }
                )

            clause_status = "full" if not clause_blockers and not clause_manual else "partial"
            clause_results.append(
                ClauseCompileResult(
                    clause_id=clause.clause_id,
                    status=clause_status,
                    capability_ids=_unique(clause_capabilities),
                    generated_block=(
                        generated[-1]
                        if clause_status == "full" and generated
                        else None
                    ),
                    blockers=_unique((*clause_blockers, clause_manual)),
                )
            )

        statuses = {item.status for item in clause_results}
        if manual_boundaries:
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
            "status_authority": self.status_authority,
            "legacy_adapter_used": legacy_adapter_used,
            "blockers": list(_unique(blockers)),
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
    "consume_resource": "resources",
    "exchange_resource": "resources",
    "add_modifier": "combat_modifiers",
    "set_modifier": "combat_modifiers",
    "impose_advantage": "combat_modifiers",
    "impose_disadvantage": "combat_modifiers",
    "grant_movement_mode": "movement_modes",
    "grant_sight_mode": "combat_modifiers",
    "heal": "actions",
    "grant_temporary_hp": "triggers",
    "add_damage": "attack_riders",
    "replace_damage_type": "combat_modifiers",
    "grant_resistance": "combat_defenses",
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
    definition: dict[str, Any] = {
        "combat_start": {"modifiers": [], "defenses": [], "movement_modes": []},
        "resources": {},
        "actions": {},
        "triggers": [],
        "attack_riders": [],
        "proficiencies": [],
        "advancement": None,
        "prepared_spell_list": None,
    }
    for index, block in enumerate(result.generated_runtime_blocks):
        operator = str(block.get("operator") or "")
        section = _RUNTIME_SECTION_BY_OPERATOR.get(operator)
        if section is None:
            raise ValueError(f"no runtime section mapping for operator {operator}")
        capability_id = str(block.get("capability_id") or "")
        descriptor = capability_catalog.get(capability_id)
        if descriptor is None:
            raise ValueError(f"unknown capability in compile result: {capability_id}")
        entry = {
            "id": f"{spec.feature_id}:{block.get('clause_id')}:{index}",
            "feature_id": spec.feature_id,
            "feature_name": spec.source_name,
            "class_name": spec.class_name or "unclassified",
            "class_level": spec.level or 0,
            "kind": operator,
            "operator": operator,
            "trigger": block.get("trigger"),
            "action_cost": block.get("action_economy", "none"),
            "targeting": block.get("targeting"),
            "parameters": block.get("parameters") or {},
            "runtime_execution": {
                "status": "ready",
                "consumer": descriptor.consumer,
                "capability_id": capability_id,
                "contract_version": descriptor.contract_version,
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
        if section == "combat_modifiers":
            definition["combat_start"]["modifiers"].append(entry)
        elif section == "combat_defenses":
            definition["combat_start"]["defenses"].append(entry)
        elif section == "movement_modes":
            definition["combat_start"]["movement_modes"].append(entry)
        elif section in {"proficiencies", "triggers", "attack_riders", "actions"}:
            target = definition[section]
            if isinstance(target, list):
                target.append(entry)
        elif section == "resources":
            definition["resources"][entry["id"]] = entry
        elif section == "advancement":
            definition["advancement"] = entry
        elif section == "prepared_spell_list":
            definition["prepared_spell_list"] = entry
    return definition
