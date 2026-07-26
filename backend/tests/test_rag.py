from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_dm_assistant.application.rag import (
    DeterministicChunker,
    GroundedAnswerService,
    IndexCompatibilityError,
    KnowledgeIndexer,
    KnowledgeRetriever,
    RagError,
    RuntimeUnavailableError,
)
from dnd_dm_assistant.domain.content import (
    ContentType,
    Edition,
    NormalizedEntity,
    Officiality,
)
from dnd_dm_assistant.domain.rag import (
    Chunk,
    GeneratedAnswer,
    GroundedAnswer,
    IndexManifest,
    IndexStatus,
    MetadataFilters,
    RecordIndexState,
    SearchHit,
    SearchQuery,
)
from dnd_dm_assistant.infrastructure.rag_artifacts import JsonCorpusReader
from dnd_dm_assistant.integrations.qdrant_store import QdrantLocalVectorStore
from dnd_dm_assistant.integrations.runtime import RuntimeIntegrations


def _record(
    *,
    stable_id: str = "fireball-record",
    markdown: str = "# 火球术 Fireball\n\n## 效果\n\n目标进行敏捷豁免，失败受到8d6火焰伤害。",
    content_type: ContentType = ContentType.SPELLS,
    edition: Edition = Edition.EDITION_2024,
    officiality: Officiality = Officiality.OFFICIAL,
) -> NormalizedEntity:
    checksum = hashlib.sha256(markdown.encode()).hexdigest()
    return NormalizedEntity(
        stable_id=stable_id,
        name="火球术",
        aliases=("Fireball",),
        content_type=content_type,
        source_url="https://5echm.kagangtuya.top/fireball.htm",
        canonical_url="https://5echm.kagangtuya.top/fireball.htm#Fireball",
        repository_url="https://github.com/DND5eChm/DND5e_chm.git",
        source_revision="a" * 40,
        source_ref="main",
        source_relative_path="玩家手册2024/法术详述/3环.htm",
        source_license="GPL-3.0",
        source_book="玩家手册2024",
        edition=edition,
        officiality=officiality,
        heading_path=("玩家手册2024", "法术详述", "3环"),
        fragment="Fireball",
        content_markdown=markdown,
        content_plain_text="火球术 Fireball 效果 目标进行敏捷豁免，失败受到8d6火焰伤害。",
        checksum=checksum,
        fetched_at=datetime(2026, 7, 24, tzinfo=UTC),
        run_id="fixture",
    )


class FakeEmbedder:
    model_name = "fake-bge"

    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple((1.0, float(len(text) % 7) / 10) for text in texts)


class FailOnSecondEmbeddingBatch(FakeEmbedder):
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("simulated embedding failure")
        return await super().embed(texts)


class MemoryManifest:
    def __init__(self) -> None:
        self.value: IndexManifest | None = None

    def load(self) -> IndexManifest | None:
        return self.value

    def save(self, manifest: IndexManifest) -> None:
        self.value = manifest

    def invalidate(self) -> None:
        self.value = None


class StaticReader:
    def __init__(self, records: Sequence[NormalizedEntity]) -> None:
        self.records = records

    def iter_records(
        self, _root: Path
    ) -> Sequence[tuple[Path, NormalizedEntity | None, str | None]]:
        return tuple((Path(f"{record.stable_id}.json"), record, None) for record in self.records)


class MemoryVectorStore:
    def __init__(self, hits: Sequence[SearchHit] = ()) -> None:
        self.points: dict[str, Chunk] = {}
        self.hits = tuple(hits)
        self.vector_size: int | None = None

    async def reset_collection(self) -> None:
        self.points.clear()
        self.vector_size = None

    async def ensure_collection(self, vector_size: int) -> None:
        self.vector_size = vector_size

    async def upsert(self, chunks: Sequence[Chunk], _vectors: Sequence[Sequence[float]]) -> None:
        self.points.update((chunk.chunk_id, chunk) for chunk in chunks)

    async def delete(self, chunk_ids: Sequence[str]) -> None:
        for chunk_id in chunk_ids:
            self.points.pop(chunk_id, None)

    async def search(
        self,
        _vector: Sequence[float],
        *,
        limit: int,
        filters: MetadataFilters,
    ) -> Sequence[SearchHit]:
        del filters
        return self.hits[:limit]

    async def status(self) -> IndexStatus:
        return IndexStatus(
            collection_name="memory",
            available=bool(self.vector_size),
            points_count=len(self.points),
            vector_size=self.vector_size,
        )

    async def close(self) -> None:
        return None


class FakeGenerator:
    model_name = "fake-qwen"

    def __init__(self, response: GeneratedAnswer) -> None:
        self.response = response
        self.calls = 0

    async def generate_grounded(
        self,
        _system_prompt: str,
        _user_prompt: str,
    ) -> GeneratedAnswer:
        self.calls += 1
        return self.response


class StubRetriever:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, _query: SearchQuery) -> tuple[()]:
        self.calls += 1
        return ()


class StubAnswerService:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, _question: str, _query: SearchQuery | None = None) -> GroundedAnswer:
        self.calls += 1
        return GroundedAnswer(answer="unused", abstained=True, reason="no_evidence")


def test_chunk_ids_and_provenance_are_stable() -> None:
    chunker = DeterministicChunker(max_chars=300, overlap_chars=30)
    first = chunker.chunk(_record())
    second = chunker.chunk(_record())

    assert first == second
    assert first
    assert first[0].chunk_id == second[0].chunk_id
    assert first[0].source_revision == "a" * 40
    assert first[0].source_relative_path == "玩家手册2024/法术详述/3环.htm"
    assert "效果" in first[0].section


def test_search_query_rejects_blank_text() -> None:
    with pytest.raises(ValidationError, match="search text must not be blank"):
        SearchQuery(text="  \n ")


def test_json_reader_rejects_invalid_checksum(tmp_path: Path) -> None:
    record = _record()
    path = tmp_path / "spells" / f"{record.stable_id}.json"
    path.parent.mkdir(parents=True)
    corrupted = record.model_copy(update={"checksum": "0" * 64})
    path.write_text(corrupted.model_dump_json(), encoding="utf-8")

    item = next(iter(JsonCorpusReader().iter_records(tmp_path)))
    assert item[1] is None
    assert item[2] == "Markdown checksum mismatch"


def test_incremental_index_is_idempotent_and_replaces_changed_chunks() -> None:
    manifest = MemoryManifest()
    vector_store = MemoryVectorStore()
    first = _record()
    indexer = KnowledgeIndexer(
        corpus_reader=StaticReader([first]),
        manifest_store=manifest,
        chunker=DeterministicChunker(max_chars=300, overlap_chars=20),
        embeddings=FakeEmbedder(),
        vector_store=vector_store,
        batch_records=1,
    )
    first_stats = asyncio.run(indexer.build(Path("unused")))
    initial_ids = set(vector_store.points)
    second_stats = asyncio.run(indexer.build(Path("unused")))

    assert first_stats.indexed_records == 1
    assert second_stats.skipped_unchanged == 1
    assert set(vector_store.points) == initial_ids

    changed = _record(markdown="# 火球术 Fireball\n\n## 效果\n\n造成10d6火焰伤害。")
    indexer = KnowledgeIndexer(
        corpus_reader=StaticReader([changed]),
        manifest_store=manifest,
        chunker=DeterministicChunker(max_chars=300, overlap_chars=20),
        embeddings=FakeEmbedder(),
        vector_store=vector_store,
        batch_records=1,
    )
    changed_stats = asyncio.run(indexer.build(Path("unused")))
    assert changed_stats.indexed_records == 1
    assert changed_stats.chunks_deleted == len(initial_ids)
    assert set(vector_store.points).isdisjoint(initial_ids)


def test_failed_full_rebuild_invalidates_manifest_and_next_run_recovers() -> None:
    manifest = MemoryManifest()
    vector_store = MemoryVectorStore()
    records = [_record(stable_id="one"), _record(stable_id="two")]
    failing = KnowledgeIndexer(
        corpus_reader=StaticReader(records),
        manifest_store=manifest,
        chunker=DeterministicChunker(max_chars=300, overlap_chars=20),
        embeddings=FailOnSecondEmbeddingBatch(),
        vector_store=vector_store,
        batch_records=1,
    )
    with pytest.raises(RuntimeError, match="simulated embedding failure"):
        asyncio.run(failing.build(Path("unused"), full_rebuild=True))
    assert manifest.value is None
    assert vector_store.points

    recovering = KnowledgeIndexer(
        corpus_reader=StaticReader(records),
        manifest_store=manifest,
        chunker=DeterministicChunker(max_chars=300, overlap_chars=20),
        embeddings=FakeEmbedder(),
        vector_store=vector_store,
        batch_records=1,
    )
    stats = asyncio.run(recovering.build(Path("unused")))
    expected_ids = {
        chunk.chunk_id
        for record in records
        for chunk in DeterministicChunker(max_chars=300, overlap_chars=20).chunk(record)
    }
    assert stats.indexed_records == 2
    assert set(vector_store.points) == expected_ids
    assert manifest.value is not None
    assert set(manifest.value.records) == {"one", "two"}


def test_empty_or_missing_corpus_cannot_destroy_existing_index() -> None:
    record = _record()
    chunk = DeterministicChunker(max_chars=300, overlap_chars=20).chunk(record)[0]
    manifest = MemoryManifest()
    manifest.value = IndexManifest(
        embedding_model="fake-bge",
        chunking_fingerprint=DeterministicChunker(
            max_chars=300, overlap_chars=20
        ).strategy_fingerprint,
        vector_size=2,
        updated_at=datetime.now(UTC),
        records={
            record.stable_id: RecordIndexState(
                checksum=record.checksum,
                chunk_ids=(chunk.chunk_id,),
            )
        },
    )
    vector_store = MemoryVectorStore()
    vector_store.vector_size = 2
    vector_store.points[chunk.chunk_id] = chunk
    indexer = KnowledgeIndexer(
        corpus_reader=StaticReader([]),
        manifest_store=manifest,
        chunker=DeterministicChunker(max_chars=300, overlap_chars=20),
        embeddings=FakeEmbedder(),
        vector_store=vector_store,
        batch_records=1,
    )
    with pytest.raises(RagError, match="no checksum-validated JSON"):
        asyncio.run(indexer.build(Path("missing"), full_rebuild=True))
    assert manifest.value is not None
    assert set(vector_store.points) == {chunk.chunk_id}


def test_chunking_strategy_change_requires_full_rebuild() -> None:
    manifest = MemoryManifest()
    vector_store = MemoryVectorStore()
    record = _record()
    initial = KnowledgeIndexer(
        corpus_reader=StaticReader([record]),
        manifest_store=manifest,
        chunker=DeterministicChunker(max_chars=300, overlap_chars=20),
        embeddings=FakeEmbedder(),
        vector_store=vector_store,
        batch_records=1,
    )
    asyncio.run(initial.build(Path("unused")))

    changed = KnowledgeIndexer(
        corpus_reader=StaticReader([record]),
        manifest_store=manifest,
        chunker=DeterministicChunker(max_chars=400, overlap_chars=20),
        embeddings=FakeEmbedder(),
        vector_store=vector_store,
        batch_records=1,
    )
    with pytest.raises(IndexCompatibilityError, match="chunking strategy changed"):
        asyncio.run(changed.build(Path("unused")))


def test_runtime_blocks_partial_index_and_allows_only_consistent_manifest() -> None:
    chunker = DeterministicChunker(max_chars=300, overlap_chars=20)
    chunk = chunker.chunk(_record())[0]
    store = MemoryVectorStore()
    store.vector_size = 2
    store.points[chunk.chunk_id] = chunk
    manifest_store = MemoryManifest()
    retriever = StubRetriever()
    answer_service = StubAnswerService()
    runtime = object.__new__(RuntimeIntegrations)
    runtime.vector_store = store
    runtime.manifest_store = manifest_store
    runtime.embeddings = FakeEmbedder()
    runtime.chunking_fingerprint = chunker.strategy_fingerprint
    runtime.retriever = retriever
    runtime.answer_service = answer_service

    partial_status = asyncio.run(runtime.status())
    assert not partial_status.available
    assert partial_status.state == "building"
    with pytest.raises(RuntimeUnavailableError, match="manifest is missing"):
        asyncio.run(runtime.search(SearchQuery(text="火球术")))
    with pytest.raises(RuntimeUnavailableError, match="manifest is missing"):
        asyncio.run(runtime.answer("火球术伤害？"))
    assert retriever.calls == 0
    assert answer_service.calls == 0

    manifest_store.value = IndexManifest(
        embedding_model="fake-bge",
        chunking_fingerprint=chunker.strategy_fingerprint,
        vector_size=2,
        updated_at=datetime.now(UTC),
        records={
            chunk.record_id: RecordIndexState(
                checksum=chunk.record_checksum,
                chunk_ids=(chunk.chunk_id,),
            )
        },
    )
    ready = asyncio.run(runtime.status())
    assert ready.available
    assert ready.state == "ready"
    asyncio.run(runtime.search(SearchQuery(text="火球术")))
    asyncio.run(runtime.answer("火球术伤害？"))
    assert retriever.calls == 1
    assert answer_service.calls == 1

    manifest_store.value = manifest_store.value.model_copy(
        update={
            "records": {
                chunk.record_id: RecordIndexState(
                    checksum=chunk.record_checksum,
                    chunk_ids=(chunk.chunk_id, "missing-point"),
                )
            }
        }
    )
    mismatch = asyncio.run(runtime.status())
    assert not mismatch.available
    assert mismatch.state == "inconsistent"
    assert "point count" in (mismatch.reason or "")


def test_retriever_excludes_unknown_and_third_party_by_default_and_filters_edition() -> None:
    chunker = DeterministicChunker(max_chars=300, overlap_chars=20)
    official = chunker.chunk(_record())[0]
    third_party = chunker.chunk(
        _record(
            stable_id="third",
            edition=Edition.EDITION_2024,
            officiality=Officiality.THIRD_PARTY,
        )
    )[0]
    unknown = chunker.chunk(
        _record(
            stable_id="unknown",
            content_type=ContentType.UNKNOWN,
            edition=Edition.UNKNOWN,
            officiality=Officiality.UNKNOWN,
        )
    )[0]
    legacy = chunker.chunk(_record(stable_id="legacy", edition=Edition.LEGACY))[0]
    store = MemoryVectorStore(
        [
            SearchHit(chunk=unknown, score=0.99),
            SearchHit(chunk=third_party, score=0.98),
            SearchHit(chunk=legacy, score=0.97),
            SearchHit(chunk=official, score=0.96),
        ]
    )
    retriever = KnowledgeRetriever(embeddings=FakeEmbedder(), vector_store=store)

    default = asyncio.run(retriever.search(SearchQuery(text="火球术")))
    assert [hit.chunk.record_id for hit in default] == ["fireball-record"]

    expanded = asyncio.run(
        retriever.search(
            SearchQuery(
                text="火球术",
                current_official=False,
                allow_unknown=True,
                allow_third_party=True,
            )
        )
    )
    assert {hit.chunk.record_id for hit in expanded} == {
        "fireball-record",
        "third",
        "unknown",
        "legacy",
    }

    legacy_only = asyncio.run(
        retriever.search(
            SearchQuery(
                text="火球术",
                editions=(Edition.LEGACY,),
                current_official=False,
            )
        )
    )
    assert [hit.chunk.record_id for hit in legacy_only] == ["legacy"]


def test_grounded_answer_has_complete_citation_and_low_score_abstains() -> None:
    chunk = DeterministicChunker(max_chars=300, overlap_chars=20).chunk(_record())[0]
    hit = SearchHit(chunk=chunk, score=0.91)
    generator = FakeGenerator(
        GeneratedAnswer(
            answer="火球术要求敏捷豁免，失败受到 8d6 火焰伤害。[1]",
            supported_citation_numbers=(1,),
        )
    )
    service = GroundedAnswerService(
        retriever=KnowledgeRetriever(
            embeddings=FakeEmbedder(), vector_store=MemoryVectorStore([hit])
        ),
        generator=generator,
    )
    answer = asyncio.run(service.answer("火球术伤害？"))
    assert not answer.abstained
    assert answer.citations[0].canonical_url.endswith("#Fireball")
    assert answer.citations[0].edition is Edition.EDITION_2024
    assert answer.citations[0].officiality is Officiality.OFFICIAL
    assert answer.citations[0].source_revision == "a" * 40

    low = GroundedAnswerService(
        retriever=KnowledgeRetriever(
            embeddings=FakeEmbedder(),
            vector_store=MemoryVectorStore([SearchHit(chunk=chunk, score=0.1)]),
        ),
        generator=generator,
    )
    abstained = asyncio.run(low.answer("火球术伤害？"))
    assert abstained.abstained
    assert abstained.reason == "no_evidence"
    assert generator.calls == 1


def test_qdrant_local_store_applies_payload_filters(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = QdrantLocalVectorStore(path=tmp_path / "qdrant", collection_name="rules")
        chunker = DeterministicChunker(max_chars=300, overlap_chars=20)
        official = chunker.chunk(_record())[0]
        third_party = chunker.chunk(
            _record(stable_id="third", officiality=Officiality.THIRD_PARTY)
        )[0]
        await store.ensure_collection(2)
        await store.upsert([official, third_party], [(1.0, 0.0), (1.0, 0.0)])
        hits = await store.search(
            (1.0, 0.0),
            limit=10,
            filters=MetadataFilters(
                officialities=(Officiality.OFFICIAL,),
                editions=(Edition.EDITION_2024,),
            ),
        )
        assert [hit.chunk.record_id for hit in hits] == ["fireball-record"]
        assert (await store.status()).points_count == 2
        await store.close()

    asyncio.run(scenario())
