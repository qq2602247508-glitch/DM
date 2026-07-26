# 战斗规则核心实施计划

**目标：** 把当前手工修改 HP/字符串状态的战斗辅助升级为可解释、可预览、
可确认、可审计的 D&D 5e 2024 战斗事务，同时保留 DM 最终裁定权。

**分支：** `codex/combat-engine-core`

## 任务 1：纯规则伤害结算器

文件：

- 新建 `backend/src/dnd_dm_assistant/domain/combat.py`
- 新建 `backend/tests/test_combat_rules.py`

先写失败测试：

- 临时生命先吸收伤害。
- 抗性减半并向下取整。
- 易伤翻倍。
- 免疫归零。
- 抗性与易伤同时存在时互相抵消。
- 治疗不超过当前有效最大生命。
- 最大生命下降会压低当前生命。

实现纯函数，只返回结算预览，不写数据库。

## 任务 2：战斗实例字段与迁移

文件：

- 修改 `infrastructure/database/models.py`
- 修改 `api/schemas.py`
- 新建 Alembic migration
- 修改 `tests/test_migrations.py`

`combatants` 新增：

- `temporary_hp`
- `max_hp_reduction`
- `damage_resistances`
- `damage_vulnerabilities`
- `damage_immunities`
- `condition_immunities`
- `concentration`
- `reaction_available`
- `action_state`

约束：

- 临时生命和最大生命下降非负。
- 当前 HP 不超过 `max_hp - max_hp_reduction`。
- `action_state` 只保存当前回合动作/附赠动作/移动使用情况。

新增：

- `combat_actions`
- `combat_effects`
- `death_saves`
- `combat_reinforcements`

## 任务 3：战斗动作预览与确认事务

接口：

- `POST /campaigns/{cid}/combats/{combat_id}/actions/preview`
- `POST /campaigns/{cid}/combats/{combat_id}/actions/confirm`
- `GET /campaigns/{cid}/combats/{combat_id}/actions`

支持动作：

- 伤害
- 治疗
- 临时生命
- 添加/移除状态
- 恢复反应
- 消耗动作/附赠动作/移动

确认时：

- 校验战斗、行动者、目标属于同一战役。
- 使用幂等键与版本。
- 一次事务写战斗员、动作日志和审计。
- 返回逐步计算解释。

## 任务 4：状态、持续时间与专注

- `combat_effects` 保存来源、目标、开始轮次、持续单位、结束轮次和专注关联。
- 新专注确认后，旧专注及其派生效果进入待结束预览。
- 受到伤害后生成专注检定提示：DC 为 10 与一半伤害中的较高值。
- DM 输入最终检定；失败后确认移除专注相关效果。
- 回合推进时只生成到期提示，不静默删除。

## 任务 5：死亡豁免

- HP 降到 0 后显示濒死状态。
- 记录成功/失败次数、自然 1/20 和稳定。
- 受到近战重击等自动失败由 DM 确认。
- 三次成功稳定、三次失败死亡；死亡为高影响状态，最终确认。
- 获得治疗后重置死亡豁免。

## 任务 6：回合动作经济

- 每个战斗员每回合拥有动作、附赠动作、反应和移动额度。
- “下一回合”事务结束当前回合效果、开始新回合效果并恢复对应资源。
- 先攻同值继续由 DM 可调整顺序。
- 借机攻击只给出反应与距离提示，不自动决定触发。

## 任务 7：增援与阶段事件

- 把第一批 JSON 增援迁移为 `combat_reinforcements` 实体。
- 到目标轮次显示部署提醒。
- DM 确认后按数量创建战斗员实例并记录先攻方式。
- 重复部署幂等。

## 任务 8：前端战斗事务界面

- 战斗员卡显示 AC、当前/最大/临时 HP、抗性/免疫、状态、专注和动作资源。
- “伤害”先选伤害类型并显示计算预览，再确认。
- 状态显示中文名称、来源和剩余时间。
- 0 HP 时切换为死亡豁免面板。
- 战斗日志显示掷骰、公式、调整、最终结果和 DM 覆盖。
- 情景后果与普通战斗动作使用不同视觉标签。

## 任务 9：结算回写

- 战斗结束只冻结新回合推进，不自动发经验。
- 结算预览包含角色 HP、状态、资源、死亡、战利品和 XP。
- DM 可逐项选择哪些状态回写角色原子。
- 一次确认完成全部回写；重复确认不重复。

## 任务 10：质量门禁

- 纯规则金样。
- API 跨战役、幂等、版本冲突、事务回滚。
- Alembic 空库和现有库升级。
- Ruff、严格 Mypy、全量 Pytest。
- ESLint、TypeScript、全量 Vitest、Vite build。
- 浏览器走通伤害预览 → 确认 → 专注提示 → 0 HP → 死亡豁免 → 结算。
