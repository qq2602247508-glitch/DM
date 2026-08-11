# Content IR authored batch I — 2026-08-11

本批把真实本地 CHM source records 逐条人工审阅为可追溯 Typed IR，并通过统一
Workbench 的 compiler、materializer、runtime preview 和隔离 dry-run。

## 结果

- authored typed IR：30
- compile `full`：30
- 2024 PHB spells：12 authored / 12 full
- official expansion spells：10 authored / 10 full
  - Xanathar：5
  - Tasha：2
  - Fizban：2
  - Book of Many Things：1
- official expansion features：8 authored / 8 full，全部来自 Tasha
- 职业/子职业正式 499 条审计：`328 / 110 / 61` → `328 / 110 / 61`，新增 full 为 0

原版法术分母保持独立：2024 PHB 为 411 条 records、391 条详情候选；2014 PHB
为 372 条 records、361 条详情候选。未把整本书未选中的 manual 条目计入本批失败。

## 生产合同

Spell IR 现在包含 schema/version、source path/book/fingerprint、review metadata、
evidence、clause boundaries、manual decisions 和 compiler fingerprint。闭集 clause
覆盖目标选择、攻击检定、豁免及成功/失败分支、伤害、治疗、临时生命、条件、范围、
持续时间、专注、移动和升环；未知类型/字段/缺参数 fail-closed。full 会生成
`spell-runtime-1` 标准 runtime block，不依赖法术名称。

FeatureSpec 复用现有 FeatureCompiler、Capability Catalog 和 Feature Materializer。
新增的通用补强是 proficiency replacement choice 的 materializer 投影；没有新增
feature-name 或 spell-name runtime 分支，也没有新增高风险底层 capability。

## 资产与报告

资产根目录为 `data/content-ir/authored/`，每条资产单独 JSON，并保留真实 source
fingerprint 和人工审阅字段。塔莎目录同时提供：

```text
data/content-ir/authored/official-packs/tashas-cauldron/manifest.json
```

该根 manifest 可直接编译混合 2 条 Spell + 8 条 Feature；子目录仍可独立编译。

报告：

- `reports/content-ir-authored-batch-I-2026-08-11.json`
- `reports/spell-ir-core-2024-golden-2026-08-11.json`
- `reports/spell-ir-official-expansion-batch-2026-08-11.json`
- `reports/feature-ir-official-expansion-batch-2026-08-11.json`
- `reports/content-ir-completion-unlock-ranking-2026-08-11.json`
- `reports/content-ir-isolated-pack-dry-run-2026-08-11.json`

这些资产与报告重复构建后 byte-identical。隔离 dry-run 首次写入临时 target，第二次
返回 `idempotent_replay`；正式 database、registry、campaign 和 character snapshot
均未写入。
