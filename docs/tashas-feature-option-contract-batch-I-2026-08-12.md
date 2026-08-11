# 《塔莎的万事坩埚》Feature/Option Contract Batch I

日期：2026-08-12。该批次是持续 Goal 的 Round 2，范围限定为 Feature/Option 语义合同、通用 FeatureSpec materializer、隔离 pack runtime 与角色成长回路；不处理 3D，也不修改正式 registry、database、campaign 或 character 数据。

## 结果

| 层级 | 结果 | 口径 |
| --- | ---: | --- |
| reviewed Feature/Option | 64 | 64 条真实 Content Atom 的显式 source-bound 映射 |
| authored Typed IR | 64 | `authored_ir`，逐条保留 source record/fingerprint/span |
| compile full | 58 | 其余 6 条 fail-closed 为 partial |
| isolated runtime reload | 58 | `FeaturePackImporter` apply/reload 后仅暴露 full |
| character-growth contracts | 58 | 58 grants → 58 runtime contracts，闭环通过 |
| registered production full | 0 增量 | 隔离结果不计正式 production |
| DM-assisted / game usable | 0 / 0 增量 | 正式 Tasha 基线仍为 1 / 18 |

6 条 partial 保留真实边界：海渊魂灵的水下互通、瓶中小憩的 vessel/entity lifecycle、不知疲倦的 exhaustion timing、神识显现的 spectral object lifecycle、心灵传送的 destination consumer，以及灵能术法的 component/payment consumer。它们没有被名称分支或宽松 fallback 提升为 full。

## 实施

- `scripts/author-tashas-feature-contract-batch-I.py` 使用显式 atom ID 与 clause/operator mapping 生成 64 个确定性 FeatureSpec 资产；没有 keyword-to-operator 推断。
- `FeatureCompiler.materialize_runtime_definition` 现在合并多个 advancement/prepared-spell block，同时保留逐 grant 的 `spell_grants` 元数据；十条灵能法术授予不会互相覆盖。
- `feature_runtime_contract` 支持显式稳定 feature ID，修复同一 class/level 下不同授予项的运行时合同碰撞。
- `feature_materializers` 与 combat service 增加通用 authorized-information 投影，支持 telepathy、shared darkvision、manifest-mind senses 等 typed information kind；叙事内容仍不写入战斗状态。
- `scripts/validate-tashas-feature-contract-batch-I.py` 在隔离目录执行 dry-run、首次 apply/幂等重放、registry reload，并将 58 条合同送入现有 character feature-runtime compiler。

角色成长验证证据：58 grants、14 proficiencies、9 movement modes、7 resource keys、6 action projections；`closed_loop=true`。formal apply 明确为 false。

## 整包影响

迁移重跑后仍扫描 144 source records、524 QA atoms、407 executable atoms；Tasha authored Typed IR 为 94、runtime preview full 为 93、manual authoring 从 378 降至 314、compile-only 为 75。正式 Tasha production full 仍为 17、DM-assisted 为 1、game usable 为 18；全项目仍为 111 unique compiled / 76 production full / 35 compile-only，正式 499 条职业审计保持 328 full / 110 partial / 61 dm_only。

## 验证与下一 Round

新增批次测试 4/4 通过；Feature IR、runtime、Tasha recovery/migration 定向回归通过；Ruff 与 compile gate 继续执行。下一 Round 应收割已有通用 consumer 的正式 production evidence，优先把可证明的 passive proficiency、movement、resource/action contracts 从 isolated 提升到 registered production；仍需保持 isolated/runtime/production 三层分账，不能直接把本批 58 条计入正式 production。
