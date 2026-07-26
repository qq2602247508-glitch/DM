from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EncounterEntityType = Literal["character", "npc", "monster"]


class _StrictEncounterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _EntityOperation(_StrictEncounterModel):
    entity_type: EncounterEntityType
    entity_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=1_000)

    @field_validator("entity_id", "reason")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class RemoveEntity(_EntityOperation):
    kind: Literal["remove_entity"] = "remove_entity"


class AddSceneEntity(_EntityOperation):
    kind: Literal["add_scene_entity"] = "add_scene_entity"


class SetEntityHp(_EntityOperation):
    kind: Literal["set_entity_hp"] = "set_entity_hp"
    hp: int = Field(ge=0, le=100_000)


class AddEntityCondition(_EntityOperation):
    kind: Literal["add_entity_condition"] = "add_entity_condition"
    condition: str = Field(min_length=1, max_length=120)

    @field_validator("condition")
    @classmethod
    def strip_condition(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("condition must not be blank")
        return value


class ScheduleReinforcement(_EntityOperation):
    kind: Literal["schedule_reinforcement"] = "schedule_reinforcement"
    round: int = Field(ge=1, le=100)
    quantity: int = Field(default=1, ge=1, le=100)


EncounterOperation = Annotated[
    RemoveEntity
    | AddSceneEntity
    | SetEntityHp
    | AddEntityCondition
    | ScheduleReinforcement,
    Field(discriminator="kind"),
]


class EncounterAdjustmentDraft(_StrictEncounterModel):
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)
    difficulty_shift: Literal[-1, 0, 1] = 0
    operations: tuple[EncounterOperation, ...] = Field(default=(), max_length=8)

    @field_validator("title", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value
