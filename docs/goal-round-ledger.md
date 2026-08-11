# Goal Round Ledger

本 Ledger 记录持续 Goal 的独立生产 Round。状态层严格区分：

`compile_full → runtime_preview_full → isolated_runtime_validated → registered_production_full → game_usable`

其中 `game_usable = registered_production_full + dm_assisted`。隔离 pack 不得自动成为正式 registry。

## Round 9：Resource Profile / Exchange / Event Window Consumer Expansion

当前状态：`accepted`；本轮完成 6 条真实 API evidence，属于 platform/core growth round，已提交并推送，整包 game usable 达到 76。

- 6/6 条剩余 full Feature contracts 通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay；psi-warrior psionic dice 完成 advancement resource profile，Battle Master 两条完成 triggered attack window，Harness Divine Power 完成 typed resource exchange，Interception/Runic Shield 完成 reaction window。formal apply/database/campaign/character 写入均为 false。
- 新增通用能力：`combat_engine.feature_event_window.v1`、typed `window_spec`、CombatAction durable eligible window、resource exchange、resource profile advancement、resource/CAS/idempotency 绑定；没有 feature-name/name-based runtime branch。
- Tasha status layers：`registered_production_full=74`（68→74）、`dm_assisted=2`、`game_usable=76`；`manual_authoring=314`、`compile-only=17`（23→17）、`authored Typed IR=94`、`runtime_preview_full=93`。
- 真实断言覆盖 1 个 resource profile、2 个 triggered attack window、1 个 proficiency-derived exchange（2 点）、2 个 reaction window；typed consumer、preview-confirm-replay、resource/CAS 全通过，name branch=0。
- 完整 backend pytest、Round III/V/VI/VII/VIII/IX 与 whole-pack 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-IX-2026-08-12.md`、Round IX report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：继续处理 unresolved ItemSpec consumer 与 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 的真实 event producer/consumer；已补齐的 generic window/resource consumer 继续复用。

## Round 11：ItemSpec Content Quality Correction / Equipment Consumer Expansion

当前状态：`accepted`；本轮完成 parser 质量修复和 8 条真实 ItemSpec evidence，已提交并推送。

- `_explicit_spell_identities()` 收紧为显式 `施展*中文名**English Name*法术`，移除自由 inline spell 抽取；职业法器、法术书目录、状态名和 generic “这道法术”不再伪装成 `granted_spell`。真实明确的 Disguise Self identity 保留。
- 质量重建将 ItemSpec `compile_full` 从 41 收紧至 37，10 条 partial 的实际 unresolved clauses 不被自动执行；ItemSpec typed 总量仍为 47。现有 Round X 8 条生产 evidence 继续有效。
- 新增 8 条：假肢、星卜编集、寰宇图纂、钟铃圣枝、奉献香炉、织心入门、灵肉圣契、异界行访录；8/8 create/attune-or-equip/action-or-charge preview→confirm→replay，16 个 operation transaction 通过。
- 当前 ItemSpec status layers：`47 total / 37 compile_full / 37 isolated_runtime_validated / 16 registered_production_full / 16 game_usable`；Feature Tasha status 仍 `74/2/76`，不与 ItemSpec 混计。
- 证据：Round XI report/result、Round XI doc/test、更新后的 ItemSpec catalog 与 whole-pack migration 输出。formal registry/database 仍未写入，name branch=0。
- 实现与证据提交 `0f3eccf0bcef428ff70932412d891708efc2c176` 已于 2026-08-12 05:08:31 +0800 推送到 `origin/main`；ledger receipt 更新随后单独提交。
- 下一步：继续审阅剩余 tattoo lifecycle、明确 spell-cast/charge 语义和 unresolved effect clauses；不把 projection-only、isolated-only 或 DM-reference 计入 production。

## Round 10：ItemSpec Equipment Consumer Production Evidence

当前状态：`accepted`；本轮完成 8 条真实 ItemSpec API evidence，ItemSpec registered production 从 0 增至 8，ItemSpec game usable 达到 8；Feature status layers 保持不变。

- 8/8 条 `compile_full` ItemSpec 通过真实 equipment create，以及 attune/equip、granted action、charge operation 的 preview→confirm→幂等 replay；14 个 operation transaction 均落在临时迁移 SQLite。
- 通用 consumer 覆盖 `item.equipment_modifier.v1`、`item.attunement.v1`、`item.charge_resource.v1`、`item.granted_action.v1`。守护者纹章与炼金总纲实际完成充能扣减；所有 ItemSpec projection、同调状态、角色 CAS、幂等 replay 均通过，name branch=0。
- ItemSpec 状态：`47 total / 41 compile_full / 41 isolated_runtime_validated / 8 registered_production_full / 8 game_usable`；6 个 partial blocker 继续保留。Feature 的 Tasha status 仍为 `production_full=74`、`dm_assisted=2`、`game_usable=76`。
- 新增 `load_item_production_evidence()`：只有带 `content_kind=item` 且整批 create/preview/confirm/replay gate 通过的 persisted result 才能回填 ItemSpec registered 层；隔离 pack 仍 `formal_apply=false`，不写正式数据库。
- validator、round test、ItemSpec catalog、whole-pack migration 两次确定性验证、backend 定向测试已通过；完整 backend pytest、Ruff、compileall、保护指纹和 push receipt 在本轮收尾门禁中确认。
- 证据：`docs/tashas-item-production-consumer-round-X-2026-08-12.md`、Round X report/result、`reports/tashas-item-spec-catalog-2026-08-11.json`。
- 实现与证据已提交并推送：`42153f2562cab8d24af9fc67e7549a7dc2056b13`，`origin/main`，2026-08-12 04:52:00 +0800；receipt 随后写入独立交接提交。
- 下一步：继续 unresolved ItemSpec granted-spell/tattoo lifecycle 与需要真实 event producer 的 clauses；不把 projection-only、isolated-only 或 DM-reference 伪装成 production。

## Round 8：Trigger-bound Modifier / Activation Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，已提交并推送，整包 game usable 达到 70。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` combat preview→confirm→幂等 replay；7 条通过 typed passive/inspection registry，`psi-powered-leap` 通过已有 feature-action activation，临时迁移 SQLite。formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=68`（60→68）、`dm_assisted=2`、`game_usable=70`；`manual_authoring=314`、`compile-only=23`（31→23）、`authored Typed IR=94`、`runtime_preview_full=93`。
- 真实断言覆盖 grappling/tactical/attack correction/psionic check 的 passive binding、Starry Form resistance/saving inspection，以及灵力跃动实际 `psionic_dice` 3→2 和飞行 activation；runtime ID、typed consumer、resource/CAS、preview-confirm-replay 均 8/8，name branch=0。
- 完整 backend pytest、Round III/V/VI/VII/VIII 与 whole-pack 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-VIII-2026-08-12.md`、Round VIII report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：建设通用 reaction-window、resource exchange/profile 与真正 event producer/consumer 链，再处理 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 unresolved ItemSpec lifecycle；未经过完整事件语义的合同继续不计 production。

## Round 7：Typed Advancement / Character Growth Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，已提交并推送，整包 game usable 达到 62。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` advancement preview→confirm→幂等 replay；临时迁移 SQLite，并实际写入 character features/spell grants snapshot。consumer 统一为 `advancement_service.character_growth.v1`，formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=60`（52→60）、`dm_assisted=2`、`game_usable=62`；`manual_authoring=314`、`compile-only=31`（39→31）、`authored Typed IR=94`、`runtime_preview_full=93`。
- 真实断言覆盖 10/10、10/10、2/2、2/2、2/2、1/1、2/2、6/6 spell grant 形态；4 个 typed choice consumer 完成选择生命周期；advancement block ready、character CAS、transaction、feature persistence 均为 8/8，name branch=0。
- 完整 backend pytest、Round III/V/VI/VII 与 whole-pack 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-VII-2026-08-12.md`、Round VII report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：继续推进剩余 resource/action/trigger lifecycle、vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 unresolved ItemSpec lifecycle；isolated-only 和 DM-reference 继续不计 production。

## Round 6：Passive Modifier / Inspection Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，8 条 registered production，整包 game usable 达到 54。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` passive inspection preview→confirm→幂等 replay；临时迁移 SQLite，所有 passive block 均与 runtime ID 绑定，consumer 为 `combat_engine.feature_action.v1`。formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=52`（44→52）、`dm_assisted=2`、`game_usable=54`；`manual_authoring=314`、`compile-only=39`、`authored Typed IR=94`、`runtime_preview_full=93`。
- 真实断言覆盖 spell/passive、速度、armor、sight、attack-context/social-check modifier；name branch=0，typed consumer=8/8，passive binding=8/8，inspection resolution=8/8。
- 完整 backend pytest、Round VI/历史 Tasha 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-VI-2026-08-12.md`、Round VI report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：继续推进 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 和 unresolved ItemSpec lifecycle；isolated-only 和 DM-reference 继续不计 production。

## Round 5：Typed Advancement / Character Growth Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，8 条 registered production，整包 game usable 达到 46。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` advancement preview→confirm→幂等 replay；临时迁移 SQLite，并实际写入 character features/proficiencies/skills/spells snapshot。formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=44`（36→44）、`dm_assisted=2`、`game_usable=46`；`manual_authoring=314`、`compile-only=47`、`authored Typed IR=94`、`runtime_preview_full=93`。
- 通用实现：`content_kind=advancement`、`advancement_service.character_growth.v1`，按 typed `advancement` / `proficiencies` / `prepared_spell_list` block 分发；固定 grant、choice grant、grant_spell 共用 character CAS、operation transaction、idempotency 和 feature snapshot。
- 真实断言覆盖固定熟练/语言、Order Cleric/Skill Expert/Ranger Canny 选择生命周期，以及 Aberrant Mind 10 个 spell grants；name branch=0，typed consumer=8/8。
- 完整 backend pytest、Round V/历史 Tasha 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-V-2026-08-12.md`、Round V report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：继续推进 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 和 unresolved ItemSpec lifecycle；isolated-only 和 DM-reference 继续不计 production。

## Round 4：Movement / Sight / Choice / Lifecycle Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，8 条 registered production，整包 game usable 达到 38。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay；临时迁移 SQLite，并经 combat turn boundary 刷新移动 / 视觉快照。formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=36`（28→36）、`dm_assisted=2`、`game_usable=38`；`manual_authoring=314`、`compile-only=55`、`authored Typed IR=94`、`runtime preview full=93`。
- 通用修复：选择绑定落到 `resources.selected`；显式移动模式生成通用 feature action 并持久化限时速度；支持 climb / walking speed / fixed speed；视觉 `set` 模式进入冻结 `rule_modifiers` 与 `active_sight_modes`；资源消耗继续走角色资源 CAS。没有 feature-name/name-based runtime branch。
- 真实断言覆盖海洋馈赠游泳、越野攀爬/游泳、兽性之魂选择、两条盲斗盲视、元素赐福/翻腾浪涌/午夜飞步飞行与资源扣减。完整 backend pytest 通过；whole-pack migration 和 Round IV validator 双次关键输出 byte-identical。
- 保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 下一步：继续推进 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 unresolved ItemSpec lifecycle；isolated-only 和 DM-reference 继续不计 production。

## Round 3：Formal Production Consumer Evidence Harvest

当前状态：`accepted`；本轮完成 12 条真实 API evidence，11 条 registered production、1 条 DM-assisted，整包 game usable 达到 30。

- 12/12 条 Round 2 Feature contracts 通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay；临时迁移 SQLite，formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=28`（17→28）、`dm_assisted=2`（1→2）、`game_usable=30`；`manual_authoring=314`、`compile-only=63`、`authored Typed IR=94`、`runtime preview full=93`。
- 通用修复：attack-hit typed intent 选择 rider、superiority die/ability modifier timed value materialization、AC timed modifier、`_or_` condition removal、DM-confirmed reaction trigger + reaction CAS。name branch 仍为 0。
- 正式 499 audit 保持 328/110/61；3D、source corpus、正式 campaign/character 数据未修改。证据见 `docs/tashas-feature-production-consumer-round-III-2026-08-12.md` 和 Round III report/result。
- 下一步：继续收割 movement/sight/passive/choice 等需要独立事件入口的 Feature consumers；未经过真实 producer/consumer/persistence/CAS/replay 的合同继续停在 isolated 或 partial。

## Round 2：Feature/Option Semantic Contract Batch I

当前状态：`completed_with_formal_boundary_open`；本批已完成隔离合同与角色成长闭环，正式 production 收割转入下一 Round。

- 64/64 条真实 Feature/Option atom 完成 reviewed + authored Typed IR；58/64 compile full，6 条保留 partial blocker。
- 58 条 full 合同完成 isolated pack apply/reload 与幂等重放；58 grants 进入角色成长 runtime compiler，`closed_loop=true`。formal apply=false，registered production 增量为 0。
- 整包真实结果：94 authored Typed IR、93 runtime preview full、manual authoring 314（378→314）、compile-only 75；正式 Tasha 仍为 production 17、DM-assisted 1、game usable 18。
- 通用实施包括多 advancement/prepared-spell 合并、stable feature ID、typed authorized-information consumer；没有新增 feature-name/name-based runtime branch。
- 证据：`reports/tashas-feature-contract-batch-I-2026-08-12.json`、`reports/tashas-feature-contract-runtime-batch-I-2026-08-12.json`、`docs/tashas-feature-option-contract-batch-I-2026-08-12.md`。
- 下一步：Round 3 只从已有通用 consumer 收割正式 production evidence，优先 passive proficiency、movement、resource/action；继续保持 isolated 与 formal production 分账。

## Round 1：统计口径与塔莎 Item Registry 收口

当前状态：`accepted`，已 push 到 `origin/main`。

- 实际起点：塔莎 524 个 QA 后 atoms、407 executable；ItemSpec 47，总计 41 compile/preview full，但没有可 reload 的 whole-pack isolated runtime registry。
- 本轮实现：统一 Content IR status layers；新增 `ContentPackRuntimeRegistry`；每条 ItemSpec 重新解析、校验消费者投影和 pack/version/source identity；生成 `runtime-registry.json`。
- 当前证据：47 条 ItemSpec reload；41 条 `isolated_runtime_validated`；6 条保留 blocker；`registered_production_full=0`；正式 registry/database 未写入。
- 真实净增：isolated runtime validation +41；没有伪造 formal production 或 game usable 增量。
- 下一步：Feature/Option Contract Harvest Round，优先高扇出 choice/resource/trigger/target/duration/summon 合同。
- 提交：`776c7fe`、`ecd6606`、`9c581e7`、merge `c8fe28c`。
- Push receipt：`origin/main` → `c8fe28c1c3c4c215f4eaeda1e6acc590afd93add`，2026-08-12 00:23:50 +0800。
