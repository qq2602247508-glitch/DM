# 《塔莎的万事坩埚》Round XXIV：召唤法术生产消费者

日期：2026-08-12

本轮关闭两条 source-complete Typed IR 召唤法术：

- `tashas-cauldron:spell:54c8c29188db1442473d9dc1`：野兽召唤术 / Summon Beast
- `tashas-cauldron:spell:083419d9de551806a5ca9748`：亡灵召唤术 / Summon Undead

## 覆盖内容

两条法术均保留四条 typed clauses：

- `target_selection`
- `summon_or_creation`
- `concentration`
- `upcast`

通用 `spell.summon.v1` consumer 现在真实消费：

- typed choice 与 variant stat block
- HP / AC / slot-level scaling
- speed 与结构化 movement modes
- action economy 与 shared initiative
- range、visible、unoccupied destination geometry
- structured actions、damage defenses、condition immunities
- duration、concentration、source/summon lifecycle
- spell-slot rollback、CAS、preview/confirm/replay

`default_behavior` 不再只是 snapshot 字段。对于 player-controlled ally summon，在其回合开始且没有口头命令时，通用 Combat lifecycle 会：

1. 消费 action 执行 Dodge；
2. 选择最近的权威 hostile grid position 作为危险源；
3. 按现有 grid obstacle、边界和占用规则尽可能远离危险；
4. 将行为、移动结果和 `CombatAction` 审计写入回合交易。

缺少权威危险位置时不会猜测路径，而是保留明确的 DM review 状态。

## 真实状态变化

数据来源：

- `reports/tashas-content-atom-catalog-II-2026-08-11.json`
- `reports/tashas-whole-pack-report-2026-08-11.json`
- `reports/tashas-baseline-2026-08-11.json`

| 指标 | Before | After |
|---|---:|---:|
| Source records | 144 | 144 |
| Content atoms after QA | 525 | 525 |
| Player-facing executable | 408 | 408 |
| Authored Typed IR | 95 | 95 |
| Compile full | 94 | 94 |
| Runtime preview full | 94 | 94 |
| Tasha production full | 86 | 88 |
| Tasha DM-assisted | 2 | 2 |
| Tasha game usable | 88 | 90 |
| Tasha compile-only | 6 | 4 |
| Manual authoring | 314 | 314 |
| DM reference | 107 | 107 |
| Project production full | 186 | 188 |

ItemSpec `47/40/40/40`、formal 499 `328 full / 110 partial / 61 dm_only`、正式 database 和 formal registry 均未改变。

## 验收证据

- Validator：`scripts/validate-tashas-spell-production-consumer-round-XXIV.py`
- Receipt tests：`backend/tests/test_tashas_spell_production_consumer_round_XXIV.py`
- Runtime result：`data/content-ir/compiled/production-runtime-results-XXVI.json`
- Report：`reports/tashas-spell-production-consumer-round-XXIV-2026-08-12.json`

Validator checks 全部通过，包含：

- source provenance / source checksum
- 两条法术 compile full、四条 typed clauses、consumer resolver
- choice、HP/AC scaling、movement modes、defenses/actions
- range / visible / unoccupied geometry
- action economy / shared initiative
- duration / concentration / source lifecycle
- summon zero-HP lifecycle
- default Dodge + move-away generic execution
- spell-slot rollback
- preview / confirm / replay
- formal/protected boundary 与 name-branch-free

验证命令：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  scripts/validate-tashas-spell-production-consumer-round-XXIV.py

PYTHONPATH=backend/src backend/.venv/bin/pytest -q \
  backend/tests/test_tashas_spell_production_consumer_round_XXIV.py \
  backend/tests/test_combat_summons.py \
  backend/tests/test_content_ir_workbench.py \
  backend/tests/test_content_ir_batch_workbench.py \
  backend/tests/test_content_ir_production_runtime_batch_II.py

PYTHONPATH=backend/src backend/.venv/bin/pytest -q backend/tests
backend/.venv/bin/ruff check scripts/validate-tashas-spell-production-consumer-round-XXIV.py backend/src backend/tests
backend/.venv/bin/python -m compileall -q backend/src
git diff --check
```

结果：validator 全部 checks 通过，focused `38 passed`，backend 全量通过；仅保留既有 Starlette/httpx deprecation warning。

本轮没有修改 source corpus、正式 database、formal registry、campaign、character、3D 项目或永久保护路径；`name_branch_count=0`。

提交与推送：`22f78e7`（实现）与 `0932a0f`（证据/交接）已推送到 `origin/main`。
