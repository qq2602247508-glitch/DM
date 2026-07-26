from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dnd_dm_assistant.domain.content import ContentType, Edition, Officiality


class Chunk(BaseModel):
    """A provider-neutral, deterministic retrieval unit."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    record_id: str
    chunk_index: int = Field(ge=0)
    text: str
    name: str
    aliases: tuple[str, ...] = ()
    content_type: ContentType
    edition: Edition
    officiality: Officiality
    source_title: str
    source_book: str | None = None
    canonical_url: str
    source_url: str
    repository_url: str | None = None
    source_relative_path: str | None = None
    source_ref: str | None = None
    source_revision: str | None = None
    source_license: str = "unknown"
    heading_path: tuple[str, ...] = ()
    section: str
    fragment: str | None = None
    record_checksum: str
    chunk_checksum: str


class MetadataFilters(BaseModel):
    model_config = ConfigDict(frozen=True)

    content_types: tuple[ContentType, ...] = ()
    editions: tuple[Edition, ...] = ()
    officialities: tuple[Officiality, ...] = ()
    source_books: tuple[str, ...] = ()


class SearchQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=6, ge=1, le=30)
    candidate_k: int = Field(default=18, ge=1, le=100)
    min_score: float = Field(default=0.45, ge=-1, le=1)
    content_types: tuple[ContentType, ...] = ()
    editions: tuple[Edition, ...] = ()
    source_books: tuple[str, ...] = ()
    current_official: bool = True
    allow_unknown: bool = False
    allow_third_party: bool = False

    @field_validator("text")
    @classmethod
    def normalize_nonempty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("search text must not be blank")
        return normalized

    @model_validator(mode="after")
    def candidates_cover_results(self) -> SearchQuery:
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        return self


class SearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk: Chunk
    score: float


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    citation_id: int = Field(ge=1)
    chunk_id: str
    record_id: str
    rule_name: str
    source_title: str
    canonical_url: str
    section: str
    heading_path: tuple[str, ...] = ()
    content_type: ContentType
    edition: Edition
    officiality: Officiality
    source_book: str | None = None
    repository_url: str | None = None
    source_relative_path: str | None = None
    source_ref: str | None = None
    source_revision: str | None = None
    score: float

    @classmethod
    def from_hit(cls, hit: SearchHit, citation_id: int) -> Citation:
        chunk = hit.chunk
        return cls(
            citation_id=citation_id,
            chunk_id=chunk.chunk_id,
            record_id=chunk.record_id,
            rule_name=chunk.name,
            source_title=chunk.source_title,
            canonical_url=chunk.canonical_url,
            section=chunk.section,
            heading_path=chunk.heading_path,
            content_type=chunk.content_type,
            edition=chunk.edition,
            officiality=chunk.officiality,
            source_book=chunk.source_book,
            repository_url=chunk.repository_url,
            source_relative_path=chunk.source_relative_path,
            source_ref=chunk.source_ref,
            source_revision=chunk.source_revision,
            score=hit.score,
        )


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    abstained: bool
    reason: str | None = None
    citations: tuple[Citation, ...] = ()


class GeneratedAnswer(BaseModel):
    """Strict shape expected from a text generator; citations stay application-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str
    abstained: bool = False
    reason: str | None = None
    supported_citation_numbers: tuple[int, ...] = ()


class IndexStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    discovered: int = 0
    indexed_records: int = 0
    skipped_unchanged: int = 0
    rejected: int = 0
    removed_records: int = 0
    chunks_upserted: int = 0
    chunks_deleted: int = 0
    vector_size: int | None = None
    errors: tuple[str, ...] = ()


class IndexStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    collection_name: str
    available: bool
    state: Literal["ready", "missing", "building", "inconsistent"] = "missing"
    reason: str | None = None
    points_count: int = 0
    vector_size: int | None = None
    indexed_records: int = 0
    embedding_model: str | None = None
    chunking_fingerprint: str | None = None
    updated_at: datetime | None = None


class RecordIndexState(BaseModel):
    model_config = ConfigDict(frozen=True)

    checksum: str
    chunk_ids: tuple[str, ...]


class IndexManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    embedding_model: str
    chunking_fingerprint: str = "legacy-v0"
    vector_size: int
    updated_at: datetime
    records: dict[str, RecordIndexState]


class CorpusItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    record: object | None = None
    error: str | None = None


class AnswerRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str = Field(min_length=1, max_length=2_000)
    search: SearchQuery | None = None


AbstentionReason = Literal[
    "no_evidence",
    "low_similarity",
    "generator_abstained",
    "invalid_generator_citations",
    "generation_failed",
]
