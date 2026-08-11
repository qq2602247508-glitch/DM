# Tasha Feature Production Consumer Round XIX

本轮完成一个 character-growth core exception：把完整的 `命流之器 Implements of Mercy` 通过既有 typed character-growth consumer 跑完三条 proficiency clauses。批次只有 1 条，因为它一次关闭一个完整 Feature 的三条角色成长授予，不新增语义分支，也不是普通内容批次。

## 真实 evidence

- Feature `content.tashas-cauldron.feature.way-of-mercy.implements-of-mercy` 已确认 source completeness=complete，三条 clause 分别授予 `insight`、`medicine` 和 `herbalism_kit`。
- `feature_materializers.py` 将三条 `grant_proficiency` 物化为 typed `proficiencies` blocks；没有为武僧特性名增加 dispatch。已有 `advancement_service.character_growth.v1` 负责 preview/confirm/replay、选择与授权、角色 CAS、OperationTransaction 和 feature snapshot。
- 真实临时迁移 SQLite 上完成 preview → confirm → 幂等 replay；三条 proficiency grants 全部返回并持久化，`character_cas=true`、`transaction=true`、`feature_persisted=true`、`name_branch_count=0`。

## 覆盖变化

- Tasha whole-pack：`525 atoms / 408 player-facing / 408 executable / 95 authored typed IR / 94 compile_full / 94 runtime_preview_full / 82 production_full / 2 dm_assisted / 84 game_usable / 10 compile-only / 314 manual_authoring / 107 DM reference`。
- 当前项目：`111 unique compiled / 35 compile-only / 182 production_full`；ItemSpec 独立保持 `47 total / 40 compile / 40 isolated / 40 registered / 40 game usable`。
- 本轮为 character-growth platform-core exception，selected_count=1、source clause count=3；未把 Ambush、Oceanic Soul、Bottled Respite、Psychic Teleportation、Psionic Sorcery 或 Manifest Mind 的未建模语义顺带提升。

## 证据与门禁

- Validator：`scripts/validate-tashas-feature-production-consumer-round-XIX.py`。
- Test：`backend/tests/test_tashas_feature_production_consumer_round_XIX.py`；既有 character-growth、Feature Runtime 和全量 backend 测试回归通过。
- Result/report：`data/content-ir/compiled/production-runtime-results-XXI.json`、`reports/tashas-feature-production-consumer-round-XIX-2026-08-12.json`。
- Round XIX validator、Ruff、compileall、`git diff --check` 通过；全量 backend pytest 为 `896 passed, 1 warning`；whole-pack migration 连续运行两次，关键 report/runtime hash 保持一致。
- 正式 registry/database/campaign/character、source corpus、3D 和永久保护路径未写入。

下一轮继续剩余 typed semantic cluster 的真实 generic consumer；不把 partial/manual/DM-reference clauses 冒充 production，也不增加名称分支。
