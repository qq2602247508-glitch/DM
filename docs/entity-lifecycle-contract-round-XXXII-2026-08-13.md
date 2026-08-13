# Entity Lifecycle + Remote Spell Origin Runtime Round XXXII

本轮没有把 `genie-bottled-respite` 或 `scribe-manifest-mind` 候选升为
production。实现的是后续两者共用的名称无关机制合同：实体生命周期的
operator → capability → materializer seam，以及可独立验证的状态机核心。

## 实现

- 新增 `entity.lifecycle.v1` domain contract，状态为
  `created → entered → exited → expired`；进入次数由 `active_entries` 记录，
 受 `max_entries` 限制，存在 active entry 时禁止 expire。
- 每个既有状态变更必须提供 `expected_version`；版本不匹配 fail closed。
  相同 `operation_id` 且请求 fingerprint 相同是幂等 replay；同 ID 不同请求
  拒绝。
- 新增名称无关 `configure_entity_lifecycle` operator、`entity.lifecycle`
  capability 与 `entity.lifecycle` materializer。runtime section 为
  `entity_lifecycles`，不依赖 feature 名称。
- materializer 要求 `FeatureSpec.source_fingerprint`，并写入
  `source_record_id/source_fingerprint/source_book/source_path` provenance；
  缺 fingerprint 不可物化。
- 新增名称无关 `remote.spell.origin.v1` domain contract：显式
  `origin_kind=entity`、`origin_id`、source record/fingerprint、actor authorization、
  target kind、range 与 line-of-effect；通过现有 `SpatialAuthority` 的实体距离和
  line-of-sight 事实解析目标，授权、目标、范围或视线不满足时 fail closed。
- 新增 `configure_remote_spell_origin` operator → `spell.remote_origin` capability →
  `spell.remote_origin` materializer，runtime section 为 `spell_origins`。物化块强制
  source provenance，并声明 entity-lifecycle authorization、target versions/CAS、
  operation idempotency 与 spatial authority requirements。
- 现有 `rules_kernel` 的 entity spawn/scene transaction 仍是实际执行边界；
  本轮没有复制或绕过该执行器，也没有新增候选内容 runtime dispatch。
- `ContentIRRuntimeService` advancement 已真实消费 `entity_lifecycles`：preview 计算
  `entity.lifecycle.v1` transition，confirm 复用既有 `OperationTransaction` 与
  Character version CAS，状态落在既有 `Character.features[*].runtime` JSON boundary；
  重复 confirm 返回 `already_applied`，payload drift fail closed。

## 验证

- focused lifecycle + remote-origin + real service suite：25 passed。
- focused suite 确定性双跑：两次输出 SHA-256 均为
  `29d68efd49f42366b1e9b94f42391bf5fd7d216fb797c9b0aee077e436131893`。
- backend 全量 pytest：`966 passed`；仅既有 Starlette/httpx deprecation warning。
- `backend/src backend/tests` Ruff：通过。
- `backend/src backend/tests` compileall：通过。
- `git diff --check`：通过。

## 边界

- remote-origin 仍只完成 domain + IR/materializer 合同，未在本轮扩展 spell cast
  transaction；entity lifecycle runtime evidence 使用 advancement 的既有
  Character/OperationTransaction 边界，不新增 entity store。
- Tasha/project production、compile-only、formal 499 计数没有因为本轮机制基础设施改变。
- 没有修改 formal database、formal registry、source corpus、campaign/character、
  3D 或 `backend/tests/integrations/`、`backend/tests/ollama.py`。
- 本轮未提交或推送；两个 source-incomplete feature 继续保持非 production。
