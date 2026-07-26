from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from dnd_dm_assistant.domain.rag import SearchHit, SearchQuery
from dnd_dm_assistant.domain.runtime_status import RuntimeModelStatus
from dnd_dm_assistant.domain.world import LocationGenerationPreview


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]
    environment: str


class ReadinessResponse(BaseModel):
    ready: bool
    database: Literal["ok"]
    knowledge_index: str
    models: RuntimeModelStatus


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str


class KnowledgeSearchResponse(BaseModel):
    hits: tuple[SearchHit, ...]


class KnowledgeAnswerRequest(BaseModel):
    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
    ]
    search: SearchQuery | None = None


class AssistantTurnRequest(BaseModel):
    action: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
    ]


class VersionedResponse(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    version: int


class CampaignCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: str | None = None
    world_setting: str | None = None
    current_time: datetime | None = None
    current_location_id: str | None = None
    status: str = "active"
    ruleset: Literal["dnd5e"] = "dnd5e"
    primary_rules_year: Literal[2024] = 2024
    allow_legacy: bool = False
    encumbrance_mode: Literal["standard", "variant", "none"] = "standard"


class CampaignPatch(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    description: str | None = None
    world_setting: str | None = None
    current_time: datetime | None = None
    current_location_id: str | None = None
    status: str | None = None
    allow_legacy: bool | None = None
    encumbrance_mode: Literal["standard", "variant", "none"] | None = None
    version: int | None = Field(None, ge=1)


class CampaignResponse(VersionedResponse):
    name: str
    description: str | None
    world_setting: str | None
    current_time: datetime | None
    current_location_id: str | None
    status: str
    ruleset: Literal["dnd5e"]
    primary_rules_year: Literal[2024]
    allow_legacy: bool
    encumbrance_mode: Literal["standard", "variant", "none"]


class CharacterCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    race: str | None = None
    background: str | None = None
    class_name: str | None = None
    level: int = Field(1, ge=1, le=20)
    experience: int = Field(0, ge=0)
    armor_class: int = Field(10, ge=0, le=99)
    speed: int = Field(30, ge=0, le=1000)
    ability_scores: dict[str, int] = Field(default_factory=dict)
    hp: int = Field(0, ge=0)
    max_hp: int = Field(0, ge=0)
    inventory: list[Any] = Field(default_factory=list)
    equipment: list[Any] = Field(default_factory=list)
    proficiencies: list[Any] = Field(default_factory=list)
    skills: dict[str, Any] = Field(default_factory=dict)
    features: list[Any] = Field(default_factory=list)
    actions: list[Any] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)
    spells: list[Any] = Field(default_factory=list)
    spellcasting: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_hp(self) -> CharacterCreate:
        if self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class CharacterPatch(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    race: str | None = None
    background: str | None = None
    class_name: str | None = None
    level: int | None = Field(None, ge=1, le=20)
    experience: int | None = Field(None, ge=0)
    armor_class: int | None = Field(None, ge=0, le=99)
    speed: int | None = Field(None, ge=0, le=1000)
    ability_scores: dict[str, int] | None = None
    hp: int | None = Field(None, ge=0)
    max_hp: int | None = Field(None, ge=0)
    inventory: list[Any] | None = None
    equipment: list[Any] | None = None
    proficiencies: list[Any] | None = None
    skills: dict[str, Any] | None = None
    features: list[Any] | None = None
    actions: list[Any] | None = None
    resources: dict[str, Any] | None = None
    spells: list[Any] | None = None
    spellcasting: dict[str, Any] | None = None
    notes: str | None = None
    version: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_hp(self) -> CharacterPatch:
        if self.hp is not None and self.max_hp is not None and self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class CharacterResponse(VersionedResponse):
    campaign_id: str
    name: str
    race: str | None
    background: str | None
    class_name: str | None
    level: int
    experience: int
    armor_class: int
    speed: int
    ability_scores: dict[str, int]
    hp: int
    max_hp: int
    inventory: list[Any]
    equipment: list[Any]
    proficiencies: list[Any]
    skills: dict[str, Any]
    features: list[Any]
    actions: list[Any]
    resources: dict[str, Any]
    spells: list[Any]
    spellcasting: dict[str, Any]
    notes: str | None


class NPCCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: str | None = None
    alignment: str | None = None
    attitude: str | None = None
    personality: str | None = None
    goal: str | None = None
    fear: str | None = None
    armor_class: int = Field(10, ge=0, le=99)
    hp: int = Field(1, ge=0)
    max_hp: int = Field(1, ge=0)
    speed: int = Field(30, ge=0, le=1000)
    ability_scores: dict[str, int] = Field(default_factory=dict)
    challenge_rating: str | None = None
    actions: list[Any] = Field(default_factory=list)
    equipment: list[Any] = Field(default_factory=list)
    relationship: str | None = None
    secrets: str | None = None
    known_information: str | None = None
    location_id: str | None = None
    status: str = "active"

    @model_validator(mode="after")
    def validate_hp(self) -> NPCCreate:
        if self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class NPCPatch(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    description: str | None = None
    alignment: str | None = None
    attitude: str | None = None
    personality: str | None = None
    goal: str | None = None
    fear: str | None = None
    armor_class: int | None = Field(None, ge=0, le=99)
    hp: int | None = Field(None, ge=0)
    max_hp: int | None = Field(None, ge=0)
    speed: int | None = Field(None, ge=0, le=1000)
    ability_scores: dict[str, int] | None = None
    challenge_rating: str | None = None
    actions: list[Any] | None = None
    equipment: list[Any] | None = None
    relationship: str | None = None
    secrets: str | None = None
    known_information: str | None = None
    location_id: str | None = None
    status: str | None = None
    version: int | None = Field(None, ge=1)


class NPCResponse(VersionedResponse):
    campaign_id: str
    name: str
    description: str | None
    alignment: str | None
    attitude: str | None
    personality: str | None
    goal: str | None
    fear: str | None
    armor_class: int
    hp: int
    max_hp: int
    speed: int
    ability_scores: dict[str, int]
    challenge_rating: str | None
    actions: list[Any]
    equipment: list[Any]
    relationship: str | None
    secrets: str | None
    known_information: str | None
    location_id: str | None
    status: str


class LocationCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    parent_location_id: str | None = None
    depth: int = Field(1, ge=1, le=10)
    description: str | None = None
    interactive_objects: list[Any] = Field(default_factory=list)
    secrets: str | None = None
    discovered: bool = True
    notes: str | None = None


class LocationPatch(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    parent_location_id: str | None = None
    depth: int | None = Field(None, ge=1, le=10)
    description: str | None = None
    interactive_objects: list[Any] | None = None
    secrets: str | None = None
    discovered: bool | None = None
    notes: str | None = None
    version: int | None = Field(None, ge=1)


class QuestCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: str | None = None
    quest_type: Literal["main", "side", "personal", "faction"] = "side"
    giver: str | None = None
    reward: str | None = None
    xp_reward: int = Field(0, ge=0)
    xp_awarded: bool = False
    status: str = "open"
    notes: str | None = None


class QuestPatch(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    description: str | None = None
    quest_type: Literal["main", "side", "personal", "faction"] | None = None
    giver: str | None = None
    reward: str | None = None
    xp_reward: int | None = Field(None, ge=0)
    xp_awarded: bool | None = None
    status: str | None = None
    notes: str | None = None
    version: int | None = Field(None, ge=1)


class ClueCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: str | None = None
    player_text: str | None = None
    dm_truth: str | None = None
    verified: bool = False
    quest_id: str | None = None
    discovered: bool = False
    discovered_at: datetime | None = None
    source_event_id: str | None = None


class CluePatch(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    description: str | None = None
    player_text: str | None = None
    dm_truth: str | None = None
    verified: bool | None = None
    quest_id: str | None = None
    discovered: bool | None = None
    discovered_at: datetime | None = None
    source_event_id: str | None = None
    version: int | None = Field(None, ge=1)


class EventCreate(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    event_type: str = "note"
    description: str | None = None
    occurred_at: datetime | None = None
    location_id: str | None = None
    visibility: Literal["dm", "players", "public"] = "dm"
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class EventPatch(BaseModel):
    title: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    event_type: str | None = None
    description: str | None = None
    occurred_at: datetime | None = None
    location_id: str | None = None
    visibility: Literal["dm", "players", "public"] | None = None
    metadata_json: dict[str, Any] | None = None
    version: int | None = Field(None, ge=1)


class CombatCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    scene_id: str | None = None
    status: str = "active"
    round_number: int = Field(1, ge=1)
    current_turn_index: int = Field(0, ge=0)
    difficulty: Literal["trivial", "low", "moderate", "high"] | None = None
    base_xp: int = Field(0, ge=0)
    difficulty_adjustments: list[Any] = Field(default_factory=list)
    xp_awarded: bool = False


class CombatPatch(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    scene_id: str | None = None
    status: str | None = None
    round_number: int | None = Field(None, ge=1)
    current_turn_index: int | None = Field(None, ge=0)
    difficulty: Literal["trivial", "low", "moderate", "high"] | None = None
    base_xp: int | None = Field(None, ge=0)
    difficulty_adjustments: list[Any] | None = None
    xp_awarded: bool | None = None
    version: int | None = Field(None, ge=1)


class CombatantCreate(BaseModel):
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    entity_type: str = "monster"
    entity_id: str | None = None
    initiative: int = Field(0, ge=-100, le=1000)
    armor_class: int = Field(10, ge=0, le=99)
    hp: int = Field(0, ge=0)
    max_hp: int = Field(0, ge=0)
    conditions: list[Any] = Field(default_factory=list)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_hp(self) -> CombatantCreate:
        if self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class CombatantPatch(BaseModel):
    display_name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    entity_type: str | None = None
    entity_id: str | None = None
    initiative: int | None = Field(None, ge=-100, le=1000)
    armor_class: int | None = Field(None, ge=0, le=99)
    hp: int | None = Field(None, ge=0)
    max_hp: int | None = Field(None, ge=0)
    conditions: list[Any] | None = None
    is_active: bool | None = None
    version: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_hp(self) -> CombatantPatch:
        if self.hp is not None and self.max_hp is not None and self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class ConditionCreate(BaseModel):
    condition_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    source: str | None = None
    duration: str | None = None
    notes: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ConditionPatch(BaseModel):
    condition_name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ] = None
    source: str | None = None
    duration: str | None = None
    notes: str | None = None
    details: dict[str, Any] | None = None
    version: int | None = Field(None, ge=1)


class ConnectionCreate(BaseModel):
    to_location_id: str
    label: str | None = None
    travel_time: str | None = None
    bidirectional: bool = True


class ConnectionPatch(BaseModel):
    label: str | None = None
    travel_time: str | None = None
    bidirectional: bool | None = None
    version: int | None = Field(None, ge=1)


class StateSnapshot(BaseModel):
    campaign: dict[str, Any]
    characters: tuple[dict[str, Any], ...]
    npcs: tuple[dict[str, Any], ...]
    locations: tuple[dict[str, Any], ...]
    quests: tuple[dict[str, Any], ...]
    open_clues: tuple[dict[str, Any], ...]
    active_combats: tuple[dict[str, Any], ...]
    as_of: datetime


class CampaignBackup(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    exported_at: datetime
    campaign: dict[str, Any]
    characters: tuple[dict[str, Any], ...] = ()
    conditions: tuple[dict[str, Any], ...] = ()
    npcs: tuple[dict[str, Any], ...] = ()
    locations: tuple[dict[str, Any], ...] = ()
    connections: tuple[dict[str, Any], ...] = ()
    quests: tuple[dict[str, Any], ...] = ()
    clues: tuple[dict[str, Any], ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    combats: tuple[dict[str, Any], ...] = ()
    combatants: tuple[dict[str, Any], ...] = ()
    world_items: tuple[dict[str, Any], ...] = ()
    monsters: tuple[dict[str, Any], ...] = ()
    scenes: tuple[dict[str, Any], ...] = ()
    scene_participants: tuple[dict[str, Any], ...] = ()


class CampaignImportRequest(BaseModel):
    backup: CampaignBackup
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None


class NPCGenerationRequest(BaseModel):
    mode: Literal["quick", "guided"] = "quick"
    brief: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    answers: dict[str, str] = Field(default_factory=dict)


class LocationGenerationRequest(BaseModel):
    brief: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    maximum_depth: int = Field(default=3, ge=1, le=5)
    scale: Literal["small", "medium", "large"] = "medium"


class LocationGenerationConfirmRequest(BaseModel):
    preview: LocationGenerationPreview


class WorldItemCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: str | None = None
    category: str = "misc"
    quantity: int = Field(default=1, ge=1, le=10_000)
    unit_weight_lb: float = Field(default=0, ge=0, le=100_000)
    price_cp: int = Field(default=0, ge=0, le=1_000_000_000)
    source_record_id: str | None = None
    source_label: Literal["official", "legacy", "custom", "ai_generated"] = "custom"
    location_id: str | None = None
    owner_character_id: str | None = None
    is_equipped: bool = False
    is_hidden: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ItemPickupRequest(BaseModel):
    character_id: str
    quantity: int = Field(default=1, ge=1)
    version: int = Field(ge=1)


class MonsterCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    source_record_id: str | None = None
    source_name: str | None = None
    armor_class: int = Field(default=10, ge=0, le=99)
    hp: int = Field(default=1, ge=0)
    max_hp: int = Field(default=1, ge=0)
    speed: int = Field(default=30, ge=0, le=1_000)
    ability_scores: dict[str, int] = Field(default_factory=dict)
    challenge_rating: str | None = None
    actions: list[Any] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_hp(self) -> MonsterCreate:
        if self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class SceneCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    location_id: str | None = None
    description: str | None = None
    status: Literal["draft", "active", "closed"] = "active"
    notes: str | None = None


class SceneParticipantCreate(BaseModel):
    entity_type: Literal["character", "npc", "monster"]
    entity_id: str
    role: str = "present"
    visible: bool = True
    notes: str | None = None


class SceneCombatStartRequest(BaseModel):
    name: str | None = None
