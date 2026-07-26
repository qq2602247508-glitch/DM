from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DND_DM_",
        extra="ignore",
    )

    environment: str = "development"
    api_prefix: str = "/api/v1"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    frontend_origin: str = "http://127.0.0.1:5173"

    database_url: str = "sqlite:///./data/dnd_dm.db"
    vector_store_path: Path = Path("./data/vectors")
    backup_directory: Path = Path("./data/backups")
    read_only_safe_mode: bool = False

    ollama_base_url: str = "http://127.0.0.1:11434"
    intent_model: str = ""
    reasoning_model: str = "qwen3:30b-instruct"
    embedding_model: str = "bge-m3:latest"
    ollama_embedding_timeout_seconds: float = Field(default=120, gt=0, le=600)
    ollama_generation_timeout_seconds: float = Field(default=300, gt=0, le=1_800)
    ollama_intent_timeout_seconds: float = Field(default=120, gt=0, le=600)
    ollama_retries: int = Field(default=2, ge=0, le=5)

    rag_collection_name: str = "dnd_rules"
    rag_corpus_json_root: Path = Path("./data/generated-content/dnd5e_chm/json")
    rag_manifest_path: Path = Path("./data/vectors/dnd_rules-manifest.json")
    rag_chunk_max_chars: int = Field(default=1_800, ge=256, le=8_000)
    rag_chunk_overlap_chars: int = Field(default=180, ge=0, le=2_000)
    rag_embedding_batch_size: int = Field(default=32, ge=1, le=128)
    rag_index_batch_records: int = Field(default=24, ge=1, le=256)
    rag_search_top_k: int = Field(default=6, ge=1, le=30)
    rag_search_candidate_k: int = Field(default=18, ge=1, le=100)
    rag_search_min_score: float = Field(default=0.45, ge=-1, le=1)
    rag_max_evidence_chars: int = Field(default=12_000, ge=1_000, le=60_000)

    content_base_url: str = "https://5echm.kagangtuya.top/"
    content_allowed_hosts: str = "5echm.kagangtuya.top"
    content_generated_root: Path = Path("./data/generated-content")
    content_checkout_root: Path = Path("./data/sources")
    content_user_agent: str = "LocalDnDDMAssistant/0.1 (+local research; contact: unset)"
    content_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    content_read_timeout_seconds: float = Field(default=20.0, gt=0, le=300)
    content_max_response_bytes: int = Field(default=2_097_152, ge=1024, le=20_971_520)
    content_delay_seconds: float = Field(default=1.0, ge=1.0, le=60)
    content_retries: int = Field(default=2, ge=0, le=5)
    content_backoff_seconds: float = Field(default=1.0, ge=0.1, le=30)
    content_concurrency: int = Field(default=1, ge=1, le=4)
    content_max_pages: int = Field(default=20, ge=1, le=500)

    @field_validator("host")
    @classmethod
    def require_loopback_host(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("host must be a loopback address")
        return value

    @field_validator("frontend_origin")
    @classmethod
    def require_explicit_origin(cls, value: str) -> str:
        if value == "*" or not value.startswith(("http://", "https://")):
            raise ValueError("frontend_origin must be one explicit HTTP(S) origin")
        return value.rstrip("/")

    @field_validator("rag_collection_name")
    @classmethod
    def require_safe_collection_name(cls, value: str) -> str:
        if not value or not all(character.isalnum() or character in "_-" for character in value):
            raise ValueError("rag_collection_name must contain only letters, digits, '_' or '-'")
        return value

    @property
    def allowed_content_hosts(self) -> frozenset[str]:
        return frozenset(
            host.strip().lower() for host in self.content_allowed_hosts.split(",") if host.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
