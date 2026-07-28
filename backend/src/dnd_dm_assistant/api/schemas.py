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
    mode: Literal["general", "narrative"] = "general"


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
    max_hp: int | None = Field(None, ge=0)
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


class AdvancementPreviewRequest(BaseModel):
    character_version: int = Field(ge=1)
    class_name: str = Field(min_length=1, max_length=100)
    subclass_name: str | None = Field(default=None, max_length=100)
    hp_mode: Literal["fixed", "roll"] = "fixed"
    hp_roll: int | None = Field(default=None, ge=1, le=12)
    ability_increases: dict[str, int] = Field(default_factory=dict)
    feat_choice: str | None = Field(default=None, max_length=200)
    feature_choices: list[str] = Field(default_factory=list, max_length=30)
    spell_additions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    spell_removals: list[str] = Field(default_factory=list, max_length=100)
    dm_override_reason: str | None = Field(default=None, max_length=2_000)


class CharacterSheetOcrRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    image_base64: str = Field(min_length=4, max_length=17_000_000)


class AdvancementConfirmRequest(AdvancementPreviewRequest):
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


class CombatActionCommand(BaseModel):
    action_type: Literal["damage", "heal"]
    target_combatant_id: str = Field(min_length=1, max_length=36)
    target_version: int = Field(ge=1)
    actor_combatant_id: str | None = Field(default=None, min_length=1, max_length=36)
    actor_version: int | None = Field(default=None, ge=1)
    action_cost: Literal["action", "bonus_action", "reaction", "none"] = "none"
    action_name: str | None = Field(default=None, max_length=200)
    resolution_note: str | None = Field(default=None, max_length=1_000)
    amount: int = Field(ge=0, le=100_000)
    damage_type: str | None = Field(default=None, max_length=50)
    critical_hit: bool = False
    dm_override: bool = False
    override_reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_action(self) -> CombatActionCommand:
        if self.action_type == "damage" and not (self.damage_type or "").strip():
            raise ValueError("damage_type is required for damage")
        if self.dm_override and not (self.override_reason or "").strip():
            raise ValueError("override_reason is required for a DM override")
        if self.action_cost != "none" and (
            self.actor_combatant_id is None or self.actor_version is None
        ):
            raise ValueError(
                "actor_combatant_id and actor_version are required when an action is spent"
            )
        return self


class PlayerRollPromptCommand(BaseModel):
    actor_combatant_id: str = Field(min_length=1, max_length=36)
    actor_version: int = Field(ge=1)
    action_cost: Literal["action", "bonus_action", "reaction", "none"] = "action"
    target_combatant_id: str = Field(min_length=1, max_length=36)
    target_version: int = Field(ge=1)
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
    skill: str | None = Field(default=None, max_length=80)
    roll_formula: str = Field(default="1d20", min_length=1, max_length=50)
    damage_on_success: int = Field(default=0, ge=0, le=100_000)
    damage_on_failure: int = Field(default=0, ge=0, le=100_000)
    damage_type: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_roll_prompt(self) -> PlayerRollPromptCommand:
        if self.resolution_type == "saving_throw" and not (self.ability or "").strip():
            raise ValueError("ability is required for a saving throw")
        if self.resolution_type == "skill_check" and not (self.skill or "").strip():
            raise ValueError("skill is required for a skill check")
        if (self.damage_on_success > 0 or self.damage_on_failure > 0) and not (
            self.damage_type or ""
        ).strip():
            raise ValueError("damage_type is required when the roll can deal damage")
        return self


class PlayerRollResolutionCommand(BaseModel):
    action_version: int = Field(ge=1)
    roll_total: int = Field(ge=-100, le=1_000)
    dm_note: str | None = Field(default=None, max_length=1_000)


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
    save_dc: int | None = Field(default=None, ge=0)
    save_ability: str | None = Field(default=None, max_length=30)
    trigger_timing: Literal["turn_start", "turn_end", "round_start", "round_end"] | None = None

    @model_validator(mode="after")
    def validate_effect(self) -> CombatEffectCommand:
        if self.duration_unit in {"rounds", "minutes"} and self.duration_value is None:
            raise ValueError("duration_value is required for timed effects")
        if self.requires_concentration and self.source_combatant_id is None:
            raise ValueError("source_combatant_id is required for concentration")
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
    starting_difficulty: Literal["low", "moderate", "high"] = "low"
    difficulty_growth: int = Field(default=1, ge=0, le=2)
    monster_density: int = Field(default=60, ge=0, le=100)
    reward_rate: float = Field(default=1, ge=0.25, le=3)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def validate_room_range(self) -> SiteGenerationRequest:
        if self.rooms_min > self.rooms_max:
            raise ValueError("rooms_min cannot exceed rooms_max")
        return self


class SiteGenerationConfirmRequest(BaseModel):
    preview: dict[str, Any]


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


class TravelPreviewRequest(BaseModel):
    to_location_id: str
    distance_miles: float = Field(ge=0, le=100000)
    pace: Literal["fast", "normal", "slow"] = "normal"
    notes: str | None = Field(default=None, max_length=2000)


class TravelConfirmRequest(TravelPreviewRequest):
    preview_token: str = Field(min_length=16, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=120)
