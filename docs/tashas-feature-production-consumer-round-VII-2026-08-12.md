# Tasha Feature Production Consumer Round VII

本轮从 Round-II reviewed/authored Feature IR 中选择 8 条角色成长与法术列表合同，复用通用 `ContentIRRuntimeService` 的 advancement consumer，完成真实隔离 SQLite 上的 preview → confirm → 幂等 replay。

## 生产批次

- `alchemist-spell-list`
- `clockwork-soul-clockwork-magic`
- `feat-fey-touched`
- `feat-shadow-touched`
- `paladin-blessed-warrior`
- `psi-warrior-telekinetic-master`
- `ranger-druidic-warrior`
- `swarmkeeper-spell-list`

8/8 均满足：`production_runtime_full=true`、consumer=`advancement_service.character_growth.v1`、character CAS、operation transaction、feature snapshot 持久化、confirm replay 返回 `already_applied=true`。角色成长实际写入 spell grants；4 条 feat/class cantrip 合同通过 typed choice 输入。`advancement_blocks_ready=true`，没有 feature-name/name-based 分支。

## 整包结果

Round VII 后 Tasha status layers：

- `registered_production_full=60`（52→60）
- `dm_assisted=2`
- `game_usable=62`
- `manual_authoring=314`
- `authored_typed_ir=94`
- `runtime_preview_full=93`
- `compile_only=31`（39→31）

Content-ID funnel 保持 `matched_typed_ir=94 = production_full=61 + dm_assisted=2 + compile_only=31`；其中 60 条为本包当前 production-full runtime atom 口径，另 1 条 production evidence 对应跨层 duplicate/content-id 汇总。正式 registry/database/campaign/character 不在本轮 apply 范围内。

## 验证

- Round VII validator：8/8 preview-confirm-replay、8/8 typed consumer、8/8 CAS/transaction、8/8 feature persisted。
- 定向 Round III/V/VI/VII 与 whole-pack migration tests 通过。
- backend 全量 pytest 通过；变更源 Ruff、compileall、`git diff --check` 通过。
- whole-pack migration 连续两次执行；Round VII result/report、whole-pack report、status audit、atom index、runtime registry 六个关键 SHA-256 完全一致。
- 保护边界未变：`backend/tests/integrations/` manifest=`ae4ef9f5…cd91`、`backend/tests/ollama.py`=`8027a6d8…e6ab`、database aggregate=`f3abdcf5…a6ad`、formal registry baseline=`f4b5eab2…ca6b`。

## 证据入口

- validator：`scripts/validate-tashas-feature-production-consumer-round-VII.py`
- test：`backend/tests/test_tashas_feature_production_consumer_round_VII.py`
- result：`data/content-ir/compiled/production-runtime-results-IX.json`
- report：`reports/tashas-feature-production-consumer-round-VII-2026-08-12.json`

下一轮继续处理剩余 typed contract 的 resource/action/trigger lifecycle、vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 ItemSpec consumer；isolated-only、DM-reference、formal 499 audit 与 3D 继续保持边界。
