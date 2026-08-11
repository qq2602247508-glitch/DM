# ruff: noqa: E501
"""Production consumer for reviewed Content IR runtime blocks.

This is an orchestration boundary, not a second spell or feature engine.  It
resolves a reviewed runtime block from a real known spell or combatant feature
registry, then delegates action economy, CAS, idempotency, damage/healing,
temporary HP and effect persistence to the existing production services.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import CombatActionCommand, CombatFeatureActionCommand
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import (
    Character,
    Combatant,
    KnownSpell,
    OperationTransaction,
)
from dnd_dm_assistant.infrastructure.database.spell_economy_service import SpellEconomyService

RUNTIME_PREVIEW_SCHEMA = "content-ir-runtime-preview-1"
PRODUCTION_SCHEMA = "content-ir-production-runtime-1"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: object) -> str:
    return str(value or "").strip()


def _stable_request_data(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in data.items()
        if str(key) not in {"preview_token", "idempotency_key"}
    }


class ContentIRRuntimeService:
    """Use reviewed IR through the real character and combat consumers."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.spells = SpellEconomyService(engine)
        self.combat = CombatEngineService(engine)

    @staticmethod
    def _runtime_blocks(runtime: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
        resolution = runtime.get("resolution")
        if not isinstance(resolution, Mapping):
            raise ValueError("spell runtime lacks a resolution registry")
        result: dict[str, list[dict[str, Any]]] = {}
        for key, value in resolution.items():
            if not isinstance(value, list):
                continue
            result[str(key)] = [dict(item) for item in value if isinstance(item, Mapping)]
        target_selection = result.get("target_selection") or []
        area_blocks = [
            item
            for item in target_selection
            if str(item.get("kind") or "") == "area"
            or str(item.get("type") or "") == "area"
        ]
        area_blocks.extend(item for item in result.get("effects", []) if item.get("type") == "area")
        if area_blocks:
            result["area"] = area_blocks
        temporary_blocks = [
            item for item in result.get("effects", []) if item.get("type") == "temporary_hp"
        ]
        if temporary_blocks:
            result["temporary_hp"] = temporary_blocks
        return result

    def _spell_runtime(
        self,
        session: Session,
        campaign_id: str,
        data: Mapping[str, Any],
    ) -> tuple[KnownSpell, Character, dict[str, Any], dict[str, list[dict[str, Any]]]]:
        character_id = _text(data.get("character_id"))
        known_spell_id = _text(data.get("known_spell_id"))
        character = session.get(Character, character_id)
        if character is None or character.campaign_id != campaign_id:
            raise StateNotFoundError("content runtime character not found")
        if character.version != int(data.get("character_version") or 0):
            raise VersionConflict(
                "character",
                character.id,
                int(data.get("character_version") or 0),
                character.version,
            )
        spell = session.get(KnownSpell, known_spell_id)
        if spell is None or spell.campaign_id != campaign_id or spell.character_id != character.id:
            raise StateNotFoundError("content runtime known spell not found")
        metadata = dict(spell.metadata_json or {})
        runtime = metadata.get("content_ir_runtime")
        if not isinstance(runtime, Mapping):
            raise ValueError("known spell is not bound to a reviewed Content IR runtime")
        runtime = dict(runtime)
        runtime_id = _text(data.get("runtime_id"))
        if runtime_id and runtime_id != _text(runtime.get("spell_id")):
            raise ValueError("runtime_id does not match the bound known spell")
        if runtime.get("runtime_schema_version") != "spell-runtime-1":
            raise ValueError("unsupported spell runtime schema")
        if runtime.get("execution_status") != "ready":
            raise ValueError("spell runtime is not ready")
        return spell, character, runtime, self._runtime_blocks(runtime)

    @staticmethod
    def _feature_runtime(
        session: Session,
        campaign_id: str,
        data: Mapping[str, Any],
    ) -> tuple[Combatant, dict[str, Any]]:
        combat_id = _text(data.get("combat_id"))
        actor_id = _text(data.get("actor_combatant_id"))
        actor = session.get(Combatant, actor_id)
        if actor is None or actor.combat_id != combat_id:
            raise StateNotFoundError("content runtime feature actor not found")
        if actor.version != int(data.get("actor_version") or 0):
            raise VersionConflict(
                "combatant",
                actor.id,
                int(data.get("actor_version") or 0),
                actor.version,
            )
        if _text(data.get("permission")) == "player" and actor.entity_type != "character":
            raise ValueError("player permission cannot execute a non-character feature actor")
        runtime = actor.snapshot_json.get("feature_runtime") if isinstance(actor.snapshot_json, dict) else None
        registry = dict(runtime) if isinstance(runtime, Mapping) else {}
        feature_id = _text(data.get("runtime_id"))
        actions = registry.get("actions")
        prefer_attack_rider = data.get("attack_hit") is True
        raw_action = None
        if not prefer_attack_rider:
            raw_action = actions.get(feature_id) if isinstance(actions, Mapping) else None
        if not isinstance(raw_action, Mapping) and isinstance(actions, Mapping):
            if not prefer_attack_rider:
                raw_action = next(
                    (
                        item
                        for item in actions.values()
                        if isinstance(item, Mapping)
                        and _text(item.get("feature_id")) == feature_id
                    ),
                    None,
                )
        if not isinstance(raw_action, Mapping):
            canonical = registry.get("canonical_actions")
            if isinstance(canonical, list) and not prefer_attack_rider:
                raw_action = next(
                    (
                        item
                        for item in canonical
                        if isinstance(item, Mapping)
                        and _text(item.get("feature_id")) == feature_id
                ),
                None,
            )
        if not isinstance(raw_action, Mapping):
            riders = registry.get("attack_riders")
            raw_action = next(
                (
                    {
                        "kind": "attack_rider",
                        "feature_id": feature_id,
                        "id": item.get("id"),
                        "automation_status": item.get("automation_status"),
                        "target": "enemy",
                        "target_policy": {"mode": "enemy"},
                        "action_cost": "none",
                        "resolution_kind": "damage",
                        "formula": item.get("formula"),
                        "damage_type": item.get("damage_type"),
                        "resource_key": item.get("resource_key"),
                        "resource_cost": 1 if item.get("resource_key") else 0,
                        "rider": dict(item),
                    }
                    for item in riders
                    if isinstance(item, Mapping) and _text(item.get("feature_id")) == feature_id
                ),
                None,
            )
        if not isinstance(raw_action, Mapping) and prefer_attack_rider:
            raw_action = actions.get(feature_id) if isinstance(actions, Mapping) else None
            if not isinstance(raw_action, Mapping) and isinstance(actions, Mapping):
                raw_action = next(
                    (
                        item
                        for item in actions.values()
                        if isinstance(item, Mapping)
                        and _text(item.get("feature_id")) == feature_id
                    ),
                    None,
                )
        if not isinstance(raw_action, Mapping):
            triggers = registry.get("triggers")
            raw_action = next(
                (
                    {
                        "kind": "feature_action",
                        "feature_id": feature_id,
                        "id": item.get("id"),
                        "automation_status": item.get("automation_status"),
                        "action_cost": item.get("action_cost", "none"),
                        "target": "ally_or_self",
                        "target_policy": {"mode": "ally_or_self"},
                        "resolution_kind": "condition_removal",
                        "condition_removal_options": [
                            part.strip()
                            for part in _text(item.get("condition")).split("_or_")
                            if part.strip()
                        ],
                        "condition_trigger": dict(item),
                        "effects": [],
                    }
                    for item in triggers
                    if isinstance(item, Mapping)
                    and _text(item.get("feature_id")) == feature_id
                    and _text(item.get("kind")) == "remove_condition"
                ),
                None,
            )
        if not isinstance(raw_action, Mapping):
            combat_start = registry.get("combat_start")
            start_blocks = []
            if isinstance(combat_start, Mapping):
                start_blocks = [
                    *[item for item in combat_start.get("defenses", []) if isinstance(item, Mapping)],
                    *[item for item in combat_start.get("modifiers", []) if isinstance(item, Mapping)],
                    *[item for item in combat_start.get("movement_modes", []) if isinstance(item, Mapping)],
                ]
            raw_action = next(
                (
                    {
                        "kind": "feature_action",
                        "feature_id": feature_id,
                        "id": item.get("id"),
                        "automation_status": item.get("automation_status"),
                        "availability": "any_time_readonly",
                        "action_cost": "none",
                        "target": "self",
                        "target_policy": {"mode": "self"},
                        "resolution_kind": "inspection",
                        "passive_block": dict(item),
                        "effects": (
                            [{"kind": "inspect_damage_defenses"}]
                            if item.get("kind") == "damage_resistance"
                            else []
                        ),
                    }
                    for item in start_blocks
                    if _text(item.get("feature_id")) == feature_id
                ),
                None,
            )
        if not isinstance(raw_action, Mapping):
            raise ValueError("combatant feature registry lacks the requested runtime consumer")
        action = dict(raw_action)
        if action.get("kind") == "create_timed_modifier":
            modifier_value = action.get("value")
            value_source = str(action.get("value_source") or "")
            if modifier_value is None and value_source.endswith("_die"):
                modifier_value = data.get("resolution_total")
            if modifier_value is None and value_source.endswith("_modifier"):
                ability = value_source.removesuffix("_modifier")
                scores = actor.snapshot_json.get("ability_scores")
                raw_score = scores.get(ability) if isinstance(scores, Mapping) else None
                if isinstance(raw_score, int):
                    modifier_value = (raw_score - 10) // 2
            action = {
                **action,
                "kind": "feature_action",
                "target": "ally_or_self",
                "target_policy": {"mode": "ally_or_self"},
                "resolution_kind": "timed_modifier",
                "effects": [
                    {
                        "kind": "grant_targeted_timed_modifier",
                        "modifier": {
                            "stat": action.get("stat"),
                            "operation": action.get("operation"),
                            "value": modifier_value,
                        },
                        "duration_unit": "turns",
                        "duration_value": 1,
                    }
                ],
            }
        if action.get("automation_status") != "full":
            raise ValueError("feature runtime action is not full")
        return actor, action

    @staticmethod
    def _parameters(block: Mapping[str, Any]) -> dict[str, Any]:
        parameters = block.get("parameters")
        return dict(parameters) if isinstance(parameters, Mapping) else dict(block)

    @staticmethod
    def _action_cost(blocks: Mapping[str, list[dict[str, Any]]]) -> str:
        for key in ("attack_roll", "saving_throw", "effects", "healing", "temporary_hp"):
            for block in blocks.get(key, []):
                parameters = ContentIRRuntimeService._parameters(block)
                if _text(parameters.get("action_economy")):
                    return _text(parameters["action_economy"])
        return "none"

    @staticmethod
    def _first_parameters(blocks: Mapping[str, list[dict[str, Any]]], key: str) -> dict[str, Any]:
        values = blocks.get(key) or []
        if not values:
            return {}
        return ContentIRRuntimeService._parameters(values[0])

    @staticmethod
    def _roll_bounds(expression: object) -> tuple[int, int] | None:
        match = re.fullmatch(r"\s*(\d+)d(\d+)(?:\s*([+-])\s*(\d+))?\s*", str(expression or ""))
        if not match:
            return None
        dice, sides = int(match.group(1)), int(match.group(2))
        fixed = int(match.group(4) or 0)
        if match.group(3) == "-":
            fixed = -fixed
        return dice + fixed, dice * sides + fixed

    @classmethod
    def _validate_resolution_total(
        cls,
        data: Mapping[str, Any],
        blocks: Mapping[str, list[dict[str, Any]]],
        *,
        expression: object,
        healing: bool = False,
    ) -> int:
        amount = data.get("resolution_total")
        if amount is None:
            raise ValueError("runtime requires resolution_total")
        bounds = cls._roll_bounds(expression)
        upcast = cls._first_parameters(blocks, "upcast")
        if bounds is not None and upcast:
            slot_level = int(data.get("slot_level") or 0)
            source_level = int(data.get("runtime_level") or slot_level)
            per_slot = int(upcast.get("per_slot") or 1)
            delta = max(0, slot_level - source_level)
            increment = cls._roll_bounds(upcast.get("increments"))
            if increment is not None:
                bounds = (bounds[0] + delta * per_slot * increment[0], bounds[1] + delta * per_slot * increment[1])
        value = int(amount)
        if bounds is not None and not bounds[0] <= value <= bounds[1]:
            kind = "healing" if healing else "damage"
            raise ValueError(f"{kind} roll must be between {bounds[0]} and {bounds[1]}")
        return value

    def _spell_commands(
        self,
        data: Mapping[str, Any],
        blocks: Mapping[str, list[dict[str, Any]]],
    ) -> list[CombatActionCommand] | None:
        target_ids = [
            item
            for item in [_text(data.get("target_combatant_id")), *data.get("target_combatant_ids", [])]
            if item
        ]
        if not target_ids:
            raise ValueError("production spell runtime requires a target")
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("production spell runtime target ids must be unique")
        actor_id = _text(data.get("actor_combatant_id"))
        actor_version = int(data.get("actor_version") or 0)
        target_versions = dict(data.get("target_versions") or {})
        if data.get("target_combatant_id"):
            target_versions.setdefault(
                _text(data.get("target_combatant_id")), int(data.get("target_version") or 0)
            )
        if any(int(target_versions.get(item) or 0) < 1 for item in target_ids):
            raise ValueError("production spell runtime requires every target version")
        effect_blocks = blocks.get("effects") or []
        damage = next(
            (
                self._parameters(block)
                for block in effect_blocks
                if self._parameters(block).get("damage_type")
                and (
                    self._parameters(block).get("expression")
                    or self._parameters(block).get("damage")
                )
            ),
            self._first_parameters(blocks, "damage"),
        )
        healing = next(
            (
                self._parameters(block)
                for block in [*(blocks.get("healing") or []), *effect_blocks]
                if self._parameters(block).get("healing")
                or self._parameters(block).get("resolution_kind") == "healing"
                or self._parameters(block).get("type") == "healing"
            ),
            {},
        )
        temporary = next(
            (
                self._parameters(block)
                for block in [*(blocks.get("temporary_hp") or []), *effect_blocks]
                if self._parameters(block).get("temporary_hp")
                or self._parameters(block).get("resolution_kind") == "temporary_healing"
                or self._parameters(block).get("type") == "temporary_hp"
            ),
            {},
        )
        if damage:
            base_amount = self._validate_resolution_total(
                data,
                blocks,
                expression=damage.get("expression") or damage.get("damage"),
            )
            save_blocks = blocks.get("saving_throw") or []
            save_parameters = self._parameters(save_blocks[0]) if save_blocks else {}
            attack = bool(blocks.get("attack_roll"))
            if attack and data.get("attack_roll_total") is None:
                raise ValueError("spell attack runtime requires attack_roll_total")
            area = self._first_parameters(blocks, "area")
            area_shape = _text(data.get("area_shape")) or _text(area.get("shape")) or None
            area_size = data.get("area_size_ft") or area.get("size_ft")
            if area_shape and (
                data.get("area_anchor_row") is None or data.get("area_anchor_col") is None
            ):
                raise ValueError("area spell runtime requires authoritative anchor row/col")
            condition_parameters = next(
                (
                    self._parameters(block)
                    for block in effect_blocks
                    if self._parameters(block).get("condition")
                    and self._parameters(block).get("type") in {"condition", "apply_condition"}
                ),
                {},
            )
            commands: list[CombatActionCommand] = []
            for index, target_id in enumerate(target_ids):
                save_by_target = data.get("save_succeeded_by_target")
                save_succeeded = (
                    save_by_target[target_id]
                    if isinstance(save_by_target, Mapping) and target_id in save_by_target
                    else data.get("save_succeeded")
                )
                if save_blocks and save_succeeded is None:
                    raise ValueError("saving throw runtime requires save_succeeded")
                amount = base_amount
                if save_blocks and save_succeeded is True:
                    amount = int(amount) // 2 if bool(save_parameters.get("half_on_success")) else 0
                conditions: list[str] = []
                if condition_parameters and (not save_blocks or save_succeeded is False):
                    conditions = [_text(condition_parameters.get("condition"))]
                command_data: dict[str, Any] = {
                    "action_type": "damage",
                    "target_combatant_id": target_id,
                    "target_version": int(target_versions[target_id]),
                    "actor_combatant_id": actor_id or None,
                    "actor_version": (actor_version + index) if actor_id else None,
                    "action_cost": self._action_cost(blocks) if index == 0 else "none",
                    "reaction_trigger": (
                        "content_ir_runtime"
                        if index == 0 and self._action_cost(blocks) == "reaction"
                        else None
                    ),
                    "action_name": _text(data.get("runtime_id")),
                    "amount": max(0, int(amount)),
                    "damage_type": _text(damage.get("damage_type")) or "force",
                    "is_attack": attack,
                    "is_spell_attack": attack,
                    "attack_ability": "spellcasting" if attack else None,
                    "attack_roll_total": int(data["attack_roll_total"]) if attack else None,
                    "conditions_to_apply": conditions,
                    "condition_duration": (
                        _text(condition_parameters.get("duration_kind")) or "target_turn_start"
                        if conditions
                        else None
                    ),
                    "condition_duration_value": (
                        int(condition_parameters.get("duration_value") or 1)
                        if conditions and _text(condition_parameters.get("duration_kind")) in {"rounds", "minutes"}
                        else None
                    ),
                }
                if area_shape:
                    command_data.update(
                        {
                            "area_shape": area_shape,
                            "area_size_ft": int(area_size),
                            "area_width_ft": data.get("area_width_ft"),
                            "area_height_ft": data.get("area_height_ft"),
                            "area_anchor_row": data.get("area_anchor_row"),
                            "area_anchor_col": data.get("area_anchor_col"),
                            "area_anchor_height_ft": int(data.get("area_anchor_height_ft") or 0),
                            "area_include_actor": bool(data.get("area_include_actor")),
                        }
                    )
                commands.append(CombatActionCommand.model_validate(command_data))
            return commands
        if healing:
            amount = self._validate_resolution_total(
                data,
                blocks,
                expression=healing.get("expression") or healing.get("healing"),
                healing=True,
            )
            return [
                CombatActionCommand(
                    action_type="heal",
                    target_combatant_id=target_ids[0],
                    target_version=int(target_versions[target_ids[0]]),
                    actor_combatant_id=actor_id or None,
                    actor_version=actor_version or None,
                    action_cost=self._action_cost(blocks),
                    action_name=_text(data.get("runtime_id")),
                    amount=max(0, int(amount)),
                )
            ]
        if temporary:
            return None
        raise ValueError("spell runtime has no supported production damage/healing block")

    def _spell_command(
        self,
        data: Mapping[str, Any],
        blocks: Mapping[str, list[dict[str, Any]]],
    ) -> CombatActionCommand | None:
        """Compatibility helper for callers that only accept one target."""

        commands = self._spell_commands(data, blocks)
        if commands is None:
            return None
        if len(commands) != 1:
            raise ValueError("multi-target runtime requires the batch consumer")
        return commands[0]

    def _preview_spell(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session:
            spell, character, runtime, blocks = self._spell_runtime(session, campaign_id, data)
            execution_data = {**data, "runtime_level": runtime.get("level")}
            consumers = resolve_production_consumers(
                content_kind="spell",
                runtime_schema_version=str(runtime.get("runtime_schema_version") or ""),
                blocks=blocks,
            )
            commands = self._spell_commands(execution_data, blocks)
            combat_preview = None
            if commands is not None:
                previews = [
                    self.combat.preview(campaign_id, _text(data.get("combat_id")), command)
                    for command in commands
                ]
                combat_preview = previews[0] if len(previews) == 1 else previews
            cast_data = {
                "character_id": character.id,
                "character_version": character.version,
                "known_spell_id": spell.id,
                "slot_level": int(data.get("slot_level") or 0),
                "ritual": bool(data.get("ritual")),
                "material_available": bool(data.get("material_available", True)),
                "concentration": bool(data.get("concentration")),
                "free_cast": bool(data.get("free_cast")),
                "recovery_slot_level": data.get("recovery_slot_level"),
                "preview_token": None,
                "idempotency_key": None,
            }
            spell_preview = self.spells.spell_preview(campaign_id, cast_data)
            result = {
                "schema_version": RUNTIME_PREVIEW_SCHEMA,
                "runtime_id": runtime.get("spell_id"),
                "runtime_source": runtime.get("source"),
                "compile_status": "full",
                "runtime_preview_full": True,
                "spell_preview": spell_preview,
                "combat_preview": combat_preview,
                "production_contract": {
                    "content_kind": "spell",
                    "known_spell_id": spell.id,
                    "action_cost": self._action_cost(blocks),
                    "requires_target": commands is not None,
                    "requires_resolution_input": commands is not None,
                    "requires_cas": True,
                    "requires_idempotency": True,
                    "consumers": [str(item["consumer_id"]) for item in consumers],
                    "area_batch": len(commands or []) > 1,
                },
            }
            result["preview_token"] = _fingerprint(
                {"data": _stable_request_data(data), "result": result}
            )
            return result

    def _preview_feature(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session:
            actor, action = self._feature_runtime(session, campaign_id, data)
            target_id = _text(data.get("target_combatant_id")) or actor.id
            target = session.get(Combatant, target_id)
            if target is None or target.combat_id != _text(data.get("combat_id")):
                raise StateNotFoundError("content runtime feature target not found")
            target_version = int(data.get("target_version") or target.version)
            if target.version != target_version:
                raise VersionConflict("combatant", target.id, target_version, target.version)
            if action.get("target") == "self" and target.id != actor.id:
                raise ValueError("feature runtime target policy requires self")
            feature_kind = _text(action.get("kind"))
            if feature_kind == "attack_rider":
                if data.get("attack_hit") is not True:
                    raise ValueError("attack rider runtime requires an authoritative parent attack hit")
                if CombatEngineService._combatant_faction(target) == CombatEngineService._combatant_faction(actor):
                    raise ValueError("attack rider runtime requires an enemy target")
                amount = self._validate_feature_roll(data, action)
                combat_preview = self.combat.preview(
                    campaign_id,
                    _text(data.get("combat_id")),
                    CombatActionCommand(
                        action_type="damage",
                        target_combatant_id=target.id,
                        target_version=target.version,
                        actor_combatant_id=actor.id,
                        actor_version=actor.version,
                        action_cost="none",
                        action_name=_text(data.get("runtime_id")),
                        resolution_note="typed parent attack reported hit",
                        amount=amount,
                        damage_type=_text(action.get("damage_type")) or "force",
                        resource_key=_text(action.get("resource_key")) or None,
                        resource_cost=int(action.get("resource_cost") or 0),
                    ),
                )
                feature_blocks = {"attack_rider": [action]}
            elif _text(action.get("resolution_kind")) == "condition_removal":
                feature_blocks = {
                    "condition_removal": [{"condition": (action.get("condition_removal_options") or [None])[0]}]
                }
                combat_preview = None
            elif _text(action.get("resolution_kind")) == "timed_modifier":
                feature_blocks = {"timed_modifier": [action]}
                combat_preview = None
            elif _text(action.get("resolution_kind")) == "inspection":
                feature_blocks = {"passive_registry": [action.get("passive_block") or action]}
                combat_preview = None
            else:
                feature_blocks = {"feature_action": [action]}
                combat_preview = None
            consumers = resolve_production_consumers(
                content_kind="feature",
                runtime_schema_version="feature-runtime-1",
                blocks=feature_blocks,
            )
            result = {
                "schema_version": RUNTIME_PREVIEW_SCHEMA,
                "runtime_id": _text(data.get("runtime_id")),
                "runtime_preview_full": True,
                "feature_action": action,
                "combat_preview": combat_preview,
                "production_contract": {
                    "content_kind": "feature",
                    "consumers": [str(item["consumer_id"]) for item in consumers],
                    "action_cost": action.get("action_cost", "none"),
                    "resource_key": action.get("resource_key"),
                    "resource_cost": action.get("resource_cost", 0),
                    "requires_actor_target_cas": True,
                    "requires_idempotency": True,
                    "permission": _text(data.get("permission")) or "player",
                },
            }
            result["preview_token"] = _fingerprint(
                {"data": _stable_request_data(data), "result": result}
            )
            return result

    @classmethod
    def _validate_feature_roll(cls, data: Mapping[str, Any], action: Mapping[str, Any]) -> int:
        total = data.get("resolution_total")
        if total is None:
            raise ValueError("feature damage rider requires resolution_total")
        bounds = cls._roll_bounds(action.get("formula"))
        value = int(total)
        if bounds is not None and not bounds[0] <= value <= bounds[1]:
            raise ValueError(f"feature damage rider must be between {bounds[0]} and {bounds[1]}")
        return value

    def preview(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if _text(data.get("content_kind")) == "spell":
            return self._preview_spell(campaign_id, data)
        if _text(data.get("content_kind")) == "feature":
            return self._preview_feature(campaign_id, data)
        raise ValueError("content_kind must be spell or feature")

    def _record_operation(self, campaign_id: str, key: str, result: dict[str, Any]) -> None:
        with Session(self.engine) as session, session.begin():
            session.add(
                OperationTransaction(
                    campaign_id=campaign_id,
                    operation_type="content_ir_runtime",
                    idempotency_key=f"content-ir:{key}",
                    before_snapshot={},
                    after_snapshot=result,
                    source="combat",
                    confirmed_at=datetime.now(UTC),
                )
            )

    def confirm(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        key = _text(data.get("idempotency_key"))
        if len(key) < 8:
            raise ValueError("content runtime idempotency_key is required")
        with Session(self.engine) as session:
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == f"content-ir:{key}",
                )
            )
            if existing is not None:
                return {**dict(existing.after_snapshot or {}), "already_applied": True}
        preview = self.preview(campaign_id, data)
        token = _text(data.get("preview_token"))
        if token != _text(preview.get("preview_token")):
            raise VersionConflict("content runtime preview", key, 1, 2)
        if _text(data.get("content_kind")) == "feature":
            runtime_action = dict(preview["feature_action"])
            if data.get("reaction_triggered") is True:
                runtime_action["reaction_triggered"] = True
            if runtime_action.get("kind") == "attack_rider":
                target_id = _text(data.get("target_combatant_id"))
                with Session(self.engine) as session:
                    actor, _action = self._feature_runtime(session, campaign_id, data)
                    target = session.get(Combatant, target_id)
                    if target is None:
                        raise StateNotFoundError("content runtime feature target not found")
                command = CombatActionCommand(
                    action_type="damage",
                    target_combatant_id=target_id,
                    target_version=int(data["target_version"]),
                    actor_combatant_id=actor.id,
                    actor_version=int(data["actor_version"]),
                    action_cost="none",
                    action_name=_text(data.get("runtime_id")),
                    resolution_note="typed parent attack reported hit",
                    amount=self._validate_feature_roll(data, runtime_action),
                    damage_type=_text(runtime_action.get("damage_type")) or "force",
                    resource_key=_text(runtime_action.get("resource_key")) or None,
                    resource_cost=int(runtime_action.get("resource_cost") or 0),
                )
                result = self.combat.confirm(
                    campaign_id,
                    _text(data["combat_id"]),
                    command,
                    idempotency_key=f"content-ir:{key}:feature-rider",
                )
                output = {
                    "schema_version": PRODUCTION_SCHEMA,
                    "runtime_id": data.get("runtime_id"),
                    "production_runtime_full": True,
                    "preview_token": token,
                    "consumer": "combat_engine.damage_heal.v1",
                    "result": result,
                }
                self._record_operation(campaign_id, key, output)
                return output
            command = CombatFeatureActionCommand(
                actor_combatant_id=_text(data["actor_combatant_id"]),
                actor_version=int(data["actor_version"]),
                feature_id=_text(data["runtime_id"]),
                target_combatant_id=_text(data.get("target_combatant_id")) or None,
                target_version=(int(data["target_version"]) if data.get("target_version") else None),
                healing_total=(int(data["resolution_total"]) if data.get("resolution_total") is not None else None),
                condition_to_remove=(str(data["condition_to_remove"]) if data.get("condition_to_remove") else None),
                dm_override=_text(data.get("permission")) == "dm",
                override_reason="content runtime DM authorization" if _text(data.get("permission")) == "dm" else None,
            )
            result = self.combat.confirm_feature_action(
                campaign_id,
                _text(data["combat_id"]),
                command,
                idempotency_key=f"content-ir:{key}:feature",
                runtime_action=runtime_action,
            )
            output = {
                "schema_version": PRODUCTION_SCHEMA,
                "runtime_id": data.get("runtime_id"),
                "production_runtime_full": True,
                "preview_token": token,
                "consumer": "combat_engine.feature_action.v1",
                "result": result,
            }
            self._record_operation(campaign_id, key, output)
            return output

        cast_preview = preview["spell_preview"]
        with Session(self.engine) as session:
            _spell, _character, runtime, blocks = self._spell_runtime(
                session, campaign_id, data
            )
        spell_key = f"{key}:spell"
        cast_data = {
            "character_id": data["character_id"],
            "character_version": data["character_version"],
            "known_spell_id": data["known_spell_id"],
            "slot_level": data["slot_level"],
            "ritual": data.get("ritual", False),
            "material_available": data.get("material_available", True),
            "concentration": data.get("concentration", False),
            "free_cast": data.get("free_cast", False),
            "recovery_slot_level": data.get("recovery_slot_level"),
            "preview_token": cast_preview["preview_token"],
            "idempotency_key": spell_key,
        }
        spell_done = self.spells.spell_confirm(campaign_id, cast_data)
        expected_character_version = int(spell_done.get("character_version_after") or int(data["character_version"]) + 1)
        try:
            execution_data = {**data, "runtime_level": runtime.get("level")}
            commands = self._spell_commands(execution_data, blocks)
            if commands is not None:
                if len(commands) == 1:
                    combat_done = self.combat.confirm(
                        campaign_id,
                        _text(data["combat_id"]),
                        commands[0],
                        idempotency_key=f"content-ir:{key}:combat",
                    )
                else:
                    combat_done = self.combat.confirm_action_batch(
                        campaign_id,
                        _text(data["combat_id"]),
                        [
                            (command, f"content-ir:{key}:combat:{index}")
                            for index, command in enumerate(commands)
                        ],
                    )
            else:
                temporary = self._first_parameters(blocks, "temporary_hp")
                if not temporary:
                    raise ValueError("spell runtime has no production consumer")
                runtime_action = {
                    "kind": "feature_action",
                    "id": _text(data.get("runtime_id")),
                    "feature_id": _text(data.get("runtime_id")),
                    "feature_name": _text(data.get("runtime_id")),
                    "automation_status": "full",
                    "action_cost": self._action_cost(blocks),
                    "target": "ally_or_self",
                    "resolution_kind": "temporary_healing",
                    "healing": temporary.get("expression") or temporary.get("amount"),
                    "effects": [],
                }
                feature_command = CombatFeatureActionCommand(
                    actor_combatant_id=_text(data["actor_combatant_id"]),
                    actor_version=int(data["actor_version"]),
                    feature_id=_text(data["runtime_id"]),
                    target_combatant_id=_text(data.get("target_combatant_id")) or None,
                    target_version=(int(data["target_version"]) if data.get("target_version") else None),
                    healing_total=int(data["resolution_total"]),
                )
                combat_done = self.combat.confirm_feature_action(
                    campaign_id,
                    _text(data["combat_id"]),
                    feature_command,
                    idempotency_key=f"content-ir:{key}:combat",
                    runtime_action=runtime_action,
                )
        except Exception:
            self.spells.rollback_spell_cast(
                campaign_id,
                idempotency_key=spell_key,
                expected_character_version=expected_character_version,
            )
            raise
        output = {
            "schema_version": PRODUCTION_SCHEMA,
            "runtime_id": data.get("runtime_id"),
            "production_runtime_full": True,
            "preview_token": token,
            "consumer": "spell_economy.concentration.v1" if blocks.get("concentration") else "combat_engine.damage_heal.v1",
            "spell_cast": spell_done,
            "combat": combat_done,
            "upcast": {"slot_level": data.get("slot_level")},
            "concentration": bool(data.get("concentration")),
        }
        self._record_operation(campaign_id, key, output)
        return output
