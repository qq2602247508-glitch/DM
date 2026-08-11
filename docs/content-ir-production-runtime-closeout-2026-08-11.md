# Content IR production runtime closeout — 2026-08-11

本轮把上一批 `100 compile full / 100 runtime preview full / 20 production runtime full`
的边界继续收口到真实后端 API。上一批 `batch-II` 保留为基线；新增 authored IR 独立写入
`data/content-ir/authored/batch-III/`，编译结果写入 `data/content-ir/compiled/batch-III/`。

## 结果

- 新 authored Typed IR：13 条，13/13 compile full，13/13 production full。
- 现有 compile-only 转 production：26 条 Spell + 5 条 Feature。
- 新 production runtime full：31 条；最终 production runtime full：51 条。
- Spell：新增 26 条，最终 41 条；Feature：新增 5 条，最终 10 条。
- 跨包新增/最终 Spell 生产数：Core 16/26、Xanathar 4/8、Tasha 2/3、Fizban 2/2、Book 2/2。
- 正式 499 审计保持 `328 full / 110 partial / 61 dm_only`，没有把它扩成 Feature 生产分母。

## 生产注册表与事务边界

`backend/src/dnd_dm_assistant/application/content_ir_production_registry.py` 是稳定闭集：

- `combat_engine.damage_heal.v1`
- `combat_engine.area_damage.v1`
- `combat_engine.condition_lifecycle.v1`
- `spell_economy.concentration.v1`
- `combat_engine.feature_action.v1`

路由只依赖 `content_kind + runtime_schema_version + typed clause sections`，不依赖法术名、特性名
或字符串分支。未知 schema、未知 runtime section、缺失生产字段都会 fail closed。

Spell 真实入口保留 Character/KnownSpell/slot/prepared/ownership CAS，Combat 入口保留 actor/target
CAS、action economy、slot/resource 消耗、固定骰值边界、攻击命中、豁免成功半伤（整数向下取整）、
区域几何、多目标 preflight/batch、HP 上限、temporary HP replacement、condition effect、
concentration、幂等和 rollback。Feature 入口覆盖 timed modifier、condition removal、passive
registry inspection 和攻击 rider；所有确认都写入 operation/combat audit snapshot。

## 报告与验证

- blocker audit：`reports/content-ir-production-blocker-audit-2026-08-11.json`
- unlock ranking：`reports/content-ir-production-unlock-ranking-2026-08-11.json`
- runtime validation：`reports/content-ir-production-runtime-validation-II-2026-08-11.json`
- runtime level audit：`reports/content-ir-runtime-level-audit-II-2026-08-11.json`
- cross-pack proof：`reports/content-ir-cross-pack-production-proof-2026-08-11.json`
- isolated pack dry-run：`reports/content-ir-isolated-pack-dry-run-III-2026-08-11.json`

批量验证走真实 FastAPI/TestClient API，临时 SQLite 完成后销毁；重复执行两次后，production
results 与全部新 closeout reports 的 SHA-256 字节一致。前端没有改动，因此本轮没有浏览器验收；
后端真实 API 入口验收已覆盖。

尚未生产收口的内容仍保持 compile-only/preview-only，主要是自由 choice、召唤/创建、复杂移动、
复杂持续效果、非标准多段 settlement 和需要 DM 裁定的目标/视线语义。它们没有因为 compile full
而被自动升级。
