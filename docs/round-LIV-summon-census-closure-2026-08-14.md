# Round LIV：compile-only census 与召唤簇 closure

日期：2026-08-14  
基线：`46eb58ee3bbd4dc96050a48f0b7fd562fa3946e4`。

## 决策

权威项目 census 在移除当前 generic production evidence 后剩余 30 条
compile-only。最高置信度簇是：

- `tashas-cauldron:spell:54c8c29188db1442473d9dc1`：野兽召唤术；
- `tashas-cauldron:spell:083419d9de551806a5ca9748`：亡灵召唤术。

两条均为 source-complete、四条 typed clause，并共享既有名称无关
`spell.summon.v1`。Round XXIV 已有真实临时 SQLite 的 preview/confirm/replay、
位置占用拒绝、stat block/HP/AC scaling、共享先攻、默认行为、专注/源生命周期、
spell-slot rollback、CAS 与持久化交易证据；本轮只按当前 production evidence
loader 契约重新登记这份真实证据。

其余 28 条在报告 census 中按精确 source-bound shape 分组；它们保留各自的
视觉移动/调查、伤害/豁免、条件生命周期、标记转移、区域/仪式、检测/防御、
讯息/移动等 blocker，未因相似名称或计数而提升。

## 结果

通用 set projection：`208 production / 30 compile-only / 111 unique compiled`
→ `208 production / 28 compile-only / 111 unique compiled`。

这不是重复的 `+2 production`：两条 ID 已在历史 generic production union 中；
本轮把它们重新登记为当前 required-check artifact，使严格 compile-only census
诚实减少 2 条，同时 production set 保持幂等不变。

Evidence artifact：
`data/content-ir/compiled/production-runtime-results-LIV.json`

Validator/report：
`scripts/validate-round-LIV-summon-census-closure.py`、
`reports/round-LIV-summon-census-closure-2026-08-14.json`

Focused tests：
`backend/tests/test_round_LIV_summon_census_closure.py`

未写 formal registry/database、source corpus、backend/data、campaign/character 或
3D/UI；未修改保护路径；不 push。
