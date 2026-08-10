"""Closed-world operator contracts for Feature IR.

An operator name alone is never executable.  The contract below defines the
small, typed parameter surface that a production consumer accepts and the
clause shapes that can reach that consumer.  This module intentionally
contains no feature names and no executable callbacks.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

_SAFE_PARAMETER_NAMES = frozenset(
    {
        "expression",
        "eval",
        "exec",
        "import",
        "module",
        "function",
        "callable",
        "callback",
        "python",
        "code",
        "path",
        "class_path",
        "module_path",
    }
)


def _is_exact_type(value: object, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "object":
        return isinstance(value, Mapping)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string_or_integer":
        return (isinstance(value, str) and bool(value.strip())) or (
            isinstance(value, int) and not isinstance(value, bool)
        )
    return False


def _walk_unsafe(value: object, path: str = "parameters") -> tuple[str, ...]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key)
            normalized = key.strip().casefold()
            if normalized in _SAFE_PARAMETER_NAMES or normalized.endswith("_path"):
                errors.append(f"{path}.{key}: executable or import payload is forbidden")
            errors.extend(_walk_unsafe(nested, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            errors.extend(_walk_unsafe(nested, f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.casefold()
        if "__import__" in lowered or "eval(" in lowered or "exec(" in lowered:
            errors.append(f"{path}: executable expression is forbidden")
    return tuple(errors)


@dataclass(frozen=True)
class ConditionalRequirement:
    when_field: str
    equals: object
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class OperatorValidation:
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class OperatorContract:
    operator_id: str
    contract_version: str
    required_parameters: frozenset[str]
    optional_parameters: frozenset[str]
    parameter_types: Mapping[str, str]
    enum_values: Mapping[str, frozenset[object]]
    numeric_bounds: Mapping[str, tuple[float | None, float | None]]
    mutually_exclusive_fields: tuple[frozenset[str], ...]
    conditional_required_fields: tuple[ConditionalRequirement, ...]
    compatible_triggers: frozenset[str]
    compatible_conditions: frozenset[str]
    compatible_activation: frozenset[str]
    compatible_action_economy: frozenset[str]
    compatible_targets: frozenset[str]
    compatible_durations: frozenset[str]
    compatible_resource_operations: frozenset[str]
    materializer_id: str
    capability_id: str

    @property
    def allowed_parameters(self) -> frozenset[str]:
        return self.required_parameters | self.optional_parameters

    def validate_parameters(self, parameters: Mapping[str, Any]) -> OperatorValidation:
        errors: list[str] = []
        errors.extend(_walk_unsafe(parameters))
        unknown = sorted(set(parameters) - self.allowed_parameters)
        errors.extend(
            f"unknown parameter {key!r} for operator {self.operator_id}" for key in unknown
        )
        missing = sorted(key for key in self.required_parameters if key not in parameters)
        errors.extend(
            f"missing required parameter {key!r} for operator {self.operator_id}" for key in missing
        )
        if (
            self.operator_id
            in {
                "restore_resource",
                "consume_resource",
                "exchange_resource",
            }
            and "amount" not in parameters
            and "amount_source" not in parameters
        ):
            errors.append(f"{self.operator_id} requires one of 'amount' or 'amount_source'")
        if self.operator_id == "grant_movement_mode" and (
            "speed_source" not in parameters and "speed_ft" not in parameters
        ):
            errors.append("grant_movement_mode requires one of 'speed_source' or 'speed_ft'")
        if self.operator_id == "grant_sight_mode" and (
            "range_ft" not in parameters and "range_source" not in parameters
        ):
            errors.append("grant_sight_mode requires one of 'range_ft' or 'range_source'")
        if (
            self.operator_id
            in {
                "add_modifier",
                "set_modifier",
                "grant_passive_modifier",
                "create_timed_modifier",
            }
            and "value" not in parameters
            and "value_source" not in parameters
        ):
            errors.append(f"{self.operator_id} requires one of 'value' or 'value_source'")
        if self.operator_id == "configure_attack_roll_intervention":
            modes = parameters.get("modes")
            if isinstance(modes, list):
                if not modes:
                    errors.append("configure_attack_roll_intervention requires at least one mode")
                if any(value not in {"defense", "offense"} for value in modes):
                    errors.append(
                        "configure_attack_roll_intervention modes must be defense/offense"
                    )
                if len(set(modes)) != len(modes):
                    errors.append("configure_attack_roll_intervention modes must be unique")
            elif "modes" in parameters:
                errors.append("configure_attack_roll_intervention modes must be an array")
        for key, type_name in self.parameter_types.items():
            if key not in parameters:
                continue
            if not _is_exact_type(parameters[key], type_name):
                errors.append(
                    f"parameter {key!r} must be {type_name}, got {type(parameters[key]).__name__}"
                )
        for key, values in self.enum_values.items():
            if key in parameters and parameters[key] not in values:
                errors.append(f"parameter {key!r} has unsupported value {parameters[key]!r}")
        for key, (minimum, maximum) in self.numeric_bounds.items():
            if key not in parameters or not isinstance(parameters[key], (int, float)):
                continue
            value = float(parameters[key])
            if minimum is not None and value < minimum:
                errors.append(f"parameter {key!r} must be >= {minimum:g}")
            if maximum is not None and value > maximum:
                errors.append(f"parameter {key!r} must be <= {maximum:g}")
        for group in self.mutually_exclusive_fields:
            present = sorted(field for field in group if field in parameters)
            if len(present) > 1:
                errors.append("mutually exclusive parameters present: " + ", ".join(present))
        for condition in self.conditional_required_fields:
            if parameters.get(condition.when_field) != condition.equals:
                continue
            errors.extend(
                f"parameter {field!r} is required when {condition.when_field}={condition.equals!r}"
                for field in condition.required_fields
                if field not in parameters
            )
        return OperatorValidation(tuple(dict.fromkeys(errors)))

    def validate_clause(
        self,
        *,
        trigger: str,
        conditions: Iterable[str],
        activation: str,
        action_economy: str,
        target: str | None,
        duration: str | None,
        resource_operations: Iterable[str],
    ) -> tuple[str, ...]:
        errors: list[str] = []

        def check(value: str | None, supported: frozenset[str], label: str) -> None:
            if value is not None and value not in supported:
                errors.append(f"{label} {value!r} is unsupported by {self.operator_id}")

        check(trigger, self.compatible_triggers, "trigger")
        for condition in conditions:
            check(condition, self.compatible_conditions, "condition")
        check(activation, self.compatible_activation, "activation")
        check(action_economy, self.compatible_action_economy, "action economy")
        check(target, self.compatible_targets, "target")
        if duration is not None:
            check(duration, self.compatible_durations, "duration")
        for operation in resource_operations:
            check(operation, self.compatible_resource_operations, "resource operation")
        return tuple(dict.fromkeys(errors))

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator_id": self.operator_id,
            "contract_version": self.contract_version,
            "required_parameters": sorted(self.required_parameters),
            "optional_parameters": sorted(self.optional_parameters),
            "parameter_types": dict(sorted(self.parameter_types.items())),
            "enum_values": {
                key: sorted(values, key=lambda value: str(value))
                for key, values in sorted(self.enum_values.items())
            },
            "numeric_bounds": {
                key: [minimum, maximum]
                for key, (minimum, maximum) in sorted(self.numeric_bounds.items())
            },
            "mutually_exclusive_fields": [
                sorted(group) for group in self.mutually_exclusive_fields
            ],
            "conditional_required_fields": [
                {
                    "when_field": item.when_field,
                    "equals": item.equals,
                    "required_fields": list(item.required_fields),
                }
                for item in self.conditional_required_fields
            ],
            "compatible_triggers": sorted(self.compatible_triggers),
            "compatible_conditions": sorted(self.compatible_conditions),
            "compatible_activation": sorted(self.compatible_activation),
            "compatible_action_economy": sorted(self.compatible_action_economy),
            "compatible_targets": sorted(self.compatible_targets),
            "compatible_durations": sorted(self.compatible_durations),
            "compatible_resource_operations": sorted(self.compatible_resource_operations),
            "materializer_id": self.materializer_id,
            "capability_id": self.capability_id,
        }


_TRIGGER_ADVANCEMENT = frozenset({"advancement_confirmed"})
_TRIGGER_REST = frozenset(
    {"short_rest_started", "short_rest_completed", "long_rest_started", "long_rest_completed"}
)
_TRIGGER_COMBAT = frozenset(
    {
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
        "zero_hp",
        "explicit_activation",
    }
)
_CONDITIONS = frozenset(
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
_ACTIVATION = frozenset({"automatic", "player_accept", "dm_accept", "explicit_choice"})
_ACTIONS_NONE = frozenset({"none", "automatic"})
_ACTIONS_ANY = _ACTIONS_NONE | frozenset(
    {"action", "bonus_action", "reaction", "explicit_player_choice"}
)
_TARGET_SELF = frozenset({"self"})
_TARGET_COMBAT = frozenset(
    {"self", "one_creature", "ally", "enemy", "marked_target", "visible_creature", "aura"}
)
_DURATION_PERSISTENT = frozenset({"permanent", "advancement_persistent"})
_DURATION_COMBAT = frozenset(
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
_RESOURCE_OPS = frozenset(
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


def _contract(
    operator_id: str,
    *,
    required: Iterable[str],
    optional: Iterable[str] = (),
    types: Mapping[str, str],
    enums: Mapping[str, Iterable[object]] | None = None,
    bounds: Mapping[str, tuple[float | None, float | None]] | None = None,
    triggers: frozenset[str],
    conditions: frozenset[str] = _CONDITIONS,
    activation: frozenset[str] = _ACTIVATION,
    actions: frozenset[str] = _ACTIONS_NONE,
    targets: frozenset[str] = _TARGET_SELF,
    durations: frozenset[str] = _DURATION_PERSISTENT,
    resources: frozenset[str] = frozenset(),
    materializer: str,
    capability: str,
    mutually_exclusive: tuple[frozenset[str], ...] = (),
    conditional: tuple[ConditionalRequirement, ...] = (),
) -> OperatorContract:
    return OperatorContract(
        operator_id=operator_id,
        contract_version="1.0",
        required_parameters=frozenset(required),
        optional_parameters=frozenset(optional),
        parameter_types=dict(types),
        enum_values={key: frozenset(values) for key, values in (enums or {}).items()},
        numeric_bounds=dict(bounds or {}),
        mutually_exclusive_fields=mutually_exclusive,
        conditional_required_fields=conditional,
        compatible_triggers=triggers,
        compatible_conditions=conditions,
        compatible_activation=activation,
        compatible_action_economy=actions,
        compatible_targets=targets,
        compatible_durations=durations,
        compatible_resource_operations=resources,
        materializer_id=materializer,
        capability_id=capability,
    )


def default_operator_contracts() -> dict[str, OperatorContract]:
    """Return every operator accepted by the current capability catalog."""

    contracts = [
        _contract(
            "grant_proficiency",
            required=("proficiency_kind", "asset_id", "operation"),
            types={"proficiency_kind": "string", "asset_id": "string", "operation": "string"},
            enums={"operation": {"grant", "remove", "replace"}},
            triggers=_TRIGGER_ADVANCEMENT,
            durations=_DURATION_PERSISTENT,
            materializer="advancement.proficiency",
            capability="advancement.proficiency",
        ),
        _contract(
            "grant_language",
            required=("language_id", "operation"),
            types={"language_id": "string", "operation": "string"},
            enums={"operation": {"grant", "remove", "replace"}},
            triggers=_TRIGGER_ADVANCEMENT,
            durations=_DURATION_PERSISTENT,
            materializer="advancement.language",
            capability="advancement.language",
        ),
        _contract(
            "grant_spell",
            required=("spell_id", "source_class", "casting_ability", "grant_mode"),
            optional=("ritual_only", "free_cast_resource_key", "auto_save"),
            types={
                "spell_id": "string",
                "source_class": "string",
                "casting_ability": "string",
                "grant_mode": "string",
                "ritual_only": "boolean",
                "free_cast_resource_key": "string",
                "auto_save": "boolean",
            },
            enums={"grant_mode": {"known", "always_prepared", "free_cast"}},
            triggers=_TRIGGER_ADVANCEMENT,
            durations=_DURATION_PERSISTENT,
            materializer="advancement.spell",
            capability="advancement.spell",
        ),
        _contract(
            "prepare_spell",
            required=("spell_id", "source_class"),
            optional=("preparation_mode",),
            types={"spell_id": "string", "source_class": "string", "preparation_mode": "string"},
            enums={"preparation_mode": {"prepared", "always_prepared"}},
            triggers=_TRIGGER_ADVANCEMENT,
            durations=_DURATION_PERSISTENT,
            materializer="advancement.prepare_spell",
            capability="advancement.prepare_spell",
        ),
        _contract(
            "restore_resource",
            required=("resource_key", "operation"),
            optional=("amount", "amount_source", "recovery_event"),
            types={
                "resource_key": "string",
                "operation": "string",
                "amount": "integer",
                "amount_source": "string",
                "recovery_event": "string",
            },
            enums={"operation": {"restore", "set_to_max", "add"}},
            bounds={"amount": (0, 100)},
            triggers=_TRIGGER_REST | frozenset({"advancement_confirmed", "spell_cast", "zero_hp"}),
            actions=_ACTIONS_ANY,
            durations=_DURATION_COMBAT,
            resources=_RESOURCE_OPS,
            materializer="resource.lifecycle",
            capability="resource.lifecycle",
            mutually_exclusive=(frozenset({"amount", "amount_source"}),),
        ),
        _contract(
            "set_resource_profile",
            required=("resource_key", "resource_kind", "die_size"),
            optional=("max_formula", "recovery_events", "id"),
            types={
                "resource_key": "string",
                "resource_kind": "string",
                "die_size": "integer",
                "max_formula": "string",
                "recovery_events": "array",
                "id": "string",
            },
            enums={"resource_kind": {"superiority_dice", "psionic_dice", "d20_pool"}},
            bounds={"die_size": (2, 100)},
            triggers=_TRIGGER_ADVANCEMENT,
            durations=_DURATION_PERSISTENT,
            materializer="resource.profile",
            capability="resource.profile",
        ),
        _contract(
            "consume_resource",
            required=("resource_key", "operation"),
            optional=("amount", "amount_source"),
            types={
                "resource_key": "string",
                "operation": "string",
                "amount": "integer",
                "amount_source": "string",
            },
            enums={"operation": {"consume", "set"}},
            bounds={"amount": (1, 100)},
            triggers=_TRIGGER_COMBAT | _TRIGGER_ADVANCEMENT | frozenset({"explicit_activation"}),
            actions=_ACTIONS_ANY,
            targets=_TARGET_COMBAT,
            durations=_DURATION_COMBAT,
            resources=_RESOURCE_OPS,
            materializer="resource.lifecycle.consume",
            capability="resource.lifecycle.consume",
            mutually_exclusive=(frozenset({"amount", "amount_source"}),),
        ),
        _contract(
            "exchange_resource",
            required=("from_resource_key", "to_resource_key", "operation"),
            optional=("amount", "amount_source"),
            types={
                "from_resource_key": "string",
                "to_resource_key": "string",
                "operation": "string",
                "amount": "integer",
                "amount_source": "string",
            },
            enums={"operation": {"exchange"}},
            bounds={"amount": (1, 100)},
            triggers=_TRIGGER_COMBAT
            | _TRIGGER_REST
            | _TRIGGER_ADVANCEMENT
            | frozenset({"explicit_activation"}),
            actions=_ACTIONS_ANY,
            targets=_TARGET_SELF,
            durations=_DURATION_COMBAT,
            resources=_RESOURCE_OPS,
            materializer="resource.exchange",
            capability="resource.exchange",
            mutually_exclusive=(frozenset({"amount", "amount_source"}),),
        ),
        _contract(
            "add_modifier",
            required=("stat", "operation"),
            optional=("value", "value_source", "scope", "applies_when", "id"),
            types={
                "stat": "string",
                "operation": "string",
                "value": "number",
                "value_source": "string",
                "scope": "string",
                "applies_when": "string",
                "id": "string",
            },
            enums={"scope": {"self", "outgoing", "incoming", "target", "aura"}},
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_COMBAT,
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF | frozenset({"ally", "enemy"}),
            durations=_DURATION_COMBAT,
            materializer="modifier.passive",
            capability="modifier.passive",
            mutually_exclusive=(frozenset({"value", "value_source"}),),
        ),
        _contract(
            "grant_passive_modifier",
            required=("stat", "operation", "scope", "applies_when"),
            optional=("value", "value_source", "formula", "id"),
            types={
                "stat": "string",
                "operation": "string",
                "scope": "string",
                "applies_when": "string",
                "value": "number",
                "value_source": "string",
                "formula": "string",
                "id": "string",
            },
            enums={"scope": {"self", "outgoing", "incoming", "target", "aura"}},
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_COMBAT,
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF | frozenset({"ally", "enemy"}),
            durations=_DURATION_COMBAT,
            materializer="modifier.passive.v2",
            capability="modifier.passive.v2",
            mutually_exclusive=(frozenset({"value", "value_source"}),),
        ),
        _contract(
            "set_modifier",
            required=("stat", "operation"),
            optional=("value", "value_source", "scope", "applies_when", "id"),
            types={
                "stat": "string",
                "operation": "string",
                "value": "number",
                "value_source": "string",
                "scope": "string",
                "applies_when": "string",
                "id": "string",
            },
            enums={"scope": {"self", "outgoing", "incoming", "target", "aura"}},
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_COMBAT,
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF | frozenset({"ally", "enemy"}),
            durations=_DURATION_COMBAT,
            materializer="modifier.passive.set",
            capability="modifier.passive.set",
            mutually_exclusive=(frozenset({"value", "value_source"}),),
        ),
        _contract(
            "impose_advantage",
            required=("stat", "operation"),
            optional=("scope", "applies_when", "id"),
            types={
                "stat": "string",
                "operation": "string",
                "scope": "string",
                "applies_when": "string",
                "id": "string",
            },
            enums={"operation": {"advantage"}, "scope": {"self", "outgoing", "incoming", "target"}},
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_COMBAT,
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF | frozenset({"ally", "enemy"}),
            durations=_DURATION_COMBAT,
            materializer="modifier.roll",
            capability="modifier.roll",
        ),
        _contract(
            "impose_disadvantage",
            required=("stat", "operation"),
            optional=("scope", "applies_when", "id"),
            types={
                "stat": "string",
                "operation": "string",
                "scope": "string",
                "applies_when": "string",
                "id": "string",
            },
            enums={
                "operation": {"disadvantage"},
                "scope": {"self", "outgoing", "incoming", "target"},
            },
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_COMBAT,
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF | frozenset({"ally", "enemy"}),
            durations=_DURATION_COMBAT,
            materializer="modifier.roll.disadvantage",
            capability="modifier.roll.disadvantage",
        ),
        _contract(
            "grant_movement_mode",
            required=("mode",),
            optional=(
                "speed_source",
                "speed_ft",
                "requires_not_wearing_heavy_armor",
                "applies_when",
                "selection_binding",
                "id",
            ),
            types={
                "mode": "string",
                "speed_source": "string",
                "speed_ft": "integer",
                "requires_not_wearing_heavy_armor": "boolean",
                "applies_when": "string",
                "selection_binding": "object",
                "id": "string",
            },
            enums={"mode": {"climb", "swim", "burrow", "fly", "walk"}},
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_COMBAT,
            actions=_ACTIONS_ANY,
            durations=_DURATION_PERSISTENT | _DURATION_COMBAT,
            materializer="movement.mode",
            capability="movement.mode",
            mutually_exclusive=(frozenset({"speed_source", "speed_ft"}),),
            conditional=(ConditionalRequirement("mode", "fly", ("speed_source",)),),
        ),
        _contract(
            "grant_sight_mode",
            required=("mode",),
            optional=("range_ft", "range_source", "applies_when", "id"),
            types={
                "mode": "string",
                "range_ft": "integer",
                "range_source": "string",
                "applies_when": "string",
                "id": "string",
            },
            enums={"mode": {"blindsight", "darkvision", "truesight", "tremorsense"}},
            bounds={"range_ft": (1, 120)},
            triggers=_TRIGGER_ADVANCEMENT | frozenset({"combat_started"}),
            durations=_DURATION_PERSISTENT,
            materializer="sight.mode",
            capability="sight.mode",
            mutually_exclusive=(frozenset({"range_ft", "range_source"}),),
        ),
        _contract(
            "heal",
            required=("formula", "source"),
            optional=("ability", "id", "legal_sources"),
            types={
                "formula": "string",
                "source": "string",
                "ability": "string",
                "id": "string",
                "legal_sources": "array",
            },
            triggers=_TRIGGER_COMBAT | _TRIGGER_ADVANCEMENT,
            actions=_ACTIONS_ANY,
            targets=_TARGET_COMBAT,
            durations=_DURATION_COMBAT,
            materializer="damage.healing",
            capability="damage.healing",
        ),
        _contract(
            "grant_temporary_hp",
            required=("formula", "source"),
            optional=("id",),
            types={"formula": "string", "source": "string", "id": "string"},
            triggers=_TRIGGER_COMBAT | _TRIGGER_ADVANCEMENT | _TRIGGER_REST,
            actions=_ACTIONS_ANY,
            targets=_TARGET_COMBAT,
            durations=_DURATION_COMBAT,
            materializer="damage.temporary_hp",
            capability="damage.temporary_hp",
        ),
        _contract(
            "add_damage",
            required=("formula", "damage_type"),
            optional=("source", "applies_when", "id"),
            types={
                "formula": "string",
                "damage_type": "string",
                "source": "string",
                "applies_when": "string",
                "id": "string",
            },
            triggers=_TRIGGER_COMBAT,
            actions=_ACTIONS_NONE,
            targets=_TARGET_COMBAT,
            durations=_DURATION_COMBAT,
            materializer="damage.modifier",
            capability="damage.modifier",
        ),
        _contract(
            "replace_damage_type",
            required=("from_type", "to_type"),
            optional=("applies_when", "id"),
            types={
                "from_type": "string",
                "to_type": "string",
                "applies_when": "string",
                "id": "string",
            },
            triggers=_TRIGGER_COMBAT,
            actions=_ACTIONS_NONE,
            targets=_TARGET_COMBAT,
            durations=_DURATION_COMBAT,
            materializer="damage.type",
            capability="damage.type",
        ),
        _contract(
            "grant_resistance",
            required=("damage_type",),
            optional=("source", "applies_when", "id"),
            types={
                "damage_type": "string",
                "source": "string",
                "applies_when": "string",
                "id": "string",
            },
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_COMBAT,
            actions=_ACTIONS_ANY,
            durations=_DURATION_PERSISTENT | _DURATION_COMBAT,
            materializer="defense.resistance",
            capability="defense.resistance",
        ),
        _contract(
            "grant_saving_throw_advantage",
            required=("applies_when",),
            optional=("id",),
            types={
                "applies_when": "string",
                "id": "string",
            },
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_COMBAT,
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF,
            durations=_DURATION_PERSISTENT | _DURATION_COMBAT,
            materializer="defense.saving_throw_advantage",
            capability="defense.saving_throw_advantage",
        ),
        _contract(
            "grant_immunity",
            required=("condition_or_damage_type",),
            optional=("source", "id"),
            types={"condition_or_damage_type": "string", "source": "string", "id": "string"},
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_COMBAT,
            durations=_DURATION_PERSISTENT,
            materializer="defense.immunity",
            capability="defense.immunity",
        ),
        _contract(
            "activate_condition",
            required=("condition",),
            optional=("duration", "id"),
            types={"condition": "string", "duration": "string", "id": "string"},
            triggers=_TRIGGER_COMBAT,
            actions=_ACTIONS_ANY,
            targets=_TARGET_COMBAT,
            durations=_DURATION_COMBAT,
            materializer="state.lifecycle.activate",
            capability="state.lifecycle.activate",
        ),
        _contract(
            "remove_condition",
            required=("condition",),
            optional=("id",),
            types={"condition": "string", "id": "string"},
            triggers=_TRIGGER_COMBAT,
            actions=_ACTIONS_ANY,
            targets=_TARGET_COMBAT,
            durations=_DURATION_COMBAT,
            materializer="state.lifecycle.remove",
            capability="state.lifecycle.remove",
        ),
        _contract(
            "create_timed_modifier",
            required=("stat", "operation", "duration"),
            optional=("value", "value_source", "scope", "applies_when", "id"),
            types={
                "stat": "string",
                "operation": "string",
                "duration": "string",
                "value": "number",
                "value_source": "string",
                "scope": "string",
                "applies_when": "string",
                "id": "string",
            },
            enums={"scope": {"self", "outgoing", "incoming", "target", "aura"}},
            triggers=_TRIGGER_COMBAT,
            actions=_ACTIONS_ANY,
            targets=_TARGET_COMBAT,
            durations=_DURATION_COMBAT,
            materializer="modifier.timed",
            capability="modifier.timed",
            mutually_exclusive=(frozenset({"value", "value_source"}),),
        ),
        _contract(
            "create_triggered_attack_window",
            required=("window_kind", "parent_action", "target_policy", "expires"),
            optional=("reaction_type", "attack_profile", "id"),
            types={
                "window_kind": "string",
                "parent_action": "string",
                "target_policy": "object",
                "expires": "string",
                "reaction_type": "string",
                "attack_profile": "object",
                "id": "string",
            },
            enums={"reaction_type": {"reaction", "bonus_action", "action"}},
            triggers=frozenset(
                {"attack_hit", "attack_missed", "damage_applied", "action_resolved", "zero_hp"}
            ),
            actions=frozenset({"reaction", "bonus_action", "action", "explicit_player_choice"}),
            targets=_TARGET_COMBAT,
            durations=frozenset({"current_turn", "current_round"}),
            materializer="window.triggered_attack",
            capability="window.triggered_attack",
        ),
        _contract(
            "create_reaction_window",
            required=("window_kind", "expires"),
            optional=("target_policy", "id"),
            types={
                "window_kind": "string",
                "expires": "string",
                "target_policy": "object",
                "id": "string",
            },
            triggers=_TRIGGER_COMBAT,
            actions=frozenset({"reaction", "explicit_player_choice"}),
            targets=_TARGET_COMBAT,
            durations=frozenset({"current_turn", "current_round"}),
            materializer="window.reaction",
            capability="window.reaction",
        ),
        _contract(
            "configure_attack_roll_intervention",
            required=("source_die_key", "modes"),
            optional=("id",),
            types={
                "source_die_key": "string",
                "modes": "array",
                "id": "string",
            },
            triggers=_TRIGGER_ADVANCEMENT,
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF,
            durations=_DURATION_PERSISTENT,
            materializer="attack.roll.intervention",
            capability="attack.roll.intervention",
        ),
        _contract(
            "zero_hp_intervention",
            required=("trigger", "replacement_hp", "resource_key", "eligibility", "reset"),
            optional=("id", "exceptions"),
            types={
                "trigger": "string",
                "replacement_hp": "string",
                "resource_key": "string",
                "eligibility": "object",
                "reset": "string",
                "id": "string",
                "exceptions": "array",
            },
            enums={"reset": {"short_rest", "long_rest"}},
            triggers=frozenset({"zero_hp", "damage_before_apply"}),
            actions=frozenset({"none", "automatic", "reaction", "explicit_player_choice"}),
            targets=_TARGET_SELF,
            durations=frozenset({"current_turn", "current_round", "until_long_rest"}),
            resources=_RESOURCE_OPS,
            materializer="zero_hp.intervention",
            capability="zero_hp.intervention",
        ),
        _contract(
            "spell_healing_modifier",
            required=("operation", "formula"),
            optional=("ability", "applies_when", "id"),
            types={
                "operation": "string",
                "formula": "string",
                "ability": "string",
                "applies_when": "string",
                "id": "string",
            },
            triggers=frozenset({"spell_cast", "advancement_confirmed"}),
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF | frozenset({"ally", "one_creature"}),
            durations=_DURATION_PERSISTENT,
            materializer="spell.healing_modifier",
            capability="spell.healing_modifier",
        ),
        _contract(
            "spell_damage_modifier",
            required=("operation", "formula"),
            optional=("ability", "spell_school", "applies_when", "id"),
            types={
                "operation": "string",
                "formula": "string",
                "ability": "string",
                "spell_school": "string",
                "applies_when": "string",
                "id": "string",
            },
            triggers=frozenset({"spell_cast", "advancement_confirmed"}),
            actions=_ACTIONS_NONE,
            targets=_TARGET_COMBAT,
            durations=_DURATION_PERSISTENT,
            materializer="spell.damage_modifier",
            capability="spell.damage_modifier",
        ),
        _contract(
            "spell_save_damage_modifier",
            required=("operation", "formula"),
            optional=("spell_school", "applies_when", "id"),
            types={
                "operation": "string",
                "formula": "string",
                "spell_school": "string",
                "applies_when": "string",
                "id": "string",
            },
            triggers=frozenset({"spell_cast", "saving_throw", "advancement_confirmed"}),
            actions=_ACTIONS_NONE,
            targets=_TARGET_COMBAT,
            durations=_DURATION_PERSISTENT,
            materializer="spell.save_damage_modifier",
            capability="spell.save_damage_modifier",
        ),
        _contract(
            "free_spell_cast",
            required=("spell_id", "resource_key", "reset"),
            optional=("source_class", "casting_ability", "auto_save", "id"),
            types={
                "spell_id": "string",
                "resource_key": "string",
                "reset": "string",
                "source_class": "string",
                "casting_ability": "string",
                "auto_save": "boolean",
                "id": "string",
            },
            enums={"reset": {"short_rest", "long_rest"}},
            triggers=_TRIGGER_ADVANCEMENT | _TRIGGER_REST | frozenset({"spell_cast"}),
            actions=_ACTIONS_NONE | frozenset({"explicit_player_choice"}),
            durations=_DURATION_PERSISTENT,
            resources=_RESOURCE_OPS,
            materializer="spell.free_cast",
            capability="spell.free_cast",
        ),
        _contract(
            "expose_authorized_target_information",
            required=("information_kind",),
            optional=("range_ft", "visibility", "required_state_target_key", "id"),
            types={
                "information_kind": "string",
                "range_ft": "integer",
                "visibility": "string",
                "required_state_target_key": "string",
                "id": "string",
            },
            triggers=frozenset({"explicit_activation", "action_declared", "action_resolved"}),
            actions=frozenset({"none", "bonus_action", "action", "explicit_player_choice"}),
            targets=_TARGET_COMBAT,
            durations=_DURATION_COMBAT,
            materializer="target.authorized_information",
            capability="target.authorized_information",
        ),
        _contract(
            "override_spell_components",
            required=("component", "operation"),
            optional=("applies_when", "id"),
            types={
                "component": "string",
                "operation": "string",
                "applies_when": "string",
                "id": "string",
            },
            triggers=frozenset({"spell_cast", "advancement_confirmed"}),
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF,
            durations=_DURATION_PERSISTENT,
            materializer="spell.context",
            capability="spell.context",
        ),
        _contract(
            "override_spell_range",
            required=("range_ft", "operation"),
            optional=("applies_when", "id"),
            types={
                "range_ft": "integer",
                "operation": "string",
                "applies_when": "string",
                "id": "string",
            },
            bounds={"range_ft": (0, 10000)},
            triggers=frozenset({"spell_cast", "advancement_confirmed"}),
            actions=_ACTIONS_NONE,
            targets=_TARGET_SELF,
            durations=_DURATION_PERSISTENT,
            materializer="spell.context.range",
            capability="spell.context.range",
        ),
        _contract(
            "override_spell_payment",
            required=("payment_kind", "operation"),
            optional=("resource_key", "applies_when", "id"),
            types={
                "payment_kind": "string",
                "operation": "string",
                "resource_key": "string",
                "applies_when": "string",
                "id": "string",
            },
            triggers=frozenset({"spell_cast", "advancement_confirmed"}),
            actions=_ACTIONS_NONE | frozenset({"explicit_player_choice"}),
            targets=_TARGET_SELF,
            durations=_DURATION_PERSISTENT,
            resources=_RESOURCE_OPS,
            materializer="spell.context.payment",
            capability="spell.context.payment",
        ),
    ]
    return {item.operator_id: item for item in contracts}


def get_operator_contract(operator_id: str) -> OperatorContract | None:
    return default_operator_contracts().get(operator_id)
