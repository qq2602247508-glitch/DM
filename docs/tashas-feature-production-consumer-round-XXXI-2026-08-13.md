# Round XXXI：孢子结社法术（已知戏法 + 八条恒备法术）Character-Growth Consumer

本轮沿用名称无关 `advancement_service.character_growth.v1` +
`advancement_service.spell_registry` consumer，关闭一个 source-complete 德鲁伊孢子结社
结社法术特性，这是本批首个「双子句」法术授予：

- `content.tashas-cauldron.round2.feature.spores-druid-circle-spells`（孢子结社，德鲁伊 2 级）

## 语义与 source-complete 复核

- 该特性含两条 advancement 子句：`known-cantrip`（在 2 级习得戏法 `chill_touch`，`grant_mode=known`）
  与 `always-prepared`（在 3/5/7/9 级获得八条结社法术并恒备，`grant_mode=always_prepared`）。
  每条子句的 `source_excerpt`、`source_fragment=11`、`source_record_id=54721f3b2404977bbc9d3e53`、
  `source_path=塔莎的万事坩埚/玩家选项/职业/德鲁伊（TCE）/孢子结社.html` 与 `source_fingerprint`
  全部保留。
- 八条恒备法术 slug 逐一对照 `玩家手册 2014` spell corpus 英文别名（`blindness_deafness`、
  `gentle_repose`、`animate_dead`、`gaseous_form`、`blight`、`confusion`、`cloudkill`、
  `contagion`）；戏法为 `chill_touch`。九条法术互不重叠。
- `source_completeness=complete`、`unmodeled_source_terms=[]`；reviewed fields、manual decisions
  与 source evidence 全部保留。未新增 dispatch 分支，复用既有 spell_registry consumer。

## 双子句合并语义

- `materialize_runtime_definition` 将两条 `advancement` block 合并为一个 envelope：顶层
  `spells` 恰为 9 条；由于两条子句的 `grant_mode` 不同（`known` vs `always_prepared`），顶层
  `grant_mode` 被有意移除，但每个 grant 在 `spell_grants` 内保留各自的 `grant_mode`（1 条
  `known` + 8 条 `always_prepared`），consumer 按 grant 级元数据正确解析。
- `ContentIRRuntimeService` 真实走 `content_kind=advancement` 的 preview→confirm→replay：
  `advancement_block_ready`、character CAS、OperationTransaction、feature 持久化、
  `spell_grant_count=9` 全通过；consumer 恒为 `advancement_service.character_growth.v1`。

## 实际净增

- Tasha：`production_full 99→100`、`game_usable 101→102`、`manual_authoring 305→304`、
  `authored_typed_ir 104→105`、`compile_full 103→104`、`runtime_preview_full 103→104`；
  `compile_only` 保持 2。
- 项目：`production_full 199→200`、`compile_only 35`、`unique compiled 111`。

## 证据

- `scripts/validate-tashas-feature-production-consumer-round-XXXI.py`
- `backend/tests/test_tashas_feature_production_consumer_round_XXXI.py`
- `reports/tashas-feature-production-consumer-round-XXXI-2026-08-13.json`
- `data/content-ir/compiled/production-runtime-results-XXXII.json`

## 保护与边界

- 正式 database、formal registry、source corpus、campaign/character、3D 与两个永久保护路径
  未写入；`name_branch_count=0`；`formal_registry_written=False`、`formal_database_written=False`。
- 保护指纹保持：database `f3abdcf57b0d71888f085ca081511df4f4e23f100066b402d49d769089fa6aad`、
  formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、
  integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、
  ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。

## 下一轮

- 恒备法术表 seam 已批量收口。剩余法术表候选：巨灵宗主扩展法术（warlock「扩展列表」选择语义，
  非恒备，需先复核 corpus/contract 再决定 `grant_mode=known` 的写法）。
- 仍剩 compile-only：`genie-bottled-respite`（vessel/异次元空间）、`scribe-manifest-mind`
  （spectral-object 实体生命周期 + 远程施法原点）；也可转向单一抗性/移动/视觉类特性；
  不迁移下一本扩展包、不触碰 3D。
