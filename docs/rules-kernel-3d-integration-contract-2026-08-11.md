# Rules Kernel ↔ 3D 场景接入合同

版本：`rules-kernel-1`、`scene-query-1`、`scene-delta-1`、`dm-adjudication-1`

## 权威边界

```text
玩家 / DM / 3D 场景提交意图
        ↓
Rules Kernel preview
        ↓
choice 或 DM adjudication（如需要）
        ↓
Rules Kernel confirm
        ↓
持久化权威状态 + Scene Delta
        ↓
2D/3D 场景表现
```

3D 层不是规则状态，也不能自行扣血、扣资源、移动实体或创建实体。它只保存本地表现状态，
提交选择、坐标、路径和交互意图，并按 `sequence` 消费可重放、可去重的 `scene-delta-1`。

## 空间约定

- 规则距离单位是 feet。
- 当前项目 SceneGrid 的坐标单位是 1 个 grid cell，行列从 1 开始；默认 cell size 是 5 feet，
  但每个 SceneGrid 的 `cell_size_ft` 是权威值。
- 高度使用 feet，放在 position 的 `elevation_ft`；缺失高度时规则内核不会猜测 3D 穿透结果。
- footprint 使用 `size_cells × size_cells`，支持 1–4 格；占用、传送和范围查询都必须考虑 footprint。
- 场景坐标可由 Three.js、Blender、Godot、Unity 映射为自己的世界坐标，但映射不能回写为规则事实。

## Preview / Confirm / Replay

客户端发送一个带稳定 `command_id` 和 `idempotency_key` 的 `RulesKernelCommand` 到
`POST /api/v1/rules-kernel/preview`。preview 只冻结 actor、targets、空间快照、选择项和所需
裁定，不写游戏状态；choice/adjudication workflow 记录本身可以持久化。

如果 preview 返回 `pending_choice`，客户端只能从 `required_choices[].frozen_options` 中提交值；
如果返回 `pending_adjudication`，玩家不能批准裁定，必须让 DM 通过 adjudication endpoint 提交
结构化 decision。然后将原 command、preview version、confirmed choices/rolls/decisions 和同一
idempotency key 发送到 `POST /api/v1/rules-kernel/confirm`。

confirm 在 CAS 事务中写入权威 combat/scene/resource 状态，并产生 `scene_delta`。再次使用同一
command/idempotency key 只返回同一 result，`idempotent_replay=true`，不重复扣费、伤害、治疗、
移动或 spawn。

## Scene Delta 消费

每条 delta 有稳定 `delta_id`、`source_command_id`、`sequence`、before/after 和 entity/object ID。
客户端用 `GET /api/v1/rules-kernel/scene-deltas?campaign_id=...&after=...` 增量拉取；断线重连
从最后一个已确认的 cursor 继续。客户端应按 sequence 排序并以 delta_id 去重。若发现版本不连续，
应重新拉取权威场景快照，而不是自行修补规则状态。

空间事实查询使用 `POST /api/v1/rules-kernel/scene-query`，请求是 `scene-query-1`；它只返回
位置、距离、视线、掩体、范围目标、路径和最近未占用空间等事实，不会修改场景。

## DM 裁定

自由目标语义、自然语言效果、幻象解释、环境交互、自定义物体、复杂移动和规则例外进入持久化
`pending_dm` window。窗口保存 source evidence、typed known effects、冻结上下文、允许的 decision
字段和版本。DM 只能提交 JSON decision；不能提交 Python、脚本、动态 import 或任意表达式。
拒绝时原 command 不产生游戏状态；修改后规则内核重新验证目标、位置、空间和版本。

## 协议资产

独立 JSON Schema 和可验证 examples 位于 [`docs/protocols/`](./protocols/)，生成入口是
[`scripts/build-rules-kernel-protocol-assets.py`](../scripts/build-rules-kernel-protocol-assets.py)。
协议资产不依赖后端 Python 类，未来 3D 项目可直接使用这些 schema 做边界校验。
