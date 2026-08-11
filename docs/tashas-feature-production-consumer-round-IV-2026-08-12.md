# 《塔莎的万事坩埚》Feature Production Consumer Round IV

日期：2026-08-12。本轮从 Round-II 的 authored Feature IR 中选择 8 条 movement / sight / choice / lifecycle 高扇出合同，通过真实 `ContentIRRuntimeService` API 和 combat turn boundary，在临时迁移 SQLite 上完成 production evidence。正式 campaign、character、database 和 source corpus 没有写入。

## 证据结果

| 层级 | 结果 | 说明 |
| --- | ---: | --- |
| selected contracts | 8 | 游泳、攀爬、飞行、盲视、选择绑定与资源生命周期 |
| preview → confirm → replay | 8/8 | 每条均通过 actor/target CAS、事务和幂等重放 |
| typed production evidence | 8 | `data/content-ir/compiled/production-runtime-results-VI.json` |
| DM-assisted evidence | 0 | 本轮没有把 DM 裁定当作自动化生产证据 |
| Tasha registered production full | 36 | 28→36；只计本轮 8 条 typed production |
| Tasha game usable | 38 | `registered_production_full + dm_assisted` |

## 覆盖合同

- `fathomless-gift-of-the-sea`：冻结 40 尺游泳速度。
- `ranger-roving`：冻结攀爬 / 游泳模式，并让速度修正进入真实回合移动预算。
- `beast-barbarian-bestial-soul`：`bestial_soul_mode=swim` 选择绑定只保留所选移动模式。
- `paladin-blind-fighting` 与 `ranger-blind-fighting`：盲视进入 `active_sight_modes` 和攻击上下文消费者。
- `genie-elemental-gift`、`swarmkeeper-writhing-tide`、`twilight-cleric-steps-of-night`：显式 bonus action 生成通用移动模式 action，真实扣减角色资源并写入限时飞行状态。

## 通用实现

- `grant_movement_mode` 支持 typed `speed_ft`、`walking_speed`、`speed_multiplier`、选择绑定与 `climb`；显式 activation 同时保留被条件门控的 registry block，并通过 `activate_movement_mode` feature action 写入短期状态。
- `grant_sight_mode` 的 typed `set` 修正进入 combat snapshot；`range_ft` / 已声明 `range_source` 经冻结后由 `active_sight_modes` 与 blindsight attack-context resolver 消费。
- 既有带相同资源键的状态激活动作会合并移动 effect，避免重复消耗或破坏既有条件生命周期；没有按 feature/class name 分支。

## 边界与门禁

所有 evidence 使用临时迁移数据库，`formal_apply=false`、`formal_registry_written=false`、`formal_database_written=false`。正式 499 职业审计保持 `328 full / 110 partial / 61 dm_only`。数据库指纹为 `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`；两个受保护未跟踪测试路径保持原指纹。

完整 `backend/.venv/bin/pytest -q backend/tests` 通过；Round IV validator 8/8 通过；迁移脚本和 Round IV validator 重跑后的关键报告 / runtime 文件 byte-identical；`git diff --check` 通过。Ruff 对变更 production source、Round IV test 和 validator 通过；仓库已有测试 import-order 噪音未做无关格式化。

证据：`scripts/validate-tashas-feature-production-consumer-round-IV.py`、`reports/tashas-feature-production-consumer-round-IV-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-VI.json`。

下一轮继续处理 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 和 ItemSpec lifecycle；未经过真实 producer/consumer/persistence/CAS/replay 的合同继续停在 isolated 或 partial。
