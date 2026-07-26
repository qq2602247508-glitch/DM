from __future__ import annotations

import builtins
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.encounters import EncounterAdjustmentDraft
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Campaign,
    Character,
    Combat,
    Combatant,
    EncounterAdjustmentProposal,
    Event,
    MonsterInstance,
    OperationTransaction,
    Scene,
)


class EncounterAdjustmentService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _proposal(
        session: Session,
        campaign_id: str,
        proposal_id: str,
    ) -> EncounterAdjustmentProposal:
        proposal = session.scalar(
            select(EncounterAdjustmentProposal).where(
                EncounterAdjustmentProposal.id == proposal_id,
                EncounterAdjustmentProposal.campaign_id == campaign_id,
            )
        )
        if proposal is None:
            raise StateNotFoundError("encounter adjustment not found")
        return proposal

    @staticmethod
    def _validate_scope(
        session: Session,
        campaign_id: str,
        *,
        scene_id: str,
        combat_id: str | None,
        source_event_id: str | None,
        draft: EncounterAdjustmentDraft,
    ) -> None:
        scene = session.get(Scene, scene_id)
        if scene is None or scene.campaign_id != campaign_id:
            raise StateNotFoundError("scene not found in campaign")
        if combat_id is not None:
            combat = session.get(Combat, combat_id)
            if (
                combat is None
                or combat.campaign_id != campaign_id
                or combat.scene_id != scene_id
            ):
                raise StateNotFoundError("combat not found in scene")
        if source_event_id is not None:
            event = session.get(Event, source_event_id)
            if event is None or event.campaign_id != campaign_id:
                raise StateNotFoundError("source event not found in campaign")

        models: dict[str, type[Any]] = {
            "character": Character,
            "npc": NPC,
            "monster": MonsterInstance,
        }
        for operation in draft.operations:
            entity = session.get(models[operation.entity_type], operation.entity_id)
            if entity is None or entity.campaign_id != campaign_id:
                raise StateNotFoundError(
                    f"{operation.entity_type} {operation.entity_id} not found in campaign"
                )

    def list(
        self,
        campaign_id: str,
        *,
        scene_id: str | None = None,
        status: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            query = select(EncounterAdjustmentProposal).where(
                EncounterAdjustmentProposal.campaign_id == campaign_id
            )
            if scene_id is not None:
                query = query.where(EncounterAdjustmentProposal.scene_id == scene_id)
            if status is not None:
                query = query.where(EncounterAdjustmentProposal.status == status)
            rows = session.scalars(
                query.order_by(
                    EncounterAdjustmentProposal.created_at,
                    EncounterAdjustmentProposal.id,
                )
            ).all()
            return tuple(serialize(row) for row in rows)

    def create(
        self,
        campaign_id: str,
        *,
        scene_id: str,
        combat_id: str | None,
        source_event_id: str | None,
        draft: EncounterAdjustmentDraft,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            self._validate_scope(
                session,
                campaign_id,
                scene_id=scene_id,
                combat_id=combat_id,
                source_event_id=source_event_id,
                draft=draft,
            )
            proposal = EncounterAdjustmentProposal(
                campaign_id=campaign_id,
                scene_id=scene_id,
                combat_id=combat_id,
                source_event_id=source_event_id,
                title=draft.title,
                reason=draft.reason,
                difficulty_shift=draft.difficulty_shift,
                operations_json=[
                    operation.model_dump(mode="json") for operation in draft.operations
                ],
            )
            session.add(proposal)
            session.flush()
            return serialize(proposal)

    def update_pending(
        self,
        campaign_id: str,
        proposal_id: str,
        *,
        data: dict[str, Any],
        expected_version: int,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            proposal = self._proposal(session, campaign_id, proposal_id)
            if proposal.status != "pending":
                raise ValueError("only pending encounter adjustments can be edited")
            if proposal.version != expected_version:
                raise VersionConflict(
                    "encounter adjustment",
                    proposal_id,
                    expected_version,
                    proposal.version,
                )
            values = {
                "title": data.get("title", proposal.title),
                "reason": data.get("reason", proposal.reason),
                "difficulty_shift": data.get(
                    "difficulty_shift",
                    proposal.difficulty_shift,
                ),
                "operations": tuple(data.get("operations", proposal.operations_json)),
            }
            draft = EncounterAdjustmentDraft.model_validate(values)
            self._validate_scope(
                session,
                campaign_id,
                scene_id=proposal.scene_id,
                combat_id=proposal.combat_id,
                source_event_id=proposal.source_event_id,
                draft=draft,
            )
            proposal.title = draft.title
            proposal.reason = draft.reason
            proposal.difficulty_shift = draft.difficulty_shift
            proposal.operations_json = [
                operation.model_dump(mode="json") for operation in draft.operations
            ]
            proposal.version += 1
            proposal.updated_at = datetime.now(UTC)
            session.flush()
            return serialize(proposal)

    def reject(
        self,
        campaign_id: str,
        proposal_id: str,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            proposal = self._proposal(session, campaign_id, proposal_id)
            if proposal.status == "rejected":
                return serialize(proposal)
            if proposal.status != "pending":
                raise ValueError("only pending encounter adjustments can be rejected")
            if proposal.version != expected_version:
                raise VersionConflict(
                    "encounter adjustment",
                    proposal_id,
                    expected_version,
                    proposal.version,
                )
            proposal.status = "rejected"
            proposal.version += 1
            proposal.updated_at = datetime.now(UTC)
            session.flush()
            return serialize(proposal)

    @staticmethod
    def _combatant(
        session: Session,
        combat_id: str,
        entity_type: str,
        entity_id: str,
    ) -> Combatant | None:
        return session.scalar(
            select(Combatant).where(
                Combatant.combat_id == combat_id,
                Combatant.entity_type == entity_type,
                Combatant.entity_id == entity_id,
            )
        )

    @staticmethod
    def _entity(
        session: Session,
        campaign_id: str,
        entity_type: str,
        entity_id: str,
    ) -> Character | NPC | MonsterInstance:
        entity: Character | NPC | MonsterInstance | None
        if entity_type == "character":
            entity = session.get(Character, entity_id)
        elif entity_type == "npc":
            entity = session.get(NPC, entity_id)
        elif entity_type == "monster":
            entity = session.get(MonsterInstance, entity_id)
        else:
            raise ValueError("unsupported encounter entity type")
        if entity is None or entity.campaign_id != campaign_id:
            raise StateNotFoundError(f"{entity_type} not found in campaign")
        return entity

    def _apply_to_combat(
        self,
        session: Session,
        proposal: EncounterAdjustmentProposal,
        draft: EncounterAdjustmentDraft,
    ) -> builtins.list[dict[str, object]]:
        if proposal.combat_id is None:
            return []
        combat = session.get(Combat, proposal.combat_id)
        if combat is None or combat.campaign_id != proposal.campaign_id:
            raise StateNotFoundError("combat not found in campaign")
        if combat.xp_awarded:
            raise ValueError("settled combat cannot be adjusted")

        inverse: builtins.list[dict[str, object]] = []
        for operation in draft.operations:
            combatant = self._combatant(
                session,
                combat.id,
                operation.entity_type,
                operation.entity_id,
            )
            if operation.kind == "add_scene_entity":
                if combatant is None:
                    entity = self._entity(
                        session,
                        proposal.campaign_id,
                        operation.entity_type,
                        operation.entity_id,
                    )
                    combatant = Combatant(
                        combat_id=combat.id,
                        entity_type=operation.entity_type,
                        entity_id=operation.entity_id,
                        display_name=entity.name,
                        armor_class=int(getattr(entity, "armor_class", 10)),
                        hp=int(getattr(entity, "hp", 1)),
                        max_hp=int(getattr(entity, "max_hp", 1)),
                        speed_ft=int(getattr(entity, "speed", 30)),
                        movement_remaining_ft=int(getattr(entity, "speed", 30)),
                        conditions=[],
                        snapshot_json={
                            "speed_ft": int(getattr(entity, "speed", 30)),
                            "ability_scores": dict(entity.ability_scores or {}),
                            "actions": list(getattr(entity, "actions", []) or []),
                        },
                        is_active=True,
                    )
                    session.add(combatant)
                    session.flush()
                    inverse.append(
                        {
                            "kind": "delete_combatant",
                            "combatant_id": combatant.id,
                        }
                    )
                else:
                    inverse.append(
                        {
                            "kind": "set_combatant_active",
                            "combatant_id": combatant.id,
                            "is_active": combatant.is_active,
                        }
                    )
                    combatant.is_active = True
            elif operation.kind == "schedule_reinforcement":
                reinforcements = list(combat.difficulty_adjustments or [])
                entry: dict[str, object] = {
                    "kind": "scheduled_reinforcement",
                    "proposal_id": proposal.id,
                    "entity_type": operation.entity_type,
                    "entity_id": operation.entity_id,
                    "round": operation.round,
                    "quantity": operation.quantity,
                    "reason": operation.reason,
                    "deployed": False,
                }
                reinforcements.append(entry)
                combat.difficulty_adjustments = reinforcements
                inverse.append({"kind": "remove_reinforcement", "entry": entry})
            else:
                if combatant is None:
                    raise StateNotFoundError(
                        f"{operation.entity_type} is not a combatant in this combat"
                    )
                if operation.kind == "remove_entity":
                    inverse.append(
                        {
                            "kind": "set_combatant_active",
                            "combatant_id": combatant.id,
                            "is_active": combatant.is_active,
                        }
                    )
                    combatant.is_active = False
                elif operation.kind == "set_entity_hp":
                    if operation.hp > combatant.max_hp:
                        raise ValueError(
                            f"HP {operation.hp} exceeds {combatant.display_name} max HP "
                            f"{combatant.max_hp}"
                        )
                    inverse.append(
                        {
                            "kind": "set_combatant_hp",
                            "combatant_id": combatant.id,
                            "hp": combatant.hp,
                        }
                    )
                    combatant.hp = operation.hp
                elif operation.kind == "add_entity_condition":
                    conditions = list(combatant.conditions or [])
                    condition: dict[str, object] = {
                        "name": operation.condition,
                        "source": f"encounter_adjustment:{proposal.id}",
                    }
                    if condition not in conditions:
                        conditions.append(condition)
                    combatant.conditions = conditions
                    inverse.append(
                        {
                            "kind": "remove_combatant_condition",
                            "combatant_id": combatant.id,
                            "condition": condition,
                        }
                    )
            if combatant is not None:
                combatant.version += 1
                combatant.updated_at = datetime.now(UTC)
        combat.version += 1
        combat.updated_at = datetime.now(UTC)
        return inverse

    def apply(
        self,
        campaign_id: str,
        proposal_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            proposal = self._proposal(session, campaign_id, proposal_id)
            if proposal.status == "applied":
                return serialize(proposal)
            if proposal.status != "pending":
                raise ValueError("only pending encounter adjustments can be applied")
            if proposal.version != expected_version:
                raise VersionConflict(
                    "encounter adjustment",
                    proposal_id,
                    expected_version,
                    proposal.version,
                )
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.operation_type != "encounter_adjustment":
                    raise ValueError("idempotency key was already used by another operation")
                return serialize(proposal)

            draft = EncounterAdjustmentDraft.model_validate(
                {
                    "title": proposal.title,
                    "reason": proposal.reason,
                    "difficulty_shift": proposal.difficulty_shift,
                    "operations": tuple(proposal.operations_json),
                }
            )
            self._validate_scope(
                session,
                campaign_id,
                scene_id=proposal.scene_id,
                combat_id=proposal.combat_id,
                source_event_id=proposal.source_event_id,
                draft=draft,
            )
            inverse = self._apply_to_combat(session, proposal, draft)
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="encounter_adjustment",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={
                    "proposal_id": proposal.id,
                    "inverse_operations": inverse,
                },
                after_snapshot={
                    "proposal_id": proposal.id,
                    "operations": proposal.operations_json,
                },
                reason=proposal.reason,
                source="game_table",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            proposal.operation_transaction_id = transaction.id
            proposal.inverse_operations_json = builtins.list[object](inverse)
            proposal.status = "applied"
            proposal.applied_at = datetime.now(UTC)
            proposal.version += 1
            proposal.updated_at = datetime.now(UTC)
            session.flush()
            return serialize(proposal)

    def consume_for_combat(
        self,
        session: Session,
        *,
        campaign_id: str,
        scene_id: str,
        combat: Combat,
    ) -> None:
        proposals = session.scalars(
            select(EncounterAdjustmentProposal)
            .where(
                EncounterAdjustmentProposal.campaign_id == campaign_id,
                EncounterAdjustmentProposal.scene_id == scene_id,
                EncounterAdjustmentProposal.status == "applied",
                EncounterAdjustmentProposal.combat_id.is_(None),
            )
            .order_by(
                EncounterAdjustmentProposal.applied_at,
                EncounterAdjustmentProposal.id,
            )
        ).all()
        for proposal in proposals:
            proposal.combat_id = combat.id
            draft = EncounterAdjustmentDraft.model_validate(
                {
                    "title": proposal.title,
                    "reason": proposal.reason,
                    "difficulty_shift": proposal.difficulty_shift,
                    "operations": tuple(proposal.operations_json),
                }
            )
            inverse = self._apply_to_combat(session, proposal, draft)
            proposal.inverse_operations_json = builtins.list[object](inverse)
            proposal.version += 1
            proposal.updated_at = datetime.now(UTC)
            if proposal.operation_transaction_id is not None:
                transaction = session.get(
                    OperationTransaction,
                    proposal.operation_transaction_id,
                )
                if transaction is not None:
                    transaction.before_snapshot = {
                        "proposal_id": proposal.id,
                        "inverse_operations": inverse,
                    }
                    transaction.after_snapshot = {
                        "proposal_id": proposal.id,
                        "combat_id": combat.id,
                        "operations": proposal.operations_json,
                    }
                    transaction.version += 1
                    transaction.updated_at = datetime.now(UTC)

    @staticmethod
    def _revert_operations(
        session: Session,
        combat: Combat,
        operations: builtins.list[object],
    ) -> None:
        for raw_object in reversed(operations):
            raw: dict[str, object]
            if not isinstance(raw_object, dict):
                raise ValueError("invalid inverse operation")
            raw = raw_object
            kind = raw.get("kind")
            if kind == "set_combatant_hp":
                combatant = session.get(Combatant, raw.get("combatant_id"))
                if combatant is None or combatant.combat_id != combat.id:
                    raise ValueError("combatant changed; adjustment cannot be reverted")
                hp = raw.get("hp")
                if not isinstance(hp, int) or hp < 0 or hp > combatant.max_hp:
                    raise ValueError("stored HP inverse is invalid")
                combatant.hp = hp
                combatant.version += 1
            elif kind == "remove_combatant_condition":
                combatant = session.get(Combatant, raw.get("combatant_id"))
                condition = raw.get("condition")
                if combatant is None or combatant.combat_id != combat.id:
                    raise ValueError("combatant changed; adjustment cannot be reverted")
                combatant.conditions = [
                    item for item in list(combatant.conditions or []) if item != condition
                ]
                combatant.version += 1
            elif kind == "set_combatant_active":
                combatant = session.get(Combatant, raw.get("combatant_id"))
                active = raw.get("is_active")
                if (
                    combatant is None
                    or combatant.combat_id != combat.id
                    or not isinstance(active, bool)
                ):
                    raise ValueError("combatant active state cannot be reverted")
                combatant.is_active = active
                combatant.version += 1
            elif kind == "delete_combatant":
                combatant = session.get(Combatant, raw.get("combatant_id"))
                if combatant is None or combatant.combat_id != combat.id:
                    raise ValueError("added combatant cannot be reverted")
                session.delete(combatant)
            elif kind == "remove_reinforcement":
                entry = raw.get("entry")
                reinforcements = list(combat.difficulty_adjustments or [])
                if entry not in reinforcements:
                    raise ValueError("reinforcement changed; adjustment cannot be reverted")
                reinforcements.remove(entry)
                combat.difficulty_adjustments = reinforcements
            else:
                raise ValueError("unsupported inverse operation")

    def revert(
        self,
        campaign_id: str,
        proposal_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            proposal = self._proposal(session, campaign_id, proposal_id)
            if proposal.status == "reverted":
                return serialize(proposal)
            if proposal.status != "applied":
                raise ValueError("only applied encounter adjustments can be reverted")
            if proposal.version != expected_version:
                raise VersionConflict(
                    "encounter adjustment",
                    proposal_id,
                    expected_version,
                    proposal.version,
                )
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return serialize(proposal)

            if proposal.combat_id is not None:
                combat = session.get(Combat, proposal.combat_id)
                if combat is None or combat.campaign_id != campaign_id:
                    raise StateNotFoundError("combat not found in campaign")
                if combat.xp_awarded:
                    raise ValueError("settled combat adjustment cannot be reverted")
                self._revert_operations(
                    session,
                    combat,
                    proposal.inverse_operations_json,
                )
                combat.version += 1
                combat.updated_at = datetime.now(UTC)

            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="encounter_adjustment_revert",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={
                    "proposal_id": proposal.id,
                    "operations": proposal.operations_json,
                },
                after_snapshot={
                    "proposal_id": proposal.id,
                    "inverse_operations": proposal.inverse_operations_json,
                },
                reason=f"Revert: {proposal.reason}",
                source="combat",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            if proposal.operation_transaction_id is not None:
                applied_transaction = session.get(
                    OperationTransaction,
                    proposal.operation_transaction_id,
                )
                if applied_transaction is not None:
                    applied_transaction.status = "reverted"
                    applied_transaction.reverted_at = datetime.now(UTC)
                    applied_transaction.version += 1
            proposal.status = "reverted"
            proposal.reverted_at = datetime.now(UTC)
            proposal.version += 1
            proposal.updated_at = datetime.now(UTC)
            session.flush()
            return serialize(proposal)
