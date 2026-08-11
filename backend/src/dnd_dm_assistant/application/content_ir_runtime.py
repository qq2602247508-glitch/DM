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
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import CombatActionCommand, CombatFeatureActionCommand
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
        raw_action = actions.get(feature_id) if isinstance(actions, Mapping) else None
        if not isinstance(raw_action, Mapping) and isinstance(actions, Mapping):
            raw_action = next(
                (
                    item
                    for item in actions.values()
                    if isinstance(item, Mapping) and _text(item.get("feature_id")) == feature_id
                ),
                None,
            )
        if not isinstance(raw_action, Mapping):
            canonical = registry.get("canonical_actions")
            if isinstance(canonical, list):
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
            raise ValueError("combatant feature registry lacks the requested runtime action")
        action = dict(raw_action)
        if action.get("kind") != "feature_action":
            raise ValueError("feature runtime action is not production-ready")
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

    def _spell_command(
        self,
        data: Mapping[str, Any],
        blocks: Mapping[str, list[dict[str, Any]]],
    ) -> CombatActionCommand | None:
        target_id = _text(data.get("target_combatant_id"))
        target_version = int(data.get("target_version") or 0)
        actor_id = _text(data.get("actor_combatant_id"))
        actor_version = int(data.get("actor_version") or 0)
        if not target_id or target_version < 1:
            raise ValueError("production spell runtime requires a target and target version")
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
            amount = data.get("resolution_total")
            if amount is None:
                raise ValueError("damage runtime requires resolution_total")
            save_blocks = blocks.get("saving_throw") or []
            if save_blocks and data.get("save_succeeded") is None:
                raise ValueError("saving throw runtime requires save_succeeded")
            if save_blocks and data.get("save_succeeded") is True:
                save_parameters = self._parameters(save_blocks[0])
                amount = int(amount) // 2 if bool(save_parameters.get("half_on_success")) else 0
            attack = bool(blocks.get("attack_roll"))
            return CombatActionCommand(
                action_type="damage",
                target_combatant_id=target_id,
                target_version=target_version,
                actor_combatant_id=actor_id or None,
                actor_version=actor_version or None,
                action_cost=self._action_cost(blocks),
                action_name=_text(data.get("runtime_id")),
                amount=max(0, int(amount)),
                damage_type=_text(damage.get("damage_type")) or "force",
                is_attack=attack,
                is_spell_attack=attack,
                attack_ability="spellcasting" if attack else None,
                attack_roll_total=(int(data["attack_roll_total"]) if attack else None),
            )
        if healing:
            amount = data.get("resolution_total")
            if amount is None:
                raise ValueError("healing runtime requires resolution_total")
            return CombatActionCommand(
                action_type="heal",
                target_combatant_id=target_id,
                target_version=target_version,
                actor_combatant_id=actor_id or None,
                actor_version=actor_version or None,
                action_cost=self._action_cost(blocks),
                action_name=_text(data.get("runtime_id")),
                amount=max(0, int(amount)),
            )
        if temporary:
            return None
        raise ValueError("spell runtime has no supported production damage/healing block")

    def _preview_spell(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session:
            spell, character, runtime, blocks = self._spell_runtime(session, campaign_id, data)
            command = self._spell_command(data, blocks)
            combat_preview = None
            if command is not None:
                combat_preview = self.combat.preview(campaign_id, _text(data.get("combat_id")), command)
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
                    "requires_target": command is not None,
                    "requires_resolution_input": command is not None,
                    "requires_cas": True,
                    "requires_idempotency": True,
                    "consumer": "spell_economy_and_combat_engine",
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
            result = {
                "schema_version": RUNTIME_PREVIEW_SCHEMA,
                "runtime_id": _text(data.get("runtime_id")),
                "runtime_preview_full": True,
                "feature_action": action,
                "production_contract": {
                    "content_kind": "feature",
                    "consumer": "combat_engine.feature_action",
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
            command = CombatFeatureActionCommand(
                actor_combatant_id=_text(data["actor_combatant_id"]),
                actor_version=int(data["actor_version"]),
                feature_id=_text(data["runtime_id"]),
                target_combatant_id=_text(data.get("target_combatant_id")) or None,
                target_version=(int(data["target_version"]) if data.get("target_version") else None),
                healing_total=(int(data["resolution_total"]) if data.get("resolution_total") is not None else None),
                dm_override=_text(data.get("permission")) == "dm",
                override_reason="content runtime DM authorization" if _text(data.get("permission")) == "dm" else None,
            )
            runtime_action = dict(preview["feature_action"])
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
                "consumer": "combat_engine.feature_action",
                "result": result,
            }
            self._record_operation(campaign_id, key, output)
            return output

        cast_preview = preview["spell_preview"]
        with Session(self.engine) as session:
            _spell, _character, _runtime, blocks = self._spell_runtime(
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
            command = self._spell_command(data, blocks)
            if command is not None:
                combat_done = self.combat.confirm(
                    campaign_id,
                    _text(data["combat_id"]),
                    command,
                    idempotency_key=f"content-ir:{key}:combat",
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
            "consumer": "spell_economy_and_combat_engine",
            "spell_cast": spell_done,
            "combat": combat_done,
            "upcast": {"slot_level": data.get("slot_level")},
            "concentration": bool(data.get("concentration")),
        }
        self._record_operation(campaign_id, key, output)
        return output
