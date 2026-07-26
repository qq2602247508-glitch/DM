from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from dnd_dm_assistant.domain.rag import Citation


class AbilityScores(BaseModel):
    strength: int = Field(10, ge=1, le=30)
    dexterity: int = Field(10, ge=1, le=30)
    constitution: int = Field(10, ge=1, le=30)
    intelligence: int = Field(10, ge=1, le=30)
    wisdom: int = Field(10, ge=1, le=30)
    charisma: int = Field(10, ge=1, le=30)


class GeneratedAction(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1_000)


class GeneratedItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1_000)
    category: str = Field(default="misc", max_length=50)
    quantity: int = Field(default=1, ge=1, le=100)
    unit_weight_lb: float = Field(default=0, ge=0, le=10_000)
    price_cp: int = Field(default=0, ge=0, le=10_000_000)
    interactive_note: str | None = Field(default=None, max_length=500)
    hidden: bool = False


class GeneratedNPC(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    alignment: str | None = Field(default=None, max_length=100)
    attitude: str | None = Field(default=None, max_length=100)
    personality: str | None = Field(default=None, max_length=1_000)
    goal: str | None = Field(default=None, max_length=1_000)
    fear: str | None = Field(default=None, max_length=1_000)
    secret: str | None = Field(default=None, max_length=1_000)
    known_information: str | None = Field(default=None, max_length=1_000)
    armor_class: int = Field(default=10, ge=0, le=99)
    hp: int = Field(default=1, ge=0, le=10_000)
    max_hp: int = Field(default=1, ge=0, le=10_000)
    speed: int = Field(default=30, ge=0, le=1_000)
    ability_scores: AbilityScores = Field(
        default_factory=lambda: AbilityScores(
            strength=10,
            dexterity=10,
            constitution=10,
            intelligence=10,
            wisdom=10,
            charisma=10,
        )
    )
    challenge_rating: str | None = Field(default=None, max_length=30)
    actions: tuple[GeneratedAction, ...] = ()
    equipment: tuple[GeneratedItem, ...] = ()

    @model_validator(mode="after")
    def validate_hp(self) -> GeneratedNPC:
        if self.hp > self.max_hp:
            raise ValueError("hp cannot exceed max_hp")
        return self


class GeneratedLocationNode(BaseModel):
    temp_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    interactive_objects: tuple[str, ...] = ()
    secrets: str | None = Field(default=None, max_length=1_000)
    discovered: bool = True
    items: tuple[GeneratedItem, ...] = ()
    suggested_npcs: tuple[str, ...] = ()
    suggested_monsters: tuple[str, ...] = ()
    children: tuple[GeneratedLocationNode, ...] = ()


class NPCGenerationPreview(BaseModel):
    ruleset: Literal["dnd5e"] = "dnd5e"
    primary_rules_year: Literal[2024] = 2024
    npc: GeneratedNPC
    citations: tuple[Citation, ...] = ()
    warnings: tuple[str, ...] = ()


class LocationGenerationPreview(BaseModel):
    ruleset: Literal["dnd5e"] = "dnd5e"
    primary_rules_year: Literal[2024] = 2024
    maximum_depth: int = Field(ge=1, le=5)
    root: GeneratedLocationNode
    citations: tuple[Citation, ...] = ()
    warnings: tuple[str, ...] = ()
