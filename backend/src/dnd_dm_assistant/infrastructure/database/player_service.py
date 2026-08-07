# ruff: noqa: E501, E701, E702

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult, Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import CombatActionCommand
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.equipment_rules import equipment_profile
from dnd_dm_assistant.domain.noncombat_actions import json_dict
from dnd_dm_assistant.domain.spell_rules import enrich_spell_action
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import (
    Attunement,
    AuditLog,
    Campaign,
    Character,
    CharacterCondition,
    Combat,
    Combatant,
    EquipmentInstance,
    Event,
    Handout,
    KnownSpell,
    PlayerActionRequest,
    PlayerRoom,
    Scene,
    SceneGrid,
    SceneObject,
    SceneToken,
    Wallet,
)
from dnd_dm_assistant.infrastructure.database.rest_service import RestService


class PlayerService:
    """Separate read boundary for player-safe projections and request inboxes."""

    _INTERNAL_ACTION_TYPES = frozenset({"post_hit_rider"})
    _INTERNAL_IDEMPOTENCY_PREFIXES = ("post-hit:",)

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.rest = RestService(engine)

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
            raise StateNotFoundError("character not found")
        return character

    @staticmethod
    def _audit(
        session: Session,
        campaign_id: str,
        action: str,
        request: PlayerActionRequest,
        request_id: str,
    ) -> None:
        session.add(
            AuditLog(
                campaign_id=campaign_id,
                actor="player" if action == "player_request" else "dm",
                action=action,
                entity_type="player_action_request",
                entity_id=request.id,
                before_json=None,
                after_json=serialize(request),
                request_id=request_id,
            )
        )

    def player_view(self, campaign_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            campaign = self._campaign(session, campaign_id)
            scene = session.scalars(
                select(Scene)
                .where(Scene.campaign_id == campaign_id, Scene.status == "active")
                .order_by(Scene.created_at, Scene.id)
            ).first()
            result: dict[str, Any] = {
                "campaign": {
                    "id": campaign.id,
                    "name": campaign.name,
                    "current_time": campaign.current_time,
                },
                "scene": None,
                "initiative": [],
                "handouts": [],
                "shared_log": [],
            }
            if scene:
                grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene.id))
                tokens = session.scalars(
                    select(SceneToken)
                    .where(SceneToken.scene_id == scene.id, SceneToken.visible.is_(True))
                    .order_by(SceneToken.id)
                ).all()
                objects = session.scalars(
                    select(SceneObject)
                    .where(SceneObject.scene_id == scene.id, SceneObject.visibility == "public")
                    .order_by(SceneObject.id)
                ).all()
                result["scene"] = {
                    "id": scene.id,
                    "name": scene.name,
                    "description": scene.description,
                    "grid": None
                    if grid is None
                    else {
                        "width": grid.width,
                        "height": grid.height,
                        "cell_size_ft": grid.cell_size_ft,
                        "mode": grid.mode,
                        "public_description": grid.public_description,
                    },
                    "tokens": [
                        {
                            "id": t.id,
                            "label": t.label,
                            "row": t.row,
                            "col": t.col,
                            "size_cells": t.size_cells,
                            "elevation_ft": t.elevation_ft,
                        }
                        for t in tokens
                    ],
                    "objects": [
                        {
                            "id": o.id,
                            "object_type": o.object_type,
                            "label": o.label,
                            "row": o.row,
                            "col": o.col,
                            "width_cells": o.width_cells,
                            "height_cells": o.height_cells,
                            "state": o.state,
                        }
                        for o in objects
                    ],
                }
            combat = session.scalars(
                select(Combat)
                .where(Combat.campaign_id == campaign_id, Combat.status == "active")
                .order_by(Combat.created_at.desc())
            ).first()
            if combat:
                combatants = session.scalars(
                    select(Combatant)
                    .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
                    .order_by(Combatant.initiative.desc(), Combatant.id)
                ).all()
                result["initiative"] = [
                    {
                        "id": c.id,
                        "name": c.display_name,
                        "initiative": c.initiative,
                        "hp": c.hp,
                        "max_hp": c.max_hp,
                        "conditions": c.conditions,
                    }
                    for c in combatants
                ]
            handouts = session.scalars(
                select(Handout)
                .where(Handout.campaign_id == campaign_id, Handout.published.is_(True))
                .order_by(Handout.sort_order, Handout.id)
            ).all()
            result["handouts"] = [
                {"id": h.id, "title": h.title, "body": h.body, "sort_order": h.sort_order}
                for h in handouts
            ]
            events = session.scalars(
                select(Event)
                .where(
                    Event.campaign_id == campaign_id, Event.visibility.in_(("players", "public"))
                )
                .order_by(Event.occurred_at.desc())
                .limit(100)
            ).all()
            result["shared_log"] = [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "title": e.title,
                    "description": e.description,
                    "occurred_at": e.occurred_at,
                }
                for e in events
            ]
            return result

    def character_view(self, campaign_id: str, character_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            character = self._character(session, campaign_id, character_id)
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.campaign_id == campaign_id,
                    Wallet.character_id == character_id,
                )
            )
            # Explicit allowlist: notably excludes notes and every DM-only relation.
            result = {
                key: getattr(character, key)
                for key in (
                    "id",
                    "name",
                    "race",
                    "background",
                    "class_name",
                    "level",
                    "experience",
                    "armor_class",
                    "speed",
                    "ability_scores",
                    "hp",
                    "max_hp",
                    "max_hp_reduction",
                    "death_saves",
                    "inventory",
                    "equipment",
                    "proficiencies",
                    "skills",
                    "features",
                    "actions",
                    "resources",
                    "spells",
                    "spellcasting",
                    "class_levels",
                    "subclass_choices",
                    "version",
                )
            }
            known_spells = session.scalars(
                select(KnownSpell)
                .where(KnownSpell.character_id == character_id)
                .order_by(KnownSpell.created_at, KnownSpell.id)
            ).all()
            spell_fields = (
                "source_record_id",
                "source_path",
                "damage",
                "damage_expression",
                "damage_dice",
                "healing",
                "damage_type",
                "save_ability",
                "save_dc",
                "half_damage_on_save",
                "range",
                "description",
                "cost",
                "resource_key",
                "resource_cost",
                "spell_level",
                "upcast_damage_dice",
                "upcast_healing_dice",
                "auto_hit",
                "resolution_kind",
                "rule_plan",
            )
            for known_spell in known_spells:
                metadata = dict(known_spell.metadata_json or {})
                raw_character_spell = metadata.get("character_spell")
                source = dict(raw_character_spell) if isinstance(raw_character_spell, dict) else {}
                source.setdefault("name", known_spell.name)
                for key in spell_fields:
                    if source.get(key) in (None, "") and metadata.get(key) not in (None, ""):
                        source[key] = metadata[key]
                source_id = str(source.get("source_record_id") or metadata.get("source_record_id") or "")
                for collection_name in ("actions", "spells"):
                    collection = result[collection_name]
                    for index, item in enumerate(collection):
                        if not isinstance(item, dict):
                            continue
                        item_id = str(item.get("source_record_id") or "")
                        matches_source = bool(source_id) and item_id == source_id
                        matches_name = str(item.get("name") or "") == known_spell.name
                        if not (matches_source or matches_name):
                            continue
                        merged = dict(item)
                        for key in spell_fields:
                            # KnownSpell 的结构化元数据是法术卡的权威来源。
                            # 老角色动作里可能残留由职业模板生成的占位值（例如所有法术
                            # 都被写成 3d6 psychic），不能因为它“非空”就继续保留。
                            if source.get(key) not in (None, ""):
                                merged[key] = source[key]
                        collection[index] = enrich_spell_action(
                            merged,
                            spellcasting=result.get("spellcasting"),
                        )
            result["wallet"] = (
                {
                    "id": wallet.id,
                    "name": wallet.name,
                    "copper": wallet.copper,
                    "gp": wallet.copper / 100,
                    "version": wallet.version,
                }
                if wallet is not None
                else None
            )
            # A player may see the conditions on their own character, but not
            # arbitrary DM notes.  The structured source/duration/status data
            # is enough to make poison, disease and environmental effects
            # actionable from the player view.
            result["conditions"] = [
                {
                    "id": condition.id,
                    "name": condition.condition_name,
                    "source": condition.source,
                    "duration": condition.duration,
                    "status": str(dict(condition.details or {}).get("status") or "active"),
                    "details": {
                        key: value
                        for key, value in dict(condition.details or {}).items()
                        if key in {"affliction_type", "status", "stage", "effect_kind"}
                    },
                    "version": condition.version,
                }
                for condition in session.scalars(
                    select(CharacterCondition)
                    .where(CharacterCondition.character_id == character_id)
                    .order_by(CharacterCondition.created_at, CharacterCondition.id)
                ).all()
            ]
            equipment_rows = session.scalars(
                select(EquipmentInstance)
                .where(EquipmentInstance.character_id == character_id)
                .order_by(EquipmentInstance.created_at, EquipmentInstance.id)
            ).all()
            active_attunements = set(
                session.scalars(
                    select(Attunement.equipment_instance_id).where(
                        Attunement.character_id == character_id,
                        Attunement.status == "active",
                    )
                ).all()
            )
            result["equipment_assets"] = [
                {
                    **serialize(row),
                    "attuned": row.id in active_attunements,
                    "slot": row.metadata_json.get("equipment_slot"),
                    "profile": equipment_profile(
                        row.name,
                        row.category,
                        dict(row.metadata_json),
                        row.armor_class,
                    ),
                }
                for row in equipment_rows
            ]
            result["active_attunements"] = len(active_attunements)
            return result

    def submit_action(
        self, campaign_id: str, data: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        if str(data.get("action_type") or "") in self._INTERNAL_ACTION_TYPES:
            raise ValueError("action type is reserved for the combat engine")
        idempotency_key = str(data.get("idempotency_key") or "")
        if idempotency_key.startswith(self._INTERNAL_IDEMPOTENCY_PREFIXES):
            raise ValueError("idempotency key is reserved for the combat engine")
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            existing = session.scalar(
                select(PlayerActionRequest).where(
                    PlayerActionRequest.campaign_id == campaign_id,
                    PlayerActionRequest.idempotency_key == data["idempotency_key"],
                )
            )
            if existing:
                return serialize(existing)
            character = self._character(session, campaign_id, data["character_id"])
            if character.version != data["character_version"]:
                raise VersionConflict(
                    "character", character.id, data["character_version"], character.version
                )
            item = PlayerActionRequest(campaign_id=campaign_id, **data)
            session.add(item)
            session.flush()
            self._audit(session, campaign_id, "player_request", item, request_id)
            return serialize(item)

    def list_requests(self, campaign_id: str, status: str | None = None) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            query = select(PlayerActionRequest).where(
                PlayerActionRequest.campaign_id == campaign_id
            )
            if status:
                query = query.where(PlayerActionRequest.status == status)
            return [
                serialize(item)
                for item in session.scalars(
                    query.order_by(PlayerActionRequest.created_at.desc())
                ).all()
            ]

    def _resolve_rest_action(
        self,
        campaign_id: str,
        request_id_value: str,
        expected_version: int,
        dm_note: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            now = datetime.now(UTC)
            claimed = cast(
                CursorResult[Any],
                session.execute(
                    update(PlayerActionRequest)
                    .where(
                        PlayerActionRequest.id == request_id_value,
                        PlayerActionRequest.campaign_id == campaign_id,
                        PlayerActionRequest.status == "pending",
                        PlayerActionRequest.version == expected_version,
                    )
                    .values(
                        status="accepted",
                        version=PlayerActionRequest.version + 1,
                        updated_at=now,
                    )
                ),
            )
            if claimed.rowcount != 1:
                item = session.get(PlayerActionRequest, request_id_value)
                if item is None or item.campaign_id != campaign_id:
                    raise StateNotFoundError("player action request not found")
                if item.status != "pending":
                    return serialize(item)
                raise VersionConflict(
                    "player_action_request", item.id, expected_version, item.version
                )

            item = session.get(PlayerActionRequest, request_id_value)
            if item is None or item.campaign_id != campaign_id:
                raise StateNotFoundError("player action request not found")
            payload = dict(item.payload_json or {})
            request_message = item.message or "玩家申请休息"
            if payload.get("schema_version") != "1.0":
                raise ValueError("unsupported rest request schema")
            rest_data = {
                "rest_type": payload.get("rest_type"),
                "duration_minutes": payload.get("duration_minutes"),
                "interrupted": False,
                "interruption_reason": None,
                "fallback_to_short_rest": False,
                "participants": payload.get("participants") or [],
                "notes": f"玩家申请：{request_message}",
                "dm_override_reason": None,
            }
            result = self.rest.confirm_in_session(
                session,
                campaign_id,
                {
                    **rest_data,
                    "idempotency_key": f"player-rest:{request_id_value}",
                },
                require_preview_token=False,
            )
            character = self._character(session, campaign_id, item.character_id)
            item.payload_json = {
                **payload,
                "phase": "confirmed",
                "rest_result": result,
                "dm_note": dm_note,
            }
            item.dm_note = dm_note
            item.resolved_at = now
            item.updated_at = now
            rest_label = "短休" if payload.get("rest_type") == "short" else "长休"
            session.add(
                Event(
                    campaign_id=campaign_id,
                    event_type="rest",
                    title=f"{character.name}完成{rest_label}",
                    description=(
                        f"DM 批准了{character.name}的{rest_label}申请，"
                        "休息结算已写入角色状态。"
                    ),
                    visibility="public",
                    metadata_json={
                        "player_action_request_id": item.id,
                        "rest_type": payload.get("rest_type"),
                        "rest_record_id": result.get("rest_record_id"),
                    },
                )
            )
            session.flush()
            self._audit(session, campaign_id, "player_request_accepted", item, request_id)
            return serialize(item)

    @staticmethod
    def _apply_scene_object_operation(
        session: Session,
        *,
        proposal: dict[str, Any],
        scene_id: str,
    ) -> dict[str, Any]:
        """Apply one whitelisted, DM-confirmed exploration spell operation.

        The player payload is intentionally not a generic patch document.  It can
        name only a small operation whose write shape is fixed here, so an accepted
        request cannot be turned into an arbitrary SceneObject mutation.
        """
        operation = str(proposal.get("operation") or "")
        if operation not in {
            "unlock_door",
            "lock_door",
            "illuminate_object",
            "darken_object",
            "mark_repaired",
        }:
            raise ValueError("不支持自动执行的场景物体操作")
        object_id = str(proposal.get("object_id") or "")
        if not object_id:
            raise ValueError("自动执行缺少目标物体")
        expected_version = proposal.get("expected_object_version")
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 1
        ):
            raise ValueError("自动执行缺少有效的物体版本")
        scene_object = session.get(SceneObject, object_id)
        if (
            scene_object is None
            or scene_object.scene_id != scene_id
            or scene_object.visibility != "public"
        ):
            raise ValueError("待更新的 Scene 物体已不存在")
        if scene_object.version != expected_version:
            raise ValueError("物体状态已变化，请玩家重新提交行动")
        expected_type = str(proposal.get("expected_object_type") or "")
        if not expected_type or scene_object.object_type != expected_type:
            raise ValueError("目标物体类型已变化，请玩家重新提交行动")
        expected_state = proposal.get("expected_state")
        if not isinstance(expected_state, str) or scene_object.state != expected_state:
            raise ValueError("物体状态已变化，请玩家重新提交行动")

        interaction = dict(scene_object.interaction_json or {})
        metadata = dict(scene_object.metadata_json or {})
        if operation in {"unlock_door", "lock_door"}:
            if scene_object.object_type != "door":
                raise ValueError("只有门可以自动改变锁定状态")
            expected_locked = proposal.get("expected_locked")
            if not isinstance(expected_locked, bool):
                raise ValueError("自动门锁操作缺少锁定状态")
            if bool(interaction.get("locked")) != expected_locked:
                raise ValueError("门锁状态已变化，请玩家重新提交行动")
            if operation == "unlock_door":
                interaction.update(
                    locked=False,
                    lock_state="unlocked",
                    arcane_locked=False,
                )
            else:
                if scene_object.state != "closed":
                    raise ValueError("秘法锁只能自动处理关闭的门")
                interaction.update(
                    locked=True,
                    lock_state="arcane_locked",
                    arcane_locked=True,
                )
            scene_object.interaction_json = interaction
        elif operation == "illuminate_object":
            raw_illumination = proposal.get("illumination")
            illumination = dict(raw_illumination) if isinstance(raw_illumination, dict) else {}
            mode = str(illumination.get("mode") or "bright_light")
            bright_radius = illumination.get("bright_radius_ft", 20)
            dim_radius = illumination.get("dim_radius_ft", 20)
            if mode != "bright_light" or not all(
                isinstance(value, int) and 0 <= value <= 1_000
                for value in (bright_radius, dim_radius)
            ):
                raise ValueError("光照参数无效")
            metadata["illumination"] = {
                "mode": mode,
                "bright_radius_ft": bright_radius,
                "dim_radius_ft": dim_radius,
            }
            scene_object.metadata_json = metadata
        elif operation == "darken_object":
            raw_illumination = proposal.get("illumination")
            illumination = dict(raw_illumination) if isinstance(raw_illumination, dict) else {}
            radius = illumination.get("radius_ft", 15)
            if not isinstance(radius, int) or not 0 <= radius <= 1_000:
                raise ValueError("黑暗范围参数无效")
            metadata["illumination"] = {"mode": "magical_darkness", "radius_ft": radius}
            scene_object.metadata_json = metadata
        else:
            metadata["repaired"] = True
            scene_object.metadata_json = metadata

        scene_object.version += 1
        scene_object.updated_at = datetime.now(UTC)
        result: dict[str, Any] = {
            "applied": True,
            "operation": operation,
            "object_id": scene_object.id,
            "object_version": scene_object.version,
            "state": scene_object.state,
        }
        if operation in {"unlock_door", "lock_door"}:
            result["locked"] = bool(interaction.get("locked"))
            result["lock_state"] = interaction.get("lock_state")
        elif operation in {"illuminate_object", "darken_object"}:
            result["illumination"] = dict(metadata["illumination"])
        else:
            result["repaired"] = True
        return result

    def resolve_action(
        self,
        campaign_id: str,
        request_id_value: str,
        expected_version: int,
        status: str,
        dm_note: str | None,
        request_id: str,
        *,
        attack_total: int | None = None,
        damage_total: int | None = None,
        critical_hit: bool = False,
    ) -> dict[str, Any]:
        if status == "accepted":
            with Session(self.engine) as session:
                item = session.get(PlayerActionRequest, request_id_value)
                if item is not None and item.action_type == "rest_request":
                    return self._resolve_rest_action(
                        campaign_id,
                        request_id_value,
                        expected_version,
                        dm_note,
                        request_id,
                    )
                if item is not None and item.action_type == "opportunity_attack":
                    return self._resolve_opportunity_action(
                        campaign_id,
                        request_id_value,
                        expected_version,
                        dm_note,
                        request_id,
                        attack_total=attack_total,
                        damage_total=damage_total,
                        critical_hit=critical_hit,
                    )
        with Session(self.engine) as session, session.begin():
            item = session.get(PlayerActionRequest, request_id_value)
            if item is None or item.campaign_id != campaign_id:
                raise StateNotFoundError("player action request not found")
            if item.version != expected_version:
                raise VersionConflict(
                    "player_action_request", item.id, expected_version, item.version
                )
            if item.status != "pending":
                return serialize(item)  # confirmation is idempotent
            if status == "accepted" and item.action_type == "noncombat_rule":
                payload = dict(item.payload_json or {})
                if payload.get("schema_version") != "1.0":
                    raise ValueError("unsupported noncombat action schema")
                if payload.get("phase") != "resolved":
                    raise ValueError("玩家仍需完成投骰，当前行动不能确认")
                character = self._character(session, campaign_id, item.character_id)
                if character.version != item.character_version:
                    now = datetime.now(UTC)
                    payload["phase"] = "stale"
                    payload["stale"] = {
                        "reason": "character_version_changed",
                        "planned_character_version": item.character_version,
                        "current_character_version": character.version,
                        "detected_at": now.isoformat(),
                    }
                    item.payload_json = payload
                    item.status = "stale"
                    item.dm_note = dm_note
                    item.resolved_at = now
                    item.version += 1
                    item.updated_at = now
                    session.flush()
                    self._audit(
                        session,
                        campaign_id,
                        "player_request_stale",
                        item,
                        request_id,
                    )
                    return serialize(item)
                cost = json_dict(payload.get("cost"))
                resource_key = cost.get("resource_key")
                amount = int(cost.get("amount") or 0)
                if resource_key and amount > 0:
                    resources = dict(character.resources or {})
                    resource = resources.get(str(resource_key))
                    if not isinstance(resource, dict):
                        raise ValueError("角色卡缺少行动所需资源")
                    updated = dict(resource)
                    current = int(updated.get("current") or 0)
                    if current < amount:
                        raise ValueError("角色资源已变化且不足，不能确认该行动")
                    updated["current"] = current - amount
                    resources[str(resource_key)] = updated
                    character.resources = resources
                    character.version += 1
                    character.updated_at = datetime.now(UTC)
                resolution = json_dict(payload.get("resolution"))
                proposal = json_dict(payload.get("proposal"))
                automation = json_dict(payload.get("automation"))
                automation_result: dict[str, Any] | None = None
                if resolution.get("success") is not False and proposal.get("kind") == "object_state":
                    object_id = str(proposal.get("object_id") or "")
                    scene_object = session.get(SceneObject, object_id)
                    scene_data = json_dict(payload.get("scene"))
                    if (
                        scene_object is None
                        or scene_object.scene_id != scene_data.get("id")
                        or scene_object.visibility != "public"
                    ):
                        raise ValueError("待更新的 Scene 物体已不存在")
                    if scene_object.state != proposal.get("from_state"):
                        raise ValueError("物体状态已变化，请玩家重新提交行动")
                    scene_object.state = str(proposal["to_state"])
                    scene_object.version += 1
                    scene_object.updated_at = datetime.now(UTC)
                    automation_result = {
                        "applied": True,
                        "operation": "set_object_state",
                        "object_id": scene_object.id,
                        "object_version": scene_object.version,
                        "state": scene_object.state,
                    }
                elif (
                    resolution.get("success") is not False
                    and proposal.get("kind") == "scene_object_operation"
                ):
                    if (
                        automation.get("mode") != "dm_confirmed_object_operation"
                        or automation.get("apply_on_dm_accept") is not True
                    ):
                        raise ValueError("自动场景操作缺少 DM 确认执行标记")
                    automation_result = self._apply_scene_object_operation(
                        session,
                        proposal=proposal,
                        scene_id=str(json_dict(payload.get("scene")).get("id") or ""),
                    )
                if automation:
                    if automation_result is not None:
                        automation.update(status="applied", result=automation_result)
                    elif automation.get("status") != "failed":
                        automation["status"] = "dm_confirmed"
                    payload["automation"] = automation
                actor = json_dict(payload.get("actor"))
                action = json_dict(payload.get("action"))
                target = json_dict(payload.get("target"))
                summary = str(proposal.get("summary") or "行动已由 DM 确认。")
                event = Event(
                    campaign_id=campaign_id,
                    event_type="player_noncombat_action",
                    title=f"{actor.get('name', '玩家')}：{action.get('name', '非战斗行动')}",
                    description=f"目标：{target.get('name', '当前区域')}。{summary}",
                    visibility="public",
                    metadata_json={
                        "scene_id": json_dict(payload.get("scene")).get("id"),
                        "player_action_request_id": item.id,
                        "resolution": resolution,
                        "proposal": proposal,
                        "automation": automation,
                        "dm_note": dm_note,
                        "planned_character_version": item.character_version,
                        "confirmed_character_version": character.version,
                    },
                )
                session.add(event)
                session.flush()
                payload["phase"] = "dm_confirmed"
                payload["confirmation"] = {
                    "event_id": event.id,
                    "dm_note": dm_note,
                    "planned_character_version": item.character_version,
                    "confirmed_character_version": character.version,
                    "confirmed_at": datetime.now(UTC).isoformat(),
                }
                item.payload_json = payload
            if status == "accepted" and item.action_type == "site_level_transition":
                payload = dict(item.payload_json or {})
                if payload.get("schema_version") != "1.0":
                    raise ValueError("unsupported site transition schema")
                from_scene_id = str(payload.get("from_scene_id") or "")
                target_scene_id = str(payload.get("target_scene_id") or "")
                target_scene = session.get(Scene, target_scene_id)
                room = session.scalar(
                    select(PlayerRoom).where(PlayerRoom.campaign_id == campaign_id)
                )
                if (
                    target_scene is None
                    or target_scene.campaign_id != campaign_id
                    or room is None
                    or room.current_scene_id != from_scene_id
                ):
                    raise ValueError("楼层或当前场景已经变化，请玩家重新申请")
                room.current_scene_id = target_scene.id
                room.current_combat_id = None
                room.version += 1
                room.updated_at = datetime.now(UTC)
                session.add(
                    Event(
                        campaign_id=campaign_id,
                        event_type="site_level_transition",
                        title=f"队伍进入「{target_scene.name}」",
                        description=(
                            f"DM 已批准玩家从当前楼层前往{payload.get('target_level_name') or target_scene.name}。"
                        ),
                        visibility="public",
                        metadata_json={
                            "player_action_request_id": item.id,
                            "from_scene_id": from_scene_id,
                            "target_scene_id": target_scene.id,
                        },
                    )
                )
            item.status, item.dm_note, item.resolved_at, item.version, item.updated_at = (
                status,
                dm_note,
                datetime.now(UTC),
                item.version + 1,
                datetime.now(UTC),
            )
            session.flush()
            self._audit(session, campaign_id, f"player_request_{status}", item, request_id)
            return serialize(item)

    def resolve_post_hit_rider(
        self,
        campaign_id: str,
        request_id: str,
        expected_version: int,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        return CombatEngineService(self.engine).resolve_post_hit_rider_request(
            campaign_id,
            request_id,
            expected_version=expected_version,
            inputs=inputs,
        )

    def _resolve_opportunity_action(
        self,
        campaign_id: str,
        request_id_value: str,
        expected_version: int,
        dm_note: str | None,
        request_id: str,
        *,
        attack_total: int | None,
        damage_total: int | None,
        critical_hit: bool,
    ) -> dict[str, Any]:
        if attack_total is None or damage_total is None:
            raise ValueError("确认借机攻击前必须填写攻击总值和伤害骰总值")
        with Session(self.engine) as session:
            item = session.get(PlayerActionRequest, request_id_value)
            if item is None or item.campaign_id != campaign_id:
                raise StateNotFoundError("player action request not found")
            if item.version != expected_version:
                raise VersionConflict("player_action_request", item.id, expected_version, item.version)
            if item.status != "pending":
                return serialize(item)
            payload = json_dict(item.payload_json)
            source_id = str(payload.get("source_combatant_id") or "")
            target_id = str(payload.get("target_combatant_id") or "")
            combat_id = str(payload.get("combat_id") or "")
            source = session.get(Combatant, source_id)
            target = session.get(Combatant, target_id)
            if source is None or target is None or source.combat_id != combat_id or target.combat_id != combat_id:
                raise StateNotFoundError("借机攻击的战斗单位已不存在")
            if not source.reaction_available:
                raise ValueError("该敌人的反应已经被使用")
            target_version = target.version
            action_name = str(
                payload.get("source_action_name") or f"借机攻击 · {source.display_name}"
            )
            damage_type = str(payload.get("damage_type") or "slashing")
            hit = critical_hit or attack_total >= target.armor_class
        amount = int(damage_total) if hit else 0
        result = CombatEngineService(self.engine).confirm(
            campaign_id,
            combat_id,
            CombatActionCommand(
                action_type="damage",
                target_combatant_id=target_id,
                target_version=target_version,
                actor_combatant_id=source_id,
                action_cost="none",
                action_name=f"借机攻击 · {action_name}",
                resolution_note=(
                    f"{action_name}；攻击总值 {attack_total} 对抗 AC {target.armor_class}："
                    f"{'命中' if hit else '未命中'}；伤害骰 {damage_total}"
                ),
                amount=amount,
                damage_type=damage_type,
                critical_hit=critical_hit,
            ),
            idempotency_key=f"{request_id}:opportunity-resolution",
        )
        with Session(self.engine) as session, session.begin():
            item = session.get(PlayerActionRequest, request_id_value)
            source = session.get(Combatant, source_id)
            if item is None or source is None or item.status != "pending":
                return serialize(item) if item is not None else result
            source.reaction_available = False
            source.version += 1
            source.updated_at = datetime.now(UTC)
            item.status = "accepted"
            item.dm_note = dm_note
            item.payload_json = {
                **dict(item.payload_json or {}),
                "phase": "confirmed",
                "attack_total": attack_total,
                "damage_total": damage_total,
                "hit": hit,
                "damage_result": result,
            }
            item.resolved_at = datetime.now(UTC)
            item.updated_at = datetime.now(UTC)
            self._audit(session, campaign_id, "player_request_accepted", item, request_id)
            session.flush()
            return serialize(item)

    def list_handouts(self, campaign_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            return [
                serialize(x)
                for x in session.scalars(
                    select(Handout)
                    .where(Handout.campaign_id == campaign_id)
                    .order_by(Handout.sort_order, Handout.id)
                ).all()
            ]

    def create_handout(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            item = Handout(campaign_id=campaign_id, **data)
            session.add(item)
            session.flush()
            return serialize(item)

    def update_handout(
        self, campaign_id: str, handout_id: str, data: dict[str, Any], version: int
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            item = session.get(Handout, handout_id)
            if item is None or item.campaign_id != campaign_id:
                raise StateNotFoundError("handout not found")
            if item.version != version:
                raise VersionConflict("handout", handout_id, version, item.version)
            for key, value in data.items():
                setattr(item, key, value)
            item.version += 1
            item.updated_at = datetime.now(UTC)
            session.flush()
            return serialize(item)
