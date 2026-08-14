# Round LII：generic illusion lifecycle / inspection consumer

日期：2026-08-14  
基线：`951ef198533ae9378c638bd05f66ed1066ee9cb8`

## 决策

接受 Disguise Self 通过名称无关的 `spell.illusion.lifecycle.v1` generic
consumer；Prestidigitation 仍 compile-only。没有新增 spell-name/ID dispatch，
没有写 formal registry、formal database、campaign 或 character persistent data。

## Source/runtime boundary

新增 typed `TypedSpellIllusionSpec` / receipt，覆盖：

- self target、1-hour expiry；
- clothing / armor / weapons carried envelope；
- height delta `-1/0/+1`、可变体态、limb arrangement 必须 preserve；
- caster-chosen illusion area；
- physical inspection `passes_through`；
- Research action + Intelligence (Investigation) against persisted spell save DC；
- expiry/termination state and receipt；
- preview → confirm → actor CAS → OperationTransaction → exact replay/payload-drift rejection。

Runtime selects the consumer from typed `illusion_lifecycle` blocks. No Disguise
Self ID branch exists.

## Evidence and projection

- Focused suite: `backend/tests/test_round_LII_illusion_lifecycle.py`, 3 passed.
- Validator: `scripts/validate-round-LII-illusion-lifecycle.py`.
- Artifact: `data/content-ir/compiled/production-runtime-results-LII.json`.
- Report: `reports/round-LII-illusion-lifecycle-2026-08-14.json`.
- Canonical set projection: `207 production / 31 compile-only / 111 unique compiled`.
- Validator stdout/report/artifact were byte-identical across two runs.
- Report SHA-256: `23252ff2e2cc218ca0e9aa927c93ffafd2eee7191755fe45d1be25310406c98c`.
- Artifact SHA-256: `ba613a4e4548b0549159645bd66469b68db3477885fd48d1525884b6e916c3c6`.
- Validator stdout SHA-256: `f3a2f7d1be67d48e340c45eeff02de1983a217d72e65c8dc30a4fe02fe2f1738`.

## Gates and protection

Ruff on the changed files, compileall, `git diff --check`, and full backend
pytest all pass. Full backend pytest is `1129 passed, 1 warning`. Round XLIII report SHA
remains `98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f`;
protected `backend/tests/ollama.py` SHA remains
`8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`.
The existing untracked integration files remain untouched. No push.
