# Round XLV：typed spell timed-modifier persistence seam

日期：2026-08-13。

本轮选择 Longstrider 暴露的“速度 +10 尺、持续 1 小时”作为共享语义边界，
补齐名称无关的 `spell.timed_modifier.v1`。它复用现有 combatant snapshot 的
限时 modifier 生命周期，但不按法术名 dispatch。

## 实现

- `TypedSpellTimedModifierSpec` 要求 content/source provenance、typed target、
  `speed_ft`/`jump_distance_ft`、整数 add 修正和显式分钟/小时持续时间。
- `apply_typed_spell_timed_modifier` 写入 source-bound modifier、expiry 和版本；
  同一 source+target 只保留一条记录，避免隐式叠加。
- stale CAS、坏状态、未知 stat、非法 duration、错误 stacking 和 replay payload
  drift 均 fail closed。
- production registry 新增 `spell.timed_modifier.v1`，要求
  `timed_modifier + target_selection + duration` 三类 typed block。

## Promotion boundary

五条候选全部继续 compile-only。Longstrider 仍缺真实 known-spell producer/runtime
fixture 和 source-complete replacement/stacking 证据；其余四条仍缺各自 illusion、
effect-mode 或 communication/barrier 语义。因此 promoted IDs 为空，本轮只交付
可复用 seam，不改变 canonical counts。

## Counts and evidence

- Project：`203 production / 35 compile-only / 111 unique compiled`，unchanged。
- Focused tests：`test_typed_spell_timed_modifiers.py` 与
  `test_content_ir_production_closure.py`。
- Evidence：validator、report、focused tests；protected paths 未修改。
