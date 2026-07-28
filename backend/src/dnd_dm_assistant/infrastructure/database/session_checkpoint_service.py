from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Campaign,
    Character,
    CharacterCondition,
    Combat,
    Combatant,
    CombatEffect,
    CombatReinforcement,
    DeathSave,
    MonsterInstance,
    OperationTransaction,
    ResourcePool,
    Scene,
    SceneObject,
    SceneParticipant,
    SceneToken,
)
from dnd_dm_assistant.infrastructure.database.session_checkpoint_models import (
    CampaignSessionState,
    SessionCheckpoint,
)

CHECKPOINT_SCHEMA_VERSION = 1


class CheckpointConflictError(ValueError):
    def __init__(self, message: str, conflicts: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.conflicts = conflicts


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _row(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version,
        **{field: _json_safe(getattr(row, field)) for field in fields},
    }


def _fingerprint(snapshot: dict[str, Any]) -> str:
    raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


CHARACTER_FIELDS = (
    "experience",
    "hp",
    "max_hp",
    "max_hp_reduction",
    "ability_score_reductions",
    "death_saves",
    "inventory",
    "equipment",
    "resources",
)
NPC_FIELDS = ("hp", "max_hp", "status", "location_id", "equipment")
MONSTER_FIELDS = ("hp", "max_hp", "notes")
CONDITION_FIELDS = ("character_id", "condition_name", "source", "duration", "notes", "details")
RESOURCE_FIELDS = (
    "campaign_id",
    "character_id",
    "key",
    "label",
    "category",
    "current",
    "maximum",
    "recovery_timing",
    "recovery_amount",
    "die_size",
    "source_record_id",
    "rule_key",
    "metadata_json",
)
PARTICIPANT_FIELDS = ("scene_id", "entity_type", "entity_id", "role", "visible", "notes")
TOKEN_FIELDS = (
    "scene_id",
    "entity_type",
    "entity_id",
    "label",
    "row",
    "col",
    "size_cells",
    "elevation_ft",
    "visible",
    "metadata_json",
)
OBJECT_FIELDS = (
    "scene_id",
    "object_type",
    "label",
    "row",
    "col",
    "width_cells",
    "height_cells",
    "state",
    "visibility",
    "interaction_json",
    "metadata_json",
)
COMBAT_FIELDS = (
    "scene_id",
    "name",
    "status",
    "round_number",
    "current_turn_index",
    "difficulty",
    "base_xp",
    "difficulty_adjustments",
    "xp_awarded",
    "started_at",
    "ended_at",
)
COMBATANT_FIELDS = (
    "combat_id",
    "entity_type",
    "entity_id",
    "display_name",
    "initiative",
    "armor_class",
    "hp",
    "max_hp",
    "temporary_hp",
    "max_hp_reduction",
    "damage_resistances",
    "damage_vulnerabilities",
    "damage_immunities",
    "condition_immunities",
    "conditions",
    "concentration",
    "speed_ft",
    "movement_remaining_ft",
    "action_available",
    "bonus_action_available",
    "reaction_available",
    "snapshot_json",
    "is_active",
)
EFFECT_FIELDS = (
    "campaign_id",
    "combat_id",
    "target_combatant_id",
    "source_combatant_id",
    "name",
    "effect_type",
    "details_json",
    "started_round",
    "duration_unit",
    "duration_value",
    "ends_round",
    "requires_concentration",
    "save_dc",
    "save_ability",
    "trigger_timing",
    "status",
    "ended_at",
    "end_reason",
)
DEATH_SAVE_FIELDS = (
    "combatant_id",
    "successes",
    "failures",
    "stable",
    "dead",
    "pending_death_confirmation",
    "last_roll",
)
REINFORCEMENT_FIELDS = (
    "combat_id",
    "entity_type",
    "entity_id",
    "target_round",
    "quantity",
    "reason",
    "deployed",
    "deployed_at",
)


class SessionCheckpointService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError(f"campaign {campaign_id} was not found")
        return campaign

    @staticmethod
    def _checkpoint(
        session: Session, campaign_id: str, checkpoint_id: str
    ) -> SessionCheckpoint:
        checkpoint = session.scalar(
            select(SessionCheckpoint).where(
                SessionCheckpoint.id == checkpoint_id,
                SessionCheckpoint.campaign_id == campaign_id,
            )
        )
        if checkpoint is None:
            raise StateNotFoundError(f"session checkpoint {checkpoint_id} was not found")
        return checkpoint

    @staticmethod
    def _scene(session: Session, campaign_id: str, scene_id: str | None) -> Scene | None:
        if scene_id is None:
            return None
        scene = session.scalar(
            select(Scene).where(Scene.id == scene_id, Scene.campaign_id == campaign_id)
        )
        if scene is None:
            raise StateNotFoundError(f"scene {scene_id} was not found in campaign")
        return scene

    @staticmethod
    def _combat(
        session: Session,
        campaign_id: str,
        scene_id: str | None,
        combat_id: str | None,
    ) -> Combat | None:
        if combat_id:
            combat = session.scalar(
                select(Combat).where(
                    Combat.id == combat_id,
                    Combat.campaign_id == campaign_id,
                )
            )
            if combat is None:
                raise StateNotFoundError(f"combat {combat_id} was not found in campaign")
            return combat
        query = select(Combat).where(
            Combat.campaign_id == campaign_id,
            Combat.status == "active",
        )
        if scene_id:
            query = query.where(Combat.scene_id == scene_id)
        return session.scalar(query.order_by(Combat.created_at.desc(), Combat.id.desc()).limit(1))

    def _capture(
        self,
        session: Session,
        campaign: Campaign,
        *,
        scene_id: str | None,
        active_combat_id: str | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        scene = self._scene(session, campaign.id, scene_id)
        combat = self._combat(session, campaign.id, scene_id, active_combat_id)
        participants = (
            list(
                session.scalars(
                    select(SceneParticipant)
                    .where(SceneParticipant.scene_id == scene.id)
                    .order_by(SceneParticipant.created_at, SceneParticipant.id)
                )
            )
            if scene
            else []
        )
        entity_refs = {(row.entity_type, row.entity_id) for row in participants}
        combatants = (
            list(
                session.scalars(
                    select(Combatant)
                    .where(Combatant.combat_id == combat.id)
                    .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
                )
            )
            if combat
            else []
        )
        entity_refs.update(
            (row.entity_type, row.entity_id)
            for row in combatants
            if row.entity_id and row.entity_type in {"character", "npc", "monster"}
        )

        characters: list[Character] = []
        npcs: list[NPC] = []
        monsters: list[MonsterInstance] = []
        for entity_type, entity_id in sorted(entity_refs):
            if entity_type == "character":
                character = session.get(Character, entity_id)
                if character is None or character.campaign_id != campaign.id:
                    raise StateNotFoundError(
                        f"character {entity_id} referenced by the session no longer exists"
                    )
                characters.append(character)
                continue
            if entity_type == "npc":
                npc = session.get(NPC, entity_id)
                if npc is None or npc.campaign_id != campaign.id:
                    raise StateNotFoundError(
                        f"npc {entity_id} referenced by the session no longer exists"
                    )
                npcs.append(npc)
                continue
            if entity_type == "monster":
                monster = session.get(MonsterInstance, entity_id)
                if monster is None or monster.campaign_id != campaign.id:
                    raise StateNotFoundError(
                        f"monster {entity_id} referenced by the session no longer exists"
                    )
                monsters.append(monster)

        character_ids = [row.id for row in characters]
        conditions = (
            list(
                session.scalars(
                    select(CharacterCondition)
                    .where(CharacterCondition.character_id.in_(character_ids))
                    .order_by(CharacterCondition.character_id, CharacterCondition.created_at)
                )
            )
            if character_ids
            else []
        )
        resources = (
            list(
                session.scalars(
                    select(ResourcePool)
                    .where(ResourcePool.character_id.in_(character_ids))
                    .order_by(ResourcePool.character_id, ResourcePool.key)
                )
            )
            if character_ids
            else []
        )
        tokens = (
            list(
                session.scalars(
                    select(SceneToken)
                    .where(SceneToken.scene_id == scene.id)
                    .order_by(SceneToken.created_at, SceneToken.id)
                )
            )
            if scene
            else []
        )
        objects = (
            list(
                session.scalars(
                    select(SceneObject)
                    .where(SceneObject.scene_id == scene.id)
                    .order_by(SceneObject.created_at, SceneObject.id)
                )
            )
            if scene
            else []
        )
        combatant_ids = [row.id for row in combatants]
        effects = (
            list(
                session.scalars(
                    select(CombatEffect)
                    .where(CombatEffect.combat_id == combat.id)
                    .order_by(CombatEffect.created_at, CombatEffect.id)
                )
            )
            if combat
            else []
        )
        death_saves = (
            list(
                session.scalars(
                    select(DeathSave)
                    .where(DeathSave.combatant_id.in_(combatant_ids))
                    .order_by(DeathSave.created_at, DeathSave.id)
                )
            )
            if combatant_ids
            else []
        )
        reinforcements = (
            list(
                session.scalars(
                    select(CombatReinforcement)
                    .where(CombatReinforcement.combat_id == combat.id)
                    .order_by(CombatReinforcement.created_at, CombatReinforcement.id)
                )
            )
            if combat
            else []
        )

        snapshot: dict[str, Any] = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "campaign": {
                "id": campaign.id,
                "version": campaign.version,
                "current_location_id": campaign.current_location_id,
                "current_time": _json_safe(campaign.current_time),
            },
            "scene": (
                {
                    "id": scene.id,
                    "version": scene.version,
                    "status": scene.status,
                    "location_id": scene.location_id,
                }
                if scene
                else None
            ),
            "participants": [_row(item, PARTICIPANT_FIELDS) for item in participants],
            "tokens": [_row(item, TOKEN_FIELDS) for item in tokens],
            "objects": [_row(item, OBJECT_FIELDS) for item in objects],
            "characters": [_row(item, CHARACTER_FIELDS) for item in characters],
            "character_conditions": [_row(item, CONDITION_FIELDS) for item in conditions],
            "resource_pools": [_row(item, RESOURCE_FIELDS) for item in resources],
            "npcs": [_row(item, NPC_FIELDS) for item in npcs],
            "monsters": [_row(item, MONSTER_FIELDS) for item in monsters],
            "combat": _row(combat, COMBAT_FIELDS) if combat else None,
            "combatants": [_row(item, COMBATANT_FIELDS) for item in combatants],
            "combat_effects": [_row(item, EFFECT_FIELDS) for item in effects],
            "death_saves": [_row(item, DEATH_SAVE_FIELDS) for item in death_saves],
            "reinforcements": [_row(item, REINFORCEMENT_FIELDS) for item in reinforcements],
        }
        dependencies: list[dict[str, Any]] = [
            {"type": "campaign", "id": campaign.id, "version": campaign.version, "required": True}
        ]
        for kind, rows, required in (
            ("scene", [scene] if scene else [], True),
            ("character", characters, True),
            ("npc", npcs, True),
            ("monster", monsters, True),
            ("combat", [combat] if combat else [], True),
            ("participant", participants, False),
            ("token", tokens, False),
            ("object", objects, False),
            ("combatant", combatants, False),
            ("condition", conditions, False),
            ("resource_pool", resources, False),
        ):
            dependencies.extend(
                {
                    "type": kind,
                    "id": item.id,
                    "version": item.version,
                    "required": required,
                }
                for item in rows
            )
        return snapshot, dependencies

    @staticmethod
    def _summary(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "scene_id": (snapshot.get("scene") or {}).get("id"),
            "active_combat_id": (snapshot.get("combat") or {}).get("id"),
            "participant_count": len(snapshot.get("participants", [])),
            "entity_count": sum(
                len(snapshot.get(key, [])) for key in ("characters", "npcs", "monsters")
            ),
            "resource_pool_count": len(snapshot.get("resource_pools", [])),
            "combatant_count": len(snapshot.get("combatants", [])),
        }

    @classmethod
    def _payload(
        cls, checkpoint: SessionCheckpoint, *, include_snapshot: bool = False
    ) -> dict[str, Any]:
        payload = {
            "id": checkpoint.id,
            "campaign_id": checkpoint.campaign_id,
            "name": checkpoint.name,
            "schema_version": checkpoint.schema_version,
            "status": checkpoint.status,
            "scene_id": checkpoint.scene_id,
            "active_combat_id": checkpoint.active_combat_id,
            "base_campaign_version": checkpoint.base_campaign_version,
            "source_fingerprint": checkpoint.source_fingerprint,
            "entry_count": len(checkpoint.entries_json),
            **cls._summary(checkpoint.snapshot_json),
            "restore_count": checkpoint.restore_count,
            "restored_at": checkpoint.restored_at,
            "created_at": checkpoint.created_at,
            "updated_at": checkpoint.updated_at,
            "version": checkpoint.version,
        }
        if include_snapshot:
            payload["entries"] = checkpoint.entries_json
            payload["snapshot"] = checkpoint.snapshot_json
            payload["dependencies"] = checkpoint.dependencies_json
        return payload

    def create(
        self,
        campaign_id: str,
        *,
        name: str,
        scene_id: str | None,
        active_combat_id: str | None,
        entries: list[dict[str, Any]],
        expected_campaign_version: int | None,
        notes: str | None,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            campaign = self._campaign(session, campaign_id)
            if (
                expected_campaign_version is not None
                and campaign.version != expected_campaign_version
            ):
                raise VersionConflict(
                    "campaign",
                    campaign.id,
                    expected_campaign_version,
                    campaign.version,
                )
            state = session.scalar(
                select(CampaignSessionState).where(
                    CampaignSessionState.campaign_id == campaign_id
                )
            )
            resolved_scene_id = scene_id if scene_id is not None else (
                state.current_scene_id if state else None
            )
            resolved_combat_id = active_combat_id if active_combat_id is not None else (
                state.active_combat_id if state else None
            )
            snapshot, dependencies = self._capture(
                session,
                campaign,
                scene_id=resolved_scene_id,
                active_combat_id=resolved_combat_id,
            )
            checkpoint = SessionCheckpoint(
                campaign_id=campaign_id,
                name=name.strip(),
                schema_version=CHECKPOINT_SCHEMA_VERSION,
                status="active",
                scene_id=(snapshot.get("scene") or {}).get("id"),
                active_combat_id=(snapshot.get("combat") or {}).get("id"),
                base_campaign_version=campaign.version,
                source_fingerprint=_fingerprint(snapshot),
                entries_json=entries,
                snapshot_json=snapshot,
                dependencies_json=dependencies,
                notes=notes,
            )
            session.add(checkpoint)
            session.flush()
            return self._payload(checkpoint, include_snapshot=True)

    def list_checkpoints(
        self, campaign_id: str, *, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            query = select(SessionCheckpoint).where(
                SessionCheckpoint.campaign_id == campaign_id
            )
            if not include_archived:
                query = query.where(SessionCheckpoint.status == "active")
            rows = session.scalars(
                query.order_by(SessionCheckpoint.created_at.desc(), SessionCheckpoint.id.desc())
            )
            return [self._payload(row) for row in rows]

    def get(self, campaign_id: str, checkpoint_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            return self._payload(
                self._checkpoint(session, campaign_id, checkpoint_id),
                include_snapshot=True,
            )

    def current_state(self, campaign_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            state = session.scalar(
                select(CampaignSessionState).where(
                    CampaignSessionState.campaign_id == campaign_id
                )
            )
            if state is None:
                return {
                    "campaign_id": campaign_id,
                    "current_scene_id": None,
                    "active_combat_id": None,
                    "restored_checkpoint_id": None,
                    "entries": [],
                    "version": 0,
                }
            return {
                "campaign_id": campaign_id,
                "current_scene_id": state.current_scene_id,
                "active_combat_id": state.active_combat_id,
                "restored_checkpoint_id": state.restored_checkpoint_id,
                "entries": state.entries_json,
                "version": state.version,
                "updated_at": state.updated_at,
            }

    @staticmethod
    def _dependency_model(kind: str) -> type[Any] | None:
        return {
            "campaign": Campaign,
            "scene": Scene,
            "character": Character,
            "npc": NPC,
            "monster": MonsterInstance,
            "combat": Combat,
            "participant": SceneParticipant,
            "token": SceneToken,
            "object": SceneObject,
            "combatant": Combatant,
            "condition": CharacterCondition,
            "resource_pool": ResourcePool,
        }.get(kind)

    def _conflicts(
        self,
        session: Session,
        checkpoint: SessionCheckpoint,
        *,
        expected_campaign_version: int | None,
    ) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
            conflicts.append(
                {
                    "code": "unsupported_schema",
                    "severity": "hard",
                    "expected": CHECKPOINT_SCHEMA_VERSION,
                    "found": checkpoint.schema_version,
                }
            )
        campaign = self._campaign(session, checkpoint.campaign_id)
        if expected_campaign_version is not None and campaign.version != expected_campaign_version:
            conflicts.append(
                {
                    "code": "campaign_version_mismatch",
                    "severity": "version",
                    "entity_type": "campaign",
                    "entity_id": campaign.id,
                    "expected": expected_campaign_version,
                    "found": campaign.version,
                }
            )
        for dependency in checkpoint.dependencies_json:
            if not isinstance(dependency, dict):
                continue
            kind = str(dependency.get("type", ""))
            entity_id = str(dependency.get("id", ""))
            expected = int(dependency.get("version", 0))
            required = bool(dependency.get("required", False))
            model = self._dependency_model(kind)
            if model is None:
                continue
            current = session.get(model, entity_id)
            if current is None:
                if required:
                    conflicts.append(
                        {
                            "code": "missing_dependency",
                            "severity": "hard",
                            "entity_type": kind,
                            "entity_id": entity_id,
                        }
                    )
                continue
            if current.version != expected:
                conflicts.append(
                    {
                        "code": "dependency_version_mismatch",
                        "severity": "version",
                        "entity_type": kind,
                        "entity_id": entity_id,
                        "expected": expected,
                        "found": current.version,
                    }
                )
        return conflicts

    def preview_restore(
        self,
        campaign_id: str,
        checkpoint_id: str,
        *,
        expected_campaign_version: int | None,
        force: bool,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            checkpoint = self._checkpoint(session, campaign_id, checkpoint_id)
            conflicts = self._conflicts(
                session,
                checkpoint,
                expected_campaign_version=expected_campaign_version,
            )
            hard = [item for item in conflicts if item["severity"] == "hard"]
            blocking = hard or ([] if force else conflicts)
            return {
                "checkpoint_id": checkpoint.id,
                "campaign_id": campaign_id,
                "can_restore": not blocking,
                "force_required": bool(conflicts and not hard),
                "conflicts": conflicts,
                "warnings": (
                    ["版本已漂移；强制恢复会覆盖列出的状态变更。"]
                    if conflicts and not hard
                    else []
                ),
                "change_summary": {
                    **self._summary(checkpoint.snapshot_json),
                    "entry_count": len(checkpoint.entries_json),
                },
            }

    @staticmethod
    def _assign(row: Any, data: dict[str, Any], fields: tuple[str, ...]) -> None:
        for field in fields:
            if field in data:
                value = data[field]
                if field in {"started_at", "ended_at", "deployed_at"} and isinstance(value, str):
                    value = datetime.fromisoformat(value)
                setattr(row, field, value)
        row.version += 1

    @classmethod
    def _restore_by_id(
        cls,
        session: Session,
        model: type[Any],
        records: list[dict[str, Any]],
        fields: tuple[str, ...],
        *,
        delete_scope: Any | None = None,
    ) -> None:
        expected_ids = {str(record["id"]) for record in records}
        if delete_scope is not None:
            current_rows = list(session.scalars(delete_scope))
            for current in current_rows:
                if current.id not in expected_ids:
                    session.delete(current)
        for record in records:
            current = session.get(model, str(record["id"]))
            if current is None:
                values = {
                    field: (
                        datetime.fromisoformat(record[field])
                        if field in {"started_at", "ended_at", "deployed_at"}
                        and isinstance(record[field], str)
                        else record[field]
                    )
                    for field in fields
                    if field in record
                }
                current = model(id=str(record["id"]), **values)
                session.add(current)
            else:
                cls._assign(current, record, fields)

    def _apply_snapshot(
        self,
        session: Session,
        checkpoint: SessionCheckpoint,
    ) -> None:
        snapshot = checkpoint.snapshot_json
        campaign = self._campaign(session, checkpoint.campaign_id)
        campaign_state = snapshot["campaign"]
        campaign.current_location_id = campaign_state.get("current_location_id")
        current_time = campaign_state.get("current_time")
        campaign.current_time = (
            datetime.fromisoformat(current_time) if isinstance(current_time, str) else current_time
        )
        campaign.version += 1

        scene_data = snapshot.get("scene")
        if scene_data:
            scene = session.get(Scene, scene_data["id"])
            if scene is None:
                raise CheckpointConflictError(
                    "checkpoint scene is missing",
                    [
                        {
                            "code": "missing_dependency",
                            "severity": "hard",
                            "entity_type": "scene",
                            "entity_id": scene_data["id"],
                        }
                    ],
                )
            scene.status = scene_data["status"]
            scene.version += 1
            scene_id = scene.id
            self._restore_by_id(
                session,
                SceneParticipant,
                list(snapshot.get("participants", [])),
                PARTICIPANT_FIELDS,
                delete_scope=select(SceneParticipant).where(
                    SceneParticipant.scene_id == scene_id
                ),
            )
            self._restore_by_id(
                session,
                SceneToken,
                list(snapshot.get("tokens", [])),
                TOKEN_FIELDS,
                delete_scope=select(SceneToken).where(SceneToken.scene_id == scene_id),
            )
            self._restore_by_id(
                session,
                SceneObject,
                list(snapshot.get("objects", [])),
                OBJECT_FIELDS,
                delete_scope=select(SceneObject).where(SceneObject.scene_id == scene_id),
            )

        for model, key, fields in (
            (Character, "characters", CHARACTER_FIELDS),
            (NPC, "npcs", NPC_FIELDS),
            (MonsterInstance, "monsters", MONSTER_FIELDS),
        ):
            for record in snapshot.get(key, []):
                row = session.get(model, record["id"])
                if row is None:
                    raise CheckpointConflictError(
                        f"checkpoint {key[:-1]} dependency is missing",
                        [
                            {
                                "code": "missing_dependency",
                                "severity": "hard",
                                "entity_type": key[:-1],
                                "entity_id": record["id"],
                            }
                        ],
                    )
                self._assign(row, record, fields)

        character_ids = [row["id"] for row in snapshot.get("characters", [])]
        if character_ids:
            self._restore_by_id(
                session,
                CharacterCondition,
                list(snapshot.get("character_conditions", [])),
                CONDITION_FIELDS,
                delete_scope=select(CharacterCondition).where(
                    CharacterCondition.character_id.in_(character_ids)
                ),
            )
            self._restore_by_id(
                session,
                ResourcePool,
                list(snapshot.get("resource_pools", [])),
                RESOURCE_FIELDS,
                delete_scope=select(ResourcePool).where(
                    ResourcePool.character_id.in_(character_ids)
                ),
            )

        combat_data = snapshot.get("combat")
        if combat_data:
            combat = session.get(Combat, combat_data["id"])
            if combat is None:
                raise CheckpointConflictError(
                    "checkpoint combat is missing",
                    [
                        {
                            "code": "missing_dependency",
                            "severity": "hard",
                            "entity_type": "combat",
                            "entity_id": combat_data["id"],
                        }
                    ],
                )
            self._assign(combat, combat_data, COMBAT_FIELDS)
            combat_id = combat.id
            combatant_ids = [
                row.id
                for row in session.scalars(
                    select(Combatant).where(Combatant.combat_id == combat_id)
                )
            ]
            if combatant_ids:
                session.execute(
                    delete(CombatEffect).where(CombatEffect.combat_id == combat_id)
                )
                session.execute(
                    delete(DeathSave).where(DeathSave.combatant_id.in_(combatant_ids))
                )
            session.execute(
                delete(CombatReinforcement).where(
                    CombatReinforcement.combat_id == combat_id
                )
            )
            self._restore_by_id(
                session,
                Combatant,
                list(snapshot.get("combatants", [])),
                COMBATANT_FIELDS,
                delete_scope=select(Combatant).where(Combatant.combat_id == combat_id),
            )
            session.flush()
            self._restore_by_id(
                session,
                CombatEffect,
                list(snapshot.get("combat_effects", [])),
                EFFECT_FIELDS,
            )
            self._restore_by_id(
                session,
                DeathSave,
                list(snapshot.get("death_saves", [])),
                DEATH_SAVE_FIELDS,
            )
            self._restore_by_id(
                session,
                CombatReinforcement,
                list(snapshot.get("reinforcements", [])),
                REINFORCEMENT_FIELDS,
            )

        table_state = session.scalar(
            select(CampaignSessionState).where(
                CampaignSessionState.campaign_id == checkpoint.campaign_id
            )
        )
        if table_state is None:
            table_state = CampaignSessionState(campaign_id=checkpoint.campaign_id)
            session.add(table_state)
        else:
            table_state.version += 1
        table_state.current_scene_id = checkpoint.scene_id
        table_state.active_combat_id = checkpoint.active_combat_id
        table_state.restored_checkpoint_id = checkpoint.id
        table_state.entries_json = checkpoint.entries_json

    def restore(
        self,
        campaign_id: str,
        checkpoint_id: str,
        *,
        expected_campaign_version: int | None,
        force: bool,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            checkpoint = self._checkpoint(session, campaign_id, checkpoint_id)
            prior = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == idempotency_key,
                )
            )
            if prior is not None:
                if (
                    prior.operation_type != "session_checkpoint_restore"
                    or prior.status != "applied"
                    or prior.after_snapshot.get("checkpoint_id") != checkpoint_id
                ):
                    raise CheckpointConflictError(
                        "idempotency key was already used for another operation",
                        [{"code": "idempotency_conflict", "severity": "hard"}],
                    )
                return {
                    **prior.after_snapshot,
                    "idempotent_replay": True,
                    "entries": checkpoint.entries_json,
                }
            conflicts = self._conflicts(
                session,
                checkpoint,
                expected_campaign_version=expected_campaign_version,
            )
            hard = [item for item in conflicts if item["severity"] == "hard"]
            if hard or (conflicts and not force):
                raise CheckpointConflictError(
                    "checkpoint restore has unresolved dependencies or version conflicts",
                    conflicts,
                )
            before = {
                "campaign_version": self._campaign(session, campaign_id).version,
                "conflicts_overridden": conflicts if force else [],
            }
            self._apply_snapshot(session, checkpoint)
            now = datetime.now(UTC)
            checkpoint.restored_at = now
            checkpoint.restore_count += 1
            checkpoint.version += 1
            after = {
                "restored": True,
                "checkpoint_id": checkpoint.id,
                "campaign_id": campaign_id,
                "restored_at": now.isoformat(),
                "change_summary": {
                    **self._summary(checkpoint.snapshot_json),
                    "entry_count": len(checkpoint.entries_json),
                },
            }
            session.add(
                OperationTransaction(
                    campaign_id=campaign_id,
                    operation_type="session_checkpoint_restore",
                    idempotency_key=idempotency_key,
                    status="applied",
                    before_snapshot=before,
                    after_snapshot=after,
                    reason=f"restore session checkpoint {checkpoint.id}",
                    source="game_table",
                    confirmed_at=now,
                )
            )
            session.flush()
            return {**after, "idempotent_replay": False, "entries": checkpoint.entries_json}

    def archive(
        self,
        campaign_id: str,
        checkpoint_id: str,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            checkpoint = self._checkpoint(session, campaign_id, checkpoint_id)
            if checkpoint.version != expected_version:
                raise VersionConflict(
                    "session_checkpoint",
                    checkpoint.id,
                    expected_version,
                    checkpoint.version,
                )
            checkpoint.status = "archived"
            checkpoint.version += 1
            session.flush()
            return self._payload(checkpoint)
