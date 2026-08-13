# Manifest Mind source-boundary completion audit — 2026-08-13

结论：未升 production。source-completeness 保持 `incomplete`，compile status 保持 `partial`，`unmodeled_source_terms` 不清空。四条 source-bound termination clause 已有真实 producer→consumer→persistence→CAS/replay receipt 并升为 `covered`；剩余 blocker 为 PB-per-day uses 以外的 entity senses/spatial authored binding、telepathic sharing、以及 `entity.senses`/reactivation 的 production-partial gate。

- feature: `content.tashas-cauldron.round2.feature.scribe-manifest-mind`
- source record: `ff7049c6a4d0aad0dae4adf5`
- source fingerprint: `dbbdb5b3ca9d86ece43c2f919d8483683f99068a478bccc401906057fccb920a`
- source path: `塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html`
- source HTML SHA-256: `56ea28aa46e3f85bda92f7f8487578337c7e0664c6a199d346e81539faf866b2`
- authored IR: `data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json`
- compiler status: `partial`

## Baseline

Round XXXVI baseline/after remains Tasha `106 authored / 105 compile / 105 preview / 101 production / 2 compile-only`; project `201 production / 35 compile-only / 111 unique compiled`. Dynamic source matrix changes from `3 covered / 10 partial / 0 missing` to `7 covered / 6 partial / 0 missing`; production counts remain unchanged.

## Source clause matrix

| clause | status | producer | consumer | persistence | CAS/replay | blocker |
|---|---|---|---|---|---|---|
| `activation-source-and-initial-placement` | `covered` | `feature_runtime_compiler` | `entity_lifecycle_service` | `entity.lifecycle.state` | `closed` |  |
| `spectral-object-form` | `partial` | `feature_runtime_compiler` | `entity_sensory_profile_service` | `entity.lifecycle.sensory_profile` | `closed` | The typed form contract and receipt exist, but entity.senses remains production_partial. |
| `entity-senses` | `partial` | `feature_runtime_compiler` | `entity_sensory_profile_service` | `entity.lifecycle.sensory_profile` | `closed` | The current entity.senses capability is production_partial. |
| `telepathic-sharing` | `partial` | `feature_action` | `combat_feature_action_target_defense_inspection` | `combat_action.result_json` | `closed` | The focused sensory receipt exists, but source-level telepathic no-action channel semantics are not separately closed. |
| `remote-spell-origin` | `covered` | `feature_runtime_compiler` | `remote_spell_origin_resolver` | `combat_action.spell_origin_resolution` | `closed` |  |
| `proficiency-bonus-uses` | `covered` | `advancement_service` | `character_resource_store` | `character.resources` | `closed` |  |
| `movement` | `partial` | `feature_runtime_compiler` | `entity_sensory_profile_service` | `entity.lifecycle.sensory_profile` | `closed` | Spatial seam is tested, but not yet independently bound to the authored activation contract. |
| `distance-expiry` | `partial` | `feature_runtime_compiler` | `entity_sensory_profile_service` | `entity.lifecycle.sensory_profile` | `closed` | Generic expiry exists, but authored feature binding remains partial. |
| `dispel-magic-expiry` | `covered` | `feature_runtime_compiler` | `entity_lifecycle_service` | `entity.lifecycle.state` | `closed` |  |
| `spellbook-destruction-expiry` | `covered` | `feature_runtime_compiler` | `entity_lifecycle_service` | `entity.lifecycle.state` | `closed` |  |
| `owner-dismissal-expiry` | `covered` | `feature_runtime_compiler` | `entity_lifecycle_service` | `entity.lifecycle.state` | `closed` |  |
| `owner-death-expiry` | `covered` | `feature_runtime_compiler` | `entity_lifecycle_service` | `entity.lifecycle.state` | `closed` |  |
| `long-rest-reactivation` | `partial` | `feature_runtime_compiler` | `spell_slot_reactivation_service` | `entity.lifecycle.reactivation_state` | `closed` | The reactivation capability remains production_partial. |

## Evidence and gate

- Round XXXII lifecycle and remote-origin real runtime evidence passes focused/API transaction boundaries.
- Round XXXVII adds real source-bound producer receipts for Dispel Magic, spellbook destruction, owner death, and owner dismissal; focused success/failure/replay/stale/negative tests pass.
- Round XXXIII entity senses real receipts pass, but the capability remains `production_partial`.
- Round XXXV entity spatial movement/300-ft expiry real domain evidence passes, but feature promotion remains blocked.
- Round XXXVI spell-slot reactivation real resource/rest transaction evidence passes, but the capability/materializer remains `production_partial`.
- The production gate therefore remains fail-closed: no `production_runtime_full_ids`, no whole-pack production migration delta.

## Required next work

1. Close authored entity senses/spatial binding and source-level telepathic sharing.
2. Close `entity.senses` and `spell.slot.reactivation` from `production_partial` to a production registry consumer only after all negative boundaries pass.
3. Reassess `source_completeness` only after the remaining independently auditable typed clauses are closed.

Protected paths were not read for content changes, modified, staged, or committed by this audit.
