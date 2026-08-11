# Tasha Feature Production Consumer Round XVII

本轮完成一个平台核心增长：把 typed `remove_condition` 的短休/长休状态效果接入通用 rest consumer。批次只有 1 条，因为这是关闭既有 `RestService` name-dispatch seam 的核心消费者修复，不是把单条内容冒充普通批量迁移。

## 真实 evidence

- `content.tashas-cauldron.round2.feature.ranger-tireless` 的源 clause 已完成真实内容复核：短休完成时自身 `exhaustion` 降低 1 级，source completeness 从 incomplete 收紧为 complete，仍保留 source excerpt、source fingerprint 和 authored provenance。
- `remove_condition` operator contract 支持 rest trigger；编译器对 rest 场景只接受自身 `exhaustion`，其它 condition fail closed。materializer 产出 `rest_condition_effect`，携带 `trigger=short_rest_completed`、`rest=short_rest`、`condition=exhaustion`、`effect_kind=reduce_condition_level`、`amount=1`。
- `RestService` 按 typed trigger/condition 消费，兼容旧 registry 中任意 action 的 `rest_effects`，不再读取 `actions["tireless"]`；本轮没有新增 feature-name/name-based dispatch。
- 真实临时迁移 SQLite 上完成 preview → confirm → 幂等 replay；短休 preview 将力竭 3 降至 2，confirm 持久化 condition、character version CAS 和 OperationTransaction，replay 返回相同 `rest_record_id`。

## 状态与边界

- Tasha Feature：`production_full=79 / dm_assisted=2 / game_usable=81`；`compile_only=12`、`authored_typed_ir=94`、`runtime_preview_full=93`、`manual_authoring=314`。
- 当前项目 production full：`179`；ItemSpec 独立保持 `47 total / 40 compile_full / 40 isolated / 40 registered_production_full / 40 game_usable`。
- Tireless 已从 compile-only 解锁；Oceanic Soul、Bottled Respite、Psychic Teleportation、Manifest Mind、Psionic Sorcery、Ambush/Commanding Presence 等仍因 communication/entity/teleport/payment/check-window 等缺少通用 consumer 而保留边界。剩余 7 条 partial ItemSpec 仍因随机表、DM choice、变量 spell 或 entity/exhaustion 语义保持 fail-closed。
- 正式 registry/database、campaign/character、source corpus、3D 和永久保护路径未写入。

## 证据与门禁

- Validator：`scripts/validate-tashas-rest-feature-production-consumer-round-XVII.py`。
- Test：`backend/tests/test_tashas_feature_production_consumer_round_XVII.py`、`backend/tests/test_rests_api.py`。
- Result/report：`data/content-ir/compiled/production-runtime-results-XIX.json`、`reports/tashas-feature-production-consumer-round-XVII-2026-08-12.json`。
- Round XVII validator 通过；whole-pack migration 连续运行后关键 report/runtime SHA-256 保持一致。专门 Rest API 2 项通过；全量 backend pytest、Ruff、compileall、`git diff --check` 在收尾门禁确认。

下一轮优先继续已有 typed IR 的通用 event/entity/teleport/payment consumer；不会为随机表、实体、通信或 DM 裁定增加名称分支。
