# Tasha Genie Vessel source-boundary audit — Round XLI

## Source boundary

真实 source record：

- record: `98620543cf94e974361c6567`
- fingerprint: `e81b718b2ee8728e75cf77c2f00c33312a283a9e12d3654d9bb377a64ec745c7`
- path: `塔莎的万事坩埚/玩家选项/职业/邪术师（TCE）/巨灵宗主.html`
- authored IR: `data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/genie-bottled-respite.json`

本轮选定的是 1 级 `Bottled Respite`。source-bound contract 为：

- 以一个动作进入；必须触碰器皿。
- 施法者本人进入；`Sanctuary Vessel` 的 10 级“最多 5 个可见自愿生物、30 尺内、逐出、短休”不属于本 feature，已明确排除。
- 器皿为微型物件；内部是半径 20 尺、高 20 尺的圆柱形异次元空间，温度适宜，有垫子与茶几。
- 停留时长是熟练加值的两倍小时，不是固定 8 小时。
- 死亡、器皿摧毁、附赠动作离开都会使施法者提前离开；出口是器皿最近的未占据空间。
- 器皿内物品留在其中；器皿摧毁时物品完好地转移到最近未占据空间。
- 进入后直到完成一次长休前不能再次进入。
- 器皿外观来自 source D6 表：油灯、瓮、戒指、塞住的瓶子、空心小雕像、华丽提灯。

机器矩阵见：
`reports/tashas-genie-vessel-source-boundary-2026-08-13.json`

## Implemented generic seam

新增名称无关 `vessel.space.v1` domain state machine，复用既有 source provenance、CAS/replay/rollback 约定。它覆盖：

- create / enter / exit / destroy / owner-death / long-rest lifecycle；
- 触碰、施法者所有权、动作可用、自愿、可见、容量、重复/嵌套进入等 authoritative facts；
- occupant/item containment state；
- 最近未占据空间的退出/摧毁转移事实门禁；
- long-rest 后重新开放进入；
- 固定 source-bound appearance enum、20×20 cylinder interior 与 PB×2 duration source。

新增 `configure_vessel_space` operator、typed materializer 和 `vessel.space` capability descriptor。该 descriptor 明确为 `production_partial`，没有伪造 formal vessel persistence、containment item consumer、RestService scoped-rest consumer 或真实 runtime API receipts。

## Verification and reconciliation

- vessel dynamic degradation/unit tests：通过；
- compiler degradation test：通过，feature 仍为 `partial`；
- focused suite：22 passed；
- backend full pytest：通过，仅既有 Starlette/httpx deprecation warning；
- backend Ruff：通过；
- compileall：通过；
- `git diff --check`：通过；
- audit 双跑 SHA-256：`f1a94ad9a480a1b493eda2f151e8b5d3dd9e0df7cee9643f0e778092ccd68f4c`；
- exploratory whole-pack 双跑 stdout SHA-256：`bca4a2a6a922e283847029a05c59c3e7c6ad84e646e21ec34879d3f74fd05c3c`。其临时生成物已恢复，未作为正式 promotion evidence。

正式 baseline/delta（沿用 HEAD evidence projection）：

- Tasha：`106 authored / 105 compile_full / 105 preview / 101 production / 2 compile-only`，delta 全 0；
- project：`201 production / 35 compile-only / 111 unique compiled`，delta 全 0。

## Promotion

结论：继续 `compile-only`，不 promotion。

未闭合项：正式 vessel persistence/API、entity containment consumer、物品取出与摧毁转移 receipt、SpatialAuthority 最近未占据空间真实 producer、RestService 作用域短休与 10 级 companion contract。请求方不得伪造容量、PB、位置、自愿状态、占位或空间事实。

本轮未修改/提交 `backend/tests/integrations/`、`backend/tests/ollama.py`；未写 formal DB/registry、source corpus、campaign/character 或 3D。
