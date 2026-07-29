# Local AI D&D Dungeon Master Assistant

A local-first, text-only copilot for a human Dungeon Master. It combines the
complete pinned DND5eChm repository corpus, grounded local RAG, transactional
campaign state, a DM-private typed agent, proposal-gated AI changes, a complete
React dashboard, structured D&D character/story/combat fields, runtime model
status, full rule-document reading, and local campaign backup/restore. The
knowledge index remains isolated from campaign state.

## Canonical local package

On this Mac the self-contained working package is:

```text
/Users/inagi/codex/130 游戏/135-跑团助手 dnd
```

Source, frontend, backend, SQLite campaign data, indexed rule content, reports,
logs, launch scripts, and the local Git history live together in that folder.
Double-click `启动.command` in the package (or the desktop launcher) to start
the DM dashboard, backend, and isolated LAN player gateway.

The older `700-AI/local-dnd-dm-assistant` checkout is retained as a recoverable
development mirror; it is not required by the packaged launchers.

## Prerequisites

- macOS on Apple Silicon (other local platforms may also work)
- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 or newer
- npm 10 or newer

No Ollama models are downloaded by setup or indexing. Model identifiers remain
local configuration values. This Mac's example configuration uses
`bge-m3:latest` and `qwen3:30b-instruct`; change them to locally installed model
names when needed.

## Setup

```bash
cp .env.example .env
./scripts/setup.sh
```

The setup command installs locked dependencies and upgrades the local SQLite
database with Alembic. Generated data stays under `data/` and is ignored by Git.
uv uses its normal machine-level cache unless `UV_CACHE_DIR` is explicitly set;
point that variable at an external scratch/cache location when required.

## Run

Start both applications:

```bash
./scripts/dev.sh
```

The dashboard is then available at <http://127.0.0.1:5173>, and the backend at
<http://127.0.0.1:8000>. The backend intentionally binds only to `127.0.0.1`.

The dashboard includes a campaign-scoped D&D compendium for spells, features,
monsters, equipment, items, NPCs, locations, and scenes. Original generated
content is always tagged separately from official rule references. Building and
dungeon generation can use selected characters, party parameters, independent
difficulty/reward overrides, room-scale bounds, NPC/monster population, and
level-appropriate loot. Player maps receive server-filtered exploration state,
so unrevealed rooms and creatures are not transmitted to the player client.

Run the applications separately:

```bash
./scripts/dev-backend.sh
./scripts/dev-frontend.sh
```

### LAN player gateway

The full DM dashboard and API intentionally remain loopback-only. The macOS
one-click desktop launcher starts the isolated player gateway after the local
backend is healthy. It can also be started separately in a terminal:

```bash
./scripts/player-gateway.sh
```

This command waits for the loopback DM backend to finish its migrations, builds
the frontend with a same-origin player API, confirms the database is at the
current migration, and starts a production player gateway on port `8787`. It
prints the Mac's private-network URLs for players. The gateway serves only the
public room API and the built player SPA; campaign administration, AI, backup,
diagnostics, and all other DM routes return `404` on that port. It does not
enable Uvicorn reload.

Use this only on a trusted home/table network. Do not add router port forwarding
or a public tunnel. Players must normally be on the same Wi-Fi or wired LAN;
guest-network client isolation and some VPNs can prevent local devices from
reaching one another. If the macOS firewall is enabled, allow the Python player
gateway to accept incoming connections when prompted. Press `Ctrl-C` in the
gateway terminal to stop accepting player connections. The DM continues to use
<http://127.0.0.1:5173>.

Override any setting through `.env`; see `.env.example` for the complete current
configuration surface.

## Checks

```bash
./scripts/check.sh
```

This runs Ruff, backend type checks, pytest, a fresh-database Alembic smoke test,
frontend lint, strict TypeScript checks, Vitest, and a production build.

Individual examples:

```bash
uv run --project backend pytest backend/tests
uv run --project backend alembic -c backend/alembic.ini upgrade head
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

## Content ingestion

Repository/local snapshots are the primary path. Website crawling is a
robots-aware bounded fallback. No source update occurs during application
startup.

List the built-in sources:

```bash
uv run --project backend dnd-content sources
```

The production profile is `DND5e_chm/main`. The profiles preserve their own
declaration: `5echm_web` branch `pages` has
license `unknown`, `DND5e_chm` branch `main` declares `GPL-3.0`, and
`SRD5.2Chm` branch `main` declares `CC-BY-4.0`. A repository declaration does
not automatically license all underlying official or third-party text.

Explicitly create the shallow production snapshot:

```bash
uv run --project backend dnd-content clone \
  --source dnd5e_chm \
  --checkout ./data/sources/dnd5e_chm
```

Updating is also explicit:

```bash
uv run --project backend dnd-content clone \
  --source dnd5e_chm \
  --checkout ./data/sources/dnd5e_chm \
  --update
```

Dry-run navigation discovery without emitting corpus artifacts:

```bash
uv run --project backend dnd-content discover-local \
  --checkout ./data/sources/dnd5e_chm
```

Import a pinned checkout. The command reads its exact Git commit and stores the
repository URL, branch/ref, relative path, declared/unknown license, and mapped
canonical website URL in every record and run manifest.

```bash
uv run --project backend dnd-content import-local \
  --checkout ./data/sources/dnd5e_chm \
  --source-profile dnd5e_chm \
  --output ./data/generated-content/dnd5e_chm \
  --max-pages 10000
```

This full command discovers every `.htm`/`.html` file in the pinned snapshot,
uses the primary WinCHM project manifest to enrich hierarchy and aliases, emits
unknown classifications instead of silently dropping them, and reports elapsed
time and output bytes. `SRD5.2Chm` remains the smaller validation/smoke profile.

For a generic authorized checkout, omit `--source-profile` and provide
`--repository-url`, `--ref`, and `--license` as applicable. If it is not a Git
checkout, `--revision` must be an exact 40-character snapshot identifier.

The normal offline development path uses compact synthetic fixtures:

```bash
uv run --project backend dnd-content normalize-fixtures \
  --output ./data/generated-content/fixture \
  --max-pages 20
uv run --project backend dnd-content validate \
  --output ./data/generated-content/fixture
```

Only when the snapshot path is unavailable, run the conservative website
fallback. It checks `/robots.txt`, rejects unsafe redirects/URLs and oversized
responses, waits at least one second between requests by default, and applies a
finite page bound:

```bash
uv run --project backend dnd-content crawl-site \
  --output ./data/generated-content/site-smoke \
  --max-pages 2
```

Output is local-only and ignored by Git:

```text
data/generated-content/<source>/
  raw/
  markdown/
  json/
  manifests/
  reports/
```

Do not commit, publish, or redistribute generated corpora or checkouts. See
[`docs/content-source-policy.md`](docs/content-source-policy.md) for robots,
licensing, provenance, and classification limits.

## Local RAG

Build or incrementally update the index from checksum-validated Phase 2 JSON:

```bash
uv run --project backend dnd-rag index
```

The command batches records and embeddings, reports progress to stderr, and
prints final machine-readable statistics. Identical records are skipped;
changed records replace their old chunks; removed records are deleted. A model
change requires an explicit rebuild:

```bash
uv run --project backend dnd-rag index --full-rebuild
```

No command pulls a model or starts Ollama. Check status and perform retrieval:

```bash
uv run --project backend dnd-rag status
uv run --project backend dnd-rag search "火球术造成多少伤害？"
uv run --project backend dnd-rag answer "2024版火球术如何豁免？"
```

The safe default searches only explicitly official 2024/2025 records and
excludes unknown content types, unknown editions, unknown officiality, and
third-party material. Broader research is always explicit and labels are kept:

```bash
uv run --project backend dnd-rag search "核心物品配方" \
  --all-editions --allow-third-party --allow-unknown
```

Knowledge APIs:

- `GET /api/v1/knowledge/index/status`
- `POST /api/v1/knowledge/search`
- `POST /api/v1/knowledge/answer`
- `GET /api/v1/knowledge/documents/{record_id}`

Answers return `answer`, `abstained`, `reason`, and structured `citations`.
Citation metadata comes from retrieved chunks rather than model text. Empty or
low-scoring retrieval, generator abstention, invalid citation numbers, and
generation failures all fail closed. See [`docs/local-rag.md`](docs/local-rag.md)
for boundaries and operations.

Qdrant local mode owns a file lock. Run one backend/indexing process against a
given vector path at a time; stop the backend before using the CLI if both point
at the same path.

## Campaign state API

Run migrations before using state endpoints:

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

Campaigns and every child record have UUID IDs, UTC timestamps, and a `version`.
Create a campaign, add a character, and update it without silently overwriting
another change:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/campaigns \
  -H 'Content-Type: application/json' \
  -d '{"name":"Curse of Strahd"}'

curl -sS -X POST http://127.0.0.1:8000/api/v1/campaigns/CAMPAIGN_ID/characters \
  -H 'Content-Type: application/json' \
  -d '{"name":"Ireena","level":3,"hp":18,"max_hp":18}'

curl -sS -X PATCH \
  http://127.0.0.1:8000/api/v1/campaigns/CAMPAIGN_ID/characters/CHARACTER_ID \
  -H 'Content-Type: application/json' -H 'If-Match: "1"' \
  -d '{"hp":12}'
```

Updates and deletes require `If-Match` or a body/query `version`; stale versions
return `409`. Lists are paginated and aggregates are bounded:

- `GET|POST /api/v1/campaigns`
- `GET|PATCH|DELETE /api/v1/campaigns/{campaign_id}`
- `GET /api/v1/campaigns/{campaign_id}/state?limit=100`
- Nested CRUD for characters, NPCs, locations, quests, clues, events, and combats
- Nested condition, location-connection, and combatant state endpoints
- `GET /api/v1/campaigns/{campaign_id}/export`
- `POST /api/v1/campaigns/import-backup`

Runtime status:

- `GET /api/v1/runtime/models`
- `GET /api/v1/readiness`

Campaign backups are local JSON files. Import always creates a new campaign
copy and never overwrites the source campaign.

NPC `secrets` are part of the explicitly DM-private console schema. No
player-facing endpoint returns that field. Every successful mutation writes
`audit_log` in the same SQLite transaction. See
[`docs/campaign-state.md`](docs/campaign-state.md).

## DM-private local assistant

The assistant uses the explicitly configured intent model for planning and the
reasoning model for the final private hint. An empty `DND_DM_INTENT_MODEL` is
reported as unavailable; setup never pulls a model. The model may call only four
typed tools: `search_rules`, `get_campaign_state`,
`update_campaign_state`, and `generate_dm_hint`.

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/v1/campaigns/CAMPAIGN_ID/assistant/turns \
  -H 'Content-Type: application/json' \
  -d '{"action":"玩家想调查酒馆老板是否撒谎"}'

curl -sS \
  http://127.0.0.1:8000/api/v1/campaigns/CAMPAIGN_ID/change-proposals

curl -sS -X POST \
  http://127.0.0.1:8000/api/v1/campaigns/CAMPAIGN_ID/change-proposals/PROPOSAL_ID/confirm
```

`update_campaign_state` never mutates SQLite. It creates a `pending` proposal
with a typed single operation. Confirm uses a conditional proposal claim and
applies the operation, state audit, and proposal decision in one transaction;
stale versions become `conflict`, rejection has no business-state effect, and a
second confirm is idempotent. Model runs retain only role/name/version,
latency/status/error category, campaign and request IDs—never full prompts,
retrieved正文 or NPC secrets. See
[`docs/agent.md`](docs/agent.md).

## D&D 5e world building and combat flow

The campaign profile is fixed to **D&D 5e**, with 2024 as the primary rules
year. The rules page searches current 2024/2025 material by default; a DM can
explicitly reveal 2014/Legacy compatibility material when needed. AI world
generation always returns a preview first and never writes campaign state
directly:

- `POST /api/v1/campaigns/{campaign_id}/generate/npc` returns a rule-grounded
  quick or guided NPC preview. Saving is a separate DM-confirmed create.
- `POST /api/v1/campaigns/{campaign_id}/generate/location` returns a preview
  tree with a user-selected maximum depth (an upper bound, not a required
  depth), interactive objects, secrets, suggested actors, and atomic items.
- `POST .../generate/location/confirm` is the explicit transaction that creates
  the location tree and its item instances.
- Items carry quantity, price in copper pieces, unit weight, provenance, a
  location or character owner, and a version. `POST .../items/{id}/pickup`
  moves them transactionally into a selected character inventory.
- Inventory capacity follows the campaign's D&D 5e profile: standard
  Strength × 15, optional variant thresholds, or disabled encumbrance.
- Scenes reference existing characters, NPCs, and monster instances without
  duplicating them. `POST .../scenes/{id}/start-combat` snapshots participants,
  rolls visible `d20 + Dexterity modifier` initiative, and creates combatants
  for DM review in the combat assistant.

Backups include world items, monster instances, scenes, scene participants,
hierarchical locations, and their cross-references. Import always creates a
new campaign copy and remaps all IDs.

## Current phase boundaries

The backend is a modular monolith with separate `api`, `application`, `domain`,
`infrastructure`, and `integrations` packages. HTTP code owns transport concerns;
domain ports define local runtime boundaries; infrastructure owns SQLite and
local artifact manifests; integrations implement Ollama and Qdrant behind those
ports. The UI only talks to the API.

SQLite is the source of truth for campaign state. Conversation history is never
authoritative campaign memory. The Phase 3 vector index only contains knowledge
chunks and provenance; structured campaign state never goes into Qdrant. Phase 5
adds the typed agent tools and confirmation workflow described above. Phase 8
adds D&D 5e world atoms, AI previews, inventory/encumbrance, scene composition,
and scene-to-combat flow. Voice/TTS, cloud inference, and automatic model
downloads remain outside the local v1 boundary.
See `docs/architecture.md` for the approved design.
