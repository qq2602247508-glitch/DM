# Round XLVI：typed spell communication-route seam

日期：2026-08-13。

本轮选择 Message 的私密通信语义作为最高置信度的下一组边界：可见或熟悉、
固体障碍、目标独享、私密回复和魔法沉默阻断。这些条件可抽象成名称无关的
`spell.communication.route.v1`，但 Message 仍缺少 source-complete producer、
真实 runtime fixture 和全部来源条款的闭环，因此没有 promotion。

## 实现

- `TypedSpellCommunicationRouteSpec` 绑定 content/source provenance、发送者、
  目标、距离、障碍厚度和通信策略。
- `apply_typed_spell_communication_route` 对距离、可见/熟悉、障碍、魔法沉默、
  target-only/private-reply 进行 fail-closed 判定，并把 route receipt 写入版本化
  snapshot。
- CAS、确定性 request fingerprint、幂等 replay 和 message payload drift rejection
  均有 focused behavioral tests。
- production registry 注册 `spell.communication.route.v1`，仅接受 typed target
  和 `private_communication_route` contract；没有按 Message 名称 dispatch。

## Counts and evidence

- Project：`203 production / 35 compile-only / 111 unique compiled`，unchanged。
- Promoted IDs：空；五条 audited utility spells 全部 retained compile-only。
- Evidence：validator、report、focused tests；protected paths 未修改。
- Remaining Message blockers：source-complete producer/runtime fixture、完整 barrier/
  familiarity/material semantics、magical-silence source binding and persistence receipt。
