from __future__ import annotations

import hashlib
import json
import re
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
    requires_line_of_sight: bool = True

    @model_validator(mode="after")
    def validate_geometry(self) -> TargetBlock:
        if self.mode == "area" and (self.shape is None or self.size_ft is None):
            raise ValueError("area targets require shape and size_ft")
        if self.mode != "area" and (self.shape is not None or self.size_ft is not None):
            raise ValueError("shape and size_ft are only valid for area targets")
        if self.mode == "self" and self.range_ft not in {None, 0}:
            raise ValueError("self target cannot have a positive range")
        return self


class RollBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["roll"] = "roll"
    roll_type: Literal["attack", "ability_check"]
    die: Literal["d20"] = "d20"
    ability: str | None = Field(default=None, min_length=1, max_length=40)
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


class DamageBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["damage"] = "damage"
    expression: str = Field(min_length=1, max_length=80)
    damage_type: str = Field(min_length=1, max_length=50)
    applies_on: Literal["always", "hit", "save_failure"] = "always"
    shared_roll: bool = True
    save_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_damage(self) -> DamageBlock:
        if not _DICE_EXPRESSION.fullmatch(self.expression.replace(" ", "")):
            raise ValueError("damage expression must be deterministic dice notation")
        if self.applies_on == "save_failure" and self.save_block_id is None:
            raise ValueError("save_failure damage requires save_block_id")
        return self


class HealBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["heal"] = "heal"
    expression: str = Field(min_length=1, max_length=80)
    temporary_hp: bool = False
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_healing(self) -> HealBlock:
        if not _DICE_EXPRESSION.fullmatch(self.expression.replace(" ", "")):
            raise ValueError("healing expression must be deterministic dice notation")
        return self


class ConditionBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["condition"] = "condition"
    operation: Literal["apply", "remove"]
    condition: str = Field(min_length=1, max_length=120)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    duration_block_id: str | None = Field(default=None, min_length=1, max_length=80)
    save_ends: bool = False


class MoveBlock(RuleSchema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: Literal["move"] = "move"
    distance_ft: int = Field(ge=0, le=10_000)
    movement_type: Literal["walk", "fly", "swim", "burrow", "teleport", "forced"]
    direction: Literal["chosen", "toward", "away", "push", "pull"] = "chosen"
    target_block_id: str | None = Field(default=None, min_length=1, max_length=80)


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
    count: int = Field(default=1, ge=1, le=1_000)
    controller: Literal["caster", "dm", "independent"] = "caster"
    duration_block_id: str | None = Field(default=None, min_length=1, max_length=80)


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
    | HealBlock
    | ConditionBlock
    | MoveBlock
    | ResourceBlock
    | DurationBlock
    | RepeatBlock
    | ChoiceBlock
    | SummonBlock
    | TriggerBlock
    | NarrativeBlock,
    Field(discriminator="kind"),
]


class RulePlan(RuleSchema):
    schema_version: Literal["1.0"] = "1.0"
    source_kind: Literal["spell", "action", "feature", "item", "monster_action", "unknown"]
    source_name: str = Field(min_length=1, max_length=240)
    source_ref: str | None = Field(default=None, min_length=1, max_length=500)
    blocks: tuple[RuleBlock, ...] = Field(min_length=1, max_length=2_000)
    root_block_ids: tuple[str, ...] = Field(min_length=1, max_length=2_000)
    automation_confidence: Literal["exact", "partial", "manual"]
    automation_ready: bool
    unresolved_reasons: tuple[str, ...] = Field(default=(), max_length=100)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_graph(self) -> RulePlan:
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


def build_execution_plan(plan: RulePlan) -> ExecutionPlan:
    """Flatten a validated rule graph without rolling dice or mutating game state."""

    by_id = {block.id: block for block in plan.blocks}
    steps: list[ExecutionStep] = []

    def append(block_id: str, depends_on: tuple[str, ...], guards: tuple[str, ...]) -> str:
        block = by_id[block_id]
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
        steps=tuple(steps),
    )


def validate_rule_plan(value: dict[str, Any]) -> RulePlan:
    """Strictly validate untrusted JSON before it reaches an executor."""

    return RulePlan.model_validate_json(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )
