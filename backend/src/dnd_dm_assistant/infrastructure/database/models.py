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
    experience: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
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
    xp_reward: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
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
    conditions: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
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
        CheckConstraint("hp >= 0 AND max_hp >= 0 AND hp <= max_hp", name="ck_combatant_hp"),
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
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
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
