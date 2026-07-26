# Phase 3 local RAG design and operations

## Boundaries

The RAG implementation keeps provider types outside the domain and application
layers:

```text
validated Phase 2 JSON
  -> JsonCorpusReader
  -> DeterministicChunker
  -> KnowledgeIndexer
       -> EmbeddingProvider -> Ollama /api/embed (bge-m3)
       -> VectorStore       -> Qdrant local persistent mode

question -> KnowledgeRetriever -> GroundedAnswerService
                               -> Ollama /api/chat
                               -> validated citations from SearchHit metadata
```

`Chunk`, `SearchQuery`, `SearchHit`, `Citation`, `GroundedAnswer`,
`EmbeddingProvider`, `VectorStore`, and `AnswerGenerator` are provider-neutral.
Qdrant models and Ollama response shapes stay inside `integrations/`.

The vector index is knowledge-only. It is not campaign memory, a conversation
store, or the source of truth for character/NPC/quest state.

## Validation and deterministic chunking

The reader accepts only JSON that:

- validates as the Phase 2 `NormalizedEntity` schema;
- lives under the matching content-type directory and stable-id filename;
- has non-empty Markdown and plain text;
- has a SHA-256 value matching the exact normalized Markdown.

Invalid, duplicate, or empty records are counted and reported rather than
indexed. The 20 title-only/empty source pages rejected by Phase 2 therefore do
not become metadata-only vectors.

Chunking follows Markdown headings and paragraph/sentence boundaries, works for
mixed Chinese/English content, and has configured size/overlap limits. Every
chunk carries the record id, rule name, aliases, type, edition, officiality,
source title/book, repository/ref/commit/path, canonical URL, anchor, section,
record checksum, and chunk checksum. IDs are UUID-formatted deterministic
hashes, so the same input/config produces the same points.

The incremental manifest fingerprints content and retrieval metadata. Unchanged
records skip embedding, changed records delete their prior chunk IDs and
upsert replacements, and removed records are cleaned up. Model changes require
`--full-rebuild`; chunking algorithm/size/overlap are also fingerprinted and
cannot be silently changed. Vector dimensions are discovered from embeddings
and checked against the existing collection. A manifest schema version keeps
future index-format changes explicit.

## Retrieval safety policy

Default search is the "current official rules" policy:

- `officiality=official`;
- edition `2024` or `2025`;
- all known content types, excluding `unknown`.

Unknown type/edition/officiality only participates with `allow_unknown`.
Third-party material only participates with `allow_third_party`. Explicit
edition, content-type, source-book, score, candidate, and top-k filters are
supported. The application repeats the safety filter after Qdrant returns
results, so an adapter/filter regression cannot promote disallowed evidence.

Broader results retain and expose their edition and officiality labels in both
hits and citations. They are never relabeled as current official rules.

## Grounded answers and abstention

Only a bounded set of numbered retrieval evidence is sent to the configured
local generator. The prompt treats source text as untrusted data and forbids
outside knowledge or conversation history. The generator returns strict JSON
with supported evidence numbers.

The application, not the model, builds citations. It verifies that every
claimed citation number exists and is visibly referenced as `[n]` in the
answer. It abstains when retrieval is empty/below threshold, the model
abstains, generation is unavailable, or citation validation fails.

Search and answer are enabled only when a valid manifest matches the configured
embedding model, chunking fingerprint, vector dimension, and exact Qdrant point
count. A missing manifest during a rebuild or a partial/mismatched collection
is reported as not ready and cannot be queried.

## Local runtime notes

- Defaults bind only to loopback and use `http://127.0.0.1:11434`.
- Ollama HTTP clients ignore proxy environment variables so localhost traffic
  never leaves the machine.
- No code path downloads or pulls a model.
- Requests use finite timeouts, bounded batches, and limited retry counts.
- Full prompts and source text are not logged.
- Qdrant local mode permits one process to own a storage path. Do not run the
  backend and CLI concurrently against the same path.
- Generated vectors and manifests live under ignored `data/`.

## CLI and API

```bash
uv run --project backend dnd-rag index [--corpus PATH] [--full-rebuild]
uv run --project backend dnd-rag status
uv run --project backend dnd-rag search QUESTION [filters]
uv run --project backend dnd-rag answer QUESTION [filters]
```

The API exposes:

- `GET /api/v1/knowledge/index/status`
- `POST /api/v1/knowledge/search`
- `POST /api/v1/knowledge/answer`

Errors use the project's stable error envelope and never expose the local
corpus or vector database absolute path.
