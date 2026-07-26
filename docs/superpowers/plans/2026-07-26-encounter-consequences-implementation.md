# 情景行动驱动的遭遇后果：实施计划

**目标：** 把推进台的“难度加减一级”升级为可预览、可确认、可撤销的具体遭遇
变化，并为后续结算、交易、休息和叙事操作建立通用事务基础。

**分支：** `codex/encounter-consequences`

## 任务 1：用测试定义遭遇操作协议

文件：

- 新建 `backend/tests/test_encounter_adjustments.py`
- 新建 `backend/src/dnd_dm_assistant/domain/encounters.py`

步骤：

1. 先写失败测试，覆盖五种允许操作和非法 `kind`。
2. 测试每份草案最多 8 项、`difficulty_shift` 只能为 -1/0/1。
3. 测试 HP 非负、增援轮次至少为 1、实体类型白名单。
4. 运行单测观察 RED。
5. 实现判别联合 schema 和领域校验，运行到 GREEN。

## 任务 2：持久化通用事务与遭遇草案

文件：

- 修改 `backend/src/dnd_dm_assistant/infrastructure/database/models.py`
- 修改 `backend/src/dnd_dm_assistant/api/schemas.py`
- 新建 Alembic migration
- 修改 `backend/tests/test_migrations.py`

字段：

- `operation_transactions`：战役、类型、幂等键、状态、前后快照、原因、
  来源、版本、确认/撤销时间。
- `encounter_adjustment_proposals`：战役、场景、战斗、来源事件、标题、原因、
  难度变化、操作、反向操作、状态、时间和版本。

步骤：

1. 先扩展迁移测试预期表，确认失败。
2. 增加模型和迁移。
3. 从空库升级并断言表、索引和默认值。

## 任务 3：实现草案 CRUD 与归属校验

文件：

- 新建 `backend/src/dnd_dm_assistant/infrastructure/database/encounter_service.py`
- 新建 `backend/src/dnd_dm_assistant/api/routes/encounters.py`
- 修改 `backend/src/dnd_dm_assistant/api/app.py`
- 扩展 `backend/tests/test_encounter_adjustments.py`

接口：

- `GET /campaigns/{cid}/encounter-adjustments`
- `POST /campaigns/{cid}/encounter-adjustments`
- `PATCH /campaigns/{cid}/encounter-adjustments/{id}`
- `POST .../{id}/reject`

步骤：

1. 先测试跨战役场景、战斗、事件和实体引用被拒绝。
2. 实现只允许修改 `pending` 草案。
3. 拒绝操作幂等，版本冲突返回 409。

## 任务 4：实现确认事务

文件：

- 修改 `encounter_service.py`
- 修改 `routes/encounters.py`
- 扩展后端测试

接口：

- `POST .../{id}/apply`

步骤：

1. 先写失败测试：两项操作中第二项无效时，第一项不能落库。
2. 实现单 SQLAlchemy 事务内重新验证版本、归属和 XP 结算锁。
3. 已有战斗时修改战斗员实例/结构化增援；未创建战斗时保持已应用草案等待消费。
4. 生成并保存反向操作和审计事务。
5. 同一幂等键重复确认返回原结果，不重复应用。

## 任务 5：启动场景战斗时消费已应用草案

文件：

- 修改现有战斗创建服务和路由
- 扩展战斗服务测试

步骤：

1. 先测试同一草案只绑定第一个匹配战斗。
2. 创建战斗员后应用移除、增加、HP、状态和增援配置。
3. 写回 `combat_id`，后续同场景战斗不重复消费。

## 任务 6：实现安全撤销

文件：

- 修改 `encounter_service.py`
- 修改 `routes/encounters.py`
- 扩展后端测试

接口：

- `POST .../{id}/revert`

步骤：

1. 测试已发经验时禁止撤销。
2. 测试 HP、状态、参与者和增援均恢复。
3. 测试后续依赖导致冲突时不做部分撤销并返回具体冲突。
4. 重复撤销幂等。

## 任务 7：推进台草案编辑与确认

文件：

- 修改 `frontend/src/api/types.ts`
- 修改 `frontend/src/api/entities.ts`
- 新建 `frontend/src/ui/encounterAdjustments.ts`
- 新建对应 Vitest
- 修改 `frontend/src/pages/GameTablePage.tsx`

步骤：

1. 先测试五类操作的中文差异文案。
2. 添加列表、创建/生成、逐项启用、编辑原因、拒绝和确认 API。
3. 推进台显示“触发行动 → 建议 → 具体变化 → 难度预算变化”。
4. 未确认前不调用应用接口；确认成功后刷新场景、事件、草案和战斗数据。
5. 模型不可用时允许 DM 手动创建固定操作草案。

## 任务 8：战斗页显示、部署增援与撤销

文件：

- 修改 `frontend/src/pages/CombatPage.tsx`
- 扩展组件测试

步骤：

1. 显示已应用情景后果、来源事件和具体实际变化。
2. 到达增援轮次时显示“部署”，点击后仍需 DM 确认。
3. XP 未结算时显示“撤销最近调整”。
4. 冲突、过期引用和已结算锁显示清楚原因。

## 任务 9：AI 严格草案生成

文件：

- 修改现有 agent schema、提示词和工具路由
- 扩展 agent 后端测试

步骤：

1. 测试 AI 输出只能形成 `pending` 草案。
2. 输入当前场景、参战原子和最近推进事件，不发送无关战役内容。
3. 严格解析；只允许一次有限 JSON 修复。
4. 引用不存在时返回可编辑错误，不写数据库。
5. 保持 `qwen3:30b-instruct`、`think=false`，不下载模型。

## 任务 10：全门禁与浏览器验收

1. 运行主计划中的全部后端与前端门禁。
2. Alembic 分别对空数据库和现有本地数据库升级。
3. 启动现有桌面脚本。
4. 在推进台记录“玩家提前破坏仪式”。
5. 生成/手工建立草案：移除增援、降低首领 HP、添加失去召唤状态。
6. DM 确认后从当前场景发起战斗。
7. 战斗页验证参与者、HP、状态、增援和解释一致。
8. 撤销后验证全部恢复；再次应用不重复。
9. 更新项目记忆。
