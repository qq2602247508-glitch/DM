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
| `activation-source-and-initial-placement` | `partial` | `configure_entity_lifecycle` | `ContentIRRuntimeService advancement lifecycle consumer` | `Character.features[*].runtime.entity_lifecycles` | `OperationTransaction + character version CAS + operation replay` | The generic lifecycle stores lifecycle state but does not author/consume the 60-ft placement and unoccupied-space facts as this source clause. |
| `spectral-object-form` | `partial` | `configure_entity_senses` | `entity.senses materializer / sensory resolver` | `entity_senses runtime block` | `Generic feature runtime transaction boundary` | Intangible/non-occupying form and appearance choice have no typed producer, consumer, or persisted state; only light_radius_ft is represented. |
| `entity-senses` | `partial` | `configure_entity_senses` | `entity_sensory_profile_service / resolve_entity_senses` | `Character.features[*].runtime.entity_senses` | `Real runtime receipt has OperationTransaction + actor CAS + replay` | The capability and runtime consumer are explicitly production_partial; no production registry closure. |
| `telepathic-sharing` | `partial` | `expose_authorized_target_information` | `manifest-mind sensory information runtime path` | `Source-bound entity_senses/lifecycle snapshot` | `Preview/confirm/replay and actor CAS evidence exists` | Information resolution depends on the partial entity.senses capability; source-level no-action telepathy and complete channel semantics are not production-closed. |
| `remote-spell-origin` | `partial` | `configure_remote_spell_origin` | `remote.spell.origin.v1 spell runtime` | `Character feature runtime origin/lifecycle snapshot` | `Preview/confirm/replay, target authorization, CAS and OperationTransaction` | Origin geometry is closed, but the source's owner-turn/wizard-spell gating and dependency on a production-closed sensory profile are not fully closed. |
| `proficiency-bonus-uses` | `missing` | `missing` | `missing` | `missing` | `missing` | No typed resource clause, producer, consumer, long-rest recovery, transaction, CAS, or replay evidence exists for the PB-per-day limit. |
| `movement` | `partial` | `entity.spatial.v1 movement producer` | `entity spatial runtime` | `entity lifecycle spatial state` | `Expected-version CAS + operation replay + rollback evidence` | The generic spatial seam is tested, but the authored feature remains partial and the source clause is nested under a senses operator rather than independently typed. |
| `distance-expiry` | `partial` | `entity.spatial.v1 expiry producer` | `entity lifecycle expiry transition` | `entity lifecycle status` | `CAS/replay evidence exists` | Generic expiry is implemented, but the feature cannot promote while the complete sensory/runtime boundary remains partial. |
| `dispel-magic-expiry` | `missing` | `missing` | `missing` | `missing` | `missing` | No typed dispel event, authorization/effect resolution, persistence, CAS, or replay evidence is present. |
| `spellbook-destruction-expiry` | `missing` | `missing` | `missing` | `missing` | `missing` | No spellbook entity/effect destruction event or lifecycle consumer is authored. |
| `owner-death-expiry` | `covered` | `configure_entity_lifecycle` | `entity lifecycle expiry transition` | `entity lifecycle state` | `Lifecycle CAS/replay evidence` |  |
| `owner-dismissal-expiry` | `missing` | `missing` | `missing` | `missing` | `missing` | No authored dismiss event/action or runtime receipt is present. |
| `long-rest-reactivation` | `partial` | `configure_spell_slot_reactivation` | `spell.slot.reactivation.v1` | `Character feature runtime + Character.resources` | `OperationTransaction + character CAS + replay/rollback` | The real receipt seam exists, but the materializer/capability is explicitly production_partial and not in the production registry. |

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
