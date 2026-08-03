from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RULE_SCHEMA_VERSION = "1.0"
_DICE_EXPRESSION = re.compile(
    r"^(?:\d+|(?:\d*)d\d+)(?:[+-](?:\d+|@[a-z][a-z0-9_]*))*$",
    re.IGNORECASE,
)


class RuleSchema(BaseModel):
    """Immutable, JSON-safe base for rule data crossing application boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TargetBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["target"] = "target"
    mode: Literal["self", "single", "multiple", "point", "area"]
    disposition: Literal["self", "ally", "enemy", "creature", "object", "any"] = "any"
    range_ft: int | None = Field(default=None, ge=0, le=10_000)
    max_targets: int | None = Field(default=None, ge=1, le=1_000)
    shape: Literal["sphere", "cone", "line", "cube", "cylinder"] | None = None
    size_ft: int | None = Field(default=None, gt=0, le=10_000)
    width_ft: int | None = Field(default=None, gt=0, le=10_000)
    height_ft: int | None = Field(default=None, gt=0, le=10_000)
    anchor_height_ft: int = Field(default=0, ge=-10_000, le=10_000)
    requires_explicit_elevation: bool = False
    secondary_range_ft: int | None = Field(default=None, gt=0, le=10_000)
    secondary_max_targets: int | None = Field(default=None, ge=1, le=1_000)
    requires_line_of_sight: bool = True

    @model_validator(mode="after")
    def validate_geometry(self) -> TargetBlock:
        if self.mode == "area" and (self.shape is None or self.size_ft is None):
            raise ValueError("area targets require shape and size_ft")
        if self.mode != "area" and (self.shape is not None or self.size_ft is not None):
            raise ValueError("shape and size_ft are only valid for area targets")
        if self.mode != "area" and (
            self.anchor_height_ft != 0 or self.requires_explicit_elevation
        ):
            raise ValueError("3-D area fields are only valid for area targets")
        if self.width_ft is not None and (self.mode != "area" or self.shape != "line"):
            raise ValueError("width_ft is only valid for line area targets")
        if self.height_ft is not None and (self.mode != "area" or self.shape != "cylinder"):
            raise ValueError("height_ft is only valid for cylinder area targets")
        if self.mode != "multiple" and (
            self.secondary_range_ft is not None or self.secondary_max_targets is not None
        ):
            raise ValueError("secondary target fields are only valid for multiple targets")
        if (
            self.secondary_max_targets is not None
            and self.max_targets is not None
            and self.secondary_max_targets >= self.max_targets
        ):
            raise ValueError("secondary_max_targets must leave room for a primary target")
        if self.mode == "self" and self.range_ft not in {None, 0}:
            raise ValueError("self target cannot have a positive range")
        return self


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    """A combat-agnostic candidate passed into target selection."""

    id: str
    relation: Literal["self", "ally", "enemy"]
    category: Literal["creature", "object"] = "creature"
    active: bool = True


class TargetResolutionIssue(RuleSchema):
    code: Literal[
        "missing_target",
        "inactive_target",
        "invalid_primary",
        "target_count",
        "target_limit",
        "secondary_target_limit",
        "disposition",
        "category",
    ]
    target_id: str | None = Field(default=None, min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=240)


class TargetResolution(RuleSchema):
    """The deterministic, pre-geometry result of resolving a target block."""

    target_block_id: str = Field(min_length=1, max_length=80)
    mode: Literal["self", "single", "multiple", "point", "area"]
    disposition: Literal["self", "ally", "enemy", "creature", "object", "any"]
    primary_target_id: str = Field(min_length=1, max_length=80)
    target_ids: tuple[str, ...]
    issues: tuple[TargetResolutionIssue, ...] = ()

    @property
    def accepted(self) -> bool:
        return not self.issues


class DamageComponentTotal(RuleSchema):
    """An explicitly reported total for one typed damage block."""

    block_id: str = Field(min_length=1, max_length=80)
    damage_type: str = Field(min_length=1, max_length=50)
    total: int = Field(ge=0, le=100_000)


def resolve_target_selection(
    target: TargetBlock,
    *,
    caster_id: str,
    primary_target_id: str,
    requested_target_ids: Sequence[str],
    candidates: Sequence[TargetCandidate],
) -> TargetResolution:
    """Apply typed target count and disposition rules without map assumptions.

    Geometry is deliberately outside this function: callers must provide an
    explicit map/grid and use the area dimensions from ``TargetBlock``.  This
    keeps a missing distance, area orientation, or line width from becoming an
    invented five-foot value.
    """

    target_ids = tuple(dict.fromkeys(str(value) for value in requested_target_ids if str(value)))
    candidates_by_id = {candidate.id: candidate for candidate in candidates}
    issues: list[TargetResolutionIssue] = []

    if primary_target_id not in target_ids:
        issues.append(
            TargetResolutionIssue(
                code="invalid_primary",
                target_id=primary_target_id,
                message="primary target must be included in the selected targets",
            )
        )
    if target.mode in {"self", "single", "point"} and len(target_ids) != 1:
        issues.append(
            TargetResolutionIssue(
                code="target_count",
                message=f"{target.mode} target rules require exactly one selected target",
            )
        )
    if target.mode in {"multiple", "area"} and not target_ids:
        issues.append(
            TargetResolutionIssue(
                code="target_count",
                message=f"{target.mode} target rules require at least one selected target",
            )
        )
    if target.max_targets is not None and len(target_ids) > target.max_targets:
        issues.append(
            TargetResolutionIssue(
                code="target_limit",
                message=f"target rules allow at most {target.max_targets} selected targets",
            )
        )
    if (
        target.secondary_max_targets is not None
        and len(target_ids) - 1 > target.secondary_max_targets
    ):
        issues.append(
            TargetResolutionIssue(
                code="secondary_target_limit",
                message=(
                    "target rules allow at most "
                    f"{target.secondary_max_targets} secondary targets"
                ),
            )
        )

    for target_id in target_ids:
        candidate = candidates_by_id.get(target_id)
        if candidate is None:
            issues.append(
                TargetResolutionIssue(
                    code="missing_target",
                    target_id=target_id,
                    message="selected target is not available in this resolution",
                )
            )
            continue
        if not candidate.active:
            issues.append(
                TargetResolutionIssue(
                    code="inactive_target",
                    target_id=target_id,
                    message="selected target is inactive",
                )
            )
            continue
        if target.disposition == "self" and candidate.id != caster_id:
            issues.append(
                TargetResolutionIssue(
                    code="disposition",
                    target_id=target_id,
                    message="target rules only allow the caster",
                )
            )
        elif target.disposition == "ally" and candidate.relation not in {"self", "ally"}:
            issues.append(
                TargetResolutionIssue(
                    code="disposition",
                    target_id=target_id,
                    message="target rules only allow allies",
                )
            )
        elif target.disposition == "enemy" and candidate.relation != "enemy":
            issues.append(
                TargetResolutionIssue(
                    code="disposition",
                    target_id=target_id,
                    message="target rules only allow enemies",
                )
            )
        elif target.disposition == "creature" and candidate.category != "creature":
            issues.append(
                TargetResolutionIssue(
                    code="category",
                    target_id=target_id,
                    message="target rules only allow creatures",
                )
            )
        elif target.disposition == "object" and candidate.category != "object":
            issues.append(
                TargetResolutionIssue(
                    code="category",
                    target_id=target_id,
                    message="target rules only allow objects",
                )
            )

    return TargetResolution(
        target_block_id=target.id,
        mode=target.mode,
        disposition=target.disposition,
        primary_target_id=primary_target_id,
        target_ids=target_ids,
        issues=tuple(issues),
    )


def resolve_damage_component_totals(
    damage_blocks: Sequence[DamageBlock],
    *,
    legacy_total: int | None = None,
    component_totals: Mapping[str, int] | None = None,
) -> tuple[DamageComponentTotal, ...]:
    """Bind player-reported totals to typed damage blocks without splitting rolls.

    The legacy player endpoint exposes a single ``damage_total``.  It is valid
    only for a single damage block.  A mixed-damage plan must provide one
    explicit integer per block; proportional splitting by dice, averages, or a
    default value would be a rules guess and is intentionally rejected.
    """

    if not damage_blocks:
        raise ValueError("damage component resolution requires at least one damage block")
    if component_totals is None:
        if legacy_total is None:
            raise ValueError("damage component totals are required")
        if len(damage_blocks) != 1:
            raise ValueError(
                "multiple damage blocks require an explicit total for each damage block"
            )
        component_totals = {damage_blocks[0].id: legacy_total}
    expected_ids = {block.id for block in damage_blocks}
    actual_ids = set(component_totals)
    if actual_ids != expected_ids:
        raise ValueError("damage component totals must match the plan damage block ids exactly")

    totals: list[DamageComponentTotal] = []
    for block in damage_blocks:
        value = component_totals[block.id]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("damage component totals must be non-negative integers")
        totals.append(
            DamageComponentTotal(
                block_id=block.id,
                damage_type=block.damage_type,
                total=value,
            )
        )
    return tuple(totals)


class RollBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["roll"] = "roll"
    roll_type: Literal["attack", "ability_check"]
    die: Literal["d20"] = "d20"
    ability: str | None = Field(default=None, min_length=1, max_length=40)
    skill: str | None = Field(default=None, min_length=1, max_length=80)
    modifier: int | None = Field(default=None, ge=-100, le=100)
    proficiency: Literal["none", "if_proficient", "always"] = "if_proficient"
    target_defense: Literal["ac", "dc"]
    dc: int | None = Field(default=None, ge=0, le=100)
    dc_source: str | None = Field(default=None, min_length=1, max_length=80)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_dc(self) -> RollBlock:
        if self.target_defense == "dc" and (self.dc is None) == (self.dc_source is None):
            raise ValueError("a DC roll requires exactly one of dc or dc_source")
        if self.target_defense == "ac" and (self.dc is not None or self.dc_source is not None):
            raise ValueError("an AC roll cannot declare a fixed DC")
        return self


class SaveBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["save"] = "save"
    ability: str = Field(min_length=1, max_length=40)
    dc: int | None = Field(default=None, ge=0, le=100)
    dc_source: str | None = Field(default=None, min_length=1, max_length=80)
    on_success: Literal["none", "half", "full", "special"] = "none"
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_dc(self) -> SaveBlock:
        if (self.dc is None) == (self.dc_source is None):
            raise ValueError("a save requires exactly one of dc or dc_source")
        return self


class SpellSlotScaling(RuleSchema):
    """A verified per-slot-level dice increment for one spell effect."""

    base_spell_level: int = Field(ge=1, le=9)
    dice_per_level: int = Field(ge=1, le=100)


class DamageBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["damage"] = "damage"
    expression: str = Field(min_length=1, max_length=80)
    damage_type: str = Field(min_length=1, max_length=50)
    applies_on: Literal["always", "hit", "save_failure"] = "always"
    shared_roll: bool = True
    save_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    spell_slot_scaling: SpellSlotScaling | None = None

    @model_validator(mode="after")
    def validate_damage(self) -> DamageBlock:
        if not _DICE_EXPRESSION.fullmatch(self.expression.replace(" ", "")):
            raise ValueError("damage expression must be deterministic dice notation")
        if self.applies_on == "save_failure" and self.save_block_id is None:
            raise ValueError("save_failure damage requires save_block_id")
        if self.spell_slot_scaling and not re.match(r"^(?:\d*)d\d+", self.expression, re.I):
            raise ValueError("spell-slot damage scaling requires a leading dice term")
        return self


class DefenseBlock(RuleSchema):
    """A typed damage defense copied from a creature's stat block."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["defense"] = "defense"
    operation: Literal["resistance", "vulnerability", "immunity"]
    damage_types: tuple[str, ...] = Field(min_length=1, max_length=50)
    applies_on: Literal["always", "hit", "miss", "save_success", "save_failure"] | None = None
    condition: str | None = Field(default=None, min_length=1, max_length=240)


class ModifierBlock(RuleSchema):
    """A typed persistent combat modifier that the executor can consume safely."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["modifier"] = "modifier"
    stat: Literal[
        "armor_class",
        "speed_ft",
        "attack_roll",
        "damage_roll",
        "saving_throw",
        "ability_check",
        "skill_check",
        "action",
        "bonus_action",
        "reaction",
    ]
    operation: Literal["add", "set", "advantage", "disadvantage", "grant"]
    value: int | None = Field(default=None, ge=-1_000, le=1_000)
    expression: str | None = Field(default=None, min_length=1, max_length=80)
    scope: Literal["self", "incoming", "outgoing", "all"] = "all"
    skill: str | None = Field(default=None, min_length=1, max_length=80)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    duration_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    source: str | None = Field(default=None, min_length=1, max_length=240)
    applies_on: Literal["always", "hit", "miss", "save_success", "save_failure"] | None = None

    @model_validator(mode="after")
    def validate_modifier(self) -> ModifierBlock:
        needs_value = self.operation in {"add", "set"}
        if needs_value != (self.value is not None):
            raise ValueError(
                "add/set modifiers require value; advantage/disadvantage/grant forbid it"
            )
        if self.operation in {"advantage", "disadvantage"} and self.expression is not None:
            raise ValueError("advantage/disadvantage modifiers cannot declare an expression")
        return self


class ObjectStateBlock(RuleSchema):
    """A deterministic exploration interaction with an existing scene object."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["object_state"] = "object_state"
    operation: Literal["set", "toggle"] = "set"
    state: Literal[
        "active",
        "open",
        "closed",
        "locked",
        "unlocked",
        "repaired",
        "destroyed",
        "disarmed",
        "picked_up",
    ]
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    object_types: tuple[str, ...] = Field(default=(), max_length=20)
    requires_dm_adjudication: bool = False


class ExplorationEffectBlock(RuleSchema):
    """A bounded non-combat effect that queries or changes shared scene state."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["exploration_effect"] = "exploration_effect"
    operation: Literal[
        "light",
        "darkness",
        "detect_magic",
        "detect_trap",
        "locate",
        "communicate",
        "grant_language",
        "create_supply",
    ]
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    duration_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    radius_ft: int | None = Field(default=None, ge=0, le=10_000)
    details: str | None = Field(default=None, min_length=1, max_length=2_000)
    requires_dm_adjudication: bool = False


class HealBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["heal"] = "heal"
    expression: str = Field(min_length=1, max_length=80)
    temporary_hp: bool = False
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    spell_slot_scaling: SpellSlotScaling | None = None
    applies_on: Literal["always", "hit", "miss", "save_success", "save_failure"] | None = None

    @model_validator(mode="after")
    def validate_healing(self) -> HealBlock:
        if not _DICE_EXPRESSION.fullmatch(self.expression.replace(" ", "")):
            raise ValueError("healing expression must be deterministic dice notation")
        if self.spell_slot_scaling and not re.match(r"^(?:\d*)d\d+", self.expression, re.I):
            raise ValueError("spell-slot healing scaling requires a leading dice term")
        return self


class ConditionBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["condition"] = "condition"
    operation: Literal["apply", "remove"]
    condition: str = Field(min_length=1, max_length=120)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    duration_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    save_ends: bool = False
    applies_on: Literal["always", "hit", "miss", "save_success", "save_failure"] | None = None


class MoveBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["move"] = "move"
    distance_ft: int = Field(ge=0, le=10_000)
    movement_type: Literal["walk", "fly", "swim", "burrow", "teleport", "forced"]
    direction: Literal["chosen", "toward", "away", "push", "pull"] = "chosen"
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    applies_on: Literal["always", "hit", "miss", "save_success", "save_failure"] | None = None


class AreaEffectBlock(RuleSchema):
    """A persistent, explicitly placed combat zone.

    Area geometry is not inferred by an executor.  A player must provide its
    origin whenever ``requires_origin_choice`` is true; the compiler only
    carries the already structured shape, dimensions, and child-effect links.
    """

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["area_effect"] = "area_effect"
    shape: Literal["sphere", "cone", "line", "cube", "cylinder"]
    size_ft: int = Field(gt=0, le=10_000)
    width_ft: int | None = Field(default=None, gt=0, le=10_000)
    height_ft: int | None = Field(default=None, gt=0, le=10_000)
    origin: Literal["self", "chosen_point"] = "chosen_point"
    effect_block_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    duration_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    trigger_timing: Literal["enter", "turn_start", "turn_end", "round_start", "round_end"]
    requires_origin_choice: bool = True

    @model_validator(mode="after")
    def validate_area(self) -> AreaEffectBlock:
        if self.shape == "line" and self.width_ft is None:
            raise ValueError("line area effects require width_ft")
        if self.height_ft is not None and self.shape != "cylinder":
            raise ValueError("height_ft is only valid for cylinder area effects")
        if self.origin == "self" and self.requires_origin_choice:
            raise ValueError("self-origin area effects cannot require an origin choice")
        return self


class TeleportBlock(RuleSchema):
    """A destination-sensitive teleport that must never invent a destination."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["teleport"] = "teleport"
    destination_kind: Literal["chosen_space", "known_location", "object", "creature"]
    max_distance_ft: int | None = Field(default=None, ge=0, le=1_000_000)
    destination_ref: str | None = Field(default=None, min_length=1, max_length=240)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    can_take_creatures: bool = False
    requires_destination_choice: bool = True


class TransformationBlock(RuleSchema):
    """A reversible form change whose form template is explicit or DM-selected."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["transformation"] = "transformation"
    mode: Literal["polymorph", "shapechange", "disguise", "alter"]
    form_ref: str = Field(min_length=1, max_length=240)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    preserve_personality: bool = True
    reversible: bool = True
    requires_form_choice: bool = True


class CreationBlock(RuleSchema):
    """Create an explicit item/object/scene entity; no implicit quantity or template."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["creation"] = "creation"
    creation_kind: Literal["item", "object", "portal", "terrain", "creature"]
    template_ref: str = Field(min_length=1, max_length=240)
    count: int | None = Field(default=None, ge=1, le=1_000)
    count_expression: str | None = Field(default=None, min_length=1, max_length=160)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    duration_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    requires_template_choice: bool = True

    @model_validator(mode="after")
    def validate_count(self) -> CreationBlock:
        if self.count is not None and self.count_expression is not None:
            raise ValueError("creation cannot declare both count and count_expression")
        return self


class DispelBlock(RuleSchema):
    """Remove or contest an existing effect through an explicit target/effect choice."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["dispel"] = "dispel"
    mode: Literal["dispel", "counterspell"]
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    effect_types: tuple[str, ...] = Field(default=(), max_length=30)
    check_required: bool = False
    check_dc_source: str | None = Field(default=None, min_length=1, max_length=120)


class ResourceBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["resource"] = "resource"
    resource_key: str = Field(min_length=1, max_length=120)
    operation: Literal["spend", "restore", "set"]
    amount: int = Field(ge=0, le=1_000_000)
    minimum_required: int | None = Field(default=None, ge=0, le=1_000_000)


class DurationBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["duration"] = "duration"
    unit: Literal[
        "instant",
        "round",
        "minute",
        "hour",
        "day",
        "until_save",
        "until_removed",
        "permanent",
    ]
    value: int | None = Field(default=None, ge=0, le=1_000_000)
    concentration: bool = False

    @model_validator(mode="after")
    def validate_duration(self) -> DurationBlock:
        timed = self.unit in {"round", "minute", "hour", "day"}
        if timed != (self.value is not None):
            raise ValueError("timed durations require value; untimed durations forbid it")
        return self


class RepeatBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["repeat"] = "repeat"
    block_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    count: int | None = Field(default=None, ge=1, le=1_000)
    count_expression: str | None = Field(default=None, min_length=1, max_length=80)
    timing: Literal["immediate", "turn_start", "turn_end", "round_start", "round_end"]

    @model_validator(mode="after")
    def validate_count(self) -> RepeatBlock:
        if (self.count is None) == (self.count_expression is None):
            raise ValueError("repeat requires exactly one of count or count_expression")
        return self


class ChoiceOption(RuleSchema):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=160)
    block_ids: tuple[str, ...] = Field(min_length=1, max_length=100)


class ChoiceBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["choice"] = "choice"
    prompt: str = Field(min_length=1, max_length=1_000)
    options: tuple[ChoiceOption, ...] = Field(min_length=2, max_length=100)
    minimum_choices: int = Field(default=1, ge=1, le=100)
    maximum_choices: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def validate_choices(self) -> ChoiceBlock:
        if self.minimum_choices > self.maximum_choices:
            raise ValueError("minimum_choices cannot exceed maximum_choices")
        if self.maximum_choices > len(self.options):
            raise ValueError("maximum_choices cannot exceed option count")
        keys = [option.key for option in self.options]
        if len(keys) != len(set(keys)):
            raise ValueError("choice option keys must be unique")
        return self


class SummonBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["summon"] = "summon"
    creature_ref: str = Field(min_length=1, max_length=240)
    count: int | None = Field(default=1, ge=1, le=1_000)
    count_expression: str | None = Field(default=None, min_length=1, max_length=160)
    controller: Literal["caster", "dm", "independent"] = "caster"
    enters_combat: bool = True
    initiative_mode: Literal["independent", "shared_with_source", "not_applicable"] = (
        "independent"
    )
    duration_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    template_ref: str | None = Field(default=None, min_length=1, max_length=240)
    requires_template_choice: bool = True
    enemy_ai_mode: Literal["dm_only", "basic", "not_applicable"] = "not_applicable"

    @model_validator(mode="after")
    def validate_initiative(self) -> SummonBlock:
        if (self.count is None) == (self.count_expression is None):
            raise ValueError("summon requires exactly one of count or count_expression")
        if not self.enters_combat and self.initiative_mode != "not_applicable":
            raise ValueError("non-combat summons cannot declare an initiative")
        if self.enters_combat and self.initiative_mode == "not_applicable":
            raise ValueError("combat summons require an initiative mode")
        if self.controller != "dm" and self.enemy_ai_mode != "not_applicable":
            raise ValueError("only DM-controlled summons can declare an enemy AI mode")
        return self


class TriggerBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["trigger"] = "trigger"
    event: str = Field(min_length=1, max_length=240)
    timing: Literal["before", "after", "when"]
    block_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    once: bool = False


class NarrativeBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["narrative"] = "narrative"
    text: str = Field(min_length=1, max_length=10_000)
    requires_dm_adjudication: bool = True


RuleBlock = Annotated[
    TargetBlock
    | RollBlock
    | SaveBlock
    | DamageBlock
    | DefenseBlock
    | ModifierBlock
    | HealBlock
    | ConditionBlock
    | MoveBlock
    | AreaEffectBlock
    | TeleportBlock
    | TransformationBlock
    | CreationBlock
    | DispelBlock
    | ResourceBlock
    | DurationBlock
    | RepeatBlock
    | ChoiceBlock
    | SummonBlock
    | TriggerBlock
    | ObjectStateBlock
    | ExplorationEffectBlock
    | NarrativeBlock,
    Field(discriminator="kind"),
]


class RulePlan(RuleSchema):
    schema_version: Literal["1.0"] = "1.0"
    source_kind: Literal[
        "spell", "action", "feature", "item", "monster", "monster_action", "rule", "unknown"
    ]
    source_name: str = Field(min_length=1, max_length=240)
    source_ref: str | None = Field(default=None, min_length=1, max_length=500)
    spell_level: int | None = Field(default=None, ge=0, le=9)
    blocks: tuple[RuleBlock, ...] = Field(min_length=1, max_length=2_000)
    root_block_ids: tuple[str, ...] = Field(min_length=1, max_length=2_000)
    automation_confidence: Literal["exact", "partial", "manual"]
    automation_ready: bool
    unresolved_reasons: tuple[str, ...] = Field(default=(), max_length=100)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_graph(self) -> RulePlan:
        if self.source_kind != "spell" and self.spell_level is not None:
            raise ValueError("spell_level is only valid for spell plans")
        for block in self.blocks:
            if isinstance(block, DamageBlock | HealBlock) and block.spell_slot_scaling:
                if self.spell_level != block.spell_slot_scaling.base_spell_level:
                    raise ValueError("spell-slot scaling must match the plan's base spell level")
        ids = [block.id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("block ids must be unique")
        known = set(ids)
        roots = set(self.root_block_ids)
        if not roots <= known:
            raise ValueError("root_block_ids must reference existing blocks")
        if len(self.root_block_ids) != len(roots):
            raise ValueError("root_block_ids must be unique")
        by_id = {block.id: block for block in self.blocks}
        references: dict[str, tuple[str, ...]] = {}
        for block in self.blocks:
            refs: tuple[str, ...] = ()
            if isinstance(block, RepeatBlock | TriggerBlock):
                refs = block.block_ids
            elif isinstance(block, ChoiceBlock):
                refs = tuple(ref for option in block.options for ref in option.block_ids)
            elif isinstance(block, AreaEffectBlock):
                # A persistent area owns its child effects.  They are not roots:
                # the executor must wait for the area's declared trigger rather
                # than accidentally applying the children at cast time.
                refs = block.effect_block_ids
            references[block.id] = refs
            if not set(refs) <= known:
                raise ValueError(f"{block.id} references an unknown block")
            direct_refs = tuple(
                value
                for value in (
                    getattr(block, "target_block_id", None),
                    getattr(block, "save_block_id", None),
                    getattr(block, "duration_block_id", None),
                )
                if value is not None
            )
            if not set(direct_refs) <= known:
                raise ValueError(f"{block.id} has an unknown direct reference")
            target_ref = getattr(block, "target_block_id", None)
            save_ref = getattr(block, "save_block_id", None)
            duration_ref = getattr(block, "duration_block_id", None)
            if target_ref is not None and not isinstance(by_id[target_ref], TargetBlock):
                raise ValueError(f"{block.id} target_block_id must reference a target block")
            if save_ref is not None and not isinstance(by_id[save_ref], SaveBlock):
                raise ValueError(f"{block.id} save_block_id must reference a save block")
            if duration_ref is not None and not isinstance(by_id[duration_ref], DurationBlock):
                raise ValueError(f"{block.id} duration_block_id must reference a duration block")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(block_id: str) -> None:
            if block_id in visiting:
                raise ValueError("rule block graph cannot contain cycles")
            if block_id in visited:
                return
            visiting.add(block_id)
            for child_id in references[block_id]:
                visit(child_id)
            visiting.remove(block_id)
            visited.add(block_id)

        for root in self.root_block_ids:
            visit(root)
        referenced = {ref for refs in references.values() for ref in refs}
        if roots & referenced:
            raise ValueError("control-flow child blocks cannot also be roots")
        unreachable = known - roots - referenced
        if unreachable:
            raise ValueError(f"unreachable blocks: {', '.join(sorted(unreachable))}")
        return self


class ExecutionStep(RuleSchema):
    step_id: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=0)
    block: RuleBlock
    depends_on: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()


class ExecutionPlan(RuleSchema):
    schema_version: Literal["1.0"] = "1.0"
    source_name: str
    rule_plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_slot_level: int | None = Field(default=None, ge=1, le=9)
    steps: tuple[ExecutionStep, ...] = Field(min_length=1, max_length=10_000)


def _canonical_plan(plan: RulePlan) -> str:
    return json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def rule_plan_fingerprint(plan: RulePlan) -> str:
    return hashlib.sha256(_canonical_plan(plan).encode("utf-8")).hexdigest()


def _scale_dice_expression(expression: str, extra_dice: int) -> str:
    match = re.match(r"^(\d*)d(\d+)(.*)$", expression, re.IGNORECASE)
    if not match:
        raise ValueError("spell-slot scaling requires a leading dice term")
    return f"{int(match.group(1) or '1') + extra_dice}d{match.group(2)}{match.group(3)}"


def _execution_block(
    plan: RulePlan,
    block: RuleBlock,
    slot_level: int | None,
) -> RuleBlock:
    if slot_level is None:
        return block
    if isinstance(block, ResourceBlock) and plan.spell_level is not None:
        expected_key = f"spell_slots_{plan.spell_level}"
        if block.operation == "spend" and block.resource_key == expected_key:
            return block.model_copy(update={"resource_key": f"spell_slots_{slot_level}"})
    if isinstance(block, DamageBlock | HealBlock) and block.spell_slot_scaling:
        scaling = block.spell_slot_scaling
        extra_dice = (slot_level - scaling.base_spell_level) * scaling.dice_per_level
        return block.model_copy(
            update={"expression": _scale_dice_expression(block.expression, extra_dice)}
        )
    return block


def build_execution_plan(
    plan: RulePlan,
    *,
    slot_level: int | None = None,
) -> ExecutionPlan:
    """Flatten a validated rule graph, optionally resolving a verified spell slot."""

    if slot_level is not None:
        if (
            not isinstance(slot_level, int)
            or isinstance(slot_level, bool)
            or not 1 <= slot_level <= 9
        ):
            raise ValueError("slot_level must be an integer between 1 and 9")
        if plan.source_kind != "spell" or plan.spell_level is None or plan.spell_level <= 0:
            raise ValueError("slot_level requires a leveled spell plan")
        if slot_level < plan.spell_level:
            raise ValueError("slot_level cannot be lower than the spell's base level")

    by_id = {block.id: block for block in plan.blocks}
    steps: list[ExecutionStep] = []

    def append(block_id: str, depends_on: tuple[str, ...], guards: tuple[str, ...]) -> str:
        block = _execution_block(plan, by_id[block_id], slot_level)
        step_id = f"step-{len(steps):04d}-{block.id}"
        steps.append(
            ExecutionStep(
                step_id=step_id,
                order=len(steps),
                block=block,
                depends_on=depends_on,
                guards=guards,
            )
        )
        if isinstance(block, ChoiceBlock):
            for option in block.options:
                previous = (step_id,)
                for child_id in option.block_ids:
                    child_step = append(
                        child_id,
                        previous,
                        (*guards, f"choice:{block.id}:{option.key}"),
                    )
                    previous = (child_step,)
        elif isinstance(block, RepeatBlock | TriggerBlock):
            previous = (step_id,)
            guard = (
                f"repeat:{block.id}"
                if isinstance(block, RepeatBlock)
                else f"trigger:{block.id}"
            )
            for child_id in block.block_ids:
                child_step = append(child_id, previous, (*guards, guard))
                previous = (child_step,)
        return step_id

    previous_root: tuple[str, ...] = ()
    for root_id in plan.root_block_ids:
        previous_root = (append(root_id, previous_root, ()),)
    return ExecutionPlan(
        source_name=plan.source_name,
        rule_plan_fingerprint=rule_plan_fingerprint(plan),
        selected_slot_level=slot_level,
        steps=tuple(steps),
    )


def validate_rule_plan(value: dict[str, Any]) -> RulePlan:
    """Strictly validate untrusted JSON before it reaches an executor."""

    return RulePlan.model_validate_json(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )
