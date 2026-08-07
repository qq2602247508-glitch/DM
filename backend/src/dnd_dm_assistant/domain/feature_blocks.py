"""Small, configuration-driven contracts shared by class-feature executors.

This module validates the *shape* of a feature block.  It deliberately does
not know class or feature identifiers and it never mutates combat state.  The
database services remain responsible for action economy, resource CAS,
effects, prompts and idempotency.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ACTION_COSTS = frozenset({"action", "bonus_action", "reaction", "none"})
RESOURCE_COST_MODES = frozenset({"fixed", "amount", "amount_or_condition", "dice_count"})
TARGET_MODES = frozenset({"self", "ally_or_self", "enemy", "any"})
TRIGGER_WINDOWS = frozenset(
    {
        "turn_start",
        "turn_end",
        "after_failed_saving_throw",
        "after_failed_d20_test",
        "after_hit",
        "before_damage",
    }
)
TRIGGER_EVENTS = frozenset({"after_feature_action"})
TRIGGER_EFFECT_KINDS = frozenset(
    {"grant_movement_budget", "grant_disengage", "remove_conditions"}
)
RESOURCE_LIFECYCLE_EVENTS = frozenset(
    {"short_rest", "long_rest", "initiative_start", "turn_start", "turn_end"}
)
RESOURCE_LIFECYCLE_OPERATIONS = frozenset(
    {"restore", "set_to", "set_to_max", "set_to_minimum"}
)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def feature_action_block_errors(action: Mapping[str, Any]) -> tuple[str, ...]:
    """Return structural errors for an action block, fail-closed.

    The checks are intentionally data-only: an executor can use this contract
    for a fighter, spell, condition, or test fixture without branching on an
    identifier.
    """

    errors: list[str] = []
    if action.get("kind") != "feature_action":
        errors.append("kind must be feature_action")
    cost = str(action.get("action_cost") or "none")
    if cost not in ACTION_COSTS:
        errors.append("action_cost is invalid")
    trigger = action.get("trigger")
    window = action.get("activation_window")
    if window is not None and str(window) not in TRIGGER_WINDOWS:
        errors.append("activation_window is invalid")
    if trigger is not None and not isinstance(trigger, (str, Mapping)):
        errors.append("trigger must be a string or object")
    resource_key = str(action.get("resource_key") or "").strip()
    resource_cost = action.get("resource_cost", 0)
    if resource_key and (not isinstance(resource_cost, int) or resource_cost < 0):
        errors.append("resource_cost must be a non-negative integer")
    if resource_cost and not resource_key:
        errors.append("resource_key is required when resource_cost is non-zero")
    resource_cost_mode = str(action.get("resource_cost_mode") or "fixed")
    if resource_cost_mode not in RESOURCE_COST_MODES:
        errors.append("resource_cost_mode is invalid")
    if resource_cost_mode == "dice_count":
        dice = _mapping(action.get("healing_dice"))
        die_size = dice.get("die_size")
        if not _positive_int(die_size):
            errors.append("healing_dice.die_size is required for dice_count")
        max_dice = dice.get("max_dice")
        max_formula = str(dice.get("max_dice_formula") or "").strip()
        if max_dice is not None and not _positive_int(max_dice):
            errors.append("healing_dice.max_dice is invalid")
        if max_dice is None and not max_formula:
            errors.append("healing_dice.max_dice or max_dice_formula is required")
    target_policy = action.get("target_policy")
    if target_policy is not None:
        policy = _mapping(target_policy)
        if not policy or str(policy.get("mode") or "") not in TARGET_MODES:
            errors.append("target_policy.mode is invalid")
        range_ft = policy.get("range_ft")
        if range_ft is not None and (
            not isinstance(range_ft, int) or isinstance(range_ft, bool) or range_ft < 0
        ):
            errors.append("target_policy.range_ft is invalid")
    saving_throw = action.get("saving_throw")
    if saving_throw is not None:
        save = _mapping(saving_throw)
        if not str(save.get("ability") or save.get("dc_ability") or "").strip():
            errors.append("saving_throw ability is required")
        if save.get("initial_dc") is not None and not _positive_int(save.get("initial_dc")):
            errors.append("saving_throw.initial_dc is invalid")
        if save.get("dc_source") is not None and not str(save.get("dc_source") or "").strip():
            errors.append("saving_throw.dc_source is invalid")
    effects = action.get("effects")
    if effects is not None and not isinstance(effects, list):
        errors.append("effects must be a list")
    lifecycle = action.get("resource_lifecycle")
    if lifecycle is not None:
        lifecycle_map = _mapping(lifecycle)
        events = lifecycle_map.get("events")
        if not isinstance(events, list) or not events:
            errors.append("resource_lifecycle.events must be a non-empty list")
        else:
            errors.extend(
                resource_lifecycle_block_errors(
                    {"key": resource_key, "lifecycle_events": events}
                )
            )
    return tuple(errors)


def feature_action_block_ready(action: Mapping[str, Any]) -> bool:
    """Whether the generic action/trigger/resource/target contract is valid."""

    return not feature_action_block_errors(action)


def feature_trigger_block_errors(trigger: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate a reusable post-action trigger and its supported effects."""

    errors: list[str] = []
    if str(trigger.get("event") or "") not in TRIGGER_EVENTS:
        errors.append("event is invalid")
    if not str(trigger.get("action_id") or "").strip():
        errors.append("action_id is required")
    effects = trigger.get("effects")
    if not isinstance(effects, list) or not effects:
        errors.append("effects must be a non-empty list")
    else:
        for effect in effects:
            if not isinstance(effect, Mapping):
                errors.append("trigger effect must be an object")
                continue
            kind = str(effect.get("kind") or "")
            if kind not in TRIGGER_EFFECT_KINDS:
                errors.append("trigger effect kind is invalid")
            elif kind == "grant_movement_budget":
                source = str(effect.get("amount_source") or "")
                amount = effect.get("amount")
                if source != "half_current_speed" and not _positive_int(amount):
                    errors.append("movement budget needs amount or half_current_speed")
            elif (
                kind == "grant_disengage"
                and str(effect.get("expires") or "turn_end") != "turn_end"
            ):
                errors.append("disengage trigger only supports turn_end")
            elif kind == "remove_conditions":
                conditions = effect.get("conditions")
                if not isinstance(conditions, list) or not conditions or not all(
                    str(item).strip() for item in conditions
                ):
                    errors.append("remove_conditions needs a non-empty conditions list")
    return tuple(errors)


def feature_trigger_block_ready(trigger: Mapping[str, Any]) -> bool:
    return not feature_trigger_block_errors(trigger)


def resource_recovery_block_ready(resource: Mapping[str, Any]) -> bool:
    """Validate explicit short/long-rest recovery fields without guessing."""

    events = resource.get("recovery_events")
    if events is None:
        return True
    if not isinstance(events, list):
        return False
    for event in events:
        if not isinstance(event, Mapping):
            return False
        rest = str(event.get("rest") or "")
        trigger = str(event.get("trigger") or "")
        operation = str(event.get("operation") or "")
        if rest not in {"short_rest", "long_rest"} and trigger != "initiative_start":
            return False
        if operation not in {"restore", "set_to", "set_to_max", "set_to_minimum"}:
            return False
        if operation in {"restore", "set_to", "set_to_minimum"} and not _positive_int(
            event.get("amount", event.get("value", event.get("minimum")))
        ):
            return False
    return True


def resource_lifecycle_block_errors(resource: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the reusable resource lifecycle contract.

    This contract is deliberately independent of a class or feature name.  It
    describes only a resource key, a lifecycle event, and a bounded mutation.
    Rest services and combat-start services may consume it; malformed or
    unknown events fail closed instead of being guessed from prose.
    """

    errors: list[str] = []
    key = str(resource.get("key") or "").strip()
    if not key:
        errors.append("resource lifecycle key is required")
    events = resource.get("lifecycle_events", resource.get("recovery_events"))
    if events is None:
        return tuple(errors)
    if not isinstance(events, list):
        return (*errors, "resource lifecycle events must be a list")
    for event in events:
        if not isinstance(event, Mapping):
            errors.append("resource lifecycle event must be an object")
            continue
        trigger = str(event.get("rest") or event.get("trigger") or "")
        operation = str(event.get("operation") or "")
        if trigger not in RESOURCE_LIFECYCLE_EVENTS:
            errors.append("resource lifecycle event is invalid")
        if operation not in RESOURCE_LIFECYCLE_OPERATIONS:
            errors.append("resource lifecycle operation is invalid")
        if operation in {"restore", "set_to", "set_to_minimum"} and not _positive_int(
            event.get("amount", event.get("value", event.get("minimum")))
        ):
            errors.append("resource lifecycle operation needs a positive amount")
    return tuple(errors)


def resource_lifecycle_block_ready(resource: Mapping[str, Any]) -> bool:
    return not resource_lifecycle_block_errors(resource)


def structured_target_save_status(action: Mapping[str, Any]) -> bool:
    """True when target, save and status outcome fields are all structured."""

    policy = action.get("target_policy")
    save = action.get("saving_throw")
    outcomes = action.get("on_save_failure") or action.get("on_save_success")
    if policy is None and save is None and outcomes is None:
        return True
    if policy is not None and not feature_action_block_ready(action):
        return False
    if save is not None and not isinstance(save, Mapping):
        return False
    if outcomes is not None and not isinstance(outcomes, list):
        return False
    return True
