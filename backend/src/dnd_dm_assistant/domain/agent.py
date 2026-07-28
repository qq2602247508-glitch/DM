from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dnd_dm_assistant.domain.content import ContentType, Edition
from dnd_dm_assistant.domain.rag import Citation


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ToolName(StrEnum):
    SEARCH_RULES = "search_rules"
    GET_CAMPAIGN_STATE = "get_campaign_state"
    UPDATE_CAMPAIGN_STATE = "update_campaign_state"
    GENERATE_DM_HINT = "generate_dm_hint"


class Intent(StrEnum):
    RULES = "rules"
    STATE_LOOKUP = "state_lookup"
    STATE_CHANGE = "state_change"
    DM_ASSIST = "dm_assist"


class StateOperationKind(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CONFLICT = "conflict"


class ModelRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    INVALID_OUTPUT = "invalid_output"


class AgentRequest(StrictModel):
    campaign_id: str = Field(min_length=1, max_length=36)
    action: str = Field(min_length=1, max_length=4_000)
    request_id: str = Field(min_length=1, max_length=120)
    # ``general`` remains accepted for older clients and is normalized to the
    # quick-mode policy by the orchestrator.
    mode: Literal["quick", "narrative", "combat", "general"] = "quick"

    @field_validator("action", "campaign_id", "request_id")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class RuleSearchFilters(StrictModel):
    content_types: tuple[ContentType, ...] = ()
    editions: tuple[Edition, ...] = ()
    source_books: tuple[str, ...] = Field(default=(), max_length=10)
    top_k: int = Field(default=6, ge=1, le=12)
    candidate_k: int = Field(default=18, ge=1, le=40)
    min_score: float = Field(default=0.45, ge=-1, le=1)
    current_official: bool = True
    allow_unknown: bool = False
    allow_third_party: bool = False

    @model_validator(mode="after")
    def candidates_cover_results(self) -> RuleSearchFilters:
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        return self


class RuleSearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=2_000)
    filters: RuleSearchFilters | None = None


class CampaignStateArgs(StrictModel):
    campaign_id: str = Field(min_length=1, max_length=36)
    scopes: tuple[
        Literal["campaign", "characters", "npcs", "locations", "quests", "clues", "combats"],
        ...,
    ] = ()
    limit: int = Field(default=40, ge=1, le=100)

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 7 or len(set(value)) != len(value):
            raise ValueError("scopes must be unique and bounded")
        return value


_ENTITY_FIELDS: dict[str, frozenset[str]] = {
    "character": frozenset({"name", "class_name", "level", "hp", "max_hp", "inventory", "notes"}),
    "npc": frozenset(
        {
            "name",
            "description",
            "personality",
            "relationship",
            "secrets",
            "known_information",
            "location_id",
            "status",
        }
    ),
    "quest": frozenset({"name", "description", "status", "notes"}),
    "event": frozenset(
        {
            "event_type",
            "title",
            "description",
            "occurred_at",
            "location_id",
            "visibility",
            "metadata_json",
        }
    ),
}
_RESERVED_FIELDS = frozenset(
    {"id", "campaign_id", "version", "created_at", "updated_at", "request_id", "actor"}
)


class _CharacterPayload(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    class_name: str | None = Field(default=None, max_length=100)
    level: int | None = Field(default=None, ge=1, le=20)
    hp: int | None = Field(default=None, ge=0, le=100_000)
    max_hp: int | None = Field(default=None, ge=0, le=100_000)
    inventory: list[Any] | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def valid_hp(self) -> _CharacterPayload:
        if self.hp is not None and self.max_hp is not None and self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class _NPCPayload(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    personality: str | None = Field(default=None, max_length=4_000)
    relationship: str | None = Field(default=None, max_length=4_000)
    secrets: str | None = Field(default=None, max_length=4_000)
    known_information: str | None = Field(default=None, max_length=4_000)
    location_id: str | None = Field(default=None, min_length=1, max_length=36)
    status: Literal["active", "inactive", "dead", "missing"] | None = None


class _QuestPayload(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    status: Literal["open", "active", "completed", "failed"] | None = None
    notes: str | None = Field(default=None, max_length=4_000)


class _EventPayload(StrictModel):
    event_type: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    occurred_at: str | None = Field(default=None, min_length=1, max_length=50)
    location_id: str | None = Field(default=None, min_length=1, max_length=36)
    visibility: Literal["dm", "players", "public"] | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("occurred_at")
    @classmethod
    def valid_iso_datetime(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


_PAYLOAD_MODELS = {
    "character": _CharacterPayload,
    "npc": _NPCPayload,
    "quest": _QuestPayload,
    "event": _EventPayload,
}


def _validate_json(value: Any, *, depth: int = 0) -> None:
    if depth > 4:
        raise ValueError("payload nesting exceeds four levels")
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 4_000:
            raise ValueError("payload string exceeds 4000 characters")
        return
    if isinstance(value, list):
        if len(value) > 100:
            raise ValueError("payload list exceeds 100 entries")
        for item in value:
            _validate_json(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 30 or any(not isinstance(key, str) for key in value):
            raise ValueError("payload object is invalid or too large")
        for item in value.values():
            _validate_json(item, depth=depth + 1)
        return
    raise ValueError("payload contains a non-JSON value")


class StateOperation(StrictModel):
    operation: StateOperationKind
    entity_type: Literal["character", "npc", "quest", "event"]
    entity_id: str | None = Field(default=None, min_length=1, max_length=36)
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_operation(self) -> StateOperation:
        fields = set(self.payload)
        if fields & _RESERVED_FIELDS or not fields <= _ENTITY_FIELDS[self.entity_type]:
            raise ValueError("payload contains reserved or unsupported fields")
        payload_model = cast(type[StrictModel], _PAYLOAD_MODELS[self.entity_type])
        typed = payload_model.model_validate(self.payload)
        normalized = typed.model_dump(mode="python", exclude_unset=True)
        _validate_json(normalized)
        object.__setattr__(self, "payload", normalized)
        if self.operation is StateOperationKind.CREATE:
            if self.entity_id is not None or self.expected_version is not None:
                raise ValueError("create cannot specify entity_id or expected_version")
            required = "title" if self.entity_type == "event" else "name"
            if (
                not isinstance(self.payload.get(required), str)
                or not self.payload[required].strip()
            ):
                raise ValueError(f"create requires non-empty {required}")
            if self.entity_type == "character":
                hp = self.payload.get("hp", 0)
                max_hp = self.payload.get("max_hp", 0)
                if hp > max_hp:
                    raise ValueError("hp cannot exceed max_hp")
        else:
            if self.entity_id is None or self.expected_version is None:
                raise ValueError("update/delete requires entity_id and expected_version")
            if self.operation is StateOperationKind.UPDATE and not self.payload:
                raise ValueError("update requires a payload")
            if self.operation is StateOperationKind.DELETE and self.payload:
                raise ValueError("delete payload must be empty")
        return self


class UpdateCampaignStateArgs(StrictModel):
    campaign_id: str = Field(min_length=1, max_length=36)
    operation: StateOperation


class DMHintArgs(StrictModel):
    action: str = Field(min_length=1, max_length=4_000)
    campaign_context: dict[str, Any] = Field(default_factory=dict)
    rule_evidence: tuple[dict[str, Any], ...] = Field(default=())

    @model_validator(mode="after")
    def bound_context(self) -> DMHintArgs:
        _validate_json(self.campaign_context)
        _validate_json(list(self.rule_evidence))
        if len(self.rule_evidence) > 12:
            raise ValueError("rule evidence exceeds 12 entries")
        return self


class ToolCall(StrictModel):
    tool: ToolName
    arguments: dict[str, Any]


class AgentPlan(StrictModel):
    intent: Intent
    calls: tuple[ToolCall, ...] = Field(max_length=6)
    rationale: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def no_duplicate_calls(self) -> AgentPlan:
        fingerprints = [call.model_dump_json() for call in self.calls]
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("duplicate tool calls are not allowed")
        return self


class ToolResult(StrictModel):
    tool: ToolName
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=500)


class StateChangeProposal(StrictModel):
    id: str
    campaign_id: str
    tool_name: Literal["update_campaign_state"]
    operation: StateOperationKind
    entity_type: Literal["character", "npc", "quest", "event"]
    entity_id: str | None
    payload: dict[str, Any]
    expected_version: int | None
    reason: str
    status: ProposalStatus
    created_by_model: str
    request_id: str
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None = None
    version: int


class ProposalDecision(StrictModel):
    proposal: StateChangeProposal
    applied_entity: dict[str, Any] | None = None
    already_decided: bool = False


class DMHint(StrictModel):
    visibility: Literal["dm_private"] = "dm_private"
    text: str = Field(min_length=1, max_length=8_000)
    assumptions: tuple[str, ...] = Field(default=(), max_length=20)
    uncertainties: tuple[str, ...] = Field(default=(), max_length=20)
    citations: tuple[Citation, ...] = Field(default=(), max_length=20)
    proposed_changes: tuple[str, ...] = Field(default=(), max_length=20)


class GeneratedDMHint(StrictModel):
    visibility: Literal["dm_private"] = "dm_private"
    text: str = Field(min_length=1, max_length=8_000)
    assumptions: tuple[str, ...] = Field(default=(), max_length=20)
    uncertainties: tuple[str, ...] = Field(default=(), max_length=20)
    citation_chunk_ids: tuple[str, ...] = Field(default=(), max_length=20)
    proposed_changes: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("citation_chunk_ids")
    @classmethod
    def unique_citation_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("citation ids must be unique")
        return value


class AgentResponse(StrictModel):
    request_id: str
    campaign_id: str
    dm_hint: DMHint | None = None
    tool_results: tuple[ToolResult, ...] = ()
    citations: tuple[Citation, ...] = ()
    proposals: tuple[StateChangeProposal, ...] = ()
    abstained: bool = False
    errors: tuple[str, ...] = ()


class ModelRunRecord(StrictModel):
    campaign_id: str
    request_id: str
    model_role: Literal["intent", "reasoning"]
    model_name: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=80)
    latency_ms: int = Field(ge=0)
    status: ModelRunStatus
    error_category: str | None = Field(default=None, max_length=80)
