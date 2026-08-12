# Round XXI：Psionic Sorcery Typed Spell-Context Consumer

状态：accepted。实现提交 `2066902` 已推送到 `origin/main`；receipt 另行提交。

## 目标与审阅结论

本轮选择 source-complete 的 `content.tashas-cauldron.round2.feature.aberrant-mind-psionic-sorcery`（灵能术法 / Psionic Sorcery）。其完整 authored Typed IR 保留两个显式 clause：

- `component-override`：当法术明确带有 `applies_when=psionic_spell` 时，忽略言语、姿势及无费用材料成分。
- `payment-override`：当法术为 1 环或更高且满足同一 context 时，将 `spell_slot` 支付替换为 `sorcery_points`，费用等于法术位环阶。

source fingerprint、reviewed fields、source record、source path、manual decision 和空的 `unmodeled_source_terms` 均写入 evidence；没有按 Feature 名称或法术名称 dispatch。单条选取属于 spell-economy/context platform-core exception，正常批次门槛为 8，原因是需要一次性关闭通用施法上下文、支付、CAS、snapshot 和 rollback seam。

## 实现与运行时闭环

- `spell.context.v1` registry descriptor 接入 feature production registry；`feature_compiler` 与 materializer 持久化 typed `spell_context` blocks。
- `ContentIRRuntimeService` 从 actor 的 Feature Runtime snapshot 解析 typed context，且只接受法术 metadata 明确声明 `psionic_spell=true` 的 1 环以上法术；无 display-name 分支。
- `SpellEconomyService` 在 preview 中校验组件与灵能点资源，在 confirm 中通过资源 CAS 消耗 `slot_level` 数量的 `sorcery_points`，保持法术位不变；已有 spell transaction、OperationTransaction、preview token、幂等 replay 和下游 rollback 链继续生效。
- 真实隔离 SQLite evidence 使用 6 级角色和 1 环塔莎酸蚀酿：材料不可用仍 preview/confirm 成功，法术位 `2→2`，灵能点 `3→2`，目标生命值变化；重复 confirm 幂等，模拟下游失败后 spell/resource 全部 rollback。

## Round after 与边界

全包迁移稳定为：Tasha `525 atoms / 408 player-facing / 408 executable / 95 authored Typed IR / 94 compile / 94 preview / 84 production / 2 DM-assisted / 86 game usable / 8 compile-only / 314 manual / 107 DM reference`；项目 production full `184`，compile-only `35`，unique compiled `111`。ItemSpec 保持 `47 total / 40 compile / 40 isolated / 40 registered / 40 game usable`。

Formal 499 仍为 `328 full / 110 partial / 61 dm_only`；formal registry、campaign/character/database、source corpus、3D 和永久保护路径均未写入。受保护指纹保持：database `f3abdcf5…a6ad`、formal registry `f4b5eab2…ca6b`、integrations manifest `ae4ef9f5…cd91`、`backend/tests/ollama.py` `8027a6d8…e6ab`；`name_branch_count=0`。

## 验证门禁

- Round XXI validator：1/1 production runtime full；16 项结果检查全部为 true。
- focused pytest、Ruff、compileall、`git diff --check` 通过；backend full pytest：`902 passed, 1 warning`。
- whole-pack migration 连续运行；stdout byte-identical，且连续三次 runtime registry、whole-pack report、status audit、baseline、production report SHA-256 完全一致。
- implementation/evidence commit：`2066902`，已推送；本 receipt 与 ledger/handoff/plan 更新随后单独提交。

## 下一轮

继续从剩余 compile-only 合同中复核 summon/entity、defense、communication、maneuver eligibility、vessel、teleport destination 和 spectral-object seams；保持 unresolved source contract fail-closed，不迁移下一本扩展包，不把 isolated-only、DM-reference 或单条子句冒充 production full。
