# Tasha ItemSpec Production Consumer Round XII

本轮补齐通用 `item.attunement.v1` 对 typed `tattoo_lifecycle` 的真实状态消费。

## 实现

- `equipment_preview/confirm` 读取 ItemSpec 的 `tattoo_lifecycle` clause，不读取物品名称；同调确认生成 `item_tattoo_lifecycle` metadata：`phase=manifested`、`needle_state=ink`、`effects_active=true`。
- 解除同调确认生成 `phase=needle_returned`、`needle_state=needle`、`effects_active=false`，并将同一 typed transition 写入 operation snapshot；角色/Equipment version 与 OperationTransaction 继续走既有 CAS/幂等边界。
- 未具备完整 typed lifecycle 参数的条目 fail closed；本轮无 name dispatch。

## 真实 evidence

- 8 条完整刺青通过临时迁移 SQLite 的 create → attune preview/confirm/replay → action/charge（如适用）→ unattune preview/confirm/replay。
- 8/8 的 `manifested → needle_returned` transition、最终 metadata、Attunement ended 状态、character CAS 和 replay 通过；共 21 个 equipment operation transaction，2 条充能生命周期实际扣减。
- ItemSpec 状态：`47 total / 37 compile_full / 37 isolated_runtime_validated / 24 registered_production_full / 24 game_usable`；Feature status 仍独立为 `74 production_full / 2 dm_assisted / 76 game_usable`。

## 边界与证据

- `formal_apply=false`、`formal_registry_written=false`、`formal_database_written=false`；正式 campaign/character/database 未写入。
- 证据：`reports/tashas-item-production-consumer-round-XII-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-XIV.json`。
- Validator/test：`scripts/validate-tashas-item-production-consumer-round-XII.py`、`backend/tests/test_tashas_item_production_consumer_round_XII.py`；共享 harness 同时支持 tattoo roundtrip。
