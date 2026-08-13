# Round XLIV：typed spell target fan-out seam

日期：2026-08-13。

本轮排除了已在 Round XL 中生产化的
`content.tashas-cauldron.round2.feature.scribe-manifest-mind`。从当前五条
compile-only 法术中，选择 `Longstrider` 暴露的“单生物目标 + 升环增加目标数”
作为最高置信度、可复用的最小语义簇。

## 结果

- 新增名称无关 `spell.target.fanout.v1` domain consumer。
- receipt 绑定 `content_id`、source record、source fingerprint、clause ID、
  source slot level 和解析后的 target IDs。
- 真实校验覆盖升环目标上限、最小目标数、重复目标、空目标、低于源法术等级、
  幂等 replay 与 payload drift。
- 没有新增法术名分支，也没有写入正式 database/registry/campaign/character。
- 五条候选全部保留 compile-only；本轮 promoted IDs 为空。

## Source boundary

该 seam 只覆盖 target cardinality。Longstrider 仍缺速度 +10 尺 modifier、
1 小时持久化/过期和替换/叠加语义；其余四条仍分别缺 illusion、
effect-mode lifecycle、communication capability 或 barrier/reply/silence
consumer。因此 source-complete promotion 不成立。

## Counts

Canonical before/after：project `203 production / 35 compile-only / 111 unique compiled`；
delta `0 / 0 / 0`。五条 retained IDs 与 Round XLIII 相同。

## Verification

- focused `backend/tests/test_typed_spell_targets.py`：通过。
- Round XLIV validator：通过；validator stdout/report 应可重复生成 byte-identical。
- protected `backend/tests/integrations/` 与 `backend/tests/ollama.py` 未修改。
