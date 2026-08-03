"""Deterministic planning primitives for advanced monster actions.

The planner selects from already-structured rules.  It never invents ranges,
attack bonuses, dice, reaction triggers, or effect durations.  Plans that need
facts which are not present in the stat block remain explicitly DM-gated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

MonsterActionPhase = Literal["turn", "reaction", "legendary", "lair"]
MonsterReactionEvent = Literal[
    "leaves_reach", "enters_reach", "takes_damage", "casts_spell", "turn_end"
]


@dataclass(frozen=True)
class MonsterActionStep:
    action_name: str
    action_index: int
    action_type: str
    target_ids: tuple[str, ...]
    requires_player_roll: bool
    auto_eligible: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_name": self.action_name,
            "action_index": self.action_index,
            "action_type": self.action_type,
            "target_ids": list(self.target_ids),
            "requires_player_roll": self.requires_player_roll,
            "auto_eligible": self.auto_eligible,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MonsterActionPlan:
    actor_id: str
    action_name: str
    action_type: str
    target_ids: tuple[str, ...]
    reason: str
    steps: tuple[MonsterActionStep, ...] = ()
    legendary_cost: int = 0
    requires_player_roll: bool = False
    requires_dm_confirmation: bool = True
    confirmation_reasons: tuple[str, ...] = ()
    tactical_intent: str = "attack"
    movement_mode: str = "approach"
    focus_target_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "action_name": self.action_name,
            "action_type": self.action_type,
            "target_ids": list(self.target_ids),
            "reason": self.reason,
            "steps": [step.as_dict() for step in self.steps],
            "legendary_cost": self.legendary_cost,
            "requires_player_roll": self.requires_player_roll,
            "requires_dm_confirmation": self.requires_dm_confirmation,
            "confirmation_reasons": list(self.confirmation_reasons),
            "tactical_intent": self.tactical_intent,
            "movement_mode": self.movement_mode,
            "focus_target_id": self.focus_target_id,
        }


def _action_type(raw: dict[str, Any]) -> str:
    return str(raw.get("action_type") or "action").strip().lower()


def _phase_allows(action_type: str, phase: MonsterActionPhase) -> bool:
    if phase == "reaction":
        return action_type == "reaction"
    if phase == "legendary":
        return action_type == "legendary_action"
    if phase == "lair":
        return action_type == "lair_action"
    return action_type in {"action", "bonus_action", "spellcasting"}


def _positive_int(value: object, default: int = 0) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def available_monster_actions(
    actions: list[dict[str, Any]],
    *,
    phase: MonsterActionPhase = "turn",
    action_available: bool = True,
    bonus_action_available: bool = True,
    reaction_available: bool = True,
    legendary_actions_remaining: int = 0,
    lair_action_available: bool = False,
    recharge_available: dict[str, bool] | None = None,
    reaction_event: MonsterReactionEvent | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return actions legal in the requested action window.

    A missing recharge map is the initial encounter state and therefore leaves
    parsed recharge actions available.  Once the map exists, only an explicit
    ``True`` re-enables the action; this mirrors the combat service gate.
    """

    result: list[dict[str, Any]] = []
    for raw in actions:
        if not isinstance(raw, dict):
            continue
        action_type = _action_type(raw)
        if not _phase_allows(action_type, phase):
            continue
        if action_type in {"action", "spellcasting"} and not action_available:
            continue
        if action_type == "bonus_action" and not bonus_action_available:
            continue
        if action_type == "reaction" and not reaction_available:
            continue
        if action_type == "reaction" and reaction_event is not None:
            if raw.get("reaction_event") != reaction_event:
                continue
        if action_type == "legendary_action":
            cost = _positive_int(raw.get("legendary_cost"), 1)
            if legendary_actions_remaining < cost:
                continue
        if action_type == "lair_action" and not lair_action_available:
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        if (
            raw.get("recharge")
            and recharge_available is not None
            and recharge_available.get(name) is not True
        ):
            continue
        result.append(raw)
    return tuple(result)


def _distance(actor: dict[str, Any], target: dict[str, Any]) -> int | None:
    actor_pos = actor.get("grid_position")
    target_pos = target.get("grid_position")
    if not isinstance(actor_pos, dict) or not isinstance(target_pos, dict):
        return None
    try:
        return max(
            abs(int(actor_pos["row"]) - int(target_pos["row"])),
            abs(int(actor_pos["col"]) - int(target_pos["col"])),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _is_enemy(actor: dict[str, Any], target: dict[str, Any]) -> bool:
    actor_disposition = str(actor.get("disposition") or "enemy")
    target_disposition = str(target.get("disposition") or "ally")
    if actor_disposition == "neutral" or target_disposition == "neutral":
        return False
    return actor_disposition != target_disposition


def _dice_average(expression: object) -> float:
    match = re.fullmatch(r"\s*(\d+)d(\d+)(?:\s*([+-])\s*(\d+))?\s*", str(expression or ""))
    if not match:
        return 0.0
    count, sides = int(match.group(1)), int(match.group(2))
    modifier = int(match.group(4) or 0) * (-1 if match.group(3) == "-" else 1)
    return count * (sides + 1) / 2 + modifier


def _target_priority(target: dict[str, Any], *, tactical: bool) -> tuple[object, ...]:
    hp = _positive_int(target.get("hp"), 10**9)
    armor_class = _positive_int(target.get("armor_class"), 10**9)
    return (
        hp if tactical else 0,
        armor_class if tactical else 0,
        str(target.get("id") or ""),
    )


def _select_targets(
    actor: dict[str, Any],
    enemies: list[dict[str, Any]],
    action: dict[str, Any],
    *,
    tactics: str,
    all_targets: list[dict[str, Any]],
    tactical_config: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    area = bool(action.get("area_shape")) or bool(action.get("affects_multiple_targets"))
    focus_target_id = str(tactical_config.get("focus_target_id") or "").strip()
    focused = next(
        (target for target in enemies if str(target.get("id") or "") == focus_target_id),
        None,
    )
    if focused is not None and not area:
        return (focused,)
    leader_id = str(tactical_config.get("leader_id") or "").strip()
    leader = next(
        (target for target in all_targets if str(target.get("id") or "") == leader_id),
        None,
    )
    protect_leader = tactical_config.get("strategy") == "protect_leader" and leader is not None

    def leader_distance(target: dict[str, Any]) -> int:
        if not protect_leader or leader is None:
            return 0
        distance = _distance(leader, target)
        return distance if distance is not None else 10**9

    ordered = sorted(
        enemies,
        key=lambda target: (
            leader_distance(target),
            _distance(actor, target) is None,
            _distance(actor, target) if _distance(actor, target) is not None else 10**9,
            *_target_priority(target, tactical=tactics in {"smart", "tactical"}),
        ),
    )
    # Without authoritative geometry the planner may identify candidate area
    # targets, but the executor/UI must still confirm actual coverage.
    return tuple(ordered if area else ordered[:1])


def _multiattack_steps(
    action: dict[str, Any],
    all_actions: list[dict[str, Any]],
    targets: tuple[dict[str, Any], ...],
) -> tuple[MonsterActionStep, ...]:
    components = action.get("multiattack_components")
    if not isinstance(components, list) or not components:
        return ()
    by_name = {
        str(candidate.get("name") or "").strip(): (index, candidate)
        for index, candidate in enumerate(all_actions)
        if isinstance(candidate, dict) and str(candidate.get("name") or "").strip()
    }
    result: list[MonsterActionStep] = []
    target_ids = tuple(str(target["id"]) for target in targets)
    for component in components:
        if not isinstance(component, dict):
            return ()
        name = str(component.get("action_name") or "").strip()
        count = _positive_int(component.get("count"))
        resolved = by_name.get(name)
        if not name or not count or resolved is None:
            return ()
        index, child = resolved
        for repetition in range(count):
            selected_target = target_ids[repetition % len(target_ids)] if target_ids else ""
            result.append(
                MonsterActionStep(
                    action_name=name,
                    action_index=index,
                    action_type=_action_type(child),
                    target_ids=(selected_target,) if selected_target else (),
                    requires_player_roll=bool(child.get("save_dc") and child.get("save_ability")),
                    auto_eligible=child.get("auto_eligible") is not False,
                    reason=f"多重攻击的第 {repetition + 1} 次{name}",
                )
            )
    expected = _positive_int(action.get("multiattack_count"))
    return tuple(result) if expected and len(result) == expected else ()


def _action_score(action: dict[str, Any], actions: list[dict[str, Any]]) -> float:
    if action.get("multiattack"):
        components = action.get("multiattack_components")
        if isinstance(components, list):
            by_name = {
                str(candidate.get("name") or ""): candidate
                for candidate in actions
                if isinstance(candidate, dict)
            }
            return sum(
                _dice_average(by_name.get(str(item.get("action_name") or ""), {}).get("damage"))
                * _positive_int(item.get("count"))
                for item in components
                if isinstance(item, dict)
            )
    score = _dice_average(action.get("damage"))
    if action.get("save_dc"):
        score += 2.0
    if action.get("conditions_on_failure"):
        score += 3.0
    if action.get("area_shape"):
        score += 2.0
    return score


def _tactical_config(actor: dict[str, Any]) -> dict[str, Any]:
    raw = actor.get("ai_tactics")
    return dict(raw) if isinstance(raw, dict) else {}


def choose_monster_action(
    actor: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    phase: MonsterActionPhase = "turn",
    tactics: str = "standard",
    legendary_actions_remaining: int = 0,
    lair_action_available: bool = False,
    recharge_available: dict[str, bool] | None = None,
    reaction_event: MonsterReactionEvent | None = None,
) -> MonsterActionPlan | None:
    """Choose a stable plan while preserving every unresolved rule boundary."""

    actor_id = str(actor.get("id") or "").strip()
    if not actor_id or not bool(actor.get("is_active", True)):
        return None
    actions = [item for item in list(actor.get("actions") or []) if isinstance(item, dict)]
    candidates = available_monster_actions(
        actions,
        phase=phase,
        action_available=bool(actor.get("action_available", True)),
        bonus_action_available=bool(actor.get("bonus_action_available", True)),
        reaction_available=bool(actor.get("reaction_available", True)),
        legendary_actions_remaining=legendary_actions_remaining,
        lair_action_available=lair_action_available,
        recharge_available=recharge_available,
        reaction_event=reaction_event,
    )
    enemies = [
        target
        for target in targets
        if str(target.get("id") or "") != actor_id
        and bool(target.get("is_active", True))
        and int(target.get("hp", 1) or 0) > 0
        and _is_enemy(actor, target)
    ]
    if not enemies:
        return None
    tactical_config = _tactical_config(actor)
    retreat_threshold_pct = _positive_int(tactical_config.get("retreat_threshold_pct"))
    max_hp = _positive_int(actor.get("max_hp"))
    hp = max(0, int(actor.get("hp", 0) or 0))
    if (
        bool(actor.get("action_available", True))
        and (
            tactical_config.get("strategy") == "retreat"
            or (
                retreat_threshold_pct
                and max_hp
                and hp * 100 <= max_hp * retreat_threshold_pct
            )
        )
    ):
        return MonsterActionPlan(
            actor_id=actor_id,
            action_name="撤离",
            action_type="disengage",
            target_ids=(),
            reason="结构化战术要求低血撤退；先撤离再沿权威网格远离威胁",
            requires_dm_confirmation=True,
            confirmation_reasons=("撤退路径与出口需要地图确认",),
            tactical_intent="retreat",
            movement_mode="retreat",
        )
    if not candidates:
        return None
    prefer_control = tactical_config.get("strategy") in {"control", "protect_leader"}
    selected = max(
        enumerate(candidates),
        key=lambda pair: (
            bool(
                prefer_control
                and (
                    pair[1].get("conditions_on_failure")
                    or pair[1].get("conditions_on_hit")
                )
            ),
            _action_score(pair[1], actions),
            -pair[0],
        ),
    )[1]
    selected_targets = _select_targets(
        actor,
        enemies,
        selected,
        tactics=tactics,
        all_targets=targets,
        tactical_config=tactical_config,
    )
    target_ids = tuple(str(target["id"]) for target in selected_targets)
    steps = _multiattack_steps(selected, actions, selected_targets)
    if not steps:
        selected_index = actions.index(selected)
        steps = (
            MonsterActionStep(
                action_name=str(selected["name"]),
                action_index=selected_index,
                action_type=_action_type(selected),
                target_ids=target_ids,
                requires_player_roll=bool(selected.get("save_dc") and selected.get("save_ability")),
                auto_eligible=selected.get("auto_eligible") is not False,
                reason="按动作伤害、控制价值与当前战术选择",
            ),
        )

    confirmation_reasons: list[str] = []
    if selected.get("auto_eligible") is False:
        confirmation_reasons.append("动作资料标记为不可自动执行")
    if selected.get("multiattack") and not selected.get("multiattack_components"):
        confirmation_reasons.append("多重攻击的子动作组合未可靠解析")
    if selected.get("area_shape"):
        confirmation_reasons.append("区域覆盖需要地图几何确认")
    if _action_type(selected) == "reaction":
        confirmation_reasons.append("反应触发条件需要 DM 明示")
    if selected.get("range_ft") is None and not selected.get("area_origin_self"):
        confirmation_reasons.append("动作距离未明确")
    if selected.get("conditions_on_failure") and not selected.get("condition_duration"):
        confirmation_reasons.append("状态持续时间未可靠解析")
    if any(not step.auto_eligible for step in steps):
        confirmation_reasons.append("序列包含需要 DM 裁定的子动作")

    requires_player_roll = any(step.requires_player_roll for step in steps)
    return MonsterActionPlan(
        actor_id=actor_id,
        action_name=str(selected["name"]),
        action_type=_action_type(selected),
        target_ids=target_ids,
        reason=(
            f"{phase}窗口按结构化动作价值选择；目标按已知距离"
            f"与{tactics}战术排序"
        ),
        steps=steps,
        legendary_cost=(
            _positive_int(selected.get("legendary_cost"), 1)
            if _action_type(selected) == "legendary_action"
            else 0
        ),
        requires_player_roll=requires_player_roll,
        requires_dm_confirmation=bool(confirmation_reasons),
        confirmation_reasons=tuple(dict.fromkeys(confirmation_reasons)),
        tactical_intent=str(tactical_config.get("strategy") or "attack"),
        movement_mode="hold" if selected.get("range_ft", 0) else "approach",
        focus_target_id=target_ids[0] if target_ids else None,
    )
