# Goal Round Ledger

本 Ledger 记录持续 Goal 的独立生产 Round。状态层严格区分：

`compile_full → runtime_preview_full → isolated_runtime_validated → registered_production_full → game_usable`

其中 `game_usable = registered_production_full + dm_assisted`。隔离 pack 不得自动成为正式 registry。

## Round 27：Fathomless Oceanic Soul Generic Communication Consumer

当前状态：`accepted`；实现、receipt、报告、文档、全量门禁、分离提交和 push 均已完成。

- 海渊魂灵（深海意志邪术师 6 级）补齐 source-complete 两个 typed clauses：`cold-resistance`（寒冷抗性）与 `underwater-communication`（水下互相语言理解）。后者由名称无关的 `grant_communication` operator（`channel=speech`、`direction=mutual`、`required_condition=submerged`）materializer 生成，并使用 `communication.mutual_comprehension.v1` consumer。
- `ContentIRRuntimeService` 增加 `resolution_kind=communication` 分支：真实检查 actor 与 target 均满足 `required_condition`（submerged），任一不满足即 fail closed（400）；preview→confirm→replay、actor stale 409 CAS、OperationTransaction applied 全通过。顺带修复 `_preview_feature` 非 teleport 分支未初始化 `teleport_preview` 的潜在 `UnboundLocalError`。
- Round XXVII validator 16/16 checks 为 true；focused Round XXVII receipt suite 3 passed；backend 全量 pytest 929 passed（仅既有 Starlette/httpx deprecation warning）；Ruff、compileall、diff-check 通过；whole-pack migration 双跑 projection SHA-256 均为 `355b53211546f3110823566b909d1f34c85dea35d42b5205cead3c863fa5d7e7`。
- Actual after：Tasha `525/408/408/95/94/94/90/2/92/2/314/107`；ItemSpec `47/40/40/40`；项目 `190 production / 35 compile-only / 111 unique compiled`；Tasha evidence union `133`，project evidence union `190`。content-ID funnel 为 `95 = 91 + 2 + 2`。
- 证据入口：`docs/tashas-feature-production-consumer-round-XXVII-2026-08-13.md`、`scripts/validate-tashas-feature-production-consumer-round-XXVII.py`、`backend/tests/test_tashas_feature_production_consumer_round_XXVII.py`、`reports/tashas-feature-production-consumer-round-XXVII-2026-08-13.json`、`data/content-ir/compiled/production-runtime-results-XXVIII.json`。
- 保护路径、正式 database、formal registry、source corpus、campaign/character 与 3D 未写入；`name_branch_count=0`。下一轮继续 vessel、spectral-object、entity lifecycle 与 character-growth seams，不迁移下一本扩展包。
- 保护指纹保持 database `f3abdcf57b0d71888f085ca081511df4f4e23f100066b402d49d769089fa6aad`、formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、integrations manifest `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。
- Push receipt：`f1e8d0d`、`6d084e2`、`2fdd27d`、`01db99e` 已推送到 `origin/main`（`6f81789..01db99e`，2026-08-13）。

## Round 26：Ambush Generic Initiative / Roll Intervention Consumer

当前状态：`accepted`；实现、receipt、报告、文档、全量门禁、分离提交和 push 均已完成。

- 战斗大师「伏击」补齐 source-complete 两个 typed clauses：`ambush:initiative` 与 `ambush:stealth`。两者都由名称无关的 `roll_intervention` materializer 生成，并使用同一 `combat_engine.roll_intervention.v1` consumer。
- 先攻分支通过真实隔离 HTTP/SQLite：冻结先攻结果、持久化 `initiative_roll_prompt`、superiority die 输入、资源 `4→3`、CombatAction confirmed、OperationTransaction applied、拒绝不扣资源、同 request replay 不重复扣资源。
- Round XXVI validator 13/13 checks 为 true；Round XXV reconciliation validator 18/18 checks 为 true；focused Round XXV/XXVI receipt suite 8 passed；backend 全量 pytest 926 passed（仅既有 Starlette/httpx deprecation warning）；Ruff、compileall、diff-check 通过；whole-pack migration 双跑 stdout SHA-256 均为 `e87a73fac5289a265cf7a5b780daa5546d20ce739ab52e9bf7d313f1eb5c8fbe`。
- Actual after：Tasha `525/408/408/95/94/94/89/2/91/3/314/107`；ItemSpec `47/40/40/40`；项目 `189 production / 35 compile-only / 111 unique compiled`；Tasha evidence union `132`，project evidence union `189`。
- 当前 `build_migration()` status-layer projection 的 `authored_typed_ir=94` 与 conversion/content-ID projection 的 `95` 保持分离；content-ID funnel 为 `95 = 90 + 2 + 3`。角色成长总体仍是 `bounded_partial`。
- 证据入口：`docs/tashas-feature-production-consumer-round-XXVI-2026-08-12.md`、`scripts/validate-tashas-feature-production-consumer-round-XXVI.py`、`backend/tests/test_tashas_feature_production_consumer_round_XXVI.py`、`reports/tashas-feature-production-consumer-round-XXVI-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-XXVII.json`。
- 保护路径、正式 database、formal registry、source corpus、campaign/character 与 3D 未写入；`name_branch_count=0`。下一轮继续 source-complete generic consumer，不迁移下一本扩展包。
- 保护指纹保持 database `f3abdcf57b0d71888f085ca081511df4f4e23f100066b402d49d769089fa6aad`、formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、integrations manifest `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。
- Push receipt：`feb5fb7`、`d4fa353`、`3b08410`、`bb61ae1`、`74bb1d2` 已推送到 `origin/main`（`a7f8586..74bb1d2`）。

## Round 25：Production Evidence / Status Reconciliation

当前状态：`accepted`；代码、evidence、全量门禁、交接和 push 已完成。

- 新增共享 `content_ir_production_evidence` loader：按 pack namespace、content kind、required checks 与 `name_branch_count` gate 过滤，并按 content ID 去重。当前 Tasha receipt union 为 131 条，项目 union 为 188 条，ItemSpec valid production evidence 为 40 条。
- whole-pack migration 与 `existing_project_production_ids()` 共享 evidence projection；Round XXIV 的 Summon Beast / Summon Undead 两条 receipt 已正确进入 Tasha production union。
- ItemSpec catalog 显式发布 `dm_assisted` 与 canonical status layers；`game_usable = registered_production_full + dm_assisted`，当前为 `40 = 40 + 0`。
- 当前 Tasha funnel：`144 source records / 525 atoms / 408 executable / 95 authored Typed IR / 94 compile / 94 preview / 88 production / 2 DM-assisted / 90 game usable / 4 compile-only / 314 manual / 107 DM reference`。项目为 `188 production / 35 compile-only / 111 unique compiled`。
- Round XXV validator 17/17 checks 通过；focused reconciliation suite `18 passed`；backend 全量 pytest 通过；Ruff、compileall、diff-check 通过；whole-pack migration 双跑 stdout SHA-256 均为 `f49d04eeb7158151289e61216da4e2908bf075d5d0777a0c24408c19a0630677`。
- database、formal registry、source corpus、campaign/character、3D 与永久保护路径未写入。当前 database fingerprint 为 `f3abdcf57b0d71888f085ca081511df4f4e23f100066b402d49d769089fa6aad`；formal registry 为 `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`。
- 证据入口：`scripts/validate-tashas-production-reconciliation-round-XXV.py`、`backend/tests/test_tashas_production_reconciliation_round_XXV.py`、`reports/tashas-production-reconciliation-round-XXV-2026-08-12.json`、`docs/tashas-production-reconciliation-round-XXV-2026-08-12.md`。
- Push receipt：`1b155dd`、`d0b6846`、`10bf95b`、`d304924` 已推送至 `origin/main`。

## Round 24：Summon Beast / Summon Undead Typed Summon Consumer

当前状态：`accepted`；实现、evidence、全量门禁、交接和 push 已完成。

- 本轮关闭两条 source-complete summon SpellSpec：`tashas-cauldron:spell:54c8c29188db1442473d9dc1` 与 `tashas-cauldron:spell:083419d9de551806a5ca9748`。每条保留四条 typed clauses：`target_selection`、`summon_or_creation`、`concentration`、`upcast`；source provenance/checksum/clause boundaries 未改动。
- 新增/接入名称无关 `spell.summon.v1`，真实消费 choice/stat block、HP/AC scaling、movement modes、structured actions/defenses、90 尺 visible/unoccupied geometry、action economy、shared initiative、duration/concentration、source/summon lifecycle、spell-slot rollback、CAS 与 preview/confirm/replay。
- `default_behavior` 已由 generic Combat lifecycle 自动执行：player-controlled ally summon 无口头命令时消费 action Dodge，并按最近 hostile grid position 与现有障碍/边界/占用规则远离危险；无权威位置时 fail closed 为 DM review。执行结果写入回合审计与 transaction snapshot。
- Actual before→after：Tasha `525/408/408/95/94/94/86/2/88/6/314/107` → `525/408/408/95/94/94/88/2/90/4/314/107`（atoms/player-facing/executable/authored/compile/preview/production/dm-assisted/game usable/compile-only/manual/DM reference）；项目 production `186→188`，compile-only `35`，unique compiled `111`；ItemSpec `47/40/40/40`；formal 499 `328/110/61`。
- Validator 全部 checks 通过；focused `38 passed`；backend full pytest、Ruff、`backend/src` compileall、diff-check 通过，仅有既有 Starlette/httpx deprecation warning。证据入口：Round XXIV validator/test/report/result/doc。
- 正式 database/registry、source corpus、campaign/character、3D 与两个永久保护路径未写入；`name_branch_count=0`。下一轮继续 communication、maneuver eligibility、vessel、spectral-object 和未闭合 character-growth 的 generic consumer，不迁移下一本扩展包。
- Push receipt：实现 `22f78e7`、证据 `0932a0f`、最终交接 `e52d31c` 已推送到 `origin/main`。

## Round 23：Intellect Fortress Typed Spell Defense Consumer

当前状态：`accepted`；实现、evidence、全量门禁、交接和 push 已完成。

- 本轮选择 source-complete `tashas-cauldron:spell:b4ea0dc1907dd5ac08666af3`，保留五条真实 typed clauses：target selection、concentration、psychic resistance、三种 save advantage、upcast target increment。
- 新增名称无关 `spell.defense.v1`，通过 `defense_bundle`、grouped `CombatEffect`、共享 concentration group、authoritative grid range/visibility/group distance、target cap、CAS、replacement、group end、rollback 和 replay 形成真实 spell production consumer。
- Round XXIII validator 在临时迁移 SQLite 上 23/23 checks 通过；receipt test 5/5；`production-runtime-results-XXV.json` 与 Round XXIII report 已生成，`name_branch_count=0`。
- Actual baseline：Tasha `525/408/408/95/94/94/85/2/87/7/314/107`；项目 production `185`、compile-only `35`、unique compiled `111`；ItemSpec `47/40/40/40`；formal 499 `328/110/61`。
- Actual after：Tasha `525/408/408/95/94/94/86/2/88/6/314/107`；项目 production `186`、compile-only `35`、unique compiled `111`；ItemSpec `47/40/40/40`；formal 499 `328/110/61`。净增一个 registered production spell，compile-only `-1`，game usable `+1`。
- 全量 backend pytest、Ruff、compileall、diff-check 通过；三次 whole-pack migration stdout SHA-256 `e3145aa3e6d84ec68bf2d8884057ada4fb26c40629418ee309359e843d234e74`，关键报告/runtime/isolated hashes 三次一致。
- protected/formal fingerprints unchanged；详见 `docs/tashas-spell-production-consumer-round-XXIII-2026-08-12.md`、Round XXIII validator/test/report/result。待提交：实现/evidence 与 docs/ledger 分离提交，push 后改为 `accepted`。

## Round 22：Soulknife Psychic Teleportation Typed Feature Consumer

当前状态：`accepted`；实现、隔离 evidence、全量回归、提交与 push 已完成。

- 本轮关闭 source-complete `content.tashas-cauldron.round2.feature.soulknife-psychic-teleportation`：新增通用 `teleport` operator 与 `movement.teleport` capability，Typed IR 组合 `psionic_dice` 单次消耗、bonus action、可见未占据空间和 `movement_roll_total × 10 ft` 距离上限。
- 复用既有 `combat_engine.feature_action.v1` 与 authoritative grid teleport consumer；Content IR request/preview/confirm 正式保留目的地行列和掷骰输入，没有 feature-name dispatch。
- 隔离 SQLite 证明占据目的地失败回滚、合法 `(2,2)→(2,6)` 20 尺传送、资源 `3→2`、bonus action、CAS、OperationTransaction、preview→confirm→replay 和幂等；`name_branch=0`。
- Round XXII after：Tasha `525/408/408/95/94/94/85/2/87/7/314/107`（atoms/player-facing/executable/authored/compile/preview/production/dm-assisted/game usable/compile-only/manual/DM reference）；项目 production full `185`、compile-only `35`、unique compiled `111`；ItemSpec `47/40/40/40`。formal 499 保持 `328/110/61`。
- 证据：`docs/tashas-feature-production-consumer-round-XXII-2026-08-12.md`、Round XXII validator/test/report/result、whole-pack reports 与 isolated runtime registry。validator、backend full pytest `903 passed, 1 warning`、`backend/src`+`backend/tests` Ruff、compileall、diff-check、whole-pack migration 共 6 次成功运行，最终两次关键 hash 一致。
- 本轮为 movement/feature-action platform-core exception（1 条，正常批次门槛 8）。正式 registry/database、source corpus、3D 和永久保护路径未写入；实现提交 `da93a60`、证据修正 `816a9dc` 已推送，receipt 单独记录。

## Round 21：Psionic Sorcery Typed Spell-Context Consumer

当前状态：`accepted`；实现、隔离 evidence、全量回归、提交与 push 已完成。

- 本轮关闭 `content.tashas-cauldron.round2.feature.aberrant-mind-psionic-sorcery` 的两个完整 typed spell-context clauses：`component-override` 忽略非费用成分，`payment-override` 以等同法术环阶的 `sorcery_points` 替代 `spell_slot`。这是 spell-economy/context platform-core exception，正常批次门槛为 8。
- 新增名称无关 `spell.context.v1` consumer；Feature compiler/materializer 持久化 `spell_context`，ContentIRRuntimeService 绑定 actor snapshot 的显式 `psionic_spell=true` metadata，SpellEconomyService 通过资源 CAS、法术交易、OperationTransaction、preview/confirm/replay 和 rollback 完成真实闭环，没有 Feature/spell name branch。
- 真实隔离 SQLite：材料不可用仍能施展 1 环法术，法术位 `2→2`、灵能点 `3→2`；重放幂等、下游失败 rollback、snapshot/transaction 和 formal boundary 全通过，`name_branch=0`。
- Round XXI after：Tasha `525/408/408/95/94/94/84/2/86/8/314/107`（atoms/player-facing/executable/authored/compile/preview/production/dm-assisted/game usable/compile-only/manual/DM reference）；当前项目 production full `184`；ItemSpec 保持 `47/40/40/40`。formal 499 保持 `328 full / 110 partial / 61 dm_only`。
- Round XXI validator 1/1、focused tests、Ruff、compileall、diff-check、backend full pytest `902 passed, 1 warning` 均通过；whole-pack migration stdout 与连续三次 runtime/report/status/baseline/production report SHA-256 一致。formal database/registry/campaign/character、source corpus、3D、保护路径未写入。
- 实现提交 `2066902` 已推送到 `origin/main`；receipt 已写入 ledger/handoff/plan/Round XXI doc。下一步继续 summon/entity、defense、communication、maneuver eligibility、vessel、teleport destination、spectral-object seams，保持 unresolved contract fail-closed。

## Round 20：Sword Burst Generic Spell Consumer

当前状态：`accepted`；实现、隔离 evidence、全量回归、提交与 push 已完成。

- 选中唯一仍具完整通用消费者覆盖的 compile-only spell：`tashas-cauldron:spell:eec6bd94eb83a351fb987de2`（剑刃爆发 / Sword Burst）。source text 逐字段复核了 5 尺球形范围、敏捷豁免、失败 1d6 力场伤害和 5/11/17 级戏法强化；source fingerprint、reviewed fields、manual decisions 和 source evidence 均保留。
- 新增名称无关的 `spell.cantrip_scaling.v1` registry descriptor。`ContentIRRuntimeService` 从角色当前等级消费 typed `upcast.progression`，再交给既有 `combat_engine.area_damage.v1` 与 `combat_engine.damage_heal.v1`；没有 spell-name dispatch。
- 临时 SQLite 真实 API evidence：等级 5 的两个范围目标各受到 8 点，等级 1/5/11/17 的 scaling 为 1d6/2d6/3d6/4d6；成功豁免为 0 伤害。preview→confirm→replay、双目标 CAS、OperationTransaction、stale 409、下游失败 rollback 全通过，name branch=0。
- Round XX after：Tasha `525/408/408/95/94/94/83/2/85/9/314/107`（atoms/player-facing/executable/authored/compile/preview/production/dm-assisted/game usable/compile-only/manual/DM reference）；当前项目 production full `183`；ItemSpec 保持 `47/40/40/40`。
- 召唤术、智能壁垒、Oceanic Soul、Ambush、Bottled Respite、Psychic Teleportation、Psionic Sorcery、Manifest Mind 继续保持真实 entity/defense/eligibility/vessel/teleport/spectral/payment blocker，不因本轮通用 spell seam 被伪升 full。

证据：`docs/tashas-spell-production-consumer-round-XX-2026-08-12.md`、Round XX validator/test/report/result、whole-pack report 与 isolated runtime registry。正式 database/registry/campaign/character、source corpus、3D、保护路径未写入；下一步在全量门禁和 push 后继续下一个有完整 generic consumer 的 typed cluster。

## Round 19：Character Growth / Implements of Mercy Closure

当前状态：`accepted`；实现、隔离 evidence、全量回归、提交与 push 已完成。

- `content.tashas-cauldron.feature.way-of-mercy.implements-of-mercy` 的洞悉、医药、草药工具三条 typed proficiency clause 通过既有 `advancement_service.character_growth.v1`，真实 preview→confirm→幂等 replay、character CAS、OperationTransaction、feature snapshot 全通过，`name_branch=0`。
- 本轮只有 1 条，是 character-growth core exception：一个完整 Feature 同时关闭三条角色授予；没有新增特性名分支。Oceanic Soul、Ambush、Bottled Respite、Psychic Teleportation、Psionic Sorcery、Manifest Mind 继续按未建模语义保持边界。
- Tasha status layers：`production_full=82`（81→82）、`dm_assisted=2`、`game_usable=84`、`compile_only=10`（11→10）、`authored Typed IR=95`、`compile_full=94`、`runtime_preview_full=94`、`manual_authoring=314`。当前项目 production full `182`；ItemSpec 独立保持 `47/40/40/40`。
- 证据：`docs/tashas-feature-production-consumer-round-XIX-2026-08-12.md`、Round XIX report/result、whole-pack report 与 isolated runtime registry。Round XIX validator、Ruff、compileall、diff-check、全量 backend pytest `896 passed` 已通过；migration 两次关键 hash 一致。
- 实现提交 `e09e804eef50552fd9a6af24ab8146168c4f0d03` 已推送到 `origin/main`；receipt 已写入 ledger/handoff/memory。下一步继续下一个有真实 generic consumer 的 typed semantic cluster。

## Round 18：Generic Roll Intervention / Battle Master Closure

当前状态：`accepted`；实现、隔离 evidence、提交与 push 已完成。

- 新增通用 typed `roll_intervention` materializer/consumer：领导风范绑定魅力社交检定，精准攻击绑定 `weapon_attack` 的 AC 攻击检定；actor-side Feature Runtime 会进入玩家掷骰窗口，`attack_type` 进入 schema/resolver eligibility，非武器攻击 fail closed。
- 两条 Feature 在隔离 SQLite 上真实完成 preview/open → confirm → 幂等 replay、卓越骰输入、character version CAS、OperationTransaction/资源事务：领导风范 `12+4=16`、`4→3`；精准攻击 `12+5=17`、`3→2`；spell attack 不开精准攻击窗口，`name_branch=0`。
- atomizer 新增通用 source-declared authored subclause atom 桥，精准攻击从旧显式 retirement 恢复为可追溯独立 atom；整包分母变为 `525 atoms / 408 player-facing / 408 executable`，source records 仍 `144`。
- Tasha status layers：`production_full=81`、`dm_assisted=2`、`game_usable=83`、`compile_only=11`、`authored Typed IR=95`、`compile_full=94`、`runtime_preview_full=94`、`manual_authoring=314`、`DM reference=107`。ItemSpec 独立维持 `47/40/40/40`（total/compile/isolated/registered/game usable）。当前项目 production full `181`。
- 本轮只有 2 条，是共享玩家掷骰/actor resource CAS 的 platform-core exception；Ambush 因敏捷（隐匿）与先攻双触发尚未形成完整 typed eligibility，继续 fail closed。formal registry/database、campaign/character、source corpus、3D 与保护路径未写入。
- 证据：`docs/tashas-feature-production-consumer-round-XVIII-2026-08-12.md`、Round XVIII report/result、Feature contract/character-growth/rest validators、whole-pack report 与 isolated runtime registry。第二、第三次 whole-pack migration 关键 SHA-256 完全一致。
- 实现提交 `0509c93a9c7cd7462c67098a1b0c53d709d0fba3` 已推送到 `origin/main`；receipt 已写入 ledger/handoff/memory。下一步继续下一个已有 typed semantic cluster，不增加名称分支。

## Round 17：Generic Rest Condition Consumer / Tireless Closure

当前状态：`accepted`；本轮完成一个平台核心消费者 seam，关闭 1 条 typed Feature 的真实生产闭环。

- `content.tashas-cauldron.round2.feature.ranger-tireless` 完成 source completeness 复核并从 partial 解锁为 full：`short_rest_completed` → self `remove_condition(exhaustion)`；compiler/materializer 产出 typed `rest_condition_effect`，不是 feature-name action。
- `RestService` 现在按 typed trigger/rest/condition/effect_kind 消费短休状态效果；兼容旧 registry 的匿名 `rest_effects`，移除了 `actions["tireless"]` name dispatch。rest 场景对非 exhaustion condition fail closed。
- 真实隔离 SQLite 上完成 preview→confirm→幂等 replay：力竭 `3→2`、character CAS、OperationTransaction、condition persistence、相同 `rest_record_id` replay 全通过，`name_branch_count=0`。
- Tasha Feature status layers：`production_full=79`（78→79）、`dm_assisted=2`、`game_usable=81`、`compile_only=12`（13→12）、`authored Typed IR=94`、`runtime_preview_full=93`、`manual_authoring=314`。ItemSpec 独立保持 `47/40/40/40`（total/compile/isolated/registered/game usable 的 registered/game 口径为 40）。当前项目 production full `179`。
- 本轮只有 1 条，是因为它是关闭通用 Rest/condition consumer 的核心增长，不是把单条内容冒充普通批次。Oceanic Soul、Bottled Respite、Psychic Teleportation、Manifest Mind、Psionic Sorcery、Ambush/Commanding Presence 与 7 条 partial ItemSpec 仍保持各自语义边界。
- 正式 registry/database/campaign/character、source corpus、3D 与永久保护路径未写入。Round XVII validator 与 whole-pack migration 重跑后关键 report/runtime SHA-256 保持一致；专门 Rest API 2 项通过。
- 证据：`docs/tashas-feature-production-consumer-round-XVII-2026-08-12.md`、Round XVII report/result、Round-II feature runtime report、whole-pack migration 输出；实现提交 `ecde5e8ccb79bc622f6a179af9e95b8bb39d1e3d` 已推送到 `origin/main`。
- 下一步：继续已有 typed IR 的通用 event/entity/teleport/payment consumer；不为随机表、实体、通信或 DM 裁定增加名称分支。

## Round 16：Character Growth Proficiency Consumer Expansion

当前状态：`accepted`；本轮完成 4 条安全 proficiency FeatureSpec 的真实角色成长 evidence，已提交推送。

- Battle Smith、Armorer、Alchemist、Artillerist 的工具熟练通过真实 `advancement_service.character_growth.v1` preview → confirm → 幂等 replay；4/4、5 个 proficiency grants、character CAS、OperationTransaction、feature snapshot 全通过，name branch=0。
- Feature Tasha status layers：`production_full=78`（74→78）、`dm_assisted=2`、`game_usable=80`；`compile_only=13`、`authored Typed IR=94`、`runtime_preview_full=93`、`manual_authoring=314`。ItemSpec 独立维持 `40/40/40`（compile/registered/game usable）。
- 本轮只有 4 条，因为它们是当前剩余 compile-only 中唯一无未建模通信、实体、随机表或 DM 语义的安全 proficiency cluster；Oceanic Soul 的水下互通仍阻止 full，不被抗性子句单独冒充完成。
- formal registry/database、campaign/character、source corpus 未写入；Bottled Respite、Psychic Teleportation、Manifest Mind、Tireless、Psionic Sorcery 和两条战技继续保持各自 typed/manual 边界。
- Round XVI validator、whole-pack migration 各运行两次且 byte-identical；Round X–XVI 定向测试 22 项、backend 全量 pytest 891 项、Ruff、compileall 和 `git diff --check` 通过。
- 证据：`docs/tashas-feature-production-consumer-round-XVI-2026-08-12.md`、Round XVI report/result、Feature IR/runtime report 与 whole-pack migration 输出。
- 实现与证据提交 `d61e5ad7a5fdc313d929deac195efc2fa703e6e0` 已推送到 `origin/main`；ledger/handoff receipt 随后单独提交。
- 下一步：继续剩余 13 条 feature compile-only 与 7 条 partial ItemSpec，仅在存在通用 typed event/entity/teleport consumer 时解锁。

## Round 15：Typed Item-Cast Spell Consumer

当前状态：`accepted`；本轮解锁 3 条 artifact ItemSpec 的显式 spell list，并已提交推送。

- 解析器支持显式“施展”后的单法术与列表式 inline identities；generic “这道法术”、职业法器 prose、变量蕴法刺青仍 fail closed。鲁芭的灵魂塔罗卡、拉奥圣杖和伊格薇尔伏恶魔志从 partial 解锁为 compile/isolated full。
- `item.granted_spell.v1` 已接到 equipment action preview/transaction snapshot，返回 typed `item_spell_cast`、`grant_mode=item_cast` 和去重排序 spell identities；3/3 preview/confirm/replay、16 identities、2 charge lifecycle、6 transactions、CAS/state 全通过，name branch=0。
- ItemSpec status layers：`47 total / 40 compile_full / 40 isolated_runtime_validated / 40 registered_production_full / 40 game_usable`；项目 production full `171→174`。Feature Tasha 仍独立为 `74/2/76`。
- formal registry/database、campaign/character、source corpus 未写入；随机表、DM choice、变量 spell、entity/exhaustion 语义的剩余 7 条 partial 不因有动作文字而自动升级。
- Round XV validator、whole-pack migration 各运行两次且 byte-identical；Round X–XV 定向测试 21 项、backend 全量 pytest 890 项、Ruff、compileall 和 `git diff --check` 通过。
- 证据：`docs/tashas-item-production-consumer-round-XV-2026-08-12.md`、Round XV report/result、ItemSpec catalog 与 whole-pack migration 输出。
- 实现与证据提交 `f34148d9c6c4d40a9e965c625bc4f006b27f9a9c` 已推送到 `origin/main`；ledger/handoff receipt 随后单独提交。
- 下一步：继续剩余 7 条 partial ItemSpec 的真实 typed semantic unlock；不把 generic/variable/DM-reference prose 伪装成 production。

## Round 14：Residual Complete ItemSpec Closeout / Dawn Boundary

当前状态：`accepted`；本轮关闭剩余 5 条完整 ItemSpec，已提交并推送。

- 堕影冥界碎晶、伪装刺青、堕影冥界印记刺青、重生坩埚和凝晶年纪全部通过通用 equipment create → attunement/equip → granted action 或 charge → preview → confirm → 幂等 replay。5/5、12 个 operation transactions、2 条 tattoo lifecycle 和 1 条 charge lifecycle 通过。
- 凝晶年纪的 typed `recovery_trigger=dawn` 经真实 `RestService._item_charge_recovery()` boundary probe 验证不会被 `long_rest` 错误恢复；`name_branch_count=0`。
- ItemSpec status layers：`47 total / 37 compile_full / 37 isolated_runtime_validated / 37 registered_production_full / 37 game_usable`；项目 production full `166→171`。Feature Tasha 仍独立为 `74/2/76`。
- 本轮只有 5 条是因为它们已经是全部剩余完整合同；其余 unresolved action/spell/effect clauses 仍保持 manual/DM 边界，不被本轮 evidence 覆盖。formal registry/database、campaign/character 和 source corpus 未写入。
- Round XIV validator、whole-pack migration 各运行两次且 byte-identical；Round X–XIV 定向测试 20 项、backend 全量 pytest 889 项、Ruff、compileall 和 `git diff --check` 通过。
- 证据：`docs/tashas-item-production-consumer-round-XIV-2026-08-12.md`、Round XIV report/result、ItemSpec catalog 与 whole-pack migration 输出。
- 实现与证据提交 `d6cae79f73601fced2636050f3de97ba81a101ed` 已推送到 `origin/main`；ledger/handoff receipt 随后单独提交。
- 下一步：ItemSpec complete inventory 已全部达到 production/game usable；继续 unresolved partial clauses 的逐字段语义解锁，不把 DM-reference、manual 或 isolated-only 计入 production。

## Round 13：Additional ItemSpec Equipment Consumer Batch

当前状态：`accepted`；本轮完成 8 条真实 ItemSpec evidence，已提交并推送。

- 月镰、自然护符、巴巴·雅加的魔法扫帚、星界碎片、重复手稿、爆裂论文、防护诗篇和狂欢者风笛，全部通过临时迁移 SQLite 的 equipment create → attunement/equip → granted action 或 charge → preview → confirm → 幂等 replay。
- 8/8 create/preview/confirm/replay、typed consumer、item state、attunement CAS 和 production runtime full 通过；4 条 charge lifecycle、17 个 operation transactions，`name_branch_count=0`。
- ItemSpec status layers：`47 total / 37 compile_full / 37 isolated_runtime_validated / 32 registered_production_full / 32 game_usable`；项目 `current_project_production_full` 从 158 增至 166。Feature Tasha 仍独立为 `74/2/76`。
- formal registry/database、正式 campaign/character 和 source corpus 未写入；isolated pack 仍与正式 registry 分账。永久保护的 database、formal registry、`backend/tests/ollama.py` 与 integrations manifest 指纹保持不变。
- Round XIII validator、whole-pack migration 各运行两次且 byte-identical；targeted Tasha tests 19 项、backend 全量 pytest 888 项、Ruff、compileall 和 `git diff --check` 通过。
- 证据：`docs/tashas-item-production-consumer-round-XIII-2026-08-12.md`、Round XIII report/result、ItemSpec catalog 与 whole-pack migration 输出。
- 实现与证据提交 `5ceb72ad077227364d9b33beccea9ddf7e73e3b2` 已推送到 `origin/main`；ledger/handoff receipt 随后单独提交。
- 下一步：继续剩余 5 条完整 ItemSpec；当前 production `32/47` 已过 60% gate，但 game usable `32/47` 尚未达到 75% gate，不能提前收口。

## Round 9：Resource Profile / Exchange / Event Window Consumer Expansion

当前状态：`accepted`；本轮完成 6 条真实 API evidence，属于 platform/core growth round，已提交并推送，整包 game usable 达到 76。

- 6/6 条剩余 full Feature contracts 通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay；psi-warrior psionic dice 完成 advancement resource profile，Battle Master 两条完成 triggered attack window，Harness Divine Power 完成 typed resource exchange，Interception/Runic Shield 完成 reaction window。formal apply/database/campaign/character 写入均为 false。
- 新增通用能力：`combat_engine.feature_event_window.v1`、typed `window_spec`、CombatAction durable eligible window、resource exchange、resource profile advancement、resource/CAS/idempotency 绑定；没有 feature-name/name-based runtime branch。
- Tasha status layers：`registered_production_full=74`（68→74）、`dm_assisted=2`、`game_usable=76`；`manual_authoring=314`、`compile-only=17`（23→17）、`authored Typed IR=94`、`runtime_preview_full=93`。
- 真实断言覆盖 1 个 resource profile、2 个 triggered attack window、1 个 proficiency-derived exchange（2 点）、2 个 reaction window；typed consumer、preview-confirm-replay、resource/CAS 全通过，name branch=0。
- 完整 backend pytest、Round III/V/VI/VII/VIII/IX 与 whole-pack 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-IX-2026-08-12.md`、Round IX report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：继续处理 unresolved ItemSpec consumer 与 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 的真实 event producer/consumer；已补齐的 generic window/resource consumer 继续复用。

## Round 12：Typed Tattoo Lifecycle Consumer

当前状态：`accepted`；本轮完成通用 tattoo lifecycle 实现和 8 条真实 evidence，已提交并推送。

- `equipment_preview/confirm` 现在按 typed `tattoo_lifecycle` clause 持久化 `manifested/ink/effects_active` 与 `needle_returned/needle/effects_removed`，并继续复用 `item.attunement.v1`、character CAS、OperationTransaction 和 idempotency；没有 item-name dispatch。
- 8/8 完整刺青通过 create→attune→action/charge→unattune 的 preview→confirm→replay；8/8 transition、metadata snapshot、Attunement ended、CAS/replay 通过，共 21 transactions，2 条 charge lifecycle。
- ItemSpec 当前状态：`47 total / 37 compile_full / 37 isolated / 24 registered_production_full / 24 game_usable`；Feature Tasha 仍 `74/2/76`，分开计数。
- 证据：Round XII report/result、Round XII doc/test、更新后的 ItemSpec catalog 与 whole-pack migration；formal registry/database 未写入，name branch=0。
- 实现提交 `8947eff9e958808ce7e5f5584295682b263bff39` 已于 2026-08-12 05:23:43 +0800 推送到 `origin/main`；ledger receipt 更新随后单独提交。
- 下一步：继续剩余 explicit spell-cast、partial tattoo variants 和 unresolved item effects；ItemSpec production 尚未达到整包阈值。

## Round 11：ItemSpec Content Quality Correction / Equipment Consumer Expansion

当前状态：`accepted`；本轮完成 parser 质量修复和 8 条真实 ItemSpec evidence，已提交并推送。

- `_explicit_spell_identities()` 收紧为显式 `施展*中文名**English Name*法术`，移除自由 inline spell 抽取；职业法器、法术书目录、状态名和 generic “这道法术”不再伪装成 `granted_spell`。真实明确的 Disguise Self identity 保留。
- 质量重建将 ItemSpec `compile_full` 从 41 收紧至 37，10 条 partial 的实际 unresolved clauses 不被自动执行；ItemSpec typed 总量仍为 47。现有 Round X 8 条生产 evidence 继续有效。
- 新增 8 条：假肢、星卜编集、寰宇图纂、钟铃圣枝、奉献香炉、织心入门、灵肉圣契、异界行访录；8/8 create/attune-or-equip/action-or-charge preview→confirm→replay，16 个 operation transaction 通过。
- 当前 ItemSpec status layers：`47 total / 37 compile_full / 37 isolated_runtime_validated / 16 registered_production_full / 16 game_usable`；Feature Tasha status 仍 `74/2/76`，不与 ItemSpec 混计。
- 证据：Round XI report/result、Round XI doc/test、更新后的 ItemSpec catalog 与 whole-pack migration 输出。formal registry/database 仍未写入，name branch=0。
- 实现与证据提交 `0f3eccf0bcef428ff70932412d891708efc2c176` 已于 2026-08-12 05:08:31 +0800 推送到 `origin/main`；ledger receipt 更新随后单独提交。
- 下一步：继续审阅剩余 tattoo lifecycle、明确 spell-cast/charge 语义和 unresolved effect clauses；不把 projection-only、isolated-only 或 DM-reference 计入 production。

## Round 10：ItemSpec Equipment Consumer Production Evidence

当前状态：`accepted`；本轮完成 8 条真实 ItemSpec API evidence，ItemSpec registered production 从 0 增至 8，ItemSpec game usable 达到 8；Feature status layers 保持不变。

- 8/8 条 `compile_full` ItemSpec 通过真实 equipment create，以及 attune/equip、granted action、charge operation 的 preview→confirm→幂等 replay；14 个 operation transaction 均落在临时迁移 SQLite。
- 通用 consumer 覆盖 `item.equipment_modifier.v1`、`item.attunement.v1`、`item.charge_resource.v1`、`item.granted_action.v1`。守护者纹章与炼金总纲实际完成充能扣减；所有 ItemSpec projection、同调状态、角色 CAS、幂等 replay 均通过，name branch=0。
- ItemSpec 状态：`47 total / 41 compile_full / 41 isolated_runtime_validated / 8 registered_production_full / 8 game_usable`；6 个 partial blocker 继续保留。Feature 的 Tasha status 仍为 `production_full=74`、`dm_assisted=2`、`game_usable=76`。
- 新增 `load_item_production_evidence()`：只有带 `content_kind=item` 且整批 create/preview/confirm/replay gate 通过的 persisted result 才能回填 ItemSpec registered 层；隔离 pack 仍 `formal_apply=false`，不写正式数据库。
- validator、round test、ItemSpec catalog、whole-pack migration 两次确定性验证、backend 定向测试已通过；完整 backend pytest、Ruff、compileall、保护指纹和 push receipt 在本轮收尾门禁中确认。
- 证据：`docs/tashas-item-production-consumer-round-X-2026-08-12.md`、Round X report/result、`reports/tashas-item-spec-catalog-2026-08-11.json`。
- 实现与证据已提交并推送：`42153f2562cab8d24af9fc67e7549a7dc2056b13`，`origin/main`，2026-08-12 04:52:00 +0800；receipt 随后写入独立交接提交。
- 下一步：继续 unresolved ItemSpec granted-spell/tattoo lifecycle 与需要真实 event producer 的 clauses；不把 projection-only、isolated-only 或 DM-reference 伪装成 production。

## Round 8：Trigger-bound Modifier / Activation Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，已提交并推送，整包 game usable 达到 70。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` combat preview→confirm→幂等 replay；7 条通过 typed passive/inspection registry，`psi-powered-leap` 通过已有 feature-action activation，临时迁移 SQLite。formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=68`（60→68）、`dm_assisted=2`、`game_usable=70`；`manual_authoring=314`、`compile-only=23`（31→23）、`authored Typed IR=94`、`runtime_preview_full=93`。
- 真实断言覆盖 grappling/tactical/attack correction/psionic check 的 passive binding、Starry Form resistance/saving inspection，以及灵力跃动实际 `psionic_dice` 3→2 和飞行 activation；runtime ID、typed consumer、resource/CAS、preview-confirm-replay 均 8/8，name branch=0。
- 完整 backend pytest、Round III/V/VI/VII/VIII 与 whole-pack 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-VIII-2026-08-12.md`、Round VIII report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：建设通用 reaction-window、resource exchange/profile 与真正 event producer/consumer 链，再处理 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 unresolved ItemSpec lifecycle；未经过完整事件语义的合同继续不计 production。

## Round 7：Typed Advancement / Character Growth Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，已提交并推送，整包 game usable 达到 62。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` advancement preview→confirm→幂等 replay；临时迁移 SQLite，并实际写入 character features/spell grants snapshot。consumer 统一为 `advancement_service.character_growth.v1`，formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=60`（52→60）、`dm_assisted=2`、`game_usable=62`；`manual_authoring=314`、`compile-only=31`（39→31）、`authored Typed IR=94`、`runtime_preview_full=93`。
- 真实断言覆盖 10/10、10/10、2/2、2/2、2/2、1/1、2/2、6/6 spell grant 形态；4 个 typed choice consumer 完成选择生命周期；advancement block ready、character CAS、transaction、feature persistence 均为 8/8，name branch=0。
- 完整 backend pytest、Round III/V/VI/VII 与 whole-pack 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-VII-2026-08-12.md`、Round VII report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：继续推进剩余 resource/action/trigger lifecycle、vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 unresolved ItemSpec lifecycle；isolated-only 和 DM-reference 继续不计 production。

## Round 6：Passive Modifier / Inspection Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，8 条 registered production，整包 game usable 达到 54。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` passive inspection preview→confirm→幂等 replay；临时迁移 SQLite，所有 passive block 均与 runtime ID 绑定，consumer 为 `combat_engine.feature_action.v1`。formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=52`（44→52）、`dm_assisted=2`、`game_usable=54`；`manual_authoring=314`、`compile-only=39`、`authored Typed IR=94`、`runtime_preview_full=93`。
- 真实断言覆盖 spell/passive、速度、armor、sight、attack-context/social-check modifier；name branch=0，typed consumer=8/8，passive binding=8/8，inspection resolution=8/8。
- 完整 backend pytest、Round VI/历史 Tasha 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-VI-2026-08-12.md`、Round VI report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：继续推进 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 和 unresolved ItemSpec lifecycle；isolated-only 和 DM-reference 继续不计 production。

## Round 5：Typed Advancement / Character Growth Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，8 条 registered production，整包 game usable 达到 46。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` advancement preview→confirm→幂等 replay；临时迁移 SQLite，并实际写入 character features/proficiencies/skills/spells snapshot。formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=44`（36→44）、`dm_assisted=2`、`game_usable=46`；`manual_authoring=314`、`compile-only=47`、`authored Typed IR=94`、`runtime_preview_full=93`。
- 通用实现：`content_kind=advancement`、`advancement_service.character_growth.v1`，按 typed `advancement` / `proficiencies` / `prepared_spell_list` block 分发；固定 grant、choice grant、grant_spell 共用 character CAS、operation transaction、idempotency 和 feature snapshot。
- 真实断言覆盖固定熟练/语言、Order Cleric/Skill Expert/Ranger Canny 选择生命周期，以及 Aberrant Mind 10 个 spell grants；name branch=0，typed consumer=8/8。
- 完整 backend pytest、Round V/历史 Tasha 定向回归、whole-pack migration 两次 deterministic hash、compileall、变更源 Ruff、`git diff --check` 通过。保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 证据：`docs/tashas-feature-production-consumer-round-V-2026-08-12.md`、Round V report/result、`reports/tashas-status-layer-audit-2026-08-11.json` 和 whole-pack report。
- 下一步：继续推进 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 和 unresolved ItemSpec lifecycle；isolated-only 和 DM-reference 继续不计 production。

## Round 4：Movement / Sight / Choice / Lifecycle Consumer Expansion

当前状态：`accepted`；本轮完成 8 条真实 API evidence，8 条 registered production，整包 game usable 达到 38。

- 8/8 条 Round-II Feature contracts 通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay；临时迁移 SQLite，并经 combat turn boundary 刷新移动 / 视觉快照。formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=36`（28→36）、`dm_assisted=2`、`game_usable=38`；`manual_authoring=314`、`compile-only=55`、`authored Typed IR=94`、`runtime preview full=93`。
- 通用修复：选择绑定落到 `resources.selected`；显式移动模式生成通用 feature action 并持久化限时速度；支持 climb / walking speed / fixed speed；视觉 `set` 模式进入冻结 `rule_modifiers` 与 `active_sight_modes`；资源消耗继续走角色资源 CAS。没有 feature-name/name-based runtime branch。
- 真实断言覆盖海洋馈赠游泳、越野攀爬/游泳、兽性之魂选择、两条盲斗盲视、元素赐福/翻腾浪涌/午夜飞步飞行与资源扣减。完整 backend pytest 通过；whole-pack migration 和 Round IV validator 双次关键输出 byte-identical。
- 保护指纹保持：database `f3abdcf5…a6ad`、`backend/tests/ollama.py` `8027a6d8…e6ab`、integrations manifest `ae4ef9f5…cd91`；499 formal audit 仍为 328/110/61。
- 下一步：继续推进 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 unresolved ItemSpec lifecycle；isolated-only 和 DM-reference 继续不计 production。

## Round 3：Formal Production Consumer Evidence Harvest

当前状态：`accepted`；本轮完成 12 条真实 API evidence，11 条 registered production、1 条 DM-assisted，整包 game usable 达到 30。

- 12/12 条 Round 2 Feature contracts 通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay；临时迁移 SQLite，formal apply/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=28`（17→28）、`dm_assisted=2`（1→2）、`game_usable=30`；`manual_authoring=314`、`compile-only=63`、`authored Typed IR=94`、`runtime preview full=93`。
- 通用修复：attack-hit typed intent 选择 rider、superiority die/ability modifier timed value materialization、AC timed modifier、`_or_` condition removal、DM-confirmed reaction trigger + reaction CAS。name branch 仍为 0。
- 正式 499 audit 保持 328/110/61；3D、source corpus、正式 campaign/character 数据未修改。证据见 `docs/tashas-feature-production-consumer-round-III-2026-08-12.md` 和 Round III report/result。
- 下一步：继续收割 movement/sight/passive/choice 等需要独立事件入口的 Feature consumers；未经过真实 producer/consumer/persistence/CAS/replay 的合同继续停在 isolated 或 partial。

## Round 2：Feature/Option Semantic Contract Batch I

当前状态：`completed_with_formal_boundary_open`；本批已完成隔离合同与角色成长闭环，正式 production 收割转入下一 Round。

- 64/64 条真实 Feature/Option atom 完成 reviewed + authored Typed IR；58/64 compile full，6 条保留 partial blocker。
- 58 条 full 合同完成 isolated pack apply/reload 与幂等重放；58 grants 进入角色成长 runtime compiler，`closed_loop=true`。formal apply=false，registered production 增量为 0。
- 整包真实结果：94 authored Typed IR、93 runtime preview full、manual authoring 314（378→314）、compile-only 75；正式 Tasha 仍为 production 17、DM-assisted 1、game usable 18。
- 通用实施包括多 advancement/prepared-spell 合并、stable feature ID、typed authorized-information consumer；没有新增 feature-name/name-based runtime branch。
- 证据：`reports/tashas-feature-contract-batch-I-2026-08-12.json`、`reports/tashas-feature-contract-runtime-batch-I-2026-08-12.json`、`docs/tashas-feature-option-contract-batch-I-2026-08-12.md`。
- 下一步：Round 3 只从已有通用 consumer 收割正式 production evidence，优先 passive proficiency、movement、resource/action；继续保持 isolated 与 formal production 分账。

## Round 1：统计口径与塔莎 Item Registry 收口

当前状态：`accepted`，已 push 到 `origin/main`。

- 实际起点：塔莎 524 个 QA 后 atoms、407 executable；ItemSpec 47，总计 41 compile/preview full，但没有可 reload 的 whole-pack isolated runtime registry。
- 本轮实现：统一 Content IR status layers；新增 `ContentPackRuntimeRegistry`；每条 ItemSpec 重新解析、校验消费者投影和 pack/version/source identity；生成 `runtime-registry.json`。
- 当前证据：47 条 ItemSpec reload；41 条 `isolated_runtime_validated`；6 条保留 blocker；`registered_production_full=0`；正式 registry/database 未写入。
- 真实净增：isolated runtime validation +41；没有伪造 formal production 或 game usable 增量。
- 下一步：Feature/Option Contract Harvest Round，优先高扇出 choice/resource/trigger/target/duration/summon 合同。
- 提交：`776c7fe`、`ecd6606`、`9c581e7`、merge `c8fe28c`。
- Push receipt：`origin/main` → `c8fe28c1c3c4c215f4eaeda1e6acc590afd93add`，2026-08-12 00:23:50 +0800。
