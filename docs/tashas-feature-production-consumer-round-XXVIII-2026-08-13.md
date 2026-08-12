# Round XXVIII：三张牧师领域法术表 Character-Growth Consumer

本轮关闭三个 source-complete 牧师领域法术表特性，全部走既有的名称无关
`advancement_service.character_growth.v1` + `advancement_service.spell_registry` consumer：

- `content.tashas-cauldron.round2.feature.order-cleric-domain-spells`（秩序领域，1 级）
- `content.tashas-cauldron.round2.feature.peace-cleric-domain-spells`（和平领域，1 级）
- `content.tashas-cauldron.round2.feature.twilight-cleric-domain-spells`（暮光领域，1 级）

## 语义与 source-complete 复核

- 每个特性是单条 `always-prepared` 子句，效果为 10 个 `grant_spell`
  （`source_class=cleric`、`casting_ability=wisdom`、`grant_mode=always_prepared`），
  与奇械师 `alchemist-spell-list` 的既有消费者路径一致，未新增任何 dispatch 分支。
- 法术 slug 逐一对照 `玩家手册 2014` spell corpus 的英文别名（如
  `command`、`hold_person`、`mass_healing_word`、`otilukes_resilient_sphere`、
  `rarys_telepathic_bond`、`leomunds_tiny_hut`），三张法术表互不重叠。
- `source_completeness=complete`、`unmodeled_source_terms=[]`；source record/path/
  fingerprint、reviewed fields、manual decisions 与 source evidence 全部保留。

## 真实闭环

- 每个特性经 `materialize_runtime_definition` 投影为单个 `advancement` block
  （`operator=grant_spell`、`spells` 恰为 10 条），消费到
  `advancement_service.spell_registry`，persistence 为 `character.spells`。
- `ContentIRRuntimeService` 真实走 `content_kind=advancement` 的
  preview→confirm→replay：`advancement_block_ready`、character CAS
  （`character_version_after == version+1`）、OperationTransaction、feature 持久化、
  `spell_grant_count=10` 全通过；consumer 恒为
  `advancement_service.character_growth.v1`。

## 实际净增

- Tasha：`production_full 90→93`、`game_usable 92→95`、`manual_authoring 314→311`、
  `authored_typed_ir 95→98`、`compile_full 94→97`、`runtime_preview_full 94→97`；
  `compile_only` 保持 2（本轮新增的三个直接进入 production）。
- 项目：`production_full 190→193`、`compile_only 35`、`unique compiled 111`。

## 证据

- `scripts/author-round-XXVIII-cleric-domain-spells.py`（确定性重建工具）
- `scripts/validate-tashas-feature-production-consumer-round-XXVIII.py`
- `backend/tests/test_tashas_feature_production_consumer_round_XXVIII.py`
- `reports/tashas-feature-production-consumer-round-XXVIII-2026-08-13.json`
- `data/content-ir/compiled/production-runtime-results-XXIX.json`

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
- 继续推进剩余 manual/compile-only 关闭；character-growth seam（proficiency/language/spell）
  已复用，下一步可继续收编其余领域法术表（巨灵宗主扩展法术、野火/孢子结社法术、
  圣誓法术）或转向单一抗性/移动/视觉类特性，不迁移下一本扩展包、不触碰 3D。
