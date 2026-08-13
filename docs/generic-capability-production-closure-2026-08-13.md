# Generic capability production closure — 2026-08-13

本轮关闭两个名称无关平台能力：`entity.senses` 与 `spell.slot.reactivation`。telepathic sharing 不属于本能力合同，保持独立边界，不计入 closure。

## Matrix delta

- `entity.senses`: `production_partial` → `production_closed`，consumer `entity.senses.v1`
- `spell.slot.reactivation`: `production_partial` → `production_closed`，consumer `spell.slot.reactivation.v1`
- production feature/content counts：不变；本轮没有把 scribe 自动升为 production

## Evidence

- typed provenance、owner/entity binding、active lifecycle、hearing/vision/darkvision、range/LOS、preview→confirm→replay、CAS、OperationTransaction 与负向边界由 focused runtime tests 和 closure validator 覆盖。
- reactivation 覆盖任意 1–9 环位恰一、slot shortage、长休免费恢复、重复激活、rollback、stale CAS、replay、owner/resource 防伪和 terminated entity reject。
- 详细机器报告见 `reports/generic-capability-production-closure-2026-08-13.json`。
