# Content IR template/runtime batch II — 2026-08-11

本批把上一批 30 条 authored Typed IR 扩展为模板驱动的候选生成、review authority、真实
production runtime validation 闭环。候选层只复制 normalized source 中明确存在的字段；
operator、target semantics、action economy、resource cost、复杂持续时间/触发器、召唤控制、
choice 和复杂移动都保留为 review required，不能由候选生成器推断。

## 分层结果

| scope | scan/detail | generated | reviewed authored | compile full | preview full | production full |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| core 2024 spells | 391 | 100 | 60 | 60 | 60 | 10 |
| official expansion spells | 126 | 126 | 25 | 25 | 25 | 5 |
| Tasha expansion features | 48 | 48 | 15 | 15 | 15 | 5 |
| batch II total | — | 274 | 100 | 100 | 100 | 20 |

模板目录为 12 个 name-independent shapes，所有 authored asset 保留 source path、source
fingerprint、source evidence、reviewer、clause boundary 与 compiler fingerprint。候选状态
和 reviewed/authored 状态分离；模板或 source fingerprint 变化会使 candidate review stale。

## 真实入口验证

`ContentIRRuntimeService` 通过真实已知法术、角色、combatant feature registry 解析 runtime
block，再调用现有 spell economy 与 combat engine。验证了：

- 15 个真实法术 loops，覆盖 action economy、slot cost、damage/healing、saving/attack input、
  upcast、concentration、character/actor/target CAS 与 idempotency。
- 5 个真实 feature loops，覆盖 feature action、temporary HP/healing、resource consumption、
  actor/target CAS 与 player permission。
- 资源不足、错环阶、非法目标、下游失败 rollback、持续效果、turn snapshot rebuild、short-rest
  resource recovery 与幂等重放。

报告：

- `reports/content-ir-template-catalog-I-2026-08-11.json`
- `reports/content-ir-candidate-generation-I-2026-08-11.json`
- `reports/content-ir-reviewed-batch-II-2026-08-11.json`
- `reports/spell-ir-core-2024-batch-II-2026-08-11.json`
- `reports/spell-ir-official-expansion-batch-II-2026-08-11.json`
- `reports/feature-ir-official-expansion-batch-II-2026-08-11.json`
- `reports/content-ir-runtime-level-audit-2026-08-11.json`
- `reports/content-ir-production-runtime-validation-2026-08-11.json`
- `reports/content-ir-template-match-ranking-2026-08-11.json`
- `reports/content-ir-completion-unlock-ranking-II-2026-08-11.json`
- `reports/content-ir-isolated-pack-dry-run-II-2026-08-11.json`

## CLI

```bash
python -m feature_workbench templates build --input data/content-ir/authored --output data/content-ir/templates
python -m feature_workbench candidates generate --book '玩家手册 2024' --kind spell --catalog data/content-ir/templates/catalog.json --output data/content-ir/candidates/core-2024
python -m feature_workbench candidates report --input data/content-ir/candidates/batch-II
python -m feature_workbench review validate --input data/content-ir/authored/batch-II --catalog data/content-ir/templates/catalog.json
python -m feature_workbench compile reviewed --input data/content-ir/authored/batch-II --output data/content-ir/compiled/reviewed
python -m feature_workbench dry-run --input data/content-ir/compiled/batch-II
python -m feature_workbench report --input data/content-ir/compiled/batch-II --include-runtime-levels
```

499 条正式职业/子职业审计没有被本批改写：`328 full / 110 partial / 61 dm_only`。未闭合
operator、target、branch、choice、复杂 duration/trigger、summon control 与 movement 的
条目仍然是 partial/manual，不能用 compile 或 preview 结果冒充 production full。
