from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import (
    CombatActionCommand,
    CombatEffectCommand,
    CombatEffectEndCommand,
    CombatSettlementCommand,
    ConcentrationCheckCommand,
    DeathConfirmationCommand,
    DeathSaveCommand,
    PlayerRollPromptCommand,
    PlayerRollResolutionCommand,
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
    NPC,
    Campaign,
    Character,
    CharacterCondition,
    Combat,
    CombatAction,
    Combatant,
    CombatEffect,
    CombatSettlement,
    CurrencyTransaction,
    DeathSave,
    MonsterInstance,
    OperationTransaction,
    SceneParticipant,
    Wallet,
    WorldItem,
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
    def _validate_action_economy(
        session: Session,
        combat: Combat,
        actor: Combatant | None,
        *,
        actor_version: int | None,
        action_cost: str,
        consume: bool,
    ) -> None:
        if action_cost == "none":
            return
        if actor is None or actor_version is None:
            raise ValueError("an actor and actor version are required to spend an action")
        if actor.version != actor_version:
            raise VersionConflict(
                "combatant",
                actor.id,
                actor_version,
                actor.version,
            )
        ordered = session.scalars(
            select(Combatant)
            .where(
                Combatant.combat_id == combat.id,
                Combatant.is_active.is_(True),
            )
            .order_by(
                Combatant.initiative.desc(),
                Combatant.created_at,
                Combatant.id,
            )
        ).all()
        active = ordered[combat.current_turn_index] if ordered else None
        if active is None or active.id != actor.id:
            raise ValueError("only the active combatant can spend actions")
        field = {
            "action": "action_available",
            "bonus_action": "bonus_action_available",
            "reaction": "reaction_available",
        }.get(action_cost)
        if field is None:
            raise ValueError("unsupported action cost")
        if not bool(getattr(actor, field)):
            raise ValueError(f"{action_cost} has already been spent this turn")
        if consume:
            setattr(actor, field, False)
            actor.version += 1
            actor.updated_at = datetime.now(UTC)

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

    @staticmethod
    def _end_condition(session: Session, combat: Combat) -> dict[str, Any]:
        hostiles = list(
            session.scalars(
                select(Combatant)
                .where(
                    Combatant.combat_id == combat.id,
                    Combatant.entity_type == "monster",
                )
                .order_by(Combatant.initiative.desc(), Combatant.id)
            )
        )
        defeated = [
            row
            for row in hostiles
            if row.hp <= 0 or not row.is_active
        ]
        remaining = [row for row in hostiles if row not in defeated]
        can_end = bool(hostiles) and not remaining and combat.status == "active"
        return {
            "can_end": can_end,
            "suggested_resolution_type": "victory" if can_end else None,
            "reason": (
                "all_hostile_monsters_defeated"
                if can_end
                else "hostile_monsters_remain"
                if remaining
                else "no_hostile_monsters"
            ),
            "hostile_count": len(hostiles),
            "defeated_count": len(defeated),
            "remaining_hostiles": [
                {
                    "combatant_id": row.id,
                    "display_name": row.display_name,
                    "hp": row.hp,
                }
                for row in remaining
            ],
            "requires_dm_confirmation": can_end,
        }

    def get_end_condition(
        self,
        campaign_id: str,
        combat_id: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            return self._end_condition(session, combat)

    @staticmethod
    def _player_roll_scope(
        session: Session,
        campaign_id: str,
        combat_id: str,
        action_id: str,
    ) -> tuple[Combat, CombatAction, Combatant, Combatant]:
        combat = session.get(Combat, combat_id)
        if combat is None or combat.campaign_id != campaign_id:
            raise StateNotFoundError("combat not found in campaign")
        action = session.get(CombatAction, action_id)
        if (
            action is None
            or action.combat_id != combat_id
            or action.campaign_id != campaign_id
            or action.action_type != "player_roll_prompt"
        ):
            raise StateNotFoundError("player roll prompt not found in combat")
        actor = (
            session.get(Combatant, action.actor_combatant_id)
            if action.actor_combatant_id is not None
            else None
        )
        target_id = (
            action.target_combatant_ids[0]
            if action.target_combatant_ids
            else None
        )
        target = (
            session.get(Combatant, target_id)
            if isinstance(target_id, str)
            else None
        )
        if (
            actor is None
            or actor.combat_id != combat_id
            or target is None
            or target.combat_id != combat_id
        ):
            raise StateNotFoundError("prompt actor or target is no longer in combat")
        return combat, action, actor, target

    def create_player_roll_prompt(
        self,
        campaign_id: str,
        combat_id: str,
        command: PlayerRollPromptCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
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
                return {"action": serialize(existing)}
            actor = session.get(Combatant, command.actor_combatant_id)
            target = session.get(Combatant, command.target_combatant_id)
            if actor is None or actor.combat_id != combat_id:
                raise StateNotFoundError("actor combatant not found in combat")
            if target is None or target.combat_id != combat_id:
                raise StateNotFoundError("target combatant not found in combat")
            if actor.version != command.actor_version:
                raise VersionConflict(
                    "combatant",
                    actor.id,
                    command.actor_version,
                    actor.version,
                )
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            self._validate_action_economy(
                session,
                combat,
                actor,
                actor_version=command.actor_version,
                action_cost=command.action_cost,
                consume=True,
            )
            request_json = command.model_dump(mode="json")
            request_json["actor_name"] = actor.display_name
            request_json["target_name"] = target.display_name
            label = {
                "armor_class": "AC 防御",
                "saving_throw": f"{command.ability or ''}豁免",
                "ability_check": f"{command.ability or ''}属性检定",
                "skill_check": f"{command.skill or ''}技能检定",
            }[command.resolution_type]
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=actor.id,
                action_type="player_roll_prompt",
                target_combatant_ids=[target.id],
                request_json=request_json,
                result_json={
                    "phase": "awaiting_player_roll",
                    "roll_owner": "player",
                },
                explanation=command.description,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"{actor.display_name} 对 {target.display_name} 使用"
                    f"「{command.action_name}」；等待玩家进行 {label}"
                    f"（{command.roll_formula}，DC {command.dc}）"
                ),
                idempotency_key=idempotency_key,
                status="previewed",
            )
            session.add(action)
            session.flush()
            return {"action": serialize(action)}

    @staticmethod
    def _resolve_player_roll(
        action: CombatAction,
        target: Combatant,
        command: PlayerRollResolutionCommand,
    ) -> dict[str, Any]:
        request = action.request_json
        dc = int(str(request["dc"]))
        success = command.roll_total >= dc
        damage_key = "damage_on_success" if success else "damage_on_failure"
        damage = int(str(request.get(damage_key, 0)))
        result: dict[str, Any] = {
            "phase": "resolved",
            "roll_owner": "player",
            "roll_total": command.roll_total,
            "dc": dc,
            "success": success,
            "outcome": "success" if success else "failure",
            "damage": damage,
            "damage_type": request.get("damage_type"),
            "dm_note": command.dm_note,
        }
        result["follow_up_damage"] = (
            {
                "action_type": "damage",
                "actor_combatant_id": action.actor_combatant_id,
                "action_cost": "none",
                "action_name": request["action_name"],
                "resolution_note": (
                    f"{target.display_name} 的玩家骰总值 {command.roll_total}"
                    f" 对抗 DC {dc}，{'成功' if success else '失败'}；"
                    f"结算 {damage} 点{request.get('damage_type') or ''}伤害"
                ),
                "target_combatant_id": target.id,
                "target_version": target.version,
                "amount": damage,
                "damage_type": request.get("damage_type"),
            }
            if damage > 0
            else None
        )
        return result

    def preview_player_roll(
        self,
        campaign_id: str,
        combat_id: str,
        action_id: str,
        command: PlayerRollResolutionCommand,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            _, action, actor, target = self._player_roll_scope(
                session, campaign_id, combat_id, action_id
            )
            if action.version != command.action_version:
                raise VersionConflict(
                    "combat_action",
                    action.id,
                    command.action_version,
                    action.version,
                )
            if action.status != "previewed":
                raise ValueError("player roll prompt has already been resolved")
            return {
                "action": serialize(action),
                "actor": serialize(actor),
                "target": serialize(target),
                "resolution": self._resolve_player_roll(action, target, command),
            }

    def confirm_player_roll(
        self,
        campaign_id: str,
        combat_id: str,
        action_id: str,
        command: PlayerRollResolutionCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            _, action, actor, target = self._player_roll_scope(
                session, campaign_id, combat_id, action_id
            )
            if action.status == "confirmed":
                return {
                    "action": serialize(action),
                    "actor": serialize(actor),
                    "target": serialize(target),
                    "resolution": action.result_json,
                }
            if action.version != command.action_version:
                raise VersionConflict(
                    "combat_action",
                    action.id,
                    command.action_version,
                    action.version,
                )
            resolution = self._resolve_player_roll(action, target, command)
            action.result_json = {
                **resolution,
                "confirmation_idempotency_key": idempotency_key,
            }
            action.status = "confirmed"
            action.version += 1
            action.updated_at = datetime.now(UTC)
            action.summary = (
                f"{actor.display_name} 对 {target.display_name} 使用"
                f"「{action.request_json['action_name']}」；"
                f"{target.display_name} 掷骰 {command.roll_total} 对抗"
                f" DC {action.request_json['dc']}，"
                f"{'成功' if resolution['success'] else '失败'}"
            )
            return {
                "action": serialize(action),
                "actor": serialize(actor),
                "target": serialize(target),
                "resolution": action.result_json,
            }

    def preview(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatActionCommand,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            combat, target, actor = self._scope(
                session, campaign_id, combat_id, command
            )
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            self._validate_action_economy(
                session,
                combat,
                actor,
                actor_version=command.actor_version,
                action_cost=command.action_cost,
                consume=False,
            )
            if command.action_type == "heal" and target.hp == 0:
                death_save = session.scalar(
                    select(DeathSave).where(DeathSave.combatant_id == target.id)
                )
                if (
                    death_save is not None
                    and death_save.dead
                    and not command.dm_override
                ):
                    raise ValueError(
                        "ordinary healing cannot restore a dead combatant; "
                        "use a DM override for a resurrection effect"
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
                    "end_condition": self._end_condition(session, combat),
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            self._validate_action_economy(
                session,
                combat,
                actor,
                actor_version=command.actor_version,
                action_cost=command.action_cost,
                consume=True,
            )
            if command.action_type == "heal" and target.hp == 0:
                current_death_save = session.scalar(
                    select(DeathSave).where(DeathSave.combatant_id == target.id)
                )
                if (
                    current_death_save is not None
                    and current_death_save.dead
                    and not command.dm_override
                ):
                    raise ValueError(
                        "ordinary healing cannot restore a dead combatant; "
                        "use a DM override for a resurrection effect"
                    )
            resolved = self._resolve(command, target)
            before = serialize(target)
            after = resolved["after"]
            target.hp = int(after["hp"])
            target.temporary_hp = int(after["temporary_hp"])
            target.version += 1
            target.updated_at = datetime.now(UTC)
            death_save_result: dict[str, Any] | None = None
            if command.action_type == "damage" and target.hp == 0:
                death_save = self._death_save(session, target)
                was_at_zero = int(resolved["before"]["hp"]) == 0
                massive_damage = (
                    int(resolved["result"]["unapplied_damage"]) >= target.max_hp
                    and target.max_hp > 0
                )
                if massive_damage:
                    death_save.failures = 3
                    death_save.successes = 0
                    death_save.stable = False
                    death_save.dead = True
                    death_save.pending_death_confirmation = False
                    death_save.version += 1
                    death_save_result = {
                        "failures_added": 3,
                        "massive_damage": True,
                        "dead": True,
                        "explanation": "剩余伤害达到最大生命值，角色立即死亡",
                    }
                elif was_at_zero and int(resolved["result"]["adjusted_damage"]) > 0:
                    failures_added = 2 if command.critical_hit else 1
                    death_save.failures = min(
                        3, death_save.failures + failures_added
                    )
                    death_save.successes = 0
                    death_save.stable = False
                    death_save.dead = death_save.failures >= 3
                    death_save.pending_death_confirmation = False
                    death_save.version += 1
                    death_save_result = {
                        "failures_added": failures_added,
                        "massive_damage": False,
                        "dead": death_save.dead,
                        "explanation": (
                            f"0 HP 时受到{'暴击' if command.critical_hit else ''}伤害，"
                            f"累计 {failures_added} 次死亡豁免失败"
                        ),
                    }
            elif command.action_type == "heal":
                existing_death_save = session.scalar(
                    select(DeathSave).where(DeathSave.combatant_id == target.id)
                )
                if existing_death_save is not None:
                    existing_death_save.successes = 0
                    existing_death_save.failures = 0
                    existing_death_save.stable = False
                    existing_death_save.dead = False
                    existing_death_save.pending_death_confirmation = False
                    existing_death_save.last_roll = None
                    existing_death_save.version += 1
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
            if death_save_result is not None:
                result["death_save"] = death_save_result
            if resolved["concentration_check_dc"] is not None:
                result["concentration_check_dc"] = resolved["concentration_check_dc"]
            if command.action_type == "damage" and actor is not None:
                action_result = command.resolution_note or (
                    f"造成 {result['adjusted_damage']} 点"
                    f"{command.damage_type or ''}伤害"
                )
                action_summary = (
                    f"{actor.display_name} 对 {target.display_name} 使用"
                    f"「{command.action_name or '攻击'}」；{action_result}"
                )
            elif command.action_type == "damage":
                action_summary = (
                    f"{target.display_name} 受到 {result['adjusted_damage']} 点"
                    f"{command.damage_type or ''}伤害"
                )
            else:
                action_summary = (
                    f"{target.display_name} 恢复 {result['hp_gained']} 点生命"
                )
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
                summary=action_summary,
                idempotency_key=idempotency_key,
                dm_override=command.dm_override,
                override_reason=command.override_reason,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "target": serialize(target),
                "death_save": (
                    serialize(death_save)
                    if command.action_type == "damage" and target.hp == 0
                    else None
                ),
                "end_condition": self._end_condition(session, combat),
            }

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
            if (
                death_save.dead
                or death_save.stable
                or death_save.pending_death_confirmation
            ):
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
            death_save.dead = resolution.dead
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
            expiring_effects = session.scalars(
                select(CombatEffect)
                .where(
                    CombatEffect.combat_id == combat_id,
                    CombatEffect.status == "active",
                    CombatEffect.ends_round.is_not(None),
                    CombatEffect.ends_round <= combat.round_number,
                )
                .order_by(CombatEffect.ends_round, CombatEffect.created_at, CombatEffect.id)
            ).all()
            expiration_prompts = [serialize(effect) for effect in expiring_effects]
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
                "expiration_prompts": expiration_prompts,
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
                "expiration_prompts": expiration_prompts,
            }

    @staticmethod
    def _effect_scope(
        session: Session,
        campaign_id: str,
        combat_id: str,
        command: CombatEffectCommand,
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
        source = None
        if command.source_combatant_id is not None:
            source = session.get(Combatant, command.source_combatant_id)
            if source is None or source.combat_id != combat_id:
                raise StateNotFoundError("source combatant not found in combat")
        return combat, target, source

    @staticmethod
    def _active_concentration_effects(
        session: Session,
        combat_id: str,
        source_id: str | None,
    ) -> list[CombatEffect]:
        if source_id is None:
            return []
        return list(
            session.scalars(
                select(CombatEffect)
                .where(
                    CombatEffect.combat_id == combat_id,
                    CombatEffect.source_combatant_id == source_id,
                    CombatEffect.requires_concentration.is_(True),
                    CombatEffect.status == "active",
                )
                .order_by(CombatEffect.created_at, CombatEffect.id)
            ).all()
        )

    def preview_effect(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatEffectCommand,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            combat, target, source = self._effect_scope(
                session,
                campaign_id,
                combat_id,
                command,
            )
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if (
                source is not None
                and source.id != target.id
                and source.version != command.source_version
            ):
                raise VersionConflict(
                    "combatant",
                    source.id,
                    command.source_version or 0,
                    source.version,
                )
            old_effects = (
                self._active_concentration_effects(session, combat_id, source.id)
                if command.requires_concentration and source is not None
                else []
            )
            ends_round = (
                combat.round_number + int(command.duration_value or 0)
                if command.duration_unit == "rounds"
                else None
            )
            return {
                "effect": {
                    **command.model_dump(mode="json"),
                    "started_round": combat.round_number,
                    "ends_round": ends_round,
                    "status": "active",
                },
                "effects_to_end": [serialize(effect) for effect in old_effects],
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
            }

    def confirm_effect(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatEffectCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            combat, target, source = self._effect_scope(
                session,
                campaign_id,
                combat_id,
                command,
            )
            existing_action = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing_action is not None:
                effect_id = existing_action.result_json.get("effect_id")
                effect = (
                    session.get(CombatEffect, effect_id)
                    if isinstance(effect_id, str)
                    else None
                )
                if effect is None:
                    raise ValueError("confirmed effect record is missing")
                ended_ids_raw = existing_action.result_json.get(
                    "ended_effect_ids",
                    [],
                )
                ended_ids = (
                    ended_ids_raw if isinstance(ended_ids_raw, list) else []
                )
                ended_effects = [
                    row
                    for effect_id_value in ended_ids
                    if isinstance(effect_id_value, str)
                    and (row := session.get(CombatEffect, effect_id_value)) is not None
                ]
                return {
                    "action": serialize(existing_action),
                    "effect": serialize(effect),
                    "ended_effects": [serialize(row) for row in ended_effects],
                    "target": serialize(target),
                    "source": serialize(source) if source is not None else None,
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if (
                source is not None
                and source.id != target.id
                and source.version != command.source_version
            ):
                raise VersionConflict(
                    "combatant",
                    source.id,
                    command.source_version or 0,
                    source.version,
                )
            now = datetime.now(UTC)
            old_effects = (
                self._active_concentration_effects(session, combat_id, source.id)
                if command.requires_concentration and source is not None
                else []
            )
            before = {
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
                "effects_to_end": [serialize(row) for row in old_effects],
            }
            for old_effect in old_effects:
                old_effect.status = "ended"
                old_effect.ended_at = now
                old_effect.end_reason = f"开始新专注：{command.name}"
                old_effect.version += 1
            ends_round = (
                combat.round_number + int(command.duration_value or 0)
                if command.duration_unit == "rounds"
                else None
            )
            effect = CombatEffect(
                campaign_id=campaign_id,
                combat_id=combat_id,
                target_combatant_id=target.id,
                source_combatant_id=source.id if source is not None else None,
                name=command.name,
                effect_type=command.effect_type,
                details_json=command.details_json,
                started_round=combat.round_number,
                duration_unit=command.duration_unit,
                duration_value=command.duration_value,
                ends_round=ends_round,
                requires_concentration=command.requires_concentration,
                save_dc=command.save_dc,
                save_ability=command.save_ability,
                trigger_timing=command.trigger_timing,
                status="active",
            )
            session.add(effect)
            session.flush()
            if command.requires_concentration and source is not None:
                source.concentration = {
                    "effect_id": effect.id,
                    "name": effect.name,
                    "started_round": combat.round_number,
                }
            target.version += 1
            target.updated_at = now
            if source is not None and source.id != target.id:
                source.version += 1
                source.updated_at = now
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_add_effect",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot=before,
                after_snapshot={
                    "effect": serialize(effect),
                    "ended_effect_ids": [row.id for row in old_effects],
                },
                reason=f"DM confirmed effect: {command.name}",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            result = {
                "effect_id": effect.id,
                "ended_effect_ids": [row.id for row in old_effects],
                "requires_concentration": command.requires_concentration,
            }
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=source.id if source is not None else None,
                transaction_id=transaction.id,
                action_type="add_effect",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=(
                    f"结束 {len(old_effects)} 个旧专注效果"
                    if old_effects
                    else "建立结构化战斗效果"
                ),
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{target.display_name} 获得效果：{command.name}",
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "effect": serialize(effect),
                "ended_effects": [serialize(row) for row in old_effects],
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
            }

    def list_effects(
        self,
        campaign_id: str,
        combat_id: str,
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            rows = session.scalars(
                select(CombatEffect)
                .where(CombatEffect.combat_id == combat_id)
                .order_by(CombatEffect.created_at, CombatEffect.id)
            ).all()
            return tuple(serialize(row) for row in rows)

    def confirm_concentration_check(
        self,
        campaign_id: str,
        combat_id: str,
        command: ConcentrationCheckCommand,
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
            target = session.get(Combatant, command.combatant_id)
            if target is None or target.combat_id != combat_id:
                raise StateNotFoundError("combatant not found in combat")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                ended_ids_raw = existing.result_json.get("ended_effect_ids", [])
                ended_ids = (
                    ended_ids_raw if isinstance(ended_ids_raw, list) else []
                )
                existing_ended = [
                    row
                    for effect_id in ended_ids
                    if isinstance(effect_id, str)
                    and (row := session.get(CombatEffect, effect_id)) is not None
                ]
                return {
                    "action": serialize(existing),
                    "target": serialize(target),
                    "dc": existing.result_json.get("dc"),
                    "roll_total": existing.result_json.get("roll_total"),
                    "success": existing.result_json.get("success"),
                    "ended_effects": [serialize(row) for row in existing_ended],
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            damage_action = session.get(CombatAction, command.damage_action_id)
            if damage_action is None or damage_action.combat_id != combat_id:
                raise StateNotFoundError("damage action not found in combat")
            if (
                damage_action.action_type != "damage"
                or target.id not in damage_action.target_combatant_ids
            ):
                raise ValueError("action does not require this target's concentration check")
            raw_dc = damage_action.result_json.get("concentration_check_dc")
            if not isinstance(raw_dc, int) or raw_dc <= 0:
                raise ValueError("damage action has no concentration check")
            success = command.roll_total >= raw_dc
            active_effects = self._active_concentration_effects(
                session,
                combat_id,
                target.id,
            )
            before = {
                "target": serialize(target),
                "effects": [serialize(row) for row in active_effects],
            }
            ended: list[CombatEffect] = []
            now = datetime.now(UTC)
            if not success:
                for effect in active_effects:
                    effect.status = "ended"
                    effect.ended_at = now
                    effect.end_reason = (
                        f"专注检定失败：{command.roll_total} < DC {raw_dc}"
                    )
                    effect.version += 1
                    ended.append(effect)
                target.concentration = {}
                target.version += 1
                target.updated_at = now
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_concentration_check",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot=before,
                after_snapshot={
                    "combatant_id": target.id,
                    "dc": raw_dc,
                    "roll_total": command.roll_total,
                    "success": success,
                    "ended_effect_ids": [row.id for row in ended],
                },
                reason="DM confirmed concentration check",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            result = {
                "dc": raw_dc,
                "roll_total": command.roll_total,
                "success": success,
                "ended_effect_ids": [row.id for row in ended],
                "damage_action_id": damage_action.id,
            }
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=target.id,
                transaction_id=transaction.id,
                action_type="concentration_check",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=(
                    f"{command.roll_total} 对抗 DC {raw_dc}："
                    f"{'成功，维持专注' if success else '失败，结束专注'}"
                ),
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"{target.display_name} 专注检定"
                    f"{'成功' if success else '失败'}"
                ),
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "target": serialize(target),
                "dc": raw_dc,
                "roll_total": command.roll_total,
                "success": success,
                "ended_effects": [serialize(row) for row in ended],
            }

    def end_effect(
        self,
        campaign_id: str,
        combat_id: str,
        effect_id: str,
        command: CombatEffectEndCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            effect = session.get(CombatEffect, effect_id)
            if effect is None or effect.combat_id != combat_id:
                raise StateNotFoundError("effect not found in combat")
            target = session.get(Combatant, effect.target_combatant_id)
            if target is None:
                raise StateNotFoundError("effect target is missing")
            source = (
                session.get(Combatant, effect.source_combatant_id)
                if effect.source_combatant_id is not None
                else None
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return {
                    "action": serialize(existing),
                    "effect": serialize(effect),
                    "target": serialize(target),
                    "source": serialize(source) if source is not None else None,
                }
            if effect.status != "active":
                raise ValueError("effect is already ended")
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if (
                source is not None
                and source.id != target.id
                and source.version != command.source_version
            ):
                raise VersionConflict(
                    "combatant",
                    source.id,
                    command.source_version or 0,
                    source.version,
                )
            before = {
                "effect": serialize(effect),
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
            }
            now = datetime.now(UTC)
            effect.status = "ended"
            effect.ended_at = now
            effect.end_reason = command.reason
            effect.version += 1
            target.version += 1
            target.updated_at = now
            if source is not None:
                concentration_id = source.concentration.get("effect_id")
                if concentration_id == effect.id:
                    source.concentration = {}
                if source.id != target.id:
                    source.version += 1
                    source.updated_at = now
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_end_effect",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot=before,
                after_snapshot={
                    "effect_id": effect.id,
                    "status": effect.status,
                    "end_reason": effect.end_reason,
                },
                reason=command.reason,
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=source.id if source is not None else None,
                transaction_id=transaction.id,
                action_type="end_effect",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json={
                    "effect_id": effect.id,
                    "effect_name": effect.name,
                    "reason": command.reason,
                },
                explanation=command.reason,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{target.display_name} 的效果结束：{effect.name}",
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "effect": serialize(effect),
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
            }

    @staticmethod
    def _condition_names(values: list[object]) -> list[str]:
        names: list[str] = []
        for value in values:
            if isinstance(value, str):
                name = value.strip()
            elif isinstance(value, dict):
                raw_name = value.get("name", value.get("condition_name"))
                name = raw_name.strip() if isinstance(raw_name, str) else ""
            else:
                name = ""
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _settlement_plan(
        session: Session,
        campaign_id: str,
        combat_id: str,
        command: CombatSettlementCommand,
    ) -> tuple[
        Combat,
        dict[str, Character],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        combat = session.get(Combat, combat_id)
        if combat is None or combat.campaign_id != campaign_id:
            raise StateNotFoundError("combat not found in campaign")
        if combat.version != command.combat_version:
            raise VersionConflict(
                "combat",
                combat.id,
                command.combat_version,
                combat.version,
            )
        if combat.status != "ended":
            raise ValueError("combat must be ended before settlement")
        xp_by_character = {
            award.character_id: award.xp for award in command.xp_awards
        }
        writeback_by_character = {
            writeback.character_id: writeback for writeback in command.writebacks
        }
        currency_by_character = {
            award.character_id: award.copper
            for award in command.currency_awards
        }
        loot_by_character: dict[str, list[Any]] = {}
        for award in command.loot_awards:
            loot_by_character.setdefault(award.character_id, []).append(award)
        character_ids = (
            set(xp_by_character)
            | set(writeback_by_character)
            | set(currency_by_character)
            | set(loot_by_character)
        )
        characters: dict[str, Character] = {}
        changes: list[dict[str, Any]] = []
        currency_changes: list[dict[str, Any]] = []
        loot_changes: list[dict[str, Any]] = []
        for character_id in sorted(character_ids):
            character = session.get(Character, character_id)
            if character is None or character.campaign_id != campaign_id:
                raise StateNotFoundError("settlement character not found in campaign")
            characters[character_id] = character
            before = {
                "hp": character.hp,
                "experience": character.experience,
                "version": character.version,
            }
            after = dict(before)
            after["experience"] = character.experience + xp_by_character.get(
                character_id,
                0,
            )
            condition_names: list[str] = []
            writeback = writeback_by_character.get(character_id)
            if writeback is not None:
                combatant = session.get(Combatant, writeback.combatant_id)
                if (
                    combatant is None
                    or combatant.combat_id != combat_id
                    or combatant.entity_type != "character"
                    or combatant.entity_id != character_id
                ):
                    raise ValueError(
                        "writeback combatant must reference the selected character"
                    )
                if writeback.write_hp:
                    after["hp"] = min(character.max_hp, combatant.hp)
                if writeback.write_conditions:
                    condition_names = CombatEngineService._condition_names(
                        combatant.conditions
                    )
            after["version"] = character.version + 1
            changes.append(
                {
                    "character_id": character_id,
                    "name": character.name,
                    "before": before,
                    "after": after,
                    "conditions_to_add": condition_names,
                    "xp_award": xp_by_character.get(character_id, 0),
                }
            )
            copper = currency_by_character.get(character_id, 0)
            if copper:
                wallet = session.scalar(
                    select(Wallet).where(
                        Wallet.campaign_id == campaign_id,
                        Wallet.character_id == character_id,
                    )
                )
                currency_changes.append(
                    {
                        "character_id": character_id,
                        "name": character.name,
                        "wallet_id": wallet.id if wallet is not None else None,
                        "wallet_will_be_created": wallet is None,
                        "before_copper": wallet.copper if wallet is not None else 0,
                        "award_copper": copper,
                        "after_copper": (
                            wallet.copper if wallet is not None else 0
                        )
                        + copper,
                    }
                )
            for award in loot_by_character.get(character_id, []):
                loot_changes.append(
                    {
                        "character_id": character_id,
                        "character_name": character.name,
                        **award.model_dump(mode="json"),
                    }
                )
        return (
            combat,
            characters,
            changes,
            currency_changes,
            loot_changes,
        )

    def preview_settlement(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatSettlementCommand,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            existing = session.scalar(
                select(CombatSettlement).where(
                    CombatSettlement.combat_id == combat_id
                )
            )
            if existing is not None:
                raise ValueError("combat is already settled")
            (
                combat,
                _,
                changes,
                currency_changes,
                loot_changes,
            ) = self._settlement_plan(
                session,
                campaign_id,
                combat_id,
                command,
            )
            scene_changes = self._scene_entity_changes(session, combat, command)
            return {
                "combat": serialize(combat),
                "resolution_type": command.resolution_type,
                "character_changes": changes,
                "currency_changes": currency_changes,
                "loot_changes": loot_changes,
                "scene_entity_changes": scene_changes,
                "total_xp": sum(award.xp for award in command.xp_awards),
                "total_copper": sum(
                    award.copper for award in command.currency_awards
                ),
                "notes": command.notes,
            }

    @staticmethod
    def _scene_entity_changes(
        session: Session,
        combat: Combat,
        command: CombatSettlementCommand,
    ) -> list[dict[str, Any]]:
        if combat.scene_id is None:
            return []
        changes: list[dict[str, Any]] = []
        combatants = session.scalars(
            select(Combatant).where(
                Combatant.combat_id == combat.id,
                Combatant.entity_type.in_(("npc", "monster")),
                Combatant.entity_id.is_not(None),
            )
        ).all()
        for combatant in combatants:
            entity: NPC | MonsterInstance | None
            if combatant.entity_type == "npc":
                entity = session.get(NPC, combatant.entity_id)
            else:
                entity = session.get(MonsterInstance, combatant.entity_id)
            if entity is None or entity.campaign_id != combat.campaign_id:
                continue
            participant = session.scalar(
                select(SceneParticipant).where(
                    SceneParticipant.scene_id == combat.scene_id,
                    SceneParticipant.entity_type == combatant.entity_type,
                    SceneParticipant.entity_id == combatant.entity_id,
                )
            )
            after_role = (
                "defeated"
                if command.resolution_type == "victory"
                and combatant.entity_type == "monster"
                and combatant.hp <= 0
                else participant.role if participant is not None else None
            )
            if entity.hp == combatant.hp and (
                participant is None or participant.role == after_role
            ):
                continue
            changes.append(
                {
                    "entity_type": combatant.entity_type,
                    "entity_id": entity.id,
                    "name": entity.name,
                    "participant_id": participant.id if participant is not None else None,
                    "before": {
                        "hp": entity.hp,
                        "version": entity.version,
                        "role": participant.role if participant is not None else None,
                    },
                    "after": {
                        "hp": min(entity.max_hp, combatant.hp),
                        "version": entity.version + 1,
                        "role": after_role,
                    },
                }
            )
        return changes

    def confirm_settlement(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatSettlementCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(CombatSettlement).where(
                    CombatSettlement.campaign_id == campaign_id,
                    CombatSettlement.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                character_ids_raw = existing.result_json.get("character_ids", [])
                character_ids = (
                    character_ids_raw
                    if isinstance(character_ids_raw, list)
                    else []
                )
                existing_characters: list[Character] = []
                for character_id in character_ids:
                    if isinstance(character_id, str):
                        character = session.get(Character, character_id)
                        if character is not None:
                            existing_characters.append(character)
                wallet_ids_raw = existing.result_json.get("wallet_ids", [])
                wallet_ids = (
                    wallet_ids_raw if isinstance(wallet_ids_raw, list) else []
                )
                existing_wallets: list[Wallet] = []
                for wallet_id in wallet_ids:
                    if isinstance(wallet_id, str):
                        wallet = session.get(Wallet, wallet_id)
                        if wallet is not None:
                            existing_wallets.append(wallet)
                item_ids_raw = existing.result_json.get("loot_item_ids", [])
                item_ids = item_ids_raw if isinstance(item_ids_raw, list) else []
                existing_items: list[WorldItem] = []
                for item_id in item_ids:
                    if isinstance(item_id, str):
                        item = session.get(WorldItem, item_id)
                        if item is not None:
                            existing_items.append(item)
                combat = session.get(Combat, combat_id)
                return {
                    "settlement": serialize(existing),
                    "combat": serialize(combat) if combat is not None else None,
                    "characters": [serialize(row) for row in existing_characters],
                    "conditions": [],
                    "wallets": [serialize(row) for row in existing_wallets],
                    "loot_items": [serialize(row) for row in existing_items],
                }
            other_settlement = session.scalar(
                select(CombatSettlement).where(
                    CombatSettlement.combat_id == combat_id
                )
            )
            if other_settlement is not None:
                raise ValueError("combat is already settled")
            (
                combat,
                characters,
                changes,
                currency_changes,
                loot_changes,
            ) = self._settlement_plan(
                session,
                campaign_id,
                combat_id,
                command,
            )
            combat_before = serialize(combat)
            scene_changes = self._scene_entity_changes(session, combat, command)
            now = datetime.now(UTC)
            created_conditions: list[CharacterCondition] = []
            updated_wallets: list[Wallet] = []
            created_items: list[WorldItem] = []
            for change in changes:
                character = characters[str(change["character_id"])]
                after = change["after"]
                character.hp = int(after["hp"])
                character.experience = int(after["experience"])
                character.version += 1
                character.updated_at = now
                for condition_name in change["conditions_to_add"]:
                    duplicate = session.scalar(
                        select(CharacterCondition).where(
                            CharacterCondition.character_id == character.id,
                            CharacterCondition.condition_name == condition_name,
                        )
                    )
                    if duplicate is None:
                        condition = CharacterCondition(
                            character_id=character.id,
                            condition_name=condition_name,
                            source=f"战斗结算：{combat.name}",
                            duration="持续，直至规则或DM移除",
                            notes=command.notes,
                            details={
                                "combat_id": combat.id,
                                "settlement_resolution": command.resolution_type,
                            },
                        )
                        session.add(condition)
                        created_conditions.append(condition)
            for currency_change in currency_changes:
                character_id = str(currency_change["character_id"])
                wallet = session.scalar(
                    select(Wallet).where(
                        Wallet.campaign_id == campaign_id,
                        Wallet.character_id == character_id,
                    )
                )
                if wallet is None:
                    wallet = Wallet(
                        campaign_id=campaign_id,
                        character_id=character_id,
                        name="角色钱包",
                        copper=0,
                    )
                    session.add(wallet)
                    session.flush()
                award_copper = int(currency_change["award_copper"])
                wallet.copper += award_copper
                wallet.version += 1
                wallet.updated_at = now
                updated_wallets.append(wallet)
                session.add(
                    CurrencyTransaction(
                        campaign_id=campaign_id,
                        wallet_id=wallet.id,
                        amount_copper=award_copper,
                        kind="adjustment",
                        idempotency_key=(
                            f"combat-settlement:{combat.id}:{character_id}"
                        ),
                        metadata_json={
                            "source": "combat_settlement",
                            "combat_id": combat.id,
                            "resolution_type": command.resolution_type,
                        },
                    )
                )
            for loot_change in loot_changes:
                item = WorldItem(
                    campaign_id=campaign_id,
                    owner_character_id=str(loot_change["character_id"]),
                    name=str(loot_change["name"]),
                    description=loot_change["description"],
                    category=str(loot_change["category"]),
                    quantity=int(loot_change["quantity"]),
                    unit_weight_lb=float(loot_change["unit_weight_lb"]),
                    price_cp=int(loot_change["price_cp"]),
                    source_record_id=loot_change["source_record_id"],
                    source_label=str(loot_change["source_label"]),
                    metadata_json={
                        **dict(loot_change["metadata_json"]),
                        "source": "combat_settlement",
                        "combat_id": combat.id,
                        "resolution_type": command.resolution_type,
                    },
                )
                session.add(item)
                created_items.append(item)
            session.flush()
            combat.xp_awarded = bool(command.xp_awards)
            combat.base_xp = sum(award.xp for award in command.xp_awards)
            combat.version += 1
            combat.updated_at = now
            for scene_change in scene_changes:
                if scene_change["entity_type"] == "npc":
                    scene_entity: NPC | MonsterInstance | None = session.get(
                        NPC, scene_change["entity_id"]
                    )
                else:
                    scene_entity = session.get(
                        MonsterInstance, scene_change["entity_id"]
                    )
                if scene_entity is None:
                    continue
                scene_entity.hp = int(scene_change["after"]["hp"])
                scene_entity.version += 1
                scene_entity.updated_at = now
                participant_id = scene_change["participant_id"]
                participant = (
                    session.get(SceneParticipant, participant_id)
                    if participant_id is not None
                    else None
                )
                after_role = scene_change["after"]["role"]
                if participant is not None and after_role != participant.role:
                    participant.role = str(after_role)
                    participant.version += 1
                    participant.updated_at = now
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_settlement",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={
                    "combat": combat_before,
                    "character_changes": changes,
                    "currency_changes": currency_changes,
                    "loot_changes": loot_changes,
                    "scene_entity_changes": scene_changes,
                },
                after_snapshot={
                    "combat_id": combat.id,
                    "resolution_type": command.resolution_type,
                    "character_ids": list(characters),
                    "wallet_ids": [wallet.id for wallet in updated_wallets],
                    "loot_item_ids": [item.id for item in created_items],
                    "scene_entity_changes": scene_changes,
                },
                reason=command.notes or f"combat settlement: {command.resolution_type}",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            settlement = CombatSettlement(
                campaign_id=campaign_id,
                combat_id=combat_id,
                transaction_id=transaction.id,
                status="confirmed",
                resolution_type=command.resolution_type,
                xp_allocations=[
                    award.model_dump(mode="json") for award in command.xp_awards
                ],
                writebacks=[
                    writeback.model_dump(mode="json")
                    for writeback in command.writebacks
                ],
                result_json={
                    "character_ids": list(characters),
                    "condition_ids": [condition.id for condition in created_conditions],
                    "total_xp": sum(award.xp for award in command.xp_awards),
                    "total_copper": sum(
                        award.copper for award in command.currency_awards
                    ),
                    "currency_changes": currency_changes,
                    "wallet_ids": [wallet.id for wallet in updated_wallets],
                    "loot_changes": loot_changes,
                    "loot_item_ids": [item.id for item in created_items],
                    "scene_entity_changes": scene_changes,
                },
                idempotency_key=idempotency_key,
                notes=command.notes,
                confirmed_at=now,
            )
            session.add(settlement)
            session.flush()
            return {
                "settlement": serialize(settlement),
                "combat": serialize(combat),
                "characters": [
                    serialize(characters[character_id])
                    for character_id in sorted(characters)
                ],
                "conditions": [
                    serialize(condition) for condition in created_conditions
                ],
                "wallets": [serialize(wallet) for wallet in updated_wallets],
                "loot_items": [serialize(item) for item in created_items],
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
