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
    text,
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


class CampaignAISession(Timestamped, Base):
    __tablename__ = "campaign_ai_sessions"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    summary_text: Mapped[str | None] = mapped_column(Text)


class CampaignAIMessage(Base):
    __tablename__ = "campaign_ai_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaign_ai_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    authoritative: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    __table_args__ = (
        CheckConstraint("role IN ('dm','assistant')", name="ck_campaign_ai_message_role"),
        CheckConstraint(
            "message_kind IN ('question','answer','confirmed_progress')",
            name="ck_campaign_ai_message_kind",
        ),
        UniqueConstraint("session_id", "sequence_number", name="uq_campaign_ai_message_sequence"),
        Index("ix_campaign_ai_messages_session_created", "session_id", "created_at", "id"),
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
    class_levels: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    subclass_choices: Mapped[dict[str, str]] = mapped_column(
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


class RegionMap(Timestamped, Base):
    __tablename__ = "region_maps"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=24, server_default="24")
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=16, server_default="16")
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    map_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("width >= 8 AND width <= 100", name="ck_region_map_width"),
        CheckConstraint("height >= 8 AND height <= 100", name="ck_region_map_height"),
        UniqueConstraint("campaign_id", "location_id", name="uq_region_map_location"),
        Index("ix_region_maps_campaign_created", "campaign_id", "created_at", "id"),
    )


class AdventureSite(Timestamped, Base):
    __tablename__ = "adventure_sites"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    region_map_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("region_maps.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    site_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    theme: Mapped[str] = mapped_column(String(100), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_levels: Mapped[int] = mapped_column(Integer, nullable=False)
    party_level: Mapped[int] = mapped_column(Integer, nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_parameters: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    map_position: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    generation_request_id: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        CheckConstraint("site_type IN ('building','dungeon')", name="ck_site_type"),
        CheckConstraint("maximum_levels >= 1 AND maximum_levels <= 20", name="ck_site_levels"),
        CheckConstraint("party_level >= 1 AND party_level <= 20", name="ck_site_party_level"),
        CheckConstraint("party_size >= 1 AND party_size <= 12", name="ck_site_party_size"),
        CheckConstraint("status IN ('draft','active','archived')", name="ck_site_status"),
        UniqueConstraint("campaign_id", "location_id", name="uq_site_location"),
        UniqueConstraint("campaign_id", "generation_request_id", name="uq_site_generation_request"),
        Index("ix_sites_campaign_region", "campaign_id", "region_map_id", "created_at", "id"),
    )


class SiteLevel(Timestamped, Base):
    __tablename__ = "site_levels"
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("adventure_sites.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    level_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    encounter_budget_xp: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_budget_gp: Mapped[int] = mapped_column(Integer, nullable=False)
    layout_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    generation_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("level_index >= 1 AND level_index <= 20", name="ck_site_level_index"),
        CheckConstraint("difficulty IN ('low','moderate','high')", name="ck_site_level_difficulty"),
        CheckConstraint("encounter_budget_xp >= 0", name="ck_site_level_xp"),
        CheckConstraint("reward_budget_gp >= 0", name="ck_site_level_reward"),
        UniqueConstraint("site_id", "level_index", name="uq_site_level_index"),
        Index("ix_site_levels_site_index", "site_id", "level_index", "id"),
    )


class SiteRoom(Timestamped, Base):
    __tablename__ = "site_rooms"
    site_level_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("site_levels.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    room_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    room_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    bounds_json: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    encounter_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    reward_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    interactive_objects: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    __table_args__ = (
        CheckConstraint("room_index >= 1", name="ck_site_room_index"),
        UniqueConstraint("site_level_id", "room_index", name="uq_site_room_index"),
        Index("ix_site_rooms_level_index", "site_level_id", "room_index", "id"),
    )


class SiteConnector(Timestamped, Base):
    __tablename__ = "site_connectors"
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("adventure_sites.id", ondelete="CASCADE"), nullable=False
    )
    from_level_index: Mapped[int] = mapped_column(Integer, nullable=False)
    from_room_index: Mapped[int | None] = mapped_column(Integer)
    to_level_index: Mapped[int] = mapped_column(Integer, nullable=False)
    to_room_index: Mapped[int | None] = mapped_column(Integer)
    connector_type: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="closed", server_default="closed"
    )
    position_json: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint(
            "connector_type IN ('door','stairs_up','stairs_down','secret_door','portal')",
            name="ck_site_connector_type",
        ),
        CheckConstraint(
            "state IN ('open','closed','locked','hidden')", name="ck_site_connector_state"
        ),
        Index("ix_site_connectors_site_levels", "site_id", "from_level_index", "to_level_index"),
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


class StoryBeat(Timestamped, Base):
    __tablename__ = "story_beats"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="planned", server_default="planned"
    )
    prerequisites: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    branches: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuestObjective(Timestamped, Base):
    __tablename__ = "quest_objectives"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    quest_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quests.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="custom", server_default="custom"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )


class NPCMemory(Timestamped, Base):
    __tablename__ = "npc_memories"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    npc_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("npcs.id", ondelete="CASCADE"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    memory_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="witnessed", server_default="witnessed"
    )
    attitude_delta: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    tags: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class FactionReputation(Timestamped, Base):
    __tablename__ = "faction_reputations"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    faction_name: Mapped[str] = mapped_column(String(200), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "character_id", "faction_name", name="uq_faction_reputation"
        ),
    )


class ClueDiscovery(Timestamped, Base):
    __tablename__ = "clue_discoveries"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    clue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clues.id", ondelete="CASCADE"), nullable=False
    )
    discoverer_character_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="SET NULL")
    )
    method: Mapped[str] = mapped_column(
        String(100), nullable=False, default="other", server_default="other"
    )
    scene_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)


class DowntimeActivity(Timestamped, Base):
    __tablename__ = "downtime_activities"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    activity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="planned", server_default="planned"
    )
    duration_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    progress_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    daily_cost_cp: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    details: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )


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


class KnownSpell(Timestamped, Base):
    __tablename__ = "known_spells"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    spell_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source_reference: Mapped[str | None] = mapped_column(String(200))
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_known_spell_name"),
        CheckConstraint("spell_level >= 0 AND spell_level <= 9", name="ck_known_spell_level"),
        UniqueConstraint("character_id", "name", name="uq_known_spell_character_name"),
        Index("ix_known_spells_character", "character_id", "created_at", "id"),
    )


class PreparedSpell(Timestamped, Base):
    __tablename__ = "prepared_spells"
    known_spell_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("known_spells.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    prepared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    __table_args__ = (
        UniqueConstraint(
            "character_id", "known_spell_id", name="uq_prepared_spell_character_known"
        ),
    )


class EquipmentInstance(Timestamped, Base):
    __tablename__ = "equipment_instances"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        String(30), nullable=False, default="gear", server_default="gear"
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    armor_class: Mapped[int | None] = mapped_column(Integer)
    equipped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    attunement_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    charges: Mapped[int | None] = mapped_column(Integer)
    max_charges: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_equipment_name"),
        CheckConstraint("quantity >= 0", name="ck_equipment_quantity"),
        CheckConstraint(
            "charges IS NULL OR (charges >= 0 AND max_charges IS NOT NULL "
            "AND charges <= max_charges)",
            name="ck_equipment_charges",
        ),
        Index("ix_equipment_campaign_character", "campaign_id", "character_id", "id"),
    )


class Attunement(Timestamped, Base):
    __tablename__ = "attunements"
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    equipment_instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("equipment_instances.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    __table_args__ = (
        CheckConstraint("status IN ('active','ended')", name="ck_attunement_status"),
        UniqueConstraint("equipment_instance_id", name="uq_attunement_equipment"),
        Index("ix_attunements_character_status", "character_id", "status", "id"),
    )


class Wallet(Timestamped, Base):
    __tablename__ = "wallets"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    copper: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    __table_args__ = (
        CheckConstraint("copper >= 0", name="ck_wallet_copper"),
        UniqueConstraint("campaign_id", "character_id", name="uq_wallet_campaign_character"),
    )


class CurrencyTransaction(Timestamped, Base):
    __tablename__ = "currency_transactions"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    wallet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False
    )
    amount_copper: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint(
            "kind IN ('purchase','sale','split','adjustment')", name="ck_currency_transaction_kind"
        ),
        UniqueConstraint(
            "campaign_id", "idempotency_key", name="uq_currency_transaction_idempotency"
        ),
        Index("ix_currency_transactions_wallet", "wallet_id", "created_at", "id"),
    )


class ShopInventory(Timestamped, Base):
    __tablename__ = "shop_inventories"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    price_copper: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_shop_inventory_name"),
        CheckConstraint("quantity >= 0 AND price_copper >= 0", name="ck_shop_inventory_bounds"),
        Index("ix_shop_inventory_campaign", "campaign_id", "created_at", "id"),
    )


class AdvancementRecord(Timestamped, Base):
    __tablename__ = "advancement_records"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    operation_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("operation_transactions.id", ondelete="SET NULL")
    )
    class_name: Mapped[str] = mapped_column(String(100), nullable=False)
    subclass_name: Mapped[str | None] = mapped_column(String(100))
    from_level: Mapped[int] = mapped_column(Integer, nullable=False)
    to_level: Mapped[int] = mapped_column(Integer, nullable=False)
    choices_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    result_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    preview_token: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="confirmed", server_default="confirmed"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "from_level >= 1 AND to_level >= 2 AND to_level <= 20 AND to_level = from_level + 1",
            name="ck_advancement_level_step",
        ),
        CheckConstraint(
            "status IN ('confirmed','reverted','conflict')",
            name="ck_advancement_status",
        ),
        UniqueConstraint(
            "campaign_id",
            "idempotency_key",
            name="uq_advancement_campaign_idempotency",
        ),
        Index(
            "ix_advancement_character_level",
            "character_id",
            "to_level",
            "created_at",
            "id",
        ),
    )


class CharacterCompanion(Timestamped, Base):
    __tablename__ = "character_companions"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    owner_character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    companion_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    template_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    hp: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    max_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    armor_class: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    speed: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_companion_name_nonempty"),
        CheckConstraint(
            "companion_type IN ('familiar','animal_companion','summon','wild_shape','form')",
            name="ck_companion_type",
        ),
        CheckConstraint(
            "hp >= 0 AND max_hp >= 1 AND hp <= max_hp",
            name="ck_companion_hp",
        ),
        CheckConstraint(
            "armor_class >= 0 AND armor_class <= 99",
            name="ck_companion_ac",
        ),
        CheckConstraint("speed >= 0 AND speed <= 1000", name="ck_companion_speed"),
        Index(
            "ix_companions_campaign_owner",
            "campaign_id",
            "owner_character_id",
            "active",
            "id",
        ),
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


class CompendiumEntry(Timestamped, Base):
    """Reusable rule/content atom; runtime instances always remain separate."""

    __tablename__ = "compendium_entries"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="original", server_default="original"
    )
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    source_name: Mapped[str | None] = mapped_column(String(200))
    family_key: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    filters_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    rules_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint(
            "entry_type IN "
            "('spell','feature','monster','equipment','item','npc','location','scene')",
            name="ck_compendium_entry_type",
        ),
        CheckConstraint(
            "source_kind IN ('official','original','ai_generated','dm_modified','third_party')",
            name="ck_compendium_source_kind",
        ),
        CheckConstraint("length(trim(name)) > 0", name="ck_compendium_name_nonempty"),
        UniqueConstraint(
            "campaign_id",
            "entry_type",
            "name",
            "source_kind",
            name="uq_compendium_campaign_type_name_source",
        ),
        Index(
            "ix_compendium_campaign_type_name",
            "campaign_id",
            "entry_type",
            "name",
            "id",
        ),
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


class SceneGrid(Timestamped, Base):
    __tablename__ = "scene_grids"
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default="12")
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=8, server_default="8")
    cell_size_ft: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="narrative", server_default="narrative"
    )
    public_description: Mapped[str | None] = mapped_column(Text)
    dm_description: Mapped[str | None] = mapped_column(Text)
    layers_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint(
            "width >= 1 AND width <= 100 AND height >= 1 AND height <= 100",
            name="ck_scene_grid_size",
        ),
        CheckConstraint(
            "cell_size_ft >= 1 AND cell_size_ft <= 100", name="ck_scene_grid_cell_size"
        ),
        CheckConstraint("mode IN ('narrative','exploration','combat')", name="ck_scene_grid_mode"),
    )


class SceneToken(Timestamped, Base):
    __tablename__ = "scene_tokens"
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36))
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    row: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    col: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    size_cells: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    elevation_ft: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('character','npc','monster','marker')", name="ck_scene_token_type"
        ),
        CheckConstraint(
            "row >= 1 AND col >= 1 AND size_cells >= 1 AND size_cells <= 4",
            name="ck_scene_token_coords",
        ),
        Index("ix_scene_tokens_scene", "scene_id", "id"),
    )


class SceneObject(Timestamped, Base):
    __tablename__ = "scene_objects"
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    object_type: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    row: Mapped[int] = mapped_column(Integer, nullable=False)
    col: Mapped[int] = mapped_column(Integer, nullable=False)
    width_cells: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    height_cells: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="public", server_default="public"
    )
    interaction_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint(
            "object_type IN ('wall','door','cover','terrain','light','trap','treasure',"
            "'furniture','portal')",
            name="ck_scene_object_type",
        ),
        CheckConstraint(
            "state IN ('active','open','closed','destroyed','disarmed','picked_up')",
            name="ck_scene_object_state",
        ),
        CheckConstraint(
            "visibility IN ('public','dm','hidden')", name="ck_scene_object_visibility"
        ),
        CheckConstraint(
            "row >= 1 AND col >= 1 AND width_cells >= 1 AND height_cells >= 1",
            name="ck_scene_object_coords",
        ),
        Index("ix_scene_objects_scene", "scene_id", "id"),
    )


class VisibilityState(Timestamped, Base):
    __tablename__ = "visibility_states"
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    viewer_key: Mapped[str] = mapped_column(String(100), nullable=False)
    explored_cells: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    visible_cells: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    __table_args__ = (
        UniqueConstraint("scene_id", "viewer_key", name="uq_visibility_scene_viewer"),
    )


class Handout(Timestamped, Base):
    """A DM-authored document deliberately released to the player view."""

    __tablename__ = "handouts"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="ck_handout_title_nonempty"),
        Index(
            "ix_handouts_campaign_published",
            "campaign_id",
            "published",
            "sort_order",
            "id",
        ),
    )


class PlayerRoom(Timestamped, Base):
    """A temporary LAN room opened by the DM for one campaign."""

    __tablename__ = "player_rooms"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    current_scene_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="SET NULL")
    )
    current_combat_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("combats.id", ondelete="SET NULL")
    )
    join_code_salt: Mapped[str] = mapped_column(String(32), nullable=False)
    join_code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    join_code_hint: Mapped[str] = mapped_column(String(2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    allow_character_creation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("status IN ('active','closed')", name="ck_player_room_status"),
        UniqueConstraint("campaign_id", name="uq_player_room_campaign"),
        Index("ix_player_rooms_status_expires", "status", "expires_at", "id"),
    )


class PlayerSession(Timestamped, Base):
    """A revocable player identity; only a hash of its bearer token is stored."""

    __tablename__ = "player_sessions"
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("player_rooms.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="SET NULL")
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("length(trim(display_name)) > 0", name="ck_player_session_name"),
        CheckConstraint("status IN ('active','revoked')", name="ck_player_session_status"),
        Index("ix_player_sessions_room_status", "room_id", "status", "created_at", "id"),
        Index("ix_player_sessions_character_status", "character_id", "status", "id"),
        Index(
            "uq_player_sessions_active_character",
            "room_id",
            "character_id",
            unique=True,
            sqlite_where=text("status = 'active' AND character_id IS NOT NULL"),
        ),
    )


class PlayerActionRequest(Timestamped, Base):
    """An intent submitted by a player; it never changes authoritative state."""

    __tablename__ = "player_action_requests"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    player_key: Mapped[str] = mapped_column(String(100), nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    character_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    dm_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("length(trim(action_type)) > 0", name="ck_player_action_type_nonempty"),
        CheckConstraint("character_version >= 1", name="ck_player_action_character_version"),
        CheckConstraint(
            "status IN ('pending','accepted','rejected','stale')", name="ck_player_action_status"
        ),
        UniqueConstraint(
            "campaign_id", "idempotency_key", name="uq_player_action_campaign_idempotency"
        ),
        Index("ix_player_action_campaign_status", "campaign_id", "status", "created_at", "id"),
    )


class WorldClock(Timestamped, Base):
    __tablename__ = "world_clock"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    current_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar_name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Fantasy Calendar", server_default="Fantasy Calendar"
    )
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class ExplorationTurn(Timestamped, Base):
    __tablename__ = "exploration_turns"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("operation_transactions.id", ondelete="SET NULL")
    )
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(
        String(40), nullable=False, default="explore", server_default="explore"
    )
    result_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("minutes >= 1 AND minutes <= 1440", name="ck_exploration_turn_minutes"),
        Index("ix_exploration_turns_scene", "scene_id", "created_at", "id"),
    )


class TravelLeg(Timestamped, Base):
    __tablename__ = "travel_legs"
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    from_location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="SET NULL")
    )
    to_location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="SET NULL"), nullable=False
    )
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("operation_transactions.id", ondelete="SET NULL")
    )
    distance_miles: Mapped[float] = mapped_column(Float, nullable=False)
    pace: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal", server_default="normal"
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="completed", server_default="completed"
    )
    details_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("distance_miles >= 0", name="ck_travel_leg_distance"),
        CheckConstraint("pace IN ('fast','normal','slow')", name="ck_travel_leg_pace"),
        CheckConstraint("duration_minutes >= 0", name="ck_travel_leg_duration"),
        CheckConstraint(
            "status IN ('planned','completed','interrupted')", name="ck_travel_leg_status"
        ),
        Index("ix_travel_legs_campaign", "campaign_id", "created_at", "id"),
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
