# Tasha Feature Production Consumer Round VIII

本轮从剩余 full Feature contracts 中选择 8 条，复用现有 typed combat consumer：7 条通过 runtime snapshot 的 passive/inspection 路径，1 条通过已有 feature-action activation 路径。反应窗口、资源交换/profile 等尚无完整通用事件消费者的合同继续留在排名中，未在本轮混算。

## 生产批次

- `battle-master-grappling-strike`
- `battle-master-tactical-assessment`
- `psi-warrior-psi-powered-leap`
- `soulknife-homing-strikes`
- `soulknife-psi-bolstered-knack`
- `stars-druid-full-of-stars`
- `stars-druid-weal`
- `stars-druid-woe`

8/8 均通过真实隔离 SQLite 上的 `ContentIRRuntimeService` preview→confirm→幂等 replay，consumer 为 `combat_engine.feature_action.v1`，runtime ID 与 actor registry 绑定，formal registry/database 写入为 false，name branch=0。7 条 passive contract 的 passive block 与 runtime ID 一致并由 inspection resolution 验证；`psi-powered-leap` 走显式 activation，实际消耗 `psionic_dice` 角色资源（3→2）并持久化飞行模式。

## 整包结果

Round VIII 后 Tasha status layers：

- `registered_production_full=68`（60→68）
- `dm_assisted=2`
- `game_usable=70`
- `manual_authoring=314`
- `authored_typed_ir=94`
- `runtime_preview_full=93`
- `compile_only=23`（31→23）

Content-ID funnel 保持 `matched_typed_ir=94 = production_full=69 + dm_assisted=2 + compile_only=23`；其中 68 条为本包当前 production-full runtime atom 口径，另 1 条 production evidence 对应跨层 duplicate/content-id 汇总。正式 registry/database/campaign/character 不在本轮 apply 范围内。

## 验证

- Round VIII validator：8/8 preview-confirm-replay、8/8 typed consumer、8/8 runtime ID binding、8/8 resource/CAS gate、7/7 passive binding、1/1 activation。
- 定向 Round III/V/VI/VII/VIII 与 whole-pack migration tests 通过。
- backend 全量 pytest、变更源 Ruff、compileall、`git diff --check` 通过。
- whole-pack migration 连续两次执行；Round VIII result/report、whole-pack report、status audit、atom index、runtime registry 六个关键 SHA-256 完全一致。
- 保护边界未变：`backend/tests/integrations/` manifest=`ae4ef9f5…cd91`、`backend/tests/ollama.py`=`8027a6d8…e6ab`、database aggregate=`f3abdcf5…a6ad`、formal registry baseline=`f4b5eab2…ca6b`。

## 证据入口

- validator：`scripts/validate-tashas-feature-production-consumer-round-VIII.py`
- test：`backend/tests/test_tashas_feature_production_consumer_round_VIII.py`
- result：`data/content-ir/compiled/production-runtime-results-X.json`
- report：`reports/tashas-feature-production-consumer-round-VIII-2026-08-12.json`

下一轮优先建设通用 reaction-window、resource exchange/profile 与真正 event producer/consumer 链，再处理 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 ItemSpec lifecycle；未经过完整事件语义的合同继续停留在 compile/isolated 边界。
