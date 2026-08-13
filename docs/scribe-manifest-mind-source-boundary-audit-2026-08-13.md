# Manifest Mind source-boundary completion audit — 2026-08-13

结论：未升 production。source-completeness 保持 `incomplete`，compile status 保持 `partial`，`unmodeled_source_terms` 不清空。原因是 source clauses 仍存在 missing/partial producer、consumer、persistence、CAS/replay 链路，尤其是 PB-per-day uses、Dispel Magic、spellbook destruction、owner dismissal，以及 `entity.senses`/reactivation 的 production-partial gate。

- feature: `content.tashas-cauldron.round2.feature.scribe-manifest-mind`
- source record: `ff7049c6a4d0aad0dae4adf5`
- source fingerprint: `dbbdb5b3ca9d86ece43c2f919d8483683f99068a478bccc401906057fccb920a`
- source path: `塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html`
- source HTML SHA-256: `56ea28aa46e3f85bda92f7f8487578337c7e0664c6a199d346e81539faf866b2`
- authored IR: `data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/scribe-manifest-mind.json`
- compiler status: `partial`

## Baseline

Round XXXVI baseline/after remains Tasha `106 authored / 105 compile / 105 preview / 101 production / 2 compile-only`; project `201 production / 35 compile-only / 111 unique compiled`. This audit changes no production count.

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
| `dispel-magic-expiry` | `partial` | `feature_runtime_compiler` | `entity_lifecycle_service` | `entity.lifecycle.state` | `closed` | Typed lifecycle termination reason exists, but no focused production receipt proves this event through the runtime consumer. |
| `spellbook-destruction-expiry` | `partial` | `feature_runtime_compiler` | `entity_lifecycle_service` | `entity.lifecycle.state` | `closed` | Typed lifecycle termination reason exists, but no focused production receipt proves this event through the runtime consumer. |
| `owner-dismissal-expiry` | `partial` | `feature_runtime_compiler` | `entity_lifecycle_service` | `entity.lifecycle.state` | `closed` | Typed lifecycle termination reason exists, but no focused production receipt proves this event through the runtime consumer. |
| `owner-death-expiry` | `partial` | `feature_runtime_compiler` | `entity_lifecycle_service` | `entity.lifecycle.state` | `closed` | Owner death lifecycle receipt is incomplete. |
| `long-rest-reactivation` | `partial` | `feature_runtime_compiler` | `spell_slot_reactivation_service` | `entity.lifecycle.reactivation_state` | `closed` | The reactivation capability remains production_partial. |

## Evidence and gate

- Round XXXII lifecycle and remote-origin real runtime evidence passes focused/API transaction boundaries.
- Round XXXIII entity senses real receipts pass, but the capability remains `production_partial`.
- Round XXXV entity spatial movement/300-ft expiry real domain evidence passes, but feature promotion remains blocked.
- Round XXXVI spell-slot reactivation real resource/rest transaction evidence passes, but the capability/materializer remains `production_partial`.
- The production gate therefore remains fail-closed: no `production_runtime_full_ids`, no whole-pack production migration delta.

## Required next work

1. Add a generic PB-per-day feature resource consumer with long-rest recovery, Character resource persistence, CAS, replay, rollback, and real API receipts.
2. Add generic lifecycle termination events for Dispel Magic, bound source-object destruction, and owner bonus-action dismissal.
3. Close `entity.senses` and `spell.slot.reactivation` from `production_partial` to a production registry consumer only after all negative boundaries pass.
4. Split the authored IR into independently auditable typed clauses for placement/form, sensory sharing, owner-turn wizard-spell gating, and termination events; only then reassess `source_completeness`.

Protected paths were not read for content changes, modified, staged, or committed by this audit.
