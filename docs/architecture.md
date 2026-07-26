# Local AI D&D Dungeon Master Assistant — Phase 0 Architecture

Status: approved baseline for Phase 1  
Date: 2026-07-25  
Scope: local, text-only DM copilot; the human DM remains the final authority.

## 1. Architecture

Version 1 is a modular monolith. One React application talks to one FastAPI
process. The backend owns persistence, retrieval, model orchestration, and audit
logging. This keeps local installation simple while preserving module boundaries
that can later become services.

```text
React DM Dashboard
  ├─ campaign header and event log
  ├─ assistant workspace
  └─ character/NPC/quest panels
             │ HTTP JSON + SSE
FastAPI application
  ├─ API layer (validation, errors, request IDs)
  ├─ application services
  │   ├─ CampaignService
  │   ├─ KnowledgeService
  │   ├─ AssistantService
  │   └─ IngestionService
  ├─ agent orchestrator
  │   ├─ intent/extraction model: Qwen3 8B
  │   ├─ reasoning/generation model: Qwen3 32B
  │   └─ typed tools + write confirmation policy
  ├─ repositories
  │   ├─ SQLAlchemy → SQLite
  │   └─ VectorStore interface → Qdrant local mode
  └─ integrations
      ├─ Ollama
      ├─ bge-m3 embedding
      └─ allow-listed D&D content crawler
```

### Architectural rules

- SQLite is the source of truth for campaign state. Prompts and chat history are
  never authoritative memory.
- The agent can read state directly. Mutating tool calls produce a typed change
  proposal; the DM explicitly confirms it before persistence.
- Every mutation and model/tool run is auditable.
- Rules answers must cite stored source title, canonical URL, content type, and
  section heading. If retrieval evidence is insufficient, the assistant says so.
- Domain, application, infrastructure, and API code remain separate. HTTP
  handlers do not contain domain rules or model prompts.
- The UI does not call Ollama, SQLite, or Qdrant directly.

## 2. Primary data flows

### Rules query

1. Dashboard sends a question and optional campaign context.
2. Backend embeds the normalized question with bge-m3.
3. Retriever searches Qdrant with content-type and edition filters.
4. It reranks/deduplicates candidates and loads canonical chunk metadata.
5. Qwen3 32B answers only from retrieved evidence.
6. Backend validates citations and returns the answer plus structured sources.

### DM action assistance

1. DM records a player action.
2. Qwen3 8B classifies intent and extracts mentioned entities without mutating
   state.
3. Orchestrator calls `search_rules` and `get_campaign_state` as needed.
4. Qwen3 32B creates a private DM hint with assumptions and evidence.
5. Any suggested state change is returned separately as a confirmation proposal.
6. Confirmed changes are committed transactionally and appended to the event log.

### Content ingestion

1. Crawler reads only the configured allow-listed source and obeys rate limits.
2. Parser extracts canonical page content and section hierarchy.
3. Normalizer emits deterministic Markdown and JSON plus metadata.
4. Validator rejects incomplete/duplicate records into a review report.
5. Chunker preserves headings and rule identity.
6. Indexer embeds changed chunks only and upserts them into Qdrant.

## 3. Technology choices

| Concern | Choice | Reason |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2 | Typed APIs, async model calls, mature local ecosystem |
| ORM/migrations | SQLAlchemy 2 + Alembic | Explicit unit-of-work boundaries and evolvable schema |
| Campaign DB | SQLite, WAL enabled | Zero-service local persistence; reliable for a single DM |
| Vector DB | Qdrant client local persistent mode behind an interface | Rich metadata filtering now; same API can later target a Qdrant server |
| Embeddings | bge-m3 through a pluggable embedding adapter | Multilingual retrieval and local execution |
| LLM runtime | Ollama adapter | Local Apple Silicon inference and replaceable model names |
| Frontend | React, TypeScript, Vite, Tailwind CSS | Fast local UI development and strong typing |
| Server state | TanStack Query | Cache invalidation and mutation lifecycle without a large global store |
| Streaming | Server-Sent Events | Simple one-way token/progress streaming for a local console |
| Tests | pytest, HTTPX, Vitest, Testing Library, Playwright smoke tests | Unit, contract, component, and critical-path coverage |
| Packaging | uv for Python; pnpm for frontend | Reproducible local installs and fast dependency handling |

Model identifiers, paths, source URL, database locations, and runtime limits are
configuration values, never hard-coded in application modules.

## 4. Database schema

All primary keys are UUID strings. All mutable records include `created_at`,
`updated_at`, and an integer `version` for optimistic concurrency. JSON fields
are used only for flexible leaf data, not as a substitute for core relations.

### Campaign state

| Table | Important columns |
|---|---|
| `campaigns` | `id`, `name`, `description`, `world_setting`, `current_time`, `current_location_id`, `status` |
| `characters` | `id`, `campaign_id`, `name`, `class_name`, `level`, `hp`, `max_hp`, `inventory_json`, `notes` |
| `character_conditions` | `id`, `character_id`, `condition_name`, `source`, `duration`, `notes` |
| `npcs` | `id`, `campaign_id`, `name`, `description`, `personality`, `relationship`, `secrets`, `known_information`, `location_id`, `status` |
| `locations` | `id`, `campaign_id`, `name`, `description`, `notes` |
| `location_connections` | `id`, `from_location_id`, `to_location_id`, `label`, `travel_time`, `bidirectional` |
| `quests` | `id`, `campaign_id`, `name`, `description`, `status`, `notes` |
| `clues` | `id`, `campaign_id`, `quest_id`, `name`, `description`, `discovered`, `discovered_at`, `source_event_id` |
| `events` | `id`, `campaign_id`, `event_type`, `title`, `description`, `occurred_at`, `location_id`, `visibility`, `metadata_json` |
| `combats` | `id`, `campaign_id`, `name`, `status`, `round_number`, `current_turn_index`, `started_at`, `ended_at` |
| `combatants` | `id`, `combat_id`, `entity_type`, `entity_id`, `display_name`, `initiative`, `hp`, `max_hp`, `conditions_json`, `is_active` |

### Assistant, audit, and safety

| Table | Important columns |
|---|---|
| `assistant_sessions` | `id`, `campaign_id`, `title`, `created_at` |
| `assistant_messages` | `id`, `session_id`, `role`, `content`, `visibility`, `created_at` |
| `state_change_proposals` | `id`, `campaign_id`, `tool_name`, `arguments_json`, `reason`, `status`, `requested_at`, `confirmed_at` |
| `audit_log` | `id`, `campaign_id`, `actor`, `action`, `entity_type`, `entity_id`, `before_json`, `after_json`, `request_id`, `created_at` |
| `model_runs` | `id`, `campaign_id`, `model_role`, `model_name`, `prompt_version`, `latency_ms`, `status`, `error`, `created_at` |

Message history can support the current user experience, but all factual campaign
context supplied to the model is freshly read from campaign tables.

### Rules corpus

| Table | Important columns |
|---|---|
| `rule_documents` | `id`, `source_url`, `canonical_url`, `content_type`, `name`, `edition`, `language`, `checksum`, `raw_path`, `markdown_path`, `fetched_at` |
| `rule_sections` | `id`, `document_id`, `parent_id`, `heading`, `heading_path`, `ordinal`, `content`, `checksum` |
| `rule_chunks` | `id`, `section_id`, `chunk_index`, `content`, `token_count`, `vector_key`, `metadata_json` |
| `ingestion_runs` | `id`, `source`, `started_at`, `finished_at`, `status`, `stats_json`, `error_report_path` |

Qdrant payloads contain `chunk_id`, `document_id`, `content_type`, `name`,
`edition`, `language`, `source_url`, and `heading_path`. SQL remains the canonical
metadata store.

### Constraints and indexes

- Foreign keys are enabled and destructive cascades are limited to campaign-owned
  child records.
- `hp`, `max_hp`, `level`, initiative, and round values have validity checks.
- Unique constraints cover `(campaign_id, name)` where ambiguity would be harmful
  and `(canonical_url, checksum)` for source versions.
- Indexes cover campaign foreign keys, quest status, NPC/location lookup, event
  chronology, proposal status, and rule metadata filters.

## 5. API design

All endpoints are under `/api/v1`. Errors use a stable envelope:
`{code, message, details, request_id}`. Entity responses include `version`.

### System and configuration

- `GET /health` — process and database health
- `GET /readiness` — SQLite, vector store, embedding model, and Ollama readiness
- `GET /runtime/models` — configured roles and availability; no secrets

### Campaigns and state

- `GET|POST /campaigns`
- `GET|PATCH|DELETE /campaigns/{campaign_id}`
- `GET|POST /campaigns/{campaign_id}/characters`
- `GET|PATCH|DELETE /characters/{id}`
- Equivalent CRUD resources for `npcs`, `locations`, `quests`, and `clues`
- `GET|POST /campaigns/{campaign_id}/events`
- `GET /campaigns/{campaign_id}/state` — bounded aggregate snapshot
- `GET|POST /campaigns/{campaign_id}/combats`
- `PATCH /combats/{id}` and typed combat actions under `/combats/{id}/actions`

Mutating requests accept `If-Match` or an explicit `version` to prevent silent
overwrites.

### Knowledge and ingestion

- `POST /knowledge/search` — raw ranked chunks with filters and citations
- `POST /knowledge/answer` — grounded answer with structured sources
- `POST /ingestion/runs` — start an allow-listed crawl/index run
- `GET /ingestion/runs/{id}` — status and validation report
- `GET /rule-documents/{id}` — canonical document metadata and sections

### Assistant and tools

- `POST /campaigns/{campaign_id}/assistant/messages`
- `GET /campaigns/{campaign_id}/assistant/stream?message_id=...` — SSE
- `GET /campaigns/{campaign_id}/assistant/sessions`
- `GET /assistant/messages/{id}`
- `GET /campaigns/{campaign_id}/change-proposals`
- `POST /change-proposals/{id}/confirm`
- `POST /change-proposals/{id}/reject`

Internal typed tools, not publicly trusted free-form endpoints:

- `search_rules(query, content_types?, edition?, top_k?)`
- `get_campaign_state(campaign_id, scopes?, entity_ids?)`
- `update_campaign_state(campaign_id, operations, expected_versions)`
- `generate_dm_hint(action, campaign_context, rule_evidence)`

Tool arguments and results use Pydantic schemas. Only
`update_campaign_state` can write, and only after proposal confirmation.

## 6. Reliability, performance, and security

- Bind to `127.0.0.1` by default and use an explicit local frontend origin.
- Store no secrets in source control; use `.env` derived from `.env.example`.
- Sanitize crawled HTML, reject non-HTTP(S) links, enforce host allow-lists,
  timeouts, size limits, and polite concurrency.
- Treat retrieved text as untrusted data, not agent instructions.
- Use SQLite WAL, short transactions, pagination, and bounded aggregate reads.
- Cache embeddings by checksum; batch embeddings and Qdrant upserts.
- Limit context by token budget and retrieve compact, adjacent sections only when
  needed.
- Keep prompt templates versioned and test citation behavior with a fixed
  evaluation set.
- Back up SQLite and the local Qdrant directory together from a consistent
  application checkpoint.

## 7. Decision boundaries for future phases

- Phase 1 must establish interfaces and runnable skeletons, not prematurely
  implement crawler, RAG, or agent behavior.
- Phase 2 must first verify the target site's structure, permissions, and content
  licensing/terms. The application stores provenance for every record.
- Phase 3 may swap Qdrant local mode for a local server without changing
  `VectorStore`.
- Voice, TTS, multi-user networking, and player-facing live communication remain
  outside version 1.

