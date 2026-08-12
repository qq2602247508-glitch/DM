# Round XXVII：海渊魂灵 Generic Communication Consumer

本轮关闭 source-complete `content.tashas-cauldron.round2.feature.fathomless-oceanic-soul`
（海渊魂灵，深海意志邪术师 6 级），补齐此前未建模的「水下互相语言理解」语义。

## 语义与 source-complete 复核

- 原特性包含两条真实来源子句：`cold-resistance`（寒冷抗性）与新增的
  `underwater-communication`（当双方完全浸没在水中时，彼此能听懂对方说出的语言）。
- 新增名称无关 `grant_communication` operator（`channel=speech`、`direction=mutual`、
  `required_condition=submerged`），materializer 投影为只读 `communication` feature action。
- `source_completeness` 由 `incomplete` 升为 `complete`，`unmodeled_source_terms` 清空；
  source record/path/fingerprint、reviewed fields、manual decisions 与 source evidence 保留。

## 通用 consumer 与真实闭环

- 新增名称无关 `communication.mutual_comprehension.v1` production consumer；dispatch 仅按
  `content_kind=feature` + `communication` block，无 feature-name 分支。
- `ContentIRRuntimeService` 在 `_preview_feature` / `_confirm_feature` 增加
  `resolution_kind=communication` 分支：真实检查 actor 与 target 均满足
  `required_condition`（submerged），任一不满足即 fail closed（400）；CAS（stale actor 409）、
  preview→confirm→replay、OperationTransaction 幂等持久化全通过。
- 顺带修复 `_preview_feature` 中非 teleport 分支未初始化 `teleport_preview` 的潜在
  `UnboundLocalError`（此前仅 teleport 分支被生产覆盖）。

## 实际净增

- Tasha：`production_full 89→90`、`compile_only 3→2`、`game_usable 91→92`；
  content-ID funnel `95 = 91 production + 2 dm_assisted + 2 compile_only`，`relation_holds=True`。
- 项目：`production_full 189→190`、`compile_only 35`、`unique compiled 111`。

## 证据

- `scripts/validate-tashas-feature-production-consumer-round-XXVII.py`
- `backend/tests/test_tashas_feature_production_consumer_round_XXVII.py`
- `reports/tashas-feature-production-consumer-round-XXVII-2026-08-13.json`
- `data/content-ir/compiled/production-runtime-results-XXVIII.json`

## 保护与边界

- 正式 database、formal registry、source corpus、campaign/character、3D 与两个永久保护路径
  未写入；`name_branch_count=0`；`formal_registry_written=False`、`formal_database_written=False`。
- 保护指纹保持：database `f3abdcf57b0d71888f085ca081511df4f4e23f100066b402d49d769089fa6aad`、
  formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、
  integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、
  ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。

## 下一轮

- 剩余 compile-only：`genie-bottled-respite`（vessel / 异次元空间）、
  `scribe-manifest-mind`（spectral-object entity lifecycle + remote spell origin）。
- 继续下一个 source-complete generic consumer；communication 已闭合，
  vessel、spectral-object、entity lifecycle 与 character-growth seams 保持 fail-closed，
  不迁移下一本扩展包、不触碰 3D。
