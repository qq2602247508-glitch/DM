# Round XXXV：Manifest Mind entity spatial seam

## 选择与边界

Round XXXIV 基线为 Tasha `106 authored / 105 compile / 105 preview / 101 production /
2 compile-only`，项目 `201 production / 35 compile-only / 111 unique compiled`。

本轮选择 `content.tashas-cauldron.round2.feature.scribe-manifest-mind` 的
spectral-object movement / separation boundary。它复用 Round XXXII 的 entity lifecycle、
Round XXXIII 的 entity senses 和已有 spatial facts，但不把 feature 升为 production：
source completeness 仍为 `incomplete`，`entity.senses` 仍为 `production_partial`，
spell-slot reactivation payment consumer 尚未闭合。

## 实现

- 新增名称无关的 `entity.spatial.v1` domain contract。
- 支持每次最多 30 尺移动、距离持有者超过 300 尺后进入 `expired`。
- 移动要求调用方提供 owner visibility、destination unoccupied、path clear of objects；
  缺少任一事实即 fail-closed。
- 绑定 source record/fingerprint，使用 version CAS、operation-id + request fingerprint
  replay；payload 漂移和 stale version 均拒绝。
- `configure_entity_senses` 接受严格的 spatial contract，并 materialize 为
  `spatial_contract`；unknown fields 和非 30/300 边界拒绝。
- 没有新增 feature-name branch、database、formal registry、entity store、campaign/
  character 数据或 3D。

## 真实证据

- `backend/tests/test_entity_spatial.py`：11 项 focused domain/materializer 边界通过。
- `scripts/validate-tashas-feature-production-consumer-round-XXXV.py`：正向移动、
  300 尺超距 expiry、缺空间事实 fail-closed、replay、CAS、source provenance 和保护
  路径检查全部通过。
- validator 双跑 stdout SHA-256：
  `53c059905454488fd541a499243092df5f8203d74d664cf1549251b96a8dd423`。
- whole-pack 双跑 stdout SHA-256：
  `071cd15163381c68d0888a4f849d2edc80bf79450955ff8c73498a2212d123a7`。
- backend 全量 pytest 通过；Ruff、compileall、diff-check 通过。

结果：

- Tasha：`106 authored / 105 compile / 105 preview / 101 production / 2 compile-only`
- 项目：`201 production / 35 compile-only / 111 unique compiled`
- delta：Tasha/project production `0`，compile-only `0`，unique compiled `0`
- `source_completeness=incomplete` 保持不变；未生成 `production_runtime_full_ids`
- 剩余 blocker：spell-slot reactivation payment consumer；genie vessel 仍独立阻塞

证据入口：

- `backend/src/dnd_dm_assistant/domain/entity_spatial.py`
- `backend/tests/test_entity_spatial.py`
- `backend/tests/test_tashas_feature_production_consumer_round_XXXIII.py`
- `scripts/validate-tashas-feature-production-consumer-round-XXXV.py`
- `reports/tashas-feature-production-consumer-round-XXXV-2026-08-13.json`
- `data/content-ir/compiled/production-runtime-results-XXXV.json`
