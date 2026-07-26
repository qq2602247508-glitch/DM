from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from dnd_dm_assistant.domain.content import NormalizedEntity
from dnd_dm_assistant.domain.rag import (
    Chunk,
    GeneratedAnswer,
    IndexManifest,
    IndexStatus,
    MetadataFilters,
    SearchHit,
)


class OllamaClient(Protocol):
    async def is_available(self) -> bool: ...


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class VectorStore(Protocol):
    async def reset_collection(self) -> None: ...

    async def ensure_collection(self, vector_size: int) -> None: ...

    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None: ...

    async def delete(self, chunk_ids: Sequence[str]) -> None: ...

    async def search(
        self,
        vector: Sequence[float],
        *,
        limit: int,
        filters: MetadataFilters,
    ) -> Sequence[SearchHit]: ...

    async def status(self) -> IndexStatus: ...

    async def close(self) -> None: ...


class AnswerGenerator(Protocol):
    @property
    def model_name(self) -> str: ...

    async def generate_grounded(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> GeneratedAnswer: ...


class CorpusReader(Protocol):
    def iter_records(
        self, root: Path
    ) -> Iterable[tuple[Path, NormalizedEntity | None, str | None]]: ...


class IndexManifestStore(Protocol):
    def load(self) -> IndexManifest | None: ...

    def save(self, manifest: IndexManifest) -> None: ...

    def invalidate(self) -> None: ...
