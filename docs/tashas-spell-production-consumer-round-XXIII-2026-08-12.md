# 2026-08-12 Round XXIII：Intellect Fortress Typed Spell Defense Consumer

## 目标与选择

本轮从 Tasha 的现有 `compile-only` 内容中选择 source-complete 的
`tashas-cauldron:spell:b4ea0dc1907dd5ac08666af3`
（智能壁垒 / Intellect Fortress）。选择理由是它的真实源文已经明确声明：

- 对心灵伤害的抗性；
- 智力、感知和魅力豁免优势；
- 30 尺施法距离；
- 可见目标；
- 专注；
- 四环及以上每升一环增加一个目标；
- 多目标之间距离不超过 30 尺。

这些 clauses 可以由一个名称无关的复合 defense consumer 完整消费；召唤、容器、
光谱对象等仍需要不同的实体生命周期，不在本轮伪装成可执行。

## Source / Typed IR

- `source_record_id`: `b4ea0dc1907dd5ac08666af3`
- source path: `塔莎的万事坩埚/法术/法术详述/3环.html`
- source fingerprint:
  `f86c958ce95034df82a6a6301688c2c5117bcb4976c5bd9f15bc48d644ee8c31`
- authored IR:
  `data/content-ir/authored/batch-II/tashas-cauldron/spells/tashas-cauldron-spell-b4ea0dc1907dd5ac08666af3.json`
- compiled typed IR:
  `data/content-ir/compiled/batch-II/typed-ir/tashas-cauldron/spells/tashas-cauldron-spell-b4ea0dc1907dd5ac08666af3.json`
- compile result：`full`，5/5 typed clause results，无 blocker。

本轮保留五个 typed clauses：
`target_selection`、`concentration`、两个 `spell_modifier` 和 `upcast`。
编译副本已与 authored IR 同步，`batch-II/compile-result.json` 已定向重编译。

## 通用运行时实现

新增 production registry consumer：

```text
spell.defense.v1
```

它按 typed `spell_modifier` + `target_selection` 选择，不读取法术名称。运行时与
CombatEngine 共同完成：

- `defense_bundle` 复合 rule block；
- 每个目标独立 `CombatEffect`；
- 同一 `concentration_group_id`；
- psychic resistance 的实际伤害消费；
- Intelligence/Wisdom/Charisma save advantage 的实际消费；
- actor/target CAS；
- 30 ft range、visible target、30 ft target-group geometry；
- 四环目标数量；
- concentration replacement、group end、source lifecycle；
- spell cast rollback 与 idempotency。

角色 `resources["concentration"]` 同时接受 KnownSpell UUID 与 Content IR spell ID，
只有整个 grouped concentration effect 结束时才清理；group 仍有剩余 effect 时保持
专注资源。

## 真实隔离 SQLite 证据

Round XXIII validator 使用真实临时迁移 SQLite，写入：

- `data/content-ir/compiled/production-runtime-results-XXV.json`
- `reports/tashas-spell-production-consumer-round-XXIII-2026-08-12.json`

validator 和 receipt test 覆盖：

- compile full / batch-II compiled copy；
- registry consumers：`spell.defense.v1` 与 `spell_economy.concentration.v1`；
- preview → confirm → replay；
- psychic 11 damage → 5 adjusted damage；
- psychic resistance 与三个 save advantage；
- 四环双目标；
- 30 ft range / group distance；
- target cap；
- stale target CAS；
- grouped concentration end；
- character concentration resource cleanup；
- downstream failure rollback；
- formal database / registry unchanged；
- protected path fingerprints unchanged；
- `name_branch_count=0`。

Round XXIII validator：23 项检查全部为 `true`。focused receipt test 为 5 项，
既有 Content IR / combat 回归与本轮测试均通过。

## Whole-pack after

Round XXII 的实际基线（不是旧 prompt 中的历史数字）：

```text
Tasha: 525 atoms / 408 player-facing / 408 executable
       95 authored Typed IR / 94 compile / 94 runtime preview
       85 production / 2 DM-assisted / 87 game usable
       7 compile-only / 314 manual / 107 DM reference
Project: 185 production / 35 compile-only / 111 unique compiled
ItemSpec: 47 total / 40 compile / 40 isolated / 40 production
Formal 499: 328 full / 110 partial / 61 dm_only
```

本轮实际 after：

```text
Tasha: 525 atoms / 408 player-facing / 408 executable
       95 authored Typed IR / 94 compile / 94 runtime preview
       86 production / 2 DM-assisted / 88 game usable
       6 compile-only / 314 manual / 107 DM reference
Project: 186 production / 35 compile-only / 111 unique compiled
ItemSpec: 47 total / 40 compile / 40 isolated / 40 production
Formal 499: 328 full / 110 partial / 61 dm_only
```

净增是一个完整 registered production spell：Tasha production `+1`、game usable `+1`、
compile-only `-1`、项目 production `+1`。没有缩小 executable 分母，也没有把单个
子句拆成多个 full 条目。

## Deterministic migration evidence

连续三次 `scripts/migrate-tashas-whole-pack.py` 成功。三次 stdout SHA-256 均为：

```text
e3145aa3e6d84ec68bf2d8884057ada4fb26c40629418ee309359e843d234e74
```

三次相同的关键文件 hashes：

```text
reports/tashas-whole-pack-report-2026-08-11.json
  5fbaba85906965ee98ffa2f633381bc343047204d621a9c633f706cd3c258a56
reports/tashas-status-layer-audit-2026-08-11.json
  9fac16156274a6512909dae9c4aba8eb4dd2e56a21cecf92ce3736211118f317
reports/tashas-production-runtime-report-2026-08-11.json
  efb4f15027f3fba9d291fb1ff049bf0a0184ff61c4f9a8df5dc0a09c3ee3f9ea
reports/tashas-baseline-2026-08-11.json
  d543f32f5ab4a1da8adf006bc8528d229b210ec90e80912911b5353850dea799
data/content-ir/isolated-packs/tashas-cauldron-2026-08-11/runtime-registry.json
  04e870540abae3e8045e59b4150abbdd0ecf0804fff20941810470fe34be5852
data/content-ir/isolated-packs/tashas-cauldron-2026-08-11/atom-index.json
  7c26170433e635a3f936ca92037f215ab275c3d5ba3662a306262812b59c8bd1
docs/tashas-whole-pack-migration-closeout-2026-08-11.md
  8a59c5b9f7b1bcc8757fbb5574cb23ea39750c683b7dbd8dbca224bf75be789c
```

Whole-pack status layers remain distinct: `compile_full` / `runtime_preview_full` /
`isolated_runtime_validated` / `registered_production_full` / `game_usable`.

## 门禁与边界

- Round XXIII validator：通过；
- focused Round XXIII +既有 Content IR/combat suite：通过；
- backend full pytest：通过，保留 1 个既有 Starlette deprecation warning；
- `ruff check backend/src backend/tests`：通过；
- validator script Ruff：通过；
- backend/source compileall：通过；
- `git diff --check`：通过；
- formal database fingerprint：
  `f3abdcf57b0d71888f085ca081511df4f4f23f100066b402d49d769089fa6aad`；
- formal registry fingerprint：
  `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`；
- integrations manifest fingerprint：
  `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`；
- `backend/tests/ollama.py` fingerprint：
  `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`；
- formal registry/database、source corpus、campaign/character、3D 和两个保护路径均未写入。

## 下一轮

继续选择具有真实完整 typed contract 和通用 consumer 的最高收益内容；剩余
summon/entity、communication、maneuver eligibility、vessel、spectral-object 和完整
character-growth seams 继续 fail-closed，不迁移下一本扩展包，不增加名称分支。
