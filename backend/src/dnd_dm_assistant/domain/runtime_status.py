from __future__ import annotations

from pydantic import BaseModel


class ConfiguredModelStatus(BaseModel):
    role: str
    model: str | None
    configured: bool
    installed: bool


class RuntimeModelStatus(BaseModel):
    ollama_available: bool
    think_enabled: bool = False
    models: tuple[ConfiguredModelStatus, ...]
    installed_models: tuple[str, ...] = ()
    reason: str | None = None

