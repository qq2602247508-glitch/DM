# Round LII：generic illusion lifecycle / inspection consumer

日期：2026-08-14  
基线：`c5ced8c55b75eb83dc0dd6b114f5a82196a7efdc`

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

- Focused suite: `backend/tests/test_round_LII_illusion_lifecycle.py`, 6 passed.
- Validator: `scripts/validate-round-LII-illusion-lifecycle.py`.
- Artifact: `data/content-ir/compiled/production-runtime-results-LII.json`.
- Report: `reports/round-LII-illusion-lifecycle-2026-08-14.json`.
- Canonical set projection: `207 production / 31 compile-only / 111 unique compiled`.
- Validator stdout/report/artifact were byte-identical across two runs.
- Report SHA-256: `91a9953892412a065d5f10f25a3d196bb22f93034ef68301a3663680f2dcbb9b`.
- Artifact SHA-256: `26fa5f66f2f762199f6cb38b0fbc282e3e7dd16b683e36b1963edfb1d4c1c926`.
- Validator stdout SHA-256: `86b86a75a637237831a4dfb65fcf6a69d3244d57744d6a54c73965998b8c871b`.

## Gates and protection

Ruff on the changed files, compileall, `git diff --check`, and full backend
pytest all pass. Full backend pytest is `1132 passed, 1 warning`. Round XLIII report SHA
remains `98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f`;
protected `backend/tests/ollama.py` SHA remains
`8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`.
The existing untracked integration files remain untouched. No push.
