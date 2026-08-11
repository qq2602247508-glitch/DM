# Tasha Feature Production Consumer Round IX

本轮完成剩余 6 条 full Feature contract 的通用资源与事件窗口接入，属于 platform/core growth round：补齐 typed resource profile、resource exchange、reaction window 和 triggered attack window 的统一 consumer。

## 生产批次

- `psi-warrior-psionic-power`：角色成长 resource profile，按 typed `2 * proficiency_bonus` 解析为 psionic dice pool。
- `battle-master-brace`、`battle-master-quick-toss`：typed triggered attack window，持久化候选目标、攻击 profile、动作经济与资源成本。
- `paladin-harness-divine-power`：typed resource exchange，按角色 proficiency bonus 计算 2 点，从 channel divinity 交换到 1 环法术位。
- `paladin-interception`、`rune-knight-runic-shield`：typed reaction window；符文之盾同时通过角色资源 CAS 消耗一次使用次数。

6/6 均通过真实隔离 SQLite 上的 preview → confirm → 幂等 replay。Character growth 使用 `advancement_service.character_growth.v1`；5 条战斗合同使用 `combat_engine.feature_event_window.v1`。4 个窗口实际持久化为 `CombatAction` eligible window，资源 profile/exchange/CAS 全部通过。formal registry/database/campaign/character 正式写入为 false，name branch=0。

## 通用实现

- `feature_compiler.materialize_runtime_definition` 将 typed `create_*_window` / `exchange_resource` clause 投影为稳定 `feature_action` + `window_spec` / `resource_exchange`，不读取特性名。
- `ContentIRRuntimeService` 新增 event-window consumer 分发、resource profile advancement 和 resource snapshot/CAS 传递。
- `CombatEngineService.confirm_feature_action` 统一执行资源交换、窗口候选/攻击 profile 构造、窗口持久化、父动作与幂等事务绑定。
- `combat_engine.feature_event_window.v1` 加入 closed production registry；reaction、triggered attack 与 exchange 共用结构化协议。

## 整包结果

Round IX 后 Tasha status layers：

- `registered_production_full=74`（68→74）
- `dm_assisted=2`
- `game_usable=76`
- `manual_authoring=314`
- `authored_typed_ir=94`
- `runtime_preview_full=93`
- `compile_only=17`（23→17）

Content-ID funnel 保持 `matched_typed_ir=94 = production_full=75 + dm_assisted=2 + compile_only=17`；其中 74 条为本包当前 production-full runtime atom 口径，另 1 条 production evidence 对应跨层 duplicate/content-id 汇总。正式 registry/database/campaign/character 不在本轮 apply 范围内。

## 验证

- Round IX validator：6/6 preview-confirm-replay、6/6 typed consumers、4 个 event windows、1 个 resource profile、1 个 resource exchange、全部资源/CAS gate。
- 定向 Round III/V/VI/VII/VIII/IX 与 whole-pack migration tests 通过。
- backend 全量 pytest、变更源 Ruff、compileall、`git diff --check` 通过。
- whole-pack migration 连续两次执行；Round IX result/report、whole-pack report、status audit、atom index、runtime registry 六个关键 SHA-256 完全一致。
- 保护边界未变：`backend/tests/integrations/` manifest=`ae4ef9f5…cd91`、`backend/tests/ollama.py`=`8027a6d8…e6ab`、database aggregate=`f3abdcf5…a6ad`、formal registry baseline=`f4b5eab2…ca6b`。

## 证据入口

- validator：`scripts/validate-tashas-feature-production-consumer-round-IX.py`
- test：`backend/tests/test_tashas_feature_production_consumer_round_IX.py`
- result：`data/content-ir/compiled/production-runtime-results-XI.json`
- report：`reports/tashas-feature-production-consumer-round-IX-2026-08-12.json`

下一轮继续优先处理剩余 unresolved ItemSpec consumer 与 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 的真实 event producer/consumer；本轮已补齐的 generic window/resource consumers 继续作为平台能力复用。
