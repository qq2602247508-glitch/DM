from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from qdrant_client import QdrantClient, models

from dnd_dm_assistant.application.rag import IndexCompatibilityError
from dnd_dm_assistant.domain.rag import (
    Chunk,
    IndexStatus,
    MetadataFilters,
    SearchHit,
)


class QdrantLocalVectorStore:
    """Serialized access to one persistent local-mode Qdrant client."""

    def __init__(self, *, path: Path, collection_name: str) -> None:
        self._path = path
        self._collection_name = collection_name
        self._client: QdrantClient | None = None
        self._lock = asyncio.Lock()

    def _get_client(self) -> QdrantClient:
        if self._client is None:
            self._path.mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(self._path))
        return self._client

    async def reset_collection(self) -> None:
        async with self._lock:
            client = self._get_client()
            if await asyncio.to_thread(client.collection_exists, self._collection_name):
                await asyncio.to_thread(client.delete_collection, self._collection_name)

    async def ensure_collection(self, vector_size: int) -> None:
        async with self._lock:
            client = self._get_client()
            exists = await asyncio.to_thread(client.collection_exists, self._collection_name)
            if not exists:
                await asyncio.to_thread(
                    client.create_collection,
                    self._collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
                return
            info = await asyncio.to_thread(client.get_collection, self._collection_name)
            vectors = info.config.params.vectors
            if not isinstance(vectors, models.VectorParams) or vectors.size != vector_size:
                actual = vectors.size if isinstance(vectors, models.VectorParams) else "named"
                raise IndexCompatibilityError(
                    f"Qdrant vector size is {actual}, expected {vector_size}"
                )

    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have equal lengths")
        if not chunks:
            return
        points = [
            models.PointStruct(
                id=chunk.chunk_id,
                vector=[float(value) for value in vector],
                payload=chunk.model_dump(mode="json"),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        async with self._lock:
            await asyncio.to_thread(
                self._get_client().upsert,
                collection_name=self._collection_name,
                points=points,
                wait=True,
            )

    async def delete(self, chunk_ids: Sequence[str]) -> None:
        if not chunk_ids:
            return
        async with self._lock:
            client = self._get_client()
            if not await asyncio.to_thread(client.collection_exists, self._collection_name):
                return
            await asyncio.to_thread(
                client.delete,
                collection_name=self._collection_name,
                points_selector=list(chunk_ids),
                wait=True,
            )

    async def search(
        self,
        vector: Sequence[float],
        *,
        limit: int,
        filters: MetadataFilters,
    ) -> Sequence[SearchHit]:
        query_filter = _to_qdrant_filter(filters)
        async with self._lock:
            client = self._get_client()
            if not await asyncio.to_thread(client.collection_exists, self._collection_name):
                return ()
            response = await asyncio.to_thread(
                client.query_points,
                collection_name=self._collection_name,
                query=[float(value) for value in vector],
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        hits: list[SearchHit] = []
        for point in response.points:
            if not isinstance(point.payload, dict):
                continue
            hits.append(
                SearchHit(
                    chunk=Chunk.model_validate(cast(dict[str, Any], point.payload)),
                    score=float(point.score),
                )
            )
        return tuple(hits)

    async def status(self) -> IndexStatus:
        async with self._lock:
            client = self._get_client()
            exists = await asyncio.to_thread(client.collection_exists, self._collection_name)
            if not exists:
                return IndexStatus(collection_name=self._collection_name, available=False)
            info = await asyncio.to_thread(client.get_collection, self._collection_name)
        vectors = info.config.params.vectors
        vector_size = vectors.size if isinstance(vectors, models.VectorParams) else None
        return IndexStatus(
            collection_name=self._collection_name,
            available=True,
            points_count=info.points_count or 0,
            vector_size=vector_size,
        )

    async def close(self) -> None:
        async with self._lock:
            if self._client is not None:
                await asyncio.to_thread(self._client.close)
                self._client = None


def _to_qdrant_filter(filters: MetadataFilters) -> models.Filter | None:
    conditions: list[models.FieldCondition] = []
    values = (
        ("content_type", [value.value for value in filters.content_types]),
        ("edition", [value.value for value in filters.editions]),
        ("officiality", [value.value for value in filters.officialities]),
        ("source_book", list(filters.source_books)),
    )
    for key, accepted in values:
        if accepted:
            conditions.append(models.FieldCondition(key=key, match=models.MatchAny(any=accepted)))
    return models.Filter(must=cast(Any, conditions)) if conditions else None
