from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import (
    CampaignState,
    StateNotFoundError,
    VersionConflict,
)
from dnd_dm_assistant.domain.content_packs import validate_content_pack_compatibility
from dnd_dm_assistant.domain.feature_runtime import compile_feature_runtime_registry
from dnd_dm_assistant.domain.rule_extensions import (
    normalize_enabled_extensions,
    runtime_effects_for_extensions,
    seed_atoms_for_extensions,
)
from dnd_dm_assistant.domain.spell_rules import enrich_spell_action
from dnd_dm_assistant.infrastructure.database.campaign_repository import (
    SqlAlchemyCampaignStateRepository,
)
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    AdventureSite,
    AuditLog,
    Campaign,
    Character,
    CharacterCondition,
    Clue,
    Combat,
    CombatAction,
    Combatant,
    CompendiumEntry,
    DowntimeActivity,
    Event,
    KnownSpell,
    Location,
    LocationConnection,
    MonsterInstance,
    Quest,
    Scene,
    SceneParticipant,
    SiteLevel,
    SiteRoom,
    WorldItem,
)

ModelT = TypeVar("ModelT")


ENTITY_MODELS: dict[str, type[Any]] = {
    "campaign": Campaign,
    "character": Character,
    "condition": CharacterCondition,
    "npc": NPC,
    "location": Location,
    "connection": LocationConnection,
    "quest": Quest,
    "clue": Clue,
    "event": Event,
    "downtime_activity": DowntimeActivity,
    "combat": Combat,
    "combatant": Combatant,
    "world_item": WorldItem,
    "monster": MonsterInstance,
    "scene": Scene,
    "scene_participant": SceneParticipant,
}

NotFoundError = StateNotFoundError

ENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "campaign": (
        "name",
        "description",
        "world_setting",
        "current_time",
        "current_location_id",
        "status",
        "ruleset",
        "primary_rules_year",
        "allow_legacy",
        "encumbrance_mode",
        "enabled_rule_extensions",
        "enabled_content_packs",
    ),
    "character": (
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
        "ability_score_reductions",
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
        "notes",
    ),
    "npc": (
        "name",
        "description",
        "alignment",
        "attitude",
        "personality",
        "goal",
        "fear",
        "armor_class",
        "hp",
        "max_hp",
        "speed",
        "ability_scores",
        "challenge_rating",
        "actions",
        "equipment",
        "relationship",
        "secrets",
        "known_information",
        "location_id",
        "status",
    ),
    "location": (
        "name",
        "parent_location_id",
        "depth",
        "description",
        "interactive_objects",
        "secrets",
        "discovered",
        "notes",
    ),
    "quest": (
        "name",
        "description",
        "quest_type",
        "giver",
        "reward",
        "xp_reward",
        "xp_awarded",
        "status",
        "notes",
    ),
    "clue": (
        "name",
        "description",
        "player_text",
        "dm_truth",
        "verified",
        "discovered",
        "discovered_at",
        "source_event_id",
        "quest_id",
    ),
    "event": (
        "event_type",
        "title",
        "description",
        "occurred_at",
        "location_id",
        "visibility",
        "metadata_json",
    ),
    "downtime_activity": (
        "character_id",
        "activity_type",
        "title",
        "status",
        "duration_days",
        "progress_days",
        "daily_cost_cp",
        "details",
    ),
    "combat": (
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
    ),
    "combatant": (
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
    ),
    "condition": ("character_id", "condition_name", "source", "duration", "notes", "details"),
    "connection": ("from_location_id", "to_location_id", "label", "travel_time", "bidirectional"),
    "world_item": (
        "name",
        "description",
        "category",
        "quantity",
        "unit_weight_lb",
        "price_cp",
        "source_record_id",
        "source_label",
        "location_id",
        "owner_character_id",
        "is_equipped",
        "is_hidden",
        "metadata_json",
    ),
    "monster": (
        "name",
        "source_record_id",
        "source_name",
        "armor_class",
        "hp",
        "max_hp",
        "speed",
        "ability_scores",
        "challenge_rating",
        "actions",
        "damage_resistances",
        "damage_vulnerabilities",
        "damage_immunities",
        "condition_immunities",
        "notes",
    ),
    "scene": ("location_id", "name", "description", "status", "notes"),
    "scene_participant": (
        "scene_id",
        "entity_type",
        "entity_id",
        "role",
        "visible",
        "notes",
    ),
}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def serialize(entity: Any) -> dict[str, Any]:
    fields = ["id", "created_at", "updated_at", "version"]
    fields += [column.name for column in entity.__table__.columns if column.name not in fields]
    return {
        field: _json_value(getattr(entity, field)) for field in fields if hasattr(entity, field)
    }


class SqlAlchemyCampaignStateGateway:
    """Transactional application boundary for all structured campaign state."""

    def __init__(self, engine: Engine, *, actor: str = "dm") -> None:
        self.engine = engine
        self.actor = actor

    def _audit(
        self,
        session: Session,
        *,
        campaign_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        before: Any,
        after: Any,
        request_id: str,
    ) -> None:
        session.add(
            AuditLog(
                campaign_id=campaign_id,
                actor=self.actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before_json=None
                if before is None
                else serialize(before)
                if hasattr(before, "__table__")
                else before,
                after_json=None
                if after is None
                else serialize(after)
                if hasattr(after, "__table__")
                else after,
                request_id=request_id,
            )
        )

    def _resolve_campaign_id(self, session: Session, entity_type: str, entity: Any) -> str | None:
        return SqlAlchemyCampaignStateRepository(session).campaign_id_for(entity_type, entity)

    def create(
        self,
        entity_type: str,
        data: dict[str, Any],
        *,
        campaign_id: str | None = None,
        request_id: str = "unknown",
    ) -> Any:
        model = ENTITY_MODELS[entity_type]
        with Session(self.engine) as session, session.begin():
            if campaign_id is not None and entity_type == "campaign":
                raise ValueError("campaign_id is not accepted when creating a campaign")
            if entity_type != "campaign":
                self._ensure_campaign(session, campaign_id or "")
                data = self._with_parent(entity_type, data, campaign_id or "")
                self._ensure_related_scope(session, entity_type, data, campaign_id or "")
            if entity_type == "campaign":
                enabled_rule_extensions = normalize_enabled_extensions(
                    data.get("enabled_rule_extensions", []),
                    allow_legacy=bool(data.get("allow_legacy", False)),
                )
                data = {
                    **data,
                    "enabled_rule_extensions": enabled_rule_extensions,
                    "enabled_content_packs": validate_content_pack_compatibility(
                        data.get("enabled_content_packs", []),
                        allow_legacy=bool(data.get("allow_legacy", False)),
                        primary_rules_year=int(data.get("primary_rules_year", 2024)),
                    ),
                    **runtime_effects_for_extensions(enabled_rule_extensions),
                }
            if entity_type == "combatant":
                data = self._hydrate_combatant_feature_runtime(session, data)
            values = {field: data[field] for field in ENTITY_FIELDS[entity_type] if field in data}
            if entity_type in {
                "character",
                "npc",
                "location",
                "quest",
                "clue",
                "event",
                "downtime_activity",
                "combat",
                "world_item",
                "monster",
                "scene",
            }:
                values["campaign_id"] = campaign_id
            if entity_type == "campaign" and data.get("current_location_id"):
                raise NotFoundError("current location must be assigned after campaign creation")
            entity = model(**values)
            session.add(entity)
            session.flush()
            if entity_type == "campaign":
                self._seed_rule_extension_atoms(
                    session,
                    campaign_id=entity.id,
                    enabled_rule_extensions=entity.enabled_rule_extensions,
                    request_id=request_id,
                )
            self._audit(
                session,
                campaign_id=self._resolve_campaign_id(session, entity_type, entity),
                action="create",
                entity_type=entity_type,
                entity_id=entity.id,
                before=None,
                after=entity,
                request_id=request_id,
            )
            session.flush()
            return serialize(entity)

    @staticmethod
    def _hydrate_combatant_feature_runtime(
        session: Session,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Freeze a character's 1–20 runtime contract into the combat snapshot.

        Combat is intentionally a snapshot boundary.  Previously the DM page
        copied a character's visible actions but omitted the compiled feature
        registry, so Extra Attack, riders, resources, and defensive blocks
        could exist on the sheet while the combat engine could not see them.
        The source character remains authoritative; this only freezes the
        auditable runtime projection for this encounter.
        """

        if data.get("entity_type") != "character" or not data.get("entity_id"):
            return data
        character = session.get(Character, data["entity_id"])
        if character is None:
            return data
        grants = [item for item in (character.features or []) if isinstance(item, dict)]
        scaling_values = {
            str(item.get("scaling_key")): item.get("value")
            for item in grants
            if item.get("kind") == "class_scaling"
            and isinstance(item.get("scaling_key"), str)
        }
        snapshot = dict(data.get("snapshot_json") or {})
        supplied_registry = snapshot.get("feature_runtime")
        registry = (
            dict(supplied_registry)
            if isinstance(supplied_registry, dict)
            else compile_feature_runtime_registry(
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
        )
        snapshot["feature_runtime"] = registry
        combat_start = dict(snapshot.get("combat_start_state") or {})
        combat_start["snapshot_json"] = dict(snapshot)
        snapshot["combat_start_state"] = combat_start

        combat_start_registry = registry.get("combat_start")
        if isinstance(combat_start_registry, dict):
            modifiers = combat_start_registry.get("modifiers")
            rule_modifiers = dict(snapshot.get("rule_modifiers") or {})
            if isinstance(modifiers, list):
                for index, modifier in enumerate(modifiers):
                    if not isinstance(modifier, dict):
                        continue
                    stat = str(modifier.get("stat") or "").strip()
                    operation = str(modifier.get("operation") or "").strip()
                    value = modifier.get("value")
                    if not stat or operation not in {"add", "advantage", "disadvantage"}:
                        continue
                    if not isinstance(value, int) and operation == "add":
                        continue
                    scope = str(modifier.get("scope") or "all")
                    skill = str(modifier.get("skill") or "")
                    key = f"{stat}:{scope}:{skill}:{index}"
                    rule_modifiers[key] = {
                        # Keep the selector fields alongside the legacy key.
                        # Combat resolution must be able to evaluate a typed
                        # feature modifier (for example Danger Sense's
                        # Dexterity-save advantage) without parsing a
                        # presentation-only string key.
                        "stat": stat,
                        "scope": scope,
                        "skill": skill or None,
                        "ability": modifier.get("ability"),
                        "operation": operation,
                        "value": value,
                        "source": modifier.get("source_feature")
                        or modifier.get("feature_name"),
                        "applies_when": modifier.get("applies_when"),
                        "frequency": modifier.get("frequency"),
                        "expires": modifier.get("expires"),
                    }
            if rule_modifiers:
                snapshot["rule_modifiers"] = rule_modifiers

            defenses = combat_start_registry.get("defenses")
            if isinstance(defenses, list):
                advanced_defenses = dict(snapshot.get("advanced_defenses") or {})
                conditional = list(snapshot.get("conditional_damage_defenses") or [])
                for index, defense in enumerate(defenses):
                    if not isinstance(defense, dict):
                        continue
                    if defense.get("kind") == "evasion":
                        advanced_defenses["evasion"] = True
                        continue
                    operation = str(defense.get("operation") or "").strip()
                    types = defense.get("damage_types")
                    if operation not in {"resistance", "vulnerability", "immunity"}:
                        continue
                    if not isinstance(types, list) or not types:
                        continue
                    conditional.append(
                        {
                            "id": str(defense.get("id") or f"feature-defense-{index + 1}"),
                            "condition": str(
                                defense.get("applies_when") or "feature_condition"
                            ),
                            "operation": operation,
                            "damage_types": [str(value) for value in types],
                        }
                    )
                if advanced_defenses:
                    snapshot["advanced_defenses"] = advanced_defenses
                if conditional:
                    snapshot["conditional_damage_defenses"] = conditional
        return {**data, "snapshot_json": snapshot}

    def get(self, entity_type: str, entity_id: str, *, campaign_id: str | None = None) -> Any:
        with Session(self.engine) as session:
            entity = SqlAlchemyCampaignStateRepository(session).get(
                entity_type, entity_id, campaign_id
            )
            if entity is None:
                raise NotFoundError(f"{entity_type} not found")
            return serialize(entity)

    def list(
        self,
        entity_type: str,
        *,
        campaign_id: str | None,
        limit: int = 100,
        offset: int = 0,
        open_only: bool = False,
        parent_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            rows = SqlAlchemyCampaignStateRepository(session).list(
                entity_type,
                campaign_id,
                limit=limit,
                offset=offset,
                open_only=open_only,
                parent_id=parent_id,
            )
            result = [serialize(item) for item in rows]
            if entity_type == "combatant":
                # Combatants persist a snapshot at combat start.  Existing
                # combats may therefore contain an older character action
                # card; refresh its structured spell fields at read time.
                for item, row in zip(result, rows, strict=True):
                    if row.entity_type != "character" or not row.entity_id:
                        continue
                    known_spells = session.scalars(
                        select(KnownSpell).where(KnownSpell.character_id == row.entity_id)
                    ).all()
                    character = session.get(Character, row.entity_id)
                    spellcasting = character.spellcasting if character is not None else None
                    by_name = {
                        spell.name: dict(spell.metadata_json or {})
                        for spell in known_spells
                    }
                    actions = item.get("snapshot_json", {}).get("actions")
                    if not isinstance(actions, list):
                        continue
                    hydrated = []
                    for raw in actions:
                        action = dict(raw) if isinstance(raw, dict) else raw
                        if isinstance(action, dict):
                            metadata = by_name.get(str(action.get("name") or ""), {})
                            source = metadata.get("character_spell")
                            source_fields = dict(source) if isinstance(source, dict) else metadata
                            for key in (
                                "damage", "damage_expression", "damage_dice", "healing",
                                "damage_type",
                                "save_ability", "save_dc", "half_damage_on_save", "range",
                                "description", "cost", "resource_key", "resource_cost",
                                "resolution_kind", "rule_plan", "spell_level",
                                "upcast_damage_dice", "upcast_healing_dice",
                            ):
                                if source_fields.get(key) not in (None, ""):
                                    action[key] = source_fields[key]
                            action = enrich_spell_action(
                                action,
                                spellcasting=spellcasting,
                            )
                        hydrated.append(action)
                    item["snapshot_json"] = {**item["snapshot_json"], "actions": hydrated}
            return tuple(result)

    def update(
        self,
        entity_type: str,
        entity_id: str,
        data: dict[str, Any],
        *,
        campaign_id: str | None = None,
        expected_version: int,
        request_id: str = "unknown",
    ) -> dict[str, Any]:
        model = ENTITY_MODELS[entity_type]
        with Session(self.engine) as session, session.begin():
            entity = SqlAlchemyCampaignStateRepository(session).get(
                entity_type, entity_id, campaign_id
            )
            if entity is None:
                raise NotFoundError(f"{entity_type} not found")
            actual = int(entity.version)
            if actual != expected_version:
                raise VersionConflict(entity_type, entity_id, expected_version, actual)
            before = serialize(entity)
            if entity_type == "campaign":
                enabled_rule_extensions = data.get(
                    "enabled_rule_extensions", entity.enabled_rule_extensions
                )
                if "enabled_rule_extensions" in data:
                    enabled_rule_extensions = normalize_enabled_extensions(
                        enabled_rule_extensions,
                        allow_legacy=bool(data.get("allow_legacy", entity.allow_legacy)),
                    )
                    data = {
                        **data,
                        "enabled_rule_extensions": enabled_rule_extensions,
                    }
                if "enabled_content_packs" in data or "allow_legacy" in data:
                    data = {
                        **data,
                        "enabled_content_packs": validate_content_pack_compatibility(
                            data.get(
                                "enabled_content_packs",
                                entity.enabled_content_packs,
                            ),
                            allow_legacy=bool(
                                data.get("allow_legacy", entity.allow_legacy)
                            ),
                            primary_rules_year=int(entity.primary_rules_year),
                        ),
                    }
                data = {
                    **data,
                    **runtime_effects_for_extensions(enabled_rule_extensions),
                }
            values = {field: data[field] for field in ENTITY_FIELDS[entity_type] if field in data}
            if entity_type != "campaign":
                self._ensure_related_scope(
                    session,
                    entity_type,
                    values,
                    campaign_id or self._resolve_campaign_id(session, entity_type, entity) or "",
                )
            elif values.get("current_location_id"):
                location = session.get(Location, values["current_location_id"])
                if location is None or location.campaign_id != entity_id:
                    raise NotFoundError("location not found in campaign")
            values["version"] = expected_version + 1
            values["updated_at"] = datetime.now(UTC)
            result = session.execute(
                update(model)
                .where(model.id == entity_id, model.version == expected_version)
                .values(**values)
            )
            if getattr(result, "rowcount", None) != 1:
                raise VersionConflict(entity_type, entity_id, expected_version, actual)
            session.refresh(entity)
            if entity_type == "combatant" and "conditions" in values:
                # Direct DM/player condition edits must use the same typed
                # lifecycle path as structured combat effects. The import is
                # local because CombatEngineService imports this module's
                # serializer.
                from dnd_dm_assistant.infrastructure.database.combat_service import (
                    CombatEngineService,
                )

                previous_conditions = before.get("conditions", [])
                if isinstance(previous_conditions, list):
                    CombatEngineService.sync_condition_state(entity, previous_conditions)
            if entity_type == "combatant" and (
                "conditions" in values or "hp" in values or "is_active" in values
            ):
                # A DM may apply unconscious/dead/inactive state through the
                # direct combatant editor rather than a combat action.  Run
                # the same explicit lifecycle predicates used by combat
                # damage so concentration summons are removed immediately.
                combat = session.get(Combat, entity.combat_id)
                if combat is not None:
                    from dnd_dm_assistant.infrastructure.database.combat_service import (
                        CombatEngineService,
                    )

                    CombatEngineService._end_predicated_effects(
                        session,
                        combat,
                        now=datetime.now(UTC),
                        event_combatant_ids={entity.id},
                        event_kinds={"condition"},
                    )
            if entity_type == "campaign" and "enabled_rule_extensions" in values:
                self._seed_rule_extension_atoms(
                    session,
                    campaign_id=entity.id,
                    enabled_rule_extensions=entity.enabled_rule_extensions,
                    request_id=request_id,
                )
            if entity_type == "combatant":
                before_snapshot = before.get("snapshot_json")
                after_snapshot = entity.snapshot_json
                before_position = (
                    before_snapshot.get("grid_position")
                    if isinstance(before_snapshot, dict)
                    else None
                )
                after_position = (
                    after_snapshot.get("grid_position")
                    if isinstance(after_snapshot, dict)
                    else None
                )
                if (
                    isinstance(before_position, dict)
                    and isinstance(after_position, dict)
                    and before_position != after_position
                ):
                    combat = session.get(Combat, entity.combat_id)
                    if combat is not None:
                        spent_ft = max(
                            0,
                            int(before.get("movement_remaining_ft", 0))
                            - int(entity.movement_remaining_ft),
                        )
                        session.add(
                            CombatAction(
                                campaign_id=combat.campaign_id,
                                combat_id=combat.id,
                                actor_combatant_id=entity.id,
                                action_type="move",
                                target_combatant_ids=[entity.id],
                                request_json={
                                    "action_name": "移动",
                                    "from_position": before_position,
                                    "to_position": after_position,
                                    "movement_spent_ft": spent_ft,
                                },
                                result_json={
                                    "from_position": before_position,
                                    "to_position": after_position,
                                    "movement_remaining_ft": entity.movement_remaining_ft,
                                },
                                explanation="战斗地图移动已公开同步",
                                round_number=combat.round_number,
                                turn_index=combat.current_turn_index,
                                summary=(
                                    f"{entity.display_name} 从"
                                    f"（{before_position.get('row')},{before_position.get('col')}）"
                                    f"移动到（{after_position.get('row')},{after_position.get('col')}）"
                                    f"；消耗 {spent_ft} 尺移动力"
                                ),
                                idempotency_key=(
                                    f"combatant-move:{entity.id}:{expected_version}"
                                ),
                                status="confirmed",
                            )
                        )
            self._audit(
                session,
                campaign_id=self._resolve_campaign_id(session, entity_type, entity),
                action="update",
                entity_type=entity_type,
                entity_id=entity_id,
                before=before,
                after=entity,
                request_id=request_id,
            )
            session.flush()
            return serialize(entity)

    def _seed_rule_extension_atoms(
        self,
        session: Session,
        *,
        campaign_id: str,
        enabled_rule_extensions: object,
        request_id: str,
    ) -> None:
        """Materialize selected registry modules as campaign-scoped rule atoms."""

        for atom in seed_atoms_for_extensions(enabled_rule_extensions):
            existing = session.scalar(
                select(CompendiumEntry).where(
                    CompendiumEntry.campaign_id == campaign_id,
                    CompendiumEntry.entry_type == "rule",
                    CompendiumEntry.name == atom["name"],
                    CompendiumEntry.source_kind == atom["source_kind"],
                )
            )
            if existing is not None:
                continue
            entry = CompendiumEntry(campaign_id=campaign_id, **atom)
            session.add(entry)
            session.flush()
            self._audit(
                session,
                campaign_id=campaign_id,
                action="seed_rule_extension",
                entity_type="compendium_entry",
                entity_id=entry.id,
                before=None,
                after=entry,
                request_id=request_id,
            )

    def delete(
        self,
        entity_type: str,
        entity_id: str,
        *,
        campaign_id: str | None = None,
        expected_version: int,
        request_id: str = "unknown",
    ) -> None:
        model = ENTITY_MODELS[entity_type]
        with Session(self.engine) as session, session.begin():
            entity = SqlAlchemyCampaignStateRepository(session).get(
                entity_type, entity_id, campaign_id
            )
            if entity is None:
                raise NotFoundError(f"{entity_type} not found")
            if int(entity.version) != expected_version:
                raise VersionConflict(entity_type, entity_id, expected_version, int(entity.version))
            if entity_type == "location":
                managed = session.scalar(
                    select(AdventureSite.id).where(AdventureSite.location_id == entity_id)
                )
                managed = managed or session.scalar(
                    select(SiteLevel.id).where(SiteLevel.location_id == entity_id)
                )
                managed = managed or session.scalar(
                    select(SiteRoom.id).where(SiteRoom.location_id == entity_id)
                )
                if managed is not None:
                    raise ValueError(
                        "generated site locations must be deleted through "
                        "the adventure site endpoint"
                    )
            before = serialize(entity)
            audit_campaign = self._resolve_campaign_id(session, entity_type, entity)
            # Campaign deletion retains a tombstone audit record via SET NULL FK.
            if entity_type == "campaign":
                audit_campaign = None
            result = session.execute(
                sa_delete(model).where(model.id == entity_id, model.version == expected_version)
            )
            if getattr(result, "rowcount", None) != 1:
                raise VersionConflict(entity_type, entity_id, expected_version, int(entity.version))
            self._audit(
                session,
                campaign_id=audit_campaign,
                action="delete",
                entity_type=entity_type,
                entity_id=entity_id,
                before=before,
                after=None,
                request_id=request_id,
            )

    def state(self, campaign_id: str, *, limit: int = 100) -> CampaignState:
        campaign = self.get("campaign", campaign_id)
        now = datetime.now(UTC)
        return CampaignState(
            campaign=campaign,
            characters=self.list("character", campaign_id=campaign_id, limit=limit),
            npcs=self.list("npc", campaign_id=campaign_id, limit=limit),
            locations=self.list("location", campaign_id=campaign_id, limit=limit),
            quests=self.list("quest", campaign_id=campaign_id, limit=limit, open_only=True),
            open_clues=self.list("clue", campaign_id=campaign_id, limit=limit, open_only=True),
            active_combats=self.list(
                "combat", campaign_id=campaign_id, limit=limit, open_only=True
            ),
            as_of=now,
        )

    def export_campaign_backup(self, campaign_id: str) -> dict[str, Any]:
        from dnd_dm_assistant.infrastructure.database.backup_service import (
            CampaignBackupStore,
        )

        return CampaignBackupStore(self.engine).export(campaign_id)

    def import_campaign_backup(
        self,
        backup: dict[str, Any],
        *,
        name: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        from dnd_dm_assistant.infrastructure.database.backup_service import (
            CampaignBackupStore,
        )

        return CampaignBackupStore(self.engine).import_backup(
            backup, name=name, request_id=request_id
        )

    def _ensure_campaign(self, session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise NotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _with_parent(entity_type: str, data: dict[str, Any], campaign_id: str) -> dict[str, Any]:
        values = dict(data)
        if entity_type in {
            "character",
            "npc",
            "location",
            "quest",
            "clue",
            "event",
            "downtime_activity",
            "combat",
            "world_item",
            "monster",
            "scene",
        }:
            values["campaign_id"] = campaign_id
        return values

    def _ensure_related_scope(
        self, session: Session, entity_type: str, data: dict[str, Any], campaign_id: str
    ) -> None:
        if entity_type in {"npc", "event"} and data.get("location_id"):
            location = session.get(Location, data["location_id"])
            if location is None or location.campaign_id != campaign_id:
                raise NotFoundError("location not found in campaign")
        if entity_type == "location" and data.get("parent_location_id"):
            parent = session.get(Location, data["parent_location_id"])
            if parent is None or parent.campaign_id != campaign_id:
                raise NotFoundError("parent location not found in campaign")
            expected_depth = int(parent.depth) + 1
            if int(data.get("depth", expected_depth)) != expected_depth:
                raise ValueError("location depth must be parent depth + 1")
        if entity_type == "clue" and data.get("quest_id"):
            quest = session.get(Quest, data["quest_id"])
            if quest is None or quest.campaign_id != campaign_id:
                raise NotFoundError("quest not found in campaign")
        if entity_type == "condition" and data.get("character_id"):
            character = session.get(Character, data["character_id"])
            if character is None or character.campaign_id != campaign_id:
                raise NotFoundError("character not found in campaign")
        if entity_type == "downtime_activity" and data.get("character_id"):
            character = session.get(Character, data["character_id"])
            if character is None or character.campaign_id != campaign_id:
                raise NotFoundError("character not found in campaign")
        if entity_type == "combatant" and data.get("combat_id"):
            combat = session.get(Combat, data["combat_id"])
            if combat is None or combat.campaign_id != campaign_id:
                raise NotFoundError("combat not found in campaign")
        if entity_type == "combat" and data.get("scene_id"):
            scene = session.get(Scene, data["scene_id"])
            if scene is None or scene.campaign_id != campaign_id:
                raise NotFoundError("scene not found in campaign")
        if entity_type == "connection":
            for key in ("from_location_id", "to_location_id"):
                if key not in data:
                    continue
                location = session.get(Location, data[key])
                if location is None or location.campaign_id != campaign_id:
                    raise NotFoundError("location not found in campaign")
        if entity_type == "world_item":
            location_id = data.get("location_id")
            owner_id = data.get("owner_character_id")
            if location_id and owner_id:
                raise ValueError("item cannot have both location and owner")
            if location_id:
                location = session.get(Location, location_id)
                if location is None or location.campaign_id != campaign_id:
                    raise NotFoundError("location not found in campaign")
            if owner_id:
                character = session.get(Character, owner_id)
                if character is None or character.campaign_id != campaign_id:
                    raise NotFoundError("character not found in campaign")
        if entity_type == "scene" and data.get("location_id"):
            location = session.get(Location, data["location_id"])
            if location is None or location.campaign_id != campaign_id:
                raise NotFoundError("location not found in campaign")
        if entity_type == "scene_participant":
            scene = session.get(Scene, data.get("scene_id"))
            if scene is None or scene.campaign_id != campaign_id:
                raise NotFoundError("scene not found in campaign")
            participant_type = str(data.get("entity_type", ""))
            participant_id = str(data.get("entity_id", ""))
            if participant_type == "character":
                entity_campaign_id = getattr(
                    session.get(Character, participant_id), "campaign_id", None
                )
            elif participant_type == "npc":
                entity_campaign_id = getattr(
                    session.get(NPC, participant_id), "campaign_id", None
                )
            elif participant_type == "monster":
                entity_campaign_id = getattr(
                    session.get(MonsterInstance, participant_id), "campaign_id", None
                )
            else:
                entity_campaign_id = None
            if entity_campaign_id != campaign_id:
                label = participant_type or "participant"
                raise NotFoundError(f"{label} not found in campaign")
