# Round XXXVI：Manifest Mind spell-slot reactivation seam

本轮先复核 `scribe-manifest-mind.json` 的 source boundary：首次显现是一次附赠动作，
显现停止后再次显现必须完成一次长休，或消耗一枚任意环阶法术位；每次 reactivation
消耗恰一枚法术位，长休恢复下一次显现资格。实体状态与 payment 状态分离，不能把该
语义误投影为普通法术位回满。

## 实现

- 新增名称无关 `spell.slot.reactivation.v1` domain contract：
  `inactive/active`、activation limit=1、首次激活、deactivate、long-rest reset、
  any-level spell-slot payment、严格 1 枚法术位。
- contract 绑定 `source_record_id/source_fingerprint`，要求 expected-version CAS，
  operation-id + request fingerprint replay；payload drift、stale CAS 和非相邻
  rollback fail closed。
- 新增 `configure_spell_slot_reactivation` operator、`spell.slot.reactivation`
  capability 与 `spell_slot_reactivations` materializer section；通用 capability
  已升级为 `production_closed`，并注册 `spell.slot.reactivation.v1` consumer。
- authored IR 只增加该 source-complete boundary 的 typed clause；feature
  `source_completeness=incomplete` 保持不变，`scribe-manifest-mind` 不升 production。
- 真实接入仍复用既有 Resource/Rest/OperationTransaction seam：状态嵌入
  `Character.features[*].runtime`，支付从 `Character.resources` 的
  `spell_slots_1`–`spell_slots_9` 中严格扣一枚，并由同一 character CAS /
  OperationTransaction 事务提交；不存在平行资源存储或 API。

## 证据

- `backend/tests/test_spell_slot_reactivation.py`：source provenance、materializer
  closure、法术位不足/严格一枚、重复激活、长休恢复、rollback、CAS/replay。
- `backend/tests/test_content_ir_spell_slot_reactivation_runtime.py`：真实 API
  preview/confirm/replay、任意环位支付、slot shortage、长休免费 availability、
  character CAS、provenance/entity binding 与 OperationTransaction receipt。
- `scripts/validate-tashas-feature-production-consumer-round-XXXVI.py`：同一 contract
  的 deterministic validator 双跑通过。
- backend 全量 pytest `987 passed, 1 warning`，Ruff、compileall、
  `git diff --check` 通过。
- Round XXXVI validator 全部检查通过且双跑 byte-identical；whole-pack migration
  双跑 byte-identical，projection SHA-256 保持
  `071cd15163381c68d0888a4f849d2edc80bf79450955ff8c73498a2212d123a7`。
- Tasha/project production 计数保持：`106 authored / 105 compile / 105 preview /
  101 production / 2 compile-only`；项目 `201 production / 35 compile-only /
  111 unique compiled`；全部 delta 为 0。
- `production_runtime_full_ids=[]`；compile-only 仍包含
  `scribe-manifest-mind` 与 `genie-bottled-respite`。

## 剩余风险

实体感官/空间 runtime、移动与 300 尺过期、telepathic sharing 和 PB-per-day
uses 仍未闭合；因此 `scribe-manifest-mind` 继续保持 `compile_only`，
`production_runtime_full_ids=[]`。本轮只关闭通用 reactivation capability，
没有升级该 feature production。
