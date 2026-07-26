from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import (
    CombatActionCommand,
    DeathConfirmationCommand,
    DeathSaveCommand,
    TurnAdvanceCommand,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.combat import (
    resolve_damage,
    resolve_death_save,
    resolve_healing,
)
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    Campaign,
    Combat,
    CombatAction,
    Combatant,
    DeathSave,
    OperationTransaction,
)


class CombatEngineService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _scope(
        session: Session,
        campaign_id: str,
        combat_id: str,
        command: CombatActionCommand,
    ) -> tuple[Combat, Combatant, Combatant | None]:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        combat = session.get(Combat, combat_id)
        if combat is None or combat.campaign_id != campaign_id:
            raise StateNotFoundError("combat not found in campaign")
        target = session.get(Combatant, command.target_combatant_id)
        if target is None or target.combat_id != combat_id:
            raise StateNotFoundError("target combatant not found in combat")
        actor = None
        if command.actor_combatant_id is not None:
            actor = session.get(Combatant, command.actor_combatant_id)
            if actor is None or actor.combat_id != combat_id:
                raise StateNotFoundError("actor combatant not found in combat")
        return combat, target, actor

    @staticmethod
    def _resolve(
        command: CombatActionCommand,
        target: Combatant,
    ) -> dict[str, Any]:
        before = {
            "hp": target.hp,
            "max_hp": target.max_hp,
            "max_hp_reduction": target.max_hp_reduction,
            "temporary_hp": target.temporary_hp,
            "version": target.version,
        }
        concentration_check_dc: int | None = None
        if command.action_type == "damage":
            damage_resolution = resolve_damage(
                amount=command.amount,
                current_hp=target.hp,
                temporary_hp=target.temporary_hp,
                damage_type=command.damage_type or "",
                resistances=tuple(target.damage_resistances),
                vulnerabilities=tuple(target.damage_vulnerabilities),
                immunities=tuple(target.damage_immunities),
            )
            result = asdict(damage_resolution)
            after = {
                **before,
                "hp": damage_resolution.remaining_hp,
                "temporary_hp": damage_resolution.remaining_temporary_hp,
            }
            if damage_resolution.adjusted_damage > 0 and target.concentration:
                concentration_check_dc = max(
                    10,
                    damage_resolution.adjusted_damage // 2,
                )
        else:
            healing_resolution = resolve_healing(
                amount=command.amount,
                current_hp=target.hp,
                max_hp=target.max_hp,
                max_hp_reduction=target.max_hp_reduction,
            )
            result = asdict(healing_resolution)
            after = {**before, "hp": healing_resolution.remaining_hp}
        after["version"] = target.version + 1
        return {
            "before": before,
            "after": after,
            "result": result,
            "concentration_check_dc": concentration_check_dc,
        }

    @staticmethod
    def _death_save(session: Session, target: Combatant) -> DeathSave:
        death_save = session.scalar(
            select(DeathSave).where(DeathSave.combatant_id == target.id)
        )
        if death_save is None:
            death_save = DeathSave(combatant_id=target.id)
            session.add(death_save)
            session.flush()
        return death_save

    def preview(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatActionCommand,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            _, target, _ = self._scope(session, campaign_id, combat_id, command)
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            return self._resolve(command, target)

    def confirm(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatActionCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            combat, target, actor = self._scope(
                session,
                campaign_id,
                combat_id,
                command,
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                existing_target_id = (
                    existing.target_combatant_ids[0]
                    if existing.target_combatant_ids
                    else None
                )
                existing_target = (
                    session.get(Combatant, existing_target_id)
                    if isinstance(existing_target_id, str)
                    else None
                )
                return {
                    "action": serialize(existing),
                    "target": serialize(existing_target) if existing_target is not None else None,
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            resolved = self._resolve(command, target)
            before = serialize(target)
            after = resolved["after"]
            target.hp = int(after["hp"])
            target.temporary_hp = int(after["temporary_hp"])
            target.version += 1
            target.updated_at = datetime.now(UTC)
            if target.hp == 0:
                self._death_save(session, target)
            elif command.action_type == "heal":
                death_save = session.scalar(
                    select(DeathSave).where(DeathSave.combatant_id == target.id)
                )
                if death_save is not None:
                    death_save.successes = 0
                    death_save.failures = 0
                    death_save.stable = False
                    death_save.dead = False
                    death_save.pending_death_confirmation = False
                    death_save.last_roll = None
                    death_save.version += 1
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type=f"combat_{command.action_type}",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"combatant": before},
                after_snapshot={
                    "combatant_id": target.id,
                    "hp": target.hp,
                    "temporary_hp": target.temporary_hp,
                },
                reason=command.override_reason
                if command.dm_override
                else f"{command.action_type} confirmed in combat",
                source="combat",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            result = dict(resolved["result"])
            if resolved["concentration_check_dc"] is not None:
                result["concentration_check_dc"] = resolved["concentration_check_dc"]
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=actor.id if actor is not None else None,
                transaction_id=transaction.id,
                action_type=command.action_type,
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=result.get("explanation"),
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"{target.display_name} 受到 {result['adjusted_damage']} 点"
                    f"{command.damage_type or ''}伤害"
                    if command.action_type == "damage"
                    else f"{target.display_name} 恢复 {result['hp_gained']} 点生命"
                ),
                idempotency_key=idempotency_key,
                dm_override=command.dm_override,
                override_reason=command.override_reason,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {"action": serialize(action), "target": serialize(target)}

    def get_death_save(
        self,
        campaign_id: str,
        combat_id: str,
        combatant_id: str,
    ) -> dict[str, Any]:
        command = CombatActionCommand(
            action_type="heal",
            target_combatant_id=combatant_id,
            target_version=1,
            amount=0,
        )
        with Session(self.engine) as session:
            _, target, _ = self._scope(session, campaign_id, combat_id, command)
            death_save = session.scalar(
                select(DeathSave).where(DeathSave.combatant_id == target.id)
            )
            if death_save is None:
                if target.hp != 0:
                    raise ValueError("death saves are only available at 0 HP")
                return {
                    "combatant_id": target.id,
                    "successes": 0,
                    "failures": 0,
                    "stable": False,
                    "dead": False,
                    "pending_death_confirmation": False,
                    "last_roll": None,
                    "version": 1,
                }
            return serialize(death_save)

    def confirm_death_save(
        self,
        campaign_id: str,
        combat_id: str,
        combatant_id: str,
        command: DeathSaveCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope_command = CombatActionCommand(
            action_type="heal",
            target_combatant_id=combatant_id,
            target_version=command.target_version,
            amount=0,
        )
        with Session(self.engine) as session, session.begin():
            combat, target, _ = self._scope(
                session,
                campaign_id,
                combat_id,
                scope_command,
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                death_save = self._death_save(session, target)
                return {
                    "action": serialize(existing),
                    "target": serialize(target),
                    "death_save": serialize(death_save),
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if target.hp != 0:
                raise ValueError("death saves are only available at 0 HP")
            death_save = self._death_save(session, target)
            if death_save.dead or death_save.pending_death_confirmation:
                raise ValueError("death save track cannot advance in its current state")
            resolution = resolve_death_save(
                roll=command.roll,
                successes=death_save.successes,
                failures=death_save.failures,
            )
            before_target = serialize(target)
            before_death_save = serialize(death_save)
            death_save.successes = resolution.successes
            death_save.failures = resolution.failures
            death_save.stable = resolution.stable
            death_save.pending_death_confirmation = (
                resolution.pending_death_confirmation
            )
            death_save.last_roll = command.roll
            death_save.version += 1
            if resolution.hp_restored:
                target.hp = resolution.hp_restored
            target.version += 1
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_death_save",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={
                    "combatant": before_target,
                    "death_save": before_death_save,
                },
                after_snapshot={
                    "combatant_id": target.id,
                    "hp": target.hp,
                    "successes": death_save.successes,
                    "failures": death_save.failures,
                    "stable": death_save.stable,
                    "pending_death_confirmation": (
                        death_save.pending_death_confirmation
                    ),
                },
                reason="DM confirmed death save roll",
                source="combat",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            result = asdict(resolution)
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                transaction_id=transaction.id,
                action_type="death_save",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=resolution.explanation,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{target.display_name}：{resolution.explanation}",
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "target": serialize(target),
                "death_save": serialize(death_save),
            }

    def confirm_death(
        self,
        campaign_id: str,
        combat_id: str,
        combatant_id: str,
        command: DeathConfirmationCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope_command = CombatActionCommand(
            action_type="heal",
            target_combatant_id=combatant_id,
            target_version=command.target_version,
            amount=0,
        )
        with Session(self.engine) as session, session.begin():
            combat, target, _ = self._scope(
                session,
                campaign_id,
                combat_id,
                scope_command,
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            death_save = self._death_save(session, target)
            if existing is not None:
                return {
                    "action": serialize(existing),
                    "target": serialize(target),
                    "death_save": serialize(death_save),
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if not death_save.pending_death_confirmation:
                raise ValueError("death is not awaiting confirmation")
            before = serialize(death_save)
            death_save.dead = True
            death_save.pending_death_confirmation = False
            death_save.version += 1
            target.version += 1
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_confirm_death",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"death_save": before},
                after_snapshot={
                    "combatant_id": target.id,
                    "dead": True,
                },
                reason=command.reason,
                source="combat",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                transaction_id=transaction.id,
                action_type="confirm_death",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json={"dead": True, "reason": command.reason},
                explanation=command.reason,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{target.display_name} 已由 DM 确认死亡",
                idempotency_key=idempotency_key,
                dm_override=True,
                override_reason=command.reason,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "target": serialize(target),
                "death_save": serialize(death_save),
            }

    def advance_turn(
        self,
        campaign_id: str,
        combat_id: str,
        command: TurnAdvanceCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                active_id = existing.result_json.get("active_combatant_id")
                active = (
                    session.get(Combatant, active_id)
                    if isinstance(active_id, str)
                    else None
                )
                return {
                    "action": serialize(existing),
                    "combat": serialize(combat),
                    "active_combatant": (
                        serialize(active) if active is not None else None
                    ),
                    "expiration_prompts": existing.result_json.get(
                        "expiration_prompts",
                        [],
                    ),
                }
            if combat.version != command.combat_version:
                raise VersionConflict(
                    "combat",
                    combat.id,
                    command.combat_version,
                    combat.version,
                )
            if combat.status in {"completed", "cancelled"}:
                raise ValueError("completed combat cannot advance turns")
            ordered = session.scalars(
                select(Combatant)
                .where(
                    Combatant.combat_id == combat_id,
                    Combatant.is_active.is_(True),
                )
                .order_by(
                    Combatant.initiative.desc(),
                    Combatant.created_at,
                    Combatant.id,
                )
            ).all()
            if not ordered:
                raise ValueError("combat has no active combatants")
            before = serialize(combat)
            next_index = combat.current_turn_index + 1
            next_round = combat.round_number
            if next_index >= len(ordered):
                next_index = 0
                next_round += 1
            active = ordered[next_index]
            combat.current_turn_index = next_index
            combat.round_number = next_round
            combat.version += 1
            active.movement_remaining_ft = active.speed_ft
            active.action_available = True
            active.bonus_action_available = True
            active.reaction_available = True
            active.version += 1
            now = datetime.now(UTC)
            active.updated_at = now
            combat.updated_at = now
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_advance_turn",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"combat": before},
                after_snapshot={
                    "combat_id": combat.id,
                    "round_number": combat.round_number,
                    "current_turn_index": combat.current_turn_index,
                    "active_combatant_id": active.id,
                },
                reason="DM advanced combat turn",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            result: dict[str, Any] = {
                "active_combatant_id": active.id,
                "round_number": combat.round_number,
                "turn_index": combat.current_turn_index,
                "expiration_prompts": [],
            }
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=active.id,
                transaction_id=transaction.id,
                action_type="advance_turn",
                target_combatant_ids=[active.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation="恢复新回合角色的动作、附赠动作、反应与移动",
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"第 {combat.round_number} 轮：轮到 {active.display_name}"
                ),
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "combat": serialize(combat),
                "active_combatant": serialize(active),
                "expiration_prompts": [],
            }

    def list_actions(
        self,
        campaign_id: str,
        combat_id: str,
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            rows = session.scalars(
                select(CombatAction)
                .where(CombatAction.combat_id == combat_id)
                .order_by(CombatAction.created_at, CombatAction.id)
            ).all()
            return tuple(serialize(row) for row in rows)
