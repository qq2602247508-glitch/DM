# Round XLIX：Message source-complete production closure

日期：2026-08-14。状态：`registered_production_full`；local commit only，未 push。

## Decision

Promote Message
`core-phb-2024:spell:dd9cb25c63b7e13194c7d01c` through the existing generic
`spell.communication.route.v1` consumer. No spell-name or ID dispatch was
added.

The authored IR now binds the source clauses for action casting, 120-foot
range, one creature, visibility/familiarity, solid-material barriers, one-foot
thickness, target-only audible delivery, private reply, instantaneous duration,
and magical-silence blocking. The source’s S/M copper-wire component remains
provenance data; no unsupported material inventory behavior was invented.

## Runtime evidence

The real API path is:

`known spell persistence → preview → authoritative range/route validation →
spell confirm → target snapshot route persistence → OperationTransaction →
replay`.

The receipt proves source provenance, target-only delivery, private reply
ownership, message fingerprint, actor/target CAS, and deterministic replay.
Preview and confirm fail closed for missing visibility/familiarity, excessive
barrier thickness, unfamiliar targets behind barriers, magical silence,
authoritative out-of-range targets, stale character/actor/target versions, and
payload drift.

Evidence was written to
`data/content-ir/compiled/production-runtime-results-XLIX.json` and loaded by
the generic `load_production_runtime_evidence()` loader. The validator and
registration tests contain no Message-specific loader branch.

## Derived projection and gates

Canonical projection derived from the generic loaders:

`205 production / 33 compile-only / 111 unique compiled`.

Validator:
`scripts/validate-round-XLIX-message-production.py`.

Focused tests:
`backend/tests/test_round_XLIX_message_runtime.py`,
`backend/tests/test_typed_spell_communication_routes.py`,
`backend/tests/test_content_ir_production_closure.py`.

The validator stdout, report, and production artifact were byte-identical
across two runs. The Round XLIII report SHA remains
`98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f`.
Protected `backend/tests/ollama.py` remains
`8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`; protected
integrations remain untouched and untracked.

No campaign/character persistent data, source corpus, 3D/UI, deletion, reset,
checkout, clean, or push was performed.
