# Round XLVIII：Longstrider authoritative evidence registration

日期：2026-08-14。

## Decision

Promote Longstrider through the existing generic production evidence mechanism.
The authoritative union now contains
`core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb`.

Canonical counts derive naturally as `204 production / 34 compile-only /
111 unique compiled`.

## Evidence

The artifact is
`data/content-ir/compiled/production-runtime-results-XLVIII.json`. It is loaded
by `load_production_runtime_evidence()` and consumed by
`existing_project_production_ids()` and `build_migration()`; no loader or
validator special-cases the Longstrider ID.

The artifact was generated from a real isolated migrated SQLite runtime:

- source-bound authored/compiled provenance and typed clause IDs;
- generic consumer `spell.timed_modifier.v1`;
- preview → confirm → replay;
- willing target and range contract;
- actor/target CAS;
- persisted `speed_ft +10` timed modifier receipts with expiry and replacement;
- `OperationTransaction` receipt;
- formal database/registry unchanged and protected paths unchanged.

Validator: `scripts/validate-round-XLVIII-longstrider-evidence-registration.py`.
Focused registration tests:
`backend/tests/test_round_XLVIII_longstrider_evidence_registration.py`.

Round XLVII remains the historical withdrawn attempt and was not rewritten.
The Round XLIII report SHA remains
`98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f`.

No push. No campaign/character persistent data, source corpus, 3D/UI, or
protected paths were modified.
