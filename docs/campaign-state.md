# Structured campaign state

Phase 4 stores mutable campaign facts in normalized SQLite tables. State is not
derived from chat history, prompts, generated text, or Qdrant.

## Transaction and scope rules

- Every record is read through a campaign scope. A child ID from another
  campaign produces `404`, including conditions, connections, and combatants.
- Every mutation and its `audit_log` row commit or roll back together.
- Updates and deletes require an expected version. A stale version produces
  `409` and leaves both state and audit unchanged.
- Lists use stable `created_at, id` ordering with `limit` and `offset`.
- The state snapshot has a caller-selected limit from 1 to 200 for each
  collection. It includes open clues and active combats only.
- Campaign deletion cascades owned state while preserving a tombstone deletion
  audit record with a null campaign foreign key.

## Schema boundaries

Core entities and relationships use foreign keys: campaigns, characters,
conditions, NPCs, locations, location connections, quests, clues, events,
combats, and combatants. JSON is limited to flexible leaf fields such as
inventory, condition details, event metadata, and combatant conditions.

The API is a DM console. NPC secrets are deliberately exposed only in the
DM-private NPC schema; there is no player-facing state endpoint in this phase.

## Operations

Apply migrations:

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

Run all checks:

```bash
UV_CACHE_DIR=/Users/inagi/codex/900-杂项/uv-cache ./scripts/check.sh
```

The OpenAPI contract is available locally at
`http://127.0.0.1:8000/docs`.

Phase 5 adds DM-private state-change proposals and model-run metadata. Proposal
confirmation is a single conditional-claim transaction; see
[`agent.md`](agent.md).
