from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionCheckpointCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scene_id: str | None = Field(default=None, min_length=1, max_length=36)
    active_combat_id: str | None = Field(default=None, min_length=1, max_length=36)
    entries: list[dict[str, Any]] = Field(default_factory=list, max_length=1_000)
    expected_campaign_version: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=2_000)


class SessionCheckpointRestoreRequest(BaseModel):
    expected_campaign_version: int | None = Field(default=None, ge=1)
    force: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class SessionCheckpointArchiveRequest(BaseModel):
    version: int = Field(ge=1)
