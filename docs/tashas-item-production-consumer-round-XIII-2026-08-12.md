# Tasha ItemSpec Production Consumer Round XIII

本轮继续沿用通用 `ItemSpec` equipment consumer，新增 8 条完整物品的真实生产 evidence。

## 覆盖批次

- 月镰、自然护符、巴巴·雅加的魔法扫帚、星界碎片。
- 重复手稿、爆裂论文、防护诗篇、狂欢者风笛。
- 8 条均为 `compile_full`，没有为 unresolved action/effect clause 添加名称分支或
  fallback。

## 真实运行时闭环

- 通过临时迁移 SQLite 的 equipment create → attunement/equip → granted action 或
  charge operation → preview → confirm → idempotent replay。
- `item.equipment_modifier.v1`、`item.attunement.v1`、`item.granted_action.v1` 和
  `item.charge_resource.v1` 由 typed clauses 驱动；4 条 charge lifecycle、17 个
  operation transactions、character CAS、item state snapshot 均通过。
- 8/8 create/preview/confirm/replay、typed consumer、item state、attunement CAS 和
  production runtime full 通过；`name_branch_count=0`。

## 状态与边界

- ItemSpec：`47 total / 37 compile_full / 37 isolated_runtime_validated /
  32 registered_production_full / 32 game_usable`。
- 本轮使项目 `current_project_production_full` 从 158 增至 166；Tasha Feature 独立
  维持 `74 production_full / 2 dm_assisted / 76 game_usable`。
- formal registry/database、正式 campaign/character 和 source corpus 均未写入；证据
  只回填 isolated pack 的 production evidence，正式 registry 指纹保持不变。

## 证据与门禁

- Validator：`scripts/validate-tashas-item-production-consumer-round-XIII.py`。
- Result：`data/content-ir/compiled/production-runtime-results-XV.json`。
- Report：`reports/tashas-item-production-consumer-round-XIII-2026-08-12.json`。
- 测试：`backend/tests/test_tashas_item_production_consumer_round_XIII.py`，并更新
  Round X/XI/XII 的累计 evidence 断言。
- Round XIII validator 与 whole-pack migration 各运行两次，输出 byte-identical；
  targeted Tasha tests 19 项、backend 全量 pytest 888 项通过；Ruff、compileall 和
  `git diff --check` 通过。

下一轮继续处理剩余 5 条完整 ItemSpec；当前 ItemSpec production 已超过整包 60% 的
production gate，但 `32/47` 尚未达到 75% 的 game-usable gate，因此不能提前收口。
