# 《塔莎的万事坩埚》Round XXVI：Ambush 通用先攻/掷骰干预消费者

当前状态：`accepted`；全量门禁、分离提交和 push 已完成。

## 本轮交付

本轮选取战斗大师战技「伏击」作为第一个同时具备两个真实触发分支的 Feature generic consumer：

- `content.tashas-cauldron.feature.battle-master.ambush`
- source record：`12139219bf7e575f9cde019c`
- source path：`塔莎的万事坩埚/玩家选项/职业/战士（TCE）/战技选项.htm`

此前 IR 只表达先攻分支，遗漏敏捷（隐匿）分支，因此不能称为 source-complete。本轮保留并验证两个 typed clauses：

| Clause | 触发 | 资格 | 效果 |
|---|---|---|---|
| `ambush:initiative` | 先攻检定 | `initiative` | 玩家可消耗一枚 `superiority_dice`，加入玩家报告的 superiority die 结果 |
| `ambush:stealth` | 敏捷（隐匿）检定 | `ability_check` / `skill_check`、Dexterity、Stealth | 玩家可消耗一枚 `superiority_dice`，加入玩家报告的 superiority die 结果 |

两个分支均保留角色失能时不可用的 typed eligibility，不依赖 feature 名称 dispatch。

## 实现边界

- `backend/src/dnd_dm_assistant/application/feature_materializers.py`：名称无关的 `roll_intervention` materializer，支持 ability check、attack declaration、initiative roll、typed die source、skill/ability/initiative eligibility。
- `backend/src/dnd_dm_assistant/application/content_ir_production_registry.py`：新增通用 `combat_engine.roll_intervention.v1`，声明 transaction boundary、character resource CAS、combatant CAS、snapshot effects 和 idempotency scope。
- `backend/src/dnd_dm_assistant/api/schemas.py`：新增 `InitiativeRollConfirmationCommand`。
- `backend/src/dnd_dm_assistant/api/routes/world.py`：新增 initiative intervention confirm endpoint。
- `backend/src/dnd_dm_assistant/infrastructure/database/world_service.py`：start-combat 持久化冻结先攻与 intervention contract；confirm 支持资源 CAS、拒绝、回放和 transaction。
- `data/content-ir/authored/official-packs/tashas-cauldron/features/features/content-tashas-cauldron-feature-battle-master-ambush.json`：补齐两个 source-complete clauses。

## 真实隔离运行证据

Round XXVI validator 在临时 SQLite 和隔离 HTTP campaign 上通过：

- Typed IR load、compile full、runtime materialization。
- 先攻结果冻结后建立持久化 `CombatAction(action_type="initiative_roll_prompt")`。
- 玩家确认 superiority die `7` 后，先攻 `13 → 20`，资源 `superiority_dice 4 → 3`。
- `CombatAction` 变为 `confirmed`，`OperationTransaction` 变为 `applied`。
- 相同 request replay 返回相同 resolution，不重复扣资源。
- 拒绝 intervention 保留原先攻结果且资源不变。
- 隐匿分支通过同一个 `combat_engine.roll_intervention.v1` consumer 打开窗口。
- `name_branch_count=0`，正式 database、formal registry、campaign 和 character 未写入。

证据入口：

- `scripts/validate-tashas-feature-production-consumer-round-XXVI.py`
- `backend/tests/test_tashas_feature_production_consumer_round_XXVI.py`
- `reports/tashas-feature-production-consumer-round-XXVI-2026-08-12.json`
- `data/content-ir/compiled/production-runtime-results-XXVII.json`

## 整包计数

相对 Round XXV 当前报告：

| 指标 | Round XXV | Round XXVI |
|---|---:|---:|
| Source records | 144 | 144 |
| Content Atoms | 525 | 525 |
| 玩家向 executable | 408 | 408 |
| Authored Typed IR（conversion projection） | 95 | 95 |
| Compile Full | 94 | 94 |
| Runtime Preview Full | 94 | 94 |
| Production Full | 88 | 89 |
| DM-assisted | 2 | 2 |
| Game Usable | 90 | 91 |
| Compile-only | 4 | 3 |
| Manual Authoring | 314 | 314 |
| DM Reference | 107 | 107 |

当前 `build_migration()` 的 status-layer projection 中 `authored_typed_ir=94`，而 conversion/content-ID projection 为 `95`；这是现有系统保留的两个口径，不能在报告中合并成一个数字。当前 content-ID funnel 仍满足 `95 = 90 + 2 + 3`。

ItemSpec 保持 `47 total / 40 compile full / 40 isolated runtime validated / 40 registered production full / 40 game usable`。

角色成长总体状态仍为 `bounded_partial`。本轮只关闭一个真实通用掷骰干预消费者，不宣称《塔莎》整包迁移完成，也不宣称全量角色成长闭环完成。

## 保护指纹

- database：`f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`
- formal registry：`f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`
- `backend/tests/integrations/` manifest：`ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`
- `backend/tests/ollama.py`：`8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`

下一步继续已有 source-complete typed contract 的 generic consumer；Oceanic Soul 通信、Bottled Respite vessel、Manifest Mind spectral object、Psychic Teleportation destination、Psionic Sorcery payment、更多 entity lifecycle、Tireless 以外的成长语义和大量 manual atoms 继续 fail-closed。
