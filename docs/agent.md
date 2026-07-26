# Phase 5 — Local typed DM assistant

The assistant is a bounded orchestration layer between two local Ollama roles:

* the configured intent model emits a strict JSON `AgentPlan`;
* the configured reasoning model emits a strict JSON DM-private hint.

An unset intent model is an explicit unavailable state. No model is downloaded
or silently replaced. Both prompts are versioned and keep an immutable system
role; user, campaign and retrieved rule text are untrusted data.

## Tool boundary

Only these tools are accepted:

* `search_rules(query, filters?)` delegates to the existing safe grounded
  knowledge service. The application builds citations from returned chunks.
* `get_campaign_state(campaign_id, scopes?, limit?)` reads a bounded structured
  SQLite snapshot. `clues` and `combats` map to the aggregate's open/active
  collections.
* `update_campaign_state(campaign_id, operation)` validates a single
  character/NPC/quest/event operation and creates a pending proposal. IDs,
  campaign IDs, versions, audit fields and unsupported payload fields cannot be
  supplied by the model.
* `generate_dm_hint(action, campaign_context, rule_evidence)` is validated as a
  typed call, then the reasoning model emits only citation chunk IDs. The
  application resolves those IDs to verified citations and rejects an
  unreferenced hint when rule evidence was available.

Unknown tools, duplicate calls, invalid JSON arguments, cross-campaign access,
and calls beyond six per turn fail closed. Tool failures are structured and
bounded; absolute paths, prompt bodies, source正文 and secrets are not logged.

## Proposal transaction

`state_change_proposals` stores one typed operation, expected version, reason,
model/request provenance, status and timestamps. Creating a proposal and its
`proposal_create` audit row is transactional. Confirm atomically claims a
pending proposal using `id + campaign_id + status + version`, then applies the
single state mutation and the existing state audit in the same SQLite
transaction. A version mismatch marks the proposal `conflict` with no state
change. Any failure rolls the claim and mutation back to `pending`; concurrent
confirm calls therefore produce at most one create. Reject claims the pending
row, records a decision audit, and never touches business state. Confirm/reject
are idempotent after a decision.

The API is DM-private:

* `POST /api/v1/campaigns/{id}/assistant/turns`
* `GET /api/v1/campaigns/{id}/change-proposals?status=pending`
* `POST /api/v1/campaigns/{id}/change-proposals/{proposal_id}/confirm`
* `POST /api/v1/campaigns/{id}/change-proposals/{proposal_id}/reject`

No assistant message is used as campaign truth. Model-run rows contain only
model metadata, prompt version, latency/status/error category, campaign ID and
request ID.
