# 特性自动化迁移预审报告

这份报告只规划迁移，不修改运行时状态，也不把候选行直接升级为 `full`。

- 矩阵 schema：`feature-automation-migration-plan-2`
- 总条目：499
- 当前状态：`{'full': 268, 'dm_only': 74, 'partial': 157}`
- 预审状态：`{'already_full': 268, 'manual_boundary': 10, 'missing_runtime_contract': 148, 'consumer_partial': 32, 'needs_contract_review': 6, 'missing_source': 35}`

## 模板分组

| 模板 | 条目 | 已 full | 缺运行时合同 | 待合同复核 | 消费者不完整 | 人工边界 | 缺源码 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 动作经济与触发条件 (`action_trigger`) | 31 | 25 | 5 | 0 | 0 | 1 | 0 |
| 成长授予/升级选择 (`progression_grant`) | 71 | 66 | 4 | 0 | 0 | 1 | 0 |
| 命中后骑手 (`attack_rider`) | 13 | 4 | 0 | 0 | 9 | 0 | 0 |
| 光环/范围被动 (`aura_passive`) | 48 | 8 | 39 | 1 | 0 | 0 | 0 |
| 伤害/治疗 (`damage_healing`) | 48 | 26 | 21 | 1 | 0 | 0 | 0 |
| 移动/位移 (`movement`) | 15 | 3 | 12 | 0 | 0 | 0 | 0 |
| 通用被动/数值修正 (`passive_modifier`) | 79 | 31 | 12 | 0 | 0 | 1 | 35 |
| 伤害前/防御干预 (`pre_damage_intervention`) | 13 | 5 | 7 | 1 | 0 | 0 | 0 |
| 资源/恢复/频率 (`resource_lifecycle`) | 64 | 37 | 19 | 2 | 0 | 6 | 0 |
| 掷骰干预 (`roll_intervention`) | 46 | 27 | 0 | 0 | 19 | 0 | 0 |
| 施法框架/法术修改 (`spell_capability`) | 7 | 3 | 0 | 0 | 4 | 0 | 0 |
| 状态生命周期 (`state_lifecycle`) | 34 | 19 | 14 | 1 | 0 | 0 | 0 |
| 召唤/伙伴 (`summon_lifecycle`) | 12 | 7 | 5 | 0 | 0 | 0 | 0 |
| 目标/范围/豁免组合 (`target_save_status`) | 10 | 4 | 5 | 0 | 0 | 1 | 0 |
| 0 HP/死亡生命周期 (`zero_hp_intervention`) | 8 | 3 | 5 | 0 | 0 | 0 | 0 |

## 能力簇

| 能力簇 | 总数 | full | 非 full | 本轮可直接迁移 | producer | consumer | 新 UI | 新持久化 |
|---|---:|---:|---:|---:|:---:|:---:|:---:|:---:|
| passive_modifier | 79 | 31 | 48 | 0 | 是 | 是 | 是 | 否 |
| aura_passive | 48 | 8 | 40 | 0 | 是 | 是 | 是 | 是 |
| resource_lifecycle | 64 | 37 | 27 | 0 | 是 | 是 | 是 | 是 |
| damage_healing | 48 | 26 | 22 | 0 | 是 | 是 | 是 | 是 |
| roll_intervention | 46 | 27 | 19 | 0 | 是 | 是 | 是 | 是 |
| state_lifecycle | 34 | 19 | 15 | 0 | 是 | 是 | 是 | 是 |
| movement | 15 | 3 | 12 | 0 | 是 | 是 | 是 | 是 |
| attack_rider | 13 | 4 | 9 | 0 | 是 | 是 | 是 | 是 |
| pre_damage_intervention | 13 | 5 | 8 | 0 | 是 | 是 | 是 | 是 |
| action_trigger | 31 | 25 | 6 | 0 | 是 | 是 | 是 | 否 |
| target_save_status | 10 | 4 | 6 | 0 | 是 | 是 | 是 | 是 |
| summon_lifecycle | 12 | 7 | 5 | 0 | 是 | 是 | 是 | 是 |
| zero_hp_intervention | 8 | 3 | 5 | 0 | 是 | 是 | 是 | 是 |
| advancement_asset_grant:fighting_style | 4 | 0 | 4 | 0 | 是 | 是 | 是 | 否 |
| spell_capability | 7 | 3 | 4 | 0 | 是 | 是 | 是 | 是 |
| progression_grant | 55 | 54 | 1 | 0 | 是 | 是 | 是 | 否 |
| advancement_asset_grant:epic_boon | 12 | 12 | 0 | 0 | 是 | 是 | 否 | 否 |

## 预审结论

- `missing_runtime_contract`：源码命中积木，但还没有真实运行时合同；不能仅靠字段改成 `full`。
- `needs_contract_review`：已有部分运行时结构，但仍需逐字段核对消费者、输入、资源和幂等。
- `consumer_partial`：执行器存在，但生产接线或安全闭环未完成。
- `manual_boundary`：包含选择、DM裁定或开放叙事，不能强行无人值守。
- 只有完成真实配置、消费者、状态写入、输入链和测试后，才允许从本报告中产生 `full` 增量。

## 下一批执行门槛

下一批必须从一个模板中选择一组条目，先生成配置和定向测试，再跑499条审计。预审数字是候选分组，不是承诺的新增 `full` 数量。
