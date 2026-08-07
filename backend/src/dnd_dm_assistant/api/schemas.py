from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from dnd_dm_assistant.domain.encounters import EncounterOperation
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


class SafeModeRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=2_000)


class BackupCreateRequest(BaseModel):
    label: str = Field(default="手动恢复点", min_length=1, max_length=200)


class RestoreConfirmRequest(BaseModel):
    confirm_token: str = Field(min_length=16, max_length=200)
    confirmation: str = Field(min_length=1, max_length=20)


class HouseRuleOverrideRequest(BaseModel):
    rule_key: str = Field(min_length=1, max_length=160)
    core_value: Any
    override_value: Any
    source: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)
    enabled: bool = True


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
    mode: Literal["quick", "narrative", "combat", "general"] = "quick"
    user_message: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
        ]
        | None
    ) = None
    remember_conversation: bool = False
    use_conversation_history: bool = False
    include_campaign_state: bool = True


class AssistantConversationTurnRequest(BaseModel):
    user_message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
    ]
    assistant_message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000),
    ]


class VersionedResponse(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    version: int


class EncounterAdjustmentCreate(BaseModel):
    scene_id: str = Field(min_length=1, max_length=36)
    combat_id: str | None = Field(default=None, min_length=1, max_length=36)
    source_event_id: str | None = Field(default=None, min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)
    difficulty_shift: Literal[-1, 0, 1] = 0
    operations: list[EncounterOperation] = Field(default_factory=list, max_length=8)


class EncounterAdjustmentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    reason: str | None = Field(default=None, min_length=1, max_length=2_000)
    difficulty_shift: Literal[-1, 0, 1] | None = None
    operations: list[EncounterOperation] | None = Field(default=None, max_length=8)
    version: int | None = Field(default=None, ge=1)


class CampaignCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: str | None = None
    world_setting: str | None = None
    current_time: datetime | None = None
    current_location_id: str | None = None
    status: Literal["active", "archived"] = "active"
    ruleset: Literal["dnd5e"] = "dnd5e"
    primary_rules_year: Literal[2024] = 2024
    allow_legacy: bool = False
    encumbrance_mode: Literal["standard", "variant", "none"] = "standard"
    enabled_rule_extensions: list[str] = Field(default_factory=list, max_length=30)
    enabled_content_packs: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_rule_extensions(self) -> CampaignCreate:
        from dnd_dm_assistant.domain.content_packs import (
            validate_content_pack_compatibility,
        )
        from dnd_dm_assistant.domain.rule_extensions import normalize_enabled_extensions

        self.enabled_rule_extensions = normalize_enabled_extensions(
            self.enabled_rule_extensions,
            allow_legacy=self.allow_legacy,
        )
        self.enabled_content_packs = validate_content_pack_compatibility(
            self.enabled_content_packs,
            allow_legacy=self.allow_legacy,
            primary_rules_year=self.primary_rules_year,
        )
        return self


class CampaignPatch(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    description: str | None = None
    world_setting: str | None = None
    current_time: datetime | None = None
    current_location_id: str | None = None
    status: Literal["active", "archived"] | None = None
    allow_legacy: bool | None = None
    encumbrance_mode: Literal["standard", "variant", "none"] | None = None
    enabled_rule_extensions: list[str] | None = Field(default=None, max_length=30)
    enabled_content_packs: list[str] | None = Field(default=None, max_length=12)
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
    enabled_rule_extensions: list[str]
    enabled_content_packs: list[str]


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
    max_hp_reduction: int = Field(0, ge=0)
    ability_score_reductions: dict[str, int] = Field(default_factory=dict)
    death_saves: dict[str, int] = Field(default_factory=lambda: {"successes": 0, "failures": 0})
    inventory: list[Any] = Field(default_factory=list)
    equipment: list[Any] = Field(default_factory=list)
    proficiencies: list[Any] = Field(default_factory=list)
    skills: dict[str, Any] = Field(default_factory=dict)
    features: list[Any] = Field(default_factory=list)
    actions: list[Any] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)
    spells: list[Any] = Field(default_factory=list)
    spellcasting: dict[str, Any] = Field(default_factory=dict)
    class_levels: dict[str, int] = Field(default_factory=dict)
    subclass_choices: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None
    dm_override_reason: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_hp(self) -> CharacterCreate:
        if self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        if self.max_hp_reduction > self.max_hp:
            raise ValueError("max_hp_reduction cannot exceed max_hp")
        if any(
            self.death_saves.get(key, 0) < 0 or self.death_saves.get(key, 0) > 3
            for key in ("successes", "failures")
        ):
            raise ValueError("death save successes and failures must be between 0 and 3")
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
    max_hp: int | None = Field(None, ge=1)
    max_hp_reduction: int | None = Field(None, ge=0)
    ability_score_reductions: dict[str, int] | None = None
    death_saves: dict[str, int] | None = None
    inventory: list[Any] | None = None
    equipment: list[Any] | None = None
    proficiencies: list[Any] | None = None
    skills: dict[str, Any] | None = None
    features: list[Any] | None = None
    actions: list[Any] | None = None
    resources: dict[str, Any] | None = None
    spells: list[Any] | None = None
    spellcasting: dict[str, Any] | None = None
    class_levels: dict[str, int] | None = None
    subclass_choices: dict[str, str] | None = None
    notes: str | None = None
    dm_override_reason: str | None = Field(default=None, max_length=2_000)
    version: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_hp(self) -> CharacterPatch:
        if self.hp is not None and self.max_hp is not None and self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        if (
            self.max_hp_reduction is not None
            and self.max_hp is not None
            and self.max_hp_reduction > self.max_hp
        ):
            raise ValueError("max_hp_reduction cannot exceed max_hp")
        if self.death_saves is not None and any(
            self.death_saves.get(key, 0) < 0 or self.death_saves.get(key, 0) > 3
            for key in ("successes", "failures")
        ):
            raise ValueError("death save successes and failures must be between 0 and 3")
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
    max_hp_reduction: int
    ability_score_reductions: dict[str, int]
    death_saves: dict[str, int]
    inventory: list[Any]
    equipment: list[Any]
    proficiencies: list[Any]
    skills: dict[str, Any]
    features: list[Any]
    actions: list[Any]
    resources: dict[str, Any]
    spells: list[Any]
    spellcasting: dict[str, Any]
    class_levels: dict[str, int]
    subclass_choices: dict[str, str]
    notes: str | None


class AdvancementStepRequest(BaseModel):
    class_name: str = Field(min_length=1, max_length=100)
    subclass_name: str | None = Field(default=None, max_length=100)
    hp_mode: Literal["fixed", "roll"] = "fixed"
    hp_roll: int | None = Field(default=None, ge=1, le=12)
    ability_increases: dict[str, int] = Field(default_factory=dict)
    feat_choice: str | None = Field(default=None, max_length=200)
    feature_choices: list[str] = Field(default_factory=list, max_length=30)
    feature_choices_by_key: dict[str, list[str]] = Field(default_factory=dict)
    subclass_feature_choices: dict[str, list[str]] = Field(default_factory=dict)
    spell_additions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    spell_removals: list[str] = Field(default_factory=list, max_length=100)
    dm_override_reason: str | None = Field(default=None, max_length=2_000)


class AdvancementPreviewRequest(AdvancementStepRequest):
    character_version: int = Field(ge=1)


class CharacterSheetOcrRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    image_base64: str = Field(min_length=4, max_length=17_000_000)


class AdvancementConfirmRequest(AdvancementPreviewRequest):
    preview_token: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=120)


class AdvancementBatchPreviewRequest(BaseModel):
    character_version: int = Field(ge=1)
    steps: list[AdvancementStepRequest] = Field(min_length=2, max_length=19)


class AdvancementBatchConfirmRequest(AdvancementBatchPreviewRequest):
    preview_token: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=120)


class RuleBlockCompileRequest(BaseModel):
    source_kind: Literal[
        "spell",
        "action",
        "feature",
        "item",
        "monster_action",
        "unknown",
    ]
    source: dict[str, Any]


class CompanionCreate(BaseModel):
    owner_character_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=200)
    companion_type: Literal["familiar", "animal_companion", "summon", "wild_shape", "form"]
    source_record_id: str | None = Field(default=None, max_length=100)
    template_json: dict[str, Any] = Field(default_factory=dict)
    hp: int = Field(1, ge=0)
    max_hp: int = Field(1, ge=1)
    armor_class: int = Field(10, ge=0, le=99)
    speed: int = Field(30, ge=0, le=1000)
    active: bool = True
    notes: str | None = None

    @model_validator(mode="after")
    def validate_hp(self) -> CompanionCreate:
        if self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class CompanionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    source_record_id: str | None = Field(default=None, max_length=100)
    template_json: dict[str, Any] | None = None
    hp: int | None = Field(default=None, ge=0)
    max_hp: int | None = Field(default=None, ge=1)
    armor_class: int | None = Field(default=None, ge=0, le=99)
    speed: int | None = Field(default=None, ge=0, le=1000)
    active: bool | None = None
    notes: str | None = None
    version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_hp(self) -> CompanionPatch:
        if self.hp is not None and self.max_hp is not None and self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class RestHitDieSelection(BaseModel):
    resource_pool_id: str = Field(min_length=1, max_length=36)
    roll: int = Field(ge=1, le=20)


class RestParticipantInput(BaseModel):
    character_id: str = Field(min_length=1, max_length=36)
    character_version: int = Field(ge=1)
    hit_dice: list[RestHitDieSelection] = Field(default_factory=list, max_length=20)
    excluded_resource_keys: list[str] = Field(default_factory=list, max_length=50)


class RestPreviewRequest(BaseModel):
    rest_type: Literal["short", "long"]
    duration_minutes: int = Field(ge=1, le=24 * 60)
    interrupted: bool = False
    interruption_reason: str | None = Field(default=None, max_length=2_000)
    fallback_to_short_rest: bool = False
    participants: list[RestParticipantInput] = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=4_000)
    dm_override_reason: str | None = Field(default=None, max_length=2_000)


class RestConfirmRequest(RestPreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


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
    status: Literal["active", "ended", "archived"] = "active"
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
    status: Literal["active", "ended", "archived"] | None = None
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
    temporary_hp: int = Field(0, ge=0)
    max_hp_reduction: int = Field(0, ge=0)
    damage_resistances: list[str] = Field(default_factory=list)
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)
    conditions: list[Any] = Field(default_factory=list)
    concentration: dict[str, Any] = Field(default_factory=dict)
    speed_ft: int = Field(30, ge=0)
    movement_remaining_ft: int = Field(30, ge=0)
    action_available: bool = True
    bonus_action_available: bool = True
    reaction_available: bool = True
    snapshot_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_hp(self) -> CombatantCreate:
        if self.max_hp_reduction > self.max_hp:
            raise ValueError("max_hp_reduction cannot exceed max_hp")
        if self.hp + self.max_hp_reduction > self.max_hp:
            raise ValueError("hp cannot exceed effective max_hp")
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
    temporary_hp: int | None = Field(None, ge=0)
    max_hp_reduction: int | None = Field(None, ge=0)
    damage_resistances: list[str] | None = None
    damage_vulnerabilities: list[str] | None = None
    damage_immunities: list[str] | None = None
    condition_immunities: list[str] | None = None
    conditions: list[Any] | None = None
    concentration: dict[str, Any] | None = None
    speed_ft: int | None = Field(None, ge=0)
    movement_remaining_ft: int | None = Field(None, ge=0)
    action_available: bool | None = None
    bonus_action_available: bool | None = None
    reaction_available: bool | None = None
    snapshot_json: dict[str, Any] | None = None
    is_active: bool | None = None
    version: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_hp(self) -> CombatantPatch:
        reduction = self.max_hp_reduction
        if reduction is not None and self.max_hp is not None and reduction > self.max_hp:
            raise ValueError("max_hp_reduction cannot exceed max_hp")
        if (
            self.hp is not None
            and self.max_hp is not None
            and self.hp + (reduction or 0) > self.max_hp
        ):
            raise ValueError("hp cannot exceed effective max_hp")
        return self


class CombatResetCommand(BaseModel):
    combat_version: int = Field(ge=1)


class CombatDamageComponent(BaseModel):
    """One independently resisted segment of a mixed damage event."""

    amount: int = Field(ge=0, le=100_000)
    damage_type: str = Field(min_length=1, max_length=50)
    damage_tags: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_typed_damage(self) -> CombatDamageComponent:
        if self.damage_type.strip().lower() in {"mixed", "复合", "多种"}:
            raise ValueError(
                "each damage component needs one concrete damage_type; "
                "use multiple components for mixed damage"
            )
        return self


class CombatActionCommand(BaseModel):
    action_type: Literal["damage", "heal"]
    target_combatant_id: str = Field(min_length=1, max_length=36)
    target_version: int = Field(ge=1)
    actor_combatant_id: str | None = Field(default=None, min_length=1, max_length=36)
    actor_version: int | None = Field(default=None, ge=1)
    action_cost: Literal[
        "action", "bonus_action", "reaction", "legendary_action", "lair_action", "none"
    ] = "none"
    action_name: str | None = Field(default=None, max_length=200)
    resolution_note: str | None = Field(default=None, max_length=1_000)
    amount: int = Field(ge=0, le=100_000)
    damage_type: str | None = Field(default=None, max_length=50)
    damage_components: list[CombatDamageComponent] = Field(default_factory=list, max_length=20)
    damage_tags: list[str] = Field(default_factory=list, max_length=20)
    critical_hit: bool = False
    is_attack: bool = False
    attack_ability: str | None = Field(default=None, max_length=30)
    is_weapon_attack: bool = False
    is_spell_attack: bool = False
    is_sorcerer_spell: bool = False
    attack_roll_total: int | None = Field(default=None, ge=-100, le=1_000)
    attack_d20: int | None = Field(default=None, ge=1, le=20)
    attack_range_ft: int | None = Field(default=None, ge=0, le=10_000)
    ignore_cover: bool = False
    attack_roll_mode: Literal["normal", "advantage", "disadvantage"] | None = None
    attack_adjudication_note: str | None = Field(default=None, max_length=1_000)
    help_effect_id: str | None = Field(default=None, min_length=1, max_length=36)
    help_effect_version: int | None = Field(default=None, ge=1)
    dm_override: bool = False
    override_reason: str | None = Field(default=None, max_length=1_000)
    recharge_key: str | None = Field(default=None, max_length=200)
    recharge_consume: bool = False
    legendary_cost: int | None = Field(default=None, ge=1, le=10)
    legendary_pool_max: int | None = Field(default=None, ge=1, le=10)
    action_window_id: str | None = Field(default=None, min_length=1, max_length=36)
    reaction_window_id: str | None = Field(default=None, min_length=1, max_length=36)
    reaction_trigger: str | None = Field(default=None, max_length=1_000)
    reaction_event: (
        Literal[
            "leaves_reach",
            "enters_reach",
            "takes_damage",
            "hit_by_attack",
            "casts_spell",
            "turn_end",
        ]
        | None
    ) = None
    resource_key: str | None = Field(default=None, max_length=120)
    resource_cost: int = Field(default=0, ge=0, le=100)
    sequence_id: str | None = Field(default=None, max_length=120)
    sequence_step: int | None = Field(default=None, ge=0, le=50)
    sequence_size: int | None = Field(default=None, ge=1, le=50)
    conditions_to_apply: list[str] = Field(default_factory=list, max_length=20)
    condition_duration: (
        Literal[
            "actor_turn_start",
            "actor_turn_end",
            "target_turn_start",
            "target_turn_end",
            "rounds",
            "minutes",
            "until_save",
            "until_removed",
        ]
        | None
    ) = None
    condition_duration_value: int | None = Field(default=None, ge=1, le=10_000)
    condition_save_dc: int | None = Field(default=None, ge=0, le=99)
    condition_save_ability: str | None = Field(default=None, max_length=30)
    forced_movement_distance_ft: int | None = Field(default=None, ge=1, le=1_000)
    forced_movement_direction: Literal["away", "toward"] | None = None
    # Optional authoritative area proof for direct player-side area confirms.
    # Player-roll prompts already carry these fields; keeping them on the
    # ordinary command closes the old path where the UI checked the map but
    # the backend accepted a stale or fabricated target list.
    area_shape: Literal["cone", "line", "cube", "sphere", "cylinder"] | None = None
    area_size_ft: int | None = Field(default=None, ge=5, le=1_000)
    area_width_ft: int | None = Field(default=None, ge=5, le=1_000)
    area_height_ft: int | None = Field(default=None, ge=5, le=1_000)
    area_anchor_height_ft: int = Field(default=0, ge=-10_000, le=10_000)
    area_anchor_row: int | None = Field(default=None, ge=1, le=1_000)
    area_anchor_col: int | None = Field(default=None, ge=1, le=1_000)
    area_include_actor: bool = False
    requires_explicit_elevation: bool = False

    @model_validator(mode="after")
    def validate_action(self) -> CombatActionCommand:
        if self.action_type == "damage":
            if self.damage_components:
                if sum(component.amount for component in self.damage_components) != self.amount:
                    raise ValueError("damage amount must equal the sum of damage_components")
            elif not (self.damage_type or "").strip():
                raise ValueError("damage_type is required for damage")
            elif self.damage_type.strip().lower() in {"mixed", "复合", "多种"}:
                raise ValueError("mixed damage requires explicit damage_components for each type")
        elif self.damage_components:
            raise ValueError("damage_components are only valid for damage actions")
        if self.dm_override and not (self.override_reason or "").strip():
            raise ValueError("override_reason is required for a DM override")
        if self.recharge_consume and not (self.recharge_key or "").strip():
            raise ValueError("recharge_key is required when consuming a recharge action")
        if self.resource_cost and not (self.resource_key or "").strip():
            raise ValueError("resource_key is required when consuming a feature resource")
        if self.resource_key is not None and not self.resource_cost:
            raise ValueError("resource_cost is required with resource_key")
        if self.action_cost == "legendary_action" and (
            self.legendary_cost is None or self.legendary_pool_max is None
        ):
            raise ValueError(
                "legendary_cost and legendary_pool_max are required for a legendary action"
            )
        if self.action_cost != "legendary_action" and (
            self.legendary_cost is not None or self.legendary_pool_max is not None
        ):
            raise ValueError("legendary fields are only valid for a legendary action")
        if (
            self.action_cost not in {"legendary_action", "lair_action"}
            and self.action_window_id is not None
        ):
            raise ValueError("action_window_id is only valid for legendary or lair actions")
        if self.action_cost != "reaction" and self.reaction_window_id is not None:
            raise ValueError("reaction_window_id is only valid for reactions")
        if self.action_cost == "reaction" and not (self.reaction_trigger or "").strip():
            raise ValueError("reaction_trigger is required for a monster reaction")
        if self.action_cost != "reaction" and self.reaction_trigger is not None:
            raise ValueError("reaction_trigger is only valid for a reaction")
        if self.action_cost != "reaction" and self.reaction_event is not None:
            raise ValueError("reaction_event is only valid for a reaction")
        sequence_values = (self.sequence_id, self.sequence_step, self.sequence_size)
        if any(value is not None for value in sequence_values) and not all(
            value is not None for value in sequence_values
        ):
            raise ValueError("sequence_id, sequence_step and sequence_size are required together")
        if self.sequence_step is not None and self.sequence_size is not None:
            if self.sequence_step >= self.sequence_size:
                raise ValueError("sequence_step must be smaller than sequence_size")
            if self.sequence_step == 0 and self.action_cost == "none":
                raise ValueError("the first sequence step must spend an action resource")
            if self.sequence_step > 0 and self.action_cost != "none":
                raise ValueError("only the first sequence step may spend an action resource")
        if self.conditions_to_apply and self.condition_duration is None:
            raise ValueError("condition_duration is required for structured monster conditions")
        if self.condition_duration is not None and not self.conditions_to_apply:
            raise ValueError("conditions_to_apply is required with condition_duration")
        if (
            self.condition_duration in {"rounds", "minutes"}
            and self.condition_duration_value is None
        ):
            raise ValueError("condition_duration_value is required for timed conditions")
        if self.condition_duration == "until_save" and (
            self.condition_save_dc is None or not (self.condition_save_ability or "").strip()
        ):
            raise ValueError(
                "condition_save_dc and condition_save_ability are required for until_save"
            )
        if (
            self.condition_duration not in {"rounds", "minutes"}
            and self.condition_duration_value is not None
        ):
            raise ValueError("condition_duration_value is only valid for rounds or minutes")
        if self.condition_duration != "until_save" and (
            self.condition_save_dc is not None or self.condition_save_ability is not None
        ):
            raise ValueError("condition save fields are only valid for until_save")
        if (self.forced_movement_distance_ft is None) != (self.forced_movement_direction is None):
            raise ValueError("forced movement distance and direction are required together")
        area_fields = (
            self.area_shape,
            self.area_size_ft,
            self.area_anchor_row,
            self.area_anchor_col,
        )
        if any(value is not None for value in area_fields) and not all(
            value is not None for value in area_fields
        ):
            raise ValueError("area_shape, area_size_ft and area anchor are required together")
        if self.area_shape is None and any(
            value is not None for value in (self.area_width_ft, self.area_height_ft)
        ):
            raise ValueError("area width and height require area_shape")
        if self.action_cost != "none" and (
            self.actor_combatant_id is None or self.actor_version is None
        ):
            raise ValueError(
                "actor_combatant_id and actor_version are required when an action is spent"
            )
        if self.is_attack and (self.actor_combatant_id is None or self.actor_version is None):
            raise ValueError("actor_combatant_id and actor_version are required for an attack")
        if not self.is_attack and (
            self.attack_ability is not None
            or self.is_weapon_attack
            or self.is_spell_attack
            or self.is_sorcerer_spell
            or self.attack_roll_total is not None
            or self.attack_d20 is not None
            or self.attack_range_ft is not None
            or self.ignore_cover
            or self.attack_roll_mode is not None
            or self.attack_adjudication_note is not None
            or self.help_effect_id is not None
            or self.help_effect_version is not None
        ):
            raise ValueError("attack adjudication and Help are only valid for an attack")
        if self.is_sorcerer_spell and not self.is_spell_attack:
            raise ValueError("is_sorcerer_spell requires is_spell_attack")
        if self.ignore_cover and not self.dm_override:
            raise ValueError("ignoring cover requires an explicit DM override")
        if (self.help_effect_id is None) != (self.help_effect_version is None):
            raise ValueError("help_effect_id and help_effect_version must be provided together")
        return self


class CombatActionBatchItem(BaseModel):
    """One idempotent member of a multi-target combat confirmation."""

    command: CombatActionCommand
    idempotency_key: str = Field(min_length=1, max_length=200)


class CombatActionBatchCommand(BaseModel):
    """Preflight and confirm several target resolutions as one UI operation."""

    items: list[CombatActionBatchItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_batch(self) -> CombatActionBatchCommand:
        keys = [item.idempotency_key for item in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("batch idempotency keys must be unique")
        first = self.items[0].command
        if first.action_cost == "none":
            raise ValueError("the first batch action must spend an action resource")
        for item in self.items[1:]:
            if item.command.action_cost != "none":
                raise ValueError("only the first batch action may spend an action resource")
        return self


class CombatManeuverCommand(BaseModel):
    action_type: Literal[
        "dash",
        "stand_up",
        "grapple",
        "shove",
        "dodge",
        "help",
        "ready",
        "search",
        "hide",
        "disengage",
        "use_item",
        "object_interaction",
    ]
    actor_combatant_id: str = Field(min_length=1, max_length=36)
    actor_version: int = Field(ge=1)
    target_combatant_id: str | None = Field(default=None, min_length=1, max_length=36)
    target_version: int | None = Field(default=None, ge=1)
    outcome: Literal["success", "failure"] | None = None
    shove_mode: Literal["prone", "push"] | None = None
    push_distance_ft: int | None = Field(default=None, ge=1, le=1_000)
    adjudication_note: str | None = Field(default=None, max_length=1_000)
    help_trigger: str | None = Field(default=None, max_length=500)
    ready_phase: Literal["prepare", "trigger"] = "prepare"
    ready_trigger: str | None = Field(default=None, max_length=500)
    ready_response: str | None = Field(default=None, max_length=500)
    ready_effect_id: str | None = Field(default=None, min_length=1, max_length=36)
    ready_effect_version: int | None = Field(default=None, ge=1)
    item_id: str | None = Field(default=None, min_length=1, max_length=36)
    item_version: int | None = Field(default=None, ge=1)
    object_id: str | None = Field(default=None, min_length=1, max_length=36)
    object_version: int | None = Field(default=None, ge=1)
    object_state: (
        Literal["active", "open", "closed", "destroyed", "disarmed", "picked_up"] | None
    ) = None

    @model_validator(mode="after")
    def validate_maneuver(self) -> CombatManeuverCommand:
        targeted = self.action_type in {"grapple", "shove", "help", "search"}
        if targeted and (self.target_combatant_id is None or self.target_version is None):
            raise ValueError(
                "target_combatant_id and target_version are required for grapple/shove/help/search"
            )
        if not targeted and (
            self.target_combatant_id is not None or self.target_version is not None
        ):
            raise ValueError(f"{self.action_type} does not accept a target")
        adjudicated = self.action_type in {
            "grapple",
            "shove",
            "search",
            "hide",
            "use_item",
            "object_interaction",
        }
        if adjudicated and self.outcome is None:
            raise ValueError(f"{self.action_type} requires an explicit DM-adjudicated outcome")
        if (adjudicated or self.action_type in {"help", "ready"}) and not (
            self.adjudication_note or ""
        ).strip():
            raise ValueError("adjudication_note is required for this DM-adjudicated action")
        if self.action_type == "shove" and self.shove_mode is None:
            raise ValueError("shove_mode is required for shove")
        if self.action_type != "shove" and self.shove_mode is not None:
            raise ValueError("shove_mode is only valid for shove")
        if self.action_type == "shove" and self.shove_mode == "push":
            if self.push_distance_ft is None:
                raise ValueError(
                    "push_distance_ft is required; the engine will not guess shove distance"
                )
        elif self.push_distance_ft is not None:
            raise ValueError("push_distance_ft is only valid for a shove push")
        if self.action_type == "help":
            if not (self.help_trigger or "").strip():
                raise ValueError("help_trigger is required for Help")
        elif self.help_trigger is not None:
            raise ValueError("help_trigger is only valid for Help")
        if self.action_type == "ready":
            if self.ready_phase == "prepare":
                if (
                    not (self.ready_trigger or "").strip()
                    or not (self.ready_response or "").strip()
                ):
                    raise ValueError(
                        "ready_trigger and ready_response are required to prepare Ready"
                    )
                if self.ready_effect_id is not None or self.ready_effect_version is not None:
                    raise ValueError("a prepared Ready action cannot reference an existing effect")
            else:
                if self.outcome is None:
                    raise ValueError("triggering Ready requires an explicit DM outcome")
                if self.ready_effect_id is None or self.ready_effect_version is None:
                    raise ValueError(
                        "ready_effect_id and ready_effect_version are required to trigger Ready"
                    )
                if self.ready_trigger is not None or self.ready_response is not None:
                    raise ValueError("a Ready trigger uses the trigger stored on the effect")
        elif (
            self.ready_phase != "prepare"
            or self.ready_trigger is not None
            or self.ready_response is not None
            or self.ready_effect_id is not None
            or self.ready_effect_version is not None
        ):
            raise ValueError("ready fields are only valid for Ready")
        if self.action_type == "use_item":
            if self.item_id is None or self.item_version is None:
                raise ValueError("use_item requires item_id and item_version")
        elif self.item_id is not None or self.item_version is not None:
            raise ValueError("item fields are only valid for use_item")
        if self.action_type == "object_interaction":
            if self.object_id is None or self.object_version is None or self.object_state is None:
                raise ValueError(
                    "object_interaction requires object_id, object_version and object_state"
                )
        elif (
            self.object_id is not None
            or self.object_version is not None
            or self.object_state is not None
        ):
            raise ValueError("object fields are only valid for object_interaction")
        return self


class CombatFeatureActionCommand(BaseModel):
    """Confirm one compiled class feature from the combat snapshot."""

    actor_combatant_id: str = Field(min_length=1, max_length=36)
    actor_version: int = Field(ge=1)
    feature_id: str = Field(min_length=1, max_length=120)
    selected_action: Literal["dash", "disengage", "hide"] | None = None
    outcome: Literal["success", "failure"] | None = None
    adjudication_note: str | None = Field(default=None, max_length=1_000)
    healing_total: int | None = Field(default=None, ge=0, le=100_000)
    healing_dice_count: int | None = Field(default=None, ge=1, le=100)
    condition_to_cure: Literal[
        "blinded",
        "charmed",
        "deafened",
        "diseased",
        "frightened",
        "paralyzed",
        "poisoned",
        "stunned",
    ] | None = None
    condition_to_remove: Literal["charmed", "frightened", "poisoned"] | None = None
    target_combatant_id: str | None = Field(default=None, min_length=1, max_length=36)
    target_version: int | None = Field(default=None, ge=1)
    dm_override: bool = False
    override_reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_feature_action(self) -> CombatFeatureActionCommand:
        if self.dm_override and not (self.override_reason or "").strip():
            raise ValueError("override_reason is required for a DM override")
        if (self.target_combatant_id is None) != (self.target_version is None):
            raise ValueError("target_combatant_id and target_version are required together")
        return self


class CombatPreDamageReactionCommand(BaseModel):
    """Resolve a persisted reaction window before the triggering damage lands."""

    reaction_window_id: str = Field(min_length=1, max_length=36)
    reaction_window_version: int = Field(ge=1)
    decision: Literal["accept", "reject"]
    feature_id: str | None = Field(default=None, min_length=1, max_length=120)
    reduction_roll: int | None = Field(default=None, ge=1, le=100)
    inputs: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_pre_damage_reaction(self) -> CombatPreDamageReactionCommand:
        if self.decision == "accept" and not (self.feature_id or "").strip():
            raise ValueError("使用伤害前反应时必须选择职业特性")
        if self.decision == "reject" and self.feature_id is not None:
            raise ValueError("放弃伤害前反应时不能携带职业特性")
        if self.decision == "reject" and (self.reduction_roll is not None or self.inputs):
            raise ValueError("放弃伤害前反应时不能携带执行输入")
        if (
            self.reduction_roll is not None
            and "reduction_roll" in self.inputs
            and self.inputs["reduction_roll"] != self.reduction_roll
        ):
            raise ValueError("兼容减伤骰字段与通用输入不一致")
        return self


class CombatDeflectRedirectCommand(BaseModel):
    """Resolve the second, zero-damage branch of Deflect Attacks."""

    redirect_window_id: str = Field(min_length=1, max_length=36)
    redirect_window_version: int = Field(ge=1)
    decision: Literal["accept", "reject"]
    target_combatant_id: str | None = Field(default=None, min_length=1, max_length=36)
    target_version: int | None = Field(default=None, ge=1)
    saving_throw_roll: int | None = Field(default=None, ge=-100, le=1_000)
    damage_rolls: list[int] = Field(default_factory=list, min_length=0, max_length=2)
    dm_override: bool = False
    override_reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_redirect(self) -> CombatDeflectRedirectCommand:
        if self.dm_override and not (self.override_reason or "").strip():
            raise ValueError("override_reason is required for a DM override")
        if self.decision == "accept":
            if (self.target_combatant_id is None) != (self.target_version is None):
                raise ValueError("target_combatant_id and target_version are required together")
            if self.target_combatant_id is None:
                raise ValueError("反击分支必须选择目标")
            if self.saving_throw_roll is None:
                raise ValueError("反击分支必须提交目标的敏捷豁免总值")
            if len(self.damage_rolls) != 2:
                raise ValueError("反击分支必须提交两枚武艺骰")
        elif (
            any(
                value is not None
                for value in (
                    self.target_combatant_id,
                    self.target_version,
                    self.saving_throw_roll,
                )
            )
            or self.damage_rolls
        ):
            raise ValueError("放弃反击分支时不能携带目标或骰值")
        return self


class _PlayerRollPromptBase(BaseModel):
    actor_combatant_id: str = Field(min_length=1, max_length=36)
    actor_version: int = Field(ge=1)
    action_cost: Literal[
        "action", "bonus_action", "reaction", "legendary_action", "lair_action", "none"
    ] = "action"
    action_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    resolution_type: Literal[
        "armor_class",
        "saving_throw",
        "ability_check",
        "skill_check",
    ]
    dc: int = Field(ge=0, le=99)
    ability: str | None = Field(default=None, max_length=30)
    # Jack of All Trades only applies when the caller explicitly confirms
    # that this is an ability check without proficiency.  ``None`` is
    # intentionally distinct from ``False`` so the server never guesses.
    ability_check_proficient: bool | None = None
    skill: str | None = Field(default=None, max_length=80)
    requires_sight: bool = False
    roll_formula: str = Field(default="1d20", min_length=1, max_length=50)
    damage_on_success: int = Field(default=0, ge=0, le=100_000)
    damage_on_failure: int = Field(default=0, ge=0, le=100_000)
    damage_components_on_success: list[CombatDamageComponent] = Field(
        default_factory=list, max_length=20
    )
    damage_components_on_failure: list[CombatDamageComponent] = Field(
        default_factory=list, max_length=20
    )
    damage_type: str | None = Field(default=None, max_length=50)
    damage_tags: list[str] = Field(default_factory=list, max_length=20)
    description: str | None = Field(default=None, max_length=2_000)
    recharge_key: str | None = Field(default=None, max_length=200)
    recharge_consume: bool = False
    legendary_cost: int | None = Field(default=None, ge=1, le=10)
    legendary_pool_max: int | None = Field(default=None, ge=1, le=10)
    action_window_id: str | None = Field(default=None, min_length=1, max_length=36)
    reaction_window_id: str | None = Field(default=None, min_length=1, max_length=36)
    reaction_trigger: str | None = Field(default=None, max_length=1_000)
    reaction_event: (
        Literal[
            "leaves_reach",
            "enters_reach",
            "takes_damage",
            "hit_by_attack",
            "casts_spell",
            "turn_end",
        ]
        | None
    ) = None
    sequence_id: str | None = Field(default=None, max_length=120)
    sequence_step: int | None = Field(default=None, ge=0, le=50)
    sequence_size: int | None = Field(default=None, ge=1, le=50)
    conditions_on_success: list[str] = Field(default_factory=list, max_length=20)
    conditions_on_failure: list[str] = Field(default_factory=list, max_length=20)
    condition_duration: (
        Literal[
            "actor_turn_start",
            "actor_turn_end",
            "target_turn_start",
            "target_turn_end",
            "rounds",
            "minutes",
            "until_save",
            "until_removed",
        ]
        | None
    ) = None
    condition_duration_value: int | None = Field(default=None, ge=1, le=10_000)
    condition_save_dc: int | None = Field(default=None, ge=0, le=99)
    condition_save_ability: str | None = Field(default=None, max_length=30)
    movement_on_success_ft: int | None = Field(default=None, ge=1, le=1_000)
    movement_on_failure_ft: int | None = Field(default=None, ge=1, le=1_000)
    movement_direction: Literal["away", "toward"] | None = None
    is_magical: bool = False
    area_shape: Literal["cone", "line", "cube", "sphere", "cylinder"] | None = None
    area_size_ft: int | None = Field(default=None, ge=5, le=1_000)
    area_width_ft: int | None = Field(default=None, ge=5, le=1_000)
    area_height_ft: int | None = Field(default=None, ge=5, le=1_000)
    area_anchor_height_ft: int = Field(default=0, ge=-10_000, le=10_000)
    area_anchor_row: int | None = Field(default=None, ge=1, le=1_000)
    area_anchor_col: int | None = Field(default=None, ge=1, le=1_000)
    area_include_actor: bool = False
    requires_explicit_elevation: bool = False
    dm_override: bool = False
    override_reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_roll_prompt(self) -> _PlayerRollPromptBase:
        if self.resolution_type == "saving_throw" and not (self.ability or "").strip():
            raise ValueError("ability is required for a saving throw")
        if self.ability_check_proficient is not None and self.resolution_type != "ability_check":
            raise ValueError("ability_check_proficient is only valid for ability checks")
        if self.resolution_type == "skill_check" and not (self.skill or "").strip():
            raise ValueError("skill is required for a skill check")
        for field_name in ("success", "failure"):
            components = getattr(self, f"damage_components_on_{field_name}")
            scalar_name = f"damage_on_{field_name}"
            scalar = getattr(self, scalar_name)
            if components:
                component_total = sum(component.amount for component in components)
                if scalar not in {0, component_total}:
                    raise ValueError(
                        f"{scalar_name} must equal the sum of damage_components_on_{field_name}"
                    )
                setattr(self, scalar_name, component_total)
        if (
            (
                self.damage_on_success > 0
                or self.damage_on_failure > 0
                or self.damage_components_on_success
                or self.damage_components_on_failure
            )
            and not (self.damage_type or "").strip()
            and not all(
                component.damage_type.strip()
                for component in (
                    *self.damage_components_on_success,
                    *self.damage_components_on_failure,
                )
            )
        ):
            raise ValueError("damage_type is required when the roll can deal damage")
        if self.recharge_consume and not (self.recharge_key or "").strip():
            raise ValueError("recharge_key is required when consuming a recharge action")
        if self.action_cost == "legendary_action" and (
            self.legendary_cost is None or self.legendary_pool_max is None
        ):
            raise ValueError(
                "legendary_cost and legendary_pool_max are required for a legendary action"
            )
        if self.action_cost == "reaction" and not (self.reaction_trigger or "").strip():
            raise ValueError("reaction_trigger is required for a monster reaction")
        if (
            self.action_cost not in {"legendary_action", "lair_action"}
            and self.action_window_id is not None
        ):
            raise ValueError("action_window_id is only valid for legendary or lair actions")
        if self.action_cost != "reaction" and self.reaction_window_id is not None:
            raise ValueError("reaction_window_id is only valid for reactions")
        if self.action_cost != "reaction" and self.reaction_trigger is not None:
            raise ValueError("reaction_trigger is only valid for a reaction")
        if self.action_cost != "reaction" and self.reaction_event is not None:
            raise ValueError("reaction_event is only valid for a reaction")
        sequence_values = (self.sequence_id, self.sequence_step, self.sequence_size)
        if any(value is not None for value in sequence_values) and not all(
            value is not None for value in sequence_values
        ):
            raise ValueError("sequence_id, sequence_step and sequence_size are required together")
        if self.sequence_step is not None and self.sequence_size is not None:
            if self.sequence_step >= self.sequence_size:
                raise ValueError("sequence_step must be smaller than sequence_size")
            if self.sequence_step == 0 and self.action_cost == "none":
                raise ValueError("the first sequence step must spend an action resource")
            if self.sequence_step > 0 and self.action_cost != "none":
                raise ValueError("only the first sequence step may spend an action resource")
        if (
            self.conditions_on_success or self.conditions_on_failure
        ) and self.condition_duration is None:
            raise ValueError("condition_duration is required for structured monster conditions")
        if self.condition_duration is not None and not (
            self.conditions_on_success or self.conditions_on_failure
        ):
            raise ValueError("a structured condition outcome is required with condition_duration")
        if (
            self.condition_duration in {"rounds", "minutes"}
            and self.condition_duration_value is None
        ):
            raise ValueError("condition_duration_value is required for timed conditions")
        if self.condition_duration == "until_save" and (
            self.condition_save_dc is None or not (self.condition_save_ability or "").strip()
        ):
            raise ValueError(
                "condition_save_dc and condition_save_ability are required for until_save"
            )
        if (
            self.condition_duration not in {"rounds", "minutes"}
            and self.condition_duration_value is not None
        ):
            raise ValueError("condition_duration_value is only valid for rounds or minutes")
        if self.condition_duration != "until_save" and (
            self.condition_save_dc is not None or self.condition_save_ability is not None
        ):
            raise ValueError("condition save fields are only valid for until_save")
        if (self.movement_on_success_ft or self.movement_on_failure_ft) and (
            self.movement_direction is None
        ):
            raise ValueError("movement_direction is required for structured forced movement")
        area_fields = (
            self.area_shape,
            self.area_size_ft,
            self.area_anchor_row,
            self.area_anchor_col,
        )
        if any(value is not None for value in area_fields) and not all(
            value is not None for value in area_fields
        ):
            raise ValueError("area prompts require shape, size, and anchor row/col")
        if self.area_shape == "line" and self.area_width_ft is None:
            raise ValueError("line prompts require area_width_ft")
        if self.area_shape != "line" and self.area_width_ft is not None:
            raise ValueError("area_width_ft is only valid for line prompts")
        if self.area_shape == "cylinder" and self.area_height_ft is None:
            raise ValueError("cylinder prompts require area_height_ft")
        if self.area_shape != "cylinder" and self.area_height_ft is not None:
            raise ValueError("area_height_ft is only valid for cylinder prompts")
        if self.requires_explicit_elevation and self.area_shape is None:
            raise ValueError("explicit elevation is only valid for an area prompt")
        if self.dm_override and not (self.override_reason or "").strip():
            raise ValueError("override_reason is required for a DM override")
        return self


class PlayerRollPromptCommand(_PlayerRollPromptBase):
    target_combatant_id: str = Field(min_length=1, max_length=36)
    target_version: int = Field(ge=1)
    # The target rolls the requested d20, while an optional separate target
    # receives the structured outcome.  This is used for player-originated
    # adjudications such as a character trying to make an enemy fall over.
    effect_target_combatant_id: str | None = Field(default=None, min_length=1, max_length=36)
    effect_target_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_roll_prompt_target(self) -> PlayerRollPromptCommand:
        if (self.effect_target_combatant_id is None) != (self.effect_target_version is None):
            raise ValueError(
                "effect_target_combatant_id and effect_target_version are required together"
            )
        return self


class PlayerRollPromptBatchTarget(BaseModel):
    target_combatant_id: str = Field(min_length=1, max_length=36)
    target_version: int = Field(ge=1)
    effect_target_combatant_id: str | None = Field(default=None, min_length=1, max_length=36)
    effect_target_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_effect_target(self) -> PlayerRollPromptBatchTarget:
        if (self.effect_target_combatant_id is None) != (self.effect_target_version is None):
            raise ValueError(
                "effect_target_combatant_id and effect_target_version are required together"
            )
        return self


class PlayerRollPromptBatchCommand(_PlayerRollPromptBase):
    """One action that creates a coordinated set of player saving-throw prompts."""

    targets: list[PlayerRollPromptBatchTarget] = Field(min_length=2, max_length=50)

    @model_validator(mode="after")
    def validate_batch_roll_prompt(self) -> PlayerRollPromptBatchCommand:
        if self.resolution_type != "saving_throw":
            raise ValueError("batch player-roll prompts are only valid for saving throws")
        target_ids = [target.target_combatant_id for target in self.targets]
        if len(set(target_ids)) != len(target_ids):
            raise ValueError("batch player-roll prompt targets must be unique")
        return self


class PlayerRollResolutionCommand(BaseModel):
    action_version: int = Field(ge=1)
    roll_total: int = Field(ge=-100, le=1_000)
    roll_totals: list[int] = Field(default_factory=list, min_length=0, max_length=2)
    bardic_inspiration_total: int | None = Field(default=None, ge=1, le=1_000)
    use_legendary_resistance: bool = False
    use_feature_reroll: bool = False
    use_stroke_of_luck: bool = False
    stroke_of_luck_total: int | None = Field(default=None, ge=-100, le=1_000)
    feature_reroll_reactor_id: str | None = Field(default=None, min_length=1, max_length=36)
    roll_intervention_id: str | None = Field(default=None, min_length=1, max_length=120)
    roll_intervention_inputs: dict[str, int] = Field(default_factory=dict)
    dm_note: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_roll_totals(self) -> PlayerRollResolutionCommand:
        if any(value < -100 or value > 1_000 for value in self.roll_totals):
            raise ValueError("roll_totals entries must be between -100 and 1000")
        if self.roll_totals and self.roll_total not in self.roll_totals:
            raise ValueError("roll_total must be one of roll_totals when both are provided")
        if self.use_stroke_of_luck and self.use_feature_reroll:
            raise ValueError("幸运一击不能与职业特性重掷叠加")
        if self.use_stroke_of_luck and self.use_legendary_resistance:
            raise ValueError("幸运一击不能与传奇抗性叠加")
        if self.use_stroke_of_luck and self.bardic_inspiration_total is not None:
            raise ValueError("幸运一击不能与吟游诗人激励骰在同一次提交中叠加")
        if self.roll_intervention_inputs and self.roll_intervention_id is None:
            raise ValueError("roll_intervention_inputs 需要 roll_intervention_id")
        if self.roll_intervention_id is not None and (
            self.use_feature_reroll
            or self.use_stroke_of_luck
            or self.bardic_inspiration_total is not None
        ):
            raise ValueError("通用掷骰干预不能与旧职业骰适配器在同一次提交中叠加")
        if self.stroke_of_luck_total is not None and not self.use_stroke_of_luck:
            raise ValueError("stroke_of_luck_total 只适用于确认使用幸运一击")
        if self.use_stroke_of_luck and self.stroke_of_luck_total is None:
            raise ValueError("使用幸运一击时必须提交天然 20 加调整值后的最终总值")
        return self


class MonsterAreaTargetResolution(BaseModel):
    target_combatant_id: str = Field(min_length=1, max_length=36)
    target_version: int = Field(ge=1)
    roll_total: int = Field(ge=-100, le=1_000)
    roll_totals: list[int] = Field(default_factory=list, min_length=0, max_length=2)
    use_legendary_resistance: bool = False

    @model_validator(mode="after")
    def validate_target_rolls(self) -> MonsterAreaTargetResolution:
        if any(value < -100 or value > 1_000 for value in self.roll_totals):
            raise ValueError("roll_totals entries must be between -100 and 1000")
        if self.roll_totals and self.roll_total not in self.roll_totals:
            raise ValueError("roll_total must be one of roll_totals when both are provided")
        return self


class MonsterAreaActionCommand(BaseModel):
    actor_combatant_id: str = Field(min_length=1, max_length=36)
    actor_version: int = Field(ge=1)
    action_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    action_cost: Literal[
        "action", "bonus_action", "reaction", "legendary_action", "lair_action"
    ] = "action"
    shape: Literal["cone", "line", "cube", "sphere", "cylinder"]
    size_ft: int = Field(ge=5, le=1_000)
    width_ft: int | None = Field(default=None, ge=5, le=1_000)
    height_ft: int | None = Field(default=None, ge=5, le=1_000)
    anchor_height_ft: int = Field(default=0, ge=-10_000, le=10_000)
    anchor_row: int = Field(ge=1, le=1_000)
    anchor_col: int = Field(ge=1, le=1_000)
    requires_line_of_sight: bool = True
    include_actor: bool = False
    requires_explicit_elevation: bool = False
    save_dc: int = Field(ge=0, le=99)
    save_ability: str = Field(min_length=1, max_length=30)
    damage_total: int = Field(ge=0, le=100_000)
    damage_type: str = Field(min_length=1, max_length=50)
    damage_components: list[CombatDamageComponent] = Field(default_factory=list, max_length=20)
    damage_tags: list[str] = Field(default_factory=list, max_length=20)
    half_damage_on_save: bool = False
    is_magical: bool = False
    targets: list[MonsterAreaTargetResolution] = Field(min_length=1, max_length=100)
    conditions_on_success: list[str] = Field(default_factory=list, max_length=20)
    conditions_on_failure: list[str] = Field(default_factory=list, max_length=20)
    condition_duration: (
        Literal[
            "actor_turn_start",
            "actor_turn_end",
            "target_turn_start",
            "target_turn_end",
            "rounds",
            "minutes",
            "until_save",
            "until_removed",
        ]
        | None
    ) = None
    condition_duration_value: int | None = Field(default=None, ge=1, le=10_000)
    condition_save_dc: int | None = Field(default=None, ge=0, le=99)
    condition_save_ability: str | None = Field(default=None, max_length=30)
    recharge_key: str | None = Field(default=None, max_length=200)
    recharge_consume: bool = False
    legendary_cost: int | None = Field(default=None, ge=1, le=10)
    legendary_pool_max: int | None = Field(default=None, ge=1, le=10)
    action_window_id: str | None = Field(default=None, min_length=1, max_length=36)
    reaction_window_id: str | None = Field(default=None, min_length=1, max_length=36)
    reaction_trigger: str | None = Field(default=None, max_length=1_000)
    reaction_event: (
        Literal[
            "leaves_reach",
            "enters_reach",
            "takes_damage",
            "hit_by_attack",
            "casts_spell",
            "turn_end",
        ]
        | None
    ) = None
    dm_override: bool = False
    override_reason: str | None = Field(default=None, max_length=1_000)
    dm_geometry_note: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ]

    @model_validator(mode="after")
    def validate_area_action(self) -> MonsterAreaActionCommand:
        if self.dm_override and not (self.override_reason or "").strip():
            raise ValueError("override_reason is required for a DM override")
        if self.shape == "line" and self.width_ft is None:
            raise ValueError("line areas require width_ft")
        if self.shape != "line" and self.width_ft is not None:
            raise ValueError("width_ft is only valid for line areas")
        if self.shape == "cylinder" and self.height_ft is None:
            raise ValueError("cylinder areas require height_ft")
        if self.shape != "cylinder" and self.height_ft is not None:
            raise ValueError("height_ft is only valid for cylinder areas")
        if self.damage_components:
            if sum(component.amount for component in self.damage_components) != self.damage_total:
                raise ValueError("damage_total must equal the sum of damage_components")
        elif self.damage_type.strip().lower() in {"mixed", "复合", "多种"}:
            raise ValueError("mixed area damage requires explicit damage_components for each type")
        if len({target.target_combatant_id for target in self.targets}) != len(self.targets):
            raise ValueError("area targets must be unique")
        if (self.conditions_on_success or self.conditions_on_failure) and (
            self.condition_duration is None
        ):
            raise ValueError("condition_duration is required for area conditions")
        if (
            self.condition_duration in {"rounds", "minutes"}
            and self.condition_duration_value is None
        ):
            raise ValueError("condition_duration_value is required for timed area conditions")
        if self.condition_duration == "until_save" and (
            self.condition_save_dc is None or not (self.condition_save_ability or "").strip()
        ):
            raise ValueError(
                "condition_save_dc and condition_save_ability are required for until_save"
            )
        if (
            self.condition_duration not in {"rounds", "minutes"}
            and self.condition_duration_value is not None
        ):
            raise ValueError("condition_duration_value is only valid for rounds or minutes")
        if self.condition_duration != "until_save" and (
            self.condition_save_dc is not None or self.condition_save_ability is not None
        ):
            raise ValueError("condition save fields are only valid for until_save")
        if self.recharge_consume and not (self.recharge_key or "").strip():
            raise ValueError("recharge_key is required when consuming recharge")
        if self.action_cost == "legendary_action" and (
            self.legendary_cost is None or self.legendary_pool_max is None
        ):
            raise ValueError("legendary area actions require cost and pool maximum")
        if self.action_cost != "legendary_action" and (
            self.legendary_cost is not None or self.legendary_pool_max is not None
        ):
            raise ValueError("legendary fields are only valid for legendary actions")
        if self.action_cost == "reaction" and not (self.reaction_trigger or "").strip():
            raise ValueError("reaction area actions require an explicit trigger")
        if self.action_cost != "reaction" and self.reaction_trigger is not None:
            raise ValueError("reaction_trigger is only valid for reactions")
        if self.action_cost != "reaction" and self.reaction_event is not None:
            raise ValueError("reaction_event is only valid for reactions")
        if (
            self.action_cost not in {"legendary_action", "lair_action"}
            and self.action_window_id is not None
        ):
            raise ValueError("action_window_id is only valid for legendary or lair actions")
        if self.action_cost != "reaction" and self.reaction_window_id is not None:
            raise ValueError("reaction_window_id is only valid for reactions")
        return self


class DeathSaveCommand(BaseModel):
    target_version: int = Field(ge=1)
    roll: int = Field(ge=1, le=20)


class DeathConfirmationCommand(BaseModel):
    target_version: int = Field(ge=1)
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ]


class TurnAdvanceCommand(BaseModel):
    combat_version: int = Field(ge=1)


class CombatSummonCommand(BaseModel):
    companion_id: str | None = Field(default=None, min_length=1, max_length=36)
    count: int = Field(default=1, ge=1, le=20)
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    controller: Literal["player", "dm"] = "dm"
    owner_character_id: str | None = Field(default=None, min_length=1, max_length=36)
    disposition: Literal["ally", "enemy"] = "enemy"
    source_combatant_id: str | None = Field(default=None, min_length=1, max_length=36)
    position: dict[str, int] | None = None
    initiative_mode: Literal["independent", "shared_with_source", "not_applicable"] = "independent"
    action_cost: Literal["action", "bonus_action", "reaction", "none"] = "action"
    resource_key: str | None = Field(default=None, max_length=120)
    resource_cost: int = Field(default=0, ge=0, le=100)
    duration_unit: Literal["rounds", "minutes", "until_save", "until_removed"] = "until_removed"
    duration_value: int | None = Field(default=None, ge=0)
    requires_concentration: bool = False
    enemy_ai_mode: Literal["dm_only", "basic"] = "dm_only"
    hp: int | None = Field(default=None, ge=0, le=1_000_000)
    max_hp: int | None = Field(default=None, ge=1, le=1_000_000)
    armor_class: int | None = Field(default=None, ge=0, le=99)
    speed_ft: int | None = Field(default=None, ge=0, le=1_000)
    ability_scores: dict[str, int] = Field(default_factory=dict)
    actions: list[Any] = Field(default_factory=list)
    template_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_summon(self) -> CombatSummonCommand:
        if self.companion_id is None and not self.name:
            raise ValueError("companion_id or name is required")
        if self.controller == "player" and not self.owner_character_id:
            raise ValueError("owner_character_id is required for a player-controlled summon")
        if self.hp is not None and self.max_hp is not None and self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        if self.duration_unit in {"rounds", "minutes"} and self.duration_value is None:
            raise ValueError("duration_value is required for timed summons")
        if self.requires_concentration and self.source_combatant_id is None:
            raise ValueError("source_combatant_id is required for concentration summons")
        if self.position is not None:
            if set(self.position) != {"row", "col"} or any(
                isinstance(value, bool) or value < 1 for value in self.position.values()
            ):
                raise ValueError("position must contain positive integer row and col")
        return self


class CombatSummonEndCommand(BaseModel):
    summon_version: int = Field(ge=1)
    actor: Literal["dm", "player"] = "dm"
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ]


class CombatEffectCommand(BaseModel):
    target_combatant_id: str = Field(min_length=1, max_length=36)
    target_version: int = Field(ge=1)
    source_combatant_id: str | None = Field(default=None, min_length=1, max_length=36)
    source_version: int | None = Field(default=None, ge=1)
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    ]
    effect_type: Literal["condition", "buff", "debuff", "aura", "damage_over_time"]
    details_json: dict[str, Any] = Field(default_factory=dict)
    duration_unit: Literal[
        "rounds",
        "minutes",
        "concentration",
        "until_save",
        "until_removed",
    ] = "until_removed"
    duration_value: int | None = Field(default=None, ge=0)
    requires_concentration: bool = False
    ends_summon_combatant_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
    )
    summon_version: int | None = Field(default=None, ge=1)
    save_dc: int | None = Field(default=None, ge=0)
    save_ability: str | None = Field(default=None, max_length=30)
    trigger_timing: Literal["turn_start", "turn_end", "round_start", "round_end"] | None = None

    @model_validator(mode="after")
    def validate_effect(self) -> CombatEffectCommand:
        if self.duration_unit in {"rounds", "minutes"} and self.duration_value is None:
            raise ValueError("duration_value is required for timed effects")
        if self.requires_concentration and self.source_combatant_id is None:
            raise ValueError("source_combatant_id is required for concentration")
        if self.ends_summon_combatant_id is not None and self.summon_version is None:
            raise ValueError("summon_version is required for a summon lifecycle effect")
        if self.ends_summon_combatant_id is None and self.summon_version is not None:
            raise ValueError("ends_summon_combatant_id is required with summon_version")
        if (
            self.source_combatant_id is not None
            and self.source_combatant_id != self.target_combatant_id
            and self.source_version is None
        ):
            raise ValueError("source_version is required when source and target differ")
        return self


class CombatEffectEndCommand(BaseModel):
    target_version: int = Field(ge=1)
    source_version: int | None = Field(default=None, ge=1)
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ]


class CombatEffectSaveCommand(BaseModel):
    """Resolve an explicit end-of-turn save for a persistent condition."""

    target_combatant_id: str = Field(min_length=1, max_length=36)
    target_version: int = Field(ge=1)
    roll_total: int = Field(ge=-100, le=1_000)
    dm_note: str | None = Field(default=None, max_length=1_000)


class ConcentrationCheckCommand(BaseModel):
    combatant_id: str = Field(min_length=1, max_length=36)
    target_version: int = Field(ge=1)
    damage_action_id: str = Field(min_length=1, max_length=36)
    roll_total: int = Field(ge=-100, le=1_000)


class CombatXpAward(BaseModel):
    character_id: str = Field(min_length=1, max_length=36)
    xp: int = Field(ge=0, le=10_000_000)


class CombatCurrencyAward(BaseModel):
    character_id: str = Field(min_length=1, max_length=36)
    copper: int = Field(ge=0, le=1_000_000_000)


class CombatLootAward(BaseModel):
    character_id: str = Field(min_length=1, max_length=36)
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    description: str | None = Field(default=None, max_length=5_000)
    category: str = Field(default="loot", min_length=1, max_length=50)
    quantity: int = Field(default=1, ge=1, le=10_000)
    unit_weight_lb: float = Field(default=0, ge=0, le=100_000)
    price_cp: int = Field(default=0, ge=0, le=1_000_000_000)
    source_record_id: str | None = Field(default=None, max_length=100)
    source_label: Literal["official", "legacy", "custom", "ai_generated"] = "custom"
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class CombatWriteback(BaseModel):
    combatant_id: str = Field(min_length=1, max_length=36)
    character_id: str = Field(min_length=1, max_length=36)
    write_hp: bool = True
    write_conditions: bool = False


class CombatSettlementCommand(BaseModel):
    combat_version: int = Field(ge=1)
    resolution_type: Literal[
        "victory",
        "defeat",
        "retreat",
        "negotiated",
        "bypassed",
        "other",
    ]
    xp_awards: list[CombatXpAward] = Field(default_factory=list)
    currency_awards: list[CombatCurrencyAward] = Field(default_factory=list)
    loot_awards: list[CombatLootAward] = Field(default_factory=list)
    writebacks: list[CombatWriteback] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=5_000)

    @model_validator(mode="after")
    def validate_settlement(self) -> CombatSettlementCommand:
        character_ids = [award.character_id for award in self.xp_awards]
        if len(character_ids) != len(set(character_ids)):
            raise ValueError("xp_awards cannot contain duplicate characters")
        currency_character_ids = [award.character_id for award in self.currency_awards]
        if len(currency_character_ids) != len(set(currency_character_ids)):
            raise ValueError("currency_awards cannot contain duplicate characters")
        combatant_ids = [writeback.combatant_id for writeback in self.writebacks]
        if len(combatant_ids) != len(set(combatant_ids)):
            raise ValueError("writebacks cannot contain duplicate combatants")
        return self


class ConditionCreate(BaseModel):
    condition_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    source: str | None = None
    duration: str | None = None
    notes: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class NarrativeCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None
    quest_id: str | None = None
    npc_id: str | None = None
    character_id: str | None = None
    clue_id: str | None = None
    faction_name: str | None = Field(default=None, max_length=200)
    summary: str | None = None
    activity_type: str | None = Field(default=None, max_length=40)
    objective_type: str | None = Field(default=None, max_length=40)
    hidden: bool | None = None
    score: int | None = Field(default=None, ge=-100, le=100)
    attitude_delta: int | None = Field(default=None, ge=-100, le=100)
    duration_days: int | None = Field(default=None, ge=1, le=10000)
    progress_days: int | None = Field(default=None, ge=0, le=10000)
    daily_cost_cp: int | None = Field(default=None, ge=0)
    method: str | None = None
    details: dict[str, Any] | None = None
    branches: dict[str, Any] | None = None
    prerequisites: list[Any] | None = None
    tags: list[Any] | None = None
    secret: bool | None = None
    notes: str | None = None


class NarrativePatch(NarrativeCreate):
    version: int | None = Field(default=None, ge=1)


class NarrativeOperation(BaseModel):
    """One DM-reviewed narrative state change.  No operation is applied at preview time."""

    kind: Literal[
        "story_beat", "quest_objective", "reputation", "downtime", "quest_reward", "runtime"
    ]
    entity_id: str | None = Field(default=None, max_length=36)
    version: int | None = Field(default=None, ge=1)
    status: str | None = Field(default=None, max_length=30)
    score_delta: int | None = Field(default=None, ge=-100, le=100)
    progress_days: int | None = Field(default=None, ge=0, le=10000)
    character_ids: list[str] = Field(default_factory=list, max_length=20)
    xp_each: int | None = Field(default=None, ge=0, le=1_000_000)
    title: str | None = Field(default=None, max_length=200)
    detail: str | None = Field(default=None, max_length=5000)
    mode: Literal["skill_challenge", "chase", "negotiation", "stealth", "investigation"] | None = (
        None
    )
    successes: int | None = Field(default=None, ge=0, le=99)
    failures: int | None = Field(default=None, ge=0, le=99)
    runtime_id: str | None = Field(default=None, max_length=36)
    success_delta: int | None = Field(default=None, ge=0, le=20)
    failure_delta: int | None = Field(default=None, ge=0, le=20)
    target_successes: int | None = Field(default=None, ge=1, le=20)
    target_failures: int | None = Field(default=None, ge=1, le=20)


class NarrativeTransactionRequest(BaseModel):
    operations: list[NarrativeOperation] = Field(min_length=1, max_length=40)
    idempotency_key: str = Field(min_length=8, max_length=120)
    preview_token: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=5000)


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


class CampaignBackupManifest(BaseModel):
    format: Literal["dnd-dm-campaign-backup"] = "dnd-dm-campaign-backup"
    source_campaign_id: str
    table_names: tuple[str, ...] = ()
    excluded_tables: tuple[str, ...] = ()
    record_count: int = Field(default=0, ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CampaignBackup(BaseModel):
    schema_version: Literal["1.0", "2.0"] = "1.0"
    exported_at: datetime
    campaign: dict[str, Any]
    manifest: CampaignBackupManifest | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    tables: dict[str, tuple[dict[str, Any], ...]] = Field(default_factory=dict)
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
    brief: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
    answers: dict[str, str] = Field(default_factory=dict)


class LocationGenerationRequest(BaseModel):
    brief: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
    maximum_depth: int = Field(default=3, ge=1, le=5)
    scale: Literal["small", "medium", "large"] = "medium"


class LocationGenerationConfirmRequest(BaseModel):
    preview: LocationGenerationPreview


class SiteGenerationRequest(BaseModel):
    site_type: Literal["building", "dungeon"]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    brief: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]
    region_path: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    maximum_levels: int = Field(default=1, ge=1, le=20)
    rooms_min: int = Field(default=3, ge=2, le=9)
    rooms_max: int = Field(default=7, ge=2, le=9)
    party_level: int = Field(default=1, ge=1, le=20)
    party_size: int = Field(default=4, ge=1, le=12)
    character_ids: list[str] = Field(default_factory=list, max_length=12)
    starting_difficulty: Literal["low", "moderate", "high"] = "low"
    difficulty_growth: int = Field(default=1, ge=0, le=2)
    monster_density: int = Field(default=60, ge=0, le=100)
    reward_rate: float = Field(default=1, ge=0.25, le=3)
    overall_scale: Literal["small", "medium", "large", "huge"] = "medium"
    minimum_room_size: Literal["small", "medium", "large", "huge"] = "medium"
    maximum_room_size: Literal["small", "medium", "large", "huge"] = "large"
    generate_npcs: bool = True
    generate_monsters: bool = True
    generate_loot: bool = True
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def validate_room_range(self) -> SiteGenerationRequest:
        if self.rooms_min > self.rooms_max:
            raise ValueError("rooms_min cannot exceed rooms_max")
        order = ("small", "medium", "large", "huge")
        if order.index(self.minimum_room_size) > order.index(self.maximum_room_size):
            raise ValueError("minimum_room_size cannot exceed maximum_room_size")
        return self


class SiteGenerationConfirmRequest(BaseModel):
    preview: dict[str, Any]


class SiteRoomVisibilityRequest(BaseModel):
    visible: bool


class CompendiumEntryCreate(BaseModel):
    entry_type: Literal[
        "spell", "feature", "monster", "equipment", "item", "npc", "location", "scene", "rule"
    ]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: str | None = None
    source_kind: Literal["official", "original", "ai_generated", "dm_modified", "third_party"] = (
        "original"
    )
    source_record_id: str | None = None
    source_name: str | None = None
    family_key: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)
    filters_json: dict[str, Any] = Field(default_factory=dict)
    rules_json: dict[str, Any] = Field(default_factory=dict)


class CompendiumGenerateRequest(BaseModel):
    mode: Literal["single", "equipment_set", "monster_family"] = "single"
    entry_type: Literal[
        "spell", "feature", "monster", "equipment", "item", "npc", "location", "scene", "rule"
    ] = "item"
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
    applicable_level: int = Field(default=1, ge=1, le=20)


class CompendiumGenerateConfirmRequest(BaseModel):
    preview: dict[str, Any]


class CompendiumInstantiateRequest(BaseModel):
    target_type: Literal["character", "scene"]
    target_id: str = Field(min_length=1, max_length=36)


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
    damage_resistances: list[str] = Field(default_factory=list)
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)
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


class KnownSpellCreate(BaseModel):
    character_id: str = Field(min_length=1, max_length=36)
    character_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    spell_level: int = Field(ge=0, le=9)
    prepared: bool = True
    source_reference: str | None = Field(default="PHB 2024", max_length=200)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class EquipmentInstanceCreate(BaseModel):
    character_id: str = Field(min_length=1, max_length=36)
    character_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="gear", min_length=1, max_length=30)
    quantity: int = Field(default=1, ge=1)
    armor_class: int | None = Field(default=None, ge=0, le=99)
    attunement_required: bool = False
    charges: int | None = Field(default=None, ge=0)
    max_charges: int | None = Field(default=None, ge=0)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class WalletCreate(BaseModel):
    character_id: str = Field(min_length=1, max_length=36)
    character_version: int = Field(ge=1)
    name: str = Field(default="角色钱包", min_length=1, max_length=100)
    copper: int = Field(default=0, ge=0)


class ShopInventoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=0)
    price_copper: int = Field(default=0, ge=0)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class MerchantGenerateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    brief: str = Field(default="", max_length=1000)
    location_id: str | None = Field(default=None, max_length=36)
    scene_id: str | None = Field(default=None, max_length=36)
    categories: list[
        Literal["weapon", "armor", "shield", "adventuring_gear", "consumable", "magic"]
    ] = Field(default_factory=list, max_length=6)
    item_tier: Literal["mundane", "common", "uncommon", "rare", "very_rare", "legendary"] = "common"
    character_ids: list[str] = Field(default_factory=list, max_length=12)
    stock_size: int = Field(default=12, ge=1, le=40)
    price_modifier_bps: int = Field(default=10_000, ge=5_000, le=20_000)
    allow_original: bool = True
    seed: int | None = Field(default=None, ge=0, le=9_223_372_036_854_775_807)


class MerchantConfirmRequest(BaseModel):
    preview: dict[str, Any]


class SpellCastRequest(BaseModel):
    character_id: str
    character_version: int = Field(ge=1)
    known_spell_id: str
    slot_level: int = Field(ge=0, le=9)
    ritual: bool = False
    material_available: bool = True
    concentration: bool = False
    preview_token: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class EquipmentOperationRequest(BaseModel):
    character_id: str
    character_version: int = Field(ge=1)
    equipment_id: str
    operation: Literal["equip", "unequip", "consume", "use_charge", "attune", "unattune"]
    slot: Literal["armor", "main_hand", "off_hand", "focus", "worn"] | None = None
    amount: int = Field(default=1, ge=1)
    preview_token: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class CommerceRequest(BaseModel):
    wallet_id: str
    wallet_version: int = Field(ge=1)
    shop_inventory_id: str
    shop_version: int = Field(ge=1)
    quantity: int = Field(ge=1)
    direction: Literal["buy", "sell"]
    price_modifier_bps: int = Field(default=10_000, ge=0, le=100_000)
    preview_token: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class CurrencySplitRequest(BaseModel):
    source_wallet_id: str
    source_wallet_version: int = Field(ge=1)
    target_wallet_id: str
    target_wallet_version: int = Field(ge=1)
    copper: int = Field(gt=0)
    preview_token: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class SceneGridCreate(BaseModel):
    width: int = Field(12, ge=1, le=100)
    height: int = Field(8, ge=1, le=100)
    cell_size_ft: int = Field(5, ge=1, le=100)
    mode: Literal["narrative", "exploration", "combat"] = "narrative"
    public_description: str | None = None
    dm_description: str | None = None
    layers_json: dict[str, Any] = Field(default_factory=dict)


class SceneTokenCreate(BaseModel):
    entity_type: Literal["character", "npc", "monster", "marker"]
    entity_id: str | None = None
    label: str = Field(min_length=1, max_length=200)
    row: int = Field(1, ge=1)
    col: int = Field(1, ge=1)
    size_cells: int = Field(1, ge=1, le=4)
    elevation_ft: int = 0
    visible: bool = True
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class SceneObjectCreate(BaseModel):
    object_type: Literal[
        "wall", "door", "cover", "terrain", "light", "trap", "treasure", "furniture", "portal"
    ]
    label: str = Field(min_length=1, max_length=200)
    row: int = Field(ge=1)
    col: int = Field(ge=1)
    width_cells: int = Field(1, ge=1, le=20)
    height_cells: int = Field(1, ge=1, le=20)
    state: Literal["active", "open", "closed", "destroyed", "disarmed", "picked_up"] = "active"
    visibility: Literal["public", "dm", "hidden"] = "public"
    interaction_json: dict[str, Any] = Field(default_factory=dict)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ExplorationPreviewRequest(BaseModel):
    action: Literal["move", "search", "interact", "explore"] = "explore"
    minutes: int = Field(10, ge=1, le=1440)
    token_id: str | None = None
    path: list[tuple[int, int]] = Field(default_factory=list, max_length=200)
    object_id: str | None = None
    object_state: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=2000)


class ExplorationConfirmRequest(ExplorationPreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


class TravelEncounterInput(BaseModel):
    """A DM-adjudicated event that is persisted with a confirmed travel leg."""

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    outcome: Literal["avoided", "resolved", "evaded"] = "resolved"
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    visibility: Literal["dm", "players"] = "dm"


class TravelPreviewRequest(BaseModel):
    to_location_id: str
    distance_miles: float = Field(ge=0, le=100000)
    pace: Literal["fast", "normal", "slow"] = "normal"
    encounter: TravelEncounterInput | None = None
    notes: str | None = Field(default=None, max_length=2000)


class TravelConfirmRequest(TravelPreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


class SocialInteractionPreviewRequest(BaseModel):
    """A DM-adjudicated social result; preview never changes the NPC."""

    npc_version: int = Field(ge=1)
    outcome: Literal["improve", "unchanged", "worsen"]
    minutes: int = Field(default=10, ge=1, le=1_440)
    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
    ]
    memory_kind: Literal[
        "conversation", "bargain", "deception", "intimidation", "favor", "other"
    ] = "conversation"
    tags: list[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
        ]
    ] = Field(default_factory=list, max_length=20)
    secret: bool = False


class SocialInteractionConfirmRequest(SocialInteractionPreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


class ExplorationCharacterEffect(BaseModel):
    """DM-supplied numeric consequence for an exploration confirmation.

    This intentionally has no DC/save fields: a failed or successful check is
    adjudicated before this API is called, so confirming cannot silently invent
    a roll or a narrative consequence.
    """

    character_id: str = Field(min_length=1, max_length=36)
    character_version: int = Field(ge=1)
    damage: int = Field(default=0, ge=0, le=100_000)
    max_hp_reduction: int = Field(default=0, ge=0, le=100_000)
    condition_name: str | None = Field(default=None, min_length=1, max_length=100)
    condition_duration: str | None = Field(default=None, max_length=100)
    condition_notes: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_effect(self) -> ExplorationCharacterEffect:
        if not (self.damage or self.max_hp_reduction or self.condition_name):
            raise ValueError("character effect must include damage, reduction, or condition")
        return self


class ChasePreviewRequest(BaseModel):
    chase_event_id: str | None = Field(default=None, min_length=1, max_length=36)
    chase_version: int | None = Field(default=None, ge=1)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    outcome: Literal["success", "failure"]
    target_successes: int = Field(default=3, ge=1, le=100)
    target_failures: int = Field(default=3, ge=1, le=100)
    minutes: int = Field(default=1, ge=0, le=1_440)
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    visibility: Literal["dm", "players"] = "dm"
    character_effects: list[ExplorationCharacterEffect] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_chase_reference(self) -> ChasePreviewRequest:
        if (self.chase_event_id is None) != (self.chase_version is None):
            raise ValueError("chase_event_id and chase_version must be supplied together")
        _validate_distinct_character_effects(self.character_effects)
        return self


class ChaseConfirmRequest(ChasePreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


class TrapResolutionPreviewRequest(BaseModel):
    trap_version: int = Field(ge=1)
    outcome: Literal["triggered", "disarmed", "bypassed", "failed"]
    result_state: Literal["active", "disarmed", "destroyed"] = "active"
    minutes: int = Field(default=1, ge=1, le=1_440)
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    visibility: Literal["dm", "players"] = "dm"
    character_effects: list[ExplorationCharacterEffect] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_trap_effects(self) -> TrapResolutionPreviewRequest:
        _validate_distinct_character_effects(self.character_effects)
        return self


class TrapResolutionConfirmRequest(TrapResolutionPreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


class AfflictionPreviewRequest(BaseModel):
    operation: Literal["apply", "progress", "cure"]
    character_id: str = Field(min_length=1, max_length=36)
    character_version: int = Field(ge=1)
    condition_id: str | None = Field(default=None, min_length=1, max_length=36)
    condition_version: int | None = Field(default=None, ge=1)
    affliction_type: Literal["poison", "disease", "infection"]
    condition_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    source: str | None = Field(default=None, max_length=200)
    duration: str | None = Field(default=None, max_length=100)
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    damage: int = Field(default=0, ge=0, le=100_000)
    max_hp_reduction: int = Field(default=0, ge=0, le=100_000)
    minutes: int = Field(default=0, ge=0, le=1_440)
    visibility: Literal["dm", "players"] = "dm"

    @model_validator(mode="after")
    def validate_affliction_reference(self) -> AfflictionPreviewRequest:
        referenced = self.condition_id is not None or self.condition_version is not None
        if self.operation == "apply" and referenced:
            raise ValueError("new affliction must not include a condition reference")
        if self.operation != "apply" and (
            self.condition_id is None or self.condition_version is None
        ):
            raise ValueError("progress and cure require condition_id and condition_version")
        return self


class AfflictionConfirmRequest(AfflictionPreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


class DowntimeResolutionPreviewRequest(BaseModel):
    activity_version: int = Field(ge=1)
    character_version: int = Field(ge=1)
    progress_days: int = Field(default=1, ge=1, le=365)
    xp_award: int = Field(default=0, ge=0, le=10_000_000)
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    visibility: Literal["dm", "players"] = "dm"


class DowntimeResolutionConfirmRequest(DowntimeResolutionPreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


class NPCMoralePreviewRequest(BaseModel):
    npc_version: int = Field(ge=1)
    outcome: Literal["hold", "retreat", "surrender"]
    combat_id: str | None = Field(default=None, min_length=1, max_length=36)
    combat_version: int | None = Field(default=None, ge=1)
    leave_combat: bool = True
    minutes: int = Field(default=0, ge=0, le=1_440)
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    visibility: Literal["dm", "players"] = "dm"

    @model_validator(mode="after")
    def validate_combat_reference(self) -> NPCMoralePreviewRequest:
        if (self.combat_id is None) != (self.combat_version is None):
            raise ValueError("combat_id and combat_version must be supplied together")
        return self


class NPCMoraleConfirmRequest(NPCMoralePreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


class EnvironmentHazardPreviewRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    object_id: str | None = Field(default=None, min_length=1, max_length=36)
    object_version: int | None = Field(default=None, ge=1)
    object_state: (
        Literal["active", "open", "closed", "destroyed", "disarmed", "picked_up"] | None
    ) = None
    minutes: int = Field(default=1, ge=1, le=1_440)
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    visibility: Literal["dm", "players"] = "dm"
    character_effects: list[ExplorationCharacterEffect] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_hazard_reference(self) -> EnvironmentHazardPreviewRequest:
        if (self.object_id is None) != (self.object_version is None):
            raise ValueError("object_id and object_version must be supplied together")
        _validate_distinct_character_effects(self.character_effects)
        return self


class EnvironmentHazardConfirmRequest(EnvironmentHazardPreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)


def _validate_distinct_character_effects(effects: list[ExplorationCharacterEffect]) -> None:
    ids = [effect.character_id for effect in effects]
    if len(ids) != len(set(ids)):
        raise ValueError("each character may appear only once in an exploration resolution")
