# Round XXXIX：Manifest Mind dedicated entity spatial runtime

## 结论

本轮完成名称无关 `entity.spatial.v1` dedicated production consumer/API/service，
闭合 Manifest Mind 的 movement 与 distance-expiry 两条 source boundary；但
`scribe-manifest-mind` 仍保持 `compile_only_blocked`，不升 production。

## Runtime evidence

- owner 在自己的回合以 bonus action 指挥 entity，最多移动 30 ft。
- 终点由 authoritative grid 校验为未占用；对象阻断路径，creature 可穿过。
- owner/entity 绑定、owner turn、bonus action、grid position、visibility、occupancy、
  path、distance 均由服务端重算；请求体不能伪造这些事实。
- entity position 与 typed spatial state 持久化；actor/entity version CAS、
  `OperationTransaction`、preview → confirm → replay、payload fingerprint 和
  failed-confirm rollback 均覆盖。
- 超过 owner 300 ft 立即写入 typed `expired/distance_expired`；后续 senses、
  telepathy、remote-origin 对 expired/terminated entity fail-closed。
- 没有 feature-name dispatch；consumer 为 `entity.spatial.v1`。

## Matrix and gates

- source boundary matrix：`13 covered / 0 partial / 0 missing`。
- Tasha baseline/after：`106 authored / 105 compile / 105 preview / 101 production /
  2 compile-only`，delta 全部 `0`。
- project baseline/after：`201 production / 35 compile-only / 111 unique compiled`，
  delta 全部 `0`。
- `production_runtime_full_ids=[]`；formal DB/registry 未写入。
- `source_completeness=incomplete`；whole-feature production promotion gate 保持关闭。
- remaining blockers：source-level feature promotion requires the broader authored
  completeness/production promotion gate; genie vessel remains independent.

## Verification

- focused/API spatial receipts：通过。
- full backend pytest：通过（仓库源码 `PYTHONPATH` 入口）。
- Ruff、compileall、`git diff --check`：通过。
- dynamic audit 双跑：byte-identical，stdout SHA-256
  `f619e20e7c756077adefcefaf866ddd39b74c13229585acb0ae438fdbf99594c`。
- Round XXXV validator 双跑：byte-identical，stdout SHA-256
  `53c059905454488fd541a499243092df5f8203d74d664cf1549251b96a8dd423`。
- whole-pack 双跑：byte-identical，stdout SHA-256
  `071cd15163381c68d0888a4f849d2edc80bf79450955ff8c73498a2212d123a7`。
- production reconciliation：历史报告 gate 失败，因为脚本期待旧的
  `Tasha 132 / project 189 / whole-pack 89` receipts，而当前真实状态为
  `Tasha 144 / project 201 / production 101`；formal DB、formal registry、
  protected fingerprints、name-branch gate 均通过。该历史口径不作为 promotion
  证据，且未修改正式 registry/database。

## Evidence map

- `backend/src/dnd_dm_assistant/domain/spatial_authority.py`
- `backend/src/dnd_dm_assistant/application/content_ir_runtime.py`
- `backend/src/dnd_dm_assistant/api/schemas.py`
- `backend/tests/test_content_ir_entity_spatial_api.py`
- `backend/tests/test_content_ir_entity_spatial_runtime.py`
- `scripts/audit-scribe-manifest-mind-source-boundary.py`
- `reports/scribe-manifest-mind-source-boundary-audit-2026-08-13.json`
- `data/content-ir/compiled/production-runtime-results-XXXV.json`

保护路径 `backend/tests/integrations/`、`backend/tests/ollama.py` 未修改、未暂存、
未提交。
