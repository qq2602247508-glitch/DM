# 《塔莎的万事坩埚》Feature Production Consumer Round III

日期：2026-08-12。Round 3 在 Round 2 的 58 条 isolated full Feature contract 中，选择 12 条已有通用 combat/content consumer 的候选，通过真实 `ContentIRRuntimeService` API 在临时迁移 SQLite 上完成证据收割。正式 campaign、character、database 和 source corpus 没有写入。

## 证据结果

| 层级 | 结果 | 说明 |
| --- | ---: | --- |
| selected contracts | 12 | attack rider、authorized information、condition lifecycle、timed modifier、reaction action |
| preview → confirm → replay | 12/12 | 每条均通过 CAS、事务和幂等重放 |
| typed production evidence | 11 | `production-runtime-results-V.json` |
| DM-assisted evidence | 1 | 辉煌防御；DM-confirmed typed reaction，真实消费 reaction resource |
| Tasha registered production full | 28 | 17→28；只计 11 条 typed production |
| Tasha DM-assisted | 2 | 1→2；只计 1 条 Round 3 DM continuation |
| Tasha game usable | 30 | `registered_production_full + dm_assisted` |

新增通用运行时合同包括：有 `attack_hit=true` execution intent 时优先选择同一 Feature 的 attack rider；typed timed modifier 解析 superiority die 与 ability modifier 输入；AC timed modifier；`_or_` 条件移除选项展开；DM-confirmed reaction 通过明确 trigger 和 reaction resource CAS。

## 边界

所有 evidence 使用临时迁移数据库，报告仍标记 `formal_apply=false`、`formal_registry_written=false`、`formal_database_written=false`。因此它们证明的是 production consumer contract 已通过真实 API，而不是把隔离 campaign/character 数据写入用户环境。正式 499 职业审计保持 328 full / 110 partial / 61 dm_only；没有 feature-name/name-based dispatch。

尚未收割的 Feature contract 继续保留为 compile/isolated 层，尤其是 vessel/entity lifecycle、exhaustion timing、spectral object lifecycle、teleport destination、psionic component/payment、reaction window family 等需要更完整事件链的语义。

证据：`scripts/validate-tashas-feature-production-consumer-round-III.py`、`reports/tashas-feature-production-consumer-round-III-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-V.json`。
