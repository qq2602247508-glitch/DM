from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import CombatManeuverCommand
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.monster_ai import MonsterActionPhase, choose_monster_action
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import (
    Campaign,
    Combat,
    CombatAction,
    Combatant,
    OperationTransaction,
)


class MonsterAIService:
    """Build a deterministic monster turn proposal from the live combat snapshot."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.combat_engine = CombatEngineService(engine)

    @staticmethod
    def _supports_basic_ai(actor: Combatant) -> bool:
        """Keep AI opt-in for enemy summons instead of treating every companion as a monster."""

        if actor.entity_type == "monster":
            return True
        state = dict(actor.snapshot_json or {})
        return (
            actor.entity_type == "companion"
            and state.get("controller") == "dm"
            and state.get("disposition") == "enemy"
            and state.get("enemy_ai_mode") == "basic"
        )

    @staticmethod
    def _state_int(value: object, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    def preview(
        self,
        campaign_id: str,
        combat_id: str,
        actor_combatant_id: str,
        *,
        actor_version: int | None = None,
        phase: str = "turn",
        tactics: str = "standard",
        recharge_available: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            actor = session.get(Combatant, actor_combatant_id)
            if actor is None or actor.combat_id != combat_id:
                raise StateNotFoundError("monster combatant not found in combat")
            if not self._supports_basic_ai(actor):
                raise ValueError(
                    "monster AI preview requires a monster or a DM-controlled "
                    "enemy summon with basic AI"
                )
            if not actor.is_active:
                raise ValueError("inactive monsters cannot receive a turn plan")
            if actor_version is not None and actor.version != actor_version:
                raise VersionConflict("combatant", actor.id, actor_version, actor.version)
            rows = list(
                session.scalars(
                    select(Combatant)
                    .where(Combatant.combat_id == combat_id, Combatant.is_active.is_(True))
                    .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
                ).all()
            )

            def snapshot(row: Combatant) -> dict[str, Any]:
                state = dict(row.snapshot_json or {})
                actions = state.get("actions")
                return {
                    "id": row.id,
                    "entity_type": row.entity_type,
                    "display_name": row.display_name,
                    "hp": row.hp,
                    "max_hp": row.max_hp,
                    "armor_class": row.armor_class,
                    "is_active": row.is_active,
                    "action_available": row.action_available,
                    "bonus_action_available": row.bonus_action_available,
                    "reaction_available": row.reaction_available,
                    "actions": list(actions) if isinstance(actions, list) else [],
                    "grid_position": state.get("grid_position"),
                    "disposition": state.get("disposition", "enemy"),
                    "ai_tactics": state.get("ai_tactics"),
                }

            actor_state = snapshot(actor)
            live_recharge = recharge_available
            if live_recharge is None:
                raw_recharge = actor.snapshot_json.get("recharge_available")
                live_recharge = (
                    {
                        str(key): value
                        for key, value in raw_recharge.items()
                        if isinstance(key, str) and isinstance(value, bool)
                    }
                    if isinstance(raw_recharge, dict)
                    else None
                )
            legendary_remaining = self._state_int(
                actor.snapshot_json.get("legendary_actions_remaining")
            )
            if phase == "legendary" and legendary_remaining == 0:
                actor_actions = actor_state.get("actions")
                normalized_actor_actions = actor_actions if isinstance(actor_actions, list) else []
                pools = {
                    int(item["legendary_pool_max"])
                    for item in normalized_actor_actions
                    if isinstance(item, dict) and isinstance(item.get("legendary_pool_max"), int)
                }
                if len(pools) == 1:
                    legendary_remaining = pools.pop()
            plan = choose_monster_action(
                actor_state,
                [snapshot(row) for row in rows],
                phase=cast(MonsterActionPhase, phase),
                tactics=tactics,
                legendary_actions_remaining=legendary_remaining,
                lair_action_available=(
                    self._state_int(actor.snapshot_json.get("lair_action_round"))
                    != combat.round_number
                ),
                recharge_available=live_recharge,
            )
            return {
                "combat": serialize(combat),
                "actor": serialize(actor),
                "actor_policy": (
                    "enemy_summon_basic" if actor.entity_type == "companion" else "monster"
                ),
                "plan": plan.as_dict() if plan is not None else None,
                "requires_confirmation": (
                    plan.requires_dm_confirmation if plan is not None else True
                ),
            }

    def confirm_retreat(
        self,
        campaign_id: str,
        combat_id: str,
        actor_combatant_id: str,
        *,
        actor_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Execute a retreat plan's Disengage without guessing a movement path."""

        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session:
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None and (
                existing.action_type != "disengage"
                or existing.actor_combatant_id != actor_combatant_id
            ):
                raise ValueError("idempotency key is already used by another combat action")

        if existing is None:
            preview = self.preview(
                campaign_id,
                combat_id,
                actor_combatant_id,
                actor_version=actor_version,
                phase="turn",
                tactics="tactical",
            )
            plan = preview.get("plan")
            if not isinstance(plan, dict) or plan.get("action_type") != "disengage":
                raise ValueError("monster AI has no active retreat plan to execute")

        result = self.combat_engine.confirm_maneuver(
            campaign_id,
            combat_id,
            CombatManeuverCommand(
                action_type="disengage",
                actor_combatant_id=actor_combatant_id,
                actor_version=actor_version,
                adjudication_note=(
                    "怪物 AI 按已确认撤退战术执行撤离；移动路径仍由权威网格另行结算"
                ),
            ),
            idempotency_key=idempotency_key,
        )
        action = result.get("action")
        if not isinstance(action, dict) or (
            action.get("action_type") != "disengage"
            or action.get("actor_combatant_id") != actor_combatant_id
        ):
            raise ValueError("retreat execution did not produce the expected combat action")
        return result

    def configure_tactics(
        self,
        campaign_id: str,
        combat_id: str,
        actor_combatant_id: str,
        *,
        actor_version: int,
        strategy: str,
        focus_target_id: str | None,
        leader_id: str | None,
        retreat_threshold_pct: int | None,
        reason: str,
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
            actor = session.get(Combatant, actor_combatant_id)
            if actor is None or actor.combat_id != combat_id or not self._supports_basic_ai(actor):
                raise StateNotFoundError("monster or basic enemy summon not found in combat")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return {
                    "actor": serialize(actor),
                    "action": serialize(existing),
                    "already_applied": True,
                }
            if actor.version != actor_version:
                raise VersionConflict("combatant", actor.id, actor_version, actor.version)
            target_ids = [value for value in (focus_target_id, leader_id) if value]
            targets: list[Combatant] = []
            for target_id in target_ids:
                target = session.get(Combatant, target_id)
                if target is None or target.combat_id != combat_id or not target.is_active:
                    raise StateNotFoundError("AI tactics target not found in active combat")
                targets.append(target)
            if strategy == "focus_fire" and focus_target_id is None:
                raise ValueError("focus_fire requires focus_target_id")
            if strategy == "protect_leader" and leader_id is None:
                raise ValueError("protect_leader requires leader_id")
            before = serialize(actor)
            snapshot = dict(actor.snapshot_json or {})
            snapshot["ai_tactics"] = {
                "strategy": strategy,
                "focus_target_id": focus_target_id,
                "leader_id": leader_id,
                "retreat_threshold_pct": retreat_threshold_pct,
                "reason": reason,
            }
            actor.snapshot_json = snapshot
            conditions = list(actor.conditions or [])
            if strategy == "retreat":
                if "撤退中" not in conditions:
                    conditions.append("撤退中")
            else:
                conditions = [value for value in conditions if value != "撤退中"]
            actor.conditions = conditions
            actor.version += 1
            actor.updated_at = datetime.now(UTC)
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_monster_ai_tactics",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"actor": before},
                after_snapshot={"actor": serialize(actor)},
                reason=reason,
                source="combat",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=actor.id,
                transaction_id=transaction.id,
                action_type="monster_ai_tactics",
                target_combatant_ids=[target.id for target in targets],
                request_json={
                    "strategy": strategy,
                    "focus_target_id": focus_target_id,
                    "leader_id": leader_id,
                    "retreat_threshold_pct": retreat_threshold_pct,
                    "reason": reason,
                },
                result_json={
                    "ai_tactics": snapshot["ai_tactics"],
                    "retreating": strategy == "retreat",
                },
                explanation=reason,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{actor.display_name} 的敌方 AI 战术切换为 {strategy}",
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "actor": serialize(actor),
                "action": serialize(action),
                "already_applied": False,
            }
