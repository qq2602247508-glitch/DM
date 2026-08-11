# Tasha ItemSpec Production Consumer Round X

本轮只处理 ItemSpec 的真实通用 equipment consumer，不修改 3D、正式 campaign/character 数据、正式数据库或隔壁项目。

## 结果

- 选择 8 条 `compile_full` ItemSpec：虔信护符、奥法秘典、血源瓶、守护者纹章、调律者之鼓、炼金总纲、遥远国度碎晶、建筑里拉琴。
- 8/8 通过真实 FastAPI/TestClient 的 equipment create，以及 attune/equip、granted action、charge operation 的 preview → confirm → 幂等 replay；14 个 equipment operation transaction 均落在临时迁移 SQLite。
- 通用 typed consumers 覆盖 `item.equipment_modifier.v1`、`item.attunement.v1`、`item.charge_resource.v1`、`item.granted_action.v1`；守护者纹章与炼金总纲实际完成充能扣减，持久化值分别为 2。
- ItemSpec catalog 状态由 `41 compile_full / 41 isolated_runtime_validated / 0 registered_production_full` 增至 `41 / 41 / 8`；`game_usable=8`。Feature 的 Tasha status 不与 ItemSpec 计数混合，仍为 `production_full=74`、`dm_assisted=2`、`game_usable=76`。

## 边界

- 生产证据写入 `data/content-ir/compiled/production-runtime-results-XII.json`，但 `formal_apply=false`、`formal_registry_written=false`、`formal_database_written=false`；这是项目 production-runtime evidence，不是把隔离 pack 自动写入正式数据库。
- `load_item_production_evidence()` 只接受声明 `content_kind=item`、通过整批 create/preview/confirm/replay gate 的结果，并按稳定 ItemSpec ID 过滤；未知 clauses、grant spell 的下游施法和 tattoo 特殊语义继续 fail closed。
- 无 item name dispatch / name branch，状态层仍遵循 `isolated_runtime_validated → registered_production_full → game_usable` 的严格顺序。

## 验证入口

- `scripts/validate-tashas-item-production-consumer-round-X.py`
- `backend/tests/test_tashas_item_production_consumer_round_X.py`
- `reports/tashas-item-production-consumer-round-X-2026-08-12.json`
- `data/content-ir/compiled/production-runtime-results-XII.json`
