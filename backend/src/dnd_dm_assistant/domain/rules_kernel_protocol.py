# ruff: noqa: E501
"""Versioned, engine-neutral contracts for the authoritative rules kernel.

The protocol deliberately contains only JSON-shaped data.  It is shared by
the HTTP API, the persistence layer, deterministic spatial adapters and the
future 2-D/3-D scene clients; no renderer object or executable callback is
allowed to cross this boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RULES_KERNEL_SCHEMA_VERSION = "rules-kernel-1"
SCENE_QUERY_SCHEMA_VERSION = "scene-query-1"
SCENE_DELTA_SCHEMA_VERSION = "scene-delta-1"
DM_ADJUDICATION_SCHEMA_VERSION = "dm-adjudication-1"
TYPED_ADJUDICATION_SCHEMA_VERSION = "typed-adjudication-1"


class KernelModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class KernelPosition(KernelModel):
    row: int = Field(ge=1, le=10_000)
    col: int = Field(ge=1, le=10_000)
    elevation_ft: int = Field(default=0, ge=-10_000, le=10_000)


class KernelTargetIntent(KernelModel):
    target_ids: tuple[str, ...] = Field(default=(), max_length=64)
    target_kind: Literal[
        "none",
        "self",
        "one_creature",
        "multiple_creatures",
        "position",
        "area",
        "freeform",
    ] = "none"
    semantic: Literal["typed", "target_dependent", "freeform"] = "typed"

    @model_validator(mode="after")
    def validate_target_shape(self) -> KernelTargetIntent:
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("target_ids must be unique")
        if self.target_kind in {"one_creature", "self"} and len(self.target_ids) > 1:
            raise ValueError("single-target intent cannot contain multiple targets")
        if self.semantic == "freeform" and self.target_kind != "freeform":
            raise ValueError("freeform target semantics require target_kind=freeform")
        return self


class KernelSpatialIntent(KernelModel):
    origin: KernelPosition | None = None
    destination: KernelPosition | None = None
    path: tuple[KernelPosition, ...] = Field(default=(), max_length=256)
    shape: Literal["point", "cone", "line", "cube", "sphere", "cylinder"] | None = None
    size_ft: int | None = Field(default=None, ge=5, le=10_000)
    width_ft: int | None = Field(default=None, ge=5, le=10_000)
    height_ft: int | None = Field(default=None, ge=5, le=10_000)
    maximum_distance_ft: int | None = Field(default=None, ge=0, le=10_000)
    movement_kind: Literal[
        "none",
        "voluntary_movement",
        "forced_movement",
        "teleport",
        "swap_positions",
    ] = "none"
    entity_profile_id: str | None = Field(default=None, min_length=1, max_length=200)
    occupied_space_policy: Literal["reject", "nearest_unoccupied"] = "reject"
    path_required: bool = True
    line_of_sight_required: bool = False

    @model_validator(mode="after")
    def validate_spatial_shape(self) -> KernelSpatialIntent:
        if self.shape is not None and self.size_ft is None:
            raise ValueError("area shape requires size_ft")
        if self.movement_kind in {"teleport", "voluntary_movement", "forced_movement"} and (
            self.destination is None
        ):
            raise ValueError("movement intent requires destination")
        if self.movement_kind == "swap_positions" and self.destination is not None:
            raise ValueError("swap_positions uses target entities, not a destination")
        return self


class KernelResourceIntent(KernelModel):
    resource_key: str | None = Field(default=None, min_length=1, max_length=160)
    amount: int = Field(default=0, ge=0, le=10_000)
    mode: Literal["none", "consume", "grant", "reserve"] = "none"


class KernelChoiceInput(KernelModel):
    key: str = Field(min_length=1, max_length=160)
    values: tuple[str, ...] = Field(default=(), max_length=32)


class KernelRollInputs(KernelModel):
    attack_roll_total: int | None = Field(default=None, ge=-100, le=10_000)
    resolution_total: int | None = Field(default=None, ge=0, le=100_000)
    save_succeeded: bool | None = None
    save_succeeded_by_target: dict[str, bool] = Field(default_factory=dict, max_length=64)


class KernelExpectedVersions(KernelModel):
    actor_version: int | None = Field(default=None, ge=1)
    target_versions: dict[str, int] = Field(default_factory=dict, max_length=64)
    scene_version: int | None = Field(default=None, ge=1)
    combat_version: int | None = Field(default=None, ge=1)
    choice_window_version: int | None = Field(default=None, ge=1)
    adjudication_version: int | None = Field(default=None, ge=1)
    entity_versions: dict[str, int] = Field(default_factory=dict, max_length=64)


class RulesKernelCommand(KernelModel):
    schema_version: Literal["rules-kernel-1"] = RULES_KERNEL_SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=160)
    campaign_id: str = Field(min_length=1, max_length=36)
    scene_id: str | None = Field(default=None, max_length=36)
    combat_id: str | None = Field(default=None, max_length=36)
    round: int = Field(default=1, ge=1, le=10_000)
    turn: int = Field(default=0, ge=0, le=10_000)
    actor_id: str = Field(min_length=1, max_length=36)
    content_id: str | None = Field(default=None, max_length=200)
    content_kind: Literal["spell", "feature", "feat", "item", "monster_action", "system"]
    runtime_definition_id: str | None = Field(default=None, max_length=200)
    source_pack_id: str | None = Field(default=None, max_length=120)
    action_kind: Literal[
        "content",
        "move",
        "forced_move",
        "teleport",
        "swap_positions",
        "summon_known_profile",
        "create_known_object",
        "create_known_hazard",
        "choice",
        "adjudication",
    ] = "content"
    action_economy: Literal[
        "none", "free", "action", "bonus_action", "reaction", "automatic"
    ] = "none"
    resource_intent: KernelResourceIntent = Field(default_factory=KernelResourceIntent)
    target_intent: KernelTargetIntent = Field(default_factory=KernelTargetIntent)
    spatial_intent: KernelSpatialIntent = Field(default_factory=KernelSpatialIntent)
    choice_inputs: tuple[KernelChoiceInput, ...] = Field(default=(), max_length=32)
    roll_inputs: KernelRollInputs = Field(default_factory=KernelRollInputs)
    parent_command_id: str | None = Field(default=None, max_length=120)
    causal_depth: int = Field(default=0, ge=0, le=8)
    expected_versions: KernelExpectedVersions = Field(default_factory=KernelExpectedVersions)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def validate_command(self) -> RulesKernelCommand:
        if self.action_kind == "content" and not self.content_id:
            raise ValueError("content commands require content_id")
        if self.action_kind in {"summon_known_profile", "create_known_object", "create_known_hazard"}:
            if not self.spatial_intent.entity_profile_id:
                raise ValueError("entity commands require entity_profile_id")
        if self.action_kind == "adjudication" and self.causal_depth >= 8:
            raise ValueError("adjudication command exceeded causal depth")
        if self.parent_command_id == self.command_id:
            raise ValueError("parent_command_id cannot equal command_id")
        if set(self.expected_versions.target_versions) - set(self.target_intent.target_ids):
            raise ValueError("target version contains an unknown target")
        return self


class RulesKernelBlocker(KernelModel):
    code: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=1_000)
    retryable: bool = False


class RulesKernelAdjudicationRequest(KernelModel):
    schema_version: Literal["dm-adjudication-1"] = DM_ADJUDICATION_SCHEMA_VERSION
    adjudication_id: str
    source_command_id: str
    content_id: str | None = None
    category: Literal[
        "target_semantics",
        "freeform_effect",
        "illusion_interpretation",
        "environment_interaction",
        "custom_object",
        "custom_movement",
        "rule_exception",
    ]
    source_text_evidence: str
    typed_known_effects: tuple[dict[str, Any], ...] = ()
    open_questions: tuple[str, ...] = ()
    allowed_decision_schema: tuple[str, ...] = ()
    frozen_context: dict[str, Any] = Field(default_factory=dict)
    expected_versions: KernelExpectedVersions = Field(default_factory=KernelExpectedVersions)
    expires_at: datetime | None = None


class TypedTargetContext(KernelModel):
    """Name-independent target context frozen at the producer boundary."""

    campaign_id: str = Field(min_length=1, max_length=36)
    scene_id: str | None = Field(default=None, max_length=36)
    actor_id: str = Field(min_length=1, max_length=36)
    target_kind: Literal["self", "single_entity", "single_object"] = "self"
    target_id: str | None = Field(default=None, max_length=36)
    target_type: Literal["character", "creature", "object"] | None = None

    @model_validator(mode="after")
    def validate_target_context(self) -> TypedTargetContext:
        if self.target_kind == "self":
            if self.target_id not in {None, self.actor_id}:
                raise ValueError("self target context must point at actor")
            if self.target_type not in {None, "character", "creature"}:
                raise ValueError("self target context cannot target an object")
        elif not self.target_id:
            raise ValueError("entity/object target context requires target_id")
        if self.target_kind == "single_object" and self.target_type != "object":
            raise ValueError("object target context requires target_type=object")
        if self.target_kind == "single_entity" and self.target_type == "object":
            raise ValueError("entity target context cannot target an object")
        return self


class SourceClauseBinding(KernelModel):
    content_id: str = Field(min_length=1, max_length=200)
    source_record_id: str = Field(min_length=1, max_length=120)
    source_fingerprint: str = Field(min_length=32, max_length=128)
    clause_ids: tuple[str, ...] = Field(min_length=1, max_length=64)


class TypedEffectEnvelope(KernelModel):
    allowed_effect_kinds: tuple[
        Literal[
            "modifier",
            "capability",
            "communication",
            "illusion",
            "object_effect",
            "instant_sensory",
        ],
        ...,
    ] = ()
    allowed_fields: tuple[str, ...] = ()
    duration: dict[str, Any] | None = None
    max_concurrent: int | None = Field(default=None, ge=1, le=100)
    source_semantics: tuple[str, ...] = ()


class TypedAdjudicationContract(KernelModel):
    schema_version: Literal["typed-adjudication-1"] = TYPED_ADJUDICATION_SCHEMA_VERSION
    decision_kind: Literal[
        "target_selection",
        "effect_mode",
        "illusion_interpretation",
        "communication_path",
        "capability_scope",
    ]
    target_context: TypedTargetContext
    effect_envelope: TypedEffectEnvelope
    source_binding: SourceClauseBinding


class RulesKernelAdjudicationDecision(KernelModel):
    adjudication_id: str
    status: Literal["approved", "modified", "rejected"]
    approved_targets: tuple[str, ...] = ()
    approved_position: KernelPosition | None = None
    approved_duration: dict[str, Any] | None = None
    approved_damage: dict[str, Any] | None = None
    approved_condition: dict[str, Any] | None = None
    approved_object_profile: dict[str, Any] | None = None
    approved_movement: dict[str, Any] | None = None
    approved_exception: str | None = None
    notes: str | None = Field(default=None, max_length=2_000)
    typed_contract: TypedAdjudicationContract | None = None


class RulesKernelPreview(KernelModel):
    schema_version: Literal["rules-kernel-1"] = RULES_KERNEL_SCHEMA_VERSION
    command_id: str
    command_fingerprint: str
    preview_version: int = Field(ge=1)
    status: Literal["ready", "blocked", "pending_choice", "pending_adjudication"]
    legal: bool
    blockers: tuple[RulesKernelBlocker, ...] = ()
    frozen_actor: dict[str, Any] = Field(default_factory=dict)
    frozen_targets: tuple[dict[str, Any], ...] = ()
    frozen_spatial_snapshot: dict[str, Any] = Field(default_factory=dict)
    required_choices: tuple[dict[str, Any], ...] = ()
    required_rolls: tuple[str, ...] = ()
    required_adjudications: tuple[RulesKernelAdjudicationRequest, ...] = ()
    predicted_resource_cost: KernelResourceIntent = Field(default_factory=KernelResourceIntent)
    predicted_action_cost: str = "none"
    predicted_effects: tuple[dict[str, Any], ...] = ()
    predicted_scene_delta: tuple[dict[str, Any], ...] = ()
    expires_at: datetime | None = None


class RulesKernelConfirmation(KernelModel):
    schema_version: Literal["rules-kernel-1"] = RULES_KERNEL_SCHEMA_VERSION
    command_id: str
    preview_version: int = Field(ge=1)
    confirmed_choices: tuple[KernelChoiceInput, ...] = ()
    confirmed_targets: tuple[str, ...] = ()
    confirmed_rolls: KernelRollInputs = Field(default_factory=KernelRollInputs)
    adjudication_decisions: tuple[RulesKernelAdjudicationDecision, ...] = ()
    expected_versions: KernelExpectedVersions = Field(default_factory=KernelExpectedVersions)
    idempotency_key: str = Field(min_length=8, max_length=160)


class RulesKernelStateDelta(KernelModel):
    delta_id: str
    source_command_id: str
    entity_id: str
    field: str
    before: Any
    after: Any
    version_before: int | None = None
    version_after: int | None = None


SCENE_DELTA_TYPES = (
    "move_entity",
    "teleport_entity",
    "spawn_entity",
    "despawn_entity",
    "create_object",
    "remove_object",
    "create_hazard",
    "remove_hazard",
    "apply_visual_effect",
    "remove_visual_effect",
    "update_health",
    "update_resource",
    "apply_condition",
    "remove_condition",
    "set_concentration",
    "clear_concentration",
    "emit_floating_text",
    "emit_combat_log",
    "request_dm_adjudication",
)


class RulesKernelSceneDelta(KernelModel):
    schema_version: Literal["scene-delta-1"] = SCENE_DELTA_SCHEMA_VERSION
    delta_id: str
    source_command_id: str
    scene_id: str | None = None
    delta_type: Literal[
        "move_entity",
        "teleport_entity",
        "spawn_entity",
        "despawn_entity",
        "create_object",
        "remove_object",
        "create_hazard",
        "remove_hazard",
        "apply_visual_effect",
        "remove_visual_effect",
        "update_health",
        "update_resource",
        "apply_condition",
        "remove_condition",
        "set_concentration",
        "clear_concentration",
        "emit_floating_text",
        "emit_combat_log",
        "request_dm_adjudication",
    ]
    entity_id: str | None = None
    object_id: str | None = None
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(ge=1)
    sequence: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class RulesKernelResult(KernelModel):
    schema_version: Literal["rules-kernel-1"] = RULES_KERNEL_SCHEMA_VERSION
    result_id: str
    command_id: str
    status: Literal["confirmed", "rejected", "pending_choice", "pending_adjudication"]
    actual_resource_cost: KernelResourceIntent = Field(default_factory=KernelResourceIntent)
    actual_action_cost: str = "none"
    roll_results: dict[str, Any] = Field(default_factory=dict)
    save_results: dict[str, Any] = Field(default_factory=dict)
    damage_results: tuple[dict[str, Any], ...] = ()
    healing_results: tuple[dict[str, Any], ...] = ()
    condition_results: tuple[dict[str, Any], ...] = ()
    movement_results: tuple[dict[str, Any], ...] = ()
    entity_results: tuple[dict[str, Any], ...] = ()
    state_delta: tuple[RulesKernelStateDelta, ...] = ()
    scene_delta: tuple[RulesKernelSceneDelta, ...] = ()
    event_ids: tuple[str, ...] = ()
    new_versions: dict[str, int] = Field(default_factory=dict)
    operation_transaction_id: str | None = None
    adjudication_receipt: dict[str, Any] = Field(default_factory=dict)
    idempotent_replay: bool = False


class SceneQuery(KernelModel):
    schema_version: Literal["scene-query-1"] = SCENE_QUERY_SCHEMA_VERSION
    query_id: str
    scene_id: str
    combat_id: str | None = None
    query_kind: Literal[
        "entity_position",
        "entities_in_range",
        "visible_entities",
        "unoccupied_space",
        "cover",
        "distance",
        "path",
        "area_targets",
    ]
    entity_ids: tuple[str, ...] = ()
    origin: KernelPosition | None = None
    destination: KernelPosition | None = None
    shape: Literal["point", "cone", "line", "cube", "sphere", "cylinder"] | None = None
    size_ft: int | None = Field(default=None, ge=5, le=10_000)
    maximum_distance_ft: int | None = Field(default=None, ge=0, le=10_000)


def protocol_json_schema(model: type[KernelModel]) -> dict[str, Any]:
    """Return a standalone JSON Schema without Python-specific metadata."""

    return model.model_json_schema(mode="serialization")
