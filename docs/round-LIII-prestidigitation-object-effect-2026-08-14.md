# Round LIII：Prestidigitation generic object-effect lifecycle

日期：2026-08-14
基线：`eec42902554ba4e085c43ca4e1d47aa15cff8bcd`

## 决策

接受 Prestidigitation 通过名称无关的
`spell.object_effect.lifecycle.v1` generic consumer；没有新增 spell-name/ID
dispatch、numeric delta、hardcoded coverage 或 formal registry/database 写入。

## Source/runtime boundary

源绑定 IR 现在显式包含六个 typed modes：

- `sensory_effect`：立即、无害感官效应；
- `fire_play`：10 尺内蜡烛、火把或小篝火的点燃/熄灭；
- `clean_or_soil`：不超过 1 立方尺的物件清洁/弄脏；
- `minor_sensation`：不超过 1 立方尺的非活体物质，温暖/变冷/调味 1 小时；
- `magic_mark`：物件或表面的色斑、小印记或徽记，1 小时；
- `minor_creation`：不超过手掌大小的非魔法小饰品/虚幻图像，至下个施法者回合结束。

同一个 consumer 负责 typed mode choice、object/surface target、10-foot range、
size/nonliving/harmless validation、即时与 timed expiry、next-turn expiry、
dismissal、最多三个不同非即时 effect、snapshot CAS、exact replay/payload drift、
`OperationTransaction` 与 spell rollback boundary。

## Evidence and projection

- Focused suite：`backend/tests/test_round_LIII_prestidigitation_object_effect.py`，11/11。
- Validator：`scripts/validate-round-LIII-prestidigitation-object-effect.py`。
- Artifact：`data/content-ir/compiled/production-runtime-results-LIII.json`。
- Report：`reports/round-LIII-prestidigitation-object-effect-2026-08-14.json`。
- Loader-derived projection：`208 production / 30 compile-only / 111 unique compiled`。
- Validator artifact/report 两次运行 byte-identical。
- Report SHA-256：`27e7c05430d19929ed83c43876607512ca09fd69e08506ab98c13acae0068d42`。
- Artifact SHA-256：`25e729bd382bd3af5ea64933e9280c718cf4ae9ffdd678c8ac83e8b765348bfd`。

## Gates and protection

Round XLIII historical report SHA 保持
`98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f`；
`backend/tests/ollama.py` SHA 保持
`8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab`；
`backend/tests/integrations/` 未修改。无 push。
全 backend pytest：`1143 passed, 1 warning`。
