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
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import (
    CombatActionCommand,
    CombatFeatureActionCommand,
    CombatSummonCommand,
)
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import (
    Character,
    Combat,
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
    def _character_snapshot(character: Character) -> dict[str, Any]:
        """Return the character fields owned by the typed growth consumer."""

        return {
            "character_id": character.id,
            "version": character.version,
            "level": character.level,
            "features": deepcopy(list(character.features or [])),
            "actions": deepcopy(list(character.actions or [])),
            "proficiencies": deepcopy(list(character.proficiencies or [])),
            "skills": deepcopy(dict(character.skills or {})),
            "spells": deepcopy(list(character.spells or [])),
            "resources": deepcopy(dict(character.resources or {})),
        }

    @staticmethod
    def _choice_value(
        block: Mapping[str, Any],
        choices: Mapping[str, list[str]],
        *,
        required: bool,
    ) -> str | None:
        keys = (
            _text(block.get("id")),
            _text(block.get("asset_id")),
            _text(block.get("language_id")),
            _text(block.get("kind")),
        )
        values: list[str] = []
        for key in keys:
            if key and key in choices:
                values.extend(_text(item) for item in choices[key] if _text(item))
        values = list(dict.fromkeys(values))
        if len(values) > 1:
            raise ValueError("advancement choice accepts exactly one typed value")
        if required and not values:
            raise ValueError(
                "advancement runtime requires a choice for "
                + (_text(block.get("asset_id")) or _text(block.get("kind")))
            )
        return values[0] if values else None

    @staticmethod
    def _requires_choice(value: object) -> bool:
        text = _text(value).lower()
        return text.startswith("chosen_") or text.endswith("_choice") or "_or_" in text

    def _advancement_runtime(
        self,
        session: Session,
        campaign_id: str,
        data: Mapping[str, Any],
    ) -> tuple[Character, dict[str, Any], dict[str, list[dict[str, Any]]], tuple[dict[str, Any], ...]]:
        character_id = _text(data.get("character_id"))
        character = session.get(Character, character_id)
        if character is None or character.campaign_id != campaign_id:
            raise StateNotFoundError("content runtime advancement character not found")
        expected_version = int(data.get("character_version") or 0)
        if character.version != expected_version:
            raise VersionConflict("character", character.id, expected_version, character.version)
        runtime = data.get("runtime_contract")
        if not isinstance(runtime, Mapping):
            raise ValueError("advancement runtime contract must be an object")
        runtime = deepcopy(dict(runtime))
        runtime_id = _text(data.get("runtime_id"))
        if _text(runtime.get("automation_status")) != "full":
            raise ValueError("advancement runtime is not full")
        if runtime.get("requires_dm_adjudication") is True:
            raise ValueError("advancement runtime requires DM adjudication")
        blocks: dict[str, list[dict[str, Any]]] = {}
        for section in ("advancement", "prepared_spell_list"):
            value = runtime.get(section)
            if isinstance(value, Mapping):
                blocks[section] = [dict(value)]
        proficiencies = runtime.get("proficiencies")
        if isinstance(proficiencies, list) and proficiencies:
            blocks["proficiencies"] = [dict(item) for item in proficiencies if isinstance(item, Mapping)]
        resources = runtime.get("resources")
        if isinstance(resources, Mapping) and resources:
            blocks["resources"] = [
                {"key": str(key), **dict(value)}
                for key, value in resources.items()
                if isinstance(value, Mapping)
            ]
        for block in [item for values in blocks.values() for item in values]:
            block_feature_id = _text(block.get("feature_id"))
            if block_feature_id and block_feature_id != runtime_id:
                raise ValueError("advancement runtime id does not match the typed feature contract")
            execution = block.get("runtime_execution")
            if not isinstance(execution, Mapping) or _text(execution.get("status")) != "ready":
                raise ValueError("advancement runtime block is not execution-ready")
        consumers = resolve_production_consumers(
            content_kind="advancement",
            runtime_schema_version="feature-runtime-1",
            blocks=blocks,
        )
        return character, runtime, blocks, consumers

    def _preview_advancement(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session:
            character, runtime, blocks, consumers = self._advancement_runtime(
                session, campaign_id, data
            )
            before = self._character_snapshot(character)
            after = deepcopy(before)
            choices = data.get("advancement_choices") or {}
            if not isinstance(choices, Mapping):
                raise ValueError("advancement_choices must be an object")
            typed_choices = {
                _text(key): [_text(item) for item in value if _text(item)]
                for key, value in choices.items()
                if _text(key) and isinstance(value, list)
            }
            feature_id = _text(data.get("runtime_id"))
            feature_name = _text(runtime.get("feature_name")) or feature_id
            proficiencies: list[dict[str, Any]] = []
            skills = dict(after["skills"])
            sheet_proficiencies = list(after["proficiencies"])
            for block in blocks.get("proficiencies", []):
                if _text(block.get("operation")) != "grant":
                    raise ValueError("advancement growth currently accepts grant operations only")
                kind = _text(block.get("kind")) or "proficiency"
                asset = _text(block.get("asset_id")) or _text(block.get("name"))
                selected = self._choice_value(
                    block,
                    typed_choices,
                    required=self._requires_choice(asset) or self._requires_choice(block.get("language_id")),
                )
                value = selected or _text(block.get("language_id")) or asset
                if not value:
                    raise ValueError("advancement proficiency block lacks a typed asset")
                if kind == "language":
                    persisted = "语言：" + value
                elif kind == "skill":
                    persisted = value
                    existing = dict(skills.get(value) or {})
                    skills[value] = {
                        **existing,
                        "proficient": True,
                        "source_feature_id": feature_id,
                    }
                else:
                    persisted = value
                if kind != "skill" and persisted not in sheet_proficiencies:
                    sheet_proficiencies.append(persisted)
                proficiencies.append(
                    {
                        "kind": kind,
                        "value": persisted,
                        "source_feature_id": feature_id,
                    }
                )

            spell_grants: list[dict[str, Any]] = []
            sheet_spells = list(after["spells"])
            advancement_blocks = [*blocks.get("advancement", []), *blocks.get("prepared_spell_list", [])]
            for block in advancement_blocks:
                raw_grants = block.get("spell_grants")
                grants = raw_grants if isinstance(raw_grants, list) else [block]
                for grant in grants:
                    if not isinstance(grant, Mapping):
                        continue
                    for raw_spell_id in grant.get("spells") or []:
                        spell_id = _text(raw_spell_id)
                        if not spell_id:
                            continue
                        selected = self._choice_value(
                            {"id": spell_id, "asset_id": spell_id},
                            typed_choices,
                            required=self._requires_choice(spell_id),
                        )
                        resolved_spell_id = selected or spell_id
                        source_id = f"{feature_id}:{resolved_spell_id}"
                        entry = {
                            "name": resolved_spell_id,
                            "spell_id": resolved_spell_id,
                            "spell_level": 0,
                            "class_name": _text(grant.get("grant_class")),
                            "spellcasting_ability": _text(grant.get("casting_ability")),
                            "grant_mode": _text(grant.get("grant_mode")),
                            "prepared": _text(grant.get("grant_mode")) == "always_prepared",
                            "always_prepared": _text(grant.get("grant_mode")) == "always_prepared",
                            "source_record_id": source_id,
                            "source_feature_id": feature_id,
                            "granted_spell_access": True,
                            "does_not_count_toward_level_learning": True,
                        }
                        if not any(
                            isinstance(item, Mapping)
                            and _text(item.get("source_record_id")) == source_id
                            for item in sheet_spells
                        ):
                            sheet_spells.append(entry)
                        spell_grants.append(entry)

            resource_grants: list[dict[str, Any]] = []
            resources = dict(after["resources"])
            proficiency_bonus = 2 + (max(1, int(character.level or 1)) - 1) // 4
            for block in blocks.get("resources", []):
                resource_key = _text(block.get("key") or block.get("resource_key"))
                if not resource_key:
                    raise ValueError("advancement resource block lacks a key")
                maximum = block.get("maximum", block.get("max"))
                if maximum is None and _text(block.get("max_formula")) == "2 * proficiency_bonus":
                    maximum = 2 * proficiency_bonus
                if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
                    raise ValueError("advancement resource block lacks a resolvable maximum")
                previous = resources.get(resource_key)
                previous = dict(previous) if isinstance(previous, Mapping) else {}
                entry = {
                    **previous,
                    "key": resource_key,
                    "current": maximum,
                    "maximum": maximum,
                }
                for field in (
                    "resource_kind",
                    "die_size",
                    "max_formula",
                    "recovery",
                    "recovery_events",
                ):
                    if field in block:
                        entry[field] = deepcopy(block[field])
                resources[resource_key] = entry
                resource_grants.append(deepcopy(entry))

            feature_entry = {
                "feature_id": feature_id,
                "name": feature_name,
                "kind": "content_ir_feature",
                "class_name": _text(runtime.get("class_name")),
                "class_level": int(runtime.get("class_level") or 0),
                "source_record_id": _text(runtime.get("source_record_id")),
                "runtime": {"registry": runtime, "source": "content_ir"},
            }
            features = [
                item
                for item in after["features"]
                if not (isinstance(item, Mapping) and _text(item.get("feature_id")) == feature_id)
            ]
            features.append(feature_entry)
            after.update(
                {
                    "features": features,
                    "proficiencies": sheet_proficiencies,
                    "skills": skills,
                    "spells": sheet_spells,
                    "resources": resources,
                }
            )
            result = {
                "schema_version": RUNTIME_PREVIEW_SCHEMA,
                "content_kind": "advancement",
                "runtime_id": feature_id,
                "runtime_preview_full": True,
                "character_id": character.id,
                "character_version": character.version,
                "before": before,
                "after": after,
                "feature_grant": feature_entry,
                "proficiency_grants": proficiencies,
                "spell_grants": spell_grants,
                "resource_grants": resource_grants,
                "production_contract": {
                    "content_kind": "advancement",
                    "consumers": [str(item["consumer_id"]) for item in consumers],
                    "requires_character_cas": True,
                    "requires_idempotency": True,
                    "typed_sections": sorted(blocks),
                },
            }
            result["preview_token"] = _fingerprint(
                {"data": _stable_request_data(data), "result": result}
            )
            return result

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
    def _spell_context(
        actor: Combatant,
        spell: KnownSpell,
    ) -> dict[str, Any]:
        """Resolve typed spell-context modifiers from the actor snapshot.

        The context predicate is data carried by the authored Feature IR.  A
        spell must explicitly opt into the psionic context in its persisted
        metadata; no spell or feature display name participates in dispatch.
        """

        metadata = dict(spell.metadata_json or {})
        if spell.spell_level < 1 or metadata.get("psionic_spell") is not True:
            return {}
        feature_runtime = actor.snapshot_json.get("feature_runtime")
        direct_context = (
            feature_runtime.get("spell_context")
            if isinstance(feature_runtime, Mapping)
            else None
        )
        combat_start = feature_runtime.get("combat_start") if isinstance(feature_runtime, Mapping) else None
        modifiers = combat_start.get("modifiers") if isinstance(combat_start, Mapping) else None
        modifiers = [
            *(direct_context if isinstance(direct_context, list) else []),
            *(modifiers if isinstance(modifiers, list) else []),
        ]
        components: list[dict[str, Any]] = []
        payments: list[dict[str, Any]] = []
        for modifier in modifiers:
            if not isinstance(modifier, Mapping):
                continue
            parameters = modifier.get("parameters")
            parameters = parameters if isinstance(parameters, Mapping) else modifier
            if _text(parameters.get("applies_when")) != "psionic_spell":
                continue
            operator = _text(modifier.get("operator") or parameters.get("operator"))
            if operator == "override_spell_components":
                components.append(dict(parameters))
            elif operator == "override_spell_payment":
                payments.append(dict(parameters))
        if len(payments) > 1:
            raise ValueError("spell runtime has multiple typed payment overrides")
        return {
            "component_override": components[0] if components else None,
            "payment_override": payments[0] if payments else None,
            "source_feature_ids": sorted(
                {
                    _text(modifier.get("feature_id"))
                    for modifier in modifiers
                    if isinstance(modifier, Mapping)
                    and _text(modifier.get("feature_id"))
                    and _text(
                        (modifier.get("parameters") or modifier).get("applies_when")
                        if isinstance(modifier.get("parameters") or modifier, Mapping)
                        else ""
                    )
                    == "psionic_spell"
                }
            ),
        }

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
        for block in blocks.get("effects", []):
            parameters = ContentIRRuntimeService._parameters(block)
            if _text(parameters.get("type")) == "summon_or_creation":
                return _text(parameters.get("action_economy")) or "none"
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
            progression = upcast.get("progression")
            if source_level == 0 and isinstance(progression, list):
                caster_level = int(data.get("caster_level") or 0)
                selected_expression: str | None = None
                selected_level = 0
                for step in progression:
                    if not isinstance(step, Mapping):
                        continue
                    try:
                        threshold = int(step.get("character_level") or 0)
                    except (TypeError, ValueError):
                        continue
                    expression_value = _text(step.get("expression"))
                    if threshold > selected_level and threshold <= caster_level and expression_value:
                        selected_level = threshold
                        selected_expression = expression_value
                scaled_bounds = cls._roll_bounds(selected_expression)
                if scaled_bounds is not None:
                    bounds = scaled_bounds
            else:
                per_slot = int(upcast.get("per_slot") or 1)
                delta = max(0, slot_level - source_level)
                increment = cls._roll_bounds(upcast.get("increments"))
                if increment is not None:
                    bounds = (
                        bounds[0] + delta * per_slot * increment[0],
                        bounds[1] + delta * per_slot * increment[1],
                    )
        value = int(amount)
        if bounds is not None and not bounds[0] <= value <= bounds[1]:
            kind = "healing" if healing else "damage"
            raise ValueError(f"{kind} roll must be between {bounds[0]} and {bounds[1]}")
        return value

    @staticmethod
    def _runtime_target_ids(data: Mapping[str, Any]) -> list[str]:
        target_ids = [
            item
            for item in [_text(data.get("target_combatant_id")), *data.get("target_combatant_ids", [])]
            if item
        ]
        if not target_ids:
            raise ValueError("production spell runtime requires a target")
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("production spell runtime target ids must be unique")
        return target_ids

    @staticmethod
    def _text_list(value: object, *, field: str) -> list[str]:
        raw_values = [value] if isinstance(value, str) else value
        if not isinstance(raw_values, list):
            raise ValueError(f"typed spell defense field {field} must be a string list")
        values = [str(item).strip().lower() for item in raw_values if str(item).strip()]
        if not values:
            raise ValueError(f"typed spell defense field {field} must not be empty")
        return list(dict.fromkeys(values))

    @classmethod
    def _spell_defense_contract(
        cls,
        data: Mapping[str, Any],
        blocks: Mapping[str, list[dict[str, Any]]],
        *,
        runtime_id: str,
        runtime_level: int,
        caster_level: int,
    ) -> dict[str, Any] | None:
        modifier_blocks = [
            cls._parameters(block)
            for block in blocks.get("effects", [])
            if cls._parameters(block).get("type") == "spell_modifier"
        ]
        if not modifier_blocks:
            return None
        components: list[dict[str, Any]] = []
        for modifier in modifier_blocks:
            operator = _text(modifier.get("modifier")).lower()
            value = modifier.get("value")
            if operator in {"damage_resistance", "resistance"}:
                components.append(
                    {
                        "kind": "defense",
                        "operation": "resistance",
                        "damage_types": cls._text_list(value, field="value"),
                        "source": runtime_id,
                    }
                )
            elif operator in {"saving_throw_advantage", "saving_advantage"}:
                abilities = modifier.get("applies_to")
                if abilities in (None, ""):
                    abilities = value
                components.append(
                    {
                        "kind": "modifier",
                        "stat": "saving_throw",
                        "scope": "all",
                        "operation": "advantage",
                        "abilities": cls._text_list(abilities, field="applies_to"),
                        "source": runtime_id,
                        "applies_when": "always",
                    }
                )
            else:
                raise ValueError(f"unsupported typed spell modifier: {operator}")
        target = cls._first_parameters(blocks, "target_selection")
        target_count = int(target.get("count") or 1)
        if target_count < 1:
            raise ValueError("typed spell target count must be positive")
        range_ft = target.get("range_ft", target.get("range"))
        if range_ft is None:
            range_ft = data.get("spell_range_ft")
        if isinstance(range_ft, str):
            range_match = re.search(r"\d+", range_ft)
            range_ft = int(range_match.group(0)) if range_match else None
        if range_ft is not None and (
            isinstance(range_ft, bool) or not isinstance(range_ft, (int, float)) or int(range_ft) < 0
        ):
            raise ValueError("typed spell target range must be a non-negative number")
        range_ft = int(range_ft) if range_ft is not None else None
        max_target_distance_ft = target.get(
            "max_distance_ft",
            target.get("max_target_distance_ft"),
        )
        if max_target_distance_ft is not None:
            max_target_distance_ft = int(max_target_distance_ft)
            if max_target_distance_ft < 0:
                raise ValueError("typed spell target group distance must be non-negative")
        upcast = cls._first_parameters(blocks, "upcast")
        increment = int(upcast.get("target_count_increment") or 0)
        minimum_slot = int(upcast.get("minimum_slot") or runtime_level + 1)
        slot_level = int(data.get("slot_level") or 0)
        maximum_count = target_count
        if increment:
            if slot_level >= minimum_slot:
                maximum_count += max(0, slot_level - runtime_level) * increment
        elif slot_level > runtime_level:
            maximum_count = target_count
        target_ids = cls._runtime_target_ids(data)
        if len(target_ids) > maximum_count:
            raise ValueError(f"typed spell runtime allows at most {maximum_count} targets")
        if len(target_ids) < target_count:
            raise ValueError(f"typed spell runtime requires at least {target_count} target")
        target_versions = dict(data.get("target_versions") or {})
        if data.get("target_combatant_id"):
            target_versions.setdefault(
                _text(data.get("target_combatant_id")),
                int(data.get("target_version") or 0),
            )
        if any(int(target_versions.get(item) or 0) < 1 for item in target_ids):
            raise ValueError("typed spell runtime requires every target version")
        return {
            "name": _text(data.get("runtime_name")) or runtime_id,
            "rule_block": {
                "kind": "defense_bundle",
                "spell_id": runtime_id,
                "known_spell_id": _text(data.get("known_spell_id")),
                "components": components,
            },
            "target_ids": target_ids,
            "target_versions": {item: int(target_versions[item]) for item in target_ids},
            "range_ft": range_ft,
            "require_visible": str(target.get("visibility") or "").lower() == "visible",
            "max_target_distance_ft": max_target_distance_ft,
            "slot_level": slot_level,
            "maximum_target_count": maximum_count,
            "runtime_level": runtime_level,
            "caster_level": caster_level,
        }

    @classmethod
    def _spell_summon_contract(
        cls,
        data: Mapping[str, Any],
        blocks: Mapping[str, list[dict[str, Any]]],
        *,
        runtime_id: str,
        runtime_name: str,
        runtime_level: int,
        caster_level: int,
    ) -> dict[str, Any] | None:
        """Resolve a typed summon stat block without dispatching on its name."""

        summon = next(
            (
                cls._parameters(block)
                for block in blocks.get("effects", [])
                if cls._parameters(block).get("type") == "summon_or_creation"
            ),
            None,
        )
        if not summon:
            return None
        if _text(summon.get("kind")).lower() != "summon":
            raise ValueError("typed spell summon kind is unsupported")
        stat_block_id = _text(summon.get("stat_block_id"))
        template = summon.get("template")
        if not stat_block_id or not isinstance(template, Mapping):
            raise ValueError("typed spell summon requires a stat block template")
        template = deepcopy(dict(template))
        choice_key = _text(summon.get("choice_key"))
        choice_values = [
            _text(value)
            for value in (summon.get("choice_values") or [])
            if _text(value)
        ]
        choice = _text(data.get("summon_choice"))
        if choice_values:
            if not choice:
                if summon.get("choice_required") is True:
                    raise ValueError(f"typed spell summon requires {choice_key} choice")
                choice = choice_values[0]
            if choice not in choice_values:
                raise ValueError(
                    f"typed spell summon choice must be one of {', '.join(choice_values)}"
                )
        variants = template.get("variants")
        variant: dict[str, Any] = {}
        if isinstance(variants, Mapping):
            raw_variant = variants.get(choice) if choice else variants.get("default")
            if not isinstance(raw_variant, Mapping):
                raise ValueError("typed spell summon choice has no stat block variant")
            variant = deepcopy(dict(raw_variant))
        else:
            variant = deepcopy(template)

        scaling = summon.get("scaling")
        scaling = dict(scaling) if isinstance(scaling, Mapping) else {}
        base_level = int(scaling.get("base_level") or runtime_level)
        if base_level < 0 or base_level > 9:
            raise ValueError("typed spell summon base level is invalid")
        slot_level = int(data.get("slot_level") or 0)
        if slot_level < runtime_level:
            raise ValueError("typed spell summon slot level is below spell level")
        slot_delta = max(0, slot_level - base_level)

        def scaled_int(field: str, *, default: int | None = None) -> int | None:
            raw = variant.get(field, template.get(field, default))
            if raw is None:
                return default
            if isinstance(raw, bool):
                raise ValueError(f"typed spell summon {field} must be an integer")
            if isinstance(raw, int):
                return raw + slot_delta * int(scaling.get(f"{field}_per_slot") or 0)
            expression = _text(raw)
            if expression == "11 + spell_level":
                return 11 + slot_level
            match = re.fullmatch(r"(\d+)\s*\+\s*spell_level", expression)
            if match:
                return int(match.group(1)) + slot_level
            raise ValueError(f"typed spell summon {field} is not executable")

        hp = scaled_int("hp")
        if hp is None:
            raise ValueError("typed spell summon requires HP")
        max_hp = hp
        armor_class = scaled_int("armor_class")
        speed_ft = scaled_int("speed_ft")
        ability_scores = variant.get("ability_scores", template.get("ability_scores", {}))
        if not isinstance(ability_scores, Mapping):
            raise ValueError("typed spell summon ability_scores must be an object")
        actions = variant.get("actions", template.get("actions", []))
        if not isinstance(actions, list) or not actions:
            raise ValueError("typed spell summon requires structured actions")
        target = cls._first_parameters(blocks, "target_selection")
        range_ft = int(target["range_ft"]) if target.get("range_ft") is not None else None
        if range_ft is None:
            raise ValueError("typed spell summon requires an explicit range")
        destination_row = data.get("destination_row")
        destination_col = data.get("destination_col")
        if destination_row is None or destination_col is None:
            raise ValueError("typed spell summon requires a destination position")
        duration = summon.get("duration")
        duration_unit = "until_removed"
        duration_value: int | None = None
        if isinstance(duration, Mapping):
            duration_unit = _text(duration.get("unit")) or duration_unit
            if duration.get("value") is not None:
                duration_value = int(duration["value"])
        elif _text(duration).lower() in {"rounds", "minutes"}:
            duration_unit = _text(duration).lower()
        if duration_unit in {"rounds", "minutes"} and duration_value is None:
            raise ValueError("typed spell summon timed duration requires a value")
        if duration_unit not in {"rounds", "minutes", "until_removed"}:
            raise ValueError("typed spell summon duration unit is unsupported")
        require_visible = _text(target.get("visibility")).lower() == "visible"
        action_economy = _text(summon.get("action_economy")) or "action"
        if action_economy not in {"action", "bonus_action", "reaction", "none"}:
            raise ValueError("typed spell summon action economy is unsupported")
        movement_modes = variant.get("movement_modes", template.get("movement_modes", []))
        if not isinstance(movement_modes, list) or any(
            not isinstance(item, Mapping)
            or not _text(item.get("mode"))
            or (
                item.get("speed_ft") is not None
                and (
                    isinstance(item.get("speed_ft"), bool)
                    or not isinstance(item.get("speed_ft"), int)
                    or item.get("speed_ft") < 0
                )
            )
            for item in movement_modes
        ):
            raise ValueError("typed spell summon movement_modes must be structured")
        default_behavior = summon.get("default_behavior") or {}
        if not isinstance(default_behavior, Mapping):
            raise ValueError("typed spell summon default_behavior must be structured")
        return {
            "name": _text(summon.get("name")) or runtime_name,
            "choice_key": choice_key or None,
            "choice": choice or None,
            "choice_values": choice_values,
            "stat_block_id": stat_block_id,
            "count": int(summon.get("count") or 1),
            "range_ft": range_ft,
            "require_visible": require_visible,
            "requires_unoccupied": target.get("requires_unoccupied") is True,
            "destination": {
                "row": int(destination_row),
                "col": int(destination_col),
            },
            "controller": _text(summon.get("controller")) or "player",
            "disposition": _text(summon.get("disposition")) or "ally",
            "initiative_mode": _text(summon.get("initiative_mode")) or "shared_with_source",
            "action_economy": action_economy,
            "requires_concentration": summon.get("requires_concentration") is True,
            "default_behavior": deepcopy(dict(default_behavior)),
            "duration_unit": duration_unit,
            "duration_value": duration_value,
            "movement_modes": deepcopy(movement_modes),
            "template": {
                **template,
                "stat_block_id": stat_block_id,
                "choice": choice,
                "choice_key": choice_key or None,
                "variant": variant,
                "hp": hp,
                "max_hp": max_hp,
                "armor_class": armor_class,
                "speed_ft": speed_ft,
                "ability_scores": dict(ability_scores),
                "actions": deepcopy(actions),
                "movement_modes": deepcopy(movement_modes),
                "damage_resistances": list(
                    variant.get("damage_resistances", template.get("damage_resistances", []))
                    or []
                ),
                "damage_vulnerabilities": list(
                    variant.get(
                        "damage_vulnerabilities",
                        template.get("damage_vulnerabilities", []),
                    )
                    or []
                ),
                "damage_immunities": list(
                    variant.get("damage_immunities", template.get("damage_immunities", []))
                    or []
                ),
                "condition_immunities": list(
                    variant.get(
                        "condition_immunities",
                        template.get("condition_immunities", []),
                    )
                    or []
                ),
            },
            "scaling": {
                "base_level": base_level,
                "slot_level": slot_level,
                "slot_delta": slot_delta,
                "caster_level": caster_level,
            },
        }

    @staticmethod
    def _spell_summon_command(
        data: Mapping[str, Any],
        contract: Mapping[str, Any],
        *,
        runtime_id: str,
        known_spell_id: str,
        actor_id: str,
        actor_version: int,
        character_id: str,
    ) -> CombatSummonCommand:
        template = dict(contract["template"])
        return CombatSummonCommand(
            count=int(contract["count"]),
            name=str(contract["name"]),
            controller=str(contract["controller"]),
            owner_character_id=character_id,
            disposition=str(contract["disposition"]),
            source_combatant_id=actor_id,
            source_version=actor_version,
            position=dict(contract["destination"]),
            range_ft=int(contract["range_ft"]),
            require_visible=bool(contract["require_visible"]),
            requires_unoccupied=bool(contract["requires_unoccupied"]),
            initiative_mode=str(contract["initiative_mode"]),
            action_cost=str(contract["action_economy"]),
            duration_unit=str(contract["duration_unit"]),
            duration_value=(
                int(contract["duration_value"])
                if contract.get("duration_value") is not None
                else None
            ),
            requires_concentration=bool(contract["requires_concentration"]),
            hp=int(template["hp"]),
            max_hp=int(template["max_hp"]),
            armor_class=int(template["armor_class"]),
            speed_ft=int(template["speed_ft"]),
            ability_scores=dict(template["ability_scores"]),
            actions=list(template["actions"]),
            movement_modes=list(contract.get("movement_modes") or []),
            damage_resistances=list(template.get("damage_resistances") or []),
            damage_vulnerabilities=list(template.get("damage_vulnerabilities") or []),
            damage_immunities=list(template.get("damage_immunities") or []),
            condition_immunities=list(template.get("condition_immunities") or []),
            template_json={
                "spell_id": runtime_id,
                "known_spell_id": known_spell_id,
                "stat_block_id": contract["stat_block_id"],
                "choice_key": contract.get("choice_key"),
                "choice": contract.get("choice"),
                "default_behavior": deepcopy(contract.get("default_behavior") or {}),
                "scaling": deepcopy(contract.get("scaling") or {}),
                "template": template,
            },
        )

    def _spell_commands(
        self,
        data: Mapping[str, Any],
        blocks: Mapping[str, list[dict[str, Any]]],
    ) -> list[CombatActionCommand] | None:
        target_ids = self._runtime_target_ids(data)
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
            actor = session.get(Combatant, _text(data.get("actor_combatant_id")))
            if actor is None or actor.combat_id != _text(data.get("combat_id")):
                raise StateNotFoundError("content runtime spell actor not found")
            combat = session.get(Combat, _text(data.get("combat_id")))
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("content runtime spell combat not found")
            spell_context = self._spell_context(actor, spell)
            execution_data = {
                **data,
                "runtime_level": runtime.get("level"),
                "caster_level": int(character.level or 0),
            }
            consumers = resolve_production_consumers(
                content_kind="spell",
                runtime_schema_version=str(runtime.get("runtime_schema_version") or ""),
                blocks=blocks,
            )
            defense_contract = self._spell_defense_contract(
                execution_data,
                blocks,
                runtime_id=_text(runtime.get("spell_id")),
                runtime_level=int(runtime.get("level") or 0),
                caster_level=int(character.level or 0),
            )
            summon_contract = self._spell_summon_contract(
                execution_data,
                blocks,
                runtime_id=_text(runtime.get("spell_id")),
                runtime_name=_text(runtime.get("name")),
                runtime_level=int(runtime.get("level") or 0),
                caster_level=int(character.level or 0),
            )
            summon_preview = None
            if summon_contract is not None:
                summon_preview = {
                    **deepcopy(summon_contract),
                    "geometry": self.combat.validate_summon_position(
                        session,
                        combat,
                        actor,
                        (
                            int(summon_contract["destination"]["row"]),
                            int(summon_contract["destination"]["col"]),
                        ),
                        range_ft=int(summon_contract["range_ft"]),
                        require_visible=bool(summon_contract["require_visible"]),
                        requires_unoccupied=bool(summon_contract["requires_unoccupied"]),
                    ),
                }
            commands = (
                None
                if defense_contract is not None or summon_contract is not None
                else self._spell_commands(execution_data, blocks)
            )
            combat_preview = None
            if defense_contract is not None:
                if not blocks.get("concentration") or data.get("concentration") is not True:
                    raise ValueError(
                        "typed spell defense runtime requires concentration=True"
                    )
                combat_preview = self.combat.preview_spell_defense(
                    campaign_id,
                    _text(data.get("combat_id")),
                    source_combatant_id=actor.id,
                    source_version=int(data.get("actor_version") or 0),
                    target_combatant_ids=defense_contract["target_ids"],
                    target_versions=defense_contract["target_versions"],
                    name=defense_contract["name"],
                    rule_block=defense_contract["rule_block"],
                    range_ft=defense_contract["range_ft"],
                    require_visible=defense_contract["require_visible"],
                    max_target_distance_ft=defense_contract["max_target_distance_ft"],
                )
            elif commands is not None:
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
                "spell_context": spell_context,
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
                    "requires_target": commands is not None or summon_contract is not None,
                    "requires_resolution_input": commands is not None,
                    "requires_cas": True,
                    "requires_idempotency": True,
                    "caster_level": int(character.level or 0),
                    "spell_context": spell_context,
                    "consumers": [str(item["consumer_id"]) for item in consumers],
                    "area_batch": len(commands or []) > 1,
                    "defense": defense_contract,
                    "summon": summon_preview,
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
            teleport_preview = None
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
            elif _text(action.get("resolution_kind")) == "communication":
                self._validate_communication_condition(actor, target, action)
                feature_blocks = {"communication": [action]}
                combat_preview = None
            elif _text(action.get("resolution_kind")) == "inspection":
                feature_blocks = {"passive_registry": [action.get("passive_block") or action]}
                combat_preview = None
            elif _text(action.get("resolution_kind")) in {
                "reaction_window",
                "triggered_attack_window",
                "resource_exchange",
            }:
                feature_blocks = {"feature_event_window": [action]}
                combat_preview = None
            else:
                if _text(action.get("resolution_kind")) == "teleport":
                    raw_roll = data.get("movement_roll_total")
                    if (
                        not isinstance(raw_roll, int)
                        or isinstance(raw_roll, bool)
                        or raw_roll < 1
                    ):
                        raise ValueError("传送特性预览需要明确的正整数灵能骰结果")
                    if data.get("destination_row") is None or data.get("destination_col") is None:
                        raise ValueError("传送特性预览需要明确的目的地行列")
                    teleport_effect = next(
                        (
                            item
                            for item in action.get("effects", [])
                            if isinstance(item, Mapping) and item.get("kind") == "teleport"
                        ),
                        None,
                    )
                    if not isinstance(teleport_effect, Mapping):
                        raise ValueError("传送特性缺少结构化 teleport effect")
                    multiplier = int(teleport_effect.get("roll_multiplier_ft") or 0)
                    if multiplier < 1:
                        raise ValueError("传送特性缺少正整数距离倍率")
                    teleport_preview = {
                        "movement_roll_total": raw_roll,
                        "roll_input": _text(teleport_effect.get("roll_input")),
                        "roll_source": _text(teleport_effect.get("roll_source")),
                        "max_distance_ft": raw_roll * multiplier,
                        "destination": {
                            "row": int(data["destination_row"]),
                            "col": int(data["destination_col"]),
                        },
                    }
                else:
                    teleport_preview = None
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
            if teleport_preview is not None:
                result["production_contract"]["teleport"] = teleport_preview
            if _text(action.get("resolution_kind")) == "communication":
                result["communication"] = {
                    "channel": _text(action.get("channel")),
                    "direction": _text(action.get("direction")),
                    "required_condition": _text(action.get("required_condition")),
                    "mutual_comprehension": True,
                }
            result["preview_token"] = _fingerprint(
                {"data": _stable_request_data(data), "result": result}
            )
            return result

    def _confirm_advancement(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        key = _text(data.get("idempotency_key"))
        if len(key) < 8:
            raise ValueError("content runtime idempotency_key is required")
        operation_key = f"content-ir:{key}"
        with Session(self.engine) as session:
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == operation_key,
                )
            )
            if existing is not None:
                return {**dict(existing.after_snapshot or {}), "already_applied": True}
        preview = self._preview_advancement(campaign_id, data)
        token = _text(data.get("preview_token"))
        if token != _text(preview.get("preview_token")):
            raise VersionConflict("content runtime advancement preview", key, 1, 2)
        expected_version = int(data["character_version"])
        after = dict(preview["after"])
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == operation_key,
                )
            )
            if existing is not None:
                return {**dict(existing.after_snapshot or {}), "already_applied": True}
            operation = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="content_ir_advancement",
                idempotency_key=operation_key,
                status="applied",
                before_snapshot=preview["before"],
                after_snapshot=after,
                reason="typed Content IR advancement confirmed",
                source="dm",
                confirmed_at=now,
            )
            session.add(operation)
            session.flush()
            outcome = session.execute(
                update(Character)
                .where(
                    Character.id == _text(data["character_id"]),
                    Character.campaign_id == campaign_id,
                    Character.version == expected_version,
                )
                .values(
                    features=list(after["features"]),
                    actions=list(after["actions"]),
                    proficiencies=list(after["proficiencies"]),
                    skills=dict(after["skills"]),
                    spells=list(after["spells"]),
                    resources=dict(after["resources"]),
                    version=expected_version + 1,
                    updated_at=now,
                )
            )
            if outcome.rowcount != 1:
                actual = session.scalar(
                    select(Character.version).where(
                        Character.id == _text(data["character_id"]),
                        Character.campaign_id == campaign_id,
                    )
                )
                raise VersionConflict(
                    "character",
                    _text(data["character_id"]),
                    expected_version,
                    int(actual or 0),
                )
            output = {
                "schema_version": PRODUCTION_SCHEMA,
                "content_kind": "advancement",
                "runtime_id": data.get("runtime_id"),
                "production_runtime_full": True,
                "preview_token": token,
                "consumer": "advancement_service.character_growth.v1",
                "operation_transaction_id": operation.id,
                "character_id": data.get("character_id"),
                "character_version_after": expected_version + 1,
                "feature_grant": preview["feature_grant"],
                "proficiency_grants": preview["proficiency_grants"],
                "spell_grants": preview["spell_grants"],
                "resource_grants": preview["resource_grants"],
            }
            operation.after_snapshot = output
            session.flush()
            return output

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

    @staticmethod
    def _validate_communication_condition(
        actor: Combatant,
        target: Combatant,
        action: Mapping[str, Any],
    ) -> str:
        required_condition = _text(action.get("required_condition"))
        if not required_condition:
            raise ValueError("communication runtime requires a required_condition")
        if not CombatEngineService._has_condition(actor, required_condition):
            raise ValueError("communication requires the actor to satisfy the stated condition")
        if not CombatEngineService._has_condition(target, required_condition):
            raise ValueError("communication requires the target to satisfy the stated condition")
        return required_condition

    def preview(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if _text(data.get("content_kind")) == "spell":
            return self._preview_spell(campaign_id, data)
        if _text(data.get("content_kind")) == "feature":
            return self._preview_feature(campaign_id, data)
        if _text(data.get("content_kind")) == "advancement":
            return self._preview_advancement(campaign_id, data)
        raise ValueError("content_kind must be spell, feature, or advancement")

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

    def _confirm_communication(
        self,
        campaign_id: str,
        data: Mapping[str, Any],
        action: Mapping[str, Any],
        key: str,
        token: str,
    ) -> dict[str, Any]:
        actor_id = _text(data.get("actor_combatant_id"))
        target_id = _text(data.get("target_combatant_id")) or actor_id
        with Session(self.engine) as session:
            actor = session.get(Combatant, actor_id)
            if actor is None:
                raise StateNotFoundError("communication actor not found")
            if actor.version != int(data.get("actor_version") or 0):
                raise VersionConflict(
                    "combatant", actor.id, int(data.get("actor_version") or 0), actor.version
                )
            target = session.get(Combatant, target_id)
            if target is None or target.combat_id != actor.combat_id:
                raise StateNotFoundError("communication target not found in combat")
            if target_id != actor_id and target.version != int(data.get("target_version") or 0):
                raise VersionConflict(
                    "combatant", target.id, int(data.get("target_version") or 0), target.version
                )
            required_condition = self._validate_communication_condition(actor, target, action)
        output = {
            "schema_version": PRODUCTION_SCHEMA,
            "content_kind": "feature",
            "runtime_id": _text(data.get("runtime_id")),
            "production_runtime_full": True,
            "preview_token": token,
            "consumer": "communication.mutual_comprehension.v1",
            "communication": {
                "channel": _text(action.get("channel")),
                "direction": _text(action.get("direction")),
                "required_condition": required_condition,
                "actor_satisfies": True,
                "target_satisfies": True,
                "mutual_comprehension": True,
            },
            "actor_combatant_id": actor_id,
            "target_combatant_id": target_id,
        }
        self._record_operation(campaign_id, key, output)
        return output

    def confirm(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if _text(data.get("content_kind")) == "advancement":
            return self._confirm_advancement(campaign_id, data)
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
            if runtime_action.get("resolution_kind") == "communication":
                return self._confirm_communication(
                    campaign_id, data, runtime_action, key, token
                )
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
                reset_spell_slot_level=(
                    int(data["reset_spell_slot_level"])
                    if data.get("reset_spell_slot_level") is not None
                    else None
                ),
                destination_row=(
                    int(data["destination_row"]) if data.get("destination_row") is not None else None
                ),
                destination_col=(
                    int(data["destination_col"]) if data.get("destination_col") is not None else None
                ),
                movement_roll_total=(
                    int(data["movement_roll_total"])
                    if data.get("movement_roll_total") is not None
                    else None
                ),
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
                "consumer": str(
                    (preview.get("production_contract", {}).get("consumers") or [
                        "combat_engine.feature_action.v1"
                    ])[0]
                ),
                "result": result,
            }
            self._record_operation(campaign_id, key, output)
            return output

        cast_preview = preview["spell_preview"]
        with Session(self.engine) as session:
            _spell, character, runtime, blocks = self._spell_runtime(
                session, campaign_id, data
            )
            actor = session.get(Combatant, _text(data.get("actor_combatant_id")))
            if actor is None or actor.combat_id != _text(data.get("combat_id")):
                raise StateNotFoundError("content runtime spell actor not found")
            spell_context = self._spell_context(actor, _spell)
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
            "spell_context": spell_context,
            "preview_token": cast_preview["preview_token"],
            "idempotency_key": spell_key,
        }
        spell_done = self.spells.spell_confirm(campaign_id, cast_data)
        expected_character_version = int(spell_done.get("character_version_after") or int(data["character_version"]) + 1)
        try:
            execution_data = {
                **data,
                "runtime_level": runtime.get("level"),
                "caster_level": int(character.level or 0),
            }
            defense_contract = self._spell_defense_contract(
                execution_data,
                blocks,
                runtime_id=_text(runtime.get("spell_id")),
                runtime_level=int(runtime.get("level") or 0),
                caster_level=int(character.level or 0),
            )
            summon_contract = self._spell_summon_contract(
                execution_data,
                blocks,
                runtime_id=_text(runtime.get("spell_id")),
                runtime_name=_text(runtime.get("name")),
                runtime_level=int(runtime.get("level") or 0),
                caster_level=int(character.level or 0),
            )
            if defense_contract is not None:
                if not blocks.get("concentration") or data.get("concentration") is not True:
                    raise ValueError(
                        "typed spell defense runtime requires concentration=True"
                    )
                combat_done = self.combat.confirm_spell_defense(
                    campaign_id,
                    _text(data["combat_id"]),
                    source_combatant_id=_text(data["actor_combatant_id"]),
                    source_version=int(data["actor_version"]),
                    target_combatant_ids=defense_contract["target_ids"],
                    target_versions=defense_contract["target_versions"],
                    name=defense_contract["name"],
                    rule_block=defense_contract["rule_block"],
                    range_ft=defense_contract["range_ft"],
                    require_visible=defense_contract["require_visible"],
                    max_target_distance_ft=defense_contract["max_target_distance_ft"],
                    idempotency_key=f"content-ir:{key}:defense",
                )
            elif summon_contract is not None:
                if not summon_contract["requires_concentration"] or data.get("concentration") is not True:
                    raise ValueError("typed spell summon runtime requires concentration=True")
                summon_command = self._spell_summon_command(
                    data,
                    summon_contract,
                    runtime_id=_text(runtime.get("spell_id")),
                    known_spell_id=_text(data.get("known_spell_id")),
                    actor_id=_text(data.get("actor_combatant_id")),
                    actor_version=int(data.get("actor_version") or 0),
                    character_id=_text(data.get("character_id")),
                )
                combat_done = self.combat.add_summon(
                    campaign_id,
                    _text(data["combat_id"]),
                    summon_command,
                    idempotency_key=f"content-ir:{key}:summon",
                )
            else:
                commands = self._spell_commands(execution_data, blocks)
            if defense_contract is not None or summon_contract is not None:
                pass
            elif commands is not None:
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
            "consumer": (
                "spell.defense.v1"
                if defense_contract is not None
                else "spell.summon.v1"
                if summon_contract is not None
                else "spell_economy.concentration.v1"
                if blocks.get("concentration")
                else "combat_engine.damage_heal.v1"
            ),
            "spell_cast": spell_done,
            "combat": combat_done,
            "upcast": {"slot_level": data.get("slot_level")},
            "concentration": bool(data.get("concentration")),
        }
        self._record_operation(campaign_id, key, output)
        return output
