from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

DraftKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]
Name = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
DuplicateStrategy = Literal["error", "reuse", "create"]

ABILITY_KEYS = frozenset(
    {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}
)
VALID_CHALLENGE_RATINGS = frozenset(
    {"0", "1/8", "1/4", "1/2", *(str(value) for value in range(1, 31))}
)


class StrictDraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeyedDraftModel(StrictDraftModel):
    key: DraftKey
    name: Name


class PrepLocation(KeyedDraftModel):
    parent_location_key: DraftKey | None = None
    depth: int = Field(default=1, ge=1, le=10)
    description: str | None = Field(default=None, max_length=20_000)
    interactive_objects: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    secrets: str | None = Field(default=None, max_length=10_000)
    discovered: bool = True
    notes: str | None = Field(default=None, max_length=10_000)


class PrepSceneParticipant(StrictDraftModel):
    entity_type: Literal["npc", "monster"]
    entity_key: DraftKey
    role: str = Field(default="present", min_length=1, max_length=30)
    visible: bool = True
    notes: str | None = Field(default=None, max_length=4_000)


class PrepSceneGrid(StrictDraftModel):
    width: int = Field(default=12, ge=4, le=100)
    height: int = Field(default=8, ge=4, le=100)
    cell_size_ft: int = Field(default=5, ge=1, le=100)
    mode: Literal["narrative", "exploration", "combat"] = "exploration"
    public_description: str | None = Field(default=None, max_length=20_000)
    dm_description: str | None = Field(default=None, max_length=20_000)
    layers_json: dict[str, Any] = Field(default_factory=dict)


class PrepScene(KeyedDraftModel):
    location_key: DraftKey | None = None
    description: str | None = Field(default=None, max_length=20_000)
    status: Literal["draft", "active", "closed"] = "active"
    notes: str | None = Field(default=None, max_length=10_000)
    grid: PrepSceneGrid | None = None
    participants: list[PrepSceneParticipant] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_participants(self) -> PrepScene:
        refs = [(item.entity_type, item.entity_key) for item in self.participants]
        if len(refs) != len(set(refs)):
            raise ValueError("scene participants must be unique")
        return self


class CreatureDraft(KeyedDraftModel):
    armor_class: int = Field(ge=0, le=99)
    hp: int = Field(ge=0, le=100_000)
    max_hp: int = Field(ge=1, le=100_000)
    speed: int = Field(ge=0, le=1_000)
    ability_scores: dict[str, int]
    challenge_rating: str | None = None
    actions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)

    @field_validator("ability_scores")
    @classmethod
    def validate_ability_scores(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != ABILITY_KEYS:
            missing = sorted(ABILITY_KEYS - set(value))
            extra = sorted(set(value) - ABILITY_KEYS)
            raise ValueError(
                "ability_scores requires six D&D abilities; "
                f"missing={missing}, extra={extra}"
            )
        if any(isinstance(score, bool) or score < 1 or score > 30 for score in value.values()):
            raise ValueError("ability scores must be integers from 1 to 30")
        return value

    @field_validator("challenge_rating")
    @classmethod
    def validate_challenge_rating(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_CHALLENGE_RATINGS:
            raise ValueError("challenge_rating must be a D&D 5e CR from 0 through 30")
        return value

    @model_validator(mode="after")
    def validate_hit_points(self) -> CreatureDraft:
        if self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class PrepNPC(CreatureDraft):
    description: str | None = Field(default=None, max_length=20_000)
    alignment: str | None = Field(default=None, max_length=100)
    attitude: str | None = Field(default=None, max_length=100)
    personality: str | None = Field(default=None, max_length=10_000)
    goal: str | None = Field(default=None, max_length=10_000)
    fear: str | None = Field(default=None, max_length=10_000)
    equipment: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    relationship: str | None = Field(default=None, max_length=10_000)
    secrets: str | None = Field(default=None, max_length=10_000)
    known_information: str | None = Field(default=None, max_length=10_000)
    location_key: DraftKey | None = None
    status: str = Field(default="active", min_length=1, max_length=50)


class PrepMonster(CreatureDraft):
    source_record_id: str | None = Field(default=None, max_length=100)
    source_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)


class PrepQuest(KeyedDraftModel):
    description: str | None = Field(default=None, max_length=20_000)
    quest_type: Literal["main", "side", "personal", "faction"] = "side"
    giver: str | None = Field(default=None, max_length=200)
    giver_npc_key: DraftKey | None = None
    reward: str | None = Field(default=None, max_length=10_000)
    xp_reward: int = Field(default=0, ge=0, le=10_000_000)
    status: str = Field(default="open", min_length=1, max_length=30)
    notes: str | None = Field(default=None, max_length=10_000)


class PrepClue(KeyedDraftModel):
    description: str | None = Field(default=None, max_length=20_000)
    player_text: str | None = Field(default=None, max_length=20_000)
    dm_truth: str | None = Field(default=None, max_length=20_000)
    verified: bool = False
    quest_key: DraftKey | None = None
    discovered: bool = False
    discovered_at: datetime | None = None


class PrepItem(KeyedDraftModel):
    description: str | None = Field(default=None, max_length=20_000)
    category: str = Field(default="misc", min_length=1, max_length=50)
    quantity: int = Field(default=1, ge=1, le=10_000)
    unit_weight_lb: float = Field(ge=0, le=100_000)
    price_cp: int = Field(ge=0, le=1_000_000_000)
    source_record_id: str | None = Field(default=None, max_length=100)
    source_label: Literal["official", "legacy", "custom", "ai_generated"] = "custom"
    location_key: DraftKey
    is_hidden: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class PrepDraft(StrictDraftModel):
    schema_version: Literal["1.0"]
    title: str | None = Field(default=None, max_length=200)
    locations: list[PrepLocation] = Field(default_factory=list, max_length=200)
    scenes: list[PrepScene] = Field(default_factory=list, max_length=200)
    npcs: list[PrepNPC] = Field(default_factory=list, max_length=500)
    monsters: list[PrepMonster] = Field(default_factory=list, max_length=500)
    quests: list[PrepQuest] = Field(default_factory=list, max_length=200)
    clues: list[PrepClue] = Field(default_factory=list, max_length=500)
    items: list[PrepItem] = Field(default_factory=list, max_length=1_000)

    @model_validator(mode="after")
    def require_content(self) -> PrepDraft:
        if not any(
            (
                self.locations,
                self.scenes,
                self.npcs,
                self.monsters,
                self.quests,
                self.clues,
                self.items,
            )
        ):
            raise ValueError("prep draft must contain at least one entity")
        return self


class PrepDraftValidationRequest(StrictDraftModel):
    draft: PrepDraft
    duplicate_strategy: DuplicateStrategy = "error"


class PrepImportConfirmRequest(PrepDraftValidationRequest):
    preview_token: str = Field(min_length=65, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=100)


class PrepValidationIssue(StrictDraftModel):
    code: str
    path: str
    message: str


class PrepDraftValidationResponse(StrictDraftModel):
    valid: bool
    summary: dict[str, int]
    warnings: list[PrepValidationIssue]
    errors: list[PrepValidationIssue]
    operations: list[dict[str, Any]]
    reference_plan: dict[str, dict[str, str]]


class PrepImportPreviewResponse(PrepDraftValidationResponse):
    preview_token: str
    expires_at: datetime


class PrepImportConfirmResponse(StrictDraftModel):
    import_id: str
    idempotent_replay: bool
    created: dict[str, int]
    reused: dict[str, int]
    reference_map: dict[str, dict[str, str]]
