from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dnd_dm_assistant.application.rag import (
    DeterministicChunker,
    GroundedAnswerService,
    KnowledgeIndexer,
    KnowledgeRetriever,
    RuntimeUnavailableError,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.content import NormalizedEntity
from dnd_dm_assistant.domain.rag import (
    GroundedAnswer,
    IndexManifest,
    IndexStats,
    IndexStatus,
    SearchHit,
    SearchQuery,
)
from dnd_dm_assistant.domain.runtime_status import ConfiguredModelStatus, RuntimeModelStatus
from dnd_dm_assistant.infrastructure.rag_artifacts import JsonCorpusReader, JsonIndexManifestStore
from dnd_dm_assistant.integrations.ollama import (
    OllamaAgentPlannerAdapter,
    OllamaDMHintAdapter,
    OllamaEmbeddingAdapter,
    OllamaGroundedAnswerAdapter,
    OllamaWorldGeneratorAdapter,
)
from dnd_dm_assistant.integrations.qdrant_store import QdrantLocalVectorStore


class RuntimeIntegrations:
    """Owns Phase 3 local adapters and their lifecycle without eager network access."""

    def __init__(self, settings: Settings) -> None:
        self.embeddings = OllamaEmbeddingAdapter(
            base_url=settings.ollama_base_url,
            model=settings.embedding_model,
            batch_size=settings.rag_embedding_batch_size,
            timeout_seconds=settings.ollama_embedding_timeout_seconds,
            retries=settings.ollama_retries,
        )
        self.generator = OllamaGroundedAnswerAdapter(
            base_url=settings.ollama_base_url,
            model=settings.reasoning_model,
            timeout_seconds=settings.ollama_generation_timeout_seconds,
            retries=min(settings.ollama_retries, 1),
        )
        self.agent_planner = (
            OllamaAgentPlannerAdapter(
                base_url=settings.ollama_base_url,
                model=settings.intent_model,
                timeout_seconds=settings.ollama_intent_timeout_seconds,
                retries=min(settings.ollama_retries, 1),
            )
            if settings.intent_model.strip()
            else None
        )
        self.dm_hint_generator = OllamaDMHintAdapter(
            base_url=settings.ollama_base_url,
            model=settings.reasoning_model,
            timeout_seconds=settings.ollama_generation_timeout_seconds,
            retries=min(settings.ollama_retries, 1),
        )
        self.world_generator = OllamaWorldGeneratorAdapter(
            base_url=settings.ollama_base_url,
            model=settings.reasoning_model,
            timeout_seconds=settings.ollama_generation_timeout_seconds,
            retries=min(settings.ollama_retries, 1),
        )
        self.vector_store = QdrantLocalVectorStore(
            path=settings.vector_store_path,
            collection_name=settings.rag_collection_name,
        )
        self.manifest_store = JsonIndexManifestStore(settings.rag_manifest_path)
        chunker = DeterministicChunker(
            max_chars=settings.rag_chunk_max_chars,
            overlap_chars=settings.rag_chunk_overlap_chars,
        )
        self.chunking_fingerprint = chunker.strategy_fingerprint
        self.retriever = KnowledgeRetriever(
            embeddings=self.embeddings,
            vector_store=self.vector_store,
        )
        self.answer_service = GroundedAnswerService(
            retriever=self.retriever,
            generator=self.generator,
            max_evidence_chars=settings.rag_max_evidence_chars,
        )
        self.indexer = KnowledgeIndexer(
            corpus_reader=JsonCorpusReader(),
            manifest_store=self.manifest_store,
            chunker=chunker,
            embeddings=self.embeddings,
            vector_store=self.vector_store,
            batch_records=settings.rag_index_batch_records,
        )
        self.corpus_root = settings.rag_corpus_json_root
        self.corpus_reader = JsonCorpusReader()

    async def index(
        self,
        *,
        corpus_root: Path | None = None,
        full_rebuild: bool = False,
        progress: Callable[[IndexStats], None] | None = None,
    ) -> IndexStats:
        return await self.indexer.build(
            corpus_root or self.corpus_root,
            full_rebuild=full_rebuild,
            progress=progress,
        )

    async def status(self) -> IndexStatus:
        raw_status = await self.vector_store.status()
        manifest = self.manifest_store.load()
        return validated_index_status(
            raw_status,
            manifest,
            embedding_model=self.embeddings.model_name,
            chunking_fingerprint=self.chunking_fingerprint,
        )

    async def search(self, query: SearchQuery) -> tuple[SearchHit, ...]:
        await self._require_ready()
        return await self.retriever.search(query)

    async def answer(self, question: str, query: SearchQuery | None = None) -> GroundedAnswer:
        await self._require_ready()
        return await self.answer_service.answer(question, query)

    async def model_status(self) -> RuntimeModelStatus:
        installed = await self.embeddings.available_models()
        available = bool(installed)
        configured = (
            ("intent", self.agent_planner.model_name if self.agent_planner else None),
            ("reasoning", self.generator.model_name),
            ("embedding", self.embeddings.model_name),
        )
        return RuntimeModelStatus(
            ollama_available=available,
            think_enabled=False,
            installed_models=installed,
            models=tuple(
                ConfiguredModelStatus(
                    role=role,
                    model=model,
                    configured=bool(model),
                    installed=bool(model and model in installed),
                )
                for role, model in configured
            ),
            reason=None if available else "Ollama service is unavailable",
        )

    def get_document(self, record_id: str) -> NormalizedEntity | None:
        return self.corpus_reader.get_record(self.corpus_root, record_id)

    async def _require_ready(self) -> None:
        status = await self.status()
        if not status.available:
            raise RuntimeUnavailableError(status.reason or "knowledge index is not ready")

    async def close(self) -> None:
        await self.embeddings.close()
        await self.generator.close()
        if self.agent_planner is not None:
            await self.agent_planner.close()
        await self.dm_hint_generator.close()
        await self.world_generator.close()
        await self.vector_store.close()


def validated_index_status(
    raw_status: IndexStatus,
    manifest: IndexManifest | None,
    *,
    embedding_model: str,
    chunking_fingerprint: str,
) -> IndexStatus:
    if manifest is None:
        state = "building" if raw_status.points_count else "missing"
        return raw_status.model_copy(
            update={
                "available": False,
                "state": state,
                "reason": "index manifest is missing; build or recover the index",
            }
        )
    expected_points = sum(len(record.chunk_ids) for record in manifest.records.values())
    shared = {
        "indexed_records": len(manifest.records),
        "embedding_model": manifest.embedding_model,
        "chunking_fingerprint": manifest.chunking_fingerprint,
        "updated_at": manifest.updated_at,
    }
    if manifest.embedding_model != embedding_model:
        return raw_status.model_copy(
            update={
                **shared,
                "available": False,
                "state": "inconsistent",
                "reason": "configured embedding model does not match the index manifest",
            }
        )
    if manifest.chunking_fingerprint != chunking_fingerprint:
        return raw_status.model_copy(
            update={
                **shared,
                "available": False,
                "state": "inconsistent",
                "reason": "configured chunking strategy does not match the index manifest",
            }
        )
    if raw_status.vector_size != manifest.vector_size:
        return raw_status.model_copy(
            update={
                **shared,
                "available": False,
                "state": "inconsistent",
                "reason": "vector dimension does not match the index manifest",
            }
        )
    if not raw_status.available or raw_status.points_count != expected_points:
        return raw_status.model_copy(
            update={
                **shared,
                "available": False,
                "state": "inconsistent",
                "reason": (
                    f"vector point count {raw_status.points_count} does not match "
                    f"manifest count {expected_points}"
                ),
            }
        )
    return raw_status.model_copy(
        update={
            **shared,
            "available": True,
            "state": "ready",
            "reason": None,
        }
    )
