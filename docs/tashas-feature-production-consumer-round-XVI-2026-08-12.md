# Tasha Feature Production Consumer Round XVI

本轮扩展既有 `advancement_service.character_growth.v1`，收割 4 条没有未建模事件语义的
工具熟练 FeatureSpec。批次小于常规 8 条，是因为它关闭了当前剩余 compile-only 中可
诚实接入的 proficiency cluster；第五个候选 Oceanic Soul 因水下互通语义仍保持 partial。

## 真实 evidence

- Battle Smith Tool Proficiency、Armorer Tools of the Trade、Alchemist Tool Proficiency、
  Artillerist Tool Proficiency 通过真实 ContentIRRuntimeService advancement
  preview → confirm → 幂等 replay。
- 4/4 使用 typed character-growth consumer，character CAS、OperationTransaction、
  feature snapshot 和 proficiency persistence 全通过；共 5 个 proficiency grants，
  没有 feature-name/name-based dispatch。
- 正式 registry/database、campaign/character 和 source corpus 未写入；全部运行于临时
  迁移 SQLite。

## 状态与边界

- Tasha Feature：`production_full=78 / dm_assisted=2 / game_usable=80`；整包
  `compile_only=13`、`authored_typed_ir=94`、`runtime_preview_full=93`、
  `manual_authoring=314`。
- ItemSpec 分开计数仍为 `47 total / 40 compile_full / 40 isolated /
  40 registered_production_full / 40 game_usable`。
- Oceanic Soul 的寒冷抗性 clause 尚可 typed，但同一 source 还包含水下互通；因为缺少
  communication consumer，本轮没有把它错误提升为 full。Bottled Respite、Psychic
  Teleportation、Manifest Mind、Tireless、Psionic Sorcery 和两条战技继续保留各自边界。

## 证据与门禁

- Validator：`scripts/validate-tashas-feature-production-consumer-round-XVI.py`。
- Result/report/test：`data/content-ir/compiled/production-runtime-results-XVIII.json`、
  `reports/tashas-feature-production-consumer-round-XVI-2026-08-12.json`、
  `backend/tests/test_tashas_feature_production_consumer_round_XVI.py`。
- Round XVI validator 与 whole-pack migration 各运行两次且 byte-identical；Round X–XVI
  累计定向测试 22 项、backend 全量 pytest 仍需在收尾门禁确认；Ruff、compileall 和
  `git diff --check` 通过。

下一轮优先处理已有 typed IR、可由通用 consumer 诚实验证的 `Tireless` / teleport 或
其它 feature semantic cluster；不为随机表、实体、通信或 DM 裁定语义新增名称分支。
