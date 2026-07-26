from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SystemMetadata(Base):
    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
    )


def _id() -> str:
    import uuid

    return str(uuid.uuid4())


class Timestamped:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class Campaign(Timestamped, Base):
    __tablename__ = "campaigns"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    world_setting: Mapped[str | None] = mapped_column(String(200))
    current_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    ruleset: Mapped[str] = mapped_column(
        String(30), nullable=False, default="dnd5e", server_default="dnd5e"
    )
    primary_rules_year: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2024, server_default="2024"
    )
    allow_legacy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    encumbrance_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="standard", server_default="standard"
    )
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_campaign_name_nonempty"),
        CheckConstraint("ruleset = 'dnd5e'", name="ck_campaign_ruleset"),
        CheckConstraint("primary_rules_year = 2024", name="ck_campaign_rules_year"),
        CheckConstraint(
            "encumbrance_mode IN ('standard','variant','none')",
            name="ck_campaign_encumbrance",
        ),
        Index("ix_campaigns_status_created", "status", "created_at"),
    )


class Character(Timestamped, Base):
    __tablename__ = "characters"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    race: Mapped[str | None] = mapped_column(String(100))
    background: Mapped[str | None] = mapped_column(String(100))
    class_name: Mapped[str | None] = mapped_column(String(100))
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    experience: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    armor_class: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    speed: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    ability_scores: Mapped[dict[str, int]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {
            "strength": 10,
            "dexterity": 10,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 10,
        },
        server_default="{}",
    )
    hp: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_hp_reduction: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    ability_score_reductions: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    death_saves: Mapped[dict[str, int]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {"successes": 0, "failures": 0},
        server_default='{"successes":0,"failures":0}',
    )
    inventory: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    equipment: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    proficiencies: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    skills: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    features: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    actions: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    resources: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    spells: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    spellcasting: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_character_name_nonempty"),
        CheckConstraint("level >= 1 AND level <= 20", name="ck_character_level"),
        CheckConstraint("experience >= 0", name="ck_character_experience"),
        CheckConstraint("armor_class >= 0 AND armor_class <= 99", name="ck_character_ac"),
        CheckConstraint("speed >= 0 AND speed <= 1000", name="ck_character_speed"),
        CheckConstraint("hp >= 0 AND max_hp >= 0 AND hp <= max_hp", name="ck_character_hp"),
        CheckConstraint(
            "max_hp_reduction >= 0 AND max_hp_reduction <= max_hp",
            name="ck_character_max_hp_reduction",
        ),
        Index("ix_characters_campaign_created", "campaign_id", "created_at", "id"),
    )


class CharacterCondition(Timestamped, Base):
    __tablename__ = "character_conditions"
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    condition_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str | None] = mapped_column(String(200))
    duration: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("length(trim(condition_name)) > 0", name="ck_condition_name_nonempty"),
    )


class Location(Timestamped, Base):
    __tablename__ = "locations"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="SET NULL")
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    description: Mapped[str | None] = mapped_column(Text)
    interactive_objects: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    secrets: Mapped[str | None] = mapped_column(Text)
    discovered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_location_name_nonempty"),
        CheckConstraint("depth >= 1 AND depth <= 10", name="ck_location_depth"),
        Index("ix_locations_campaign_created", "campaign_id", "created_at", "id"),
    )


class NPC(Timestamped, Base):
    __tablename__ = "npcs"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    alignment: Mapped[str | None] = mapped_column(String(100))
    attitude: Mapped[str | None] = mapped_column(String(100))
    personality: Mapped[str | None] = mapped_column(Text)
    goal: Mapped[str | None] = mapped_column(Text)
    fear: Mapped[str | None] = mapped_column(Text)
    armor_class: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    hp: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    max_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    speed: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    ability_scores: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    challenge_rating: Mapped[str | None] = mapped_column(String(30))
    actions: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    equipment: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    relationship: Mapped[str | None] = mapped_column(Text)
    secrets: Mapped[str | None] = mapped_column(Text)
    known_information: Mapped[str | None] = mapped_column(Text)
    location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default="active"
    )
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_npc_name_nonempty"),
        CheckConstraint("armor_class >= 0 AND armor_class <= 99", name="ck_npc_ac"),
        CheckConstraint("hp >= 0 AND max_hp >= 0 AND hp <= max_hp", name="ck_npc_hp"),
        Index("ix_npcs_campaign_created", "campaign_id", "created_at", "id"),
    )


class LocationConnection(Timestamped, Base):
    __tablename__ = "location_connections"
    from_location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    to_location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(200))
    travel_time: Mapped[str | None] = mapped_column(String(100))
    bidirectional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    __table_args__ = (
        CheckConstraint("from_location_id <> to_location_id", name="ck_connection_distinct"),
    )


class Quest(Timestamped, Base):
    __tablename__ = "quests"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    quest_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="side", server_default="side"
    )
    giver: Mapped[str | None] = mapped_column(String(200))
    reward: Mapped[str | None] = mapped_column(Text)
    xp_reward: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    xp_awarded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="open", server_default="open"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_quest_name_nonempty"),
        Index("ix_quests_campaign_status", "campaign_id", "status", "id"),
    )


class Clue(Timestamped, Base):
    __tablename__ = "clues"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    quest_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("quests.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    player_text: Mapped[str | None] = mapped_column(Text)
    dm_truth: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    discovered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_event_id: Mapped[str | None] = mapped_column(String(36))
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_clue_name_nonempty"),
        Index("ix_clues_campaign_discovered", "campaign_id", "discovered", "id"),
    )


class Event(Timestamped, Base):
    __tablename__ = "events"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        String(80), nullable=False, default="note", server_default="note"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="SET NULL")
    )
    visibility: Mapped[str] = mapped_column(
        String(30), nullable=False, default="dm", server_default="dm"
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (CheckConstraint("length(trim(title)) > 0", name="ck_event_title_nonempty"),)


class Combat(Timestamped, Base):
    __tablename__ = "combats"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    round_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    current_turn_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    difficulty: Mapped[str | None] = mapped_column(String(30))
    base_xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    difficulty_adjustments: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    xp_awarded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_combat_name_nonempty"),
        CheckConstraint("round_number >= 1", name="ck_combat_round"),
        CheckConstraint("current_turn_index >= 0", name="ck_combat_turn"),
        CheckConstraint("base_xp >= 0", name="ck_combat_base_xp"),
        Index("ix_combats_campaign_status", "campaign_id", "status", "id"),
    )


class Combatant(Timestamped, Base):
    __tablename__ = "combatants"
    combat_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("combats.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36))
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    initiative: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    armor_class: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    hp: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    temporary_hp: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_hp_reduction: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    damage_resistances: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    damage_vulnerabilities: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    damage_immunities: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    condition_immunities: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    conditions: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    concentration: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    speed_ft: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    movement_remaining_ft: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    action_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    bonus_action_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    reaction_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    snapshot_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    __table_args__ = (
        CheckConstraint("length(trim(display_name)) > 0", name="ck_combatant_name_nonempty"),
        CheckConstraint(
            "initiative >= -100 AND initiative <= 1000", name="ck_combatant_initiative"
        ),
        CheckConstraint("armor_class >= 0 AND armor_class <= 99", name="ck_combatant_ac"),
        CheckConstraint(
            "hp >= 0 AND max_hp >= 0 AND hp + max_hp_reduction <= max_hp",
            name="ck_combatant_hp",
        ),
        CheckConstraint("temporary_hp >= 0", name="ck_combatant_temporary_hp"),
        CheckConstraint(
            "max_hp_reduction >= 0 AND max_hp_reduction <= max_hp",
            name="ck_combatant_max_hp_reduction",
        ),
        CheckConstraint("speed_ft >= 0", name="ck_combatant_speed"),
        CheckConstraint(
            "movement_remaining_ft >= 0",
            name="ck_combatant_movement_remaining",
        ),
    )


class CombatAction(Timestamped, Base):
    __tablename__ = "combat_actions"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    combat_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("combats.id", ondelete="CASCADE"), nullable=False
    )
    actor_combatant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("combatants.id", ondelete="SET NULL")
    )
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("operation_transactions.id", ondelete="SET NULL")
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_combatant_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    request_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    result_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    explanation: Mapped[str | None] = mapped_column(Text)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    dm_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    override_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="confirmed", server_default="confirmed"
    )
    __table_args__ = (
        CheckConstraint(
            "status IN ('previewed','confirmed','reverted','conflict')",
            name="ck_combat_action_status",
        ),
        CheckConstraint("round_number >= 1", name="ck_combat_action_round"),
        CheckConstraint("turn_index >= 0", name="ck_combat_action_turn"),
        CheckConstraint("length(trim(summary)) > 0", name="ck_combat_action_summary"),
        UniqueConstraint(
            "combat_id",
            "idempotency_key",
            name="uq_combat_action_combat_idempotency",
        ),
        Index("ix_combat_actions_combat_created", "combat_id", "created_at", "id"),
    )


class CombatEffect(Timestamped, Base):
    __tablename__ = "combat_effects"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    combat_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("combats.id", ondelete="CASCADE"), nullable=False
    )
    target_combatant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("combatants.id", ondelete="CASCADE"), nullable=False
    )
    source_combatant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("combatants.id", ondelete="SET NULL")
    )
    source_action_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("combat_actions.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    effect_type: Mapped[str] = mapped_column(String(50), nullable=False)
    details_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    started_round: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_unit: Mapped[str] = mapped_column(
        String(30), nullable=False, default="until_removed", server_default="until_removed"
    )
    duration_value: Mapped[int | None] = mapped_column(Integer)
    ends_round: Mapped[int | None] = mapped_column(Integer)
    requires_concentration: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    save_dc: Mapped[int | None] = mapped_column(Integer)
    save_ability: Mapped[str | None] = mapped_column(String(30))
    trigger_timing: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_combat_effect_name"),
        CheckConstraint("started_round >= 1", name="ck_combat_effect_started_round"),
        CheckConstraint(
            "duration_value IS NULL OR duration_value >= 0",
            name="ck_combat_effect_duration",
        ),
        CheckConstraint(
            "ends_round IS NULL OR ends_round >= started_round",
            name="ck_combat_effect_ends_round",
        ),
        CheckConstraint(
            "save_dc IS NULL OR save_dc >= 0",
            name="ck_combat_effect_save_dc",
        ),
        CheckConstraint(
            "status IN ('active','ended')",
            name="ck_combat_effect_status",
        ),
        Index(
            "ix_combat_effects_target_status",
            "target_combatant_id",
            "status",
            "id",
        ),
    )


class DeathSave(Timestamped, Base):
    __tablename__ = "death_saves"
    combatant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("combatants.id", ondelete="CASCADE"), nullable=False
    )
    successes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    stable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    dead: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    pending_death_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    last_roll: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("successes >= 0 AND successes <= 3", name="ck_death_save_successes"),
        CheckConstraint("failures >= 0 AND failures <= 3", name="ck_death_save_failures"),
        CheckConstraint(
            "last_roll IS NULL OR (last_roll >= 1 AND last_roll <= 20)",
            name="ck_death_save_last_roll",
        ),
        UniqueConstraint("combatant_id", name="uq_death_save_combatant"),
    )


class CombatReinforcement(Timestamped, Base):
    __tablename__ = "combat_reinforcements"
    combat_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("combats.id", ondelete="CASCADE"), nullable=False
    )
    proposal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("encounter_adjustment_proposals.id", ondelete="SET NULL")
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_round: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    reason: Mapped[str | None] = mapped_column(Text)
    deployed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('character','npc','monster')",
            name="ck_combat_reinforcement_type",
        ),
        CheckConstraint("target_round >= 1", name="ck_combat_reinforcement_round"),
        CheckConstraint("quantity >= 1", name="ck_combat_reinforcement_quantity"),
        Index(
            "ix_combat_reinforcements_combat_round",
            "combat_id",
            "target_round",
            "deployed",
            "id",
        ),
    )


class CombatSettlement(Timestamped, Base):
    __tablename__ = "combat_settlements"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    combat_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("combats.id", ondelete="CASCADE"), nullable=False
    )
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("operation_transactions.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="confirmed", server_default="confirmed"
    )
    resolution_type: Mapped[str] = mapped_column(String(30), nullable=False)
    xp_allocations: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    writebacks: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    result_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "status IN ('confirmed','reverted','conflict')",
            name="ck_combat_settlement_status",
        ),
        CheckConstraint(
            "resolution_type IN ('victory','defeat','retreat','negotiated','bypassed','other')",
            name="ck_combat_settlement_resolution",
        ),
        UniqueConstraint("combat_id", name="uq_combat_settlement_combat"),
        UniqueConstraint(
            "campaign_id",
            "idempotency_key",
            name="uq_combat_settlement_campaign_idempotency",
        ),
        Index(
            "ix_combat_settlements_campaign_confirmed",
            "campaign_id",
            "confirmed_at",
            "id",
        ),
    )


class OperationTransaction(Timestamped, Base):
    __tablename__ = "operation_transactions"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    operation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="applied", server_default="applied"
    )
    before_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    after_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="dm", server_default="dm"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','applied','reverted','conflict','failed')",
            name="ck_operation_transaction_status",
        ),
        CheckConstraint(
            "source IN ('dm','game_table','combat','system')",
            name="ck_operation_transaction_source",
        ),
        UniqueConstraint(
            "campaign_id",
            "idempotency_key",
            name="uq_operation_transaction_campaign_idempotency",
        ),
        Index(
            "ix_operation_transactions_campaign_created",
            "campaign_id",
            "created_at",
            "id",
        ),
    )


class ResourcePool(Timestamped, Base):
    __tablename__ = "resource_pools"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="other", server_default="other"
    )
    current: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    maximum: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    recovery_timing: Mapped[str] = mapped_column(
        String(30), nullable=False, default="manual", server_default="manual"
    )
    recovery_amount: Mapped[int | None] = mapped_column(Integer)
    die_size: Mapped[int | None] = mapped_column(Integer)
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    rule_key: Mapped[str | None] = mapped_column(String(200))
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("length(trim(key)) > 0", name="ck_resource_pool_key_nonempty"),
        CheckConstraint("length(trim(label)) > 0", name="ck_resource_pool_label_nonempty"),
        CheckConstraint(
            "current >= 0 AND maximum >= 0 AND current <= maximum", name="ck_resource_pool_bounds"
        ),
        CheckConstraint(
            "recovery_amount IS NULL OR recovery_amount >= 0",
            name="ck_resource_pool_recovery_amount",
        ),
        CheckConstraint("die_size IS NULL OR die_size >= 2", name="ck_resource_pool_die_size"),
        CheckConstraint(
            "category IN ('class_feature','spell_slot','hit_die','item','other')",
            name="ck_resource_pool_category",
        ),
        CheckConstraint(
            "recovery_timing IN ('short_rest','long_rest','both','dawn','manual','none')",
            name="ck_resource_pool_recovery_timing",
        ),
        UniqueConstraint("character_id", "key", name="uq_resource_pool_character_key"),
        Index("ix_resource_pools_campaign_character", "campaign_id", "character_id", "id"),
        Index("ix_resource_pools_character_timing", "character_id", "recovery_timing", "id"),
    )


class RestRecord(Timestamped, Base):
    __tablename__ = "rest_records"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    operation_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("operation_transactions.id", ondelete="SET NULL")
    )
    rest_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    interrupted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    world_time_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    world_time_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    result_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("rest_type IN ('short','long')", name="ck_rest_record_type"),
        CheckConstraint(
            "status IN ('pending','completed','interrupted','failed','reverted')",
            name="ck_rest_record_status",
        ),
        CheckConstraint("duration_minutes >= 0", name="ck_rest_record_duration"),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_rest_record_completion_after_start",
        ),
        CheckConstraint(
            "interrupted = 0 OR status = 'interrupted'",
            name="ck_rest_record_interrupted_status",
        ),
        UniqueConstraint(
            "campaign_id", "idempotency_key", name="uq_rest_record_campaign_idempotency"
        ),
        UniqueConstraint("operation_transaction_id", name="uq_rest_record_operation_transaction"),
        Index("ix_rest_records_campaign_created", "campaign_id", "created_at", "id"),
        Index("ix_rest_records_campaign_status", "campaign_id", "status", "created_at", "id"),
    )


class RestRecoveryEntry(Timestamped, Base):
    __tablename__ = "rest_recovery_entries"
    rest_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rest_records.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    resource_pool_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("resource_pools.id", ondelete="SET NULL")
    )
    recovery_type: Mapped[str] = mapped_column("type", String(30), nullable=False)
    before_value: Mapped[int | None] = mapped_column(Integer)
    after_value: Mapped[int | None] = mapped_column(Integer)
    amount: Mapped[int | None] = mapped_column(Integer)
    die_roll: Mapped[int | None] = mapped_column(Integer)
    modifier: Mapped[int | None] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text)
    rule_reference: Mapped[str | None] = mapped_column(String(200))
    selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    __table_args__ = (
        CheckConstraint(
            "type IN ('hp','resource','hit_die','spell_slot','condition','other')",
            name="ck_rest_recovery_entry_type",
        ),
        CheckConstraint("amount IS NULL OR amount >= 0", name="ck_rest_recovery_entry_amount"),
        CheckConstraint(
            "die_roll IS NULL OR die_roll >= 1", name="ck_rest_recovery_entry_die_roll"
        ),
        CheckConstraint(
            "status IN ('pending','applied','skipped','failed','reverted')",
            name="ck_rest_recovery_entry_status",
        ),
        CheckConstraint(
            "applied = 0 OR status = 'applied'", name="ck_rest_recovery_entry_applied_status"
        ),
        Index("ix_rest_recovery_entries_rest", "rest_record_id", "created_at", "id"),
        Index("ix_rest_recovery_entries_character", "character_id", "created_at", "id"),
    )


class EncounterAdjustmentProposal(Timestamped, Base):
    __tablename__ = "encounter_adjustment_proposals"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    combat_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("combats.id", ondelete="SET NULL")
    )
    source_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="SET NULL")
    )
    operation_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("operation_transactions.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty_shift: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    operations_json: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    inverse_operations_json: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="ck_encounter_adjustment_title"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_encounter_adjustment_reason"),
        CheckConstraint(
            "difficulty_shift IN (-1,0,1)",
            name="ck_encounter_adjustment_difficulty_shift",
        ),
        CheckConstraint(
            "status IN ('pending','applied','rejected','reverted','conflict')",
            name="ck_encounter_adjustment_status",
        ),
        Index(
            "ix_encounter_adjustments_campaign_status",
            "campaign_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_encounter_adjustments_scene_combat",
            "scene_id",
            "combat_id",
            "id",
        ),
    )


class WorldItem(Timestamped, Base):
    __tablename__ = "world_items"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="misc", server_default="misc"
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    unit_weight_lb: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    price_cp: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    source_label: Mapped[str] = mapped_column(
        String(30), nullable=False, default="custom", server_default="custom"
    )
    location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="SET NULL")
    )
    owner_character_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="SET NULL")
    )
    is_equipped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_world_item_name_nonempty"),
        CheckConstraint("quantity >= 1", name="ck_world_item_quantity"),
        CheckConstraint("unit_weight_lb >= 0", name="ck_world_item_weight"),
        CheckConstraint("price_cp >= 0", name="ck_world_item_price"),
        CheckConstraint(
            "NOT (location_id IS NOT NULL AND owner_character_id IS NOT NULL)",
            name="ck_world_item_single_holder",
        ),
        Index("ix_world_items_campaign_location", "campaign_id", "location_id", "id"),
        Index("ix_world_items_campaign_owner", "campaign_id", "owner_character_id", "id"),
    )


class MonsterInstance(Timestamped, Base):
    __tablename__ = "monster_instances"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    source_name: Mapped[str | None] = mapped_column(String(200))
    armor_class: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    hp: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    max_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    speed: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    ability_scores: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    challenge_rating: Mapped[str | None] = mapped_column(String(30))
    actions: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_monster_name_nonempty"),
        CheckConstraint("armor_class >= 0 AND armor_class <= 99", name="ck_monster_ac"),
        CheckConstraint("hp >= 0 AND max_hp >= 0 AND hp <= max_hp", name="ck_monster_hp"),
        Index("ix_monsters_campaign_created", "campaign_id", "created_at", "id"),
    )


class Scene(Timestamped, Base):
    __tablename__ = "scenes"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_scene_name_nonempty"),
        CheckConstraint("status IN ('draft','active','closed')", name="ck_scene_status"),
        Index("ix_scenes_campaign_status", "campaign_id", "status", "created_at", "id"),
    )


class SceneParticipant(Timestamped, Base):
    __tablename__ = "scene_participants"
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, default="present", server_default="present"
    )
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('character','npc','monster')",
            name="ck_scene_participant_type",
        ),
        UniqueConstraint("scene_id", "entity_type", "entity_id", name="uq_scene_participant"),
        Index("ix_scene_participants_scene", "scene_id", "created_at", "id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    campaign_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36))
    before_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    __table_args__ = (Index("ix_audit_campaign_created", "campaign_id", "created_at", "id"),)


class StateChangeProposal(Timestamped, Base):
    __tablename__ = "state_change_proposals"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(
        String(80), nullable=False, default="update_campaign_state"
    )
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36))
    payload_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    expected_version: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_by_model: Mapped[str] = mapped_column(String(200), nullable=False)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("operation IN ('create','update','delete')", name="ck_proposal_operation"),
        CheckConstraint(
            "entity_type IN ('character','npc','quest','event')",
            name="ck_proposal_entity",
        ),
        CheckConstraint(
            "status IN ('pending','confirmed','rejected','conflict')",
            name="ck_proposal_status",
        ),
        Index(
            "ix_proposals_campaign_status_created",
            "campaign_id",
            "status",
            "created_at",
            "id",
        ),
    )


class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    model_role: Mapped[str] = mapped_column(String(30), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    __table_args__ = (
        CheckConstraint("latency_ms >= 0", name="ck_model_run_latency"),
        Index("ix_model_runs_campaign_request", "campaign_id", "request_id", "created_at"),
    )
