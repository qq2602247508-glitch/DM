# Tasha ItemSpec Production Consumer Round XIV

本轮关闭当前 47 条 ItemSpec inventory 中剩余的 5 条 `compile_full` / isolated full
条目。批次小于常规 8 条，是因为这 5 条已经是全部剩余完整合同；本轮同时验证了通用
tattoo lifecycle 与 dawn world-time recovery boundary，没有用名称分支降低语义门槛。

## 覆盖批次

- 堕影冥界碎晶、伪装刺青、堕影冥界印记刺青、重生坩埚、凝晶年纪。
- 5/5 均通过 equipment create → attunement/equip → granted action 或 charge →
  preview → confirm → idempotent replay。
- 2 条魔法刺青通过 `manifested/ink → needle_returned/needle` lifecycle；凝晶年纪的
  typed `recovery_trigger=dawn` 保留为世界时间事件，不被 rest consumer 当成长休。

## 真实 evidence

- 5/5 create/preview/confirm/replay、typed consumer、item state、attunement CAS 和
  operation transaction 通过，共 12 个 equipment operation transactions、1 条 charge
  lifecycle，`name_branch_count=0`。
- 真实 `RestService._item_charge_recovery()` boundary probe 证明 dawn charge 在
  `effective_type=long` 时不被恢复；typed Chronicle metadata 仍为 `dawn`。
- formal registry/database 未写入，evidence 仅进入 isolated pack production result。

## 状态与证据

- ItemSpec：`47 total / 37 compile_full / 37 isolated_runtime_validated /
  37 registered_production_full / 37 game_usable`。
- 项目 `current_project_production_full` 从 166 增至 171；Tasha Feature 独立维持
  `74 production_full / 2 dm_assisted / 76 game_usable`。
- Validator：`scripts/validate-tashas-item-production-consumer-round-XIV.py`。
- Result：`data/content-ir/compiled/production-runtime-results-XVI.json`。
- Report/test：`reports/tashas-item-production-consumer-round-XIV-2026-08-12.json`、
  `backend/tests/test_tashas_item_production_consumer_round_XIV.py`。
- Round XIV validator 与 whole-pack migration 各运行两次且 byte-identical；Round X–XIV
  定向测试 20 项、backend 全量 pytest 889 项、Ruff、compileall、`git diff --check`
  通过。

当前完整 ItemSpec 已全部通过 production/game-usable 层；后续不再为 partial/DM-only
条目补假 evidence，而是进入剩余 unresolved clauses 的逐字段语义解锁和整体 pack gate
复核。
