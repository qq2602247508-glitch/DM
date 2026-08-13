# Round XLIII Typed Target/Adjudication Seam

Date: 2026-08-13

## Decision

The generic producer-consumer seam is closed, but none of the five audited
spells is promoted. All five remain compile-only because the existing runtime
does not represent every source-required effect dimension.

Promoted IDs: none.

Retained IDs:

- `core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb` — Longstrider
- `core-phb-2024:spell:83b7d94b77f332dd71310bbe` — Disguise Self
- `core-phb-2024:spell:b9db026fa1853bca5b6f1c13` — Prestidigitation
- `core-phb-2024:spell:d82624a42cf6c33ccec927b8` — Speak with Animals
- `core-phb-2024:spell:dd9cb25c63b7e13194c7d01c` — Message

## Source boundary

The exact source clauses and blockers are versioned in
`reports/round-XLIII-typed-target-adjudication-2026-08-13.json`.
The compiled records currently expose only generic target-selection clauses;
the source markdown supplies the additional duration, effect, inspection,
communication, barrier, and lifecycle semantics used for the decision.

## Seam

The Rules Kernel now supports a `typed-adjudication-1` contract with:

- typed self/entity/object target context bound to campaign, scene, and actor;
- source content ID, source record ID, source fingerprint, and clause IDs;
- constrained effect envelope and decision kind;
- preview → DM producer resolution → confirm → idempotent replay;
- payload-drift rejection, expiry, and actor/target/scene CAS;
- immutable producer provenance and an `OperationTransaction` receipt;
- fail-closed wrong or missing source/target/campaign bindings.

## Counts

The accepted canonical baseline is 203 production, 35 compile-only, and 111
unique compiled. The after-state is derived from the same canonical projection:
203 / 35 / 111, delta `0 / 0 / 0`.

## Verification

Status: `platform_seam_complete/no_promotion`.

The focused XLIII/Rules Kernel/migration regression passes 14 tests, and the
full backend suite passes 1,018 tests with one existing Starlette/httpx
deprecation warning. Ruff, compileall, and `git diff --check` pass.

The validator was run twice with the repository backend virtualenv and produced
byte-identical stdout and report bytes. Final report SHA-256 is
`98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f`;
report fingerprint is
`c0f336292e2312935db7f85fd9eee38940910445e7acdd36d8f5c18f5842e3da`.
The protected integrations manifest is
`ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`;
`backend/tests/ollama.py` remains
`8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab`.

The XLIII implementation is local-only and was not pushed. The five audited
spells remain compile-only because their distinct source-required consumers
are absent.
