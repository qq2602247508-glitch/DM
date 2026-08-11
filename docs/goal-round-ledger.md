# Goal Round Ledger

本 Ledger 记录持续 Goal 的独立生产 Round。状态层严格区分：

`compile_full → runtime_preview_full → isolated_runtime_validated → registered_production_full → game_usable`

其中 `game_usable = registered_production_full + dm_assisted`。隔离 pack 不得自动成为正式 registry。

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
