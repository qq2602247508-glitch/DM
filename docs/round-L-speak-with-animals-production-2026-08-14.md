# Round L：Speak with Animals production closure

日期：2026-08-14  
基线：`ec801044a25bc2d8ddaf3df2478c7adc90843eeb`

## 比较与选择

本轮比较了 Disguise Self、Prestidigitation、Speak with Animals 三个剩余 audited utility spell。

- Disguise Self 仍缺持久 illusion appearance envelope、物理检查穿透、研究动作与法术 DC 消费者，以及 expiry receipt。
- Prestidigitation 仍缺六模式 typed choice、即时/定时 object/surface lifecycle、dismissal 和三槽并发限制。
- Speak with Animals 的完整 source boundary 可由一个通用 source-bound communication capability consumer 闭合：自身目标、10 分钟能力、beast scope、Influence 三项 skill options，以及不超过 24 小时的 surroundings/monsters observation boundary。

因此本轮只 promotion Speak with Animals；另外两个保持 compile-only。

## Source / runtime evidence

Authored IR：

`data/content-ir/authored/batch-II/core-phb-2024/spells/core-phb-2024-spell-d82624a42cf6c33ccec927b8.json`

新增 typed clause：

- `target`：`self`
- `communication_capability`：`beast_communication_capability`、10 minutes、`deception/intimidation/persuasion`、`surroundings_and_monsters`、24-hour boundary

通用 consumer：

`spell.communication.capability.v1`

能力通过 generic Content IR preview → confirm → spell economy transaction → combatant snapshot CAS → operation transaction → replay 路径落地。receipt 持久化 source provenance、capability expiry、Influence skill set 和 recent-observation boundary；invalid skill/scope/age、non-beast target 与 stale CAS 均 fail closed。

## Projection / gates

证据 artifact：

`data/content-ir/compiled/production-runtime-results-L.json`

validator：

`scripts/validate-round-L-speak-with-animals-production.py`

自然投影：

`206 production / 32 compile-only / 111 unique compiled`

Round XLIII historical report SHA-256 保持：

`98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f`

Focused behavioral tests：

`backend/tests/test_round_L_speak_with_animals_runtime.py`（16 passed）

覆盖独立节点：preview/confirm 与 actor snapshot persistence、source
record/fingerprint/clause、精确 10 分钟 expiry、Influence skill enumeration、
24 小时边界、exact replay/no second mutation/payload drift、character/actor/beast
CAS、invalid runtime/source contract、invalid skill/scope/25-hour age 与 non-beast。

validator 在隔离迁移 SQLite 中实际执行 API preview → confirm → persistence →
OperationTransaction → replay，并序列化实际 capability receipt、persisted actor
snapshot 与 transaction lookup；不再组装手写成功 receipt。artifact/report/stdout
连续两次 byte-identical。

其余 Ruff、compileall、diff-check、full backend pytest 和 validator 双跑结果以最终 handoff 为准。

## Remaining risks

Disguise Self 与 Prestidigitation 仍没有可诚实复用的完整 generic consumer；不应通过 name/ID branch 或只登记 partial helper 进行 promotion。
