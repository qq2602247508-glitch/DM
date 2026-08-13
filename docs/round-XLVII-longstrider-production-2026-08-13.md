# Round XLVII：Longstrider source-complete production closure

日期：2026-08-13。

## Decision

`core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb`（Longstrider）提升为
`registered_production_full`。其余四条 audited utility spells remain
compile-only。

## Source boundary

Authoritative source record：`玩家手册2024/法术详述/1环.htm`，
source fingerprint `834e92d0104e26b08042388d344c97379f0274a935e10fd4953075ec9bd0a8b0`。
The authored producer represents every source-required clause:

- touch / one creature target, with explicit willing-target gate;
- `speed_ft +10`, additive timed modifier;
- one-hour duration and expiry;
- one extra target per slot level above first;
- same-source replacement, never stacking.

## Runtime boundary

The known-spell `content_ir_runtime` record is compiled into
`spell-runtime-1`. `ContentIRRuntimeService` resolves the typed
`spell.timed_modifier.v1` consumer without spell-name dispatch. The real request
path is preview → spell economy confirm → authoritative actor/target CAS →
versioned combatant snapshot → `OperationTransaction` receipt. Replays return the
existing receipt; payload drift, stale versions, unwilling targets, invalid source
provenance, wrong slot, wrong target, invalid duration or modifier fail closed.

## Counts and gates

- Project: `203 production / 35 compile-only / 111 unique compiled` →
  `204 / 34 / 111`.
- Focused: `20 passed`.
- Validator: two runs byte-identical, stdout SHA-256
  `788b0f048d052e6744028589a92ae93de22b0ee3e6bf095dd8f771d375ac3d16`.
- Report SHA-256:
  `59156a8c9740654c317fe6cce9cee091b23b63263e31c042c5216421d5acf6bf`.
- Existing Starlette/httpx deprecation warning remains the only expected warning
  in the focused fixture.
- No push. Protected paths remain unchanged and untracked.
