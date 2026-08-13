# Tasha Feature Production Consumer Round XLII

## Decision

Promoted `content.tashas-cauldron.round2.feature.genie-bottled-respite` to
`registered_production_full` / game usable.

Sanctuary Vessel remains excluded as the separate level-10 feature atom.

## Gate matrix

| Gate | Result | Evidence |
|---|---|---|
| Source completeness and provenance | pass | authored IR; source record `98620543cf94e974361c6567`; fingerprint `e81b718b2ee8728e75cf77c2f00c33312a283a9e12d3654d9bb377a64ec745c7` |
| Compiler | pass | `compile_status=full`; capability `vessel.space` |
| Materializer | pass | one `vessel_spaces` block and one derived `vessel_external_sound` block |
| Registry | pass | `vessel.external_sound.v1`, `vessel.space.v1`; no unknown sections |
| Real API evidence | pass | create, enter, normal exit, long-rest reset, destroy relocation, owner-death relocation, external hearing replay, tamper fail-closed |
| Persistence/CAS/transactions | pass | VesselSpace, Character, Combatant, WorldItem, producer receipts, OperationTransaction |
| Negative gates | pass | missing/mismatched producer, CAS conflict, non-audible/wrong binding, direct DB tampering |
| Name branching | pass | `0` |
| Protected paths | pass | `backend/tests/integrations/` unchanged; `backend/tests/ollama.py` unchanged |

## Derived count delta

- Tasha: production `+1` (`102 → 103`), compile-only `-1` (`1 → 0`); authored/compile/preview unchanged.
- Project: production `+1` (`202 → 203`), compile-only `0` (`35 → 35`), unique compiled unchanged at `111`.
- Current Tasha projection: `106 authored / 105 compile / 105 preview / 103 production_full / 2 DM-assisted / 105 game_usable / 0 compile-only`.

## Baseline provenance

- Authoritative prior accepted after-state: `reports/tashas-production-reconciliation-round-XXV-2026-08-12.json`.
- Baseline SHA-256: `1ca123067fedbcf6e8592afc8272f1e6f935280d475658c45613e4545094f8c7`.
- The Round XLII after-state is derived from the canonical `build_migration` projection and the Round XLII production evidence; no count transition is manufactured.

## Determinism

- Validator stdout SHA-256: `2fc288c752bb689bb310b3e6c6fc99b47b66d51b8f705a98d1222e3ca9ff5766` (identical double-run).
- Whole-pack projection stdout SHA-256: `ba01efbd8c89a92fb59de6da854064c5e2b1366fd493efe61e716a78b954caf5` (identical double-run).
- Runtime result SHA-256: `430572cbea12360a75e98935626a6d82635a767504ee4957341844b674f8314d`.
- Round report SHA-256: `1ac0d3e2ebd52bf44df33d075e0194105d228d28e88bb69a21849adc6ecdcfe5`.
- Independent vessel audit SHA-256: `256b91d2fb2f315e7c4153aca05025691de7f58b2a7a9b4268f4be63540512ce`.

## Formal persistence note

Round XLII includes formal vessel persistence changes in the working tree. The report records those changes honestly; no database or registry push receipt is claimed.

## Evidence entrance

- `scripts/validate-tashas-feature-production-consumer-round-XLII.py`
- `backend/tests/test_tashas_feature_production_consumer_round_XLII.py`
- `scripts/audit-tashas-genie-vessel.py`
- `reports/tashas-feature-production-consumer-round-XLII-2026-08-13.json`
- `data/content-ir/compiled/production-runtime-results-XLII.json`
- `reports/tashas-genie-vessel-source-boundary-2026-08-13.json`
