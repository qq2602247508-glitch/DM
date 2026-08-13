# ruff: noqa: E501
"""Authoritative Rules Kernel orchestration service.

This service owns the preview/confirm boundary and persists workflow state,
but delegates spatial facts to :class:`SpatialAuthority`.  The typed content
consumer below intentionally accepts only data-shaped effects supplied by a
compiled runtime definition; it never evaluates expressions or dispatches on
content names.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.rules_kernel_consumer_registry import (
    kernel_consumer_descriptors,
    resolve_kernel_consumer,
    validate_consumer_fields,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.rules_kernel_protocol import (
    KernelPosition,
    RulesKernelAdjudicationDecision,
    RulesKernelAdjudicationRequest,
    RulesKernelBlocker,
    RulesKernelCommand,
    RulesKernelConfirmation,
    RulesKernelPreview,
    RulesKernelResult,
    RulesKernelSceneDelta,
    RulesKernelStateDelta,
    SceneQuery,
    TypedAdjudicationContract,
)
from dnd_dm_assistant.domain.spatial_authority import SceneGridSpatialAuthority, SpatialAuthority
from dnd_dm_assistant.infrastructure.database.models import (
    Combat,
    Combatant,
    CompendiumEntry,
    OperationTransaction,
    RulesKernelAdjudicationWindow,
    RulesKernelChoiceWindow,
    RulesKernelCommandRecord,
    RulesKernelSceneDeltaRecord,
    Scene,
    SceneObject,
    SceneToken,
)

MAX_CAUSAL_DEPTH = 8
TYPED_OPERATION_NAMESPACE = "rules_kernel_typed_adjudication"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _is_expired(value: datetime | None) -> bool:
    if value is None:
        return False
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current < _now()


def _text(value: object) -> str:
    return str(value or "").strip()


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _typed_adjudication_is_authoritative(
    adjudication: RulesKernelAdjudicationWindow,
) -> bool:
    provenance = _as_dict(adjudication.producer_provenance)
    return (
        provenance.get("source_bound") is True
        and provenance.get("contract_schema") == "typed-adjudication-1"
        and _text(adjudication.source_record_id) not in {"", "legacy-unbound"}
        and _text(adjudication.source_fingerprint) not in {"", "legacy-unbound"}
        and bool(_as_list(adjudication.source_clause_ids))
        and bool(_as_dict(adjudication.target_context))
        and bool(_as_dict(adjudication.effect_envelope))
        and bool(_as_dict(adjudication.frozen_context).get("typed_contract"))
    )


def _without_idempotency(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "idempotency_key"}


class RulesKernelService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def consumer_registry() -> dict[str, dict[str, Any]]:
        return kernel_consumer_descriptors()

    @staticmethod
    def _command(payload: Mapping[str, Any] | RulesKernelCommand) -> RulesKernelCommand:
        if isinstance(payload, RulesKernelCommand):
            return payload
        nested_value = payload.get("command")
        nested = (
            nested_value
            if isinstance(nested_value, Mapping)
            else {
                key: value
                for key, value in payload.items()
                if key in RulesKernelCommand.model_fields
            }
        )
        return RulesKernelCommand.model_validate(nested)

    @staticmethod
    def _confirmation(
        payload: Mapping[str, Any] | RulesKernelConfirmation,
        command: RulesKernelCommand,
    ) -> RulesKernelConfirmation:
        if isinstance(payload, RulesKernelConfirmation):
            return payload
        nested = payload.get("confirmation")
        if isinstance(nested, Mapping):
            raw = nested
        else:
            raw = {
                key: value
                for key, value in payload.items()
                if key in RulesKernelConfirmation.model_fields
            }
        if "command_id" not in raw:
            raw = {**raw, "command_id": command.command_id}
        if "idempotency_key" not in raw:
            raw = {**raw, "idempotency_key": command.idempotency_key}
        return RulesKernelConfirmation.model_validate(raw)

    @staticmethod
    def _actor_snapshot(actor: Combatant) -> dict[str, Any]:
        position = _as_dict(_as_dict(actor.snapshot_json).get("grid_position"))
        return {
            "id": actor.id,
            "version": actor.version,
            "display_name": actor.display_name,
            "hp": actor.hp,
            "max_hp": actor.max_hp,
            "temporary_hp": actor.temporary_hp,
            "speed_ft": actor.speed_ft,
            "movement_remaining_ft": actor.movement_remaining_ft,
            "position": position,
            "conditions": list(actor.conditions or []),
            "combat_id": actor.combat_id,
        }

    @staticmethod
    def _position(value: KernelPosition | Mapping[str, Any] | None) -> KernelPosition | None:
        if isinstance(value, KernelPosition):
            return value
        if not isinstance(value, Mapping):
            return None
        try:
            return KernelPosition.model_validate(value)
        except ValueError:
            return None

    @staticmethod
    def _combatant(session: Session, combat_id: str | None, entity_id: str) -> Combatant:
        actor = session.get(Combatant, entity_id)
        if actor is None or (combat_id is not None and actor.combat_id != combat_id):
            raise StateNotFoundError("rules-kernel combatant not found")
        if not actor.is_active:
            raise ValueError("rules-kernel combatant is inactive")
        return actor

    @staticmethod
    def _check_version(kind: str, entity_id: str, expected: int | None, actual: int) -> None:
        if expected is not None and expected != actual:
            raise VersionConflict(kind, entity_id, expected, actual)

    @staticmethod
    def _expected_actor(command: RulesKernelCommand) -> int | None:
        return command.expected_versions.actor_version

    @staticmethod
    def _expected_target(command: RulesKernelCommand, target_id: str) -> int | None:
        return command.expected_versions.target_versions.get(target_id)

    def _spatial(self, session: Session, command: RulesKernelCommand) -> SpatialAuthority | None:
        if not command.scene_id:
            return None
        return SceneGridSpatialAuthority(session, command.scene_id, combat_id=command.combat_id)

    @staticmethod
    def _blocker(code: str, detail: str, *, retryable: bool = False) -> RulesKernelBlocker:
        return RulesKernelBlocker(code=code, detail=detail, retryable=retryable)

    @staticmethod
    def _clause_types(command: RulesKernelCommand) -> set[str]:
        raw = command.metadata.get("clause_types", ())
        if not isinstance(raw, (list, tuple, set)):
            return set()
        if any(not isinstance(item, str) or not item for item in raw):
            raise ValueError("clause_types must be a closed list of strings")
        return {str(item) for item in raw}

    def _resolve_consumer(self, command: RulesKernelCommand) -> dict[str, Any]:
        action_kind = {
            "move": "movement",
            "forced_move": "forced_movement",
            "teleport": "teleport",
            "swap_positions": "swap_positions",
            "summon_known_profile": "summon_known_profile",
            "create_known_object": "create_known_object",
            "create_known_hazard": "create_known_hazard",
            "choice": "choice",
            "adjudication": "target_semantics",
        }.get(command.action_kind, "")
        if command.action_kind == "content" and (
            command.metadata.get("requires_adjudication") is True
            or command.target_intent.semantic == "freeform"
        ):
            action_kind = "target_semantics"
        consumer = resolve_kernel_consumer(
            runtime_schema_version=command.schema_version,
            content_kind=command.content_kind,
            clause_types=self._clause_types(command),
            action_kind=action_kind,
        )
        validate_consumer_fields(consumer, command.model_dump(mode="json"))
        return consumer

    @staticmethod
    def _choice_metadata(command: RulesKernelCommand) -> dict[str, Any]:
        raw = command.metadata.get("choice")
        if isinstance(raw, Mapping):
            return dict(raw)
        return {
            "choice_kind": command.metadata.get("choice_kind", "fixed_options"),
            "option_source": command.metadata.get("option_source", "typed_asset_options"),
            "options": command.metadata.get("options", []),
            "minimum_choices": command.metadata.get("minimum_choices", 1),
            "maximum_choices": command.metadata.get("maximum_choices", 1),
            "replacement_policy": command.metadata.get("replacement_policy", "reject"),
        }

    def _create_choice_window(
        self,
        session: Session,
        command: RulesKernelCommand,
        actor: Combatant,
    ) -> tuple[RulesKernelChoiceWindow, dict[str, Any]]:
        metadata = self._choice_metadata(command)
        options = metadata.get("options")
        if not isinstance(options, list) or not options or any(not isinstance(item, str) for item in options):
            raise ValueError("choice window requires a non-empty typed option list")
        if len(set(options)) != len(options):
            raise ValueError("choice options must be unique")
        choice_kind = _text(metadata.get("choice_kind")) or "fixed_options"
        allowed = {
            "fixed_options", "typed_asset_options", "target_options", "position_options",
            "replacement_choice", "mode_choice", "resource_choice",
        }
        if choice_kind not in allowed:
            raise ValueError("unknown choice kind")
        minimum = int(metadata.get("minimum_choices") or 1)
        maximum = int(metadata.get("maximum_choices") or minimum)
        if minimum < 1 or maximum < minimum or maximum > len(options):
            raise ValueError("choice cardinality is invalid")
        window = RulesKernelChoiceWindow(
            campaign_id=command.campaign_id,
            source_command_id=command.command_id,
            actor_id=actor.id,
            content_id=command.content_id,
            choice_kind=choice_kind,
            option_source=_text(metadata.get("option_source")) or "typed_asset_options",
            frozen_options=options,
            minimum_choices=minimum,
            maximum_choices=maximum,
            replacement_policy=_text(metadata.get("replacement_policy")) or "reject",
            expires_at=_now() + timedelta(minutes=15),
            expected_versions=command.expected_versions.model_dump(mode="json"),
        )
        session.add(window)
        session.flush()
        return window, {
            "choice_window_id": window.id,
            "choice_kind": window.choice_kind,
            "frozen_options": options,
            "minimum_choices": minimum,
            "maximum_choices": maximum,
            "status": window.status,
            "version": window.version,
        }

    def _create_adjudication_window(
        self,
        session: Session,
        command: RulesKernelCommand,
        actor: Combatant,
        *,
        category: str | None = None,
    ) -> tuple[RulesKernelAdjudicationWindow, RulesKernelAdjudicationRequest]:
        metadata = _as_dict(command.metadata.get("adjudication"))
        typed_raw = _as_dict(command.metadata.get("typed_adjudication"))
        typed_contract = TypedAdjudicationContract.model_validate(typed_raw) if typed_raw else None
        if typed_contract is not None:
            context = typed_contract.target_context
            if not command.content_id or typed_contract.source_binding.content_id != command.content_id:
                raise ValueError("typed adjudication content binding mismatch")
            if not typed_contract.source_binding.clause_ids:
                raise ValueError("typed adjudication requires source clause binding")
            if context.campaign_id != command.campaign_id:
                raise ValueError("typed adjudication campaign binding mismatch")
            if context.actor_id != actor.id:
                raise ValueError("typed adjudication actor binding mismatch")
            if context.scene_id != command.scene_id:
                raise ValueError("typed adjudication scene binding mismatch")
            if context.target_id and context.target_id not in command.target_intent.target_ids and context.target_id != actor.id:
                raise ValueError("typed adjudication target binding mismatch")
        category_value = category or _text(metadata.get("category")) or "target_semantics"
        allowed_categories = {
            "target_semantics", "freeform_effect", "illusion_interpretation",
            "environment_interaction", "custom_object", "custom_movement", "rule_exception",
        }
        if category_value not in allowed_categories:
            raise ValueError("unknown adjudication category")
        evidence = _text(metadata.get("source_text_evidence")) or _text(command.metadata.get("source_text_evidence"))
        if not evidence:
            raise ValueError("DM adjudication requires source text evidence")
        allowed_schema = metadata.get("allowed_decision_schema") or [
            "approved_targets", "approved_position", "approved_duration", "approved_damage",
            "approved_condition", "approved_object_profile", "approved_movement", "approved_exception",
        ]
        if not isinstance(allowed_schema, list) or any(not isinstance(item, str) for item in allowed_schema):
            raise ValueError("allowed_decision_schema must be a closed string list")
        row = RulesKernelAdjudicationWindow(
            campaign_id=command.campaign_id,
            source_command_id=command.command_id,
            content_id=command.content_id,
            source_record_id=(
                typed_contract.source_binding.source_record_id
                if typed_contract is not None
                else (_text(metadata.get("source_record_id")) or _text(command.content_id) or "legacy-unbound")
            ),
            source_fingerprint=(
                typed_contract.source_binding.source_fingerprint
                if typed_contract is not None
                else (_text(metadata.get("source_fingerprint")) or "legacy-unbound")
            ),
            source_clause_ids=list(
                typed_contract.source_binding.clause_ids
                if typed_contract is not None
                else tuple(str(item) for item in _as_list(metadata.get("source_clause_ids")))
            ),
            actor_id=actor.id,
            target_context=(
                typed_contract.target_context.model_dump(mode="json")
                if typed_contract is not None
                else {
                    "campaign_id": command.campaign_id,
                    "scene_id": command.scene_id,
                    "actor_id": actor.id,
                    "target_kind": command.target_intent.target_kind,
                    "target_ids": list(command.target_intent.target_ids),
                }
            ),
            effect_envelope=(
                typed_contract.effect_envelope.model_dump(mode="json")
                if typed_contract is not None
                else {}
            ),
            decision_kind=typed_contract.decision_kind if typed_contract is not None else "target_selection",
            producer_provenance={
                "producer": "rules-kernel",
                "producer_version": "2026-08-13",
                "contract_schema": typed_contract.schema_version if typed_contract is not None else "legacy-adjudication-1",
                "source_bound": typed_contract is not None,
            },
            requested_by=_text(metadata.get("requested_by")) or "player",
            category=category_value,
            source_text_evidence=evidence,
            typed_known_effects=_as_list(metadata.get("typed_known_effects")),
            open_questions=[str(item) for item in _as_list(metadata.get("open_questions"))],
            allowed_decision_schema=allowed_schema,
            frozen_context={
                "actor": self._actor_snapshot(actor),
                "targets": list(command.target_intent.target_ids),
                "spatial": command.spatial_intent.model_dump(mode="json"),
                "rolls": command.roll_inputs.model_dump(mode="json"),
                "typed_contract": typed_contract.model_dump(mode="json") if typed_contract is not None else None,
            },
            expected_versions=command.expected_versions.model_dump(mode="json"),
            expires_at=_now() + timedelta(minutes=30),
        )
        session.add(row)
        session.flush()
        request = RulesKernelAdjudicationRequest(
            adjudication_id=row.id,
            source_command_id=command.command_id,
            content_id=command.content_id,
            category=category_value,
            source_text_evidence=evidence,
            typed_known_effects=tuple(item for item in row.typed_known_effects if isinstance(item, dict)),
            open_questions=tuple(str(item) for item in row.open_questions),
            allowed_decision_schema=tuple(str(item) for item in allowed_schema),
            frozen_context=dict(row.frozen_context),
            expected_versions=command.expected_versions,
            expires_at=row.expires_at,
        )
        return row, request

    def _validate_common_preview(
        self,
        session: Session,
        command: RulesKernelCommand,
    ) -> tuple[Combatant, list[Combatant], SpatialAuthority | None, list[RulesKernelBlocker]]:
        actor = self._combatant(session, command.combat_id, command.actor_id)
        self._check_version("combatant", actor.id, self._expected_actor(command), actor.version)
        target_ids = list(command.target_intent.target_ids)
        targets = [self._combatant(session, command.combat_id, target_id) for target_id in target_ids]
        for target in targets:
            self._check_version("combatant", target.id, self._expected_target(command, target.id), target.version)
        blockers: list[RulesKernelBlocker] = []
        spatial: SpatialAuthority | None = None
        spatial_required = command.action_kind in {
            "move", "forced_move", "teleport", "swap_positions", "summon_known_profile",
            "create_known_object", "create_known_hazard",
        } or command.spatial_intent.shape is not None or command.spatial_intent.line_of_sight_required
        if spatial_required:
            try:
                spatial = self._spatial(session, command)
                if spatial is None:
                    blockers.append(self._blocker("spatial.authority_missing", "this action requires an authoritative scene grid"))
            except ValueError as exc:
                blockers.append(self._blocker("spatial.authority_invalid", str(exc)))
        if command.expected_versions.combat_version is not None:
            combat = session.get(Combat, command.combat_id) if command.combat_id else None
            if combat is None:
                blockers.append(self._blocker("combat.missing", "combat_id does not identify an active combat"))
            else:
                try:
                    self._check_version("combat", combat.id, command.expected_versions.combat_version, combat.version)
                except VersionConflict as exc:
                    blockers.append(self._blocker("cas.combat", str(exc), retryable=True))
        elif command.combat_id:
            blockers.append(
                self._blocker(
                    "cas.combat_required",
                    "combat commands require expected_versions.combat_version",
                    retryable=True,
                )
            )
        if command.scene_id:
            scene = session.get(Scene, command.scene_id)
            if scene is None or scene.campaign_id != command.campaign_id:
                blockers.append(self._blocker("scene.missing", "scene_id does not identify a scene in the campaign"))
            elif command.expected_versions.scene_version is None:
                blockers.append(
                    self._blocker(
                        "cas.scene_required",
                        "scene commands require expected_versions.scene_version",
                        retryable=True,
                    )
                )
            else:
                try:
                    self._check_version("scene", scene.id, command.expected_versions.scene_version, scene.version)
                except VersionConflict as exc:
                    blockers.append(self._blocker("cas.scene", str(exc), retryable=True))
        return actor, targets, spatial, blockers

    def preview(self, payload: Mapping[str, Any] | RulesKernelCommand) -> dict[str, Any]:
        command = self._command(payload)
        fingerprint = _fingerprint(command.model_dump(mode="json"))
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(RulesKernelCommandRecord).where(
                    RulesKernelCommandRecord.campaign_id == command.campaign_id,
                    RulesKernelCommandRecord.command_id == command.command_id,
                )
            )
            if existing is not None:
                old_fingerprint = _text(_as_dict(existing.preview_json).get("command_fingerprint"))
                if old_fingerprint != fingerprint:
                    raise VersionConflict("rules-kernel-command", command.command_id, 1, existing.version)
                return dict(existing.preview_json)
            actor, targets, spatial, blockers = self._validate_common_preview(session, command)
            required_choices: list[dict[str, Any]] = []
            required_adjudications: list[RulesKernelAdjudicationRequest] = []
            if not blockers:
                self._resolve_consumer(command)
                if command.action_kind == "choice" or command.choice_inputs == () and command.metadata.get("requires_choice") is True:
                    _window, choice_payload = self._create_choice_window(session, command, actor)
                    required_choices.append(choice_payload)
                if command.target_intent.semantic == "freeform" or command.metadata.get("requires_adjudication") is True or command.action_kind == "adjudication":
                    _row, request = self._create_adjudication_window(session, command, actor)
                    required_adjudications.append(request)
            status = "ready"
            if blockers:
                status = "blocked"
            elif required_choices:
                status = "pending_choice"
            elif required_adjudications:
                status = "pending_adjudication"
            predicted_effects = tuple(
                item for item in _as_list(command.metadata.get("effects")) if isinstance(item, dict)
            )
            frozen_spatial = spatial.snapshot() if spatial is not None else {}
            preview = RulesKernelPreview(
                command_id=command.command_id,
                command_fingerprint=fingerprint,
                preview_version=1,
                status=status,
                legal=status == "ready",
                blockers=tuple(blockers),
                frozen_actor=self._actor_snapshot(actor),
                frozen_targets=tuple(self._actor_snapshot(target) for target in targets),
                frozen_spatial_snapshot=frozen_spatial,
                required_choices=tuple(required_choices),
                required_rolls=tuple(
                    str(item) for item in _as_list(command.metadata.get("required_rolls")) if isinstance(item, str)
                ),
                required_adjudications=tuple(required_adjudications),
                predicted_resource_cost=command.resource_intent,
                predicted_action_cost=command.action_economy,
                predicted_effects=predicted_effects,
                predicted_scene_delta=tuple(
                    self._predicted_movement_delta(command, actor, targets, spatial)
                ),
                expires_at=_now() + timedelta(minutes=10),
            )
            record = RulesKernelCommandRecord(
                command_id=command.command_id,
                campaign_id=command.campaign_id,
                scene_id=command.scene_id,
                combat_id=command.combat_id,
                idempotency_key=command.idempotency_key,
                action_kind=command.action_kind,
                command_json=command.model_dump(mode="json"),
                preview_json=preview.model_dump(mode="json"),
                status="previewed",
            )
            session.add(record)
            session.flush()
            return preview.model_dump(mode="json")

    @staticmethod
    def _predicted_movement_delta(
        command: RulesKernelCommand,
        actor: Combatant,
        targets: Sequence[Combatant],
        spatial: SpatialAuthority | None,
    ) -> list[dict[str, Any]]:
        if command.action_kind not in {"move", "forced_move", "teleport", "swap_positions"}:
            return []
        ids = list(command.target_intent.target_ids) or [actor.id]
        result: list[dict[str, Any]] = []
        for entity_id in ids:
            try:
                before = spatial.get_entity_position(entity_id).model_dump(mode="json") if spatial else {}
            except ValueError:
                before = {}
            after = command.spatial_intent.destination.model_dump(mode="json") if command.spatial_intent.destination else before
            result.append({"delta_type": "teleport_entity" if command.action_kind == "teleport" else "move_entity", "entity_id": entity_id, "before": before, "after": after})
        return result

    def _load_record(self, session: Session, command: RulesKernelCommand) -> RulesKernelCommandRecord:
        record = session.scalar(
            select(RulesKernelCommandRecord).where(
                RulesKernelCommandRecord.campaign_id == command.campaign_id,
                RulesKernelCommandRecord.command_id == command.command_id,
            )
        )
        if record is None:
            raise StateNotFoundError("rules-kernel preview not found")
        return record

    @staticmethod
    def _resolved_choice(session: Session, command_id: str) -> RulesKernelChoiceWindow | None:
        return session.scalar(select(RulesKernelChoiceWindow).where(RulesKernelChoiceWindow.source_command_id == command_id))

    @staticmethod
    def _resolved_adjudication(session: Session, command_id: str) -> RulesKernelAdjudicationWindow | None:
        return session.scalar(select(RulesKernelAdjudicationWindow).where(RulesKernelAdjudicationWindow.source_command_id == command_id))

    def _consume_choice(
        self,
        session: Session,
        command: RulesKernelCommand,
        confirmation: RulesKernelConfirmation,
    ) -> RulesKernelChoiceWindow | None:
        window = self._resolved_choice(session, command.command_id)
        if window is None:
            return None
        if window.status == "resolved":
            return window
        if window.status != "pending":
            raise ValueError("choice window is no longer resolvable")
        if _is_expired(window.expires_at):
            window.status = "expired"
            window.version += 1
            raise ValueError("choice window expired")
        submitted = next((item.values for item in confirmation.confirmed_choices if item.key == "selection"), ())
        if not submitted:
            return window
        if len(set(submitted)) != len(submitted) or not set(submitted).issubset(set(window.frozen_options)):
            raise ValueError("choice contains a value outside the frozen option set")
        if not window.minimum_choices <= len(submitted) <= window.maximum_choices:
            raise ValueError("choice count is outside the frozen bounds")
        expected_version = confirmation.expected_versions.choice_window_version or command.expected_versions.choice_window_version
        self._check_version("choice_window", window.id, expected_version, window.version)
        resolution = {
            "selection": list(submitted),
            "idempotency_key": confirmation.idempotency_key,
        }
        changed = session.execute(
            update(RulesKernelChoiceWindow)
            .where(
                RulesKernelChoiceWindow.id == window.id,
                RulesKernelChoiceWindow.status == "pending",
                RulesKernelChoiceWindow.version == window.version,
            )
            .values(
                status="resolved",
                resolution=resolution,
                version=window.version + 1,
                updated_at=_now(),
            )
        )
        if changed.rowcount != 1:
            raise VersionConflict("choice_window", window.id, window.version, window.version + 1)
        window.status = "resolved"
        window.resolution = resolution
        window.version += 1
        return window

    def _consume_adjudication(
        self,
        session: Session,
        command: RulesKernelCommand,
        confirmation: RulesKernelConfirmation,
    ) -> RulesKernelAdjudicationWindow | None:
        window = self._resolved_adjudication(session, command.command_id)
        if window is None:
            return None
        if window.status in {"approved", "modified", "rejected"}:
            decision = next(
                (
                    item
                    for item in confirmation.adjudication_decisions
                    if item.adjudication_id == window.id
                ),
                None,
            )
            if decision is not None:
                incoming = _without_idempotency(
                    decision.model_dump(
                        mode="json", exclude_none=True, exclude_defaults=True
                    )
                )
                stored = _without_idempotency(_as_dict(window.dm_decision))
                if incoming != stored:
                    raise ValueError("adjudication decision payload drift")
            return window
        if window.status != "pending_dm":
            raise ValueError("adjudication window is no longer resolvable")
        decision = next(
            (item for item in confirmation.adjudication_decisions if item.adjudication_id == window.id),
            None,
        )
        if decision is None:
            return window
        expected_version = confirmation.expected_versions.adjudication_version or command.expected_versions.adjudication_version
        self._check_version("adjudication", window.id, expected_version, window.version)
        decision_payload = decision.model_dump(
            mode="json", exclude_none=True, exclude_defaults=True
        )
        frozen_contract = _as_dict(_as_dict(window.frozen_context).get("typed_contract"))
        if frozen_contract:
            submitted_contract = _as_dict(decision_payload.get("typed_contract"))
            if submitted_contract != frozen_contract:
                raise ValueError("typed adjudication decision does not match frozen contract")
            target_context = _as_dict(frozen_contract.get("target_context"))
            expected_target = _text(target_context.get("target_id"))
            approved_targets = tuple(str(item) for item in decision.approved_targets)
            if decision.status in {"approved", "modified"} and expected_target:
                if approved_targets != (expected_target,):
                    raise ValueError(
                        "typed adjudication decision target does not match frozen target"
                    )
        permitted = set(str(item) for item in window.allowed_decision_schema)
        allowed_base = {"adjudication_id", "status", "notes"}
        if frozen_contract:
            allowed_base.add("typed_contract")
        unexpected = set(decision_payload) - allowed_base - permitted
        if unexpected:
            raise ValueError("DM decision contains fields outside allowed_decision_schema")
        changed = session.execute(
            update(RulesKernelAdjudicationWindow)
            .where(
                RulesKernelAdjudicationWindow.id == window.id,
                RulesKernelAdjudicationWindow.status == "pending_dm",
                RulesKernelAdjudicationWindow.version == window.version,
            )
            .values(
                status=decision.status,
                dm_decision=decision_payload,
                version=window.version + 1,
                updated_at=_now(),
            )
        )
        if changed.rowcount != 1:
            raise VersionConflict("adjudication", window.id, window.version, window.version + 1)
        window.status = decision.status
        window.dm_decision = decision_payload
        window.version += 1
        return window

    def _ensure_ready_workflows(
        self,
        session: Session,
        command: RulesKernelCommand,
        confirmation: RulesKernelConfirmation,
    ) -> str | None:
        choice = self._consume_choice(session, command, confirmation)
        if choice is not None and choice.status != "resolved":
            return "pending_choice"
        adjudication = self._consume_adjudication(session, command, confirmation)
        if adjudication is not None and adjudication.status == "pending_dm":
            return "pending_adjudication"
        if adjudication is not None and adjudication.status == "rejected":
            return "rejected"
        return None

    @staticmethod
    def _conditions(actor: Combatant) -> list[dict[str, Any]]:
        return [dict(item) for item in (actor.conditions or []) if isinstance(item, Mapping)]

    @staticmethod
    def _apply_action_economy(actor: Combatant, action_economy: str) -> None:
        field = {
            "action": "action_available",
            "bonus_action": "bonus_action_available",
            "reaction": "reaction_available",
        }.get(action_economy)
        if field is None:
            return
        if not bool(getattr(actor, field)):
            raise ValueError(f"{action_economy} is already spent")
        setattr(actor, field, False)
        actor.version += 1
        actor.updated_at = _now()

    @staticmethod
    def _resource_snapshot(actor: Combatant) -> dict[str, Any]:
        snapshot = dict(actor.snapshot_json or {})
        resources = snapshot.get("resources")
        return dict(resources) if isinstance(resources, Mapping) else {}

    @classmethod
    def _consume_resource(cls, actor: Combatant, command: RulesKernelCommand) -> dict[str, Any]:
        intent = command.resource_intent
        if intent.mode == "none" or intent.amount == 0:
            return {"resource_key": intent.resource_key, "amount": 0}
        if not intent.resource_key:
            raise ValueError("resource intent requires resource_key")
        snapshot = dict(actor.snapshot_json or {})
        resources = cls._resource_snapshot(actor)
        raw = resources.get(intent.resource_key)
        resource = dict(raw) if isinstance(raw, Mapping) else {"current": 0}
        before = int(resource.get("current") or 0)
        if intent.mode in {"consume", "reserve"} and before < intent.amount:
            raise ValueError("rules-kernel resource is insufficient")
        after = before - intent.amount if intent.mode in {"consume", "reserve"} else before + intent.amount
        resource["current"] = after
        resources[intent.resource_key] = resource
        snapshot["resources"] = resources
        actor.snapshot_json = snapshot
        actor.version += 1
        actor.updated_at = _now()
        return {"resource_key": intent.resource_key, "before": before, "after": after, "amount": intent.amount}

    @staticmethod
    def _state_delta(command_id: str, entity: Combatant, field: str, before: Any, after: Any, version_before: int) -> RulesKernelStateDelta:
        return RulesKernelStateDelta(
            delta_id=f"{command_id}:state:{entity.id}:{field}",
            source_command_id=command_id,
            entity_id=entity.id,
            field=field,
            before=before,
            after=after,
            version_before=version_before,
            version_after=version_before + 1,
        )

    def _persist_scene_delta(
        self,
        session: Session,
        command: RulesKernelCommand,
        *,
        delta_type: str,
        entity_id: str | None,
        object_id: str | None,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        version: int,
        payload: Mapping[str, Any] | None = None,
        index: int,
    ) -> RulesKernelSceneDelta:
        max_sequence = session.scalar(select(func.max(RulesKernelSceneDeltaRecord.sequence)).where(RulesKernelSceneDeltaRecord.campaign_id == command.campaign_id)) or 0
        sequence = int(max_sequence) + 1
        delta_id = f"{command.command_id}:scene:{index}"
        delta = RulesKernelSceneDelta(
            delta_id=delta_id,
            source_command_id=command.command_id,
            scene_id=command.scene_id,
            delta_type=delta_type,  # type: ignore[arg-type]
            entity_id=entity_id,
            object_id=object_id,
            before=dict(before),
            after=dict(after),
            version=version,
            sequence=sequence,
            payload=dict(payload or {}),
        )
        session.add(
            RulesKernelSceneDeltaRecord(
                campaign_id=command.campaign_id,
                scene_id=command.scene_id,
                source_command_id=command.command_id,
                delta_id=delta_id,
                sequence=sequence,
                delta_type=delta_type,
                delta_json=delta.model_dump(mode="json"),
            )
        )
        return delta

    @staticmethod
    def _update_scene_token(session: Session, command: RulesKernelCommand, entity: Combatant, position: KernelPosition) -> None:
        if not command.scene_id:
            return
        token = session.scalar(
            select(SceneToken).where(
                SceneToken.scene_id == command.scene_id,
                ((SceneToken.entity_id == entity.entity_id) | (SceneToken.entity_id == entity.id)),
            )
        )
        if token is not None:
            token.row = position.row
            token.col = position.col
            token.elevation_ft = position.elevation_ft
            token.version += 1
            token.updated_at = _now()

    def _apply_movement(
        self,
        session: Session,
        command: RulesKernelCommand,
        actor: Combatant,
        targets: Sequence[Combatant],
        spatial: SpatialAuthority,
    ) -> tuple[list[RulesKernelStateDelta], list[RulesKernelSceneDelta], list[dict[str, Any]]]:
        movement_targets = list(targets) if targets else [actor]
        destination = command.spatial_intent.destination
        if command.action_kind == "swap_positions":
            if len(movement_targets) != 2:
                raise ValueError("swap_positions requires exactly two target entities")
            first, second = movement_targets
            first_position = spatial.get_entity_position(first.id)
            second_position = spatial.get_entity_position(second.id)
            if spatial.is_space_occupied(first_position, size_cells=spatial.get_entity_size(first.id), ignore_entity_id=first.id):
                raise ValueError("swap source space is invalid")
            for entity, position in ((first, second_position), (second, first_position)):
                snapshot = dict(entity.snapshot_json or {})
                snapshot["grid_position"] = position.model_dump(mode="json")
                entity.snapshot_json = snapshot
                entity.version += 1
                entity.updated_at = _now()
                self._update_scene_token(session, command, entity, position)
            deltas = [
                self._persist_scene_delta(session, command, delta_type="move_entity", entity_id=first.id, object_id=None, before=first_position.model_dump(mode="json"), after=second_position.model_dump(mode="json"), version=first.version, index=0),
                self._persist_scene_delta(session, command, delta_type="move_entity", entity_id=second.id, object_id=None, before=second_position.model_dump(mode="json"), after=first_position.model_dump(mode="json"), version=second.version, index=1),
            ]
            return [], deltas, [{"entity_id": first.id, "from": first_position.model_dump(mode="json"), "to": second_position.model_dump(mode="json")}, {"entity_id": second.id, "from": second_position.model_dump(mode="json"), "to": first_position.model_dump(mode="json")}]
        if destination is None:
            raise ValueError("movement requires a destination")
        state_deltas: list[RulesKernelStateDelta] = []
        scene_deltas: list[RulesKernelSceneDelta] = []
        movement_results: list[dict[str, Any]] = []
        for index, target in enumerate(movement_targets):
            before_position = spatial.get_entity_position(target.id)
            if command.action_kind == "move":
                path_result = spatial.validate_path(target.id, command.spatial_intent.path or (before_position, destination), maximum_distance_ft=target.movement_remaining_ft)
                if not path_result.legal:
                    raise ValueError(path_result.reason or "movement path is invalid")
                if path_result.cost_ft > target.movement_remaining_ft:
                    raise ValueError("movement exceeds remaining movement budget")
            elif command.action_kind == "forced_move":
                path_result = spatial.validate_forced_movement(target.id, destination, source_id=actor.id if actor.id != target.id else None)
                if not path_result.legal:
                    raise ValueError(path_result.reason or "forced movement is invalid")
            else:
                spatial.validate_teleport_destination(target.id, destination, maximum_distance_ft=command.spatial_intent.maximum_distance_ft)
                path_result = type("Path", (), {"cost_ft": 0})()
            before_version = target.version
            snapshot = dict(target.snapshot_json or {})
            snapshot["grid_position"] = destination.model_dump(mode="json")
            target.snapshot_json = snapshot
            if command.action_kind == "move":
                target.movement_remaining_ft -= int(path_result.cost_ft)
            target.version += 1
            target.updated_at = _now()
            self._update_scene_token(session, command, target, destination)
            state_deltas.append(self._state_delta(command.command_id, target, "grid_position", before_position.model_dump(mode="json"), destination.model_dump(mode="json"), before_version))
            scene_deltas.append(self._persist_scene_delta(session, command, delta_type="teleport_entity" if command.action_kind == "teleport" else "move_entity", entity_id=target.id, object_id=None, before=before_position.model_dump(mode="json"), after=destination.model_dump(mode="json"), version=target.version, payload={"movement_kind": command.spatial_intent.movement_kind}, index=index))
            movement_results.append({"entity_id": target.id, "from": before_position.model_dump(mode="json"), "to": destination.model_dump(mode="json"), "cost_ft": int(path_result.cost_ft), "movement_kind": command.spatial_intent.movement_kind})
        return state_deltas, scene_deltas, movement_results

    def _apply_entity_lifecycle(
        self,
        session: Session,
        command: RulesKernelCommand,
        actor: Combatant,
        spatial: SpatialAuthority,
    ) -> tuple[list[dict[str, Any]], list[RulesKernelSceneDelta]]:
        if not command.combat_id:
            raise ValueError("entity lifecycle requires combat_id")
        combat = session.get(Combat, command.combat_id)
        if combat is None or combat.campaign_id != command.campaign_id or combat.status != "active":
            raise StateNotFoundError("active combat not found")
        profile_id = command.spatial_intent.entity_profile_id
        if not profile_id:
            raise ValueError("entity profile is required")
        profile_row = session.get(CompendiumEntry, profile_id)
        if profile_row is None or profile_row.campaign_id != command.campaign_id:
            raise StateNotFoundError("known entity profile not found")
        profile = dict(profile_row.rules_json or {})
        if command.action_kind == "summon_known_profile" and profile_row.entry_type not in {"monster", "npc"}:
            raise ValueError("summon profile must be a known monster or NPC profile")
        if command.action_kind != "summon_known_profile" and profile_row.entry_type not in {"item", "equipment", "scene", "rule"}:
            raise ValueError("object/hazard profile must be a known object profile")
        destination = command.spatial_intent.destination or spatial.find_nearest_unoccupied_space(spatial.get_entity_position(actor.id))
        size_cells = int(profile.get("size_cells") or 1)
        if command.action_kind == "summon_known_profile":
            spatial.validate_teleport_destination(actor.id, destination, maximum_distance_ft=None) if destination == spatial.get_entity_position(actor.id) else None
            if spatial.is_space_occupied(destination, size_cells=size_cells):
                if command.spatial_intent.occupied_space_policy == "nearest_unoccupied":
                    destination = spatial.find_nearest_unoccupied_space(destination, size_cells=size_cells)
                else:
                    raise ValueError("summon position is occupied")
            max_hp = int(profile.get("max_hp") or 0)
            armor_class = int(profile.get("armor_class") or 0)
            speed_ft = int(profile.get("speed_ft") or profile.get("speed") or 0)
            if max_hp < 1 or armor_class < 0 or speed_ft < 0:
                raise ValueError("known summon profile lacks HP, AC or speed")
            disposition = _text(profile.get("disposition")) or "ally"
            summoned = Combatant(
                combat_id=combat.id,
                entity_type="companion",
                entity_id=profile_row.id,
                display_name=_text(profile.get("display_name")) or profile_row.name,
                initiative=actor.initiative,
                armor_class=armor_class,
                hp=int(profile.get("hp") or max_hp),
                max_hp=max_hp,
                speed_ft=speed_ft,
                movement_remaining_ft=speed_ft,
                snapshot_json={
                    "disposition": disposition,
                    "controller_id": actor.id,
                    "summon_source": {"profile_id": profile_row.id, "source_command_id": command.command_id},
                    "summon_source_combatant_id": actor.id,
                    "summon_duration": command.metadata.get("duration", {"unit": "until_removed"}),
                    "grid_position": destination.model_dump(mode="json"),
                    "size_cells": size_cells,
                },
            )
            session.add(summoned)
            session.flush()
            if command.scene_id:
                session.add(SceneToken(scene_id=command.scene_id, entity_type="marker", entity_id=summoned.id, label=summoned.display_name, row=destination.row, col=destination.col, size_cells=size_cells, elevation_ft=destination.elevation_ft, metadata_json={"combatant_id": summoned.id, "profile_id": profile_row.id}))
            delta = self._persist_scene_delta(session, command, delta_type="spawn_entity", entity_id=summoned.id, object_id=None, before={}, after={"position": destination.model_dump(mode="json"), "profile_id": profile_row.id, "version": summoned.version}, version=summoned.version, payload={"entity_kind": "companion"}, index=0)
            return [{"entity_id": summoned.id, "profile_id": profile_row.id, "position": destination.model_dump(mode="json"), "version": summoned.version}], [delta]
        if not command.scene_id:
            raise ValueError("known object/hazard creation requires scene_id")
        if spatial.is_space_occupied(destination, size_cells=size_cells):
            raise ValueError("object creation position is occupied")
        object_type = "trap" if command.action_kind == "create_known_hazard" else _text(profile.get("object_type")) or "furniture"
        allowed_types = {"wall", "door", "cover", "terrain", "light", "trap", "treasure", "furniture", "portal"}
        if object_type not in allowed_types:
            raise ValueError("known object profile has an unsupported object_type")
        scene_object = SceneObject(scene_id=command.scene_id, object_type=object_type, label=_text(profile.get("label")) or profile_row.name, row=destination.row, col=destination.col, width_cells=size_cells, height_cells=size_cells, state="active", visibility="public", interaction_json=dict(profile.get("interaction_json") or {}), metadata_json={"profile_id": profile_row.id, "source_command_id": command.command_id})
        session.add(scene_object)
        session.flush()
        delta_type = "create_hazard" if command.action_kind == "create_known_hazard" else "create_object"
        delta = self._persist_scene_delta(session, command, delta_type=delta_type, entity_id=None, object_id=scene_object.id, before={}, after={"position": destination.model_dump(mode="json"), "object_type": object_type, "version": scene_object.version}, version=scene_object.version, index=0)
        return [{"object_id": scene_object.id, "profile_id": profile_row.id, "position": destination.model_dump(mode="json"), "version": scene_object.version}], [delta]

    def _apply_typed_content(
        self,
        session: Session,
        command: RulesKernelCommand,
        actor: Combatant,
        targets: Sequence[Combatant],
        spatial: SpatialAuthority | None,
    ) -> tuple[list[RulesKernelStateDelta], list[RulesKernelSceneDelta], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        effects = [dict(item) for item in _as_list(command.metadata.get("effects")) if isinstance(item, Mapping)]
        adjudication = self._resolved_adjudication(session, command.command_id)
        if not effects and adjudication is not None and adjudication.status in {"approved", "modified"}:
            decision = dict(adjudication.dm_decision or {})
            approved_damage = decision.get("approved_damage")
            approved_condition = decision.get("approved_condition")
            if isinstance(approved_damage, Mapping):
                effects.append({"kind": "damage", **dict(approved_damage)})
            elif isinstance(approved_condition, Mapping):
                effects.append({"kind": "apply_condition", **dict(approved_condition)})
            if isinstance(decision.get("approved_duration"), Mapping):
                effects.append({"kind": "set_concentration", "value": {"duration": dict(decision["approved_duration"]), "source_command_id": command.command_id}})
        if not effects:
            raise ValueError("typed content command has no executable effect blocks")
        target_rows = list(targets)
        if command.spatial_intent.shape is not None:
            if spatial is None or command.spatial_intent.origin is None:
                raise ValueError("area content requires authoritative origin and scene")
            resolved = spatial.resolve_area_targets(command.spatial_intent.origin, command.spatial_intent.shape, int(command.spatial_intent.size_ft or 0), include_ids=command.target_intent.target_ids)
            target_rows = [self._combatant(session, command.combat_id, item) for item in resolved]
        if not target_rows and any(_text(effect.get("kind")) in {"damage", "healing", "apply_condition", "remove_condition"} for effect in effects):
            raise ValueError("typed content requires at least one target")
        state_deltas: list[RulesKernelStateDelta] = []
        scene_deltas: list[RulesKernelSceneDelta] = []
        damage_results: list[dict[str, Any]] = []
        healing_results: list[dict[str, Any]] = []
        condition_results: list[dict[str, Any]] = []
        roll_results = command.roll_inputs.model_dump(mode="json")
        for effect_index, effect in enumerate(effects):
            kind = _text(effect.get("kind"))
            if kind not in {
                "damage", "healing", "temporary_hp", "apply_condition", "remove_condition",
                "set_concentration", "clear_concentration", "modifier", "reaction_window",
            }:
                raise ValueError(f"unknown typed content effect kind: {kind}")
            rows = [actor] if kind in {"set_concentration", "clear_concentration", "modifier", "reaction_window"} else target_rows
            for target_index, target in enumerate(rows):
                before_version = target.version
                if kind == "damage":
                    amount = int(effect.get("amount") or command.roll_inputs.resolution_total or 0)
                    if amount < 0:
                        raise ValueError("damage amount cannot be negative")
                    hp_before = target.hp
                    temp_before = target.temporary_hp
                    absorbed = min(temp_before, amount)
                    target.temporary_hp -= absorbed
                    target.hp = max(0, target.hp - (amount - absorbed))
                    damage_results.append({"target_id": target.id, "amount": amount, "absorbed_by_temporary_hp": absorbed, "hp_before": hp_before, "hp_after": target.hp})
                    state_deltas.extend([
                        self._state_delta(command.command_id, target, "hp", hp_before, target.hp, before_version),
                        self._state_delta(command.command_id, target, "temporary_hp", temp_before, target.temporary_hp, before_version),
                    ])
                    target.version += 1
                    scene_deltas.append(self._persist_scene_delta(session, command, delta_type="update_health", entity_id=target.id, object_id=None, before={"hp": hp_before, "temporary_hp": temp_before}, after={"hp": target.hp, "temporary_hp": target.temporary_hp}, version=target.version, payload={"damage_type": effect.get("damage_type")}, index=effect_index * 100 + target_index))
                elif kind in {"healing", "temporary_hp"}:
                    amount = int(effect.get("amount") or command.roll_inputs.resolution_total or 0)
                    if amount < 0:
                        raise ValueError("healing amount cannot be negative")
                    if kind == "temporary_hp":
                        before_value = target.temporary_hp
                        target.temporary_hp = max(target.temporary_hp, amount)
                        field = "temporary_hp"
                    else:
                        before_value = target.hp
                        target.hp = min(target.max_hp, target.hp + amount)
                        field = "hp"
                    healing_results.append({"target_id": target.id, "amount": amount, "field": field, "before": before_value, "after": getattr(target, field)})
                    state_deltas.append(self._state_delta(command.command_id, target, field, before_value, getattr(target, field), before_version))
                    target.version += 1
                    scene_deltas.append(self._persist_scene_delta(session, command, delta_type="update_health", entity_id=target.id, object_id=None, before={field: before_value}, after={field: getattr(target, field)}, version=target.version, index=effect_index * 100 + target_index))
                elif kind == "apply_condition":
                    condition = _text(effect.get("condition"))
                    if not condition:
                        raise ValueError("apply_condition requires condition")
                    before_conditions = list(target.conditions or [])
                    if not any(isinstance(item, Mapping) and item.get("name") == condition for item in before_conditions):
                        target.conditions = [*before_conditions, {"name": condition, "source_command_id": command.command_id}]
                    condition_results.append({"target_id": target.id, "operation": "apply", "condition": condition})
                    state_deltas.append(self._state_delta(command.command_id, target, "conditions", before_conditions, list(target.conditions or []), before_version))
                    target.version += 1
                    scene_deltas.append(self._persist_scene_delta(session, command, delta_type="apply_condition", entity_id=target.id, object_id=None, before={"conditions": before_conditions}, after={"conditions": list(target.conditions or [])}, version=target.version, index=effect_index * 100 + target_index))
                elif kind == "remove_condition":
                    condition = _text(effect.get("condition"))
                    before_conditions = list(target.conditions or [])
                    target.conditions = [item for item in before_conditions if not (isinstance(item, Mapping) and item.get("name") == condition)]
                    condition_results.append({"target_id": target.id, "operation": "remove", "condition": condition})
                    state_deltas.append(self._state_delta(command.command_id, target, "conditions", before_conditions, list(target.conditions or []), before_version))
                    target.version += 1
                    scene_deltas.append(self._persist_scene_delta(session, command, delta_type="remove_condition", entity_id=target.id, object_id=None, before={"conditions": before_conditions}, after={"conditions": list(target.conditions or [])}, version=target.version, index=effect_index * 100 + target_index))
                elif kind == "modifier":
                    snapshot = dict(actor.snapshot_json or {})
                    before_modifiers = list(snapshot.get("rules_kernel_modifiers") or [])
                    modifier = {
                        "modifier_id": f"{command.command_id}:{effect_index}",
                        "stat": _text(effect.get("stat")),
                        "operation": _text(effect.get("operation")) or "add",
                        "value": effect.get("value"),
                        "duration": effect.get("duration") or "until_removed",
                    }
                    if not modifier["stat"]:
                        raise ValueError("modifier requires stat")
                    snapshot["rules_kernel_modifiers"] = [*before_modifiers, modifier]
                    actor.snapshot_json = snapshot
                    actor.version += 1
                    state_deltas.append(self._state_delta(command.command_id, actor, "rules_kernel_modifiers", before_modifiers, snapshot["rules_kernel_modifiers"], before_version))
                    scene_deltas.append(self._persist_scene_delta(session, command, delta_type="emit_combat_log", entity_id=actor.id, object_id=None, before={"modifiers": before_modifiers}, after={"modifiers": snapshot["rules_kernel_modifiers"]}, version=actor.version, payload={"effect": "modifier"}, index=effect_index * 100 + target_index))
                elif kind == "reaction_window":
                    snapshot = dict(actor.snapshot_json or {})
                    before_windows = list(snapshot.get("rules_kernel_reaction_windows") or [])
                    window = {
                        "window_id": f"{command.command_id}:{effect_index}",
                        "kind": _text(effect.get("window_kind")) or "typed_reaction",
                        "expires": _text(effect.get("expires")) or "current_turn",
                        "candidate_target_ids": list(command.target_intent.target_ids),
                    }
                    snapshot["rules_kernel_reaction_windows"] = [*before_windows, window]
                    actor.snapshot_json = snapshot
                    actor.version += 1
                    state_deltas.append(self._state_delta(command.command_id, actor, "rules_kernel_reaction_windows", before_windows, snapshot["rules_kernel_reaction_windows"], before_version))
                    scene_deltas.append(self._persist_scene_delta(session, command, delta_type="emit_combat_log", entity_id=actor.id, object_id=None, before={"windows": before_windows}, after={"windows": snapshot["rules_kernel_reaction_windows"]}, version=actor.version, payload={"effect": "reaction_window"}, index=effect_index * 100 + target_index))
                elif kind == "set_concentration":
                    before = dict(actor.concentration or {})
                    actor.concentration = dict(effect.get("value") or {"source_command_id": command.command_id})
                    state_deltas.append(self._state_delta(command.command_id, actor, "concentration", before, dict(actor.concentration), before_version))
                    actor.version += 1
                    scene_deltas.append(self._persist_scene_delta(session, command, delta_type="set_concentration", entity_id=actor.id, object_id=None, before=before, after=dict(actor.concentration), version=actor.version, index=effect_index * 100 + target_index))
                else:
                    before = dict(actor.concentration or {})
                    actor.concentration = {}
                    state_deltas.append(self._state_delta(command.command_id, actor, "concentration", before, {}, before_version))
                    actor.version += 1
                    scene_deltas.append(self._persist_scene_delta(session, command, delta_type="clear_concentration", entity_id=actor.id, object_id=None, before=before, after={}, version=actor.version, index=effect_index * 100 + target_index))
        resource = self._consume_resource(actor, command)
        self._apply_action_economy(actor, command.action_economy)
        return state_deltas, scene_deltas, damage_results, healing_results, condition_results, {"resource": resource, "rolls": roll_results}

    def confirm(self, payload: Mapping[str, Any] | RulesKernelConfirmation) -> dict[str, Any]:
        command = self._command(payload)
        confirmation = self._confirmation(payload, command)
        if confirmation.command_id != command.command_id:
            raise ValueError("confirmation command_id does not match command")
        if confirmation.idempotency_key != command.idempotency_key:
            raise ValueError("confirmation idempotency_key does not match command")
        with Session(self.engine) as session, session.begin():
            record = self._load_record(session, command)
            preview = RulesKernelPreview.model_validate(record.preview_json)
            if confirmation.preview_version != preview.preview_version:
                raise VersionConflict("rules-kernel-preview", command.command_id, confirmation.preview_version, preview.preview_version)
            if record.result_json:
                previous = RulesKernelResult.model_validate(record.result_json)
                if previous.status not in {"pending_choice", "pending_adjudication"}:
                    return previous.model_copy(update={"idempotent_replay": True}).model_dump(mode="json")
            if preview.command_fingerprint != _fingerprint(command.model_dump(mode="json")):
                raise VersionConflict("rules-kernel-command", command.command_id, 1, record.version)
            if preview.status == "blocked":
                raise ValueError("rules-kernel preview is blocked")
            if record.status not in {"previewed", "pending_choice", "pending_adjudication"}:
                raise VersionConflict("rules-kernel-command", command.command_id, record.version, record.version + 1)
            claimed = session.execute(
                update(RulesKernelCommandRecord)
                .where(
                    RulesKernelCommandRecord.id == record.id,
                    RulesKernelCommandRecord.status == record.status,
                    RulesKernelCommandRecord.version == record.version,
                )
                .values(status="processing", version=record.version + 1, updated_at=_now())
            )
            if claimed.rowcount != 1:
                raise VersionConflict("rules-kernel-command", command.command_id, record.version, record.version + 1)
            record.status = "processing"
            record.version += 1
            workflow_status = self._ensure_ready_workflows(session, command, confirmation)
            if workflow_status in {"pending_choice", "pending_adjudication"}:
                pending = RulesKernelResult(result_id=f"{command.command_id}:result", command_id=command.command_id, status=workflow_status)
                record.result_json = pending.model_dump(mode="json")
                record.status = workflow_status
                return pending.model_dump(mode="json")
            if workflow_status == "rejected":
                rejected = RulesKernelResult(result_id=f"{command.command_id}:result", command_id=command.command_id, status="rejected")
                record.result_json = rejected.model_dump(mode="json")
                record.status = "rejected"
                return rejected.model_dump(mode="json")
            actor, targets, spatial, blockers = self._validate_common_preview(session, command)
            if blockers:
                raise ValueError("; ".join(item.detail for item in blockers))
            if command.combat_id:
                combat = session.get(Combat, command.combat_id)
                if combat is not None:
                    self._check_version("combat", combat.id, confirmation.expected_versions.combat_version or command.expected_versions.combat_version, combat.version)
            state_deltas: list[RulesKernelStateDelta] = []
            scene_deltas: list[RulesKernelSceneDelta] = []
            movement_results: list[dict[str, Any]] = []
            entity_results: list[dict[str, Any]] = []
            damage_results: list[dict[str, Any]] = []
            healing_results: list[dict[str, Any]] = []
            condition_results: list[dict[str, Any]] = []
            roll_results: dict[str, Any] = command.roll_inputs.model_dump(mode="json")
            if command.action_kind in {"move", "forced_move", "teleport", "swap_positions"}:
                if spatial is None:
                    raise ValueError("movement requires authoritative spatial authority")
                state_deltas, scene_deltas, movement_results = self._apply_movement(session, command, actor, targets, spatial)
                self._apply_action_economy(actor, command.action_economy)
            elif command.action_kind in {"summon_known_profile", "create_known_object", "create_known_hazard"}:
                if spatial is None:
                    raise ValueError("entity lifecycle requires authoritative spatial authority")
                entity_results, scene_deltas = self._apply_entity_lifecycle(session, command, actor, spatial)
                self._apply_action_economy(actor, command.action_economy)
            elif command.action_kind == "content":
                state_deltas, scene_deltas, damage_results, healing_results, condition_results, extra = self._apply_typed_content(session, command, actor, targets, spatial)
                roll_results = dict(extra.get("rolls") or roll_results)
            elif command.action_kind in {"choice", "adjudication"}:
                self._apply_action_economy(actor, command.action_economy)
            else:
                raise ValueError("unsupported rules-kernel action kind")
            new_versions = {
                actor.id: actor.version,
                **{target.id: target.version for target in targets},
            }
            if command.combat_id:
                combat = session.get(Combat, command.combat_id)
                if combat is not None:
                    combat.version += 1
                    combat.updated_at = _now()
                    new_versions[f"combat:{combat.id}"] = combat.version
            if command.scene_id:
                scene = session.get(Scene, command.scene_id)
                if scene is not None:
                    scene.version += 1
                    scene.updated_at = _now()
                    new_versions[f"scene:{scene.id}"] = scene.version
            adjudication = self._resolved_adjudication(session, command.command_id)
            typed_authoritative = (
                adjudication is not None
                and _typed_adjudication_is_authoritative(adjudication)
            )
            record.result_json = RulesKernelResult(
                result_id=f"{command.command_id}:result",
                command_id=command.command_id,
                status="confirmed",
                actual_resource_cost=command.resource_intent,
                actual_action_cost=command.action_economy,
                roll_results=roll_results,
                save_results={"by_target": command.roll_inputs.save_succeeded_by_target, "default": command.roll_inputs.save_succeeded},
                damage_results=tuple(damage_results),
                healing_results=tuple(healing_results),
                condition_results=tuple(condition_results),
                movement_results=tuple(movement_results),
                entity_results=tuple(entity_results),
                state_delta=tuple(state_deltas),
                scene_delta=tuple(scene_deltas),
                event_ids=tuple(delta.delta_id for delta in scene_deltas),
                new_versions=new_versions,
                adjudication_receipt=(
                    {
                        "adjudication_id": adjudication.id,
                        "status": adjudication.status,
                        "source_record_id": adjudication.source_record_id,
                        "source_fingerprint": adjudication.source_fingerprint,
                        "source_clause_ids": list(adjudication.source_clause_ids),
                        "target_context": dict(adjudication.target_context),
                        "effect_envelope": dict(adjudication.effect_envelope),
                        "decision_kind": adjudication.decision_kind,
                        "producer_provenance": dict(adjudication.producer_provenance),
                    }
                    if typed_authoritative and adjudication is not None
                    else {}
                ),
            ).model_dump(mode="json")
            if typed_authoritative and adjudication is not None:
                operation_key = (
                    f"{TYPED_OPERATION_NAMESPACE}:{adjudication.id}:"
                    f"{command.idempotency_key}"
                )
                existing_operation = session.scalar(
                    select(OperationTransaction).where(
                        OperationTransaction.campaign_id == command.campaign_id,
                        OperationTransaction.idempotency_key == operation_key,
                    )
                )
                if existing_operation is not None:
                    if (
                        _as_dict(existing_operation.after_snapshot).get("result")
                        != record.result_json
                    ):
                        raise ValueError("typed operation transaction payload drift")
                    result_payload = dict(record.result_json)
                    result_payload["operation_transaction_id"] = existing_operation.id
                    record.result_json = result_payload
                else:
                    operation = OperationTransaction(
                        campaign_id=command.campaign_id,
                        operation_type=TYPED_OPERATION_NAMESPACE,
                        idempotency_key=operation_key,
                        status="applied",
                        before_snapshot={
                            "command_id": command.command_id,
                            "preview": preview.model_dump(mode="json"),
                        },
                        after_snapshot={
                            "result": record.result_json,
                            "producer_provenance": dict(adjudication.producer_provenance),
                        },
                        reason="typed adjudication producer-consumer confirmation",
                        source="dm",
                        confirmed_at=_now(),
                    )
                    session.add(operation)
                    session.flush()
                    result_payload = dict(record.result_json)
                    result_payload["operation_transaction_id"] = operation.id
                    record.result_json = result_payload
            record.status = "confirmed"
            record.version += 1
            record.updated_at = _now()
            result = RulesKernelResult.model_validate(record.result_json)
            return result.model_dump(mode="json")

    def resolve_choice(self, campaign_id: str, window_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        values = payload.get("values")
        if not isinstance(values, list):
            raise ValueError("choice resolution requires values")
        permission = _text(payload.get("permission")) or "player"
        actor_id = _text(payload.get("actor_id"))
        idempotency_key = _text(payload.get("idempotency_key")) or f"choice:{window_id}:{_fingerprint(values)[:16]}"
        expected_version = int(payload.get("expected_version") or 0)
        with Session(self.engine) as session, session.begin():
            window = session.get(RulesKernelChoiceWindow, window_id)
            if window is None or window.campaign_id != campaign_id:
                raise StateNotFoundError("choice window not found")
            if window.status == "resolved":
                if window.resolution.get("idempotency_key") == idempotency_key:
                    return {"window_id": window.id, "status": window.status, "resolution": window.resolution, "idempotent_replay": True}
                raise ValueError("choice window has already been resolved")
            if permission != "dm" and actor_id != window.actor_id:
                raise ValueError("player may only resolve their own choice window")
            if expected_version and expected_version != window.version:
                raise VersionConflict("choice_window", window.id, expected_version, window.version)
            if len(set(values)) != len(values) or not set(values).issubset(set(window.frozen_options)):
                raise ValueError("choice contains a value outside the frozen option set")
            if not window.minimum_choices <= len(values) <= window.maximum_choices:
                raise ValueError("choice count is outside the frozen bounds")
            resolution = {
                "selection": list(values),
                "idempotency_key": idempotency_key,
                "resolved_by": permission,
            }
            changed = session.execute(
                update(RulesKernelChoiceWindow)
                .where(
                    RulesKernelChoiceWindow.id == window.id,
                    RulesKernelChoiceWindow.status == "pending",
                    RulesKernelChoiceWindow.version == window.version,
                )
                .values(
                    status="resolved",
                    resolution=resolution,
                    version=window.version + 1,
                    updated_at=_now(),
                )
            )
            if changed.rowcount != 1:
                raise VersionConflict("choice_window", window.id, window.version, window.version + 1)
            window.status = "resolved"
            window.resolution = resolution
            window.version += 1
            return {"window_id": window.id, "status": window.status, "resolution": window.resolution, "version": window.version, "idempotent_replay": False}

    def resolve_adjudication(self, campaign_id: str, adjudication_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        permission = _text(payload.get("permission"))
        if permission != "dm":
            raise ValueError("only DM may resolve adjudication windows")
        raw = dict(payload.get("decision") or payload)
        raw.setdefault("adjudication_id", adjudication_id)
        decision = RulesKernelAdjudicationDecision.model_validate(raw)
        with Session(self.engine) as session, session.begin():
            window = session.get(RulesKernelAdjudicationWindow, adjudication_id)
            if window is None or window.campaign_id != campaign_id:
                raise StateNotFoundError("adjudication window not found")
            if window.status in {"approved", "modified", "rejected"}:
                previous_key = _text(_as_dict(window.dm_decision).get("idempotency_key"))
                incoming_key = _text(payload.get("idempotency_key"))
                if previous_key and incoming_key and previous_key != incoming_key:
                    raise ValueError("adjudication idempotency payload drift")
                incoming_payload = _without_idempotency(
                    decision.model_dump(
                        mode="json", exclude_none=True, exclude_defaults=True
                    )
                )
                stored_payload = _without_idempotency(_as_dict(window.dm_decision))
                if incoming_payload != stored_payload:
                    raise ValueError("adjudication payload drift")
                return {"adjudication_id": window.id, "status": window.status, "decision": window.dm_decision, "idempotent_replay": True}
            if _is_expired(window.expires_at):
                window.status = "expired"
                window.version += 1
                raise ValueError("adjudication window expired")
            expected_version = int(payload.get("expected_version") or 0)
            if expected_version and expected_version != window.version:
                raise VersionConflict("adjudication", window.id, expected_version, window.version)
            permitted = set(str(item) for item in window.allowed_decision_schema)
            allowed_base = {"adjudication_id", "status", "notes"}
            frozen_contract = _as_dict(_as_dict(window.frozen_context).get("typed_contract"))
            if frozen_contract:
                allowed_base.add("typed_contract")
                submitted_contract = _as_dict(
                    decision.model_dump(mode="json").get("typed_contract")
                )
                if submitted_contract != frozen_contract:
                    raise ValueError("typed adjudication decision does not match frozen contract")
                target_context = _as_dict(frozen_contract.get("target_context"))
                expected_target = _text(target_context.get("target_id"))
                approved_targets = tuple(str(item) for item in decision.approved_targets)
                if decision.status in {"approved", "modified"} and expected_target:
                    if approved_targets != (expected_target,):
                        raise ValueError(
                            "typed adjudication decision target does not match frozen target"
                        )
            unexpected = set(
                decision.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
            ) - allowed_base - permitted
            if unexpected:
                raise ValueError("DM decision contains fields outside allowed_decision_schema")
            decision_payload = decision.model_dump(
                mode="json", exclude_none=True, exclude_defaults=True
            )
            decision_payload["idempotency_key"] = (
                _text(payload.get("idempotency_key"))
                or f"adjudication:{window.id}:{_fingerprint(decision_payload)[:16]}"
            )
            changed = session.execute(
                update(RulesKernelAdjudicationWindow)
                .where(
                    RulesKernelAdjudicationWindow.id == window.id,
                    RulesKernelAdjudicationWindow.status == "pending_dm",
                    RulesKernelAdjudicationWindow.version == window.version,
                )
                .values(
                    status=decision.status,
                    dm_decision=decision_payload,
                    version=window.version + 1,
                    updated_at=_now(),
                )
            )
            if changed.rowcount != 1:
                raise VersionConflict("adjudication", window.id, window.version, window.version + 1)
            window.status = decision.status
            window.dm_decision = decision_payload
            window.version += 1
            return {"adjudication_id": window.id, "status": window.status, "decision": window.dm_decision, "version": window.version, "idempotent_replay": False}

    def result(self, campaign_id: str, command_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            record = session.scalar(select(RulesKernelCommandRecord).where(RulesKernelCommandRecord.campaign_id == campaign_id, RulesKernelCommandRecord.command_id == command_id))
            if record is None or not record.result_json:
                raise StateNotFoundError("rules-kernel result not found")
            return dict(record.result_json)

    def scene_deltas(self, campaign_id: str, *, scene_id: str | None = None, after: int = 0, limit: int = 100) -> dict[str, Any]:
        with Session(self.engine) as session:
            query = select(RulesKernelSceneDeltaRecord).where(RulesKernelSceneDeltaRecord.campaign_id == campaign_id, RulesKernelSceneDeltaRecord.sequence > after)
            if scene_id:
                query = query.where(RulesKernelSceneDeltaRecord.scene_id == scene_id)
            rows = list(session.scalars(query.order_by(RulesKernelSceneDeltaRecord.sequence).limit(limit)).all())
            next_cursor = rows[-1].sequence if rows else after
            return {"schema_version": "scene-delta-1", "campaign_id": campaign_id, "scene_id": scene_id, "cursor": after, "next_cursor": next_cursor, "deltas": [dict(row.delta_json) for row in rows]}

    def query_scene(self, campaign_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        query = SceneQuery.model_validate(payload)
        if not query.scene_id.strip():
            raise ValueError("scene_id is required")
        with Session(self.engine) as session:
            scene = session.get(Scene, query.scene_id)
            if scene is None or scene.campaign_id != campaign_id:
                raise StateNotFoundError("scene not found in campaign")
            spatial = SceneGridSpatialAuthority(
                session,
                query.scene_id,
                combat_id=query.combat_id,
            )
            if query.query_kind == "entity_position":
                if len(query.entity_ids) != 1:
                    raise ValueError("entity_position requires one entity_id")
                value: Any = spatial.get_entity_position(query.entity_ids[0]).model_dump(mode="json")
            elif query.query_kind == "distance":
                if len(query.entity_ids) != 2:
                    raise ValueError("distance requires two entity_ids")
                value = spatial.distance_between(query.entity_ids[0], query.entity_ids[1])
            elif query.query_kind == "cover":
                if len(query.entity_ids) != 2:
                    raise ValueError("cover requires two entity_ids")
                value = spatial.get_cover(query.entity_ids[0], query.entity_ids[1])
            elif query.query_kind == "visible_entities":
                if len(query.entity_ids) != 1:
                    raise ValueError("visible_entities requires an origin entity")
                origin = query.entity_ids[0]
                value = tuple(
                    entity_id
                    for entity_id in sorted(spatial.entities)
                    if entity_id != origin and spatial.has_line_of_sight(origin, entity_id)
                )
            elif query.query_kind == "entities_in_range":
                if len(query.entity_ids) != 1 or query.maximum_distance_ft is None:
                    raise ValueError("entities_in_range requires one origin and maximum_distance_ft")
                origin = query.entity_ids[0]
                value = tuple(
                    entity_id
                    for entity_id in sorted(spatial.entities)
                    if entity_id != origin
                    and spatial.distance_between(origin, entity_id) <= query.maximum_distance_ft
                )
            elif query.query_kind == "unoccupied_space":
                if query.origin is None:
                    raise ValueError("unoccupied_space requires origin")
                value = spatial.find_nearest_unoccupied_space(query.origin).model_dump(mode="json")
            elif query.query_kind == "area_targets":
                if query.origin is None or query.shape is None or query.size_ft is None:
                    raise ValueError("area_targets requires origin, shape and size_ft")
                value = spatial.resolve_area_targets(query.origin, query.shape, query.size_ft)
            else:
                if len(query.entity_ids) != 1 or query.destination is None:
                    raise ValueError("path requires one entity and destination")
                current = spatial.get_entity_position(query.entity_ids[0])
                path = spatial.validate_path(query.entity_ids[0], (current, query.destination))
                value = {"legal": path.legal, "cost_ft": path.cost_ft, "reason": path.reason}
            return {
                "schema_version": "scene-query-1",
                "query_id": query.query_id,
                "scene_id": query.scene_id,
                "query_kind": query.query_kind,
                "result": value,
                "spatial_snapshot": spatial.snapshot(),
            }
