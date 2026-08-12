# Round XXIX：野火/守望/荣耀三张恒备法术表 Character-Growth Consumer

本轮继续沿用 Round XXVIII 的名称无关 `advancement_service.character_growth.v1` +
`advancement_service.spell_registry` consumer，关闭三个 source-complete 恒备法术表：

- `content.tashas-cauldron.round2.feature.wildfire-druid-circle-spells`（野火结社，德鲁伊 2 级）
- `content.tashas-cauldron.round2.feature.watchers-paladin-oath-spells`（守望之誓，圣武士 3 级）
- `content.tashas-cauldron.round2.feature.glory-paladin-oath-spells`（荣耀之誓，圣武士 3 级）

## 语义与 source-complete 复核

- 每个特性是单条 `always-prepared` 子句，效果为 10 个 `grant_spell`
  （德鲁伊 `wisdom`/`druid`，圣武士 `charisma`/`paladin`），与既有恒备法术表
  `alchemist-spell-list`、Round XXVIII 领域法术表同一条消费者路径，未新增 dispatch 分支。
- 法术 slug 逐一对照 `玩家手册 2014` spell corpus 英文别名（如 `burning_hands`、
  `mass_cure_wounds`、`counterspell`、`nondetection`、`guiding_bolt`、
  `freedom_of_movement` 等），三张法术表互不重叠。
- `source_completeness=complete`、`unmodeled_source_terms=[]`；source record/path/
  fingerprint、reviewed fields、manual decisions 与 source evidence 全部保留。

## 真实闭环

- 每个特性经 `materialize_runtime_definition` 投影为单个 `advancement` block
  （`operator=grant_spell`、`spells` 恰为 10 条），消费到 `advancement_service.spell_registry`。
- `ContentIRRuntimeService` 真实走 `content_kind=advancement` 的 preview→confirm→replay：
  `advancement_block_ready`、character CAS、OperationTransaction、feature 持久化、
  `spell_grant_count=10` 全通过；consumer 恒为 `advancement_service.character_growth.v1`。

## 实际净增

- Tasha：`production_full 93→96`、`game_usable 95→98`、`manual_authoring 311→308`、
  `authored_typed_ir 98→101`、`compile_full 97→100`、`runtime_preview_full 97→100`；
  `compile_only` 保持 2。
- 项目：`production_full 193→196`、`compile_only 35`、`unique compiled 111`。

## 证据

- `scripts/author-round-XXIX-spell-lists.py`（确定性重建工具）
- `scripts/validate-tashas-feature-production-consumer-round-XXIX.py`
- `backend/tests/test_tashas_feature_production_consumer_round_XXIX.py`
- `reports/tashas-feature-production-consumer-round-XXIX-2026-08-13.json`
- `data/content-ir/compiled/production-runtime-results-XXX.json`

## 保护与边界

- 正式 database、formal registry、source corpus、campaign/character、3D 与两个永久保护路径
  未写入；`name_branch_count=0`；`formal_registry_written=False`、`formal_database_written=False`。
- 保护指纹保持：database `f3abdcf57b0d71888f085ca081511df4f4e23f100066b402d49d769089fa6aad`、
  formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、
  integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、
  ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。

## 下一轮

- 剩余 compile-only：`genie-bottled-respite`（vessel / 异次元空间）、
  `scribe-manifest-mind`（spectral-object entity lifecycle + remote spell origin）。
- 恒备法术表 seam 已批量复用；下一轮可继续收编孢子结社（含戏法颤栗之触的混合列表）、
  巨灵宗主扩展法术（warlock 列表扩展语义）、战地匠师/装甲师/魔炮师法术，或转向单一
  抗性/移动/视觉类特性；不迁移下一本扩展包、不触碰 3D。
