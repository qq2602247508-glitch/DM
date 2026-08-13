# Round XXXIII：Manifest Mind spectral-object blocker 收口

本轮选择 `content.tashas-cauldron.round2.feature.scribe-manifest-mind`，没有把
`genie-bottled-respite` 或 `scribe-manifest-mind` 升为 production。

## Baseline 与选择理由

Round XXXII baseline：Tasha `105 authored / 104 compile / 104 preview /
100 production / 2 DM-assisted / 102 game usable / 2 compile-only / 304 manual /
107 DM reference`；项目 `200 production / 35 compile-only / 111 unique compiled`。

`genie-bottled-respite` 仍缺器皿创建、异次元容器、携带物与破坏/死亡/长休语义；
`scribe-manifest-mind` 可复用 entity lifecycle 与 remote spell origin，但其感官
属于 spectral object，不是角色自身的 darkvision。因此本轮选择 scribe，补齐
名称无关 entity sensory-profile authoring seam，并保持 production fail-closed。

## 实际变更

- 修正 `scribe-manifest-mind.json` 的 authored metadata：保留 `kind=feature` 兼容
  whole-pack provenance loader；移除 schema 外字段只能由测试 fixture 验证 fail-closed。
- 保留并显式记录四个 source boundaries：spectral-object lifecycle、remote spell
  origin、entity senses、authorized information。source record、book、path、
  fingerprint 与 source excerpt 均保留。
- 新增通用 `configure_entity_senses` → `entity.senses` → `entity_senses` materializer
  contract。支持 `hearing`、`darkvision_ft`、`light_radius_ft`，未知字段、错误类型、
  超范围值与缺 provenance 均拒绝；该 capability 当前为 `production_partial`，因此
  不允许 compile full / production promotion。
- 修复 remote-origin 对既有 lifecycle 包装记录
  `{"entity_id","state"}` 的读取，保留 actor ownership、source provenance、range、
  line-of-effect 与 target authorization 的 fail-closed 边界。

## Evidence

本轮后续接入了真实通用 runtime consumer，但没有改变 source completeness 或
production promotion：

- `entity.senses` 现在由 `ContentIRRuntimeService` advancement snapshot 持久化，
  并由既有 inspection/combat action consumer 读取；实体来源仍必须来自已持久化的
  `entity_lifecycle` + `entity_senses` 记录，不能由请求体伪造。
- 真实 API receipt 覆盖 spectral object 的 source provenance、owner/entity binding、
  lifecycle `entered` active gate、`SceneGridSpatialAuthority` 的实体/目标空间事实、
  hearing/vision channel、距离、line-of-sight、preview → confirm → replay、
  OperationTransaction 与 actor CAS。
- 真实 API fail-closed 覆盖 inactive/expired entity、未授权 entity、无 authoritative
  scene、stale actor CAS；既有 target policy、combat/inspection snapshot 和 lifecycle
  state 未被平行实现替代。
- 独立通用测试入口：
  `backend/tests/test_content_ir_entity_senses_runtime.py`。

- `scribe-manifest-mind` 当前真实 compile status：`partial`。
- 完整 source IR 的 blockers：`capability entity.senses is production_partial`；
  source completeness 仍为 `incomplete`，未建模 terms 明确为 entity sensory profile、
  entity movement/300-foot expiry、spell-slot reactivation payment。
- 正向 remote-origin geometry：20 ft，line of effect true。
- 未授权 origin fail-closed：通过。
- `production_runtime_full_ids=[]`；`compile_only_ids=[scribe-manifest-mind]`。
- Round XXXIII validator 与报告：
  `scripts/validate-tashas-feature-production-consumer-round-XXXIII.py`、
  `reports/tashas-feature-production-consumer-round-XXXIII-2026-08-13.json`、
  `data/content-ir/compiled/production-runtime-results-XXXIII.json`。
- Round XXXIII focused suite：6 passed；既有 lifecycle/remote-origin suites：
  25 passed；backend 全量 pytest：990 passed，仅既有 Starlette/httpx deprecation
  warning。
- Ruff、compileall、`git diff --check`：通过。
- validator 双跑 stdout SHA-256：
  `da3119fc8bd4788b0b844d16f616174dc15e9fa57f52fed9d139d635c59b379a`。
- whole-pack migration 双跑 stdout SHA-256：
  `e6544f3bb121a2be03ea3dde70adc6974f39a988681a44cf3b53ad0c1064449b`。

## Actual after / delta

计数无变化：Tasha `105/104/104/100/2/102/2/304/107`；项目
`200 production / 35 compile-only / 111 unique compiled`。本轮只推进通用 blocker
与 provenance/runtime authoring infrastructure，不产生 production delta。

formal database、formal registry、source corpus、campaign/character、3D 与两个
保护路径未写入。`backend/tests/integrations/`、`backend/tests/ollama.py` 保持
用户原有未跟踪状态与指纹。

下一轮应先完成 entity sensory profile 的真实 producer/consumer、实体移动与距离
过期、长休/法术位重新显现支付，再重新审查 scribe source completeness；vessel
仍保持独立 blocker。
