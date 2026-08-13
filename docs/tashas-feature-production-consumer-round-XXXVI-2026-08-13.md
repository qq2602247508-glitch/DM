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
  capability 与 `spell_slot_reactivations` materializer section；明确
  `production_partial`，未接入正式 production runtime/registry。
- authored IR 只增加该 source-complete boundary 的 typed clause；feature
  `source_completeness=incomplete` 保持不变，`scribe-manifest-mind` 不升 production。
- 复用语义边界，不新增 Resource/Rest/OperationTransaction 平行系统；真实持久化支付
  transaction 留待现有 Resource/Rest/OperationTransaction seam 完成后接入。

## 证据

- `backend/tests/test_spell_slot_reactivation.py`：source provenance、materializer
  partial、法术位不足/严格一枚、重复激活、长休恢复、rollback、CAS/replay。
- `scripts/validate-tashas-feature-production-consumer-round-XXXVI.py`：同一 contract
  的 deterministic validator 双跑通过。
- backend 全量 pytest、Ruff、compileall、`git diff --check` 通过。
- Tasha/project production 计数保持：`106 authored / 105 compile / 105 preview /
  101 production / 2 compile-only`；项目 `201 production / 35 compile-only /
  111 unique compiled`；全部 delta 为 0。
- `production_runtime_full_ids=[]`；compile-only 仍包含
  `scribe-manifest-mind` 与 `genie-bottled-respite`。

## 剩余风险

法术位支付尚未通过真实角色资源持久化、RestService/SpellEconomyService、
OperationTransaction 的端到端 transaction evidence；实体感官/空间 runtime 也仍是
partial。因此本轮只交付可独立验证的 domain + IR/materializer contract。
