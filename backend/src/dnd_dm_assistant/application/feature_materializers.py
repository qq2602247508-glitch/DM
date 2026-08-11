"""Materializer registry for Feature IR runtime contracts.

The compiler decides whether a clause is satisfiable.  This module decides how
that already-validated clause is projected into the typed sections consumed by
the existing advancement, rest, spell and combat code.  Materializers are
registered by operator/capability contract, never by feature name.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from dnd_dm_assistant.domain.feature_capabilities import CapabilityDescriptor
from dnd_dm_assistant.domain.feature_ir import ClauseSpec, FeatureSpec


class MaterializerError(ValueError):
    """Raised when a validated clause cannot be projected safely."""


@dataclass(frozen=True)
class MaterializedBlock:
    section: str
    entry: dict[str, Any]


@dataclass(frozen=True)
class MaterializerContext:
    spec: FeatureSpec
    clause: ClauseSpec
    operator: str
    parameters: Mapping[str, Any]
    descriptor: CapabilityDescriptor
    index: int

    @property
    def block_id(self) -> str:
        explicit = self.parameters.get("id")
        return (
            str(explicit)
            if isinstance(explicit, str) and explicit.strip()
            else (f"{self.spec.feature_id}:{self.clause.clause_id}:{self.index}")
        )

    def base(self, *, kind: str | None = None) -> dict[str, Any]:
        return {
            "id": self.block_id,
            "feature_id": self.spec.feature_id,
            "clause_id": self.clause.clause_id,
            "source_record_id": self.spec.source_record_id,
            "feature_name": self.spec.source_name,
            "class_name": self.spec.class_name or "unclassified",
            "class_level": self.spec.level or 0,
            "kind": kind or self.operator,
            "operator": self.operator,
            "trigger": self.clause.trigger,
            "activation": self.clause.activation,
            "action_cost": self.clause.action_economy,
            "targeting": (
                self.clause.targeting.to_dict() if self.clause.targeting is not None else None
            ),
            "runtime_execution": {
                "status": "ready",
                "consumer": self.descriptor.consumer,
                "capability_id": self.descriptor.capability_id,
                "contract_version": self.descriptor.contract_version,
                "materializer_id": self.descriptor.materializer_id,
                "persistence": self.descriptor.persisted_state,
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }


Materializer = Callable[[MaterializerContext], MaterializedBlock]


def _with_parameters(context: MaterializerContext, *, kind: str | None = None) -> dict[str, Any]:
    entry = context.base(kind=kind)
    entry.update(dict(context.parameters))
    entry["operator"] = context.operator
    entry["runtime_execution"] = context.base()["runtime_execution"]
    entry["automation_status"] = "full"
    entry["requires_dm_adjudication"] = False
    return entry


def _materialize_proficiency(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    proficiency_kind = str(params["proficiency_kind"])
    if proficiency_kind == "language_choice" or proficiency_kind.endswith("_choice"):
        choice_input = next(
            (
                item
                for item in context.clause.required_inputs
                if item.kind == "choice"
            ),
            None,
        )
        choice_key = choice_input.key if choice_input is not None else f"{proficiency_kind}_input"
        choice_parameters = dict(choice_input.parameters) if choice_input is not None else {}
        entry = context.base(
            kind="selected_language_grant"
            if proficiency_kind == "language_choice"
            else "selected_proficiency_grant"
        )
        entry["choice_requirement"] = {
            "key": choice_key,
            "minimum": 1,
            "maximum": 1,
            "strict": True,
            "options_source": str(params["asset_id"]),
            "duplicate_policy": str(choice_parameters.get("duplicate_policy") or "forbid"),
            "requires_dm_selection": bool(choice_parameters.get("requires_dm_selection")),
        }
        entry["proficiency_kind"] = proficiency_kind
        return MaterializedBlock("advancement", entry)
    entry = context.base(kind=str(params["proficiency_kind"]))
    entry.update(
        {
            "name": str(params["asset_id"]),
            "asset_id": str(params["asset_id"]),
            "operation": str(params["operation"]),
        }
    )
    if params.get("if_already_proficient"):
        entry["if_already_proficient"] = str(params["if_already_proficient"])
        choice_input = next(
            (
                item
                for item in context.clause.required_inputs
                if item.kind == "choice"
            ),
            None,
        )
        if choice_input is not None:
            entry["replacement_choice"] = {
                "key": choice_input.key,
                "options_source": str(
                    choice_input.parameters.get("options_source") or "proficiency_options"
                ),
                "duplicate_policy": str(
                    choice_input.parameters.get("duplicate_policy") or "forbid"
                ),
            }
    return MaterializedBlock("proficiencies", entry)


def _materialize_language(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    entry = context.base(kind="language")
    entry.update(
        {
            "name": f"语言：{params['language_id']}",
            "language_id": str(params["language_id"]),
            "operation": str(params["operation"]),
        }
    )
    return MaterializedBlock("proficiencies", entry)


def _materialize_spell(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    entry = context.base(kind="fixed_spell_grant")
    entry.update(
        {
            "spells": [str(params["spell_id"])],
            "grant_class": str(params["source_class"]),
            "casting_ability": str(params["casting_ability"]),
            "grant_mode": str(params["grant_mode"]),
        }
    )
    for key in ("ritual_only", "free_cast_resource_key", "auto_save"):
        if key in params:
            entry[key] = params[key]
    return MaterializedBlock("advancement", entry)


def _materialize_prepare_spell(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    entry = context.base(kind="always_prepared_spell_list")
    entry.update(
        {
            "spells": [str(params["spell_id"])],
            "source_class": str(params["source_class"]),
            "preparation_mode": str(params.get("preparation_mode", "prepared")),
        }
    )
    return MaterializedBlock("prepared_spell_list", entry)


def _materialize_resource(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    entry = context.base(kind="resource_lifecycle")
    entry.update(
        {
            "key": str(params["resource_key"]),
            "operation": str(params["operation"]),
            "recovery": context.clause.trigger,
        }
    )
    for key in ("amount", "amount_source", "recovery_event"):
        if key in params:
            entry[key] = params[key]
    if context.clause.trigger in {"long_rest_completed", "long_rest_started"}:
        entry["recovery_events"] = [{"rest": "long_rest", "operation": params["operation"]}]
    elif context.clause.trigger in {"short_rest_completed", "short_rest_started"}:
        entry["recovery_events"] = [{"rest": "short_rest", "operation": params["operation"]}]
    return MaterializedBlock("resources", entry)


def _materialize_resource_profile(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    entry = context.base(kind="resource_profile")
    entry.update(
        {
            "key": str(params["resource_key"]),
            "resource_kind": str(params["resource_kind"]),
            "die_size": int(params["die_size"]),
            "recovery": "both",
            "recovery_events": [
                {"rest": "short_rest", "operation": "set_to_max"},
                {"rest": "long_rest", "operation": "set_to_max"},
            ],
        }
    )
    if "max_formula" in params:
        entry["max_formula"] = str(params["max_formula"])
    if "recovery_events" in params:
        recovery_events = params["recovery_events"]
        if not isinstance(recovery_events, list) or not recovery_events:
            raise MaterializerError("resource profile recovery_events must be a non-empty array")
        entry["recovery_events"] = [dict(item) for item in recovery_events]
        entry["recovery"] = "custom"
    return MaterializedBlock("resources", entry)


def _materialize_exchange(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    entry = context.base(kind="resource_exchange")
    entry.update(
        {
            "key": str(params["from_resource_key"]),
            "from_resource_key": str(params["from_resource_key"]),
            "to_resource_key": str(params["to_resource_key"]),
            "operation": str(params["operation"]),
            "recovery_events": [],
        }
    )
    for key in ("amount", "amount_source"):
        if key in params:
            entry[key] = params[key]
    return MaterializedBlock("resources", entry)


def _materialize_roll_intervention(context: MaterializerContext) -> MaterializedBlock:
    """Project a typed superiority-die modifier into the shared d20 window."""

    params = context.parameters
    if context.clause.trigger not in {"ability_check", "attack_declared"}:
        raise MaterializerError("superiority-die intervention trigger is unsupported")
    if str(params.get("value_source") or "") != "superiority_die":
        raise MaterializerError("roll intervention requires a typed superiority die")
    resource_effects = [
        effect
        for effect in context.clause.effects
        if effect.operator == "consume_resource"
    ]
    if len(resource_effects) != 1:
        raise MaterializerError(
            "roll intervention requires exactly one consume_resource effect"
        )
    resource = resource_effects[0].parameters
    resource_key = str(resource.get("resource_key") or "").strip()
    resource_cost = resource.get("amount")
    if not resource_key or not isinstance(resource_cost, int) or resource_cost < 1:
        raise MaterializerError("roll intervention resource cost is invalid")

    applies_when = str(params.get("applies_when") or "").strip()
    eligibility: dict[str, Any] = {
        "entity_types": ["character"],
        "resource": {
            "key": resource_key,
            "minimum": resource_cost,
            "value_bind_as": "superiority_die_sides",
        },
        "forbidden_conditions": ["incapacitated"],
    }
    if context.clause.trigger == "ability_check":
        eligibility["test_kinds"] = ["ability_check"]
        stat = str(params.get("stat") or "")
        if stat.endswith("_social_check"):
            eligibility["abilities"] = [stat.removesuffix("_social_check")]
        elif stat != "ability_check":
            raise MaterializerError(
                "ability-check intervention stat is not a typed ability check"
            )
        skills = [item for item in applies_when.split("_or_") if item]
        if not skills:
            raise MaterializerError("ability-check intervention lacks typed skills")
        eligibility["skills"] = skills
    else:
        if applies_when != "weapon_attack":
            raise MaterializerError("attack intervention lacks weapon_attack binding")
        eligibility["test_kinds"] = ["armor_class"]
        eligibility["attack_types"] = ["weapon_attack"]

    entry = context.base(kind="roll_intervention")
    entry.update(
        {
            "name": context.spec.source_name,
            "trigger": "after_d20_test",
            "source_trigger": context.clause.trigger,
            "operation": {
                "kind": "add_die",
                "input_key": "superiority_die_roll",
                "die_sides_expression": "superiority_die_sides",
            },
            "eligibility": eligibility,
            "input_requirements": [
                {"key": "superiority_die_roll", "kind": "integer"}
            ],
            "window": {"phase": "after_d20_test", "expires": "operation"},
            "action_cost": "none",
            "resource": {"key": resource_key, "cost": resource_cost},
            "idempotency": {"prefix": "typed-roll-intervention"},
            "runtime_execution": {
                "status": "ready",
                "consumer": "player_roll_resolution",
                "capability_id": "feature.roll_intervention",
                "contract_version": "feature-roll-intervention-1",
                "materializer_id": "modifier.passive",
                "persistence": "character_resource_and_operation_transaction",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
    )
    return MaterializedBlock("actions", entry)


def _materialize_modifier(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    if (
        context.operator == "add_modifier"
        and params.get("value_source") == "superiority_die"
        and (
            (
                context.clause.trigger == "ability_check"
                and params.get("stat") == "charisma_social_check"
                and str(params.get("applies_when") or "").strip()
                in {"intimidation_or_performance_or_persuasion"}
            )
            or (
                context.clause.trigger == "attack_declared"
                and params.get("stat") == "attack_roll"
                and params.get("applies_when") == "weapon_attack"
            )
        )
    ):
        return _materialize_roll_intervention(context)
    entry = context.base(kind="modifier")
    if context.operator == "replace_damage_type":
        entry.update(
            {
                "stat": "damage_type",
                "operation": "replace",
                "scope": "outgoing",
            }
        )
    for key in (
        "stat",
        "operation",
        "value",
        "value_source",
        "formula",
        "scope",
        "applies_when",
    ):
        if key in params:
            entry[key] = params[key]
    if (
        "value" not in entry
        and "value_source" not in entry
        and context.operator != "replace_damage_type"
    ):
        if context.operator in {"impose_advantage", "impose_disadvantage"}:
            entry["value"] = 1
        else:
            raise MaterializerError(
                f"{context.operator} requires value or value_source in materialized contract"
            )
    return MaterializedBlock("combat_modifiers", entry)


def _materialize_movement(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    if "speed_source" not in params and "speed_ft" not in params:
        raise MaterializerError("grant_movement_mode requires speed_source or speed_ft")
    entry = context.base(kind="movement_mode")
    entry["mode"] = str(params["mode"])
    for key in (
        "speed_source",
        "speed_ft",
        "speed_multiplier",
        "requires_not_wearing_heavy_armor",
        "applies_when",
        "selection_binding",
    ):
        if key in params:
            entry[key] = params[key]
    if entry.get("speed_source") == "fixed_10_feet":
        entry.pop("speed_source", None)
        entry["speed_ft"] = 10
    selection_binding = params.get("selection_binding")
    if isinstance(selection_binding, Mapping):
        choice_key = str(selection_binding.get("choice_key") or "").strip()
        if choice_key:
            entry["selection_resource_key"] = choice_key
            entry["selection_value"] = str(params.get("selection_value") or entry["mode"])
    return MaterializedBlock("movement_modes", entry)


def _materialize_sight(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    if "range_ft" not in params and "range_source" not in params:
        raise MaterializerError("grant_sight_mode requires range_ft or range_source")
    entry = context.base(kind="sight_mode")
    entry["mode"] = str(params["mode"])
    entry["stat"] = f"{params['mode']}_ft"
    entry["operation"] = "set"
    entry["scope"] = "self"
    for key in ("range_ft", "range_source", "applies_when"):
        if key in params:
            entry[key] = params[key]
    return MaterializedBlock("combat_modifiers", entry)


def _materialize_action(context: MaterializerContext) -> MaterializedBlock:
    entry = _with_parameters(context, kind=context.operator)
    return MaterializedBlock("actions", entry)


def _materialize_trigger(context: MaterializerContext) -> MaterializedBlock:
    entry = _with_parameters(context, kind=context.operator)
    if context.operator == "remove_condition" and context.clause.trigger in {
        "short_rest_started",
        "short_rest_completed",
        "long_rest_started",
        "long_rest_completed",
    }:
        rest = (
            "short_rest"
            if context.clause.trigger.startswith("short_rest")
            else "long_rest"
        )
        entry.update(
            {
                "kind": "rest_condition_effect",
                "rest": rest,
                "effect_kind": "reduce_condition_level",
                "amount": 1,
            }
        )
    return MaterializedBlock("triggers", entry)


def _materialize_attack_roll_intervention(
    context: MaterializerContext,
) -> MaterializedBlock:
    params = context.parameters
    modes = params.get("modes")
    if not isinstance(modes, list) or not modes:
        raise MaterializerError("attack roll intervention requires at least one mode")
    normalized_modes = [str(value) for value in modes]
    if any(value not in {"defense", "offense"} for value in normalized_modes):
        raise MaterializerError("attack roll intervention mode is unsupported")
    if len(set(normalized_modes)) != len(normalized_modes):
        raise MaterializerError("attack roll intervention modes must be unique")
    entry = context.base(kind="attack_roll_intervention")
    entry.update(
        {
            "source_die_key": str(params["source_die_key"]),
            "modes": normalized_modes,
            "input_requirements": [
                {
                    "key": "bardic_inspiration_mode",
                    "kind": "enum",
                    "options": normalized_modes,
                },
                {
                    "key": "bardic_inspiration_total",
                    "kind": "die_roll",
                    "die_key": str(params["source_die_key"]),
                },
            ],
        }
    )
    return MaterializedBlock("actions", entry)


def _materialize_authorized_information(
    context: MaterializerContext,
) -> MaterializedBlock:
    params = context.parameters
    information_kind = str(params["information_kind"])
    supported_information = {
        "damage_defenses",
        "telepathic_communication",
        "telepathic_link",
        "telepathic_speech",
        "shared_darkvision",
        "manifest_mind_senses",
    }
    if information_kind not in supported_information:
        raise MaterializerError(
            "authorized target information kind is unsupported"
        )
    target_kind = (
        context.clause.targeting.kind
        if context.clause.targeting is not None
        else "enemy"
    )
    target_parameters = (
        dict(context.clause.targeting.parameters)
        if context.clause.targeting is not None
        else {}
    )
    entry = context.base(kind="feature_action")
    entry.update(
        {
            "action_cost": context.clause.action_economy,
            "target": target_kind,
            "target_policy": {
                "mode": target_kind,
                **target_parameters,
            },
            "availability": "any_time_readonly",
            "resolution_kind": "inspection",
            "effects": [{
                "kind": (
                    "inspect_damage_defenses"
                    if information_kind == "damage_defenses"
                    else "inspect_authorized_information"
                ),
                "information_kind": information_kind,
                "range_ft": params.get("range_ft"),
                "visibility": params.get("visibility"),
            }],
            "information_kind": information_kind,
        }
    )
    required_state_target_key = params.get("required_state_target_key")
    if required_state_target_key is not None:
        entry["required_actor_state_target_key"] = str(required_state_target_key)
    return MaterializedBlock("actions", entry)


def _materialize_defense(context: MaterializerContext) -> MaterializedBlock:
    kind = {
        "grant_resistance": "damage_resistance",
        "grant_immunity": "condition_immunity",
        "grant_saving_throw_advantage": "saving_throw_advantage",
    }.get(context.operator)
    if kind is None:
        raise MaterializerError(f"unknown defense operator {context.operator}")
    entry = _with_parameters(context, kind=kind)
    if context.operator in {"grant_resistance", "grant_immunity"}:
        raw_type = entry.get("damage_type")
        if isinstance(raw_type, str) and raw_type.strip():
            entry["damage_types"] = [raw_type.strip()]
    return MaterializedBlock("combat_defenses", entry)


def _materialize_zero_hp(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    entry = context.base(kind="zero_hp_auto_prevention")
    entry.update(
        {
            "trigger": str(params["trigger"]),
            "resource_key": str(params["resource_key"]),
            "resource_cost": 1,
            "on_success": {"hit_points": str(params["replacement_hp"])},
            "eligibility": dict(params["eligibility"]),
            "reset": str(params["reset"]),
            "exceptions": list(params.get("exceptions") or ["outright_death"]),
        }
    )
    return MaterializedBlock("combat_defenses", entry)


def _materialize_spell_modifier(context: MaterializerContext) -> MaterializedBlock:
    params = context.parameters
    stat = {
        "spell_healing_modifier": "spell_healing",
        "spell_damage_modifier": "spell_damage",
        "spell_save_damage_modifier": "spell_damage",
    }.get(context.operator)
    if stat is None:
        raise MaterializerError(f"unknown spell modifier operator {context.operator}")
    entry = context.base(kind="modifier")
    entry.update(
        {
            "stat": stat,
            "operation": str(params["operation"]),
            "formula": str(params["formula"]),
            "scope": "outgoing",
            "applies_when": params.get("applies_when", "always"),
        }
    )
    for key in ("ability", "spell_school"):
        if key in params:
            entry[key] = params[key]
    return MaterializedBlock("combat_modifiers", entry)


def _materialize_rider(context: MaterializerContext) -> MaterializedBlock:
    entry = _with_parameters(context, kind=context.operator)
    return MaterializedBlock("attack_riders", entry)


class MaterializerRegistry:
    """Stable operator/materializer registry with fail-closed validation."""

    def __init__(self, materializers: Mapping[str, Materializer] | None = None) -> None:
        self._materializers: dict[str, Materializer] = dict(materializers or {})

    def register(self, materializer_id: str, materializer: Materializer) -> None:
        if not materializer_id.strip():
            raise ValueError("materializer_id cannot be empty")
        existing = self._materializers.get(materializer_id)
        if existing is not None and existing is not materializer:
            raise ValueError(f"duplicate materializer_id: {materializer_id}")
        self._materializers[materializer_id] = materializer

    def get(self, materializer_id: str | None) -> Materializer | None:
        return self._materializers.get(materializer_id or "")

    def materialize(
        self,
        *,
        spec: FeatureSpec,
        clause: ClauseSpec,
        operator: str,
        parameters: Mapping[str, Any],
        descriptor: CapabilityDescriptor,
        index: int,
    ) -> MaterializedBlock:
        materializer = self.get(descriptor.materializer_id)
        if materializer is None:
            raise MaterializerError(
                f"missing materializer {descriptor.materializer_id!r} "
                f"for capability {descriptor.capability_id}"
            )
        block = materializer(
            MaterializerContext(
                spec=spec,
                clause=clause,
                operator=operator,
                parameters=parameters,
                descriptor=descriptor,
                index=index,
            )
        )
        self.validate(block)
        return block

    @staticmethod
    def validate(block: MaterializedBlock) -> None:
        entry = block.entry
        if not entry.get("id") or not entry.get("feature_id"):
            raise MaterializerError("materialized block needs stable id and feature_id")
        execution = entry.get("runtime_execution")
        if not isinstance(execution, Mapping) or execution.get("status") != "ready":
            raise MaterializerError("materialized block lacks ready runtime_execution")
        if entry.get("automation_status") != "full":
            raise MaterializerError("materialized block is not full")
        if block.section == "combat_modifiers":
            for key in ("stat", "operation", "scope"):
                if not entry.get(key):
                    raise MaterializerError(f"combat modifier missing {key}")
        elif block.section == "movement_modes":
            if not entry.get("mode") or ("speed_source" not in entry and "speed_ft" not in entry):
                raise MaterializerError("movement mode lacks mode or speed")
        elif block.section == "proficiencies":
            if not entry.get("name") or not entry.get("operation"):
                raise MaterializerError("proficiency block lacks name or operation")
        elif block.section == "advancement":
            if entry.get("kind") == "selected_language_grant":
                if not isinstance(entry.get("choice_requirement"), Mapping):
                    raise MaterializerError("language choice lacks choice_requirement")
            elif not entry.get("spells") or not entry.get("grant_class"):
                raise MaterializerError("spell advancement block lacks spell or class")
        elif block.section == "prepared_spell_list":
            if not entry.get("spells") or not entry.get("source_class"):
                raise MaterializerError("prepared spell block lacks spell or class")

    def to_dict(self) -> list[str]:
        return sorted(self._materializers)


def default_materializer_registry() -> MaterializerRegistry:
    registry = MaterializerRegistry()
    for materializer_id, materializer in {
        "advancement.proficiency": _materialize_proficiency,
        "advancement.language": _materialize_language,
        "advancement.spell": _materialize_spell,
        "advancement.prepare_spell": _materialize_prepare_spell,
        "resource.lifecycle": _materialize_resource,
        "resource.profile": _materialize_resource_profile,
        "resource.lifecycle.consume": _materialize_resource,
        "resource.exchange": _materialize_exchange,
        "modifier.passive": _materialize_modifier,
        "modifier.passive.v2": _materialize_modifier,
        "modifier.passive.set": _materialize_modifier,
        "modifier.roll": _materialize_modifier,
        "modifier.roll.disadvantage": _materialize_modifier,
        "movement.mode": _materialize_movement,
        "sight.mode": _materialize_sight,
        "damage.healing": _materialize_action,
        "damage.temporary_hp": _materialize_trigger,
        "damage.modifier": _materialize_rider,
        "damage.type": _materialize_modifier,
        "defense.resistance": _materialize_defense,
        "defense.saving_throw_advantage": _materialize_defense,
        "defense.immunity": _materialize_defense,
        "state.lifecycle.activate": _materialize_action,
        "state.lifecycle.remove": _materialize_trigger,
        "modifier.timed": _materialize_action,
        "window.triggered_attack": _materialize_trigger,
        "window.reaction": _materialize_trigger,
        "attack.roll.intervention": _materialize_attack_roll_intervention,
        "target.authorized_information": _materialize_authorized_information,
        "zero_hp.intervention": _materialize_zero_hp,
        "spell.healing_modifier": _materialize_spell_modifier,
        "spell.damage_modifier": _materialize_spell_modifier,
        "spell.save_damage_modifier": _materialize_spell_modifier,
        "spell.context": _materialize_modifier,
        "spell.context.range": _materialize_modifier,
        "spell.context.payment": _materialize_modifier,
    }.items():
        registry.register(materializer_id, materializer)
    return registry
