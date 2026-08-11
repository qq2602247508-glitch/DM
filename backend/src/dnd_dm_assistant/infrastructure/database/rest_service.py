from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.character_catalog import CharacterCatalog
from dnd_dm_assistant.domain.advancement_choices import canonical_class_name
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.feature_runtime import (
    compile_feature_runtime_registry,
    feature_block_payloads,
    resource_recovery_events,
)
from dnd_dm_assistant.domain.growth_asset_catalog import weapon_asset, weapon_is_eligible
from dnd_dm_assistant.domain.rests import (
    HitDieSpend,
    ResourceRecovery,
    RestResource,
    resolve_long_rest,
    resolve_short_rest,
)
from dnd_dm_assistant.domain.zero_hp_intervention import (
    adapt_legacy_zero_hp_intervention,
    reset_zero_hp_intervention_states,
)
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    Campaign,
    Character,
    CharacterCondition,
    Combat,
    Combatant,
    EquipmentInstance,
    OperationTransaction,
    ResourcePool,
    RestRecord,
    RestRecoveryEntry,
)

RULE_REFERENCE = "PHB 2024 / 术语汇编 / 休息"
HIT_DIE_BY_CLASS = {
    "barbarian": 12,
    "野蛮人": 12,
    "fighter": 10,
    "战士": 10,
    "paladin": 10,
    "圣武士": 10,
    "ranger": 10,
    "游侠": 10,
    "bard": 8,
    "吟游诗人": 8,
    "cleric": 8,
    "牧师": 8,
    "druid": 8,
    "德鲁伊": 8,
    "monk": 8,
    "武僧": 8,
    "rogue": 8,
    "游荡者": 8,
    "warlock": 8,
    "邪术师": 8,
    "sorcerer": 6,
    "术士": 6,
    "wizard": 6,
    "法师": 6,
}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _ability_modifier(score: int) -> int:
    return (score - 10) // 2


def _hit_die_size(class_name: str | None) -> int:
    normalized = (class_name or "").strip().lower()
    for key, size in HIT_DIE_BY_CLASS.items():
        if key in normalized:
            return size
    return 8


def _resource_recovery(value: str) -> ResourceRecovery:
    if value in {"short_rest", "both"}:
        return "short_rest"
    if value == "long_rest":
        return "long_rest"
    if value in {"dawn", "special", "manual"}:
        return "special" if value != "dawn" else "dawn"
    return None


class RestService:
    def __init__(self, engine: Engine, catalog: CharacterCatalog | None = None) -> None:
        self.engine = engine
        self.catalog = catalog or CharacterCatalog(
            Path("data/generated-content/dnd5e_chm/json")
        )

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _character(session: Session, campaign_id: str, character_id: str) -> Character:
        character = session.get(Character, character_id)
        if character is None or character.campaign_id != campaign_id:
            raise StateNotFoundError("character not found in campaign")
        return character

    @staticmethod
    def _reset_combat_feature_states(
        session: Session,
        *,
        character_id: str,
        rest_event: str,
    ) -> list[str]:
        """Reset rest-scoped feature state in active combat snapshots."""

        combatants = session.scalars(
            select(Combatant)
            .join(Combat, Combat.id == Combatant.combat_id)
            .where(
                Combat.status == "active",
                Combatant.entity_type == "character",
                Combatant.entity_id == character_id,
            )
        ).all()
        reset_ids: list[str] = []
        for combatant in combatants:
            snapshot = dict(combatant.snapshot_json or {})
            runtime = snapshot.get("feature_runtime")
            defenses: list[dict[str, object]] = []
            if isinstance(runtime, dict):
                defenses = [
                    dict(item)
                    for item in feature_block_payloads(runtime, "defense")
                    if isinstance(item, dict)
                ]
                if not defenses:
                    combat_start = runtime.get("combat_start")
                    raw_defenses = (
                        combat_start.get("defenses")
                        if isinstance(combat_start, dict)
                        else None
                    )
                    defenses = [
                        dict(item)
                        for item in (raw_defenses or [])
                        if isinstance(item, dict)
                    ]
            updated, reset_state_keys = reset_zero_hp_intervention_states(
                snapshot,
                [adapt_legacy_zero_hp_intervention(item) for item in defenses],
                rest_event=rest_event,
            )
            timed_modifiers = updated.get("timed_feature_modifiers")
            if isinstance(timed_modifiers, list):
                remaining_modifiers = [
                    item
                    for item in timed_modifiers
                    if not isinstance(item, dict)
                    or str(item.get("expires_on") or "")
                    not in (
                        {"long_rest", "short_rest"}
                        if rest_event == "long_rest"
                        else {"short_rest"}
                    )
                ]
                if len(remaining_modifiers) != len(timed_modifiers):
                    updated["timed_feature_modifiers"] = remaining_modifiers
                    reset_state_keys.append("timed_feature_modifiers")
            if not reset_state_keys:
                # Adapter for snapshots created before contracts were frozen.
                legacy_state = snapshot.get("relentless_rage_state")
                if not isinstance(legacy_state, dict) or "current_dc" not in legacy_state:
                    continue
                legacy_state = dict(legacy_state)
                legacy_state.update(
                    {"current_dc": 10, "reset_reason": "short_or_long_rest"}
                )
                updated["relentless_rage_state"] = legacy_state
            combatant.snapshot_json = updated
            combatant.version += 1
            combatant.updated_at = datetime.now(UTC)
            reset_ids.append(combatant.id)
        return reset_ids

    @staticmethod
    def _fatigue_condition(
        session: Session, character_id: str
    ) -> CharacterCondition | None:
        rows = session.scalars(
            select(CharacterCondition).where(
                CharacterCondition.character_id == character_id
            )
        ).all()
        return next(
            (
                row
                for row in rows
                if row.condition_name.strip().lower()
                in {"exhaustion", "疲劳", "力竭"}
            ),
            None,
        )

    @staticmethod
    def _fatigue_level(condition: CharacterCondition | None) -> int:
        if condition is None:
            return 0
        raw = (condition.details or {}).get("level", 1)
        try:
            return max(0, min(6, int(cast(Any, raw))))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _short_rest_fatigue_reduction(character: Character) -> int:
        """Read an explicit feature contract before reducing exhaustion."""

        grants = [item for item in (character.features or []) if isinstance(item, dict)]
        if not grants:
            return 0
        scaling_values = {
            str(item.get("scaling_key")): item.get("value")
            for item in grants
            if item.get("kind") == "class_scaling"
            and isinstance(item.get("scaling_key"), str)
        }
        registry = compile_feature_runtime_registry(
            grants,
            resources=(character.resources or {})
            if isinstance(character.resources, dict)
            else {},
            scalings={key: {"value": value} for key, value in scaling_values.items()},
            class_levels=(character.class_levels or {})
            if isinstance(character.class_levels, dict)
            else {},
            total_level=character.level,
        )
        reduction = 0

        def read_effects(raw: object) -> tuple[object, ...]:
            if not isinstance(raw, dict):
                return ()
            typed_kind = str(raw.get("kind") or "")
            if typed_kind == "rest_condition_effect":
                return (raw,)
            legacy = raw.get("rest_effects")
            return tuple(legacy) if isinstance(legacy, list) else ()

        trigger_entries = registry.get("triggers")
        if isinstance(trigger_entries, list):
            entries: list[object] = list(trigger_entries)
        else:
            entries = []
        action_entries = registry.get("actions")
        if isinstance(action_entries, dict):
            entries.extend(action_entries.values())
        for entry in entries:
            for effect in read_effects(entry):
                if not isinstance(effect, dict):
                    continue
                if effect.get("rest") != "short_rest":
                    continue
                if effect.get("kind") == "reduce_exhaustion":
                    amount = effect.get("amount")
                elif (
                    effect.get("kind") == "rest_condition_effect"
                    and effect.get("condition") == "exhaustion"
                    and effect.get("effect_kind") == "reduce_condition_level"
                ):
                    amount = effect.get("amount")
                else:
                    continue
                try:
                    reduction = max(reduction, int(amount or 0))
                except (TypeError, ValueError):
                    continue
        return reduction

    def _sync_pools(self, session: Session, character: Character) -> list[ResourcePool]:
        pools = list(
            session.scalars(
                select(ResourcePool)
                .where(ResourcePool.character_id == character.id)
                .order_by(ResourcePool.created_at, ResourcePool.id)
            ).all()
        )
        by_key = {pool.key: pool for pool in pools}
        raw_resources = dict(character.resources or {})
        for key, raw in raw_resources.items():
            if not isinstance(raw, dict):
                continue
            current = max(0, int(raw.get("current", 0) or 0))
            maximum = max(current, int(raw.get("max", current) or current))
            recovery = str(raw.get("recovery", "manual") or "manual")
            raw_events = raw.get("recovery_events")
            recovery_events = (
                [dict(item) for item in raw_events if isinstance(item, dict)]
                if isinstance(raw_events, list)
                else resource_recovery_events(str(key), raw)
            )
            timing = recovery if recovery in {
                "short_rest",
                "long_rest",
                "both",
                "dawn",
                "manual",
                "none",
            } else "manual"
            pool = by_key.get(str(key))
            if pool is None:
                pool = ResourcePool(
                    campaign_id=character.campaign_id,
                    character_id=character.id,
                    key=str(key),
                    label=str(raw.get("label", key)),
                    category="spell_slot"
                    if str(key).startswith("spell_slots")
                    else "class_feature",
                    current=current,
                    maximum=maximum,
                    recovery_timing=timing,
                    metadata_json={
                        "legacy_resource": True,
                        "recovery_events": recovery_events,
                    },
                )
                session.add(pool)
                pools.append(pool)
                by_key[pool.key] = pool
            elif pool.category != "hit_die":
                pool.label = str(raw.get("label", pool.label))
                pool.current = current
                pool.maximum = maximum
                pool.recovery_timing = timing
                metadata = dict(pool.metadata_json or {})
                metadata["recovery_events"] = recovery_events
                pool.metadata_json = metadata

        hit_die_size = _hit_die_size(character.class_name)
        hit_die_key = f"hit_dice_d{hit_die_size}"
        hit_die = by_key.get(hit_die_key)
        if hit_die is None:
            hit_die = ResourcePool(
                campaign_id=character.campaign_id,
                character_id=character.id,
                key=hit_die_key,
                label=f"d{hit_die_size} 生命骰",
                category="hit_die",
                current=character.level,
                maximum=character.level,
                recovery_timing="manual",
                die_size=hit_die_size,
                rule_key="character.hit_dice",
                metadata_json={"derived_from_class": character.class_name or ""},
            )
            session.add(hit_die)
            pools.append(hit_die)
        elif hit_die.maximum < character.level:
            gained = character.level - hit_die.maximum
            hit_die.maximum = character.level
            hit_die.current = min(hit_die.maximum, hit_die.current + gained)
        session.flush()
        return sorted(pools, key=lambda pool: (pool.key, pool.id))

    @staticmethod
    def _item_charge_recovery(
        session: Session,
        character: Character,
        *,
        effective_type: str,
        completed: bool,
    ) -> list[dict[str, Any]]:
        """Build typed item-charge recovery changes without treating dawn as rest."""

        if not completed:
            return []
        rows = session.scalars(
            select(EquipmentInstance).where(
                EquipmentInstance.character_id == character.id,
                EquipmentInstance.campaign_id == character.campaign_id,
            )
        ).all()
        changes: list[dict[str, Any]] = []
        for row in rows:
            spec = (row.metadata_json or {}).get("item_spec")
            charges = spec.get("charges") if isinstance(spec, dict) else None
            if not isinstance(charges, dict):
                continue
            trigger = str(charges.get("recovery_trigger") or "none")
            if trigger != f"{effective_type}_rest":
                # ``dawn`` remains a typed world-time trigger and must not be
                # silently converted into long-rest recovery.
                continue
            maximum = int(row.max_charges or charges.get("maximum") or 0)
            before = int(row.charges or 0)
            if maximum <= before:
                continue
            recovery = charges.get("recovery_amount")
            amount = maximum - before if recovery in (None, "all") else int(recovery)
            after = min(maximum, before + max(0, amount))
            if after != before:
                changes.append(
                    {
                        "equipment_instance_id": row.id,
                        "name": row.name,
                        "before": before,
                        "after": after,
                        "amount": after - before,
                        "recovery_trigger": trigger,
                        "type": "item_charge",
                        "explanation": f"{trigger} restores typed item charges",
                    }
                )
        return changes

    def list_resources(
        self, campaign_id: str, *, character_id: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            query = select(Character).where(Character.campaign_id == campaign_id)
            if character_id:
                query = query.where(Character.id == character_id)
            characters = session.scalars(query.order_by(Character.created_at, Character.id)).all()
            if character_id and not characters:
                raise StateNotFoundError("character not found in campaign")
            for character in characters:
                self._sync_pools(session, character)
            rows = session.scalars(
                select(ResourcePool)
                .where(
                    ResourcePool.campaign_id == campaign_id,
                    *(
                        (ResourcePool.character_id == character_id,)
                        if character_id
                        else ()
                    ),
                )
                .order_by(ResourcePool.character_id, ResourcePool.created_at, ResourcePool.id)
            ).all()
            return tuple(serialize(row) for row in rows)

    @staticmethod
    def _apply_feature_recovery_choices(
        character: Character,
        resources: tuple[RestResource, ...],
        participant: Mapping[str, Any],
        *,
        effective_type: str,
        completed: bool,
    ) -> tuple[tuple[RestResource, ...], list[dict[str, Any]]]:
        """Apply explicitly submitted rest feature recoveries.

        The rest request is the authoritative player/DM input boundary.  The
        feature registry supplies the action contract; this method only
        executes the two deterministic recovery formulas currently supported.
        Missing choices do nothing, while a submitted choice that is not
        available fails closed instead of silently consuming a feature.
        """

        raw_choices = participant.get("feature_recovery_choices")
        choices = dict(raw_choices) if isinstance(raw_choices, Mapping) else {}
        if not choices or not completed:
            return resources, []
        grants = [item for item in character.features or [] if isinstance(item, dict)]
        if not grants:
            raise ValueError("休息特性恢复选择缺少职业特性运行时合同")
        scalings = {
            str(item.get("scaling_key")): {"value": item.get("value")}
            for item in grants
            if item.get("kind") == "class_scaling" and isinstance(item.get("scaling_key"), str)
        }
        registry = compile_feature_runtime_registry(
            grants,
            resources=character.resources if isinstance(character.resources, dict) else {},
            scalings=scalings,
            class_levels=character.class_levels if isinstance(character.class_levels, dict) else {},
            total_level=character.level,
        )
        actions = registry.get("actions")
        if not isinstance(actions, Mapping):
            raise ValueError("休息特性恢复选择缺少动作合同")
        by_key = {item.key: item for item in resources}
        applied: list[dict[str, Any]] = []
        for action_id, raw_amount in choices.items():
            action = actions.get(str(action_id))
            if action_id == "portent_pool":
                feature_pool = by_key.get("portent_dice")
                if feature_pool is None or effective_type != "long":
                    raise ValueError("预兆骰池只能在长休时生成")
                raw_values = (
                    raw_amount.get("values")
                    if isinstance(raw_amount, Mapping)
                    else raw_amount
                )
                if not isinstance(raw_values, list):
                    raise ValueError("预兆骰池必须提交 values 列表")
                values = [int(value) for value in raw_values]
                if len(values) != feature_pool.maximum or any(
                    value < 1 or value > 20 for value in values
                ):
                    raise ValueError("预兆骰池必须提交与资源上限相同数量的 1 至 20 骰值")
                by_key[feature_pool.key] = RestResource(
                    feature_pool.key,
                    len(values),
                    feature_pool.maximum,
                    feature_pool.recovery,
                    feature_pool.recovery_events,
                )
                applied.append(
                    {
                        "action_id": "portent_pool",
                        "resource_key": feature_pool.key,
                        "resource_cost": 0,
                        "pool_values": values,
                    }
                )
                continue
            if (
                isinstance(action, Mapping)
                and action.get("kind") == "rest_asset_loadout_reconfiguration"
            ):
                if effective_type != "long":
                    raise ValueError(f"资产配置只能在长休时变更：{action_id}")
                if not isinstance(raw_amount, Mapping):
                    raise ValueError(f"资产配置必须提交 weapon_ids 列表：{action_id}")
                raw_values = raw_amount.get("weapon_ids")
                if not isinstance(raw_values, list):
                    raise ValueError(f"资产配置必须提交 weapon_ids 列表：{action_id}")
                class_name = str(action.get("class_name") or "")
                current = [
                    dict(item)
                    for item in character.proficiencies or []
                    if isinstance(item, Mapping)
                    and item.get("kind") == "weapon_mastery"
                    and str(item.get("class_name") or "") == class_name
                ]
                if not current:
                    raise ValueError(f"角色没有可重配的武器精通：{action_id}")
                assets = [weapon_asset(value) for value in raw_values]
                if any(asset is None for asset in assets):
                    raise ValueError(f"武器不在2024权威目录中：{action_id}")
                asset_ids = [str(asset.id) for asset in assets if asset is not None]
                if len(asset_ids) != len(current) or len(set(asset_ids)) != len(asset_ids):
                    raise ValueError(f"重配后必须保持原数量且不重复：{action_id}")
                policy = str(action.get("eligibility_policy") or "")
                if any(
                    not weapon_is_eligible(
                        asset,
                        policy=policy,
                        proficiencies=list(character.proficiencies or []),
                    )
                    for asset in assets
                    if asset is not None
                ):
                    raise ValueError(f"重配包含不符合职业策略的武器：{action_id}")
                current_ids = {
                    str(item.get("id") or item.get("name") or "") for item in current
                }
                replacement_count = len(set(asset_ids) - current_ids)
                maximum_replacements = action.get("maximum_replacements")
                if maximum_replacements is not None and replacement_count > int(
                    maximum_replacements
                ):
                    raise ValueError(f"本次长休替换的武器精通过多：{action_id}")
                template_level = max(int(item.get("class_level") or 1) for item in current)
                selected_masteries = [
                    {
                        "kind": "weapon_mastery",
                        "id": asset.id,
                        "name": asset.name,
                        "weapon_category": asset.category,
                        "range_kind": asset.range_kind,
                        "mastery": asset.mastery,
                        "source_record_id": asset.source_record_id,
                        "mastery_source_record_id": "08fd9f442907e6520302fddf",
                        "class_name": class_name,
                        "class_level": template_level,
                        "selected_asset_status": "full",
                        "effect_status": "separate_asset_contract",
                    }
                    for asset in assets
                    if asset is not None
                ]
                applied.append(
                    {
                        "action_id": str(action_id),
                        "class_name": class_name,
                        "weapon_masteries": selected_masteries,
                        "replacement_count": replacement_count,
                    }
                )
                continue
            if isinstance(action, Mapping) and action.get("kind") == "rest_choice":
                trigger = str(action.get("trigger") or "").strip()
                if trigger not in {"short_rest", "long_rest", "short_or_long_rest"}:
                    raise ValueError(f"休息特性选择触发时机无效：{action_id}")
                if trigger != "short_or_long_rest" and trigger != effective_type + "_rest":
                    raise ValueError(f"休息特性选择不适用于本次休息：{action_id}")
                raw_value = (
                    raw_amount.get("value")
                    if isinstance(raw_amount, Mapping)
                    else raw_amount
                )
                selected = str(raw_value or "").strip().lower()
                options = {
                    str(value).strip().lower()
                    for value in action.get("choice_options") or ()
                    if str(value).strip()
                }
                if not options or selected not in options:
                    raise ValueError(f"休息特性选择不在允许范围内：{action_id}")
                applied.append(
                    {
                        "action_id": str(action_id),
                        "selection_key": str(action.get("choice_key") or action_id),
                        "selected": selected,
                    }
                )
                continue
            if not isinstance(action, Mapping) or action.get("kind") != "rest_recovery":
                raise ValueError(f"休息特性恢复动作不存在或不可执行：{action_id}")
            if action.get("trigger") != effective_type + "_rest":
                raise ValueError(f"休息特性恢复动作不适用于本次休息：{action_id}")
            resource_key = str(action.get("resource_key") or "").strip()
            restore_key = str(action.get("restore_resource_key") or "").strip()
            feature_pool = by_key.get(resource_key)
            restore_pool = by_key.get(restore_key)
            if feature_pool is None or (
                action_id != "natural_recovery" and restore_pool is None
            ):
                raise ValueError(f"休息特性恢复资源池不存在：{action_id}")
            if feature_pool.current < int(action.get("resource_cost") or 1):
                raise ValueError(f"休息特性恢复次数不足：{action_id}")
            if action.get("kind") == "rest_recovery" and action_id == "natural_recovery":
                if not isinstance(raw_amount, Mapping):
                    raise ValueError("自然恢复必须提交各法术环阶的恢复数量")
                class_level = (
                    max(
                        int(value)
                        for key, value in (character.class_levels or {}).items()
                        if str(key) in {"德鲁伊", "druid"}
                        and isinstance(value, int)
                    )
                    if any(
                        str(key) in {"德鲁伊", "druid"}
                        for key in (character.class_levels or {})
                    )
                    else 0
                )
                maximum_total_levels = (class_level + 1) // 2
                total_levels = 0
                restored_slots: list[tuple[int, int]] = []
                for raw_level, raw_count in raw_amount.items():
                    level = int(raw_level)
                    count = int(raw_count)
                    if level < 1 or level > int(action.get("maximum_slot_level") or 5):
                        raise ValueError("自然恢复只能选择1至5环法术位")
                    if count < 0:
                        raise ValueError("自然恢复数量不能为负数")
                    if count == 0:
                        continue
                    total_levels += level * count
                    restored_slots.append((level, count))
                if total_levels < 1 or total_levels > maximum_total_levels:
                    raise ValueError("自然恢复总环阶必须不超过德鲁伊等级一半（向上取整）")
                for level, count in restored_slots:
                    restore_pool = by_key.get(f"spell_slots_{level}")
                    if restore_pool is None:
                        raise ValueError(f"自然恢复法术位资源池不存在：{level}环")
                    available = max(0, restore_pool.maximum - restore_pool.current)
                    if count > available:
                        raise ValueError(f"自然恢复数量超过{level}环法术位缺口")
                by_key[resource_key] = RestResource(
                    feature_pool.key,
                    feature_pool.current - int(action.get("resource_cost") or 1),
                    feature_pool.maximum,
                    feature_pool.recovery,
                    feature_pool.recovery_events,
                )
                for level, count in restored_slots:
                    key = f"spell_slots_{level}"
                    pool = by_key[key]
                    by_key[key] = RestResource(
                        pool.key,
                        pool.current + count,
                        pool.maximum,
                        pool.recovery,
                        pool.recovery_events,
                    )
                applied.append(
                    {
                        "action_id": str(action_id),
                        "resource_key": resource_key,
                        "resource_cost": int(action.get("resource_cost") or 1),
                        "restore_resource_key": "spell_slots_*",
                        "slot_choices": {str(level): count for level, count in restored_slots},
                        "total_levels": total_levels,
                    }
                )
                continue
            amount = int(raw_amount)
            if action_id == "sorcery_restoration":
                class_level = (
                    max(
                        int(value)
                        for key, value in (character.class_levels or {}).items()
                        if str(key) in {"术士", "sorcerer"}
                        and isinstance(value, int)
                    )
                    if any(
                        str(key) in {"术士", "sorcerer"}
                        for key in (character.class_levels or {})
                    )
                    else 0
                )
                maximum_amount = class_level // 2
                if amount < 1 or amount > maximum_amount:
                    raise ValueError("术法复苏数量必须不大于术士等级一半且至少为1")
            else:
                raise ValueError(f"未支持的休息特性恢复动作：{action_id}")
            available = max(0, restore_pool.maximum - restore_pool.current)
            if amount > available:
                raise ValueError(f"休息特性恢复数量超过资源池缺口：{restore_key}")
            by_key[resource_key] = RestResource(
                feature_pool.key,
                feature_pool.current - int(action.get("resource_cost") or 1),
                feature_pool.maximum,
                feature_pool.recovery,
                feature_pool.recovery_events,
            )
            by_key[restore_key] = RestResource(
                restore_pool.key,
                restore_pool.current + amount,
                restore_pool.maximum,
                restore_pool.recovery,
                restore_pool.recovery_events,
            )
            applied.append(
                {
                    "action_id": str(action_id),
                    "resource_key": resource_key,
                    "resource_cost": int(action.get("resource_cost") or 1),
                    "restore_resource_key": restore_key,
                    "amount": amount,
                }
            )
        return tuple(by_key[item.key] for item in resources), applied

    def _refresh_selection_bound_spells(
        self,
        session: Session,
        *,
        campaign: Campaign,
        character: Character,
        resources: tuple[RestResource, ...],
        applied: list[dict[str, Any]],
    ) -> set[str]:
        """Rebuild fixed spell-table rows after a persisted rest selection."""

        selection_keys = {
            str(item.get("selection_key") or "")
            for item in applied
            if str(item.get("selection_key") or "")
        }
        if not selection_keys:
            return set()
        enabled_content_packs = tuple(str(value) for value in campaign.enabled_content_packs or ())
        allow_legacy = bool(campaign.allow_legacy)
        try:
            class_rules = self.catalog.classes(
                enabled_content_packs=enabled_content_packs,
                allow_legacy=allow_legacy,
            )
            spell_catalog = tuple(
                dict(item)
                for item in self.catalog.options(
                    enabled_content_packs=enabled_content_packs,
                    allow_legacy=allow_legacy,
                ).get("spells", [])
            )
        except Exception:
            # The selection itself remains authoritative; if an optional
            # corpus cannot be read, do not invent spell rows.
            return selection_keys

        selected_values = {
            key: str(
                (character.resources or {}).get(key, {}).get("selected") or ""
            ).strip().lower()
            for key in selection_keys
        }
        for entry in applied:
            key = str(entry.get("selection_key") or "")
            if key in selected_values:
                selected_values[key] = str(entry.get("selected") or "").strip().lower()

        from dnd_dm_assistant.infrastructure.database.advancement_service import (
            _fixed_subclass_spell_additions,
        )

        desired: list[dict[str, Any]] = []
        bound_feature_ids: set[str] = set()
        class_levels = character.class_levels if isinstance(character.class_levels, dict) else {}
        subclass_choices = (
            character.subclass_choices if isinstance(character.subclass_choices, dict) else {}
        )
        for raw_class_name, raw_level in class_levels.items():
            class_name = canonical_class_name(str(raw_class_name))
            target_level = int(raw_level or 0)
            if target_level < 1:
                continue
            rule = next((item for item in class_rules if item.name == class_name), None)
            if rule is None:
                continue
            subclass_name = str(
                subclass_choices.get(raw_class_name)
                or subclass_choices.get(class_name)
                or ""
            ).strip()
            subclass = next(
                (
                    item
                    for item in rule.subclasses
                    if str(item.get("name") or "").strip() == subclass_name
                ),
                None,
            )
            if not isinstance(subclass, dict):
                continue
            for definition in subclass.get("feature_definitions") or ():
                if not isinstance(definition, dict):
                    continue
                description = str(definition.get("description") or "")
                if "选择一种地形" not in description:
                    continue
                bound_feature_ids.add(
                    str(definition.get("id") or definition.get("name") or "")
                )
            for key in selection_keys:
                selected = selected_values.get(key) or None
                if not selected:
                    continue
                desired.extend(
                    _fixed_subclass_spell_additions(
                        subclass,
                        class_name=class_name,
                        target_class_level=target_level,
                        spell_catalog=spell_catalog,
                        selected_terrain=(
                            selected if key == "circle_land_terrain" else None
                        ),
                    )
                )

        existing = [
            dict(item)
            for item in character.spells or ()
            if isinstance(item, dict)
            and str(item.get("selection_resource_key") or "") not in selection_keys
            and str(item.get("source_feature_id") or "") not in bound_feature_ids
        ]
        identities = {
            str(item.get("source_record_id") or item.get("name") or "")
            for item in existing
        }
        for spell in desired:
            identity = str(spell.get("source_record_id") or spell.get("name") or "")
            if not identity or identity in identities:
                continue
            existing.append(spell)
            identities.add(identity)
        character.spells = existing
        return selection_keys

    def _preview_in_session(
        self,
        session: Session,
        campaign_id: str,
        request_data: dict[str, Any],
    ) -> dict[str, Any]:
        campaign = self._campaign(session, campaign_id)
        rest_type = str(request_data["rest_type"])
        duration = int(request_data["duration_minutes"])
        interrupted = bool(request_data.get("interrupted", False))
        fallback = bool(request_data.get("fallback_to_short_rest", False))
        override = str(request_data.get("dm_override_reason") or "").strip()
        minimum = 60 if rest_type == "short" else 480
        if duration < minimum and not override:
            raise ValueError(
                f"{'short' if rest_type == 'short' else 'long'} rest requires "
                f"at least {minimum} minutes or a DM override reason"
            )
        if fallback and (not interrupted or rest_type != "long" or duration < 60):
            raise ValueError(
                "short-rest fallback requires an interrupted long rest with at least 60 minutes"
            )

        world_before = campaign.current_time
        world_after = world_before + timedelta(minutes=duration) if world_before else None
        warnings: list[str] = []
        if world_before is None:
            warnings.append("战役世界时间为空；本次休息不会擅自写入现实时间。")
        if rest_type == "long" and world_before is not None:
            last_long_rest = session.scalar(
                select(RestRecord)
                .where(
                    RestRecord.campaign_id == campaign_id,
                    RestRecord.rest_type == "long",
                    RestRecord.status == "completed",
                    RestRecord.world_time_after.is_not(None),
                )
                .order_by(RestRecord.world_time_after.desc(), RestRecord.id.desc())
            )
            if (
                last_long_rest is not None
                and last_long_rest.world_time_after is not None
                and world_before - last_long_rest.world_time_after < timedelta(hours=16)
            ):
                if not override:
                    raise ValueError(
                        "a character must wait at least 16 hours after a long rest; "
                        "provide a DM override reason to continue"
                    )
                warnings.append("DM 已覆盖两次长休之间至少 16 小时的限制。")
        if interrupted:
            warnings.append("休息被中断；只有 DM 明确选择的长休折算短休才会产生收益。")
        effective_type = "short" if fallback else rest_type
        no_benefits = interrupted and not fallback
        participant_results: list[dict[str, Any]] = []
        token_state: list[dict[str, Any]] = []

        seen_characters: set[str] = set()
        for participant in request_data["participants"]:
            character_id = str(participant["character_id"])
            if character_id in seen_characters:
                raise ValueError("duplicate rest participant")
            seen_characters.add(character_id)
            character = self._character(session, campaign_id, character_id)
            expected_version = int(participant["character_version"])
            if character.version != expected_version:
                raise VersionConflict(
                    "character",
                    character.id,
                    expected_version,
                    character.version,
                )
            pools = self._sync_pools(session, character)
            pool_by_id = {pool.id: pool for pool in pools}
            excluded = {str(key) for key in participant.get("excluded_resource_keys", [])}
            resources = tuple(
                RestResource(
                    key=pool.key,
                    current=pool.current,
                    maximum=pool.maximum,
                    recovery=_resource_recovery(pool.recovery_timing),
                    recovery_events=tuple(
                        dict(item)
                        for item in (pool.metadata_json or {}).get("recovery_events", [])
                        if isinstance(item, dict)
                    ),
                )
                for pool in pools
                if pool.category != "hit_die" and pool.key not in excluded
            )
            untouched = {
                pool.key: pool
                for pool in pools
                if pool.category != "hit_die" and pool.key in excluded
            }
            hit_dice_pools = [pool for pool in pools if pool.category == "hit_die"]
            hit_dice = {
                f"d{pool.die_size or 8}": pool.current for pool in hit_dice_pools
            }
            spends: list[HitDieSpend] = []
            hit_die_details: list[dict[str, Any]] = []
            for selection in participant.get("hit_dice", []):
                pool = pool_by_id.get(str(selection["resource_pool_id"]))
                if pool is None or pool.category != "hit_die":
                    raise ValueError("selected hit die resource pool is invalid")
                roll = int(selection["roll"])
                if pool.die_size is not None and roll > pool.die_size:
                    raise ValueError(f"hit die roll cannot exceed d{pool.die_size}")
                die = f"d{pool.die_size or 8}"
                spends.append(HitDieSpend(die=die, roll=roll))
                hit_die_details.append(
                    {"resource_pool_id": pool.id, "key": pool.key, "die": die, "roll": roll}
                )

            ability_scores = dict(character.ability_scores or {})
            con_modifier = _ability_modifier(int(ability_scores.get("constitution", 10)))
            fatigue_condition = self._fatigue_condition(session, character.id)
            fatigue = self._fatigue_level(fatigue_condition)
            if no_benefits:
                after_hp = character.hp
                after_fatigue = fatigue
                after_resources = resources
                after_hit_dice = hit_dice
                completed = False
            elif effective_type == "short":
                fatigue_reduction = self._short_rest_fatigue_reduction(character)
                resolution = resolve_short_rest(
                    current_hp=character.hp,
                    max_hp=character.max_hp,
                    constitution_modifier=con_modifier,
                    hit_dice=hit_dice,
                    spends=tuple(spends),
                    resources=resources,
                    fatigue=fatigue,
                    fatigue_reduction=fatigue_reduction,
                    started_at=world_before,
                )
                after_hp = resolution.current_hp
                after_fatigue = resolution.fatigue
                after_resources = resolution.resources
                after_hit_dice = resolution.hit_dice
                completed = True
            else:
                if spends:
                    raise ValueError("hit dice can only be spent during a short rest")
                resolution_long = resolve_long_rest(
                    current_hp=character.hp,
                    max_hp=character.max_hp,
                    fatigue=fatigue,
                    resources=resources,
                    started_at=world_before,
                )
                after_hp = resolution_long.current_hp
                after_fatigue = resolution_long.fatigue
                after_resources = resolution_long.resources
                after_hit_dice = hit_dice
                completed = True

            after_resources, feature_recovery_applied = self._apply_feature_recovery_choices(
                character,
                after_resources,
                participant,
                effective_type=effective_type,
                completed=completed,
            )
            selection_keys = self._refresh_selection_bound_spells(
                session,
                campaign=campaign,
                character=character,
                resources=after_resources,
                applied=feature_recovery_applied,
            )
            after_resource_map = {item.key: item for item in after_resources}
            resource_changes: list[dict[str, Any]] = []
            for pool in pools:
                if pool.category == "hit_die":
                    after_value = after_hit_dice.get(f"d{pool.die_size or 8}", pool.current)
                    change_type = "hit_die"
                elif pool.key in untouched:
                    after_value = pool.current
                    change_type = "resource"
                else:
                    after_value = after_resource_map.get(
                        pool.key,
                        RestResource(pool.key, pool.current, pool.maximum, None),
                    ).current
                    change_type = "spell_slot" if pool.category == "spell_slot" else "resource"
                if after_value != pool.current:
                    resource_changes.append(
                        {
                            "type": change_type,
                            "resource_pool_id": pool.id,
                            "key": pool.key,
                            "label": pool.label,
                            "before": pool.current,
                            "after": after_value,
                            "amount": abs(after_value - pool.current),
                        }
                    )
            changes = [
                {
                    "type": "hp",
                    "before": character.hp,
                    "after": after_hp,
                    "amount": max(0, after_hp - character.hp),
                    "explanation": (
                        "生命骰恢复"
                        if effective_type == "short"
                        else "长休恢复全部生命值"
                    ),
                }
            ]
            changes.extend(resource_changes)
            item_charge_changes = self._item_charge_recovery(
                session,
                character,
                effective_type=effective_type,
                completed=completed,
            )
            changes.extend(item_charge_changes)
            if after_fatigue != fatigue:
                changes.append(
                    {
                        "type": "condition",
                        "before": fatigue,
                        "after": after_fatigue,
                        "amount": fatigue - after_fatigue,
                        "explanation": "完成长休后疲劳降低 1 级",
                    }
                )
            if completed and effective_type == "long":
                if character.max_hp_reduction:
                    changes.append(
                        {
                            "type": "other",
                            "key": "max_hp_reduction",
                            "label": "最大生命值降低",
                            "before": character.max_hp_reduction,
                            "after": 0,
                            "amount": character.max_hp_reduction,
                            "explanation": "完成长休后恢复降低的最大生命值",
                        }
                    )
                ability_reduction_total = sum(
                    max(0, int(value))
                    for value in (character.ability_score_reductions or {}).values()
                )
                if ability_reduction_total:
                    changes.append(
                        {
                            "type": "other",
                            "key": "ability_score_reductions",
                            "label": "属性值降低",
                            "before": ability_reduction_total,
                            "after": 0,
                            "amount": ability_reduction_total,
                            "explanation": "完成长休后恢复降低的属性值",
                        }
                    )
                death_save_total = sum(
                    max(0, int((character.death_saves or {}).get(key, 0)))
                    for key in ("successes", "failures")
                )
                if death_save_total:
                    changes.append(
                        {
                            "type": "other",
                            "key": "death_saves",
                            "label": "死亡豁免记录",
                            "before": death_save_total,
                            "after": 0,
                            "amount": death_save_total,
                            "explanation": "角色恢复后清空死亡豁免记录",
                        }
                    )
            participant_results.append(
                {
                    "character_id": character.id,
                    "character_name": character.name,
                    "character_version": character.version,
                    "completed": completed,
                    "feature_recovery_applied": feature_recovery_applied,
                    "selection_bound_spell_keys": sorted(selection_keys),
                    "before": {
                        "hp": character.hp,
                        "fatigue": fatigue,
                        "max_hp_reduction": character.max_hp_reduction,
                        "ability_score_reductions": dict(
                            character.ability_score_reductions or {}
                        ),
                        "death_saves": dict(character.death_saves or {}),
                    },
                    "after": {
                        "hp": after_hp,
                        "fatigue": after_fatigue,
                        "max_hp_reduction": (
                            0 if completed and effective_type == "long"
                            else character.max_hp_reduction
                        ),
                        "ability_score_reductions": (
                            {} if completed and effective_type == "long"
                            else dict(character.ability_score_reductions or {})
                        ),
                        "death_saves": (
                            {"successes": 0, "failures": 0}
                            if completed and effective_type == "long"
                            else dict(character.death_saves or {})
                        ),
                    },
                    "changes": changes,
                    "item_charge_changes": item_charge_changes,
                    "hit_dice": hit_die_details,
                }
            )
            token_state.append(
                {
                    "id": character.id,
                    "version": character.version,
                    "hp": character.hp,
                    "max_hp": character.max_hp,
                    "fatigue": fatigue,
                    "max_hp_reduction": character.max_hp_reduction,
                    "ability_score_reductions": dict(
                        character.ability_score_reductions or {}
                    ),
                    "death_saves": dict(character.death_saves or {}),
                    "pools": [
                        [pool.id, pool.key, pool.current, pool.maximum, pool.recovery_timing]
                        for pool in pools
                    ],
                }
            )

        token_payload = {
            "campaign_id": campaign_id,
            "campaign_version": campaign.version,
            "world_time": _json_value(world_before),
            "request": _json_value(request_data),
            "state": token_state,
        }
        token = hashlib.sha256(
            json.dumps(token_payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return {
            "preview_token": token,
            "rest_type": rest_type,
            "effective_rest_type": effective_type,
            "duration_minutes": duration,
            "interrupted": interrupted,
            "world_time_before": _json_value(world_before),
            "world_time_after": _json_value(world_after),
            "warnings": warnings,
            "participants": participant_results,
            "rule_reference": RULE_REFERENCE,
        }

    def preview(self, campaign_id: str, request_data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            return self._preview_in_session(session, campaign_id, request_data)

    def confirm_feature_recovery(
        self, campaign_id: str, request_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a non-combat, idempotent feature recovery ritual."""

        idempotency_key = str(request_data.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise ValueError("feature recovery idempotency_key is required")
        operation_key = f"feature-recovery:{idempotency_key}"
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == operation_key,
                )
            )
            if existing is not None:
                return dict(existing.after_snapshot or {})
            character = self._character(
                session,
                campaign_id,
                str(request_data.get("character_id") or ""),
            )
            expected_version = int(request_data.get("character_version") or 0)
            if character.version != expected_version:
                raise VersionConflict(
                    "character", character.id, expected_version, character.version
                )
            feature_id = str(request_data.get("feature_id") or "").strip()
            if not feature_id:
                raise ValueError("feature recovery feature_id is required")
            grants = [item for item in character.features or [] if isinstance(item, dict)]
            registry = compile_feature_runtime_registry(
                grants,
                resources=character.resources if isinstance(character.resources, dict) else {},
                class_levels=(
                    character.class_levels if isinstance(character.class_levels, dict) else {}
                ),
                total_level=character.level,
            )
            actions = registry.get("actions")
            action = actions.get(feature_id) if isinstance(actions, Mapping) else None
            if not isinstance(action, Mapping) or action.get("kind") != "ritual_recovery":
                raise ValueError("该职业特性没有可执行的仪式恢复合同")
            if int(request_data.get("ritual_minutes") or 0) != 1:
                raise ValueError("秘法回流必须完成一分钟仪式")
            resource_key = str(action.get("resource_key") or "").strip()
            restore_key = str(action.get("restore_resource_key") or "").strip()
            resources = dict(character.resources or {})
            feature_pool = dict(resources.get(resource_key) or {})
            restore_pool = dict(resources.get(restore_key) or {})
            feature_before = int(feature_pool.get("current") or 0)
            if feature_before < int(action.get("resource_cost") or 1):
                raise ValueError("秘法回流今日使用次数不足")
            restore_before = int(restore_pool.get("current") or 0)
            restore_max = int(restore_pool.get("max") or restore_pool.get("maximum") or 0)
            if restore_max < 1:
                raise ValueError("秘法回流缺少契约魔法法术位上限")
            amount_formula = str(action.get("amount_formula") or "").strip()
            remaining = restore_max - restore_before
            if amount_formula == "all_expended":
                amount = remaining
            elif amount_formula == "half_expended_round_up":
                amount = (remaining + 1) // 2
            else:
                raise ValueError("秘法回流缺少受支持的恢复数量公式")
            amount = min(amount, remaining)
            feature_pool["current"] = feature_before - int(action.get("resource_cost") or 1)
            restore_pool["current"] = restore_before + amount
            resources[resource_key] = feature_pool
            resources[restore_key] = restore_pool
            before = {
                "character_id": character.id,
                "character_version": character.version,
                "resources": dict(character.resources or {}),
            }
            character.resources = resources
            character.version += 1
            character.updated_at = datetime.now(UTC)
            result = {
                "feature_id": feature_id,
                "feature_name": action.get("name"),
                "ritual_minutes": 1,
                "resource_key": resource_key,
                "resource_before": feature_before,
                "resource_after": feature_pool["current"],
                "restore_resource_key": restore_key,
                "restored_amount": amount,
                "restore_before": restore_before,
                "restore_after": restore_pool["current"],
                "character": serialize(character),
            }
            session.add(
                OperationTransaction(
                    campaign_id=campaign_id,
                    operation_type="feature_recovery",
                    idempotency_key=operation_key,
                    status="applied",
                    before_snapshot=before,
                    after_snapshot=result,
                    reason="完成一分钟职业特性仪式恢复",
                    source="game_table",
                    confirmed_at=datetime.now(UTC),
                )
            )
            session.flush()
            return result

    def confirm(self, campaign_id: str, request_data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            return self.confirm_in_session(session, campaign_id, request_data)

    def confirm_in_session(
        self,
        session: Session,
        campaign_id: str,
        request_data: dict[str, Any],
        *,
        require_preview_token: bool = True,
    ) -> dict[str, Any]:
        request_data = dict(request_data)
        idempotency_key = str(request_data.pop("idempotency_key"))
        raw_preview_token = request_data.pop("preview_token", None)
        preview_token = str(raw_preview_token) if raw_preview_token is not None else None
        if require_preview_token and preview_token is None:
            raise ValueError("preview_token required")
        existing = session.scalar(
            select(RestRecord).where(
                RestRecord.campaign_id == campaign_id,
                RestRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return {**dict(existing.result_json or {}), "idempotent_replay": True}

        preview = self._preview_in_session(session, campaign_id, request_data)
        if preview_token is not None and preview["preview_token"] != preview_token:
            raise VersionConflict("rest preview", "state", 1, 2)
        campaign = self._campaign(session, campaign_id)
        now = datetime.now(UTC)
        before_snapshot = {
            "campaign_time": _json_value(campaign.current_time),
            "participants": [
                {"character_id": item["character_id"], "before": item["before"]}
                for item in preview["participants"]
            ],
        }
        operation = OperationTransaction(
            campaign_id=campaign_id,
            operation_type="rest",
            idempotency_key=f"rest:{idempotency_key}",
            status="applied",
            before_snapshot=before_snapshot,
            after_snapshot={},
            reason=str(request_data.get("notes") or "DM 确认休息结算"),
            source="game_table",
            confirmed_at=now,
        )
        session.add(operation)
        session.flush()
        rest = RestRecord(
            campaign_id=campaign_id,
            operation_transaction_id=operation.id,
            rest_type=str(request_data["rest_type"]),
            status="interrupted" if request_data.get("interrupted") else "completed",
            duration_minutes=int(request_data["duration_minutes"]),
            interrupted=bool(request_data.get("interrupted", False)),
            started_at=campaign.current_time,
            completed_at=(
                campaign.current_time + timedelta(minutes=int(request_data["duration_minutes"]))
                if campaign.current_time
                else now
            ),
            world_time_before=campaign.current_time,
            world_time_after=(
                campaign.current_time + timedelta(minutes=int(request_data["duration_minutes"]))
                if campaign.current_time
                else None
            ),
            request_json=_json_value(request_data),
            result_json={},
            idempotency_key=idempotency_key,
            notes=request_data.get("notes"),
        )
        session.add(rest)
        session.flush()

        for participant in preview["participants"]:
            character = self._character(session, campaign_id, participant["character_id"])
            character.hp = int(participant["after"]["hp"])
            resources_json = dict(character.resources or {})
            for change in participant["changes"]:
                change_type = str(change["type"])
                pool_id = change.get("resource_pool_id")
                pool = session.get(ResourcePool, pool_id) if pool_id else None
                if pool is not None:
                    pool.current = int(change["after"])
                    if pool.category != "hit_die":
                        existing_resource = resources_json.get(pool.key, {})
                        raw = (
                            dict(existing_resource)
                            if isinstance(existing_resource, dict)
                            else {}
                        )
                        raw["label"] = pool.label
                        raw["current"] = pool.current
                        raw["max"] = pool.maximum
                        raw["recovery"] = pool.recovery_timing
                        metadata = dict(pool.metadata_json or {})
                        events = metadata.get("recovery_events")
                        if isinstance(events, list):
                            raw["recovery_events"] = [
                                dict(item) for item in events if isinstance(item, dict)
                            ]
                        resources_json[pool.key] = raw
                session.add(
                    RestRecoveryEntry(
                        rest_record_id=rest.id,
                        character_id=character.id,
                        resource_pool_id=pool.id if pool else None,
                        recovery_type=change_type,
                        before_value=int(change["before"]),
                        after_value=int(change["after"]),
                        amount=int(change.get("amount", 0)),
                        die_roll=None,
                        modifier=None,
                        explanation=str(change.get("explanation") or ""),
                        rule_reference=RULE_REFERENCE,
                        selected=True,
                        applied=True,
                        status="applied",
                    )
                )
            for item_change in participant.get("item_charge_changes") or []:
                equipment = session.get(
                    EquipmentInstance,
                    str(item_change.get("equipment_instance_id") or ""),
                )
                if equipment is None or equipment.character_id != character.id:
                    raise StateNotFoundError("item charge recovery equipment not found")
                if equipment.charges != int(item_change["before"]):
                    raise VersionConflict(
                        "equipment_instance",
                        equipment.id,
                        int(item_change["before"]),
                        int(equipment.charges or 0),
                    )
                equipment.charges = int(item_change["after"])
                equipment.version += 1
            character.resources = resources_json
            if participant.get("completed") and str(request_data.get("rest_type") or "") == "long":
                if "portent_dice" in resources_json:
                    pool = dict(resources_json.get("portent_dice") or {})
                    pool["available_values"] = []
                    pool["current"] = 0
                    resources_json["portent_dice"] = pool
                    character.resources = resources_json
            for recovery in participant.get("feature_recovery_applied") or []:
                if (
                    isinstance(recovery, dict)
                    and recovery.get("action_id") == "portent_pool"
                    and isinstance(recovery.get("pool_values"), list)
                ):
                    pool = dict(resources_json.get("portent_dice") or {})
                    values = [int(value) for value in recovery["pool_values"]]
                    pool["available_values"] = values
                    pool["current"] = len(values)
                    pool["max"] = int(pool.get("max") or len(values))
                    pool["maximum"] = int(pool.get("maximum") or pool["max"])
                    resources_json["portent_dice"] = pool
                    character.resources = resources_json
                elif (
                    isinstance(recovery, dict)
                    and recovery.get("selection_key")
                    and isinstance(recovery.get("selected"), str)
                ):
                    selection_key = str(recovery["selection_key"])
                    selection = dict(resources_json.get(selection_key) or {})
                    selection["selected"] = recovery["selected"]
                    resources_json[selection_key] = selection
                    character.resources = resources_json
                elif (
                    isinstance(recovery, dict)
                    and isinstance(recovery.get("weapon_masteries"), list)
                    and recovery.get("class_name")
                ):
                    owner_class = str(recovery["class_name"])
                    preserved = [
                        item
                        for item in character.proficiencies or []
                        if not (
                            isinstance(item, dict)
                            and item.get("kind") == "weapon_mastery"
                            and str(item.get("class_name") or "") == owner_class
                        )
                    ]
                    character.proficiencies = [
                        *preserved,
                        *[dict(item) for item in recovery["weapon_masteries"]],
                    ]
            selection_bound_spell_keys = {
                str(value)
                for value in participant.get("selection_bound_spell_keys") or ()
                if str(value)
            }
            if selection_bound_spell_keys:
                from dnd_dm_assistant.infrastructure.database.advancement_service import (
                    AdvancementService,
                )

                AdvancementService._sync_source_bound_spells(
                    session,
                    campaign_id=campaign_id,
                    character_id=character.id,
                    spells=list(character.spells or []),
                    bound_selection_keys=selection_bound_spell_keys,
                )
            character.max_hp_reduction = int(participant["after"]["max_hp_reduction"])
            character.ability_score_reductions = dict(
                participant["after"]["ability_score_reductions"]
            )
            character.death_saves = dict(participant["after"]["death_saves"])
            feature_runtime_resets: list[str] = []
            if participant.get("completed") and (
                bool(request_data.get("fallback_to_short_rest"))
                or str(request_data.get("rest_type") or "") in {"short", "long"}
            ):
                feature_runtime_resets = self._reset_combat_feature_states(
                    session,
                    character_id=character.id,
                    rest_event=(
                        "short_rest"
                        if bool(request_data.get("fallback_to_short_rest"))
                        or str(request_data.get("rest_type") or "") == "short"
                        else "long_rest"
                    ),
                )
            if feature_runtime_resets:
                participant["feature_runtime_resets"] = feature_runtime_resets
            before_fatigue = int(participant["before"]["fatigue"])
            after_fatigue = int(participant["after"]["fatigue"])
            if after_fatigue != before_fatigue:
                condition = self._fatigue_condition(session, character.id)
                if condition is not None:
                    if after_fatigue == 0:
                        session.delete(condition)
                    else:
                        details = dict(condition.details or {})
                        details["level"] = after_fatigue
                        condition.details = details
                        condition.version += 1
            character.version += 1
            character.updated_at = now

        if campaign.current_time is not None:
            campaign.current_time = campaign.current_time + timedelta(
                minutes=int(request_data["duration_minutes"])
            )
            campaign.version += 1
            campaign.updated_at = now
        result = {
            **preview,
            "rest_record_id": rest.id,
            "operation_transaction_id": operation.id,
            "idempotent_replay": False,
        }
        operation.after_snapshot = {
            "campaign_time": _json_value(campaign.current_time),
            "participants": [
                {"character_id": item["character_id"], "after": item["after"]}
                for item in preview["participants"]
            ],
        }
        rest.result_json = _json_value(result)
        session.flush()
        return result
