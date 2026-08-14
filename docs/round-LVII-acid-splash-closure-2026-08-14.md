# Round LVII：Acid Splash generic runtime closure

本轮从 Round LIV 的 27 条剩余 compile-only census 中选择
`core-phb-2024:spell:d84dec64befac8db7294e0f1`（酸液飞溅 / Acid Splash）。

选择依据是现有 generic consumer 已经覆盖这条 canonical source-complete IR
的目标区域、敏捷豁免、失败伤害与戏法强化：

- `combat_engine.area_damage.v1`
- `combat_engine.damage_heal.v1`
- `spell.cantrip_scaling.v1`

验证使用临时 SQLite API，实际记录 preview → confirm → replay、重复确认幂等、
目标版本推进、独立目标 CAS 拒绝、OperationTransaction 持久化、豁免成功无伤害、
1/5/11/17 级 source-derived scaling，以及 payload drift 拒绝。

投影是 set-derived：`208 production / 27 compile-only / 111 unique compiled`
变为 `209 production / 26 compile-only / 111 unique compiled`。具体 ID 集合、
真实响应/数据库证据、loader 检查、重复/非法集合幂等和保护哈希见：

- `data/content-ir/compiled/production-runtime-results-LVII.json`
- `reports/round-LVII-acid-splash-closure-2026-08-14.json`

本轮不修改 source corpus、backend/data、持久化 campaign/character 数据、
3D/UI 或 protected test artifacts，也不 push。
