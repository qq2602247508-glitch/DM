# Feature IR 自动装配架构（2026-08-09）

本轮建立了职业/子职业特性自动装配的第一版中间层。它不替代现有的 CombatEngine、PlayerRoom、advancement、rest 或 spell economy；它只负责把结构化特性需求编译成已有生产消费者可以识别的合同，并对无法满足的子句给出精确阻塞原因。

## 生产化硬化 I（当前检查点）

`domain/feature_operators.py` 为每个 operator 提供 `OperatorContract`：required/optional 参数、
精确类型、enum、数值边界、互斥字段、条件必填、兼容 trigger/condition/target/duration/action/
resource、materializer 和 capability 绑定。未知参数、空参数、错误类型以及 expression/eval/
exec/Python/import/module/function/path payload 均 fail-closed。

`production_closed` capability 禁止 wildcard，并且必须同时有真实 producer、consumer、持久化、
CAS、幂等、materializer 和 evidence test。FeatureSpec/FeaturePackManifest 记录 `source_trust`；
只有 `authored_ir`、`verified_mapping` 能自动 full，generated draft 只能登记为 partial/manual。

`application/feature_materializers.py` 的 `MaterializerRegistry` 只按 operator、验证后的参数和
capability 工作，输出现有 advancement、resource、feature_runtime、移动/视线、法术修改、
zero-HP 与窗口消费者识别的 canonical contract，并经过 section validator。

十条正式特性现在由 authored Feature IR 编译，字段级 parity 全部为 `exact` 或有证明的
`equivalent`，十条稳定 ID 的 `status_authority` 为 `compiler`。旧名称配置只保留兼容 fallback，
不再参与这十条正式绑定的执行。新增 `modifier.passive.v2` 证明六条真实 FeatureSpec 在能力
注册前全部 partial、注册后无需修改 specs 即全部 full，并进入
`feature_runtime_registry` 与 `combat_start_modifiers` 两个生产投影。

## 分层

```text
FeaturePackManifest
        ↓
FeatureSpec / FeatureClause
        ↓
FeatureCompiler
        ↓
CapabilityCatalog
        ↓
canonical runtime blocks
        ↓
现有 advancement / rest / spell / combat consumers
```

## Feature IR v1

Feature IR 使用严格 schema `feature-ir-1`，顶层包含稳定 `feature_id`、namespace、pack/version、规则集版本、源码身份、完整性、依赖和 clauses。每个 clause 明确记录 trigger、conditions、activation、action economy、resource、inputs、targeting、effects、duration、expiry、stacking、frequency、persistence、visibility 和 audit 信息。

效果只能使用关闭的 operator registry。IR 不允许 Python、模块路径、函数名、`eval` 表达式或未知顶层字段。未知 schema、未知字段、重复 clause ID、重复 pack feature ID 和非法依赖均 fail-closed。

## Capability Catalog

CapabilityDescriptor 记录：

- producer、consumer 和持久化状态；
- 支持的 trigger、condition、input、target、duration、动作经济和资源操作；
- CAS、幂等、UI 投影和版本；
- production status 与证据测试；
- 已知限制。

只有 `production_closed` capability 可以让 clause 参与自动 `full`。当前目录包含 34 个 descriptor，覆盖成长授予、资源、被动修正、移动/视线、伤害/治疗、防御、状态、计时 modifier、zero-HP、反应窗口和部分施法上下文能力。施法上下文和目标情报仍明确标记为 `production_partial`，不会被编译器误报为 full。

## 编译结果

`FeatureCompiler` 对每个 clause 逐项检查：

- operator 是否存在；
- capability 是否 production closed；
- trigger、condition、input、target、duration 和 action economy 是否支持；
- 资源和依赖是否满足；
- 是否存在人工裁定边界；
- 是否有生产证据。

输出 `full`、`partial`、`manual` 或 `invalid`，并记录 unsupported operator、condition、combination、clause ID、required persistence、required UI 和 evidence。输出带确定性 fingerprint。

编译器只生成 canonical runtime blocks；实际规则仍由现有消费者结算。完整结果可以通过 `materialize_runtime_definition` 进入当前 `feature_runtime_contract` 形状，避免建立平行执行器。

## Legacy shadow 与 authority

旧 runtime contract 可以通过 legacy adapter 转成 Feature IR。当前审计保持旧 `runtime_status` 不变，同时新增：

- `ir_available`
- `ir_schema_version`
- `compiler_status`
- `status_authority`
- clause 计数
- unsupported clause IDs
- capability IDs
- legacy adapter 标记
- compiler fingerprint

审计中只有十条真实 authored IR 且逐字段 parity/生产回归通过的特性切换为 compiler authority；其余 legacy/结构 IR 为 `shadow_candidate` 或 `legacy`。正式 499 条状态仍保持 `full 310 / partial 128 / dm_only 61`，没有因为编译器改变正式分母或状态。

## 后续边界

自然语言或 AI 解析结果只能作为 `generated_draft`，不能自动 full。只有 `authored_ir` 或 `verified_mapping` 才能进入自动 full。需要新的 producer、consumer、状态机、目标系统或复杂 UI 的特性必须继续保持 partial，并在编译报告中指出具体缺口。
