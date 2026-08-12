# 《塔莎的万事坩埚》Round XXV：Production Evidence / Status Reconciliation

日期：2026-08-12

本轮没有新增名称分支、source corpus、正式数据库、formal registry、campaign/character 或 3D 改动。目标是把历史 Round receipts、whole-pack Atom funnel 和 ItemSpec funnel 统一到同一个可去重、可验证的 evidence/status projection。

## 实际实现

- 新增 `content_ir_production_evidence.py`，统一读取 `production-runtime-results*.json`，按 pack namespace、content kind、required consumer checks 和 `name_branch_count` 过滤，并按 content ID 去重。
- whole-pack migration 与 `existing_project_production_ids()` 改用共享 evidence loader；Tasha receipt 和全项目 receipt 不再由两个不同的 glob/ID 规则计算。
- `load_item_production_evidence()` 改用相同 loader，继续只接受完整 equipment/attunement/item-state receipt；ItemSpec 不会因 isolated reload 自动升级。
- ItemSpec catalog 现在显式发布 `dm_assisted` 与 canonical `status_layers`，`game_usable` 由状态层计算，不通过独立相加字段重复计数。
- whole-pack Item report 读取 ItemSpec 的 `dm_assisted` 字段，避免 Item、Feature、Spell、Feat、Option 的 status semantics 在报告层分叉。

## 当前真实状态

| 指标 | 当前值 |
|---|---:|
| Source records | 144 |
| Content atoms | 525 |
| Player-facing executable | 408 |
| Authored Typed IR | 95 |
| Compile full / runtime preview full | 94 / 94 |
| Tasha production full | 88 |
| Tasha DM-assisted | 2 |
| Tasha game usable | 90 |
| Tasha compile-only | 4 |
| Manual authoring / DM reference | 314 / 107 |
| ItemSpec total / compile full | 47 / 40 |
| ItemSpec isolated / registered / game usable | 40 / 40 / 40 |
| Tasha persisted receipt IDs | 131 |
| Project persisted receipt IDs | 188 |

关系门禁保持：

```text
game_usable = registered_production_full + dm_assisted
90 = 88 + 2
ItemSpec game_usable = registered_production_full + dm_assisted
40 = 40 + 0
```

Round XXIV 的两条 summon receipt 已纳入当前 Tasha union：

- `tashas-cauldron:spell:54c8c29188db1442473d9dc1`
- `tashas-cauldron:spell:083419d9de551806a5ca9748`

ItemSpec evidence 仍严格为 40 条，且全部是 `content.tashas-cauldron.item.*`；没有把 Feature/Spell receipt 或 isolated-only 条目混入 ItemSpec production。

## 验收

- Round XXV validator：17/17 checks 通过。
- focused reconciliation / whole-pack / ItemSpec tests：18 passed。
- backend 全量 pytest：通过；仅有既有 Starlette/httpx deprecation warning。
- backend source/tests Ruff：通过。
- Round XXV validator、migration script Ruff：通过（按项目脚本既有 E402/E501 配置）。
- backend source、scripts、tests compileall：通过。
- `git diff --check`：通过。
- whole-pack migration 连续两次 stdout byte-identical，SHA-256：
  `f49d04eeb7158151289e61216da4e2908bf075d5d0777a0c24408c19a0630677`。
- 当前 database fingerprint 与 Round XXV baseline 一致：
  `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`。
- formal registry fingerprint：
  `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`。
- `backend/tests/integrations/` manifest：
  `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`。
- `backend/tests/ollama.py`：
  `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。

历史 Round XXVI receipt 中保存的 database 字符串与当前 baseline 有一处历史字符差异；本轮 validator 同时记录了该历史值，并以当前权威 baseline、当前文件 aggregate 与 receipt 的 `formal_database_unchanged=true` 作为门禁依据，没有修改数据库或伪造历史 receipt。

证据入口：

- `scripts/validate-tashas-production-reconciliation-round-XXV.py`
- `backend/tests/test_tashas_production_reconciliation_round_XXV.py`
- `reports/tashas-production-reconciliation-round-XXV-2026-08-12.json`
- `reports/tashas-whole-pack-report-2026-08-11.json`
- `reports/tashas-item-ir-report-2026-08-11.json`
