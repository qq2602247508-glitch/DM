# Round LI：Disguise Self / Prestidigitation closure audit

日期：2026-08-14  
基线：`738e624260bb43575766a9cf73c42c360ec74310`

## 决策

本轮比较两条剩余 utility spell source boundary，结论是两者都不能由现有 generic production consumer 完整闭合，因此均保留 compile-only。

- Disguise Self：源文要求 self/1 小时、外观与随身物品的 illusion envelope、物理触碰穿透、Research 动作与智力（调查）对抗法术豁免 DC，以及终止/expiry receipt。当前 generic registry 没有这些持久状态、检查判定和过期消费者。
- Prestidigitation：源文要求 10 尺 object/surface 边界、六种 typed mode、即时与定时两类生命周期、下一回合结束的次级造物、dismissal，以及至多三个并发非即时效应。当前 generic registry 没有六模式选择、物件/表面生命周期或三槽并发不变量。

两条记录仍可从 source-bound authored IR 编译为 `full`，但真实调用 `resolve_production_consumers` 均 fail closed：`spell runtime has no registered executable consumer`。没有新增 name/ID dispatch、partial helper、正式 registry 写入或 campaign 数据写入。

## 证据与投影

- 证据 artifact：`data/content-ir/compiled/production-runtime-results-LI.json`
- validator：`scripts/validate-round-LI-utility-spell-closure.py`
- focused nodes：`backend/tests/test_round_LI_utility_spell_retention.py`
- set-based projection：`206 production / 32 compile-only / 111 unique compiled`
- promotion delta：`0 / 0 / 0`

Validator 直接执行 source-bound `SpellSpec` 编译、generic registry resolution、set-based evidence loader 与命名 pytest nodes；artifact/report 两次生成应 byte-identical。由于没有 source-complete consumer，本轮不伪造 preview/confirm receipt。

## 保护与后续

- Round XLIII report SHA-256 保持：`98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f`
- `backend/tests/ollama.py` SHA-256 保持：`8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`
- 无 push。

下一次若继续推进，需要先设计一个名称无关的 illusion appearance/inspection lifecycle consumer，或一个名称无关的 multi-mode object-effect lifecycle consumer，并为其补齐 source-bound preview → confirm → CAS → OperationTransaction → replay/expiry 证据。
