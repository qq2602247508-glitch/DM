# 《塔莎的万事坩埚》Feature Production Consumer Round VI

日期：2026-08-12。本轮从 Round-II authored Feature IR 中选择 8 条未生产的 `combat_start` passive modifier 合同，通过真实 `ContentIRRuntimeService` feature inspection consumer，在临时迁移 SQLite 上完成 production evidence。正式 campaign、character、database、formal registry 和 source corpus 没有写入。

## 证据结果

| 层级 | 结果 | 说明 |
| --- | ---: | --- |
| selected contracts | 8 | passive modifier、sight、inspection fan-out |
| preview → confirm → replay | 8/8 | 每条均通过 actor/target CAS、事务和幂等重放 |
| typed production evidence | 8 | `data/content-ir/compiled/production-runtime-results-VIII.json` |
| typed consumer | 8/8 | `combat_engine.feature_action.v1` |
| passive registry binding | 8/8 | block feature ID 与 runtime ID 一致 |
| inspection resolution | 8/8 | typed passive block 进入 generic inspection path |
| Tasha registered production full | 52 | 44→52 |
| Tasha game usable | 54 | `registered_production_full + dm_assisted` |

## 覆盖合同

- 炼金术掌握、动力步伐、工具精通、奥法枪械：spell/passive modifier 与速度 modifier。
- 星之铠甲、星之视觉：armor/sight typed modifier。
- 粉碎者、妖冶娴都：attack-context / social-check passive modifier，并保留 typed proficiency section。

## 通用实现与边界

- 复用现有 `feature_runtime` registry、`ContentIRRuntimeService._feature_runtime` 和 `combat_engine.feature_action.v1`；没有新增 feature-name/name-based runtime branch。
- 每条 contract 都由 `combat_start` typed block 生成 inspection action，preview 断言 passive block 的 `feature_id` 绑定，confirm/replay 断言真实 production consumer。
- 所有 evidence 使用临时迁移数据库，`formal_apply=false`、`formal_registry_written=false`、`formal_database_written=false`。正式 499 职业审计保持 `328 full / 110 partial / 61 dm_only`。

Round VI validator 与 whole-pack migration 连续重跑；关键结果、报告、status layer 和 isolated runtime 文件 byte-identical。完整 backend pytest、Round VI/历史 Tasha 定向回归、compileall、变更源 Ruff、`git diff --check` 作为本轮门禁。

证据：`scripts/validate-tashas-feature-production-consumer-round-VI.py`、`reports/tashas-feature-production-consumer-round-VI-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-VIII.json`。

下一轮继续处理剩余 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 和 ItemSpec lifecycle；未经过真实 producer/consumer/persistence/CAS/replay 的合同继续停在 isolated、compile-only 或 manual boundary。
