# Goal Round Ledger

本 Ledger 记录持续 Goal 的独立生产 Round。状态层严格区分：

`compile_full → runtime_preview_full → isolated_runtime_validated → registered_production_full → game_usable`

其中 `game_usable = registered_production_full + dm_assisted`。隔离 pack 不得自动成为正式 registry。

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
