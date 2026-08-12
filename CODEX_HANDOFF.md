# 2026-08-12 Round 24 检查点：Summon Beast / Summon Undead Typed Summon Consumer

- Round XXIV 已验收 source-complete `tashas-cauldron:spell:54c8c29188db1442473d9dc1`（野兽召唤术）与 `tashas-cauldron:spell:083419d9de551806a5ca9748`（亡灵召唤术）。两条均保留 `target_selection`、`summon_or_creation`、`concentration`、`upcast` 四条 typed clauses，以及 source fingerprint、source checksum、source path 和 clause boundaries。
- 新增/接入名称无关 `spell.summon.v1`：choice/stat block、HP/AC scaling、movement modes、structured actions/defenses、90 尺 visible/unoccupied geometry、action economy、shared initiative、duration/concentration、source/summon lifecycle、spell-slot rollback、CAS、preview/confirm/replay 均在真实临时 SQLite 通过。
- `default_behavior` 已真正闭环：player-controlled ally summon 在无口头命令的回合开始自动消费 action 执行 Dodge，并按最近权威 hostile grid position 与现有障碍/边界/占用规则远离危险；无权威危险位置时 fail closed 为 DM review。行为写入 `advance_turn`、`CombatAction` 和 transaction snapshot，不把持久化字段伪称自动执行。
- Round XXIV after：Tasha `525 atoms / 408 player-facing executable / 95 authored Typed IR / 94 compile / 94 preview / 88 production / 2 DM-assisted / 90 game usable / 4 compile-only / 314 manual / 107 DM reference`；项目 production full `188`、compile-only `35`、unique compiled `111`；ItemSpec `47/40/40/40`；formal 499 `328/110/61`。
- Validator 全部 checks 通过；focused receipt suite `38 passed`；backend 全量 pytest、Ruff、`backend/src` compileall、diff-check 通过，仅保留既有 Starlette/httpx deprecation warning。证据入口：`scripts/validate-tashas-spell-production-consumer-round-XXIV.py`、`backend/tests/test_tashas_spell_production_consumer_round_XXIV.py`、`reports/tashas-spell-production-consumer-round-XXIV-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-XXVI.json`、`docs/tashas-spell-production-consumer-round-XXIV-2026-08-12.md`。
- 正式 database、formal registry、source corpus、campaign/character、3D 和两个永久保护路径未写入；保护指纹保持 database `f3abdcf57b0d71888f085ca081511df4f4f23f100066b402d49d769089fa6aad`、formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`；`name_branch_count=0`。
- 提交与推送：实现 `22f78e7`、证据/交接 `0932a0f` 均已推送到 `origin/main`。
- 下一轮继续 source-complete typed contract 的 generic consumer；communication、maneuver eligibility、vessel、spectral-object 和未闭合 character-growth seams 保持 fail-closed，不迁移下一本扩展包、不触碰 3D。

# 2026-08-12 Round 23 检查点：Intellect Fortress Typed Spell Defense Consumer

- Round XXIII 已验收 source-complete `tashas-cauldron:spell:b4ea0dc1907dd5ac08666af3`（智能壁垒）：五条 typed clauses 覆盖 30 尺可见目标、psychic resistance、Intelligence/Wisdom/Charisma save advantage、concentration 和四环目标增长/30 尺组距。
- 新增名称无关 `spell.defense.v1` production consumer；`defense_bundle` 以共享 `concentration_group_id` 持久化每个目标的 `CombatEffect`，实际消费 psychic resistance/save advantage，支持 range/visibility/group geometry、target cap、actor/target CAS、replacement、group end、source lifecycle、spell rollback 和 replay。
- 修复 grouped concentration 语义：group 仍有 active effect 时保留角色 concentration resource；整组结束或专注失败时，按 KnownSpell UUID 与 Content IR spell ID 清理角色资源。
- Round XXIII validator 使用真实临时迁移 SQLite，23 项检查全 true；receipt test 为 5 项。输出 `data/content-ir/compiled/production-runtime-results-XXV.json` 与 Round XXIII report，`name_branch_count=0`，formal database/registry unchanged。
- Round XXIII actual after：Tasha `525 atoms / 408 player-facing / 408 executable / 95 authored Typed IR / 94 compile / 94 preview / 86 production / 2 DM-assisted / 88 game usable / 6 compile-only / 314 manual / 107 DM reference`；项目 production full `186`、compile-only `35`、unique compiled `111`；ItemSpec `47/40/40/40`；formal 499 `328/110/61`。
- 全量 backend pytest、Ruff、compileall、diff-check 通过，仅保留既有 Starlette deprecation warning。whole-pack migration 连续三次成功：stdout SHA-256 `e3145aa3e6d84ec68bf2d8884057ada4fb26c40629418ee309359e843d234e74`，关键 report/runtime hashes 三次一致。
- 保护与正式指纹保持：database `f3abdcf57b0d71888f085ca081511df4f4f23f100066b402d49d769089fa6aad`、formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。
- 本轮实现提交 `f1d3ae8`、evidence/docs 提交 `6ed1a30`、receipt `43781cd`、ledger receipt `b675955` 和最终 handoff receipt `4335a3e` 均已推送到 `origin/main`。下一轮继续真实完整 typed contract 的 generic consumer，剩余 summon/entity、communication、maneuver eligibility、vessel、spectral-object 与完整 character-growth seams 保持 fail-closed，不迁移下一本扩展包、不触碰 3D。

# 2026-08-12 Round 22 检查点：Soulknife Psychic Teleportation Typed Feature Consumer

- Round XXII 已验收 source-complete `content.tashas-cauldron.round2.feature.soulknife-psychic-teleportation`：新增 typed `teleport` operator，表达 bonus action、可见未占据空间、`movement_roll_total × 10 ft` 距离上限，并与 `consume_resource(psionic_dice, 1)` 组合；`unmodeled_source_terms=[]`，没有 feature-name branch。
- 通用链路已落地：Feature operator contract、`movement.teleport` production-closed capability、materializer、`ContentIRRuntimeRequest` 的目的地/掷骰输入、ContentIR preview/confirm 绑定，复用既有 `combat_engine.feature_action.v1` 与 authoritative grid teleport consumer。
- 真实隔离 SQLite evidence：占据目的地 confirm 失败后资源、角色/战斗版本、snapshot、bonus action 全部回滚；合法 `(2,2)→(2,6)`，roll=2、最大距离=20ft、距离=20ft，`psionic_dice 3→2`，bonus action 消耗；preview→confirm→replay、CAS、transactions 全通过。
- Round XXII after：Tasha `525 atoms / 408 player-facing / 408 executable / 95 authored Typed IR / 94 compile / 94 preview / 85 production / 2 DM-assisted / 87 game usable / 7 compile-only / 314 manual / 107 DM reference`；项目 production full `185`、compile-only `35`、unique compiled `111`；ItemSpec `47/40/40/40`。formal 499 仍 `328/110/61`。
- 门禁：Round XXII validator 1/1，focused receipt tests，backend full pytest `903 passed, 1 warning`，`backend/src`+`backend/tests` Ruff，compileall，diff-check；whole-pack migration 共 6 次成功运行，最终两次关键 report SHA-256 byte-identical。正式 database `f3abdc...a6ad`、formal registry `f4b5...ca6b`、integrations `ae4e...cd91`、ollama `8027...e6ab` 未变。
- 实现提交 `da93a60` 与证据可追溯性修正 `816a9dc` 已推送至 `origin/main`；本 receipt 会继续单独提交。外部 Obsidian memory write-back 仍受本轮 Codex usage limit 阻挡，未绕过限制；本仓库 handoff/ledger/plan/Round XXII doc 是本轮本地交接 authority。
- 下一轮继续剩余 summon/entity、defense、communication、maneuver eligibility、vessel、spectral-object seams；继续 fail-closed，不迁移下一本扩展包，不触碰 3D。

# 2026-08-12 Round 21 检查点：Psionic Sorcery Typed Spell-Context Consumer

- Round XXI 已验收 source-complete `content.tashas-cauldron.round2.feature.aberrant-mind-psionic-sorcery`（灵能术法）：两个 typed clauses `component-override` 与 `payment-override`，分别表达 `psionic_spell` 下忽略非费用成分、以等同法术环阶的 `sorcery_points` 替代 `spell_slot`。source fingerprint、reviewed fields、source record/path、manual decisions 和空 `unmodeled_source_terms` 已保留。
- 新增名称无关 `spell.context.v1` consumer；Feature compiler/materializer 持久化 `spell_context`，`ContentIRRuntimeService` 只读取法术 metadata 的显式 `psionic_spell=true`，`SpellEconomyService` 通过 typed context 完成材料覆盖、灵能点 CAS、法术位保持、OperationTransaction、preview/confirm/replay 与 rollback；无 Feature/spell name branch。
- 真实隔离 SQLite evidence：6 级角色施展 1 环塔莎酸蚀酿时材料不可用仍成功，法术位 `2→2`、灵能点 `3→2`；重放幂等，下游失败后 spell/resource rollback，两个 typed context clause、transaction、snapshot、formal boundary checks 全通过。
- Round XXI after：Tasha `525 atoms / 408 player-facing / 408 executable / 95 authored Typed IR / 94 compile+preview / 84 production / 2 DM-assisted / 86 game usable / 8 compile-only / 314 manual / 107 DM reference`；项目 production full `184`、compile-only `35`、unique compiled `111`；ItemSpec `47/40/40/40`。formal 499 仍 `328/110/61`，name branch=0。
- Round XXI 全量门禁：validator 1/1、focused pytest、Ruff、compileall、diff-check、backend full pytest `902 passed, 1 warning`；whole-pack migration stdout 和连续三次关键 report/runtime SHA-256 byte-identical。database `f3abdcf57b0d71888f085ca081511df4f4f23f100066b402d49d769089fa6aad`、formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3` 均保持。
- 实现/evidence 提交 `2066902` 已推送到 `origin/main`；本交接 receipt 正在单独提交。外部 Obsidian memory write-back 曾因本轮 Codex usage limit 被拒，未绕过限制；仓库 handoff、ledger、plan 和 Round XXI doc 已作为本地交接 authority 更新。
- 下一轮继续剩余 summon/entity、defense、communication、maneuver eligibility、vessel、teleport destination、spectral-object seams；保持 fail-closed，不迁移下一本扩展包，不把 isolated-only / DM-reference / 单条子句冒充 production。

# 2026-08-12 Round 20 检查点：Sword Burst Generic Spell Consumer

- Round XX 已选定唯一具备完整现有通用消费者覆盖的 compile-only spell：`tashas-cauldron:spell:eec6bd94eb83a351fb987de2`（剑刃爆发）。source text、source fingerprint、reviewed fields、manual decisions 和 typed area/save/damage/scaling clauses 已复核。
- 新增名称无关 `spell.cantrip_scaling.v1` descriptor；runtime 从角色等级消费 authored `upcast.progression`，与既有 area geometry、saving throw、damage、batch CAS、OperationTransaction 和 rollback 链连接。真实临时 SQLite 已通过等级 1/5/11/17 scaling、双目标 preview→confirm→幂等 replay、save-success 0 damage、stale target 409、事务与 rollback。
- 当前 migration after：Tasha `525 atoms / 408 player-facing / 408 executable / 95 authored Typed IR / 94 compile+preview / 83 production / 2 DM-assisted / 85 game usable / 9 compile-only / 314 manual / 107 DM reference`；项目 production full `183`；ItemSpec `47/40/40/40`。正式 database/registry/campaign/character、source corpus、3D、永久保护路径未写入，name branch=0。
- Round XX 已验收：全量 backend pytest `899 passed, 1 warning`、全源 Ruff、变更范围 compileall、diff-check、migration 三次 byte-identical、formal/protected fingerprint 复核均通过；tracked worktree 只剩永久保护的两个未跟踪路径。实现提交 `c2823e5` 已推送到 `origin/main`，receipt 另行提交。
- 证据入口：`scripts/validate-tashas-spell-production-consumer-round-XX.py`、`backend/tests/test_tashas_spell_production_consumer_round_XX.py`、`reports/tashas-spell-production-consumer-round-XX-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-XXII.json`、Round XX doc。
- 剩余 blocker：Summon Beast/Undead 的 entity/stat-block lifecycle、Intellect Fortress defense effect、Oceanic Soul communication、Ambush 双触发 eligibility、Bottled Respite vessel、Psychic Teleportation destination、Psionic Sorcery payment、Manifest Mind spectral object；均不因本轮 spell scaling consumer 被伪升 full。

# 2026-08-12 Round 19 检查点：Character Growth / Implements of Mercy Closure

- Round XIX 完成 `content.tashas-cauldron.feature.way-of-mercy.implements-of-mercy` 的三条 typed proficiency clause：洞悉、医药、草药工具；全部通过既有 `advancement_service.character_growth.v1` 的隔离 SQLite preview→confirm→幂等 replay、character CAS、OperationTransaction、feature snapshot，`name_branch=0`。
- 本轮 1 条是 character-growth core exception，因为一个完整 Feature 关闭三条角色成长授予；没有新增语义/特性名 dispatch。Tasha actual status：`production_full=82`、`dm_assisted=2`、`game_usable=84`、`compile_only=10`、`authored Typed IR=95`、`compile+preview=94`、`manual=314`、`DM reference=107`；当前项目 production full `182`；ItemSpec `47/40/40/40`。
- 新增：`scripts/validate-tashas-feature-production-consumer-round-XIX.py`、`backend/tests/test_tashas_feature_production_consumer_round_XIX.py`、Round XIX report/result/doc；whole-pack reports/isolated pack 已重建。正式 registry/database/campaign/character、source corpus、3D、永久保护路径未写入。
- Round XIX validator、Ruff、compileall、`git diff --check` 通过；backend full pytest `896 passed, 1 warning`；whole-pack migration 两次关键 report/runtime hashes 一致。
- 实现提交 `e09e804eef50552fd9a6af24ab8146168c4f0d03` 已推送到 `origin/main`；本交接 receipt 已单独写入 ledger/handoff/memory。Round XIX 现为 accepted，正式 registry/database 与保护路径仍未写入。

# 2026-08-12 Round 18 检查点：Generic Roll Intervention / Battle Master Closure

- Round XVIII 已完成平台核心实现：typed `roll_intervention` materializer/consumer 接入玩家掷骰窗口，扫描 actor 与 target 的 Feature Runtime；`attack_type` 进入 Player Roll schema/resolver，精准攻击只接受 `weapon_attack`，非 AC prompt fail closed。
- 真实隔离 SQLite evidence：领导风范 `12+4=16`、卓越骰 `4→3`；精准攻击 `12+5=17`、`3→2`；两者 preview/open→confirm→幂等 replay、character CAS、资源 transaction 均通过，spell attack 不开精准攻击窗口，name branch=0。
- source-declared authored subclause atom bridge 已恢复精准攻击的 Content Atom 追踪，整包实际结果为 `525 atoms / 408 player-facing / 408 executable / 95 authored typed IR / 94 compile+preview / 81 production / 2 DM-assisted / 83 game usable / 11 compile-only / 314 manual / 107 DM reference`；当前项目 production full `181`，ItemSpec 仍 `47/40/40/40`。
- Round XVIII 只有 2 条，是共享玩家掷骰/actor resource CAS 的 platform-core exception；Ambush 因敏捷（隐匿）与先攻双触发未形成完整 typed eligibility，未提升。formal registry/database/campaign/character、source corpus、3D、永久保护路径未写入。
- 新增/更新：`backend/src/dnd_dm_assistant/application/feature_materializers.py`、`application/tashas_whole_pack.py`、`infrastructure/database/combat_service.py`、`api/schemas.py`、Round XVIII validator/test/report/result/doc、Precision Attack provenance、whole-pack reports/isolated pack、goal ledger。
- Round XVIII validator、Feature contract batch、Round XVI character-growth、Round XVII rest validator、targeted combat tests、Ruff、compileall、`git diff --check` 已通过；backend full pytest 为 `895 passed`，whole-pack migration 连续运行关键 report/registry hashes 完全一致。
- 实现提交 `0509c93a9c7cd7462c67098a1b0c53d709d0fba3` 已推送到 `origin/main`；本交接 receipt 已单独写入 ledger/handoff/memory。Round XVIII 现为 accepted，正式 registry/database 与保护路径仍未写入。

# 2026-08-12 Round 17 检查点：Generic Rest Condition Consumer / Tireless Closure

- Round XVII 完成 `remove_condition` 的 rest trigger contract、compiler fail-closed guard 和 `rest_condition_effect` materializer；Tireless 从 partial 解锁为 full，短休时自身 exhaustion 降低 1 级。
- `RestService._short_rest_fatigue_reduction()` 现在扫描 typed triggers 和匿名 legacy `rest_effects`，不再读取 `actions["tireless"]`；非 exhaustion 的 rest condition 会保持 partial。
- 真实隔离 SQLite preview→confirm→replay：力竭 3→2、CAS、OperationTransaction、condition persistence、相同 `rest_record_id` replay 全通过，name branch=0。
- Tasha Feature status：`production_full=79`、`dm_assisted=2`、`game_usable=81`、`compile_only=12`、`authored Typed IR=94`、`runtime_preview_full=93`、`manual_authoring=314`；ItemSpec 独立 `47/40/40/40`，当前项目 production full `179`。
- 新增/更新：`scripts/validate-tashas-rest-feature-production-consumer-round-XVII.py`、Round XVII tests/doc/report/result、feature compiler/operator/materializer/rest consumer、Round-II isolated Feature pack 与 whole-pack reports。正式 registry/database/campaign/character、source corpus、3D、永久保护路径未写入。
- Round XVII validator 通过；whole-pack migration 连续运行关键 SHA-256 一致；专门 Rest API 2 项通过。backend 全量 pytest、Ruff、compileall、`git diff --check` 在本轮收尾门禁确认。
- 实现/证据提交 `ecde5e8ccb79bc622f6a179af9e95b8bb39d1e3d` 已推送到 `origin/main`；本交接 receipt 更新随后单独提交。下一轮继续已有 typed IR 的通用 event/entity/teleport/payment consumer，不新增名称分支。

# 2026-08-12 Round 16 检查点：Character Growth Proficiency Consumer Expansion

- Round XVI 在真实 `advancement_service.character_growth.v1` 上完成 Battle Smith、Armorer、Alchemist、Artillerist 四条工具熟练 FeatureSpec：4/4 preview→confirm→幂等 replay，5 个 proficiency grants、character CAS、OperationTransaction、feature snapshot 全通过，`name_branch_count=0`。
- Tasha Feature status layers：`production_full=78`（74→78）、`dm_assisted=2`、`game_usable=80`、`compile_only=13`、`authored Typed IR=94`、`runtime_preview_full=93`、`manual_authoring=314`。ItemSpec 分开为 `40 compile / 40 isolated / 40 registered / 40 game usable`。
- Oceanic Soul 只证明寒冷抗性不够，因为同一合同还有未建模的水下互通；Bottled Respite、Psychic Teleportation、Manifest Mind、Tireless、Psionic Sorcery、Ambush、Commanding Presence 保持 fail-closed。未把单个可执行子句冒充整条 full。
- 新增 Round XVI validator/test/report/result/doc，更新 Feature IR/runtime/whole-pack reports 与历史单调断言；Round X–XVI 定向测试 22 项、backend 全量 pytest `891 passed`、Ruff、compileall、`git diff --check` 通过。formal registry/database/campaign/character、source corpus、3D、永久保护路径未写入。
- 永久指纹保持：database `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`、formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。
- 实现/证据提交 `d61e5ad7a5fdc313d929deac195efc2fa703e6e0` 已推送到 `origin/main`；本交接 receipt 更新随后单独提交。下一轮继续剩余 feature compile-only/ItemSpec partial 的通用 typed consumer 解锁，不增加名称分支。

# 2026-08-12 Round 15 检查点：Typed Item-Cast Spell Consumer

- Round XV 修复显式“施展”后的 inline spell identity parser，支持单法术与 `施展以下/下列法术：...` 列表；generic “这道法术”、职业法器 prose 和变量蕴法刺青仍 fail closed。鲁芭的灵魂塔罗卡、拉奥圣杖、伊格薇尔伏恶魔志 3 条从 partial 解锁为 compile/isolated full。
- `item.granted_spell.v1` 现在在 equipment action preview/transaction snapshot 中物化 typed `item_spell_cast`、`grant_mode=item_cast` 和 16 个去重 spell identities；3/3 preview→confirm→幂等 replay、2 charge lifecycles、6 transactions、CAS/state 全通过，`name_branch_count=0`。
- ItemSpec status layers：`47 total / 40 compile_full / 40 isolated_runtime_validated / 40 registered_production_full / 40 game_usable`；项目 production full `171→174`。Tasha Feature 独立维持 `74 production / 2 dm-assisted / 76 game-usable`。
- 新增/更新：`backend/src/dnd_dm_assistant/application/tashas_recovery.py`、`infrastructure/database/spell_economy_service.py`、Round XV validator/test/report/result/doc、ItemSpec catalog/runtime registry 与 whole-pack reports；Round X–XV 定向测试 21 项、backend 全量 pytest `890 passed`、Ruff、compileall、`git diff --check` 通过。
- formal registry/database/campaign/character、source corpus、3D 和永久保护路径未写入。剩余 7 条 partial 仍因随机表、DM choice、变量 spell 或 entity/exhaustion 语义保持 fail-closed。永久指纹保持：database `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`、formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。
- 实现/证据提交 `f34148d9c6c4d40a9e965c625bc4f006b27f9a9c` 已推送到 `origin/main`；本交接 receipt 更新随后单独提交。下一轮继续剩余 partial 的 typed semantic unlock，不将 generic/variable/DM-reference prose 计入 production。

# 2026-08-12 Round 14 检查点：Residual Complete ItemSpec Closeout / Dawn Boundary

- Round XIV 关闭当前 inventory 中剩余的 5 条完整 ItemSpec：堕影冥界碎晶、伪装刺青、堕影冥界印记刺青、重生坩埚、凝晶年纪。5/5 通过 equipment create、attunement/equip、granted action 或 charge、preview→confirm→幂等 replay。
- 2/2 魔法刺青完成 `manifested/ink → needle_returned/needle`；凝晶年纪的 typed `recovery_trigger=dawn` 通过真实 `RestService._item_charge_recovery()` boundary probe，`long_rest` 不会错误恢复 dawn charge。共 12 个 operation transactions、1 条 charge lifecycle、`name_branch_count=0`。
- ItemSpec status layers：`47 total / 37 compile_full / 37 isolated_runtime_validated / 37 registered_production_full / 37 game_usable`；项目 production full `166→171`。Tasha Feature 独立维持 `74 production / 2 dm-assisted / 76 game-usable`。
- Round XIV validator/test/report/result/doc、ItemSpec catalog、isolated runtime definitions/registry 和 whole-pack reports 已落地；Round X–XIV 定向测试 20 项、backend 全量 pytest `889 passed`、Ruff、compileall、`git diff --check` 通过。formal registry/database/campaign/character、source corpus、3D 和永久保护路径未写入。
- 本轮只有 5 条是因为它们已经是全部剩余完整合同；未解析的 action/spell/effect clauses 仍保持 manual/DM 边界，不能被这些 evidence 自动提升。永久指纹保持：database `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`、formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。
- 实现/证据提交 `d6cae79f73601fced2636050f3de97ba81a101ed` 已推送到 `origin/main`；本交接 receipt 更新随后单独提交。下一轮继续 unresolved partial clauses 的 typed semantic unlock，不将 DM-reference、manual 或 isolated-only 计入 production。

# 2026-08-12 Round 13 检查点：Additional ItemSpec Equipment Consumer Batch

- Round XIII 在隔离 SQLite 上完成月镰、自然护符、巴巴·雅加的魔法扫帚、星界碎片、重复手稿、爆裂论文、防护诗篇和狂欢者风笛共 8 条完整 ItemSpec 的 equipment create、attunement/equip、granted action 或 charge、preview→confirm→幂等 replay。
- 8/8 create/preview/confirm/replay、typed consumer、item state、attunement CAS、production runtime full 通过；4 条 charge lifecycle、17 个 operation transactions、`name_branch_count=0`。
- ItemSpec status layers：`47 total / 37 compile_full / 37 isolated_runtime_validated / 32 registered_production_full / 32 game_usable`；项目 production full `158→166`。Tasha Feature 独立维持 `74 production / 2 dm-assisted / 76 game-usable`。
- 新增/更新：`scripts/validate-tashas-item-production-consumer-round-XIII.py`、Round XIII test/report/result/doc、ItemSpec catalog、isolated runtime definitions/registry 和 whole-pack migration reports；Round X/XI/XII 累计 evidence 断言已更新。
- Round XIII validator 与 whole-pack migration 各运行两次且 byte-identical；targeted Tasha tests 19 项、backend 全量 pytest `888 passed`、Ruff、compileall 和 `git diff --check` 通过。formal registry/database/campaign/character、source corpus、3D 和永久保护路径未写入。
- 实现/证据提交 `5ceb72ad077227364d9b33beccea9ddf7e73e3b2` 已推送到 `origin/main`；本交接 receipt 更新随后单独提交。永久指纹：database `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`、formal registry `f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b`、integrations `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`、ollama `8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3`。
- 下一轮继续剩余 5 条完整 ItemSpec；`32/47` 已过 production 60% gate，但 game usable 尚未达到 75% gate，不得提前收口。

# 2026-08-12 Round 10 检查点：ItemSpec Equipment Consumer Production Evidence

- Round 10 在隔离 SQLite 上完成 8 条 `compile_full` ItemSpec 的真实 equipment create、attune/equip、granted action、charge operation preview→confirm→幂等 replay；14 个 operation transaction 均持久化，守护者纹章与炼金总纲充能均落到 2。
- 新增 `load_item_production_evidence()`，将声明 `content_kind=item` 且通过整批生命周期 gate 的 `production-runtime-results-XII.json` 回填 ItemSpec catalog 的 registered layer；不把 isolated pack 自动写入正式 registry/database。
- ItemSpec status layers：`47 total / 41 compile_full / 41 isolated_runtime_validated / 8 registered_production_full / 8 game_usable`；Feature status 不混计，仍 `74 production / 2 dm-assisted / 76 game-usable`，name branch=0。
- 证据入口：`scripts/validate-tashas-item-production-consumer-round-X.py`、`backend/tests/test_tashas_item_production_consumer_round_X.py`、`reports/tashas-item-production-consumer-round-X-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-XII.json`、`docs/tashas-item-production-consumer-round-X-2026-08-12.md`。
- Round X validator report/result 两次 hash 一致；whole-pack migration 两次 stdout 与关键 ItemSpec/catalog/runtime hashes 一致。正式 campaign/character、database、3D、source corpus、499 audit 与永久保护路径不在本轮修改范围。
- 实现提交 `42153f2562cab8d24af9fc67e7549a7dc2056b13` 已于 2026-08-12 04:52:00 +0800 推送到 `origin/main`；本 receipt 更新随后单独提交。
- 下一步继续 unresolved ItemSpec granted-spell/tattoo lifecycle 和真实 event producer，不将 projection-only、isolated-only、DM-reference 计入 production。

# 2026-08-12 Round 11 检查点：ItemSpec Content Quality Correction / Equipment Expansion

- `_explicit_spell_identities()` 已收紧为明确施展且带英文 identity 的 spell 形态，修复了职业法器、spellbook list、condition 和 generic “这道法术”的误识别；真实 Disguise Self 保留。ItemSpec compile full 从 41 收紧到 37，未解析语义继续 partial/manual。
- 新增 8 条 ItemSpec 真实 evidence：假肢、星卜编集、寰宇图纂、钟铃圣枝、奉献香炉、织心入门、灵肉圣契、异界行访录；8/8 preview/confirm/replay、16 transactions、charge/CAS/state persistence 全通过。
- 当前 ItemSpec status：`47 / 37 / 37 / 16 / 16`（total / compile / isolated / registered / game usable）；Feature Tasha 仍 `74 production / 2 dm-assisted / 76 game-usable`。
- Round XI 产物：`scripts/validate-tashas-item-production-consumer-round-XI.py`、Round XI report/result、`docs/tashas-item-production-consumer-round-XI-2026-08-12.md`；仍 formal_apply=false、formal registry/database 未写入、name branch=0。
- Round XI 实现提交 `0f3eccf0bcef428ff70932412d891708efc2c176` 已于 2026-08-12 05:08:31 +0800 推送到 `origin/main`；receipt 更新随后单独提交。

# 2026-08-12 Round 12 检查点：Typed Tattoo Lifecycle Consumer

- `item.attunement.v1` 已按 typed `tattoo_lifecycle` clause 持久化刺青状态：同调 `manifested/ink/effects_active`，解除同调 `needle_returned/needle/effects_removed`；使用 character/equipment CAS、OperationTransaction、idempotency，无 item-name branch。
- 8/8 完整刺青真实 API roundtrip 通过，21 transactions，2 charge lifecycle，8/8 transition、metadata、Attunement ended 和 replay 通过。ItemSpec：`47 / 37 / 37 / 24 / 24`（total / compile / isolated / registered / game usable）。
- 证据入口：`scripts/validate-tashas-item-production-consumer-round-XII.py`、Round XII report/result、`docs/tashas-item-production-consumer-round-XII-2026-08-12.md`。
- 当前 formal_apply/database/registry 仍 false/unchanged；下一轮继续 explicit spell-cast、partial tattoos 与 unresolved item effects。
- Round XII 实现提交 `8947eff9e958808ce7e5f5584295682b263bff39` 已于 2026-08-12 05:23:43 +0800 推送到 `origin/main`；receipt 更新随后单独提交。

# 2026-08-12 Round 9 检查点：Resource Profile / Exchange / Event Window Consumer 扩展

- Round 9 作为 platform/core growth round，完成剩余 6 条 full Feature contract 的真实 production evidence：Psi Warrior Psionic Power resource profile、Battle Master Brace/Quick Toss triggered attack windows、Paladin Harness Divine Power resource exchange、Paladin Interception/ Rune Knight Runic Shield reaction windows。
- 新增通用 typed consumer：`combat_engine.feature_event_window.v1`；`feature_compiler` 投影稳定 `window_spec` / `resource_exchange`，Character growth 写入资源 profile，CombatEngine durable `CombatAction` 持久化 eligible window，resource/CAS/idempotency 全部接入，无 feature-name/name-based branch。
- 6/6 均通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay；4 个事件窗口、1 个 proficiency-derived 2 点 exchange、1 个 resource profile 均通过。formal apply/database/campaign/character 写入为 false，name branch=0。
- Tasha status layers：`registered_production_full=74`（Round 8 的 68→74）、`dm_assisted=2`、`game_usable=76`；`manual_authoring=314`、`compile-only=17`（23→17）、`authored Typed IR=94`、`runtime_preview_full=93`。严格口径仍为 `game_usable = registered_production_full + dm_assisted`。
- 新增/修改证据入口：`backend/src/dnd_dm_assistant/application/feature_compiler.py`、`application/content_ir_runtime.py`、`application/content_ir_production_registry.py`、`infrastructure/database/combat_service.py`、`api/schemas.py`，以及 Round IX validator/test/report/result/doc。whole-pack migration 两次关键报告/runtime/isolated manifest hash 一致。
- Round IX evidence/gates 已完成并已推送：implementation/evidence commit `b2c64213638eb2a2965ad3bae9ccfd3114352fab`，`origin/main` push success，2026-08-12 04:28:30 +0800；ledger receipt 随后单独提交。下一轮继续 unresolved ItemSpec consumer 与 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 的真实 event producer/consumer，不要把 isolated-only / DM-reference 伪装成 production。

# 2026-08-12 Round 8 检查点：Trigger-bound Modifier / Activation Consumer 扩展

- Round 8 在 Round-II authored Feature IR 上完成 8 条真实 combat production evidence：Battle Master Grappling Strike、Tactical Assessment、Psi Warrior Psi-Powered Leap、Soulknife Homing Strikes、Psi Bolstered Knack、Stars Druid Full of Stars、Weal、Woe。8/8 均通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay，consumer 为 `combat_engine.feature_action.v1`。
- 7 条通过 typed passive/inspection registry 且 passive block 与 runtime ID 绑定；`psi-powered-leap` 通过已有 feature-action activation，实际消耗 `psionic_dice` 3→2 并持久化飞行模式。runtime ID binding、resource/CAS、formal false、name branch=0 均通过。
- Tasha status layers：`registered_production_full=68`（Round 7 的 60→68）、`dm_assisted=2`、`game_usable=70`；`manual_authoring=314`、`compile-only=23`（31→23）、`authored Typed IR=94`、`runtime_preview_full=93`。严格口径仍为 `game_usable = registered_production_full + dm_assisted`。
- 新增证据入口：`scripts/validate-tashas-feature-production-consumer-round-VIII.py`、`backend/tests/test_tashas_feature_production_consumer_round_VIII.py`、`reports/tashas-feature-production-consumer-round-VIII-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-X.json`、`docs/tashas-feature-production-consumer-round-VIII-2026-08-12.md`。whole-pack migration 两次关键报告/runtime/isolated manifest hash 一致。
- 完整 backend pytest、Round III/V/VI/VII/VIII 与 whole-pack 定向回归、变更源 Ruff、compileall、`git diff --check` 通过。保护目录 `backend/tests/integrations/` 和 `backend/tests/ollama.py` 未暂存/提交；database fingerprint 仍为 `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`，integrations manifest 仍为 `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`。
- Round 8 evidence/gates 已完成并已推送：implementation/evidence commit `c2e0a6590d776d7da91111c058eecc9acb621998`，`origin/main` push success，2026-08-12 04:06:08 +0800；ledger receipt 随后单独提交。下一轮建设 generic reaction-window、resource exchange/profile 与 event producer/consumer，再处理 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 ItemSpec lifecycle。不要把 isolated-only / DM-reference 伪装成 production。

# 2026-08-12 Round 7 检查点：Typed Advancement / Character Growth Consumer 扩展

- Round 7 在 Round-II authored Feature IR 上完成 8 条真实角色成长 production evidence：炼金师法术、时械魔法、妖精触碰、影界触碰、受祝福的勇士、念力宗师、德鲁伊教战士、集群牧者魔法。8/8 均通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay，consumer 为 `advancement_service.character_growth.v1`，并实际写入 character feature/spell snapshot。
- 4 条带选择的合同（妖精触碰、影界触碰、圣武士/游侠 cantrip）完成 typed choice lifecycle；全部 8 条满足 advancement block ready、character CAS、operation transaction、feature persisted；name branch=0，formal registry/database/campaign/character 写入均为 false。
- Tasha status layers：`registered_production_full=60`（Round 6 的 52→60）、`dm_assisted=2`、`game_usable=62`；`manual_authoring=314`、`compile-only=31`（39→31）、`authored Typed IR=94`、`runtime_preview_full=93`。严格口径仍为 `game_usable = registered_production_full + dm_assisted`。
- 新增证据入口：`scripts/validate-tashas-feature-production-consumer-round-VII.py`、`backend/tests/test_tashas_feature_production_consumer_round_VII.py`、`reports/tashas-feature-production-consumer-round-VII-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-IX.json`、`docs/tashas-feature-production-consumer-round-VII-2026-08-12.md`。whole-pack migration 两次关键报告/runtime/isolated manifest hash 一致。
- 完整 backend pytest、Round III/V/VI/VII 与 whole-pack 定向回归、变更源 Ruff、compileall、`git diff --check` 通过。保护目录 `backend/tests/integrations/` 和 `backend/tests/ollama.py` 未暂存/提交；database fingerprint 仍为 `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`，integrations manifest 仍为 `ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91`。
- Round 7 evidence/gates 已完成并已推送：implementation/evidence commit `0f49029e340811a6ba104310e3cd320415c180e5`，`origin/main` push success，2026-08-12 03:48:39 +0800；ledger receipt 随后单独提交。之后继续处理 resource/action/trigger lifecycle、vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 ItemSpec consumer，不要把 isolated-only / DM-reference 伪装成 production，也不要迁移下一本扩展包。

# 2026-08-12 Round 6 检查点：Passive Modifier / Inspection Consumer 扩展

- Round 6 在 Round-II authored Feature IR 上完成 8 条真实 passive production evidence：炼金术掌握、动力步伐、工具精通、奥法枪械、星之铠甲、星之视觉、粉碎者、妖冶娴都。8/8 均通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay，typed passive block 绑定和 `combat_engine.feature_action.v1` inspection consumer。
- Tasha status layers：`registered_production_full=52`（Round 5 的 44→52）、`dm_assisted=2`、`game_usable=54`；`manual_authoring=314`、`compile-only=39`、`authored Typed IR=94`、`runtime_preview_full=93`。严格口径仍为 `game_usable = registered_production_full + dm_assisted`。
- 本轮复用现有 feature runtime registry、passive inspection、actor/target CAS、transaction/idempotency；没有新增 feature-name/name-based runtime branch。
- 新增证据入口：`scripts/validate-tashas-feature-production-consumer-round-VI.py`、`reports/tashas-feature-production-consumer-round-VI-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-VIII.json`、`docs/tashas-feature-production-consumer-round-VI-2026-08-12.md`。Round VI validator 两次关键输出 hash 一致；whole-pack migration 两次关键报告/runtime hash 一致。
- formal apply/database/campaign/character 仍为 false；3D、source corpus、formal 499 audit 未改。受保护的 `backend/tests/integrations/` 和 `backend/tests/ollama.py` 未暂存/提交，database fingerprint 仍为 `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`。
- Round VI evidence 已提交并推送：`8df8ca391c7844a78c56a73d6909ac4ab2e2fb68`，`origin/main` push success，2026-08-12 03:24:06 +0800；ledger receipt 随后单独提交。
- Round VI 后继续处理 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 ItemSpec lifecycle；不要把 isolated-only / DM-reference 伪装成 production，也不要迁移下一本扩展包。

# 2026-08-12 Round 5 检查点：Typed Advancement / Character Growth Consumer 扩展

- Round 5 在 Round-II authored Feature IR 上完成 8 条真实角色成长 production evidence：Bladesinger、Peace Cleric、Rune Knight、Twilight Cleric、Order Cleric、Skill Expert、Ranger Canny、Aberrant Mind Psionic Spell List。8/8 均通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay、character CAS、operation transaction 和 feature snapshot 持久化。
- Tasha status layers：`registered_production_full=44`（Round 4 的 36→44）、`dm_assisted=2`、`game_usable=46`；`manual_authoring=314`、`compile-only=47`、`authored Typed IR=94`、`runtime_preview_full=93`。严格口径仍为 `game_usable = registered_production_full + dm_assisted`。
- 通用实现：`content_kind=advancement`、`advancement_service.character_growth.v1`、typed `advancement/proficiencies/prepared_spell_list` sections、固定与 choice grants、grant_spell、character CAS/idempotency/operation snapshot；没有 feature-name/name-based runtime branch。
- 新增证据入口：`scripts/validate-tashas-feature-production-consumer-round-V.py`、`reports/tashas-feature-production-consumer-round-V-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-VII.json`、`docs/tashas-feature-production-consumer-round-V-2026-08-12.md`。Round V validator 两次关键输出 hash 一致；whole-pack migration 两次关键报告/runtime hash 一致。
- 完整 backend pytest、Round V 与历史 Tasha 定向回归、变更 source Ruff、compileall、`git diff --check` 通过。仓库已有测试 import-order I001 噪音没有做无关格式化。
- formal apply/database/campaign/character 仍为 false；3D、source corpus、formal 499 audit 未改。受保护的 `backend/tests/integrations/` 和 `backend/tests/ollama.py` 未暂存/提交，database fingerprint 仍为 `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`。
- Round V implementation/evidence 已提交并推送：`2125670a5cda1673e8a3f62522267608fa7c3e4d`，`origin/main` push success，2026-08-12 03:10:24 +0800；ledger receipt 随后单独提交。
- 下一轮：继续 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 ItemSpec lifecycle；不要把 isolated-only / DM-reference 伪装成 production，也不要迁移下一本扩展包。

# 2026-08-12 Round 4 检查点：Movement / Sight / Choice / Lifecycle consumer 扩展

- Round 4 在 Round-II authored Feature IR 上完成 8 条真实生产 evidence：`fathomless-gift-of-the-sea`、`ranger-roving`、`beast-barbarian-bestial-soul`、两条 `blind-fighting`、`genie-elemental-gift`、`swarmkeeper-writhing-tide`、`twilight-cleric-steps-of-night`。8/8 均通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay、CAS、transaction，并经回合边界刷新移动 / 视觉快照。
- Tasha status layers：`registered_production_full=36`（Round 3 的 28→36）、`dm_assisted=2`、`game_usable=38`；`manual_authoring=314`、`compile-only=55`、`authored Typed IR=94`、`runtime_preview_full=93`。严格口径仍为 `game_usable = registered_production_full + dm_assisted`。
- 通用实现：`grant_movement_mode` 支持选择绑定、climb、walking speed、fixed speed、speed multiplier；显式移动 clause 生成通用 `activate_movement_mode` feature action，支持 ten-minute / one-minute state 和角色资源 CAS；`grant_sight_mode` 的 `set` block 进入冻结 `rule_modifiers` / `active_sight_modes`。带同一资源键的既有状态动作会合并移动 effect，保留条件生命周期和 parity。
- 新增证据入口：`scripts/validate-tashas-feature-production-consumer-round-IV.py`、`reports/tashas-feature-production-consumer-round-IV-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-VI.json`、`docs/tashas-feature-production-consumer-round-IV-2026-08-12.md`。Round IV validator 两次关键输出 hash 一致；whole-pack migration 两次关键报告/runtime hash 一致。
- 完整 backend pytest 通过；变更 production source、Round IV test/validator 的 Ruff 通过；`git diff --check` 通过。仓库已有全量 test import-order 的 I001 噪音没有做无关格式化。
- formal apply/database/campaign/character 仍为 false；3D、source corpus、formal 499 audit 未改。受保护的 `backend/tests/integrations/` 和 `backend/tests/ollama.py` 未暂存/提交，database fingerprint 仍为 `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`。
- 下一轮：继续 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 与 ItemSpec lifecycle；不要把 isolated-only / DM-reference 伪装成 production，也不要迁移下一本扩展包。

# 2026-08-12 Round 3 检查点：Feature production consumer evidence 收割

- Round 3 从 Round 2 的 isolated full contracts 中选择 12 条，全部通过真实 `ContentIRRuntimeService` preview→confirm→幂等 replay；11 条为 typed production，1 条辉煌防御为 DM-confirmed typed reaction，并实际消费 reaction resource。
- Tasha status layers 已到 `registered_production_full=28`（17→28）、`dm_assisted=2`（1→2）、`game_usable=30`；manual authoring 314、compile-only 63、authored Typed IR 94、runtime preview full 93。
- 新增通用逻辑：`attack_hit` intent 优先选择 attack rider；timed modifier 解析 die/ability modifier、支持 AC；条件移除支持 typed `_or_` 选项；DM reaction 需要显式 trigger、DM permission 和 reaction CAS。禁止按特性名分支。
- evidence 使用临时迁移 SQLite，`formal_apply=false`、`formal_registry_written=false`、`formal_database_written=false`；没有修改正式 campaign/character、source corpus、3D 或 499 formal audit。
- 证据入口：`scripts/validate-tashas-feature-production-consumer-round-III.py`、`reports/tashas-feature-production-consumer-round-III-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-V.json`、`docs/tashas-feature-production-consumer-round-III-2026-08-12.md`。
- 下一 Round：movement/sight/passive/choice 的独立生产 consumer；vessel/entity lifecycle、exhaustion、spectral object、teleport destination、psionic payment 仍保持边界。

# 2026-08-12 Round 2 检查点：Feature/Option 合同扩产与角色成长隔离闭环

- 本轮严格保持 isolated/formal 边界：64 条真实 Tasha Feature/Option atom 完成 reviewed + authored Typed IR，58 条 compile full；6 条保持 partial，不以名称分支或 fallback 冒充 full。
- 58 条 full 合同经过 `FeaturePackImporter` 隔离 apply、reload、幂等重放和 registry lookup；角色成长回路实际接收 58 grants，编译为 58 runtime contracts，`closed_loop=true`。formal apply=false，正式 registry/database/campaign/character 未写入。
- 整包迁移重跑后的 Round 2 分母为 144 source records、524 QA atoms、407 executable；94 authored Typed IR、93 runtime preview full、314 manual authoring、75 compile-only。Round 3 已将正式 Tasha status 提升至 production 28、DM-assisted 2、game usable 30。
- 通用实现：多 advancement/prepared-spell block 合并并保留逐 grant 元数据；显式 stable feature ID 防止同 class/level 授予碰撞；typed authorized-information materializer/consumer；未添加 feature-name/name-based runtime branch。
- 6 个 Round 2 partial blocker 已记录：水下互通、vessel/entity lifecycle、exhaustion timing、spectral object lifecycle、teleport destination、psionic component/payment；下一 Round 负责 movement/sight/passive/choice 及这些 lifecycle consumer 的独立事件链。
- 证据入口：`scripts/author-tashas-feature-contract-batch-I.py`、`scripts/validate-tashas-feature-contract-batch-I.py`、`reports/tashas-feature-contract-batch-I-2026-08-12.json`、`reports/tashas-feature-contract-runtime-batch-I-2026-08-12.json`、`docs/tashas-feature-option-contract-batch-I-2026-08-12.md`。

# 2026-08-11 Round 1 检查点：状态口径与塔莎 Item Registry 收口

- 当前分支 `main`，Round 1 目标是修正 `ItemSpec compile/preview full`、隔离运行时和正式 production registry 的统计混用。
- 新增统一 Content IR status layers：`compile_full`、`runtime_preview_full`、`isolated_runtime_validated`、`registered_production_full`、`dm_assisted`、`game_usable`；其中 `game_usable = registered_production_full + dm_assisted`。
- 新增 `ContentPackRuntimeRegistry`，对塔莎隔离 pack 的 47 条 ItemSpec 全部 reload/re-parse；41 条通过通用消费者投影并记为 `isolated_runtime_validated`，6 条仍为 blocker。`formal_apply=false`，`registered_production_full=0`，未触碰正式 registry/database。
- 新增 `data/content-ir/isolated-packs/tashas-cauldron-2026-08-11/runtime-registry.json`、`reports/tashas-status-layer-audit-2026-08-11.json` 和 `reports/goal-round-ledger.json`。稳定生成 stdout 与关键 registry/report hash 已验证 byte-identical。
- 定向 Tasha recovery/migration 测试、Ruff、compileall、diff-check 已通过；合并后端全量 pytest 与前端 41 文件/206 tests、typecheck、lint、build 均通过。普通 merge `c8fe28c` 已 push 到 `origin/main`：`c8fe28c1c3c4c215f4eaeda1e6acc590afd93add`。
- 下一 Round：从 318 个 Feature/Option manual atoms 中按真实 fan-out 收割 Contract Harvest，保持单线程、无名称分支、隔离 DB/pack。

# 2026-08-11 长执行检查点：《塔莎的万事坩埚》整包覆盖恢复 I

- 本轮仍严格单线程；没有调用子代理。受保护的 `backend/tests/integrations/` 和
  `backend/tests/ollama.py` 未加入本轮变更，最终必须继续排除暂存。
- QA 真实分母已修正：第一轮 625 atoms / 558 executable，本轮 524 / 407；删除/合并候选
  115，source span、parent、source fingerprint、atom ID 结构检查通过。真实 item 分母是
  36 magic items + 11 magic tattoos = 47，不再使用上一轮 139 的分页/子条款假阳性数。
- `item-ir-1` 已落地：47/47 reviewed+typed，41 compile/production full，6 保留人工/DM
  边界，name branch 0。新增通用 equipment modifier、attunement、charge/recovery、granted
  action/spell、consumable、triggered-effect consumers；EquipmentInstance、Attunement、Rest
  service、world snapshot 和 transaction/CAS/idempotency 被复用。隔离测试覆盖 item action、
  长休充能、dawn 不冒充 long rest、DM decision window、replay 和 rollback。
- 新增 28 个通用 semantic/template interface；5 个 item 模板达到保守 unlock gate，feature/option
  模板仍因 semantic cluster 未补齐而阻塞。Feature/Option batch 的真实结果为 reviewed 339、
  typed 21、compile 21、production 14、DM-assisted 0；未达到本轮要求的 120/100/80/50/10，
  因此不能宣称整包 production closed。
- 既有 authored provenance 31 条已完成匹配/别名协调/明确退役，orphan 0：Armorer 和
  Artillerist 工具熟练为 alias reconciliation；Battle Master Precision Attack 因来源是
  构筑推荐页而非独立规则资产，显式 retired。
- 角色成长新增 history-backed downgrade preview/confirm、immutable character content-pack
  pin、snapshot rebuild、CAS/idempotency；隔离测试覆盖 1→3→2、pin duplicate rejection、
  item/DM action rollback。Tasha feature/option 资产阈值未达，角色状态保留 `bounded_partial`。
- 新增报告：`reports/tashas-atom-quality-audit-2026-08-11.json`、
  `reports/tashas-atom-catalog-II-2026-08-11.json`、semantic/template、ItemSpec/tattoo、
  feature/option、provenance、character、DM、coverage/efficiency II 和 runtime audit V；
  `docs/tashas-whole-pack-coverage-recovery-I-2026-08-11.md` 是本轮交接主文档。
- 重复运行迁移脚本后的 stdout、关键报告、closeout、recovery doc 和 isolated pack manifest
  byte-identical。正式 source HTML/JSON、formal DB、formal registry、real campaign/character
  不在 apply 范围内。
- 下一步只做 FeatureSpec/Option 的逐字段语义审阅与 runtime consumer unlock，优先奇械师注法、
  魔能祈唤、战技、choice/resource/trigger/target/duration/summon lifecycle；不要改 raw source、
  不要按名称增加 runtime 分支，也不要提前迁移下一本扩展包。

# 2026-08-11 长执行检查点：《塔莎的万事坩埚》整包生产迁移 I

- 本轮严格单线程；没有创建、调用或委托子代理。受保护的
  `backend/tests/integrations/` 与 `backend/tests/ollama.py` 未修改、未暂存、未提交。
- 建立真实分母链：144/144 source records 已扫描并分类，生成 625 个 Content Atom，其中
  558 个玩家向 executable candidate；同一批次完整生成 558 Draft/Candidate/Review。
- 类型分布：`class_feature 64`、`subclass_feature 266`、`spell 21`、`feat 16`、
  `character_option 15`、`maneuver 8`、`invocation 9`、`infusion 21`、
  `magic_item 103`、`magic_tattoo 36`、`companion_profile 3`、`dm_tool 7`、
  `environment_rule 22`、`puzzle 15`、`narrative 9`、`directory 10`。
- 已复用既有 12 个模板；template match 28/558（5.02%），没有新模板、没有 name branch、
  没有新 generic consumer。28 条 authored/verified Typed IR 全部接回；compile full/runtime
  preview full 均为 28。现有 authored IR 共 31 条，另有 3 条 provenance 未匹配真实 atom，已
  明确列为 mismatch：Armorer Tools of the Trade、Artillerist Tool Proficiency、Battle
  Master Precision Attack。
- Atom 状态为 `production_full 18`、`dm_assisted 1`、`compile_only 9`、
  `manual_authoring 530`、`dm_reference 57`、`non_instantiable 10`、`invalid 0`、
  `duplicate_or_reprint 0`；Content-ID funnel `28 = 18 + 1 + 9` 通过。现有 Tasha registry
  的 19 个 production runtime ID 全部映射到真实 atom，未产生 registry 回归。
- Item/刺青 139 个（103 magic item + 36 magic tattoo）仅完成 inventory；未伪装成 runtime，
  blocker 是通用 `ItemSpec`/equipment-attunement/resource consumer 尚未接线。角色成长只做了
  bounded partial：pack compatibility/legacy boundary、reload/idempotent/rollback probe 已
  通过，未声称完成升级、降级、快照重建或正式 apply。
- 现有项目基线保持 `111 unique compiled / 35 compile-only / 76 production full`，正式 499
  条职业审计保持 `328 full / 110 partial / 61 dm_only`；formal registry、database、campaign
  数据均未修改。代表性法术运行时检查沿用既有 preview→confirm→result→replay、CAS、rollback、
  snapshot 与召唤 DM continuation 证据，Tasha 4 条法术 atom 有生产运行时证据。
- 代码入口：`backend/src/dnd_dm_assistant/application/tashas_whole_pack.py`、
  `scripts/migrate-tashas-whole-pack.py`；测试：
  `backend/tests/test_tashas_whole_pack_migration.py`。报告与 isolated pack 见
  `reports/tashas-whole-pack-report-2026-08-11.json` 和
  `data/content-ir/isolated-packs/tashas-cauldron-2026-08-11/`。
- 全量后端 pytest、backend/src+tests Ruff、迁移脚本 Ruff、compileall、diff-check 均通过；前端
  未改动，未运行前端门禁。连续两次生成的报告、closeout 与 isolated pack 文件 byte-identical。
- 下一步应先建设 ItemSpec/equipment-attunement/resource-bound item consumer，再回填 139 个
  item atoms；若选择下一本整包，优先费资本的巨龙宝库（Fizban）：同为 2014-compatible，已
  有 pack/runtime 边界且 source scope 较小、法术候选仅 7 个，适合作为 Item/实体边界的下一次
  受控迁移。

# 2026-08-11 长执行检查点：Rules Kernel、DM 裁定窗口与 3D 场景战斗协议 I

- 本轮全程单线程；没有创建、调用或委托子代理。`backend/tests/integrations/` 与
  `backend/tests/ollama.py` 未修改、未暂存、未提交，继续作为用户必保留路径。
- 本轮基线以去重后的真实 ID 为准：113 条 compile rows 中有 2 条跨批次重复，故为
  `111 unique compiled / 60 unique compile-only / 51 production_runtime_full`。旧 handoff
  中的 113/62 不是本轮继续沿用的权威计数；正式 499 条职业审计保持
  `328 full / 110 partial / 61 dm_only`。
- 真实收割 25 条既有 compile-only：`20 spell + 5 feature`，无新 authored IR。结果为
  `76 production_runtime_full`（51→76）、`61 spell`（41→61）、`15 feature`（10→15）。
  官方包增量：Core PHB 2024 `26→42`、Xanathar `8→9`、Tasha `13→19`、Fizban `2→3`、
  Book of Many Things `2→3`。
- 每一条批次成员都通过真实 FastAPI/TestClient 的 preview→DM adjudication（需要时）
  →confirm→result replay；批次报告记录 `25/25` 的 preview、confirm、replay、CAS、
  transaction、rollback probe、snapshot rebuild 与 Scene Delta 证据，
  `all_required_checks_passed=true`。没有修改 source HTML/JSON、正式 campaign/character
  数据或 499 审计状态。

## 统一执行层

- `domain/rules_kernel_protocol.py` 提供严格、版本化、`extra=forbid` 的 Rules Kernel、
  Scene Query/Delta、Confirmation、Result 和 DM Adjudication 合同；不允许任意 Python 回调、
  动态导入或 name-based dispatch。
- `application/rules_kernel.py` 实现 preview/confirm/replay、命令/窗口 CAS、事务回滚、
  actor/combat/scene version 检查、typed content effect、资源与动作经济、DM continuation、
  known-profile entity lifecycle、movement/forced movement/teleport/swap 和 Scene Delta。
- `domain/spatial_authority.py` 定义引擎无关的 Spatial Authority；提供确定性测试实现和
  现有 `SceneGrid`/`SceneObject`/`Combatant`/`SceneToken` 适配器。3D 客户端只能消费 Query/Delta，
  不能成为规则权威，也没有把任意 3D 引擎类型引入 kernel。
- 五个生产 consumer 已登记并按 schema/content/clause/action 分发：
  `kernel.content.typed`、`kernel.spatial.movement`、`kernel.entity.lifecycle`、
  `kernel.choice.window`、`kernel.dm.adjudication`。禁止按 spell/feature name、source book 分支。
- Choice window 已是生产级平台并通过冻结 options、玩家/DM 边界、cardinality、CAS、幂等验证；
  本轮 60 条剩余 compile-only 中没有可诚实记账的既有 choice unlock，因此其增量为 0。
- DM adjudication 已是生产级平台：DM-only、冻结请求、允许的 typed decision、CAS、幂等和
  命令 continuation 均有真实验证；entity lifecycle 当前只承诺既有 compendium profile 的
  summon/object/hazard，未知自然语言对象仍停在 DM 裁定，不自动执行。
- movement/spatial 已覆盖通用 voluntary/forced/teleport/swap 合同；不把未证明的空间语义
  伪装成 production full。剩余 compile-only blocker 计数为：
  `adjudication.target_semantics 44`、`duration.multi_phase 28`、`spatial.area 11`、
  `condition.composite 9`、`runtime.evidence_missing 5`。

## 协议、报告与验证产物

- API：`POST /rules-kernel/preview`、`POST /rules-kernel/confirm`、结果/choice/adjudication/
  scene-deltas 查询与解析、`POST /rules-kernel/scene-query`。
- 协议资产在 `docs/protocols/`，集成契约为
  `docs/rules-kernel-3d-integration-contract-2026-08-11.md`；生成器为
  `scripts/build-rules-kernel-protocol-assets.py`。
- 生产批次、阻塞审计、消费者注册表、Spatial/Choice/Adjudication/Entity/Movement/Scene Delta
  验证及 3D 协议报告均在 `reports/*2026-08-11*.json`；生产结果为
  `data/content-ir/compiled/production-runtime-results-IV.json`。资产与报告重复生成后
  byte-identical。
- Migration `20260811_0001_rules_kernel_protocol.py` 已在临时 SQLite 上成功升级到 head。
- 最终门禁：`PYTHONPATH=backend/src backend/.venv/bin/pytest -q backend/tests` 全量通过；
  `backend/.venv/bin/ruff check backend/src backend/tests`、脚本 Ruff、compileall、
  `git diff --check` 全部通过。前端未修改，未运行前端门禁。
- 提交：实现层 `b6aa971`，批量验证与报告 `73dac26`，协议文档与 handoff `d701d51`，
  迁移文件格式修正 `4987f8e`。
- 下一优先级由真实 blocker/fan-out 决定：先收割 `kernel.dm.adjudication` 的
  `target_semantics`，并为 `duration.multi_phase`/`spatial.area` 补字段级 typed contract、
  validator、materializer 和 runtime evidence；不得按内容名字增加分支。

# 2026-08-10 长执行检查点：Content IR Workbench 与法术自动化基线

# 2026-08-11 长执行检查点：Typed IR 模板化扩产与真实运行时闭环

- 本轮全程单线程，未创建、调用、委托或等待子代理；`backend/tests/integrations/` 与
  `backend/tests/ollama.py` 保持用户必保留状态，未修改、未暂存、未提交。
- 模板与候选链已经落地：12 个 name-independent templates，274 个
  `generated_candidate`，100 个 reviewed/authored Typed IR；生成候选永远保持
  `compile_status=never_full_before_review`，review authority 支持 stale template/source
  fingerprint 检测，未把自然语言直接提升为 production full。
- Batch II 层级结果：100/100 `compile_full`，100/100 `runtime_preview_full`，20/20
  `production_runtime_full`。其中 core 2024 为 60/60/60/10，官方扩展法术为
  25/25/25/5（珊娜萨 11、塔莎 6、费资本 5、万象无常书 3），Tasha 扩展特性为
  15/15/15/5；15 个法术与 5 个特性均通过真实生产入口。
- 新增统一 CLI：`templates build`、`candidates generate/report`、`review validate`、
  `compile reviewed`，并保留 `dry-run` 与 `report --include-runtime-levels`。模板目录、候选、
  reviewed batch、runtime level、production validation、template ranking、unlock ranking
  与 isolated-pack dry-run 报告均已生成在 `reports/`。
- 真实生产消费者仅使用通用数据块：`spell_economy` 的 slot/character CAS 与幂等、
  `combat_engine` 的 damage/heal/temporary HP/feature action、effect turn snapshot、
  `rest_service` resource recovery；没有新增 spell-name 或 feature-name runtime 分支。
  本批 generic consumer 的真实 unlock 计数为 15 spell loops、5 feature loops，另有
  duration/turn snapshot 与 short-rest recovery 各 1 个 lifecycle loop。
- 生产验证覆盖 resource lack、wrong slot、illegal target、actor/target CAS、idempotent
  replay、downstream rollback、upcast、concentration、duration/turn snapshot 与 rest
  recovery；验证报告的 `all_required_checks_passed=true`。重复构建资产与批次报告
  byte-identical。
- 职业/子职业正式 499 条审计保持不变：`328 full / 110 partial / 61 dm_only`。
  partial/manual 仍停留在需要逐字段语义审阅的 operator、target、branch、choice、复杂
  duration/trigger、summon control 或 movement，不计入本轮 production full。
- 相关文档：`docs/content-ir-template-runtime-batch-II-2026-08-11.md`。下一优先级是
  completion-unlock ranking 中仍未达到 generic unlock threshold 的最高候选，而不是按名字
  增加 runtime 分支。

- 新增只读 `application/content_ir_workbench.py` 与
  `scripts/audit-content-ir-workbench.py`：扫描真实 generated-content，按 source_book
  或稳定 source path 隔离原版/扩展包，过滤索引与非详情页，生成 source fingerprint、
  Feature Draft、Spell Draft 和确定性报告。
- 新增独立 `SpellSpec` 闭集合同与 fail-closed 编译入口。只有 authored/verified typed
  clauses 可成为 `full`；未知 clause 为 invalid，HTML/JSON 字段提取结果一律 manual，
  不把“字段可读”伪装为可执行。
- 真实基线：2024 PHB 共 650 个相关 source records，其中 391 个法术详情候选；2014 PHB
  511/361。现有库仍没有 authored Spell IR，因此 source dry-run 的 typed/full 均为 0。
- 官方包只读结果：塔莎 144 records、48 feature candidates、21 spell candidates；
  珊娜萨 325/0/95；费资本 113/0/7；万象无常书 195/0/3。以上 typed IR/full 均为 0，
  真实 blocker 是缺 authored Feature/Spell IR。
- 报告位于 `reports/content-ir-workbench-*-2026-08-10.json` 与
  `reports/spell-automation-audit-phb*-2026-08-10.json`；没有修改数据库、正式 compiled
  registry 或 499 条职业审计状态。
- 必须保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-10 长执行检查点：真实语料批量编译入口与阻塞审计

# 2026-08-10 长执行检查点：Feature Clause IR 缺口图谱（止损点）

# 2026-08-10 长执行检查点：166 条 Clause reviewed typed 审阅批次

# 2026-08-10 长执行检查点：生产收割 VIII 与扩展包自动导入

- 本轮全程单线程，正式审计从 `full 320 / partial 118 / dm_only 61` 变为
  `full 328 / partial 110 / dm_only 61`，固定分母仍为 499，真实净增 `full +8`。
- 新增 8 条 direct authored Feature IR：诡术伏击、骇异恶咒、卫护斩、力场壁垒、狂热威仪、
  天界韧性、暗杀、进阶结社形态。八条均为 `source_trust=authored_ir`、
  `status_authority=compiler`，通过现有 production_closed capability、compiler、
  materializer、validator 和 runtime registry；没有新增 feature-name runtime 分支。
- 修复通用 `replace_damage_type` materializer 的标准 `combat_modifiers` 投影，并给 pack
  importer 增加版本/规则集校验、source fingerprint 元数据校验、跨 pack duplicate feature_id
  拒绝、并发 apply lock，以及 index 写入失败后的事务回滚。
- 新增确定性 harvest planner：`scripts/plan-feature-ir-production-harvest.py`，8/8
  `harvest_ready`。新增报告：
  `reports/feature-ir-production-harvest-plan-2026-08-10.json`、
  `reports/feature-ir-production-harvest-VIII-2026-08-10.json`。
- 新增真实扩展包 fixture：
  `data/feature-packs/expansion-pack-fixture-2026-08-10/`，包含 manifest、features 和
  source metadata。8 条使用不同 feature_id、source_record_id、feature_name，但复用相同
  typed contracts；不修改核心运行时名称分支。
- 扩展包验收结果：dry-run `8 full`、apply 成功、第二次 apply 幂等、reload 后 8/8 runtime
  registry、fingerprint/version conflict 拒绝、跨 pack duplicate feature_id 拒绝、并发 apply
  一次成功一次锁拒绝、index 故障后回滚无残留文件。报告：
  `reports/feature-pack-expansion-import-2026-08-10.json`。
- 后端全量 pytest、Ruff、compileall、git diff check 和审计/Corpus/Unlock/Harvest/Pack 报告
  双次 byte-identical 均通过。前端未修改，因此未运行前端门禁。
- 必须保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

- 本轮全程单线程，实时审计仍为 `full 320 / partial 118 / dm_only 61`，固定分母 499。
- 现有 166 个 source review clause 已进入带稳定 `source_fingerprint`、`reviewed_fields`、
  `missing_fields`、`review_blocker_category` 和 `review_blocker_details` 的
  `feature-clause-reviewed-1` 结构。它们不再是只有空字段的裸分段，但仍不是 executable
  FeatureSpec：166 条全部为 `manual_boundary`，`source_incomplete=0`，`executable=0`。
- `feature_clause_corpus.py` 仍保持非执行边界：review 结构只保存源码证据、身份、缺失字段和
  审阅结论，不从 anchor 关键词生成 operator、DC、目标或资源。
- Capability ranking 现在明确区分 review manual boundary 与 capability：`review:manual_boundary`
  occurrence 为 166，但 completion unlock 必为 0；`typed_missing_contract=0` 表示没有一条
  可用于生产选择的字段完整缺口合同，不表示语义审阅被跳过。
- Batch VII 报告已生成：`reports/feature-ir-production-consumer-batch-VII-2026-08-10.json`。
  本批没有建设平台、没有新增 full，也没有新增 feature-name runtime 分支；原因是全部 clause
  仍需要逐字段 authored/runtime contract，任何平台选择都会把 manual review 当作 capability。
- 全量后端 pytest、`backend/src`+`backend/tests` Ruff、compileall、`git diff --check` 和
  审计/Corpus/Unlock/Batch VII 报告双次 byte-identical 均通过。
- 必须保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

- 本轮仍为单线程。尝试建立 Clause IR 后的实时审计没有漂移：`full 320 / partial 118 /
  dm_only 61`，固定分母 499；本轮没有把任何 feature 升为 full。
- 新增 `application/feature_clause_corpus.py` 和
  `scripts/compile-feature-clause-corpus.py`。它把 118 个 partial 的已定位源码保留为 166 个
  **非可执行** review clause，字段未知时显式为 null，绝不从关键词推断 operator、DC、目标、
  资源或 runtime。报告为 `reports/feature-clause-corpus-2026-08-10.json`。
- 实际 corpus 与旧提示不同：118/118 都是 `description_located`，无 source-incomplete 条目；
  旧 planner 的 `missing_source=35` 是 readiness 类别，不能再当作 source_parse 缺失。
- 新增 `application/feature_capability_unlocks.py` 和
  `scripts/plan-feature-capability-unlocks.py`。只有所有 operational fields 完整且 canonical
  相等的 clause 才有 capability ID 和 completion unlock credit；未审阅 source clause 仅以
  `review:missing_semantic_contract` 列出，unlock 必为 0。报告为
  `reports/feature-capability-unlock-ranking-2026-08-10.json`。
- 真实结果：166 条 clause 都尚未形成完整 missing contract，typed candidate 为 0，
  completion unlock ≥8 的 capability 为 0。因此按本 Goal 的 fail-closed 条款，没有建设任何
  “高扇出平台”、也没有虚报批量 full；`reports/feature-ir-production-consumer-batch-VI-2026-08-10.json`
  是可重复生成的止损证据。下一步必须先把一批 source clauses 人工审阅成 typed contract，而不是继续
  从原语频次推平台。
- 必须保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

- 本轮接管时固定审计实时为 `full 320 / partial 118 / dm_only 61`，分母仍为 499。
  先修复 `grant_saving_throw_advantage`、Spell Resistance typed defense、IR parity
  alias 和 planner 期望；后端全量 pytest、backend/src+backend/tests Ruff、compileall、
  git diff check 均通过。
- 新增 `application/feature_ir_batch_compiler.py` 与
  `scripts/compile-feature-ir-batch.py`：真实 audit rows 按稳定 feature ID 和 source/spec
  fingerprint 排序编译，支持 dry-run/preview/apply/replay 元数据、fingerprint conflict、
  rollback plan；没有显式 typed FeatureSpec 的行一律 partial，generated_draft 一律不能 full。
- 新增真实语料 preview 报告：`reports/feature-ir-batch-preview-2026-08-10.json`；
  118 条 partial 全部 `missing_typed_spec`，0 条 materialized，正式 499 状态未改变。
- 语义 census 已扩展为每条 partial 的 typed contract 字段、authority 缺口、CAS/幂等、
  materializer/validator/evidence 和 cluster blocker；同时单独列出
  `superficially_similar_clusters`，这些粗标签相似簇明确 `merge_allowed=false`。当前
  `partial_exact_cluster_count=115`，最大 exact cluster 仍为 2，production_closed 且成员数
  ≥8 的候选簇为 0。
- 批次报告：`reports/feature-ir-production-consumer-batch-V-2026-08-10.json`。
  本阶段真实新增 full 为 0、direct IR authority 为 0；Goal 必须保持 active，不能把
  “compiler/preview 已存在”写成批量迁移完成。
- 必须保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：现有 production_closed 消费者批量迁移 I 收尾

- 本批起点按实时审计为 `full 312 / partial 126 / dm_only 61`，终点为
  `full 314 / partial 124 / dm_only 61`，固定分母仍为 499，真实净增 `+2`。
- 新增 full：
  - 德鲁伊·大地结社·3「大地结社法术」：固定法术表现在由 typed
    `rest_choice` 合同绑定 `circle_land_terrain`；升级/快照只物化已选地形且按德鲁伊等级
    截止法术；长休重选会移除旧地形法术、加入新地形法术，并同步 known/prepared spell
    持久化记录。
  - 武僧·命流武者·6「生死之触」：命中后中毒 rider overlay 与予命之手状态解除
    action overlay 均由现有 typed overlay consumer 执行，移除错误的 partial/DM 标记；
    予命之手自身的疾风连击免费替换仍单独保持 partial。
- 新增真实回归：大地结社升级选择、四种地形分支的等级截止、长休重配与法术快照重建；
  生死之触的攻击 rider/action overlay 合同回归。后端全量 `pytest -q backend/tests`
  通过；新增源码/测试 Ruff、compileall、`git diff --check` 通过。
- 仍未完成且明确保留 partial 的高风险簇：攻击骑手/复杂反应、多目标状态/召唤、
  目标抗性读取、强制移动、额外攻击/攻击槽替换、星耀形态三分支、灵魂之刃未命中重算等。
  当前 readiness 为 `already_full 314 / missing_runtime_contract 114 /
  consumer_partial 27 / needs_contract_review 6 / manual_boundary 3 / missing_source 35`。
- 工作树必须保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。
- 本批尚未创建新的高风险底层系统；下一轮应从剩余 partial 中重新筛选至少 4 条共享同构
  production_closed capability，若证据不足则止损，不为达到数量硬升 full。

# 2026-08-09 长执行检查点：现有 production_closed 消费者批量迁移 I

- 本轮全程单线程，未创建、调用、委托或等待任何子代理。固定审计分母仍为 499：
  `full 310 / partial 128 / dm_only 61` → `full 312 / partial 126 / dm_only 61`，真实净增
  `full +2`。
- 新增 full：圣武士·复仇之誓·3「仇敌誓言」与 15 级「复仇之魂」。前者修正通用触发器
  合同，正式承认既有生产消费者已经支持的 `restore_resource` / `clear_feature_state`；
  后者复用现有 `triggered_attack_window`，新增封闭 `after_enemy_attack` producer、
  誓言目标持久化状态过滤、武器触及范围解析，未新增职业名执行分支。
- `仇敌誓言` 与 `复仇之魂` 绑定 `verified_mapping` Feature IR：IR 编译、稳定 fingerprint、
  source trust 和 parity 报告均有证据；运行时继续由已验证 typed registry authority 提供，
  直到直接 materializer 字段 parity 完成。两条均有真实动作窗口、目标过滤、反应 CAS、幂等
  重放回归；新增回归为 `test_soul_of_vengeance_uses_marked_target_state_and_any_enemy_attack`。
- 报告已刷新：`docs/class-feature-audit-2026-08-07.md`、`docs/feature-automation-migration-matrix-2026-08-09.md`
  与 `reports/feature-ir-*`。当前 readiness 为 `already_full 312 / missing_runtime_contract 116 /
  consumer_partial 27 / needs_contract_review 6 / manual_boundary 3 / missing_source 35`。
- 修复 `scripts/compile-feature-automation-report.py` 的 demo pack 初始化顺序；报告连续运行两次
  输出一致，仍为 capability/operator `34/34`、compiler pilot `10`、semantic parity 全通过、
  demo `18 full / 4 partial / 2 manual`、legacy feature-name 分支 `65`。
- 其余 partial 未强行升级：仍依赖攻击骑手、强制移动、多目标状态、目标信息读取、完整法术书
  或新 UI 的候选保留原状态。后端全量 pytest 通过；本轮无前端源码变化，不做前端/浏览器声明。
- 必须继续保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：Feature IR 自动装配与拓展包导入基础

- 本轮生产化硬化已在当前工作树完成实现，尚未分离提交。严格门禁已通过：后端全量
  `backend/.venv/bin/pytest -q backend/tests`、新增源码/测试 Ruff、compileall 和
  `git diff --check`；正式审计仍固定为 `full 310 / partial 128 / dm_only 61`，总数 499。
- 新增 `domain/feature_operators.py` 的 `OperatorContract`：34 个 operator 都有稳定 contract
  version、required/optional 参数、精确类型、enum、数值边界、互斥/条件必填、兼容 trigger/
  condition/target/duration/action/resource、materializer 和 capability 绑定。未知参数、空参数、
  错误类型、可执行/导入 payload 均 fail-closed；`authored_ir`/`verified_mapping` 才能自动 full。
- `CapabilityDescriptor` 已禁止 `production_closed` wildcard，并要求 contract/materializer/evidence
  一致。默认目录现有 34 个 descriptor，施法上下文/目标情报等不完整能力仍为
  `production_partial`。
- 新增真实 `MaterializerRegistry`：operator 参数只投影到现有 advancement、资源、角色
  `feature_runtime`、移动/视线、法术伤害/治疗和 zero-HP consumer 的 canonical 字段；每个输出
  通过 block validator，带稳定来源、capability version、持久化位置和 execution status。
- 新增 10 条 authored Feature IR 稳定 ID，并在 core/subclass runtime registry 中优先使用编译/
  物化结果；旧名称配置仅保留兼容 fallback，不再参与这十条正式绑定的执行。字段级 parity 报告
  为 exact/equivalent 全通过，十条 status_authority 均为 `compiler`：
  `dnd2024.core.druid.druidic`、`dnd2024.core.rogue.thieves-cant`、
  `dnd2024.core.warlock.contact-patron`、`dnd2024.core.ranger.roving`、
  `dnd2024.core.ranger.wild-senses`、`dnd2024.subclass.rogue.thief.second-story-work`、
  `dnd2024.subclass.cleric.life.disciple-of-life`、
  `dnd2024.subclass.wizard.evoker.empowered-evocation`、
  `dnd2024.subclass.wizard.evoker.potent-cantrip`、
  `dnd2024.subclass.paladin.ancients.undying-sentinel`。
- `FeaturePackImporter` 现在把 trusted apply 写入带 runtime contracts 的本地
  `FeaturePackRegistry`，支持 reload、稳定 feature lookup、character pack/version pin、重复 apply
  幂等、版本 fingerprint 冲突、真实 clause diff 和 breaking migration plan；partial/manual/draft
  只可登记，不能进入 execution lookup。
- 演示包已重写为真实参数，仍严格 `18 full / 4 partial / 2 manual`；18 条全部 materialize/
  validator 通过。新增真实扇出 capability `modifier.passive.v2`，六条 authored FeatureSpec
  在注册前均 partial，注册后均 full，并经 `feature_runtime_registry` 与 `combat_start_modifiers`
  两个生产投影验证。
- 新机器报告：`reports/feature-operator-contracts-2026-08-09.json`、
  `reports/feature-ir-semantic-parity-2026-08-09.json`、
  `reports/feature-ir-production-fanout-2026-08-09.json`，以及更新后的 capability/pack/parity
  报告。pack readiness 逐条区分 schema/capability/materialized/validator/production-test/
  authority；当前仍有 65 个 legacy feature-name dispatch 分支，但十条正式 IR 绑定不再执行它们。
  报告生成器连续两次运行 hash 一致。
- 必须继续保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

- 本轮全程单线程，未创建、调用、委托或等待任何子代理。正式固定审计仍为 499 条：
  `full 310 / partial 128 / dm_only 61`，没有因为 shadow 编译器而回退正式状态。
- 新增严格 `feature-ir-1`：FeatureSpec、Clause、Effect、Condition、Input、Resource 和 Target
  均为版本化、可序列化、关闭字段集合；未知字段、schema、operator、重复 ID 和不安全 pack/namespace
  fail-closed。IR 不保存 Python、模块路径、任意表达式或执行回调。
- 新增 28 项 Capability Catalog 描述现有生产消费者，记录 producer、consumer、持久化、动作经济、
  支持的 trigger/condition/input/target/duration、CAS、幂等、UI 投影、证据测试和已知限制。只有
  `production_closed` capability 能参与 full；施法上下文和目标情报保持 `production_partial`。
- 新增 FeatureCompiler：逐 clause 解析 operator 与 capability 满足性，输出 full/partial/manual/invalid、
  精确 blocker、生成 runtime blocks、输入/持久化/UI/测试需求和确定性 fingerprint。新增
  `materialize_runtime_definition`，把完整编译结果投影到现有 feature runtime contract 形状，未复制
  CombatEngine、PlayerRoom、rest 或 spell economy 执行器。
- 现有审计进入 shadow：每行新增 `ir_available`、`compiler_status`、`status_authority`、
  compiled/total clause、unsupported clause IDs、capability IDs、legacy adapter 和 fingerprint。
  30 条已有 full 进入 parity 试点，10 条 parity 行切换 compiler authority，正式 status_counts 仍由旧
  审计标准保持不变。
- 新增 FeaturePackManifest 和版本化导入器，支持 dry-run、apply、幂等重放、pack/version fingerprint
  冲突保护、版本更新 migration metadata、namespace 校验和 partial/manual 保留。命令：
  `backend/.venv/bin/python scripts/import-feature-pack.py <manifest> --dry-run`。
- 测试拓展包 `backend/tests/fixtures/feature_packs/automation_demo_pack.json` 共 24 条，实际结果严格为
  `18 full / 4 partial / 2 manual`；不计入正式 499 条。6 条扇出测试证明注册一个通用 capability 后，
  六条 FeatureSpec 无需修改即可从 partial 变为 full。
- 机器报告：
  `reports/feature-capability-catalog-2026-08-09.json`、
  `reports/feature-ir-parity-2026-08-09.json`、
  `reports/feature-pack-readiness-2026-08-09.json`。
  人类文档为 `docs/feature-ir-architecture-2026-08-09.md` 和
  `docs/feature-pack-import-readiness-2026-08-09.md`。
- 当前边界：legacy adapter 仍用于 shadow；自然语言/generated draft 不能自动 full；需要新 producer、
  复杂状态、召唤、强制移动、法术书、额外回合或新 UI 的机制继续保持 partial。
- 必须继续保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：现有生产消费者收割 II

- 本轮全程由当前对话单线程完成，未创建、调用、委托或等待任何子代理。固定审计分母仍为 499：
  `full 286 / partial 147 / dm_only 66` → `full 310 / partial 128 / dm_only 61`，严格按实时代码
  证据计算，真实净增 `full +24`；dm_only 的变化来自已有可执行消费者被重新归类，不是减少审计范围。
- 本批没有新建攻击、召唤、复杂状态或多阶段反应底座，而是收割已有生产消费者：移动/视线（越野、野性感官、
  水生亲和、兽之形貌选择、梁上君子）、语言/固定能力（盗贼黑话、德鲁伊语、联络宗主）、防御与资源
  （不灭哨卫、仇敌誓言、圣洁武器、序列意识、恐惧伏击）、治疗/法术修改（生命门徒、神祝医者、极效治疗、
  强效塑能、强力戏法、料敌机先）均接入已有 runtime consumer；同一合同被多个特性复用，不按特性名写执行器分支。
- 真实消费者证据包括：装备感知的速度/攀爬/游泳与 30 尺盲视攻击可见性；长休选择过滤后的移动模式；
  角色卡/战斗快照中的权威跳跃属性与距离、圣洁武器有效光照半径；先攻感知加值、首回合速度、恐惧伏击
  每回合命中后骑手及其资源；仇敌誓言目标状态与目标归零后的资源恢复；魅力/法术伤害/失败戏法伤害和治疗
  公式从权威快照读取。未知选择、缺快照、过期窗口和不支持操作均 fail-closed。
- 选择型分支保持真实边界：兽之形貌按休息选择写入持久化选择并只启用对应一条移动/感知 modifier；
  料敌机先仍只计它已具备的结构化读取合同，未声称目标抗性/免疫/易伤信息读取已完成；高风险攻击骑手、
  强制移动、多目标状态 producer、完整反应链继续保持 partial。
- 验证：后端全量 `backend/.venv/bin/pytest -q backend/tests` 通过；`ruff check backend/src backend/tests`、
  compileall、`git diff --check` 通过。全仓 Ruff 若包含 `scripts`，仍只有仓库既有 4 个 N999 与 1 个 EXE001；
  本轮没有前端改动，因此不新增前端门禁或浏览器验收声明。
- 分离提交：代码 `eda6872`，测试/审计 `35f0a10`；本检查点文档/交接为本轮最后一个独立提交。
  必须继续保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：权威成长选项资产目录 II

- 全程由当前对话单线程完成，未创建、调用、委托或等待任何子代理。固定审计分母仍为 499：
  `full 276 / partial 154 / dm_only 69` → `full 286 / partial 147 / dm_only 66`，真实净增
  `full +10`。
- 新增 full：野蛮人、战士、圣武士、游侠、游荡者 1 级「武器精通」；术士 2/10/17
  级三条「超魔法」；圣武士、游侠 2 级「战斗风格」。各武器精通词条和各超魔法的
  具体效果仍是独立 runtime 合同，未继承父授予行的 full。
- 新增 2024 权威目录：37 把武器持有稳定 ID、分类、远近程、伤害、词条、精通和来源；
  10 个超魔法持有稳定 ID、中英名、术法点成本和来源。角色选项 API 与前端下拉框直接消费
  该目录，不接受自由文本伪造资产。
- 武器精通按职业策略 fail-closed：野蛮人仅简易/军用近战，战士任意简易/军用，
  圣武士/游侠/游荡者必须是角色已熟练武器。累计数量从职业成长表物化；长休重配由
  `rest_asset_loadout_reconfiguration` 真实执行，野蛮人/战士每次最多替换一把，其余三职业
  可重配完整 loadout；预览、确认、版本 CAS 和幂等重放均落库。
- 超魔法在 2/10/17 级各获得两个，任一后续术士等级可结构化 `old->new` 替换一个；
  重复、未掌握旧选项、非目录新选项全部拒绝。圣武士受祝福的勇士/游侠德鲁伊教战士
  现可在每个所属职业等级替换一道来源绑定戏法；新戏法必须属于对应 0 环目录，
  同一事务同步 `character.spells`、KnownSpell 和 PreparedSpell。
- 顺带修复两个验收暴露的通用问题：固定子职法术表显式标记为子职授予法术权限；前端详细
  角色卡使用角色 ID 回读查询结果，升级后不再继续显示旧对象快照。
- 验证：后端全量 `pytest -q backend/tests` 100% 通过；`ruff check backend/src backend/tests`、
  compileall、`git diff --check` 通过；前端 205 tests、typecheck、lint、production build 通过。
  真实 DM 浏览器使用隔离 SQLite 完成「超魔法下拉选择 → 预览 → 确认 → Lv2 回读」，
  页面 console error/warn 为 0；临时服务、标签页和数据库均已清理。
- 分离提交：权威目录 `ea1bcb7`；成长合同 `cc59fad`；真实消费者 `d30921f`；测试/审计
  `530cbbe`；前端受控选择器 `f316a57`；本文档交接为随后的独立 docs 提交。
- 法师记忆法术/法术精通/招牌法术需要新法术书准备替换与免槽位消耗合同，本批在
  主目标 +10 处止损，未为追求理想 +13 跨过新高风险底层边界。
- 必须继续保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：服务端权威成长资产选择与能力授予

- 全程由当前对话单线程完成，未创建、调用、委托或等待任何子代理。固定审计分母仍为 499：
  `full 268 / partial 157 / dm_only 74` → `full 276 / partial 154 / dm_only 69`，真实净增
  `full +8`。
- 新增 full：战士 1「战斗风格」、勇士 7「额外战斗风格」、吟游诗人 10「魔法奥秘」、游侠 2
  「熟练探险家」、德鲁伊 1「原初职能」、牧师 1「圣职」、法师 1「仪式学家」、勇气学院 3
  「战争训练」。圣武士/游侠 2「战斗风格」保持 partial：首次专长/职业戏法分支已接线，但以后职业
  等级的受祝福勇士/德鲁伊教战士戏法替换尚无权威替换事务，不能提前标 full。
- 通用成长合同扩展为 keyed `selected_asset`、replacement、expertise、language、closed option bundle
  与 conditional spell grant。战斗风格来自 2024 权威专长目录，验证类别、前置、重复和 Fighter
  `old->new` 替换；职业授予行 full 与具体风格 feat 的独立 runtime 状态严格分离。
- 真实消费者：升级事务写入 features/skills/proficiencies/spells；技能专精和原初/圣职技能加值由
  `skill_modifier` 消费；护甲/武器熟练由装备/攻击规则消费；魔法奥秘沿普通吟游诗人学习与替换路径；
  仪式学家仅允许法术书中、带 ritual 标签的法师法术未准备仪式施放且不耗法术位；战争训练的已装备、
  已熟练武器法器由 `spell_economy_service` 校验。
- 迁移矩阵 schema v2 现在显式区分 `grant_status`、`selected_asset_status`、`effect_status`，并记录权威
  catalog、输入、duplicate/replacement policy、前置校验、持久化目标和下游 consumer。10 个候选都有
  稳定 feature ID；参数化测试锁定 8 full / 2 partial。
- 真实 API 覆盖：战斗风格首次授予、确认、替换与勇士额外风格；熟练探险家专精/语言及真实技能调整值；
  原初职能 Warden 熟练；未准备法师仪式且幂等重放；勇气诗人武器法器。前端测试验证只提交
  `feature_choices_by_key`，不再用自由文本伪造战斗风格。
- 验证：后端全量 pytest 通过；`ruff check backend/src backend/tests`、compileall、
  `git diff --check` 通过；前端 205 tests、typecheck、lint、production build 全部通过。真实 DM 浏览器
  以隔离数据库完成“权威防御风格选择 → 预览 → DM 确认 → 刷新角色卡”，最终显示 Lv2、独立
  `防御Defense` feat 和 3 项武器精通，控制台 error/warn 为 0；临时服务已关闭。
- 分离提交：合同基础 `d997fad`；生产消费者 `7f79815`；测试/审计/矩阵 `f24e2b6`；前端通用选择器
  `14cd3d8`；本文档提交随后单独生成。继续保留且不得暂存/提交：
  `backend/tests/integrations/`、`backend/tests/ollama.py`。
- 下一批最高收益：先补通用“已授予戏法资产替换”事务，闭合圣武士/游侠两条战斗风格；随后从矩阵的
  `progression_grant` / `passive_modifier` 选择已有 consumer 的固定熟练、抗性或被动数值批次，避免重新
  建设攻击骑手、移动、召唤或多阶段反应平台。

# 2026-08-09 长执行检查点：批量迁移矩阵与传奇恩惠授予簇

- 全程单线程执行，未创建、调用、委托或等待任何子代理。固定审计分母仍为 499：
  `full 256 / partial 169 / dm_only 74` → `full 268 / partial 157 / dm_only 74`，真实净增
  `full +12`。
- 新增的 12 个 full 是全部 2024 核心职业的 19 级「传奇恩惠」职业授予行：野蛮人、吟游诗人、
  牧师、德鲁伊、战士、武僧、圣武士、游侠、游荡者、术士、魔契师、法师。
- 边界没有放宽：19 级职业特性的完整规则只是“从权威专长目录选择并授予一个符合前置条件的传奇
  恩惠专长”。该职业行现在拥有 `selected_asset_grant` 合同，真实 consumer 为
  `advancement_service_and_feat_prerequisite_validator`；缺选择、错误分类、等级/其他前置不满足均
  fail-closed，确认后写入角色 features，角色版本与升级事务维持既有 CAS/幂等语义。
- 被选择的具体传奇恩惠仍保存为独立 `feat` 运行时合同，当前明确保持 `dm_only`。职业授予行的 full
  不会传播给所选专长，也不声称 12 个传奇恩惠专长的具体战斗效果已经自动化。
- `scripts/plan-feature-automation-migrations.py` 升级为矩阵 schema v2：499 行都有稳定 feature ID、
  当前原因/section、触发时点、producer/consumer、规范缺口、资源/动作经济/玩家或 DM 输入、权威
  目标/状态需求、风险、复用能力簇、阻塞原因，以及参数化合同测试和代表性 E2E 证据。输出稳定排序，
  默认生成 `reports/feature-automation-migration-plan-2026-08-07.json` 与
  `docs/feature-automation-migration-matrix-2026-08-09.md`。
- 参数化合同测试一次验证 12 个职业行共享同一强类型合同；真实 API 测试验证缺输入拒绝、权威目录和
  前置校验、preview/confirm、持久化与幂等重放，并验证具体 feat 保持独立 dm_only。
- 第二候选簇在收益门槛处止损：4 条战斗风格授予行仍缺权威战斗风格专长目录/分类验证，且已选择风格
  的效果消费者不完整，不能沿用传奇恩惠边界直接升级。其余较大簇仍需要状态、目标、资源、移动、
  攻击骑手或玩家输入的复合闭环，不在本轮新增高风险平台。
- 验证：后端全量 pytest、`ruff check backend/src backend/tests`、compileall、`git diff --check`；
  前端 204 tests、typecheck、lint、production build 全部通过。无前端/交互改动，因此未运行浏览器
  验收。全仓 scripts Ruff 仍仅命中既有 4 个 N999 与 1 个 EXE001。
- 分离提交：矩阵基础 `c55b80b`，运行时代码 `69eb54c`，测试/审计基线 `9ec638c`，文档提交随后
  单独生成。继续保留且不得暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：权威 Attack 动作序列与攻击槽替换

- 固定审计分母仍为 499：`full 254 / partial 171 / dm_only 74` →
  `full 256 / partial 169 / dm_only 74`，真实净增 `full +2`。新增 full 为奥法骑士
  「战争魔法 War」与「精通战争魔法 Improved War」；战斗大师父级「卓越战技」仍保持
  partial，未因指挥官奇袭单个战技闭环而整体升级。
- 新增持久化 `attack_action_sequence`：开始时从冻结的 `feature_runtime.combat_start`
  读取 `attack_action_count` 与 `attack_slot_replacements`，只消费一次 action；每槽记录
  pending/resolved/cancelled/expired、结算动作、替换类型/策略、目标、资源事务和幂等键。
  序列与槽位共用 CombatAction version CAS；同一槽并发确认只会有一个成功，幂等重放不重复
  伤害或资源消费。回合推进会把未用槽位标为 expired。
- 普通槽只绑定现有真实武器/徒手攻击入口，明确拒绝法术攻击、反应、附赠动作和追加攻击冒充；
  旧单次攻击继续兼容，存在开放序列时拒绝旧 Extra Attack 预算叠加。Action Surge 的
  `extra_action_budget` 仍由既有动作经济门消费，可在同回合建立第二个独立序列。
- 战争魔法：冻结策略只允许角色权威 KnownSpell 中的一动作法师戏法，消费 1 个攻击槽且不重复
  消费 action；普通攻击槽仍可继续。精通战争魔法：只允许已准备的一环/二环一动作法师法术，
  原子消费 2 个未用攻击槽，并在同一 CombatEngine 事务消费 `spell_slots_N`；槽不足、未准备、
  非法来源/环阶/施法时间全部 fail-closed。
- 指挥官奇袭：冻结的 `replace_attack_with_ally_attack` 策略原子消费战斗大师的一个攻击槽与一枚
  权威卓越骰，校验盟友版本、阵营、存活/失能、反应和可见/可听条件，创建通用
  triggered_attack_window。窗口分别记录 owner、attack actor、resource owner、action-economy
  owner；盟友真实武器/徒手攻击消费自己的 reaction，命中时服务端把实际卓越骰值加入伤害，
  失手/拒绝仍保留已付槽位与卓越骰。接受、拒绝、CAS 和重放均由真实 API 测试覆盖。
- DM/玩家双端新增最小攻击序列 UI：开始、槽位计数、刷新恢复、合法普通/法术替换过滤、放弃剩余
  槽位和冲突后刷新。浏览器实测 DM 创建后刷新恢复，玩家看到同一槽位，玩家放弃后 DM 刷新同步
  关闭；两端 console error/warn 均为 0。
- 验证：后端全量 `pytest -q backend/tests` 通过；`ruff check backend/src backend/tests`、
  compileall、`git diff --check` 通过；前端 204 tests/typecheck/lint/build 全部通过。全仓 scripts
  Ruff 仍只命中既有 4 个 N999 与 1 个 EXE001。
- 提交：代码 `d5c7728`，测试与审计基线 `1a473b4`，本文档提交随后单独生成。继续保留且不得
  暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。
- 仍保持 partial：卓越战技/究极战技（其余战技分支未闭环）、坚韧（尚未把所有既有战技入口统一
  到 maneuver_payment_policy）、以及需要攻击骑手、强制移动、状态 producer 或独立目标信息
  读取系统的候选。当前没有发现另一个可安全迁入攻击槽替换平台的同构消费者。

# 2026-08-09 长执行检查点：分阶段攻击结算平台安全消费者耗尽

- 实时固定审计仍为 499 条：`full 254 / partial 171 / dm_only 74`。本长执行从 `full 249 /
  partial 176 / dm_only 74` 开始，真实净增 `full +5`（辉煌防御、语出惊人、如影随行、斗转星移、
  防守战术），全部由真实 API 回归覆盖，不是配置声明。
- 已实现不识别职业/特性名称的分阶段攻击结算状态机：`attack_resolution_intervention` 支持
  after_provisional_hit 与 before_attack_roll_resolution 两阶段，冻结原始命令、初始 AC/掩体、
  攻击总值、上下文、目标/攻击者版本与候选干预；接受后服务端重算命中/失手并改写伤害命令。
  已支持 add_to_target_ac、subtract_from_attack_total、impose_disadvantage；未知操作 fail-closed。
- 安全消费者逐条闭环：
  - 辉煌防御：10 尺内可见自我/盟友被命中开窗；AC 加值重判；变失手且攻击者在武器触及内时创建
    同一反应的反击窗口。
  - 语出惊人：攻击分支在初步命中后暂停并减值重判；属性/技能检定分支仅成功时对旁观者反应者开放、
    动态诗人骰面物化、失败不误开；伤害分支由附近可见 bard 打开 pre-damage 窗口按段减伤。
  - 如影随行：攻击声明后暂停，接受则提交两个 d20 与总值、服务端取较低 d20 重算并继续；战后开放
    同一反应的 30 尺可见未占用传送窗口。
  - 斗转星移：魅惑免疫 + 半伤反应 + 攻击者感知豁免（失败受到等同实际承受伤害的心灵反伤）。
  - 防守战术：短休/长休选择 escape_the_horde 或 multiattack_defense；借机攻击劣势与同攻击者
    本回合后续攻击劣势均由权威攻击上下文强制附加。
- 剩余候选需要独立高风险基础系统，不伪造 full：复仇之魂（仇敌誓言标记生产者）、坚韧复仇（反应内
  速度归零+半速移动）、灼光复仇（死亡豁免救援+群体光耀+目盲）、料敌机先（目标信息读取）、
  战争魔法/精通战争魔法与指挥官奇袭（攻击次数替换，按指令明确不在本 Goal）。
- 验证：后端全量 `pytest -q backend/tests` 通过；前端 204 tests/typecheck/lint/build 通过；
  新增源码/测试 Ruff、compileall、`git diff --check` 通过。全量 Ruff 仍只命中仓库原有 scripts 的
  N999/EXE001。
- 提交（全部分离）：追加攻击平台 `65cd8ce/4c8b0a3/de7ec8f`，分阶段状态机 `f6c6e97/8659e36/65b660b`，
  如影随行 `8a94e1c/d589b86/8453bc7`，斗转星移 `a22a0c2/b5964ae/f4f8e0c`，防守战术
  `b27050b/a5473da/4815138`。必须继续保留且不暂存/提交：`backend/tests/integrations/`、
  `backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：防守战术休息选择与 incoming 劣势

- 实时固定审计仍为 499 条；本切片前 `full 253 / partial 172 / dm_only 74`，当前为
  `full 254 / partial 171 / dm_only 74`。新增 full：「游侠·猎人·7·防守战术」。
- 休息选择复用 rest_service 的 rest_choice 积木：短休/长休提交 `defensive_tactics`
  选择（escape_the_horde / multiattack_defense），校验选项并持久化到角色资源。
- 冲出重围：当攻击者为借机攻击（reaction + leaves_reach/借机触发）且目标选择
  escape_the_horde 时，服务端在权威攻击上下文强制附加劣势源；普通攻击不受影响。
- 多重防御：攻击命中选择 multiattack_defense 的目标时，记录 `multiattack_defense_hits`
  按回合键存攻击者；同攻击者本回合后续攻击在攻击上下文强制附加劣势源。两分支均通过
  `attack_roll_mode` 冲突校验证明真实生效（提交 normal 模式会被拒绝）。
- 验证：防守战术 3 个真实 API 测试通过；全量后端 pytest、前端 204 tests/typecheck/lint/build、
  新增源码/测试 Ruff、compileall、`git diff --check` 通过。
- 已分离提交：代码 `b27050b`，审计基线测试 `a5473da`；文档/交接随后单独提交。必须继续保留且不暂存/提交：
  `backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：斗转星移减半与心灵反伤

- 实时固定审计仍为 499 条；本切片前 `full 252 / partial 173 / dm_only 74`，当前为
  `full 253 / partial 172 / dm_only 74`。新增 full：「魔契师·至高妖精宗主·10·斗转星移」。
- 魅惑免疫走既有 condition_immunity 消费者；被可见敌人命中后打开 pre-damage 反应窗口，
  消耗 `beguiling_defenses` 资源（1 次，长休恢复），`multiply_each_component 0.5` 将最终伤害
  减半（向下取整）。
- 新增 `beguiling_reflection` 后续窗口：伤害结算后攻击者须提交感知豁免总值（DC = 8 + 熟练 +
  魅力调整值）；失败则攻击者受到等同实际承受伤害（HP/临时 HP 损失合计）的心灵伤害，走真实
  抗性/免疫结算；成功则无反伤。窗口 CAS、版本、幂等与过期均持久化。
- 验证：斗转星移 3 个真实 API 测试（减半、失败反伤、成功无反伤）通过；全量后端 pytest、
  前端 204 tests/typecheck/lint/build、新增源码/测试 Ruff、compileall、`git diff --check` 通过。
- 已分离提交：代码 `a22a0c2`，审计基线测试 `b5964ae`；文档/交接随后单独提交。必须继续保留且不暂存/提交：
  `backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：如影随行掷骰前劣势与战后传送

- 实时固定审计仍为 499 条；本切片前 `full 251 / partial 174 / dm_only 74`，当前为
  `full 252 / partial 173 / dm_only 74`。新增 full：「游侠·幽域追猎者·15·如影随行」。
- 新增 `before_attack_roll_resolution` 阶段：攻击声明但未提交最终 d20 时，若受击单位拥有
  该阶段反应，先冻结原始命令并打开攻击决议窗口。接受后必须提交两个真实 d20 与对应总值，
  服务端选择较低 d20 的总值重写 `attack_roll_total/attack_d20/attack_roll_mode=disadvantage`
  并重算命中/失手；拒绝则保留单 d20 流程。不会把已提交的单 d20 事后改标签为劣势。
- 战后传送：攻击结算完成（无论命中或失手）后，如影随行同一反应开放 `attack_resolution_teleport`
  窗口；接受必须提交目的地行列，服务端校验 30 尺距离、可见与未占用；传送复用现有
  `_apply_feature_teleport`，不重复消费反应。窗口版本、CAS、幂等和过期均走 CombatAction。
- 验证：如影随行 3 个真实 API 测试（含劣势重算、失手不结算、同反应传送、拒绝路径）通过；
  全量后端 pytest、前端 204 tests/typecheck/lint/build、新增源码/测试 Ruff、compileall、
  `git diff --check` 均通过。全量 Ruff 仍只命中仓库原有 scripts 的 N999/EXE001。
- 已分离提交：代码 `8a94e1c`，审计基线测试 `d589b86`；文档/交接随后单独提交。必须继续保留且不暂存/提交：
  `backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：分阶段攻击结算与反应干预状态机

- 实时固定审计仍为 499 条；本切片前 `full 249 / partial 176 / dm_only 74`，当前为
  `full 251 / partial 174 / dm_only 74`。真实新增 full：「圣武士·荣耀之誓·15·辉煌防御」和
  「吟游诗人·逸闻学院·3·语出惊人」。两条都通过真实 API 回归验证，不是配置声明。
- 新增不识别职业/特性名称的 `attack_resolution_intervention` 领域合同与持久化窗口：攻击进入
  `after_provisional_hit` 后暂停，冻结原始命令、初始 AC/掩体、攻击总值、攻击上下文、目标/攻击者
  版本和候选干预集合；DM/玩家选择接受或放弃，接受后服务端重算命中/失手并改写伤害命令与
  `effective_ac` 上下文。`add_to_target_ac`、`subtract_from_attack_total`、`impose_disadvantage`
  已接入，未知操作 fail-closed。
- 辉煌防御：10 尺内可见自我/盟友被命中时开窗；消费反应与 `glorious_defense` 资源（长休恢复，
  上限 max(1, 魅力调整值)）；AC 加值重判；变失手且攻击者在武器触及内时，创建 `triggered_attack_window`
  作为同一反应的一部分（不再扣反应/资源）；仍命中则正常进伤害；暴击在变失手时不产生暴击伤害。
- 语出惊人：三分支全部真实闭环。攻击检定分支在初步命中后暂停，从攻击总值减诗人骰并重判；
  属性/技能检定分支复用 player-roll 的 `after_d20_test` 窗口，仅成功后开放、旁观者反应者 60 尺可见、
  动态诗人骰面物化、失败检定不误开；伤害分支由旁观者 bard 在受击单位附近 60 尺可见时打开
  pre-damage 窗口，按诗人骰从各伤害段顺序减伤、最低 0。
- 通用链：反应、角色资源（含快照内资源）、攻击/AC/伤害重算、幂等重放、CAS 和窗口版本全部落库；
  pre-damage 与 roll-intervention 消费者扩展支持旁观者反应者（窗口 actor 不再是受击目标本人）。
- 验证：新增攻击决议/辉煌防御/语出惊人定向测试全部通过；全量后端 `pytest -q backend/tests` 通过；
  前端 `npm test -- --run`（204 tests）、typecheck、lint、build 通过；新增源码/测试 Ruff、compileall、
  `git diff --check` 通过。全量 `ruff check backend/src backend/tests scripts` 仍只命中仓库原有
  scripts 的 N999/EXE001。
- 已分离提交：代码 `f6c6e97`，审计基线测试 `8659e36`；文档/交接随后单独提交。必须继续保留且不暂存/提交：
  `backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 长执行检查点：事件驱动追加攻击窗口平台

- 实时固定审计仍为 499 条；本切片前 `full 247 / partial 178 / dm_only 74`，当前为
  `full 249 / partial 176 / dm_only 74`。真实新增 full 只有「野蛮人·狂战士道途·10·报偿」和
  「吟游诗人·勇气学院·14·战斗魔法 Battle Magic」；战斗大师「反击」已接入按已学习战技过滤的
  追加攻击合同，但其父特性仍是复合 partial，不计作独立 full。
- 新增不识别职业/特性名称的 `triggered_attack_window`：封闭事件词表（受伤、施法、敌方攻击未命中等）、
  父动作/版本、因果深度、反应者/目标集合、权威网格距离与视线、合法武器/徒手动作、动作经济、资源、
  过期和窗口版本均持久化到 `CombatAction`。确认时校验窗口 CAS、真实动作 profile、目标和玩家提交的 d20；
  反应/资源只消费一次，接受、放弃和重复请求均幂等，旧窗口在回合边界失效。
- 真实消费者：`CombatEngineService.confirm` 在实际伤害、单动作结构化施法和敌方近战攻击未命中后派发窗口；
  `PlayerRoomService.attack` 复用同一普通攻击/伤害结算器，新增玩家面板目标、动作、d20、攻击总值和伤害总值输入；
  DM 与玩家均有窗口放弃 API。未接入的复仇之魂、辉煌防御、指挥官奇袭仍保持 partial。
- 新增/扩展：`feature_blocks` 现在验证追加攻击事件合同；战斗大师 `反击` 的 trigger 仅在学习集合中出现，
  资源编译层绑定 `superiority_dice`。没有复制第二套攻击、伤害、资源或移动结算器。
- 验证：追加攻击定向测试 2 个、战技 registry 测试通过；全量后端 `pytest -q backend/tests` 通过；前端
  `npm test -- --run`（204 tests）、typecheck、lint、build 均通过。真实浏览器验收也已完成：DM 模拟战斗页
  和玩家一次性入口均正常显示，后端/SQLite/索引/模型状态正常，两端控制台无 error/warn。全量
  `ruff check backend/src backend/tests scripts` 仍会命中仓库原有脚本文件的 N999/EXE001（非本切片代码）；
  本切片源码/测试 Ruff、compileall、`git diff --check` 通过。
- 已分离提交：代码 `65cd8ce`，审计基线测试 `4c8b0a3`，文档/交接 `de7ec8f`。必须继续保留且不暂存/提交：
  `backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-08 长执行检查点：战斗大师卓越骰与战技通用平台

- 当前固定分母 499；实时审计起点 `full 246 / partial 179 / dm_only 74`，本切片结束为
  `full 247 / partial 178 / dm_only 74`。只新增了「精通战技」这一条 full；「卓越战技」、
  「料敌机先」、「坚韧」、「究极战技」仍保持 partial。
- 新增不识别职业/特性名称的卓越骰资源生产与生命周期：战士等级对应 `4d8、5d8、5d10、6d10、
  6d12`，短休/长休恢复，exact 上限支持升级、降级、重复升级和快照重建，资源真实写入角色
  状态并由运行时 registry 消费。
- 新增结构化战技选择/替换和豁免 DC 能力选择：3/7/10/15 级累计选择，重复、越级、替换未学习
  战技和非法输入 fail-closed；力量/敏捷选择持久化，不以 DM override 代替普通玩家输入。
- 首批真实战技消费者为「伏击」「领导风范」「战术预估」：复用玩家 d20 检定、动态卓越骰面、
  资源 CAS、动作幂等和重放，不复制第二套骰子结算器。仍未接入的攻击骑手、反应攻击、目标体型、
  强制移动、状态和额外攻击分支没有被误报为 full。
- 「精通战技」full 的真实消费者是升级资源编译、角色状态持久化、短休/长休恢复和快照重建；
  它并不代表战斗大师整条子职业已自动化。坚韧仍等待真实战技入口后才能实现每回合一次的 d8
  替代消费，究极战技仍等待全部 20 个战技选项闭环，料敌机先仍等待可见目标信息读取与恢复链。
- 代码提交：`36ac2dc`；审计基线测试提交：`e7aa6e0`。本检查点文档与迁移计划随后单独提交。
- 本轮无前端源码变更，因此未运行前端测试、构建或浏览器验收；后端门禁和实时审计仍为交付依据。
- 必须继续保留且不暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-08 长执行检查点：真力注拳与月光飞步生命周期

- 当前固定分母 499，最新真实审计：`full 242 / partial 182 / dm_only 75`；本 Goal 起点 `227/195/77`，真实净增 15，继续推进，未因超过 223 停止。
- `真力注拳`：武僧核心特性的最终伤害类型选择已经接入玩家攻击生产入口。服务端只接受结构化徒手攻击、`force/original` 明确输入和单一基础伤害段；伤害类型覆盖发生在实际伤害组件结算前，非法武器、多段伤害、未授予特性均 fail-closed；攻击结果、HP 变化和幂等重放均已覆盖。
- `月光飞步`：附赠动作的资源从配置编译层绑定到真实特性资源；资源不足时可提交二至九环法术位，CombatEngine 在同一事务中校验并扣除法术位、恢复并消费一次特性使用。显式目的地经过权威网格距离、边界、占用校验；`moonlight_step` 持久化到回合末，攻击上下文授予一次优势并在下一次攻击中消费。
- 新增/修复：`CombatFeatureActionCommand.reset_spell_slot_level`；运行时状态注册 `moonlight_step`；资源重置记录、角色版本更新、CombatAction 幂等重放；对应 API 生命周期测试和真实玩家攻击测试通过。
- 验证：全量 `backend/.venv/bin/pytest -q backend/tests`、Ruff、compileall、`git diff --check` 已通过；本轮代码与 docs/交接仍需分开提交。
- 工作树必须继续保留且不暂存/提交：`backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-08 长执行检查点：自然守御地形选择与动态抗性

- 当前固定分母 499，最新真实审计：`full 240 / partial 183 / dm_only 76`；本 Goal 起点 `227/195/77`，已真实净增 13，仍继续推进。
- `自然守御`：长休动作 `circle_land_terrain_choice` 接受荒漠/极地/温带/热带四选一，并由休息服务持久化到 `circle_land_terrain.selected`；伤害防御消费者按该选择映射火焰/寒冷/闪电/毒素抗性，条件免疫消费者独立执行中毒免疫，缺失或非法选择 fail-closed。
- 代码提交：`0510698 feat: automate nature ward terrain defense`；本检查点的交接与审计文档需单独提交。工作树只应保留用户规定的两个未跟踪路径。

# 2026-08-08 长执行检查点：战斗激励双模式攻击消费

- 当前固定分母 499，最新真实审计：`full 241 / partial 182 / dm_only 76`；本 Goal 起点 `227/195/77`，已真实净增 14，仍继续推进。
- `战斗激励`：吟游诗人激励动作授予骰时，若授予者拥有战斗激励合同，目标骰记录持久化 `mode_options=[defense,offense]`；攻击请求必须提交合法模式和骰值。`defense` 将激励值加入目标 AC，可能把命中变为失手；`offense` 在命中后把激励值加入首个伤害段。两种模式都复用骰面校验、一次性消费、版本更新和幂等重放。
- 代码提交：`b5609f3 feat: automate combat inspiration modes`；本检查点的交接与审计文档需单独提交。工作树只应保留用户规定的两个未跟踪路径。

# 2026-08-08 长执行检查点：元素亲和真实选择链

- 当前固定分母 499，最新真实审计：`full 239 / partial 184 / dm_only 76`；本 Goal 起点 `227/195/77`，已真实净增 12，仍继续推进，未因超过 223 停止。
- `元素亲和`：升级选择必须是 `damage_type:acid/cold/fire/lightning/poison` 之一；绑定后的抗性和法术魅力加值共享同一选择，资源/攻击入口以真实伤害类型匹配并按每回合幂等使用。
- `光耀之魂`：光耀抗性走共享伤害防御；攻击/法术入口把每个目标的真实伤害类型交给骑手消费者，玩家必须明确选择单一目标和是否使用，服务端校验火焰/光耀法术、魅力调整值、每回合一次和幂等使用。
- `邪魔体魄`：短休/长休由玩家提交非力场伤害类型，`rest_choice` 预览与确认把选择写入 `fiendish_resilience_choice.selected`；战斗伤害防御解析器在有角色会话时读取持久化选择，只应用选中的单一抗性，缺失或非法值不授予抗性。
- `凶蛮打击`：攻击服务把实际结构化优势模式传给通用骑手解析器；在狂暴、鲁莽攻击、力量武器/徒手命中时，玩家必须显式选择放弃优势并提交合法 1d10 结果，服务端校验每回合一次、伤害类型沿用武器和幂等使用。
- `意念守护`：心灵伤害抗性由真实伤害防御解析器消费；回合开始动作要求玩家从当前魅惑/恐慌中选择一个，原子消耗共享 `psionic_dice:战士` 资源并移除对应状态及其结构化效果。窗口、状态存在性、资源 CAS、版本校验与幂等重放均已测试。
- `战争祭司`：附赠动作触发一件玩家选择的近战武器攻击或徒手打击；`special_inputs.weapon_action_name` 必须指向角色真实动作，禁止法术、区域、多目标、远程或非武器动作。玩家攻击入口复用选定动作的骰伤、范围、目标和攻击属性，同时保留 5 尺敌对目标约束。
- 资源链：使用次数由感知调整值绑定，至少 1 次，短/长休恢复；CombatActionCommand 将特性资源送入 CombatEngine，由资源 CAS/幂等确认消费一次，PlayerRoom 不再二次扣除。动作经济通过 bonus_action 原子更新。
- 定向集成测试覆盖角色动作选择、徒手/武器资格拒绝、目标与伤害结算、资源 2→1、附赠动作消耗和重复请求路径；Ruff、compileall、`git diff --check` 已通过。
- 代码提交：`4230b9b feat: automate war priest bonus attack`；文档与交接本次变更需单独提交。工作树只应保留用户规定的两个未跟踪路径。

# 2026-08-08 长执行检查点：专业预言、钢铁意志与高阶防守

- 当前固定分母 499，最新真实审计：`full 233 / partial 190 / dm_only 76`；本 Goal 起点 `227/195/77`，已真实净增 6，继续执行，未因超过 223 停止。历史检查点保留，最新状态见上方。
- `钢铁意志`：`save:wisdom`，或已有感知豁免熟练时选择 `save:intelligence` / `save:charisma`；升级服务、战斗快照和实际豁免解析消费同一选择。
- `专业预言`：二环以上预言法术消耗普通法术位后，提交低于施法环阶且不超过五环的已消耗法术位恢复；预览、CAS、幂等、仪式/免费施法拒绝已接入 Spell Economy。
- `高阶防守战术`：伤害前反应窗口选择单一具体伤害类型，抗性 CombatEffect 持续至目标回合结束；混合伤害 fail-closed。
- 代码提交与 docs/交接提交保持分离；当前工作树只保留用户要求的未跟踪 `backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-08 长执行检查点：信实坐骑免费施法

- 代码提交：`4baf94c feat: automate faithful steed free casting`；交接/审计文档需单独提交。
- 当前固定分母 499，审计状态：`full 230 / partial 193 / dm_only 76`。本 Goal 起点 `227/195/77`，已真实净增 3（预兆、高等预兆、信实坐骑）。历史检查点保留；最新状态见上方。
- 信实坐骑完整链：圣武士 5 级核心运行时资源 `faithful_steed`（1 次，长休恢复）；固定法术授予「寻获坐骑」并标记始终准备；Spell Economy 的 preview/confirm 接受显式 `free_cast=true`，只允许与该已授予法术的 resource metadata 匹配，跳过普通法术位，校验资源余额，确认时原子扣除角色资源并通过 OperationTransaction 幂等重放返回同一结果。
- 不是只落库：免费施法输入、角色版本 CAS、法术准备校验、法术等级、材料校验、资源消费和重放均由真实 API 消费者执行；没有匹配授权 metadata 或资源不足会 fail-closed。
- 定向门禁：`test_spell_economy.py`（免费施法/重放）、升级/休息/预兆测试、Ruff、compileall、`git diff --check` 通过；全量 pytest 继续作为长执行门禁。
- 继续同一 Goal，不在 `+3` 停止；下一步审查其余资源/恢复或状态/防御/移动候选，优先全条规则可由现有消费者闭环者。

# 2026-08-08 长执行检查点：预兆与高等预兆真实 D20 池

- 代码切片尚未提交；文档与交接需和代码分开提交。
- 本 Goal 起点固定审计为 `full 227 / partial 195 / dm_only 77`；当前审计为 `full 229 / partial 193 / dm_only 77`，净增 2 条，来自「预兆」与「高等预兆」。
- 真实生产链：长休请求的 `feature_recovery_choices.portent_pool` 必须由玩家/DM 提交完整 1–20 骰值；休息确认持久化 `portent_dice.available_values`，未提交的新长休会清空旧池；预掷窗口从角色快照运行时合同暴露池值；玩家在真实 `player-roll` prompt 选择一颗骰子；确认时校验天然 d20、目标可见性、检定类型和骰池索引，原子消费单颗资源并写入有效总值。
- 幂等链：action request 持久化所选骰子和有效结果；相同 `X-Request-ID` 或已消费 action 重放直接返回同一结果，不再次消费；资源与战斗快照版本同步更新。
- 领域 `replace_d20_from_pool` 只负责结构化结果校验与替换，不能单独计 full；full 依赖本条完整 rest/consumer/input/CAS/idempotency 链。
- 定向门禁已通过：`test_roll_intervention.py`、`test_rests_api.py`、`test_combat_engine.py`（含长休生成、预掷选择、消费和幂等重放）；Ruff、compileall、`git diff --check` 通过。全量后端 pytest 是本检查点提交前门禁。
- 下一步继续同一 Goal，不停在 `+2`：逐条复核其余 `roll_intervention` consumer_partial，只有所有触发窗口、目标、资源、恢复、输入和持久化分支闭环才升级；随后推进资源/恢复、状态/防御/移动的安全独立簇。

# 2026-08-08 长执行检查点：预置 D20 池审计安全边界

- 继续执行了第二轮高扇出候选反审计：`resource_lifecycle` 非 full 候选最多 24 条但混合免费施法、资源转换、持续状态、目标选择和复杂分支；`aura_passive`、`state_lifecycle`、`action_trigger` 也分别混合范围几何、状态 producer、动作触发和资源语义，不能拼成一个完整同构批次。
- 独立语义扫描中，非 full 的单积木候选上界为成长授予 13、伤害/治疗 5、动作触发 4，其余单组不超过 2；固定无消耗法术文本只有少数条目且附带资源/目标/语言或仪式门禁。证据：`/private/tmp/semantic-cluster-audit.json`。
- 因此本轮仍没有安全的 `+25 full` 批次；未写入 D20 池或其他伪通用积木，也未改变 `full 227 / partial 195 / dm_only 77`。后续若继续，必须降低“单批 +25”约束或明确选择要先完成的异构小簇，不能靠审计分类制造增量。

- 实时 499 条审计：`full 227 / partial 195 / dm_only 77`；工作树除用户必保留的 `backend/tests/integrations/`、`backend/tests/ollama.py` 外干净。
- 本轮先按要求逐条审计 `roll_intervention`：46 条中 25 条已 full、21 条 `consumer_partial`。严格同时具备长休生成多枚预言骰、持久化、检定前替换、属性/技能/豁免/攻击入口、每回合一次、跨目标可见性/距离、长休清理、输入、CAS 和幂等的只有「预兆」与「高等预兆」两条审计行。
- 「混乱之潮」是自身一次性优势并带狂野魔法浪涌恢复；「归复平衡」是优势/劣势抵消；「现世传说」「专心炽志」是失败后重骰；其他候选含攻击、光环、状态、传送、召唤或多分支，不能伪装成同一预置池合同。没有因此写配置或升级 `full`。
- 对 499 条源码描述再做未依赖审计关键词的语义扫描，直接命中“检定前/掷出 d20 前/预置骰/替换骰”的只有 4 条：宇宙预兆、序列意识、混乱之潮、预兆；前 3 条分别是奇偶加减骰、持续最低值和自身单次优势，不是预置池替换。
- 由于严格同构候选远少于用户规定的 25 条正式批次门槛，本轮未实现 D20 池 helper，也未把领域测试算作增量。审计证据：`/private/tmp/audit-live.json`、`/private/tmp/plan-live.json`。
- 下一步只能在另一个真实高扇出合同达到至少 25 条完整候选后推进；优先继续审计资源/恢复、状态/防御和动作触发簇，任何缺少附带分支、权威 producer、真实输入或幂等链的条目保持 partial。

# 2026-08-08 长执行检查点：自然恢复、百折不挠与妖冶娴都

- 代码检查点提交：`967d3c7 feat: close rest survivor and glamour feature contracts`；文档与交接更新需单独提交。
- 固定审计总数 499；当前真实状态 `full 227 / partial 195 / dm_only 77`。本长执行起点是 `201/221/77`，前一完整批次真实净增 `full +25`，随后“狂怒”再净增 1，已越过 `full 223` 目标但按用户要求继续推进。
- 新增 `自然恢复`：短休选择 1–5 环法术位，总环阶不超过德鲁伊等级一半向上取整；消耗 feature resource、恢复具体 slot、长休恢复使用次数，选择通过 `feature_recovery_choices` 持久化并校验。
- 新增 `百折不挠`：死亡豁免优势、天然 18–20 视为成功、血量不高于一半时每回合开始恢复 5+体质调整值；死亡豁免接受双 d20 输入，回合触发使用版本/轮次幂等状态。
- 新增 `妖冶娴都`：魅力属性检定加入感知调整值，且必须选择一项技能熟练；前者进入 `_resolve_player_roll`，后者进入 advancement service 的技能状态写入和真实技能消费者。显式 DM override 可跳过缺失选择，但普通请求严格拒绝。
- 还修复了 Survivor 的 `DeathSaveCommand.rolls` 输入、休息恢复服务的自然恢复分支以及技能选择的 DM override 兼容路径。
- 领域 `roll_intervention` 新增 `cancel_advantage_disadvantage` 操作与 `roll_modes` eligibility；当前只有纯解析器测试，未计为新的 full，直到接入真实生产特性。
- 验证：`backend/.venv/bin/pytest -q backend/tests` 通过；`ruff check backend/src backend/tests`、`python -m compileall -q backend/src`、`git diff --check` 通过。保留未跟踪 `backend/tests/integrations/` 与 `backend/tests/ollama.py`，未暂存。

# 2026-08-08 长执行检查点：狂怒首击附伤

- 代码提交：`cb05706 feat: automate frenzy first-hit damage rider`；文档/交接需单独提交。
- 审计固定总数 499，当前 `full 227 / partial 195 / dm_only 77`。从本长执行起点 `201/221/77` 算，上一批已净增 25；下一批新增“狂怒”1 条，不能把它称为 +25 批次。
- “狂怒”完整接入既有攻击后骑手消费者：仅在 `raging + reckless_attack + strength weapon/unarmed attack` 时可用，每回合首个符合条件命中触发；骰数从权威 `rage:bonus_damage` 成长值绑定为 d6 数量，玩家提交附伤总值，伤害类型沿用基础武器伤害，重复回合使用由现有幂等集合阻止。
- 运行时配置不识别狂战士特性名；执行器只识别 `dice_count_source=rage_damage`、条件谓词和 rider 字段。配置、运行时合同和 direct rider tests 已通过。
- 下一批仍在审计的候选：战斗激励（AC 反应 + 命中附伤双分支）、暗杀（先攻/首轮优势/偷袭附伤）、自然守御（地形选择+中毒免疫+抗性）、预兆/高等预兆（长休生成并消费 d20 池）、暗影步（光照证明+传送+下一次近战优势）、迅捷灵光（动态范围/首次进入触发）。任一缺分支、资源、目标或权威输入都保持 partial。
- 全量 `backend/.venv/bin/pytest -q backend/tests`、Ruff、compileall、`git diff --check` 已通过。未跟踪 `backend/tests/integrations/` 与 `backend/tests/ollama.py` 保留且未暂存。

# 2026-08-08 长执行：多积木攻击后触发与子职业额外攻击

- 当前工作树切片已完成，尚未提交；代码与交接文档仍需分开提交。
- 新增通用 `after_attack` 触发事件合同：结构化 `when.hit` / `when.critical_hit` 条件，复用既有 `grant_movement_budget` 与 `grant_disengage` 执行器。执行器只读取事件上下文和效果字段，不识别运动健将或其他特性 ID；未知条件、缺条件和错误类型 fail-closed。
- `_feature_rule_modifiers()` 支持按 `skill` 过滤被动修正；攻击确认在权威命中后执行攻击后触发，普通命中不会误触发，暴击命中才执行。触发器改变移动额度或状态时递增角色版本；已确认的相同幂等键在事务入口直接返回，不会重复写入。
- 真实生产配置使用者：勇士「运动健将」同时配置先攻优势、运动技能优势、暴击后半速移动和本回合撤离；勇气学院「额外攻击」配置 `attack_action_count=2`，复用核心职业额外攻击的攻击次数消费者。配置层只负责映射来源字段，执行器没有子职业 ID 分支。
- 真实 API 回归覆盖：运动健将普通命中不触发、暴击命中同时写入 15 尺移动额度和撤离状态、重放不重复叠加；升级运行时回归覆盖两个配置都产出 full registry。
- 固定分母 499 的审计从 `full 163 / partial 244 / dm_only 92` 变为 `full 166 / partial 241 / dm_only 92`，真实净增 `full +3`。积木覆盖仍是重叠候选统计，不能将候选数当成完整自动化数。
- 真正通用积木：`after_attack` 条件触发器、移动额度/撤离生命周期、已有攻击次数和攻击阈值消费者的组合接线。特性配置：运动健将、高效重击、勇气学院额外攻击。真实改变状态：攻击结果、角色移动预算、撤离效果、角色版本和幂等动作审计。仍需玩家/DM 输入：攻击天然 d20/命中结果和普通攻击伤害仍由攻击请求提交；系统不替玩家掷骰。仍未自动化：其他命中后骑手的资源/豁免/分支效果、光环范围几何、武器精通词条和复杂子职业规则。
- 验证通过：定向相关测试、全量 `backend/.venv/bin/pytest -q backend/tests`、Ruff、compileall、`git diff --check`；只有既有 Starlette/httpx 弃用警告。无前端源码变更、未做浏览器验收。用户未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 保持未加入提交。

# 2026-08-07 资源生命周期第三批：通用治疗骰池

- 代码提交：`dc86312 feat: add reusable healing dice pool actions`；本轮无前端源码变更。
- 新增真正通用的治疗骰池动作合同：`resource_cost_mode=dice_count`、`healing_dice.die_size`、固定或属性调整值驱动的 `max_dice`、结构化目标范围、长休 `set_to_max` 生命周期。执行器只读取这些字段，不识别神之勇者、治疗之光或治愈之光特性 ID。
- 资源编译器识别来源中明确的固定骰池（4枚 d12）和等级成长骰池（1+职业等级枚 d6），生成可持久化资源最大值/当前值/骰面；源码译名“治愈之光”与用户常用“治疗之光”共用同一配置合同，别名只存在配置编译层。
- 真实生产配置使用者：野蛮人狂热者道途「神之勇者」（自身，4d12池，每次最多4枚）与魔契师天界宗主「治愈之光/治疗之光」（同阵营60尺目标，d6池，每次最多魅力调整值枚）。
- 真实状态行为：玩家/DM 提交骰子数量与治疗总值；服务端校验数量上限、聚合治疗总值范围、资源余额、目标阵营/距离，事务内扣除资源并写入 HP，幂等重放不重复消费；缺输入/越界/资源不足 fail-closed。系统不接收或验证每枚骰子的逐颗结果。
- 固定分母 499 的审计从 `full 159 / partial 248 / dm_only 92` 变为 `full 161 / partial 246 / dm_only 92`，本批真实净增 `full +2`，距离 `full≥223` 还差 62。资源候选覆盖 195 仍是重叠候选统计，不能当成完成数。
- 真正通用积木：治疗骰池资源消耗/上限/治疗总值/目标范围/长休恢复执行器。特性配置：两个生产配置及其资源池表达式。真实改变状态：资源 `current`、目标 HP、动作经济、幂等动作审计。仍需玩家/DM 输入：实际骰子结果；系统不替玩家掷骰。仍未自动化：其他治疗池、复杂多分支治疗、未结构化目标几何和其余子职业效果。
- 验证：定向治疗骰池/升级测试通过；全量 `backend/.venv/bin/pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过（仅既有 Starlette/httpx 弃用警告）。用户未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 未纳入提交。

# 2026-08-07 资源生命周期第二批：表达式治疗与天然 d20 暴击阈值

- 代码提交：`7c2751d feat: migrate reusable subclass healing and critical blocks`；本轮无前端源码变更。
- 通用执行器扩展：`CombatFeatureActionCommand` 接受权威 `attack_d20`；攻击结算只读取通用 `attack_critical_threshold` 修正并生成 `automatic_critical:feature_threshold`，缺天然 d20 时 fail-closed。执行器不识别勇士或“精通重击”特性 ID。
- 通用治疗扩展：职业动作治疗表达式按配置解析 `1dN`、动态骰面（如 `martial_arts_die`）和六项属性调整值，未知表达式继续要求 DM 输入；范围校验仍在真实 `combat_feature_action` 确认事务内执行。
- 真实迁移的生产配置：散打武者「混元体」使用附赠动作、感知调整值次数资源、武艺骰+感知调整值治疗、长休 `set_to_max` 恢复；勇士「精通重击」使用 19 暴击阈值并要求玩家/DM 提交天然 d20。资源 key 和生命周期 key 在配置编译层绑定，执行器不依赖特性 ID。
- 真实状态行为：混元体确认时消费角色资源 CAS、校验治疗总值、写入 HP、记录幂等动作；精通重击在权威攻击路径把天然 19/20 记为暴击，后续伤害和 0 HP 逻辑沿用既有结算链。两者均有定向运行时测试；不是只改审计字段。
- 固定分母 499 的审计从 `full 157 / partial 250 / dm_only 92` 变为 `full 159 / partial 248 / dm_only 92`，真实净增 `full +2`，距离 `full≥223` 还差 64。资源候选覆盖 195 仍是重叠候选数，不能把它当成完成数。
- 仍需玩家/DM 输入：混元体的实际治疗骰总值、攻击的天然 d20（系统不替玩家掷骰）；精通重击只有在角色快照存在该配置时生效。
- 仍未自动化：星辰形态激活状态尚未建立，因此“灿若繁星”没有被误报为 full；神之勇者/治疗之光多骰池、吟游诗人激励可听性和失败消费、复杂攻击骑手以及其他资源型子职仍需后续完整消费者。
- 门禁：定向相关测试、全量 `backend/.venv/bin/pytest -q backend/tests`、Ruff、compileall、`git diff --check` 全部通过（仅既有 Starlette/httpx 弃用警告）。用户未跟踪的 `backend/tests/integrations/` 与 `backend/tests/ollama.py` 未纳入提交。

# 2026-08-07 资源生命周期积木第一批真实接线

- 代码提交：`ea09d4c feat: add reusable resource lifecycle blocks`；无前端源码变更。
- 新增通用 `resource_lifecycle` 合同与解析器：只读取资源 key、短休/长休/先攻/回合事件、restore/set_to/set_to_max/set_to_minimum 和显式条件；休息服务与先攻开始恢复共用同一解析器，未知事件 fail-closed。执行器不识别职业或特性 ID。
- 新增通用动态骰面绑定：掷骰干预可从资源 `value`（如 D6/D8/D12）绑定骰面，不把固定骰面写死在执行器；仍由玩家/DM 提交实际骰值，服务端负责范围校验、资源 CAS 和幂等。
- 两个生产配置使用者迁入现有持久化 `after_failed_d20_test` 窗口：邪魔宗主“黑暗强运”（魅力调整值次数，长休全恢复，d10 加骰）与逸闻学院“超凡技艺”（消费吟游诗人激励骰，按权威骰面加骰，短休/长休恢复）。配置使用 `$feature_resource` 绑定适配只发生在配置编译层；通用掷骰执行器不识别这些 ID。
- 真实状态行为：失败属性/技能检定或豁免后持久化干预窗口；玩家/DM 提交骰值；确认时按现有事务扣除资源并记录结果；相同操作幂等重放不重复消费。缺资源、缺骰值或不满足资格时 fail-closed。
- 固定分母 499 的审计从 `full 155 / partial 252 / dm_only 92` 变为 `full 157 / partial 250 / dm_only 92`，真实净增 `full +2`，不是候选覆盖数。距离 `full≥223` 还差 66。
- 定向资源/休息/掷骰/运行时回归通过；全量 `backend/.venv/bin/pytest -q backend/tests`、Ruff、compileall、`git diff --check` 通过（仅既有 Starlette/httpx 弃用警告）。
- 仍需玩家/DM 输入：所有实际骰值；超凡技艺的具体失败检定由玩家选择是否发动；缺少权威角色资源或骰面时系统拒绝。仍未自动化：其余资源型子职的复杂目标、状态、传送、反应和多分支效果；资源字段本身不能替代完整特性效果。
- 用户未跟踪 `backend/tests/integrations/`、`backend/tests/ollama.py` 保持未暂存、未纳入提交。

# 2026-08-07 高扇出施法能力与子职业固定法术表批量自动化

- 代码提交：`816ca46 feat: automate reusable spell capability and subclass spell lists`；本轮没有前端源码变更。
- 后续代码提交：`381bf30 feat: cover structured subclass spell tables`；把“始终准备着表中对应的法术”这一同构表述纳入同一执行器，新增 7 条固定子职业法术表 full；混合动作/资源效果没有因出现“始终准备”文字而被误报。
- 新增通用 `spellcasting_capability` 积木：只声明施法能力来源、现有 `spell_economy_service` 消费者和法术位/选择边界，不按职业特性 ID 写专用分支。核心职业 7 条“施法”记录进入真实运行时 contract/full；“兽形施法”仍未误报为完整施法能力。
- 新增通用 `always_prepared_spell_list` 积木：只接受来源明确写出“始终/总是准备着特定法术”且不是“你选择的法术”的固定表；升级服务按权威本地法术目录匹配名称，自动写入 `spells[*]` 的 `prepared=true`、`always_prepared=true`，现有施法服务直接消费。固定誓言/领域/宗主法术表共新增 12 条 full。
- 选择绑定的“魔法探秘”等仍保持 DM-only/partial；未匹配权威法术目录时不会猜测或写入。测试覆盖通用配置复用、选择绑定排除、真实升级 preview 持久化和现有施法能力消费者。
- 固定分母 499 的审计从 `full 129 / partial 271 / dm_only 99` 变为 `full 155 / partial 252 / dm_only 92`，真实净增 `full +26`，距离用户目标 `full≥223` 仍差 68。候选积木命中数仍是重叠统计，不能把理论命中直接当 full。
- 定向验证：施法运行时、升级选择、子职业运行时、499 条审计和升级 API 回归全部通过；全量后端 `pytest -q backend/tests` 通过（仅既有 Starlette/httpx 弃用警告）；Ruff、compileall、`git diff --check` 通过。
- 用户未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 保持未暂存、未纳入提交。

# 2026-08-07 三组通用积木批量迁移（最新）

# 2026-08-07 后续长执行：配置触发与子职业防御批量切片

- 代码切片提交：`06be10e`、`bc0029a`、`abf60ec`、`178eeb6`、`d70057b`、`d79c641`、`74dbb4d`；测试基线提交 `8dc1f3c`。没有修改前端。
- 新增真正通用的 `after_feature_action` 触发执行器：按 `event/action_id/effects` 配置执行半速移动、撤离和条件移除；不识别战术转进、莽驰或无我狂暴 ID。真实回归覆盖回气后触发、狂暴后触发、资源/状态写入和幂等重放。
- 范围防御执行器新增 `damage_resistance` 的 ranged passive 消费；法术抗性新增魔法豁免优势与魔法伤害抗性两个配置字段，并接入普通伤害、区域伤害和持续伤害的权威防御链。
- 新增完整子职业配置使用者：守御灵光、奉献灵光、无我狂暴、法术抗性。仅有单一子效果而仍缺整条规则的意念守护、思维之盾、光耀之魂没有计入 full，已明确保持 DM/partial。
- 固定分母 499 的当前审计：`full 129 / partial 271 / dm_only 99`；核心职业 `124 / 35 / 99`，子职业 `5 / 236 / 0`。相对冻结基线 `123 / 275 / 101`，本轮真实净增 `full +6`，距离用户要求的 `full≥223` 仍差 94，不能宣称目标完成。
- 门禁：全量 `backend/.venv/bin/pytest -q backend/tests`、Ruff、compileall、`git diff --check` 均通过。审计报告已更新；代码与交接文档分开提交。`backend/tests/integrations/` 与 `backend/tests/ollama.py` 仍为用户未跟踪文件，未加入提交。

- 代码提交 `b7da7dc`：执行三组积木的真实批量迁移，不再只停留在字段门禁。灵巧动作的三个分支改为 `allowed_actions`/`adjudicated_actions`/`input_requirements` 配置；通用动作执行器仍负责动作经济、躲藏 DM 输入后的真实隐匿状态和幂等。
- `学者`加入通用升级选择/专精配置，复用 `expertise` 执行器；选择后由升级事务真实写入技能专精。
- `永恒追猎`接入通用专注防御语义：防御配置声明受保护的专注效果名称，伤害结算在命中结构化猎人印记时不创建专注豁免窗口。执行器只读取配置字段，不识别特性 ID。
- 子职业 `战争化身`接入通用 `damage_resistance` 防御积木；钝击、穿刺、挥砍抗性写入编译运行时并由伤害防御消费者实际减半。审计脚本现在只对这条有真实注册表和消费者的子职业记录 `full`。
- 自动化数量（固定分母 499）：`full 119→123`、`partial 278→275`、`dm_only 102→101`，净增 `full +4`；核心职业分母 258 为 `122 / 35 / 101`，子职业为 `1 full / 240 partial`。这四条是本轮真实状态效果，不把候选覆盖 322 条或字段校验数当成完成数。
- 仍需玩家/DM 输入：灵巧动作躲藏成功/失败裁定、所有实际骰值、其他带选择的职业/子职业分支和缺权威位置时的范围裁定。仍未自动化：其余 240 条子职业特性、吟游诗人激励可听性/失败消费完整窗口、引导神力/荒野变形/武器精通词条攻击结算，以及复杂 post-hit 多分支。
- 验证：本轮定向回归、全量后端 pytest、Ruff、compileall、`git diff --check` 必须在提交前完成；代码与本交接文档分开提交。用户未跟踪的 `backend/tests/integrations/` 和 `backend/tests/ollama.py` 保持未暂存。本轮没有前端源码变更。

# 2026-08-07 post-hit / pre-damage 通用执行器生产闭环

# 2026-08-07 1/2/3 通用触发、资源、目标豁免积木第一切片

- 代码提交 `043c033`：新增 `domain/feature_blocks.py`，提供不识别职业/特性 ID 的动作触发、资源绑定/恢复、目标/豁免/状态结构校验；`confirm_feature_action()` 与运行时合同门禁共用该合同。它只验证配置形状，真实动作经济、资源写入、CombatEffect 生命周期和幂等仍由现有 CombatEngineService 负责。
- 失败豁免反应窗口改为遍历任意带 `after_failed_saving_throw`、触发条件交集、`range_ft` 和 reaction action 的配置；候选反应者选择、反应消费和第二骰结算沿用现有持久化链。旧无 trigger 的 `countercharm` 快照只走明确兼容适配器，适配器不是积木。
- 生产配置使用者：反迷惑（现为配置驱动的 `saving_throw_reaction_window`）和致命猎杀的权威猎人印记目标优势；圣疗补充结构化 `target_policy`；先发激励的先攻恢复事件通过通用恢复校验。没有新增第二套战斗引擎。
- 自动化数量（固定分母 499）：`full 117→119`、`partial 280→278`、`dm_only 102`；核心职业分母 258 为 `119 / 37 / 102`。净增 2 条真实 full，不能把候选覆盖 322 条或字段校验数冒充完成数。
- 仍需玩家/DM 输入：反应者选择（多候选时）、实际重骰总值、目标位置缺失时的 DM 明确裁定以及所有未结构化分支；系统不替玩家掷骰。仍未自动化：子职业 241 条的大量具体效果、吟游诗人激励的可听性/失败消费完整窗口、荒野变形/引导神力/传奇恩惠具体分支、武器精通词条攻击结算。
- 验证：通用积木、职业运行时、战斗生命周期、反应窗口、进度统计和 499 条审计定向回归通过；全量后端 `pytest -q backend/tests`、本轮改动范围 Ruff、compileall、`git diff --check` 均通过。全仓库旧 scripts 仍有与本轮无关的模块命名/权限诊断，不影响本轮文件门禁。代码与本交接文档分开提交。

- 代码提交 `97f7432`：将命中后后续链接入真实玩家攻击 API：权威命中 → `_eligible_attack_riders()` → 持久化 `PlayerActionRequest` → 玩家/DM 输入 → 目标豁免 → 请求版本 CAS → 角色资源 CAS → condition/modifier 效果提交 → 一次性效果消费与幂等重放。公共 generic action request 拒绝保留的 `post_hit_rider` 类型和 `post-hit:` 幂等键；内部请求带 `created_by=combat_engine`，解析器校验来源、配置 ID、战斗/角色/目标边界。
- 真正通用积木：`attack_rider` 的可选发动、持久化 pending activation/choice/save、通用 DC/输入/资源提交、生命周期（来源/目标回合边界、下一次攻击/豁免）和 condition/modifier 真实写入；`pre_damage_intervention` 的标签触发、表达式绑定（如 `class_level*5`）和通用伤害变换。执行器不识别 `stunning_strike`、`slow_fall` 等特性 ID；权威攻击标签随请求保存，不能由客户端 `special_inputs` 伪造扩张。
- 生产配置使用者：震慑拳（每回合一次、功力、体质豁免、DC 8+PB+WIS、失败震慑/成功减速+下一次攻击优势）与轻身坠（坠落伤害前、武僧等级×5 减伤）。额外测试 fixture 使用不同 ID、不同豁免和中毒效果，和生产配置共用同一持久化/效果执行器；fixture 不是生产特性。
- 真实状态行为：震慑拳会原子扣功力、写入速度减半/震慑/一次性攻击优势并在消费后结束；轻身坠真实把 40 点坠落伤害变为 15 点并消耗反应。请求跨当前回合、目标/战斗失效或资源不足时 fail-closed；有待处理 post-hit 窗口时不推进 `end_turn_after`，避免延迟结算错误计算生命周期。
- 自动化数量（固定分母 258）：`full 112→117`、`partial 42→39`、`dm_only 104→102`，完整自动化率 `43.4%→45.3%`，净增 5。新增 full 为震慑拳、轻身坠；直觉闪避、拨挡攻击、拨挡能量是已有真实反应链的账面纠正（`partial→full`），不重复称为新积木。只有配置驱动、真实消费者、状态/资源写入、输入链、持久化和幂等同时成立才计 full。
- 仍需玩家/DM 输入：是否发动、选择分支、目标豁免总值以及任何实际骰值；系统不替玩家掷骰。仍未自动化：带伤害骰的 post-hit rider 持久化伤害提交（当前 fail-closed）、凶蛮打击/诡诈打击完整多选和移动、受祝击/元素之怒升级分支、未结构化的职业/子职业规则。不能把领域解析器、旧专用适配器、测试 fixture 或“字段已支持但无真实消费者”误报为通用积木/full。
- 验证：相关 attack rider、feature runtime、progression、combat engine、player-room API 定向回归通过；后端全量 `pytest -q backend/tests`、Ruff、compileall、`git diff --check` 全部通过；仅有既有 Starlette/httpx 弃用警告。代码与本交接文档分开提交；用户未跟踪的 `backend/tests/integrations/` 与 `backend/tests/ollama.py` 保持未暂存。本轮无前端源码变更，未做也未声称浏览器验收。

# 2026-08-07 通用掷骰干预与首份 post-hit rider 生产接线

- 代码提交 `9e3dcd6`。`PlayerRollResolutionCommand` 新增通用 `roll_intervention_id/inputs`；失败 D20 检定会从角色冻结的 `feature_runtime.actions` 中按触发和结构化资格筛选配置，持久化进入 `awaiting_roll_intervention`，第二次确认调用 ID 无关的 `apply_roll_intervention()`，并在同一确认事务中按返回的资源提交计划扣除角色资源、同步战斗快照。动作已确认后重放直接返回原结果，不会再次消费。
- 战术思维是第一份生产配置：仅适用于失败属性检定，要求权威 `second_wind` 资源，玩家输入 1d10；补救成功才消耗一次回气，仍失败则资源保持不变。真实 API 回归覆盖开窗、12+4 对 DC15 成功、资源 2→1 和幂等重放；执行器不识别 `tactical_mind` ID。
- 屠灭众敌迁移为第一份生产 `post_hit_rider` 配置：`after_hit`、敌对目标、攻击标签、`actor_state_target_id_keys`、1d10 力场伤害输入全部由配置声明；玩家攻击消费者调用通用 `resolve_post_hit_rider()`，只有权威 `current_hunters_mark_target_id` 与当前目标一致时校验骰值并加入真实伤害。旧 `attack_rider_totals` 只由输入兼容适配器翻译到新 input key；适配器不是积木。
- 自动化数量：上一提交为 `full 110 / partial 43 / dm_only 105`；现在为 `full 112 / partial 42 / dm_only 104`（总数 258）。净增 `full +2`：战术思维 `dm_only→full`，屠灭众敌 `partial→full`；完整自动化率 `42.6%→43.4%`。已有 full 的不屈/可靠才能/幸运一击等不会因通用积木存在而重复计数。
- 玩家仍必须输入实际 d10；系统不替玩家掷骰。仍未自动化：震慑拳成功/失败两分支、凶蛮打击的放弃优势和移动/持续效果、诡诈打击的偷袭骰牺牲与多选项、受祝击/元素之怒的升级分支，以及通用 post-hit rider 的持久化目标豁免 prompt/资源/状态写入链。仅有领域执行器或测试配置的条目继续保持 partial/dm_only。
- 验证：相关职业/战斗整文件回归通过；后端全量 `pytest -q backend/tests`、Ruff、compileall、`git diff --check` 通过；仅有既有 Starlette/httpx 弃用警告。本轮无前端源码变化，未做也未声称浏览器验收。用户未跟踪的 `backend/tests/integrations/` 与 `backend/tests/ollama.py` 仍保持未暂存。

# 2026-08-07 掷骰干预、命中后骑手与范围被动通用积木

- 代码提交 `46d439c`。新增两个不识别职业或特性 ID 的领域执行器：`roll_intervention.py` 只按触发、资格、操作、输入、资源策略和幂等字段执行重掷、加值/加骰、优势/劣势、最低值、替换 d20 与失败补救；`attack_rider.py` 只按 `after_hit`、实体/阵营/状态/动作标签/等级资格、频率、资源、附伤、目标豁免和成功/失败效果执行，并可生成 condition/move/modifier 兼容 RuleBlock。
- 两个新领域执行器都用至少两份无生产特性 ID 的测试配置证明复用。它们不会替玩家掷骰，也不会自行写数据库：返回的是已验证的结算结果、pending choice/save、资源提交计划和幂等键。持久化服务尚未接入这两个新执行器；现有不屈、幸运一击、吟游诗人激励、可靠才能和旧 bonus-damage 骑手仍走原有专用/兼容路径。因此本轮不能把这些真实旧效果误报成“已迁移到通用积木”，也不能据此提高职业自动化计数。
- 范围被动已真实接入生产战斗链：`ranged_passive` 通用解析器按目标关系、阵营、权威网格位置、距离、来源禁用状态、`range_group`、`stacking_group` 和 effect kind 动态解析；守护灵光豁免加值和勇气灵光状态免疫共用该执行器。PlayerRoom 自动豁免与 CombatEngine 玩家/DM 豁免均消费同一数值解析器，多个同组来源取最高、不同组可叠加，缺地图/位置对非自身目标 fail-closed。
- 生产配置分层：守护灵光和勇气灵光只是 `ranged_passive` 配置使用者；灵光增效只是定向 `range_group` 的 30 尺 override 配置。执行器不识别这三个特性 ID。旧快照的 `scope/applies_when` 字段组合由明确标注的兼容适配器翻译为新合同；该适配器不是积木。
- 真实状态行为：来源失能时范围被动失效；勇气灵光会在权威结算视图中暂时抑制已存储的恐慌状态，但不删除该状态，离开范围后可恢复；灵光增效真实同时扩大守护和勇气两项共享范围组，不扩大无关范围效果。
- 精确核心职业分母仍为 258。此前 `full 109 / partial 43 / dm_only 106`；本轮只有原 `dm_only` 的灵光增效具备新生产配置和真实消费者，现为 `full 110 / partial 43 / dm_only 105`，完整自动化率 `42.2% -> 42.6%`。守护灵光、勇气灵光原已计 full，通用化迁移不能重复计数；掷骰/骑手纯执行器尚无生产持久化接线，净增必须记为 0。
- 仍需玩家/DM 输入所有真实骰值，以及需要选择的骑手/失败补救分支。仍未自动化：通用掷骰干预的 API/prompt/资源确认接线；通用命中后骑手的持久化 save prompt、资源原子消费和状态/移动写入接线；震慑拳、诡诈/凶蛮打击等生产配置迁移。不能把测试 fixture、旧专用 helper、兼容 RuleBlock 适配器或仅能纯函数解析的配置称为生产效果已 full。
- 验证：新积木定向测试 7 项、相关职业/战斗/统计测试 86 项通过；后端全量 `pytest -q backend/tests`、全量 Ruff、compileall、`git diff --check` 通过；新领域模块严格 mypy 通过。用户未跟踪的 `backend/tests/integrations/` 与 `backend/tests/ollama.py` 保持未暂存。本轮无前端源码变更，未做也未声称浏览器验收。

# 2026-08-07 升级选择、专精与被动授予批量积木

- 代码提交 `9015129`：建立三件套。`progression_automation.py` 提供特性分类器、配置迁移表和机器可验收矩阵；目标五类共 `76` 个职业表命名条目，结构化需求共 `92` 个实际选择槽位：属性值提升51、传奇恩惠12、战斗风格3、武器精通16、专精10。
- 真正通用积木是 `assign_progression_choices()` + `apply_progression_choice_grants()`：它们只识别 requirement/operation 类型与字段，不识别战士、游侠、专精等职业/特性 ID。新 API 使用 `feature_choices_by_key`，能在战士1级正确分开 `fighting_style:1` 与 `weapon_mastery:3`；旧 `feature_choices` 只作为明确标注的顺序兼容适配器，不得称为积木。
- 真实角色状态写入已打通：属性提升原子写 `ability_scores`；专精先验证已熟练技能，再写 `skills[skill].expertise=true`；武器精通写入结构化 `proficiencies` 记录；战斗风格和其他选择写入带 grant/effect 分层状态的 `advancement_choice_grant`。preview、批量 preview、confirm、CAS 和幂等链均传递 `skills/proficiencies`。
- 真实消费证据：专精确认后，玩家技能检定消费者按双倍熟练计算；“防御”战斗风格授予会进入既有战斗 registry，穿甲时提供 AC +1；武器精通授予会被熟练/前置系统读取，但精通词条本身尚未进入攻击结算。
- 覆盖率从原始 `full 53 / partial 23 / dm_only 182` 提升为 `full 109 / partial 43 / dm_only 106`（总数仍为258）。`full` 增加56，即属性值提升51个+专精5个；完整自动化率从 `20.5%` 升至 `42.2%`。传奇恩惠12、战斗风格3、武器精通5只从 `dm_only` 升为 `partial`，没有被虚报为 full。
- 分层口径：属性提升的选择/授予效果已 full；如选专长，该专长的具体效果是独立 contract，不随属性提升伪装成已自动化。传奇恩惠只完成目录/前置/授予，具体恩惠效果仍 DM-only。战斗风格只有已结构化的选项（当前明确包括防御）有真实消费者，整类仍 partial。武器精通授予层 full，攻击词条效果 dm_only，整类 partial。不能把这些兼容适配器或单独真实效果称为通用积木。
- 玩家/DM 仍需输入具体选项；未结构化的选项前置可由 DM override，并留下警告。仍未自动化：传奇恩惠逐项效果、防御之外的全部战斗风格效果、武器精通词条攻击结算、未入本地目录的选项合法性。
- 验收：新增分类/迁移/矩阵回归固定 `76` 条、`92` 选择槽位和 `109/43/106`统计；真实 API 回归覆盖属性、武器精通、专精持久化及技能消费；后端全量 `pytest -q backend/tests`、Ruff、compileall、`git diff --check` 全部通过。本轮无前端源码变更，未做也未声称浏览器验收。

# 2026-08-07 通用 zero_hp_intervention 积木与坚韧狂暴迁移

- 代码提交 `89fcb2a`：新增真正通用的 `zero_hp_intervention` 执行器。执行器只消费结构化字段：`would_drop_to_zero_hit_points` 触发、实体类型/阵营/状态/资源/职业等级资格、豁免属性与递增 DC、受限生命恢复表达式、失败后继续 0 HP 生命周期、`outright_death` 例外、独立状态键以及短休/长休重置；战斗执行器不识别 `relentless_rage` 特性 ID。
- 坚韧狂暴现在只是第一份生产配置使用者：要求角色处于狂暴、绑定权威野蛮人等级、体质豁免 DC 10 且成功后 +5、成功恢复 `2*barbarian_level`、失败继续濒死、短休或长休重置。显示名、旧响应键 `relentless_rage`、旧 prompt ID 字段和旧状态键都由配置提供，不是通用执行器分支。
- 旧活动战斗快照通过独立的 `adapt_legacy_zero_hp_intervention()` 兼容适配器转换旧 `zero_hit_points_save` 形状；极旧、没有冻结特性配置但仍有 `relentless_rage_state` 的快照只在休息服务保留一条明确标注的状态重置适配器。这两项属于兼容层，不能称为通用积木。
- 第二份仅用于测试的假配置 `fixture:last_stand_save` 使用完全不同的特性 ID、感知豁免、DC 12→14、固定恢复 3 HP、独立状态键，并同时校验阵营、状态、实体类型和资源；真实 API 回归证明同一执行器可开窗、确认、恢复、递增状态并幂等重放。没有伪造新的生产规则特性。
- 坚韧狂暴效果仍真实可运行：普通伤害、区域伤害逐目标和持续伤害 tick 共用现有战斗链；直接死亡不开放窗口；成功恢复生命并移除昏迷，失败保持 0 HP 且不额外增加死亡豁免失败；短休/长休按配置重置活动战斗快照 DC。
- 仍需玩家或 DM 输入实际豁免总值；系统不会替玩家掷这枚 d20。仍未自动化的是不存在结构化 `zero_hp_intervention` 配置、资格事实缺失或规则文本无法落入白名单字段的 0 HP 特性；这些情况继续 fail-closed/交给 DM，不能按名称猜测。
- 验证：通用/坚韧狂暴/直接死亡/休息/兼容适配器定向回归通过；相关战斗生命周期、区域伤害、持续效果、召唤和职业运行时整文件回归通过；后端全量 `pytest -q backend/tests`、Ruff、compileall、`git diff --check` 全部通过。仅有既有 Starlette/httpx 弃用警告。本轮没有前端源码变化，未做也未声称浏览器验收。

# 2026-08-06 坚韧狂暴 0 HP 体质豁免真实执行

- 历史实现提交 `c03f8c9`：当时完成的是“坚韧狂暴这一特性的专用可运行效果”，不是通用积木；专用 helper 和特性 ID 分支已由上方 `89fcb2a` 重构移除。它接入普通伤害、怪物区域伤害逐目标结算和持续伤害 tick 的统一 0 HP 处理链。目标必须是权威角色、快照含结构化配置、当前处于 `raging`、野蛮人等级可从角色/运行时等级读取，且剩余伤害未达到最大生命值；缺任何条件都 fail-closed。
- 触发后真实创建持久化 `player_roll_prompt`，DM/玩家共用既有骰点面板输入体质豁免总值；不是文字提示。成功真实恢复 `2 × 野蛮人等级`（不超过最大生命值）、移除昏迷、清空死亡豁免轨迹，并写入 `relentless_rage_state.current_dc`；下一次成功 DC 增加 5。失败保持 0 HP，不额外增加死亡豁免失败。
- 直接死亡规则真实优先：剩余伤害达到最大生命值时不创建豁免窗口，继续走立即死亡/3 次死亡豁免失败。坚韧狂暴与不屈耐力同时存在时不静默叠加，先打开玩家选择的坚韧狂暴豁免，不自动消费另一项 0 HP 防御资源。
- 短休和长休确认会同步重置仍在活动战斗快照中的 `relentless_rage_state.current_dc` 为 10，并把重置的战斗单位写入休息结果；不会只修改文字字段或角色资源。
- 新增真实 API 回归：成功恢复与 DC 递增；第二次失败保持濒死且死亡豁免不增加；直接死亡不弹窗；短休重置活动战斗快照。运行时合同断言同步为 `full`。
- 验证：定向坚韧狂暴/不屈耐力/休息/运行时测试通过；后端全量 `pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过。前端源码本轮未改动，因此没有把前端构建或浏览器截图冒充本轮验证。
- 历史完成度口径纠正：坚韧狂暴的真实效果在该提交中可运行，但当时“通用 0 HP 干预积木”尚未完成；不能把专用适配器或单个效果可运行误报成通用积木。通用积木完成状态以上方 `89fcb2a` 为准。

# 2026-08-06 猎人印记结构化目标绑定消费

- 代码提交 `e03bcb6`：攻击优势和猎人印记附伤积木现在识别权威快照字段 `current_hunters_mark_target_id`；只有它与本次攻击目标 ID 完全一致时才自动通过 `target_is_current_hunters_mark` 条件。未绑定或攻击其他目标时不授予优势，也不自动激活附伤；旧的显式 eligibility 输入仍兼容，供 DM 明确裁定。
- 规则积木筛选器已把该目标谓词纳入允许集合，DM/玩家攻击路径共用同一目标绑定判断；附伤骰总值仍必须由玩家/DM 提交，未把骰点输入边界伪装成全自动。
- 新增回归：标记目标获得“致命猎杀”优势，非标记目标不获得；绑定目标的屠灭众敌附伤无需额外 eligibility 标记且仍校验伤害骰。
- 验证：职业运行时/战斗定向回归通过；后端全量 `pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 当前切片完成度：猎人印记目标条件消费 `100%`；猎人印记专注中断、目标绑定的来源创建/转移和附伤骰输入仍保持既有边界。这是固定大项“职业/子职业 1–20 级运行时闭环”的通用消费，不新增第五类缺口；高级三维战斗仍跳过。

# 2026-08-06 职业骰目标唯一持有门禁

- 代码提交 `6bcc772`：统一 `grant_roll_die` 职业积木现在读取并写回被授予目标的权威 `snapshot_json`，不再错误地把职业骰写到授予者身上。
- 同一目标已经持有 `available=true` 的同类职业骰时，确认接口返回 400，且事务回滚：授予者的附赠动作、职业资源和双方版本/快照都不改变。目标已有 `available=false` 的旧骰时允许重新授予，并真实写回新骰面与来源。
- 新增真实 API 回归：重复可用激励骰被拒绝且资源 2→2、附赠动作仍可用；已消费 D8 目标重新获得 D8，授予者资源 2→1、附赠动作消耗一次。同步修正旧回归中把骰错误断言在授予者上的基线。
- 验证：定向职业动作/运行时测试通过；后端全量 `pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 当前切片完成度：职业骰“一名目标只能持有一枚可用同类骰”及正确目标绑定 `100%`。这是固定大项“职业/子职业 1–20 级运行时闭环”的通用积木消费，不新增第五类缺口；高级三维战斗仍跳过，原有火球术、雷鸣波、复杂多段伤害和基础战斗链不重复实现。

# 2026-08-06 玩家角色借机攻击开窗通用化

- 代码提交 `8f55041`：进入/离开近战威胁范围的结构化反应窗口不再只检查怪物；玩家角色、召唤物和怪物都可作为响应者，只要敌我阵营不同、权威网格距离跨过明确 reach、仍有反应且未被失能类状态阻断。
- 玩家角色从怪物旁离开时，现在会进入既有玩家反应请求；玩家选择接受后复用原有一次攻击积木，真实扣 HP、消耗反应并写入公开日志。撤离状态等已有免借机规则仍由原有移动门禁处理。
- 新增真实玩家房间 API 回归：怪物移动离开玩家近战范围 → 玩家端收到请求 → 接受 → 一次借机攻击结算，HP 下降且反应变为已用；原有怪物响应和进入范围回归也通过。
- 验证：后端全量 pytest、移动/反应定向回归、Ruff、compileall、`git diff --check` 全部通过；仅有既有 Starlette/httpx 弃用警告。
- 当前切片完成度：玩家角色进入/离开范围反应开窗和借机攻击执行 `100%`。这是既有“反应动作触发矩阵”的通用消费切片，不新增缺口；复杂三维遮挡、非结构化反应和反应效果本身的 DM/玩家选择边界仍保持，高级三维战斗仍跳过。

# 2026-08-06 角色结构化施法反应窗口通用化

- 代码提交 `e19c916`：施法（`casts_spell`）反应窗口不再只遍历怪物；角色的结构化反制法术/施法反应也会在明确法术动作开始时进入同一持久化窗口。响应者仍必须在场、存活、有反应且未被失能类状态阻断。
- 继续复用既有 `reaction_event` 白名单、窗口幂等键、DM/玩家快照和确认执行链；没有结构化施法动作或反应积木时不猜测，不会凭“看起来像法术”自动弹窗。
- 新增真实 API 回归覆盖角色反制施法窗口，并保留原有怪物施法反应回归。定向回归、后端全量 pytest、Ruff、compileall、`git diff --check` 全部通过；仅有既有 Starlette/httpx 弃用警告。
- 当前切片完成度：角色结构化施法反应开窗 `100%`。这是既有“传奇、巢穴、反应动作触发矩阵”的通用消费切片，不新增缺口；反制法术本身的目标、法术等级/豁免等效果仍由其具体积木和 DM/玩家确认边界执行，高级三维战斗仍跳过。

# 2026-08-06 角色结构化受伤/命中反应窗口通用化

- 代码提交 `4783483`：受伤（`takes_damage`）和攻击命中（`hit_by_attack`）反应窗口不再硬限制为怪物；任意在场、仍有反应、生命值大于 0 且未处于失能类状态的单位，只要快照含有明确 `reaction_event` 积木，就会进入同一持久化窗口和现有 DM 确认执行链。
- 新增共享资格门禁，避免死亡、失能、震慑、麻痹、石化或昏迷单位出现过期反应按钮；怪物原有行为保持不变。没有结构化事件的普通文字动作仍不会被猜测开窗。
- 新增真实 API 回归：玩家角色的受伤反应和被攻击命中反应都能开窗，并保留触发目标与动作名称；后端全量测试通过，Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 当前切片完成度：角色结构化受伤/命中反应开窗 `100%`。这是既有“传奇、巢穴、反应动作触发矩阵”的通用消费切片，不新增缺口；反应的实际目标、骰值和效果改写仍按各自积木/玩家确认边界执行，高级三维战斗仍跳过。

# 2026-08-06 召唤数量表达式通用积木校验

- 代码提交 `ffea2a8`：新增 `explicit_count_outcomes` 通用解析器，只解析规则文本中明确列出的有限数量结果，例如 `1d6：2/4/8只`；普通 `1d6`、DM 选择和无法确定的表达式继续交给玩家/DM，不猜骰子结果。
- 玩家召唤动作现在会在动作、资源和召唤单位创建前校验提交数量；明确数量不在积木允许集合时返回 400，非法请求不消耗动作或资源。该校验复用现有召唤生命周期、先攻和控制权执行链，没有新增第二套召唤引擎。
- 新增规则解析回归和真实召唤 API 回归，覆盖允许集合、普通骰式保持人工输入、非法数量拒绝及拒绝后后续正常召唤仍可执行。
- 验证：`backend/.venv/bin/pytest -q backend/tests` 全量通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本切片只修改后端规则与测试，没有新增浏览器验收。
- 当前切片完成度：明确有限数量召唤校验 `100%`。它属于既有“复杂召唤/职业运行时”范围，不新增第五类缺口；高级三维战斗仍跳过。

# 2026-08-06 圣武士勇气灵光动态状态免疫闭环

- 代码提交 `be06efa`：勇气灵光从文字合同提升为 `full`，进入统一状态免疫解析器；同阵营单位在圣武士 10 尺内对 `frightened`/恐慌免疫。
- 真实结算会在每次状态写入、重复效果 tick 和状态生命周期检查时重新读取权威战斗快照；超过 10 尺、敌对阵营、缺少网格/位置或没有结构化光环时 fail-closed，不错误阻止恐慌状态。
- 新增真实 API 回归：近距离盟友拒绝写入恐慌；远距离盟友允许写入；近距离敌人允许写入；运行时合同和消费方同步为 `full`。
- 验证：定向测试 2 项通过；后端全量 `pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 内置浏览器实际刷新 `http://127.0.0.1:5173/#/combat`；DM 战斗辅助页后端连接正常，应用控制台 `error/warn` 均为空。验收截图：`/private/tmp/dnd-aura-of-courage-browser-check-20260806.jpg`。
- 当前切片完成度：勇气灵光动态状态免疫 `100%`。它属于固定大项“职业/子职业 1–20 级运行时闭环”，不新增第五类缺口；跳过高级三维战斗后的固定四大项整体粗略完成度仍约 `70%`。

# 2026-08-06 圣武士守护灵光自动豁免闭环

- 代码提交 `6ed0011`：守护灵光运行时合同从 `partial` 提升为 `full`，快照保留 `value_source` / `minimum` 等字段；自动玩家豁免现在读取权威战斗快照中的圣武士光环。
- 真实结算规则：同阵营、10 尺内才生效；取圣武士魅力调整值且最低 +1；多个符合条件的光环取最高值；缺少权威网格、位置、阵营、魅力或结构化光环积木时 fail-closed，不把光环错误扩成全场加值。
- 修复了目标没有普通 `rule_modifiers` 时 `_rule_modifier()` 提前返回、导致光环解析器永远不执行的控制流 bug。
- 新增回归：自身光环、真实玩家自动豁免 API（魅力 18、目标在 10 尺内得到 +4）均通过；目标豁免日志记录结构化修正说明。
- 验证：定向测试 2 项通过；后端全量 `pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 当前切片完成度：守护灵光自动豁免 `100%`。它属于固定大项“职业/子职业 1–20 级运行时闭环”，不新增第五类缺口；跳过高级三维战斗后的固定四大项整体粗略完成度仍约 `70%`。
- 内置浏览器实际加载 `http://127.0.0.1:5173/#/combat` 的 DM 战斗辅助页；模拟战斗、法术/召唤入口和战斗轨道正常，应用控制台 `error/warn` 均为空。视口验收截图：`/private/tmp/dnd-protection-aura-browser-check-20260806.jpg`。

# 2026-08-06 职业豁免熟练自动结算闭环

- 代码提交 `17e3fef`：圆滑心智（感知/魅力）和圆融自在（全部属性）的 `grant_proficiency` 积木现在进入战斗快照；系统替玩家自动结算目标豁免时，读取权威 `feature_runtime.progression.proficiency_bonus`，对明确匹配的属性只加入一次熟练加值。
- 快照归一化不再丢弃 `grant_proficiency` 和 `abilities` 字段；豁免属性筛选支持单项列表与 `all`，并修复 `saving_throw:self::index` 投影键被误识别为技能名的问题。
- 玩家手动提交最终豁免总值的路径没有重复加熟练，仍保留玩家/DM 的最终总值边界；自动结算日志会记录结构化豁免修正说明。
- 新增回归：重复的单项/全豁免熟练只加一次；感知、魅力和全属性匹配；运行时合同从 `partial` 更新为 `full`；真实玩家施法自动结算目标豁免记录熟练修正。
- 验证：后端全量 `pytest -q backend/tests` 通过（100%，仅既有 Starlette/httpx 弃用警告）；Ruff、compileall、`git diff --check` 通过。
- 内置浏览器实际加载 `http://127.0.0.1:5173/#/combat` 的 DM 战斗辅助页，DOM 显示战斗辅助/模拟战斗/先攻轨道，控制台 error/warn 均为空。验收截图：`/private/tmp/dnd-saving-proficiency-browser-check.png`。
- 当前切片完成度：职业豁免熟练自动结算 `100%`。跳过高级三维战斗后的固定四大项整体粗略完成度仍约 `70%`；本项属于“职业/子职业 1–20 级运行时闭环”，没有新增第五类缺口。

# 2026-08-06 反迷惑多候选反应者 UI 闭环

- 代码提交 `ad16266`：DM 的玩家豁免面板现在读取已持久化的 `countercharm` 反应窗口；唯一候选者自动带入，多候选者展示吟游诗人选择框，未选择时禁止预览/确认。
- 请求类型新增 `feature_reroll_reactor_id`，预览和确认都会把选中的反应者 ID 传给既有后端重骰结算；后端已有的距离、反应可用性、资源消费和幂等校验保持不变，没有重复实现结算器。
- 新增前端回归：两个合资格反应者均显示，未选者时按钮禁用，选择后恢复可提交。前端全量 Vitest `39 文件 / 204 项`、TypeScript、ESLint、生产构建和 `git diff --check` 通过；后端反迷惑定向回归 `2 passed`。
- 内置浏览器实际加载 `http://127.0.0.1:5173/#/combat`，DM 战斗辅助页正常，控制台 error/warn 为空。验收截图：`/private/tmp/dnd-countercharm-ui-check-20260806.jpg`。
- 当前切片完成度：反迷惑“多候选反应者的 DM 选择与请求回传” `100%`。反迷惑整体仍保留既有 DM 边界：缺少权威网格位置时不能自动判断 30 尺，且反应者资源属于其他玩家时仍由 DM 确认；固定范围仍只有 4 个大项，跳过高级三维战斗后的整体粗略完成度仍约 `70%`。

# 2026-08-06 游荡者幸运一击真实运行时闭环

- 代码提交 `0231ca5`：幸运一击从仅有职业运行时定义提升为真实玩家骰点事件链。只有战斗快照中存在完整的 `d20_replacement`、`after_failed_d20_test`、`replace_d20_roll=20` 积木，且角色权威资源 `stroke_of_luck.current` 大于 0 时，失败的属性检定、技能检定或属性豁免才会打开等待窗口；缺少任一权威条件时 fail-closed。
- 首次失败确认会保持动作 `previewed`，DM/玩家可选择幸运一击并提交“天然 20 + 调整值”的最终总值。服务端重新结算成功/失败、逐段伤害和豁免防御，真实扣除资源并同步战斗快照；结果记录原始骰值、替换总值、资源前后值、消费动作 ID。重复确认不重复消费，幸运一击不能与职业重掷、传奇抗性或吟游诗人激励骰叠加。
- 玩家端 `PlayerRollPanel` 增加幸运一击等待提示、资源剩余提示和最终总值输入；窗口不是普通动作按钮，必须先发生失败 D20 事件。运行时合同从 `partial` 修正为 `full`，旧测试同步更新。
- 新增真实 API 回归覆盖：失败打开窗口、18 对 DC 15 后成功、资源 `1→0`、报告原始 `5`、重放不重复消费、资源耗尽不再打开窗口。后端全量 `pytest` 通过；Ruff、compileall、`git diff --check` 通过；前端 Vitest `39 文件 / 203 项`、TypeScript、ESLint、生产构建通过。
- 内置浏览器实际加载 DM 战斗辅助页；后端、SQLite、索引和模型状态正常，应用控制台 error/warn 为空。验收截图：`/private/tmp/dnd-stroke-of-luck-browser-check-20260806.png`。
- 当前切片完成度：幸运一击这一项 `100%`。它属于固定四大项中的“职业/子职业 1–20 级运行时闭环”，不新增第五个缺口；跳过高级三维战斗的固定范围整体粗略完成度仍约 `70%`，后续按既有缺口继续，不重复计算已完成的火球、雷鸣波、复杂伤害和基础战斗链。

# 2026-08-06 圣疗中毒/疾病解除真实执行闭环

- 代码提交 `52b540e`：圣疗从“治疗已自动、解除分支需 DM 选择”提升为完整可执行分支。玩家/DM 共用的职业特性确认接口新增显式 `condition_to_cure`，只允许选择 `poisoned` 或 `diseased`；治疗与解除状态互斥，解除固定消耗 5 点圣疗池，目标没有对应状态时 fail-closed。
- 解除确认会真实移除目标的中毒/疾病状态，并结束当前战斗中所有明确拥有该状态的结构化效果，再恢复状态限制字段；结果、资源前后值和结束效果 ID 都写入动作审计。幂等请求重放不会再次扣池或重复执行。
- 玩家端圣疗动作新增“治疗 / 解除中毒 / 解除疾病”分支，解除选项仅对当前目标已有状态可选；圣疗目标不再被限制为施法者自身，可选择 5 尺内同阵营盟友，后端仍以权威网格位置校验接触距离。
- 新增真实 API 回归：中毒解除资源 20→15、状态移除、幂等重放；不存在的状态被拒绝且资源保持 20。运行时合同更新为 `full`，剩余 DM 边界只保留缺少权威位置时的接触距离裁定。
- 验证：定向后端回归通过；后端全量 `pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过；前端 TypeScript、ESLint、生产构建、Vitest `39 文件 / 203 项`通过。内置浏览器刷新 DM 模拟战斗页面成功，控制台 error/warn 为空，验收截图：`/private/tmp/dnd-lay-on-hands-browser-check-20260806.png`。
- 当前切片完成度：圣疗治疗/中毒/疾病解除这一个可执行子项 `100%`。它仍属于固定大项“职业/子职业 1–20 级运行时闭环”，不代表该大项全部完成；固定范围仍只有 4 个大项，没有新增缺口。

# 2026-08-06 吟游诗人激励骰真实消费与攻击幂等闭环

- 代码提交 `b5c1ea8`：玩家豁免、属性检定、技能检定和普通攻击都支持显式提交吟游诗人激励骰；先处理优势/劣势，再把激励骰加入最终总值。预览不消费，确认后真实把 `feature_dice.bardic_inspiration_die.available` 写为 `false`，并记录来源、骰面、数值和消费动作。
- 玩家端待掷骰和攻击面板增加激励骰输入入口；房间快照和待掷骰快照只投影当前仍可用的骰子。D6/D8 等骰面严格校验，自动失败、法术豁免/自动命中、资源不足、重复消费和与职业重掷叠加均 fail-closed。
- 修复并回归真实权威攻击链：激励骰不再只改变 UI 预览，而会写进 `CombatActionCommand.attack_roll_total`；8 点命中总值 + 激励 4 点按 12 判定并造成伤害。相同幂等请求重放返回原结果、HP 不重复扣除、激励骰不重复消费；不同请求仍拒绝已消费骰。
- 验证：后端全量 pytest 退出码 0；激励骰/攻击定向回归通过；Ruff、compileall、`git diff --check` 通过；前端 TypeScript、ESLint、生产构建和 Vitest `39 文件 / 203 项`通过。内置浏览器实际加载 DM 模拟战斗和玩家页面，双方控制台 error/warn 均为空；玩家端能看到攻击/技能入口、标准动作和共享地图。
- 当前切片完成度：吟游诗人激励骰这一个可执行子项 `100%`。它属于固定大项“职业/子职业 1–20 级运行时闭环”，不代表该大项全部完成；职业特性的复杂事件反应、持续来源冲突和未结构化分支仍保持原有边界。固定范围仍只有 4 个大项，没有新增缺口。

# 2026-08-06 不知疲倦临时生命真实结算切片

- 代码提交 `751d93b`：游侠「不知疲倦」接入现有职业特性执行器。动作会真实消耗 `tireless` 资源并写入临时生命值；`1d8+wisdom_modifier` 读取角色权威感知值校验最终骰值，超范围、缺少权威感知或资源不足都会拒绝且事务回滚。
- 当前只完成了临时生命值这一确定分支，保留“短休减轻力竭”的独立 DM/规则分支为 partial，没有把整个特性错误标成 full。玩家端已有通用职业特性治疗骰入口，可复用该动作投掷和提交流程。
- 新增真实 API 回归：感知 16 时 12 点结果拒绝，7 点结果真实写入临时生命值并将资源 2→1；后端全量 pytest、Ruff、compileall、`git diff --check` 通过。本轮没有前端源码变化，未重复跑前端构建。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不新增缺口。

# 2026-08-06 自然面纱隐形生命周期真实执行闭环

- 代码提交 `062c0c6`：游侠「自然面纱」现在从部分结构化升级为完整可执行职业特性。消耗一次 `nature_veil` 资源和附赠动作后，真实写入隐形状态；推进到该游侠下一回合开始时由现有效果生命周期自动结束，不会永久残留。
- 资源条目同步标为 `full`，玩家/DM 共用的职业特性投影会显示该动作；没有资源、不是当前回合、或重复使用时沿用统一资源/动作经济校验拒绝。
- 新增真实 API 回归覆盖资源 1→0、隐形写入、中间敌方回合仍保持、下一回合开始清理；后端全量 pytest、Ruff、compileall、`git diff --check` 通过。本轮没有前端源码变化，未重复跑前端构建。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不新增缺口；反迷惑、完整反应窗口等仍保持独立未完成状态。

# 2026-08-06 无懈可击持续抗性真实执行闭环

- 代码提交 `a531e81`：武僧「无懈可击」从仅有文字契约提升为可执行职业特性。回合开始、未移动且行动/附赠动作/反应经济仍完整时，确认会真实消耗 3 点专注，创建持续 1 分钟（10 轮）的 `superior_defense` 运行时效果；重复激活和非回合开始使用会被拒绝。
- 伤害引擎现在读取该 active 状态：除力场外的每个伤害段自动获得抗性并分别结算，力场不减半；持续时间由现有效果时钟在第 10 轮后自动结束。未激活或未结构化的条件防御仍保持原有 DM 裁定边界，不凭文字猜测。
- 新增真实 API 回归：资源 3→0、状态/持续时间写入、火焰 8→4、力场 8→8；运行时合同同步从 partial 提升为 full。后端全量 pytest、Ruff、compileall、`git diff --check` 通过。本轮没有前端源码变化，沿用上一切片已验证的前端门禁；浏览器无需新增页面验证。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不新增缺口。反应触发型职业特性（如反迷惑、偏转攻击的完整反击分支）仍归到已有反应窗口缺口，不在本切片冒充完成。

# 2026-08-06 灵巧动作分支真实执行闭环

- 代码提交 `409eed4`：游荡者/狡诈动作现在作为玩家端可执行职业特性投影，疾走、撤离、躲藏三分支不再只是文字。疾走真实增加一次角色有效速度的移动力；撤离真实写入本回合免借机攻击效果；躲藏必须先由 DM 提交成功/失败及裁定说明，只有成功才写入隐匿效果，失败不会伪造状态。
- DM 与玩家特性接口共用同一命令字段和执行器；选项不在积木白名单、躲藏缺少裁定、或将分支字段用于其他职业特性时服务端拒绝。新增后端真实 API 回归覆盖三分支、资源/附赠动作和 DM 边界；玩家端加入分支选择与裁定输入。
- 验证：灵巧动作定向回归通过；后端全量 pytest 通过；Ruff、compileall、前端 Vitest `39 文件 / 203 项`、TypeScript、ESLint、生产构建、`git diff --check` 通过。内置浏览器当前模拟角色是法师，无法从现有页面覆盖游荡者特性入口；DM/玩家页面控制台 error/warn 均为 0，验收截图保存于 `/private/tmp/dnd-cunning-action-browser-check-20260806.png`。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不新增缺口。躲藏的环境、可见性和检定结果仍属于 DM 裁定边界；真实状态写入和分支消费已完成。

# 2026-08-06 快速移动与无甲移动真实速度闭环

- 代码提交 `37586d7`：战斗创建不再直接把角色基础速度写入 Combatant。`快速移动` 和 `无甲移动` 的结构化 `speed_ft` 修正现在由统一解析器读取，并真实写入 `Combatant.speed_ft`、`movement_remaining_ft` 和不可变战斗快照；后续移动、疾走、起身半速和回合刷新因此消费有效速度。
- 只接受权威 `EquipmentInstance` 状态：快速移动在明确重甲时跳过，轻甲/中甲可生效；无甲移动在穿任意护甲或持盾时跳过。装备实例不存在、护甲类型不明确、修正数值未解析或条件不在白名单时 fail-closed，并在 `snapshot_json.speed_resolution` 记录 applied/skipped 原因，不按角色名称或装备文字猜测。
- `feature_runtime_definition` 不再把这两个已经有完整执行器的速度特性标成 `partial`；其运行时合同可为 `full`，但缺失装备权威数据时仍不加成。
- 新增纯运行时回归和真实 `start-combat` API 回归：30→40 的实际移动预算、重甲跳过、无权威装备状态不猜测、无甲移动持盾跳过。定向 46 项通过；后端全量 pytest 通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮只修改后端规则和测试，没有前端源码变更，因此未做浏览器验收；不要把本轮说成浏览器 UI 已验收。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不是新增缺口；固定范围仍只有 4 个大项。

# 2026-08-06 究明攻击失手关联与优势闭环

- 代码提交 `0620cf8`：游荡者「究明攻击」不再只是 `partial` 字段。只有战斗快照含有编译出的究明攻击积木时，明确的攻击失手才会创建持久化运行时效果，并锁定被失手的同一目标。
- 下一次对该目标的攻击由 DM/玩家共用的攻击上下文读取该效果，真实加入优势来源；攻击确认后消费一次。再次失手会刷新同目标效果；推进到下一回合并结束该单位的下一次回合时自动结束效果。没有权威攻击总值或没有职业积木时不创建效果，避免把普通失手误判为职业特性。
- 新增真实 API 回归覆盖：失手写入效果、同目标攻击预览为优势、确认消费、再次失手刷新、跨下一回合结束到期；新增运行时合同回归确认状态为 `full`。DM/玩家攻击上下文均接入同一持久化效果读取。
- 验证：定向回归 2 项通过；后端全量 `pytest` 通过；Ruff、compileall、`git diff --check` 通过。严格 mypy 仍有仓库既有类型错误，未新增为本切片引入的错误；仅有既有 Starlette/httpx 弃用警告。
- 本轮只修改后端规则和测试，没有前端源码变更，因此未做浏览器验收；不要把本轮说成浏览器 UI 已验收。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不是新增缺口；固定范围仍只有 4 个大项。

# 2026-08-05 失败豁免职业重掷自动闭环

- 代码提交 `42c1619`：失败豁免现在会读取战斗快照中的结构化职业特性和角色权威资源；只有明确标记 `after_failed_saving_throw` 且资源足够的特性才会自动打开重掷窗口。
- 玩家/DM 提交第二枚骰后，结算器使用第二次报告值而不是两次骰值取高；确认时真实扣除角色资源，并同步 `feature_runtime.resources`、动作结果和审计字段。资源不足、缺少角色上下文或结构化触发条件时 fail-closed。
- 旧版 `feature_saving_throw_rerolls` 临时令牌仍兼容；事件型重掷不会作为可误点的普通战斗按钮投影，直接调用普通职业动作接口也会被拒绝。
- “不屈”运行时合同从 `partial` 提升为 `full`，无需 DM 裁定；新增真实 API 回归覆盖自动打开窗口、资源扣除、第二骰较低时确实失败，以及旧令牌路径。
- 验证：定向测试和后端全量 `backend/.venv/bin/pytest -q backend/tests` 退出码 0；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本轮未修改前端，未做浏览器验收。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不是新增缺口；固定范围仍只有 4 个大项。

# 2026-08-05 不屈耐力真实战斗结算闭环

- 代码提交 `f0a5ab4`：兽人“不屈耐力”现在由生命归零前的统一伤害结算器真实消费结构化长休资源；抗性、易伤、免疫、临时生命和剩余伤害先结算，再决定是否将 HP 保留为 1。
- 普通伤害确认、区域伤害确认和持续伤害 tick 共用同一拦截逻辑。触发后不会写入昏迷/死亡豁免，角色资源扣 1，并同步角色资源、战斗快照和动作结果审计字段。
- `unapplied_damage >= 最大生命值` 时保持立即死亡规则，不触发不屈耐力；非角色单位、缺失结构化特性或资源不足时 fail-closed，不凭种族名称猜测。
- 运行时合同从 `partial` 提升为 `full`，`requires_dm_adjudication` 为 `false`；新增真实 API 回归覆盖 HP、状态、资源消耗和动作审计。
- 验证：后端全量 `backend/.venv/bin/pytest -q backend/tests` 退出码 0；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本轮未修改前端，未做浏览器验收。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不是新增第 5 个缺口；固定范围仍只有 4 个大项：复杂状态组合与例外、传奇/巢穴/反应矩阵、复杂法术与效果、职业/子职业 1–20 级运行时闭环。

# 2026-08-05 动作如潮限制闭环

- 代码提交 `4cf5120`：动作如潮现在真实强制每个先攻回合只能使用一次，并把使用标记绑定到战斗轮次/行动窗口；重复请求不会再次扣资源或增加额外动作预算。
- 额外动作预算消费时读取结构化动作资料；若动作明确是法术，服务端拒绝使用动作如潮的额外动作施法；普通攻击仍可消费额外动作。运行时合同从 `partial` 提升为 `full`。
- 新增真实 API 回归覆盖资源/预算、重复使用、法术排除和普通额外攻击。验证：后端全量 `pytest` 通过（100%，仅既有 Starlette/httpx 弃用警告）；定向测试、Ruff、compileall、`git diff --check` 通过。本轮仅修改后端，未做浏览器验收。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不是新增缺口；固定范围仍只有 4 个大项。

# 2026-08-05 不屈勇武力量检定最低值闭环

- 代码提交 `cbdadca`：不屈勇武/不屈巨力的结构化 `set_minimum_total_from_ability` 修正现在由玩家骰点结算器真实消费。明确力量属性检定且报告总值低于角色力量值时，结算总值改为力量值；敏捷、技能检定和缺少权威力量值时不套用。
- 运行时合同从 `partial` 提升为 `full`，写入 `feature:不屈勇武最低力量检定总值` 审计来源；DM/玩家共用同一 `player_roll_resolution` 路径。新增回归覆盖力量 18、报告 5、DC 17 成功，以及非力量检定保持失败。
- 验证：定向特性/战斗测试通过；后端全量 `pytest` 通过（100%，仅既有 Starlette/httpx 弃用警告）；Ruff、compileall、`git diff --check` 通过。本轮仅修改后端，未做浏览器验收，不把代码门禁冒充浏览器结果。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不是新增缺口；固定范围仍只有 4 个大项。

# 2026-08-05 目盲视觉检定自动失败闭环

- 代码提交 `699d5f8`：玩家骰点请求新增显式 `requires_sight` 输入。只有调用方明确声明该检定依赖视觉，且目标拥有 `blinded/目盲` 状态时，结算器才会把结果真实判为自动失败，并写入 `condition_auto_fail_sight_check`；不会凭“察觉”等技能名称猜测视觉依赖。
- 非视觉检定在目盲状态下不被错误改写；DM/玩家的预览和确认继续共用同一结算函数，保持结果一致。新增回归覆盖视觉检定自动失败和非视觉检定正常成功。
- 验证：后端全量 `pytest` 通过（100%，仅既有 Starlette/httpx 弃用警告）；Ruff、compileall、`git diff --check` 通过。本轮仅修改后端，未做浏览器验收，不把代码门禁冒充浏览器结果。
- 这是固定大项“复杂状态组合与规则例外”的内部切片，不是新增缺口；固定范围仍只有 4 个大项：复杂状态组合与例外、传奇/巢穴/反应矩阵、复杂法术与效果、职业/子职业 1–20 级运行时闭环。

# 2026-08-05 恐慌状态对属性/技能检定的可见来源规则

- 代码提交 `45c9471`：战斗中的 `ability_check` / `skill_check` 现在读取结构化恐慌来源的权威可见性；恐惧来源可见时真实取两枚报告骰的较低值，并写入 `condition:frightened_disadvantage_check`。
- 恐惧来源不可见时不施加该劣势；来源、场景或视线缺失时保持 DM 裁定边界，不把未知当作可见。它与职业特性优势同时存在时按优势/劣势抵消规则取单骰。
- 预览和确认共用同一结算函数，新增运行时回归覆盖可见/不可见两条结果。后端全量 pytest、Ruff、compileall、`git diff --check` 全部通过；本轮仅改后端，未做浏览器验收。
- 这属于固定大项“复杂状态组合与规则例外”，不是新增缺口；中毒、恐慌、束缚、倒地、失能等已有状态链继续复用同一优势/劣势和生命周期框架。

# 2026-08-05 回合末反应窗口跨边界失效

- 代码提交 `1575094`：同一套时序清理现在也覆盖结构化反应窗口。推进到下一行动单位时，仍为 `eligible` 且属于上一行动时序的回合末、受伤、命中、施法、进出范围等事件反应窗口会真实写为 `invalidated`；当前新时序创建的窗口不会被误关。
- 反应资源已被其他路径消耗时仍沿用 `4b79ce8` 的 `reaction_spent_elsewhere` 失效原因；本切片新增的回合边界原因是 `turn_window_closed`。确认接口继续拒绝失效窗口，不会重放事件。
- 新增回归扩展：回合末反应窗口与巢穴窗口一起跨边界失效；高级动作、巢穴动作、传奇动作、反应窗口的定向回归 4 项通过。
- 验证：后端全量 pytest 退出码 0；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本轮仍只改后端，未做浏览器验收。
- 这仍属于固定大项“传奇、巢穴、反应动作完整触发矩阵”，没有新增第五个缺口；代码与文档保持拆分提交。

# 2026-08-05 传奇/巢穴窗口跨回合失效

- 代码提交 `2f0ef2e`：传奇动作和巢穴动作的结构化资格窗口现在绑定到创建它的先攻时序。推进到下一行动窗口时，仍为 `eligible` 的旧高级动作窗口会真实写为 `invalidated`，记录 `turn_window_closed` 和关闭它的新窗口键。
- 旧窗口的确认接口返回 `advanced action window is no longer eligible`，不会再扣传奇动作点、巢穴动作使用次数或写入伤害；已经确认的窗口保持 `resolved`，不会被重复改写。
- 新增真实 API 回归：未确认巢穴窗口跨到下一单位后失效；未确认传奇窗口跨到下一时序后失效；重放旧传奇窗口被拒绝且资源仍为 3 点。
- 验证：高级动作/反应定向回归 4 项通过；后端全量 pytest 退出码 0；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮仅修改后端规则和回归测试，未做浏览器验收，不把后端门禁冒充前端结果。用户原有未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 未纳入提交。
- 这不是新增第五个缺口，而是固定大项“传奇、巢穴、反应动作完整触发矩阵”中“巢穴动作与回合窗口”的生命周期补全。固定范围仍只有 4 个大项：复杂状态组合与例外、传奇/巢穴/反应矩阵、复杂法术与效果、职业/子职业 1–20 级运行时闭环。

# 2026-08-05 无甲防御 AC 闭环

- 代码提交 `3411ce0`：战斗创建时读取角色的权威 `EquipmentInstance` 装备状态和无甲防御结构化公式，真实计算野蛮人 `10+敏捷修正+体质修正`、武僧 `10+敏捷修正+感知修正`。
- 野蛮人允许持盾并实际加入 +2 AC；武僧持盾或任一护甲时不套用无甲防御。计算结果写入 Combatant AC 和 `armor_class_resolution` 快照，后续命中判定直接消费该 AC。
- 没有装备实例、公式不在允许列表或装备状态不明确时 fail-closed，保持角色原 AC；没有用物品名称猜测“已装备”。
- 运行时合同从 `partial` 提升为 `full`；新增纯函数和真实场景战斗回归，覆盖持盾野蛮人 AC 19 及缺失装备状态边界。
- 验证：定向回归通过；当前源码全量后端 `509 passed`；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮未修改前端源码；不把后端门禁冒充浏览器验收。
- 当前仍未完成：失败豁免即时重掷窗口、复杂状态组合其他例外、完整传奇/巢穴/反应触发矩阵、复杂三维规则边界、全职业/子职业 1–20 级运行时。

# 2026-08-05 先攻开始资源恢复闭环

- 代码提交 `b330521`：先攻开始会消费结构化 `recovery_events`，对资料明确且无需裁定的事件真实写回角色资源和战斗快照。
- 已自动执行：`先发激励`在激励骰低于 2 时补到 2；`大德鲁伊`在野性形态次数为 0 时恢复 1 次。恢复过程记录资源键、前后值、条件和操作，并同步到 `feature_runtime.resources`。
- 未知条件、缺少数值状态或超出资源上限的事件 fail-closed；`明镜止水`仍因“本次是否使用运转周天”的条件保留 DM 裁定，不误执行。
- 运行时合同中上述两项从 `partial` 提升为 `full`；新增纯函数回归和真实 `start-combat` 持久化回归。
- 验证：定向回归通过；当前源码全量后端 `507 passed`；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮未修改前端源码；浏览器仍不作虚假验收声明。
- 当前仍未完成：无甲防御装备条件 AC 求值、复杂状态组合其他例外、完整传奇/巢穴/反应触发矩阵、复杂三维规则边界、全职业/子职业 1–20 级运行时。

# 2026-08-05 野性直觉先攻优势闭环

- 代码提交 `f9a6447`：场景开始战斗时读取角色 `feature_runtime.combat_start.modifiers` 的先攻优势；只有明确的 `stat=initiative`、`operation=advantage`、`scope=self` 修正才会触发，真实投掷两枚 d20 并取较高值。
- 先攻结果和不可变战斗快照同时记录 `mode`、全部 `dice`、`selected_die`、优势/劣势来源；既有 `die` 和 `total` 字段保持兼容。优势与劣势同时存在时按规则抵消，保留单骰，不猜测冲突裁定。
- 运行时合同从 `partial` 提升为 `full`；新增编译器回归和真实 `start-combat` API 回归，覆盖 `[4,18]` 取 18、敏捷修正和快照持久化。
- 验证：定向回归通过；当前源码全量后端 `505 passed`；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮未修改前端源码；不重复宣称浏览器验收，当前本地浏览器地址仍受既有安全策略限制。
- 当前仍未完成：无甲防御装备条件 AC 求值、复杂状态组合其他例外、完整传奇/巢穴/反应触发矩阵、复杂三维规则边界、全职业/子职业 1–20 级运行时。

# 2026-08-05 危险感知敏捷豁免优势闭环

- 本轮未提交修改将 `danger_sense:dexterity_saving_throw_advantage` 从 `partial` 提升为 `full`：未处于失能状态时，敏捷豁免真实取两枚报告骰的较高值；处于失能状态时不生效。
- 运行时条件复用统一的状态门禁，缺少第二枚骰值时保持既有 DM 裁定边界，不猜测骰值；DM 与玩家共用同一豁免防御求值路径。
- 新增回归覆盖正常优势和失能状态关闭优势。
- 验证：后端全量 pytest 通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮未修改前端源码；内置浏览器仍受现有 `127.0.0.1:5173` URL 安全策略阻断，未将代码门禁冒充浏览器验收，也未生成伪截图。
- 代码与本交接记录拆分提交；当前仍未完成：复杂状态组合其他例外、完整传奇/巢穴/反应触发矩阵、复杂三维规则边界、全职业/子职业 1–20 级运行时。

# 2026-08-05 稳定瞄准下一次攻击闭环

- 代码提交 `4346dd4`：稳定瞄准从 `partial/blocked` 提升为可执行特性动作。确认前要求本回合移动力仍等于速度；确认后消耗附赠动作、将移动力设为 0，并写入回合结束到期的 `steady_aim` 运行时效果。
- DM 与玩家攻击路径都读取该效果，为下一次攻击加入优势来源；攻击确认后只消费这一枚效果，第二次攻击不再继承，回合结束也会统一清理条件。
- 新增回归覆盖：移动后拒绝激活、激活后移动归零、首次攻击优势与效果消费、后续攻击不继承、回合结束失效。
- 验证：后端全量 pytest 通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮未修改前端源码；内置浏览器仍受现有 `127.0.0.1:5173` URL 安全策略阻断，未将代码门禁冒充浏览器验收，也未生成伪截图。
- 仍未完成：复杂状态组合其他例外、完整传奇/巢穴/反应触发矩阵、复杂三维规则边界、全职业/子职业 1–20 级运行时。

## 2026-08-05 中毒状态对属性/技能检定的组合规则

- 代码提交 `10fed3f`：中毒状态现在真实影响 `ability_check` 和 `skill_check`，按 D&D 规则要求取两枚报告骰的较低值；不再只在攻击骰上生效。
- 中毒与结构化优势同时存在时，优势和劣势抵消为单骰；结果写入 `applied_defenses`，不会错误取高值或擅自补第二枚骰。缺少第二枚报告骰时继续停在 DM/玩家输入边界。
- 新增纯运行时回归和真实 `player-rolls` API 回归，覆盖中毒单独劣势、与职业优势抵消、最终检定结果和审计来源。
- 验证：定向状态/特性测试通过；当前后端全量测试到 100% 且退出码 0；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮仅修改后端规则和测试，未重复前端构建或浏览器验收；工作树仍保留用户原有未跟踪文件 `backend/tests/integrations/` 和 `backend/tests/ollama.py`。
- 该切片不代表复杂状态组合全部完成；剩余仍是其他状态间例外、持续来源冲突和完整规则矩阵。

## 2026-08-05 反应资源消耗后的过期窗口清理

- 代码提交 `4b79ce8`：反应者通过其他反应路径消耗反应资源后，该单位所有尚未处理的结构化反应窗口会真实写为 `invalidated`，并记录 `reaction_spent_elsewhere`；当前正在确认的窗口仍由确认链最终写为 `resolved`。
- 过期窗口不能再创建玩家豁免 prompt 或执行伤害；服务端返回明确的“reaction window is no longer eligible”，避免 DM/玩家端继续操作旧提示。
- 新增真实 API 回归：先由受伤事件打开反应窗口，再用另一条反应消耗资源，确认窗口失效并拒绝旧窗口重放。
- 验证：定向反应回归通过；当前后端全量测试到 100% 且退出码 0；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮仅修改后端规则和测试，未重复前端构建或浏览器验收；工作树仍保留用户原有未跟踪文件 `backend/tests/integrations/` 和 `backend/tests/ollama.py`。
- 反应/传奇/巢穴大项仍未全部完成：剩余是全事件矩阵、复杂动作目标/骰子和更多高级分支，不把本项清理过期窗口说成完整高级动作自动化。

# 2026-08-05 飘忽不定取消攻击优势闭环

- 代码提交 `4fcd13c`：飘忽不定的结构化防御现在由攻击上下文统一求值。目标未处于失能、震慑、麻痹、石化或昏迷等动作阻断状态时，清除所有针对该目标的优势来源，包括倒地、目盲、鲁莽攻击和职业优势；不误清除劣势。
- DM 与玩家端共用同一取消规则；目标进入失能状态后，防御条件自动不适用，优势恢复。
- 新增回归覆盖职业优势来源、倒地近战优势以及失能例外。
- 验证：定向特性/攻击上下文测试通过；后端全量测试通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 本轮未修改前端源码；内置浏览器仍受现有 `127.0.0.1:5173` URL 安全策略阻断，未将代码门禁冒充浏览器验收，也未生成伪截图。

# 2026-08-05 鲁莽攻击优势与回合生命周期闭环

- 代码提交 `b457fe3`：鲁莽攻击的结构化特性现在会出现在可执行特性动作中，激活后写入带 `turn_start` 到期的真实状态。
- 攻击者只有在攻击元数据明确为力量属性的武器攻击时获得优势；攻击带有鲁莽攻击状态的单位时，攻击者自动获得优势。
  缺少力量/武器攻击元数据时不猜测，DM 攻击路径要求显式裁定；玩家路径复用相同的明确字段和条件矩阵。
- 下回合开始会自动结束鲁莽攻击状态和对应运行时效果；旧客户端未传新字段时保持兼容并 fail-closed。
- 新增后端回归覆盖特性动作实际激活/到期、DM 两端优势上下文、玩家端双方优势、中文/英文状态别名和特性投影。
- 验证：后端全量 pytest 通过；定向回归通过；Ruff、compileall、`git diff --check` 通过。本轮未修改前端源码。
- 内置浏览器未重复尝试：本轮只有后端规则与 API 字段改动，之前的本地 URL 安全策略阻断仍有效记录。
- 当前仍未完成：鲁莽攻击与复杂攻击例外的更多交互、稳定瞄准/危险感知等条件特性、复杂状态组合其他例外、完整传奇/巢穴/反应触发矩阵、复杂三维规则边界、全职业/子职业 1–20 级运行时。

# 2026-08-05 狂暴力量豁免优势真实执行

- 代码提交 `b1ce1d9`：运行时条件求值器现在读取 `raging` 状态；狂暴者的结构化力量豁免优势会真实选择两枚报告骰中的较高值。
- 狂暴状态移除后同一条修正不再生效；没有把尚未接入通用属性检定的“力量属性检定优势”误标为完成。
- `rage:strength_saving_throw_advantage` 运行时合同从 `partial` 更新为 `full`；狂暴的力量检定优势仍保持未完成状态。
- 新增回归覆盖中文“狂暴”别名、5/18 取 18、状态结束后只取 5，以及运行时合同状态。
- 验证：定向运行时测试通过；后端全量 pytest 100% 通过；Ruff、compileall、`git diff --check` 通过。本轮未修改前端源码。
- 内置浏览器未重复尝试：本轮只有后端规则求值改动，之前的本地 URL 安全策略阻断仍记录在上一条交接中。
- 当前仍未完成：狂暴力量属性检定优势、鲁莽攻击攻防优势、复杂状态组合的其他例外、完整传奇/巢穴/反应触发矩阵、复杂三维规则边界、全职业/子职业 1–20 级运行时。

# 2026-08-05 反射闪避状态与适用条件闭环

- 代码提交 `09ed2c0`：Evasion 现在只对明确“成功豁免减半伤害”的敏捷豁免生效；完整伤害豁免不会误套用
  反射闪避。
- Evasion 在目标处于失能、震慑、麻痹、石化或昏迷时自动失效；条件集合复用现有统一状态推导，不产生重复状态行。
- 运行时合同从 `partial` 更新为 `full`，保留真实执行摘要；没有位置、骰值或 DM 选择的新裁定被猜测。
- 新增回归覆盖完整伤害豁免、失能目标、正常半伤豁免和混合伤害逐段结算；针对一个旧测试补齐了其缺失的
  `half_damage_on_save` 事实字段。
- 验证：后端全量 `pytest` 通过；Ruff、compileall、`git diff --check` 通过；本轮未修改前端源码，因此不重复前端构建。
- 内置浏览器仍未能验收：现有 `127.0.0.1:5173/#/player?...` 标签显示“无法访问此站点”，接管动作继续被 Browser URL
  安全策略拒绝；没有生成或声称存在截图。
- 当前仍未完成：复杂状态组合的其他例外、完整传奇/巢穴/反应触发矩阵、复杂三维规则边界、全职业/子职业 1–20 级运行时。

# 2026-08-05 离开近战范围反应事件统一化

- 新增共享的 `leaves_reach` 结构化反应窗口。玩家移动、怪物 AI 移动和规则积木强制位移在
  真实离开反应者的近战范围时，都会按权威网格位置、范围和阵营写入持久化窗口。
- 兼容旧的玩家借机攻击请求：已有可自动执行的普通近战攻击仍走原玩家选择/自动攻击链；新窗口
  专门覆盖原链无法表达的结构化反应（例如豁免型离开范围反应），不替玩家请求重复弹窗。
- 窗口锁定触发单位、前后坐标、范围、反应动作名和触发文本，DM 高级动作面板复用既有窗口确认、
  目标校验、骰值和反应资源消耗链；没有反应结构化数据不会猜测。
- 新增/扩展玩家移动回归，覆盖窗口事件、触发单位、目标和旧长剑借机攻击兼容；后端全量 pytest、
  Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告；本轮未修改前端源码。
- 内置浏览器本轮未重新尝试：此前 `127.0.0.1:5173` 仍被 Browser URL 安全策略拦截，不能将代码门禁冒充浏览器验收。

# 2026-08-05 偏转攻击归零后的玩家反击闭环

- 完成 `偏转攻击` 的第二阶段真实执行：第一次减伤把本次伤害降为 0 后，创建独立的
  `deflect_redirect` 持久化窗口；窗口冻结可见、5 尺内目标、敏捷豁免 DC、武艺骰面数、
  Focus 成本和伤害类型，不把缺失的位置或骰面猜成默认值。
- DM 与玩家端都能同步显示该窗口并提交目标、敏捷豁免总值和两枚武艺骰。确认后通过普通
  CombatEngine 伤害链结算，真实消耗 1 Focus，按豁免成功半伤/失败全伤，应用抗性/易伤/免疫、
  HP、死亡/专注生命周期和战斗日志；窗口幂等且不能重复处理。
- 修复玩家端第一阶段的真实漏接：玩家提交的 d10 减伤骰现在由
  `PreDamageReactionInput` 接收并传到 CombatEngine，不再被路由层丢弃。
- 新增后端回归覆盖 DM 完整反击链、玩家完整反击链、目标范围/可见性、Focus 扣除、HP 变化和
  旧运行时契约更新；后端全量测试通过，前端 `39 文件 / 202 项`、TypeScript、ESLint、生产构建、
  Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。
- 内置浏览器本轮仍无法验收：当前 `127.0.0.1:5173` 标签显示“无法访问此站点”，Browser URL
  安全策略拒绝接管/刷新该地址；虽然 shell 对 5173 返回 HTTP 200，但不能把代码门禁冒充成浏览器
  通过，也没有生成伪截图。
- 当前仍需 DM/玩家输入：是否使用反击、目标、敏捷豁免骰和两枚武艺骰。仍未自动化的是更复杂
  的反击触发矩阵、非结构化攻击事件、以及缺少权威位置/武艺骰数据时的规则裁定。

# 2026-08-05 攻击命中反应事件窗口

- 扩展反应事件闭合词汇，新增 `hit_by_attack`。资料编译器不再把“被攻击命中”错误归入“受到伤害”；后者仍只表示实际承受伤害，前者专门表示攻击检定命中，即使后续被抗性或免疫减为 0 也保留命中语义。
- 普通攻击确认链现在在有权威攻击总值达到有效 AC、明确暴击或 DM override 时，为目标怪物的结构化 `hit_by_attack` 反应写入持久化窗口；攻击未命中、非攻击伤害、没有命中证据的自由伤害不会开窗。窗口记录攻击动作、攻击者、被命中者、攻击总值、有效 AC、命中依据和可选反应动作。
- DM 高级动作面板、玩家/后端 schema、怪物 AI 预览和前端反应事件选择器均能识别该事件；已有 `leaves_reach`、`enters_reach`、`takes_damage`、`casts_spell`、`turn_end` 链不变。
- 新增回归：未达到 AC 不产生命中反应窗口；命中后产生唯一窗口并保留攻击上下文；官方资料“被攻击命中”解析为 `hit_by_attack`。
- 验证：定向后端通过；后端全量 pytest 100% 通过（仅既有 Starlette/httpx 弃用警告）；Ruff、`git diff --check` 通过；前端相关 28 项、全量 39 文件/202 项、TypeScript、ESLint、生产构建通过。
- 内置浏览器复核仍被当前 `127.0.0.1:5173` URL 安全策略拦截，页面停留在“无法访问此站点”；没有把代码门禁冒充成浏览器验收，也没有生成伪截图。
- 当前边界：这一步完成的是“命中事件被发现并持久化”。反应动作仍由 DM 确认目标和骰值；需要在伤害落地前改写本次伤害的直觉闪避、偏转攻击、护盾等反应，仍未接入前置结算事务，不能宣称已经自动减伤或改写伤害。

# 2026-08-05 动态透明物件与大体型区域边界

- 代码工作树中的本轮实现已接入统一的 `sight_transparency` 规则：`transparent` 不阻挡视线且不提供掩体，`translucent` 可见但提供半掩体，`opaque` 完全阻挡；兼容 `clear`、`semi_transparent`、中文值以及既有 `blocks_sight: false`。未声明的墙体/关闭门仍保守按不透明处理，不猜材质。
- DM 战斗几何、玩家攻击/区域校验、玩家战争迷雾、前端网格目标预览共用该规则；`public_cells()` 保留透明度元数据。`destroyed`/`picked_up` 场景物件不再参与阻挡或掩体计算。
- 大体型单位的区域命中不再只检查锚点格：立方体、球体、圆柱、锥形、直线区域会检查其全部占用格，任意占用格命中即进入目标集合；区域距离也复用占用格之间的最短距离。普通攻击的大体型多点视线核心保持不变。
- 回归覆盖动态透明/半透明/不透明物件、销毁/拾取物件、大体型区域边界和玩家区域预检；本轮未修改火球术、雷鸣波、复合伤害、基础召唤或基础怪物 AI。
- 当前源码门禁：后端全量 pytest 通过（末尾为 100%），Ruff 通过；前端 Vitest `39 文件 / 202 项`、TypeScript、ESLint、生产构建通过；`git diff --check` 通过。仅有既存 Starlette/httpx 弃用警告。
- 浏览器验收待本轮最后一次尝试；若当前本地 URL 仍被 Browser URL 安全策略拦截，不能把代码门禁冒充为浏览器通过，也不能伪造截图。
- 仍未完成：更复杂材质/多个重叠透明物件规则、大体型区域的细致三维边界语义、完整反应/传奇/巢穴触发矩阵、复杂状态组合、全职业/子职业 1–20 级运行时。

# 2026-08-05 高度感知的三维视线与遮挡

- 补充共享三维射线判定：当攻击者、目标以及射线上的所有阻挡物都有明确高度时，按墙体的
  `base_elevation_ft`/`top_elevation_ft` 或 `height_ft` 判断射线是否越过墙体；攻击上下文新增
  `line_of_sight_mode:3d`。明确高度的矮墙可被高处单位越过，低处单位仍被挡住。
- 墙体高度缺失时不猜测，保守回退既有二维阻挡并记录 `line_of_sight_mode:2d`；二维旧地图行为保持不变。
  三维可见时，旧二维墙交点不会再错误地把攻击标成 `cover:total`。
- DM 普通攻击、怪物区域动作、玩家豁免区域目标以及玩家端攻击/多目标/区域技能校验共用同一视线判定，
  避免两端一个能选目标、另一个却判定被遮挡。
- 新增高于矮墙、低于高墙、缺失墙高保守回退的 API 回归测试；既有二维墙、掩体、闪避和三维射程测试继续通过。
- 验证：三维视线定向测试 4/4；后端全量测试通过；Ruff、`git diff --check` 通过。内置浏览器尝试接管当前
  `127.0.0.1:5173/#/player?...` 标签时被当前 Browser URL 安全策略拦截，页面显示“无法访问此站点”，未把它冒充为浏览器验收通过，也未生成伪截图。
- 仍未完成：复杂三维遮挡的多点/大体型视线、动态透明/半透明物件、完整反应/传奇/巢穴触发矩阵、复杂状态组合、
  全职业/子职业 1–20 级运行时。

# 2026-08-05 大体型单位的多点视线与距离

- 战斗快照现在识别 `size_cells`，也识别 `size` 标签：Tiny/Small/Medium=1、Large=2、Huge=3、Gargantuan=4；
  未知或缺失值保持旧的一格行为，不猜测单位大小。
- 普通攻击使用攻击者与目标占用格子之间的最短合法方格距离，并在所有占用格子组合中寻找可见射线；
  因此大型单位不再被左上角单格遮挡错误卡住。结果记录双方占地尺寸和实际采用的 `line_of_sight_pair`。
- 怪物区域动作和玩家端普通攻击/多目标视线校验复用同一多格射线核心；三维高度完整时仍使用墙高判定，
  高度缺失时仍保守回退二维。
- 新增回归：大型攻击者/目标在锚点射线被墙挡住时，使用另一组可见占用格结算，距离从 20 尺正确降为 15 尺；
  高度视线、普通墙体、掩体、闪避和三维射程回归继续通过。
- 验证：大体型/三维视线定向测试 3/3；后端全量测试通过；Ruff、`git diff --check` 通过。未改前端源码，未重复
  前端构建；内置浏览器仍受当前本地 URL 安全策略限制，未将浏览器验收冒充为通过。
- 仍未完成：动态透明/半透明物件、面积/锥体对大体型边界的完整几何、完整反应/传奇/巢穴触发矩阵、复杂状态组合、
  全职业/子职业 1–20 级运行时。

# 2026-08-05 普通攻击三维射程校验

- 提交 `51067da`：攻击者与目标都拥有权威 `grid_position.elevation_ft` 时，攻击距离按 5e 方格规则
  使用水平/垂直轴距离的较大值；缺少任一高度则保持既有二维距离，不猜高度。攻击上下文额外记录
  `horizontal_distance_ft`、`vertical_distance_ft` 和 `distance_mode:3d`。
- 新增 `test_attack_range_uses_authoritative_vertical_distance_when_available`：水平 15 尺、垂直 20 尺
  的目标不能用 15 尺射程攻击，20 尺射程可以正常结算。
- 验证：三维射程/视线/闪避定向 3/3、后端全量测试、Ruff、`git diff --check` 通过；仅有既存
  Starlette/httpx 弃用警告。本轮修改后端攻击几何，未改前端，因此未重复浏览器验收。
- 代码与文档拆分提交：代码 `51067da`；本交接文档为后续独立文档提交。

# 2026-08-05 RepeatBlock 显式次数执行

- 提交 `4166e2a`：持续伤害/治疗的 `RepeatBlock.count` 现在由回合执行器真实记录并消耗；达到次数后
  效果结束，后续回合不再 tick。无效的显式次数返回 DM review，不猜测；`count_expression` 仍未自动解析。
- 新增 `test_repeating_damage_count_stops_after_declared_ticks`：`count=1` 首次 tick 后效果结束，第二次
  推进没有第二次伤害，并保留“重复次数已用尽”审计。
- 验证：定向重复效果测试 2/2、后端全量测试、Ruff、`git diff --check` 通过；仅有既存
  Starlette/httpx 弃用警告。本轮未改前端，因此不重复浏览器验收。
- 代码与文档拆分提交：代码 `4166e2a`；本交接文档为后续独立文档提交。

# 2026-08-05 持续状态 tick 尊重后置条件免疫

- 提交 `85ff996`：持续条件在回合 tick 重新施加前，现在复用初次施加的条件免疫门禁；单位在效果
  生效期间获得对应免疫并清除状态后，后续 tick 返回 `status=immune`，不会把状态写回。
- 新增 `test_repeating_condition_tick_respects_immunity_gained_mid_effect`，覆盖“先施加中毒、再获得
  poisoned 免疫、推进回合、状态保持清除”的真实 API 链路。
- 验证：定向重复状态测试 2/2、后端全量测试、Ruff、`git diff --check` 通过；仅有既存
  Starlette/httpx 弃用警告。本轮未改前端，因此不重复浏览器验收。
- 代码与文档拆分提交：代码 `85ff996`；本交接文档为后续独立文档提交。

# 2026-08-05 闪避可见性规则闭环

- 提交 `e7446b2`：攻击上下文现在读取权威战斗网格的 `line_of_sight`，只有防御者看得见攻击者时，
  闪避才真实加入攻击劣势；有权威几何但攻击者不可见时，写入
  `target_dodge_no_effect_attacker_not_visible` 审计上下文，不再错误施加劣势。
- 缺少可靠几何时保留 DM 裁定，不猜测可见性；隔墙攻击仍必须由 DM 明确 override，且不会把闪避效果
  当作有效劣势。没有改动火球术、雷鸣波、复合伤害、召唤生命周期或基础 AI。
- 新增 `test_dodge_disadvantage_requires_authoritative_visibility`，覆盖可见生效、不可见不生效、
  DM 放行以及上下文审计。
- 验证：定向 combat engine/action lifecycle 测试通过；后端全量测试通过；Ruff 和
  `git diff --check` 通过。仅有既存 Starlette/httpx 弃用警告。
- 代码和文档拆分提交：代码 `e7446b2`；本交接文档为后续独立文档提交。

# 2026-08-04 传奇抗性豁免 UI 接入

- 提交待记录：DM 的玩家豁免面板现在读取目标 `advanced_defenses.legendary_resistance`，显示剩余次数，并允许在玩家骰结果预览/确认时选择“失败时使用传奇抗性”。预览与确认都把 `use_legendary_resistance` 传给已有后端结算链；不改变后端规则。
- 后端已有真实行为：只有豁免失败时才把结果改为成功并消耗 1 次，成功豁免不能消耗传奇抗性；伤害、状态和资源结果继续由同一个 `_resolve_save_defenses` 事务写入。
- 回归：前端 PlayerRollPanel 传奇抗性入口测试；已有后端传奇抗性批量/单体豁免测试继续覆盖失败转成功与资源消耗。
- 门禁：前端 Vitest `39 文件 / 201 项`、TypeScript、ESLint、生产构建、后端全量、Ruff、`git diff --check` 通过（仅既有 Starlette/httpx 弃用警告）。
- 仍需 DM/玩家输入：玩家仍要提供豁免骰；传奇抗性是否消耗由 DM/流程确认。浏览器实战若被当前 URL 安全策略阻断，不得将单测和构建冒充为浏览器验收。

# 2026-08-04 DM 高级动作暴击伤害自动掷骰

- 提交 `ced7073`：补完上一轮遗留的 DM 高级动作伤害骰路径。高级攻击现在复用结构化伤害积木；DM 勾选暴击，或目标满足权威规则对应的“5 尺内麻痹/昏迷”条件时，逐段把骰子项翻倍后自动掷骰，固定修正不翻倍，并向现有 `CombatActionCommand` 发送 `critical_hit` 标记。
- 多段伤害仍逐段保留伤害类型和标签，未把最终伤害总值乘 2；后端继续只接收已经掷出的最终值，按既有抗性/易伤/免疫链结算。豁免型高级动作不显示暴击伤害骰，也不会误标暴击。
- 前端回归覆盖：多段 `1d6+3`/`1d8+2` 暴击后分别变为 `2d6+3`/`2d8+2`；DM 高级动作 `2d8+5` 在近距离麻痹目标上自动发出 `4d8+5`，固定修正保持 5。
- 门禁：前端 Vitest `39 文件 / 200 项`、TypeScript、ESLint、生产构建、后端 `465 passed`、Ruff、`git diff --check` 均通过（仅既有 Starlette/httpx 弃用警告）。
- 浏览器边界：尝试刷新现有 `127.0.0.1:5173/#/player?...` 标签时再次被 Browser Use URL 安全策略拒绝；未把测试结果冒充成内置浏览器验收，也没有生成伪截图。当前浏览器实战仍待服务可访问且策略允许时补验。
- 仍需 DM 输入：攻击总值仍由 DM 确认；天然 20 等非结构化暴击需 DM 勾选。仍未自动化：复杂状态组合、完整反应/传奇/巢穴触发矩阵、复杂三维遮挡、全职业/子职业 1–20 级运行时。

# 2026-08-04 暴击伤害骰显示与自动命中边界

- 本项待提交：结构化伤害积木新增 `critical_damage_expression()`，暴击时只把骰子项翻倍，修正值和属性
  占位符不翻倍；玩家端单目标对 5 尺内麻痹/昏迷目标会显示双倍伤害骰，并明确提醒不要再次翻倍最终总值。
- 玩家战斗结果的每个伤害段补充原始表达式和 `critical_damage_expression`，日志说明同步提示应掷的骰式；
  多段伤害仍按各段独立提交，未把复合伤害合并成一个猜测值。
- 修复边界：豁免型法术和自动命中技能不会因为目标状态被误判为暴击，也不会被错误要求额外的 d20。
- 验证：后端全量 `465 passed`，Ruff、`git diff --check` 通过；前端 `combatAutomation.test.ts` 20 项、
  TypeScript、ESLint、生产构建通过。内置浏览器刷新现有玩家页被 Browser Use URL 安全策略拦截并返回
  `ERR_CONNECTION_REFUSED`，因此本项没有宣称浏览器验收通过，也没有生成截图。
- 仍未完成：DM 最终伤害总值接口的自动掷骰/自动翻倍（它没有骰式输入，不能安全猜测）、复杂状态组合其他
  例外、完整三维遮挡、完整反应/传奇/巢穴自动触发矩阵和所有职业/子职业 1–20 级运行时。

# 2026-08-04 麻痹/昏迷目标的近战自动暴击

- 提交 `8139287`：DM 核心攻击路径使用权威网格确认攻击者与麻痹/昏迷目标距离不超过 5 尺时，
  在 action 结果写入 `automatic_critical`/`critical_hit` 标记；目标处于 0 HP 时，死亡豁免失败按暴击
  增加 2 次，避免仍按普通伤害只记 1 次。玩家攻击路径同时修正独立昏迷目标的自动暴击标记，不再依赖
  优势来源列表才能保留该规则。
- 核心 DM API 接收的是 DM 已填的最终伤害总值，不是未掷的伤害骰表达式，因此不会擅自把最终伤害翻倍；
  结果已明确标记自动暴击，实际暴击伤害骰仍由玩家/DM 按动作 UI 提交。
- 回归：新增 DM 权威网格昏迷目标验收和玩家攻击条件单测；后端全量 `464 passed`，Ruff、
  `git diff --check` 通过，仅有既存 Starlette/httpx 弃用警告。本轮仅后端逻辑/测试变更，未重复浏览器验收。
- 当前工作树仍只有用户原有未跟踪 `backend/tests/integrations/`、`backend/tests/ollama.py`，未纳入提交。
- 仍未完成：自动暴击的伤害骰表达式自动翻倍、复杂状态组合其他例外、完整三维遮挡、完整反应/传奇/巢穴
  自动触发矩阵和所有职业/子职业 1–20 级运行时。

# 2026-08-04 失能状态立即结束闪避

- 修复状态组合缺口：单位在“闪避”后获得失能、震慑、麻痹、石化或昏迷时，闪避运行时效果会在同一状态事务
  中结束，不会继续给攻击者错误的劣势；攻击上下文也会对旧残留状态 fail-closed，不消费失效闪避效果。
- 直接 DM 条件编辑和结构化状态结果共用 `_end_predicated_effects` 清理路径；结束记录保留
  `end_reason=闪避因失能结束`，已有的闪避回合边界结束逻辑不变。
- 新增回归 `test_incapacitation_ends_dodge_before_the_next_attack`：失能后闪避效果为 ended，下一次攻击无需
  提供闪避裁定且日志不含 `target_dodging`。
- 验证：后端全量 `462 passed`，Ruff、`git diff --check` 通过；仅有既存 Starlette/httpx 弃用警告。
  本轮只有后端变更，未重复前端构建或浏览器验收。用户原有未跟踪 `backend/tests/integrations/`、
  `backend/tests/ollama.py` 未纳入提交。
- 仍未完成：复杂状态组合的其他例外、复杂三维遮挡、完整反应/传奇/巢穴自动触发矩阵和所有职业/子职业
  1–20 级运行时。

# 2026-08-04 结构化失能立即中断专注（本轮）

- 修复状态生命周期缺口：伤害导致失能/昏迷之外，结构化状态结果直接施加震慑、麻痹、石化或昏迷时，
  现在也会在同一事务中结束该单位拥有的全部专注效果，并清理关联召唤物/结构化效果；不再等到下一回合
  或下一次伤害才清理。
- 共用 `_end_lifecycles_after_condition_change()` 和现有生命周期谓词入口，覆盖结构化豁免结果、
  结构化怪物区域动作以及 DM 确认的规则效果；重复施加已存在状态不会误触发中断。专注来源判断统一使用
  失能条件集合，而不是只检查昏迷。
- 新增回归 `test_structured_incapacitation_ends_concentration_immediately`：专注施法者获得震慑后，
  专注效果即时变为 `ended`、专注字段清空、关联中毒状态回滚，审计结果保留结束效果 ID。
- 验证：后端全量 `461 passed`，Ruff 和 `git diff --check` 通过；仅有既存 Starlette/httpx 弃用警告。
  本轮没有前端源码变更，因此未重复前端构建或浏览器验收。
- 边界：完整状态组合/例外仍未全部完成；复杂三维遮挡、完整反应/传奇/巢穴自动触发矩阵和所有职业/子职业
  1–20 级运行时仍需继续推进。用户原有未跟踪 `backend/tests/integrations/`、`backend/tests/ollama.py`
  未纳入提交。

# Codex 交接：玩家入口、Scene 同步、装备预览与休息申请

更新时间：2026-08-04（Asia/Shanghai）

## 2026-08-04 条件入口统一接入行动与移动限制

- 修复职业特性 `activate_condition` 和怪物回合开始条件特性绕过限制层的问题：条件现在会
  真实改变 `action_available`、`bonus_action_available`、`reaction_available` 和速度，而不是
  只写入显示用条件列表；怪物特性也遵守状态免疫。
- 统一区分 D&D 规则：失能只能阻止行动但保留速度；昏迷、震慑、麻痹、石化、束缚/擒抱会
  将速度与剩余移动归零。直接 DM 条件编辑、职业特性和怪物特性共用同一限制层。
- 新增回归：职业特性施加震慑后行动/反应/速度均受限；怪物回合开始施加震慑后同样受限；
  直接条件编辑矩阵覆盖失能与速度归零状态。
- 验证：后端 `backend/tests` 全量通过，Ruff 与 `git diff --check` 通过；本项只有后端变更，
  未重复前端构建和浏览器验收。复杂状态的组合例外、三维遮挡和全职业/子职业 1–20 级运行时
  仍未全部完成。

## 2026-08-04 复杂状态组合来源独立回滚

- 修复结构化效果叠加时的共通根因：AC/速度 modifier、抗性/易伤/免疫和
  `rule_modifiers` 不再用单一效果的旧快照互相覆盖。每个效果保存内部实例顺序和
  独立 modifier key；结束任一来源时，从最早基线重放仍 active 的来源，结束顺序不再影响结果。
- 速度效果回滚保留当前已消耗的移动力，并将剩余移动限制到恢复后的速度；持续规则 tick
  会同步更新仍在场效果的基线，避免已结束来源在下一回合被重新叠回。
- 新增回归 `test_compiled_state_sources_stack_and_end_independently`：两层 AC、两层同类抗性
  和两个同形状规则 modifier 分别结束，验证另一来源与角色原有抗性均保留。
- 验证：后端 `backend/tests` 全量通过；新增定向与既有持续状态测试通过；Ruff、
  `git diff --check`、前端 TypeScript、ESLint、39 文件/196 项 Vitest、生产构建通过。
- 本项没有修改火球术、雷鸣波、复合伤害、召唤生命周期或浏览器 UI；本轮未进行内置浏览器
  实战验收，因为没有前端行为变更。复杂状态的跨规则例外、完整三维遮挡和全职业/子职业
  1–20 级运行时仍未全部完成。

## 2026-08-04 魅惑有害效果统一门禁

- 将“魅惑单位不能伤害、施加状态或强制移动魅惑来源”提取为
  `CombatEngineService._validate_charmed_harm_targets()`，接入普通伤害/攻击、玩家单目标与批量豁免
  prompt、prompt 确认、结构化多目标动作和怪物区域动作；不再只保护普通攻击路径。
- 魅惑来源缺失时 fail-closed，返回需要 DM 裁定；DM 可提交带理由的 `dm_override`。新增的
  prompt/区域命令字段均为可选，兼容原有请求。
- 回归覆盖：非攻击伤害拦截、DM override 实际扣血、来源缺失拒绝、豁免型玩家 prompt 拦截。
- 验证：后端全量测试通过，新增定向测试 2/2；Ruff、`git diff --check`、前端 TypeScript、ESLint、
  39 文件/196 项 Vitest、生产构建通过。Shell 访问 5173 返回 200；内置浏览器尝试刷新时被当前
  浏览器 URL 安全策略拦截，未将此项冒充为浏览器验收通过。
- 本项没有重做火球术、雷鸣波、复合伤害、召唤物或既有反应链；复杂状态组合、完整三维遮挡和
  全职业/子职业 1–20 级运行时仍未完成。

## 2026-08-04 恐慌状态覆盖怪物 AI 移动（本项最新）

- 把“恐慌状态不能主动靠近结构化恐慌来源”的距离判定提取为
  `CombatEngineService._validate_frightened_movement()`，玩家移动和怪物 AI
  `move_monster()` 共用同一入口，避免 AI 绕过状态规则。
- 只有目标位置比起点更接近来源时拒绝；远离或保持距离允许。来源、战斗场景或权威
  `SceneGrid` 缺失时 fail-closed，返回“需要 DM 裁定”，不使用自由快照或默认网格猜距离。
- 新增回归覆盖：怪物靠近被拒、远离成功并更新网格位置；缺少权威场景时拒绝。
- 验证：当前副本后端全量 `456 passed`；定向恐慌/移动测试通过；Ruff、`git diff --check`、
  TypeScript、ESLint、前端 `39 files / 196 tests`、生产构建全部通过。
- 内置浏览器刷新现有模拟战斗 DM/玩家页面：两端正常显示当前战斗、共享地图和 AI 当前行动；
  新增控制台 `error/warn` 均为空。截图：
  `/private/tmp/dnd-frightened-ai-movement-dm-20260804.png`、
  `/private/tmp/dnd-frightened-ai-movement-player-20260804.png`。
- 本项不改变火球术、雷鸣波、复合伤害、召唤物生命周期或既有反应执行链；复杂状态组合
  仍有其他未覆盖的规则例外，完整三维遮挡和全职业/子职业 1–20 级运行时仍未完成。

## 2026-08-04 结构化反应窗口真实执行闭环（最新）

- 上一项“进入近战威胁范围”不再只是提示窗口。`CombatActionCommand` 新增
  `reaction_window_id`；确认时服务端校验窗口仍为 eligible、反应者、结构化事件、
  动作名和触发目标完全一致，确认后执行一次普通攻击结算，并将窗口标为 `resolved`
  （记录 `resolved_action_id`），从而阻止同一事件重复消耗反应。
- DM 高级动作面板读取公开战斗日志中的 eligible window：自动带入结构化事件和触发文本、
  锁定事件触发单位为目标、提交窗口 ID；DM 仍必须填写实际攻击总值。真实伤害、抗性/易伤/免疫、
  HP 和反应资源仍统一走已有 CombatEngine，不另造结算路径。
- 新增回归覆盖：进入范围窗口确认后 HP 20→13、反应变为不可用、窗口变为 resolved，
  重复使用同一窗口被拒绝；前端覆盖窗口自动目标、事件和 `reaction_window_id` 载荷。
- 全量门禁：后端 `453 passed`（仅既有 Starlette/httpx 弃用警告）；前端 39 文件/196 项；
  TypeScript、ESLint、生产构建、Ruff、`git diff --check` 全通过。
- 内置浏览器实战：模拟战斗中熔火术士对进入范围的模拟玩家执行“借机熔击”，DM/玩家两端
  日志一致，玩家 HP `28→18`，反应资源已用，控制台 error/warn 均为空。截图：
  `/private/tmp/dnd-reaction-execution-dm-20260804.png`、
  `/private/tmp/dnd-reaction-execution-player-20260804.png`。
- 本项没有改变火球术、雷鸣波、复合伤害、召唤物生命周期或基础怪物 AI。仍未完成：
  反应事件的全矩阵自动发现、复杂状态组合、复杂三维遮挡和全职业/子职业 1–20 级运行时。

## 2026-08-04 进入近战威胁范围反应窗口与全量门禁（最新）

- 新增共享 `_persist_eligible_enters_reach_reaction_windows`，统一接入玩家移动、怪物 AI 移动和结构化强制位移；只有快照明确声明 `action_type=reaction`、`reaction_event=enters_reach` 的近战反应，且移动前在范围外、移动后进入范围时才开放窗口。
- 窗口记录触发单位、前后坐标、反应名称、反应距离、资料库触发文本和稳定幂等键；反应已用、单位同阵营、目标死亡、远程/区域反应、重复进入或已有未处理窗口时不会重复生成。
- 该项只记录合法触发时机，不自动掷攻击/伤害骰、不自动选择目标、不消耗反应；DM 仍通过现有高级动作确认链填写实际事件、目标和骰值。
- 修复同一事务内伤害 action 与 `takes_damage` 窗口的 SQLite 秒级时间排序：窗口的审计时间明确晚于原伤害 action，避免日志列表随机把窗口排在伤害之前。
- 回归覆盖玩家进入范围、怪物移动进入范围、强制位移进入范围、重复离开再进入幂等、已有窗口不重复和受伤反应审计顺序。
- 门禁：后端 `452 passed`（1 个既有 Starlette/httpx 弃用警告）；前端 39 文件/195 项；TypeScript、ESLint、生产构建、Ruff、`git diff --check` 均通过。
- 内置浏览器干净 DM/玩家页面实际验证：玩家从 `(6,2)` 移到 `(6,3)` 后，两端均显示“熔火术士·AI：进入近战威胁范围反应窗口已开放（模拟玩家·奥术师进入；等待 DM 确认）”；两端控制台 error/warn 均为空。截图：`/private/tmp/dnd-enters-reach-reaction-dm-clean-20260804.png`、`/private/tmp/dnd-enters-reach-reaction-player-clean-20260804.png`。
- 当前工作树另有用户原有未跟踪目录 `backend/tests/integrations/`、`backend/tests/ollama.py`，未纳入本项提交。
- 仍未完成：反应窗口自动目标/骰值/执行、复杂状态组合、完整三维遮挡、所有职业/子职业 1–20 级运行时；复杂高级动作的真实触发仍需 DM 确认。

## 2026-08-04 施法事件结构化反应自动开窗（最新）

- 普通施法结算、怪物区域施法和需要玩家豁免的施法 prompt，在施法 action/prompt 建立后统一检查其他存活怪物快照中明确声明的 `reaction_event=casts_spell` 反应。
- 施法必须与快照中明确的 `spellcasting`、法术环级、法术位资源或 `is_spell` 动作匹配；普通攻击或自由文本不会猜成法术。施法者自身不会给自己开反应窗口，反应已用或未结构化时不提示。
- 窗口记录施法 action、施法者、法术名、可用反应动作和资料库触发文本，稳定幂等；仍只记录合法触发时机，不自动反制、不自动选择目标、不掷骰或消耗反应。
- 新增回归覆盖怪物施法等待玩家豁免、区域施法与既有受伤窗口并存；后端全量、Ruff、前端 39 文件/195 项、TypeScript、ESLint、生产构建和 `git diff --check` 通过。
- 内置浏览器实际刷新 DM `/#/combat` 与玩家模拟房间 `/#/player?simulation_join_code=D6A76S...`，两端战斗快照/先攻/地图正常，控制台 error/warn 均为空。截图：`/private/tmp/dnd-casts-spell-reaction-dm-20260804.jpg`、`/private/tmp/dnd-casts-spell-reaction-player-20260804.jpg`。
- 仍未完成：进入范围等其他反应事件自动开窗、反应的自动目标/骰值/执行、复杂状态组合、三维遮挡和全职业 1–20 级运行时。

## 2026-08-04 受伤事件结构化反应自动开窗（最新）

- 普通/玩家伤害、怪物区域伤害和持续效果 tick 在正式伤害 action 落库、逐段防御结算和 HP 更新后，统一检查受伤怪物快照中明确声明的 `reaction_event=takes_damage` 反应。
- 只有实际扣除伤害大于 0、怪物仍存活且反应资源可用时才写入 `eligible_action_window`；没有结构化事件、目标死亡或反应已用不会伪造窗口。
- 复合多段伤害按一次伤害事件、每个受伤怪物最多一个窗口，不会按火焰/力场等每段重复开窗。窗口保留受伤单位、伤害来源、原伤害 action、实际伤害、动作名称和资料库触发文本，并使用稳定幂等键。
- 这一步仍只记录“可以触发”：不会自动选目标、掷攻击/伤害骰、执行反应或消耗反应；DM 继续使用现有高级动作确认链。
- 新增回归覆盖普通复合伤害、怪物区域伤害、持续伤害 tick，并验证重复请求不重复窗口。后端全量、Ruff、前端 39 文件/195 项、TypeScript、ESLint、生产构建和 `git diff --check` 通过。
- 内置浏览器实际刷新 DM `/#/combat` 与玩家模拟房间 `/#/player?simulation_join_code=D6A76S...`，两端页面/战斗快照正常，控制台 error/warn 均为空。截图：`/private/tmp/dnd-takes-damage-reaction-dm-20260804.jpg`、`/private/tmp/dnd-takes-damage-reaction-player-20260804.jpg`。
- 仍未完成：施法、进入范围等其他反应事件的自动开窗矩阵，反应的自动目标/骰值/执行，复杂状态组合、三维遮挡和全职业 1–20 级运行时。

## 2026-08-04 高级怪物动作窗口时机记录（最新）

- 怪物快照中明确结构化的 `legendary_action` / `lair_action` 现在由回合推进器记录为 `eligible_action_window` 战斗事件：其他单位回合结束后开放传奇动作；进入先攻 20 窗口时开放巢穴动作。
- 这一步只记录合法触发时机、动作名称、窗口、触发单位和剩余资源，不会自动掷攻击骰、伤害骰或执行动作；DM 继续通过现有高级动作面板确认目标、骰值和执行。怪物自己的回合结束不会错误开放自己的传奇动作，传奇资源耗尽也不会继续提示可用。
- 事件带幂等键，重复推进不会重复写窗口；现有前端已消费相同快照并显示“怪物高级动作窗口 · 需要 DM 确认”，没有另造一套前端状态。
- 新增后端回归 `test_advanced_action_windows_are_persisted_only_at_legal_turn_boundaries`，覆盖巢穴先攻20、怪物自身回合不触发、其他单位回合触发和重复请求幂等。
- 浏览器实际刷新 DM `/#/combat` 与玩家 `/#/player?simulation_join_code=D6A76S...`：DM 显示“传奇熔击 · 可用”和“地火喷涌 · 可用”，并明确显示“需要 DM 确认”；玩家端先攻/当前行动/地图公开快照正常。两端新增控制台 `error/warn` 均为空。
- 截图：`/private/tmp/dnd-advanced-action-window-dm-20260804.png`、`/private/tmp/dnd-advanced-action-window-player-20260804.png`。
- 本项不重做已经完成的火球术、雷鸣波、复合伤害、召唤物生命周期、多重攻击暂停恢复或结构化反应事件；高级动作的真实执行仍需 DM 确认，复杂触发矩阵、复杂状态组合、三维遮挡和全职业 1–20 级运行时仍未全部完成。

## 2026-08-04 回合结束反应自动开窗（最新）

- 结构化怪物反应现在在回合边界也进入正式可审计窗口：当其他单位回合结束，且怪物快照明确声明 `reaction_event=turn_end`、反应资源可用时，回合推进器写入 `eligible_action_window`。
- 窗口保留反应动作名、结构化事件、触发单位、触发单位名称和资料库触发文本；怪物自己的回合结束不会给自己开窗，重复推进不会重复写入。
- 这一步只记录“可以触发”，不自动选择目标、不自动掷攻击/伤害骰、不消耗反应；DM 继续使用现有高级动作确认链提交实际触发、目标和骰值。借机攻击的离开范围移动链不在本项重做范围内。
- 新增回归 `test_structured_turn_end_reaction_window_excludes_reaction_owner_turn`；后端全量 `447 passed`，前端 39 文件/195 项，TypeScript、ESLint、生产构建、Ruff、`git diff --check` 通过。严格 mypy 仍有仓库既有类型错误，本项新增的窗口代码未再增加对应位置的错误。
- 浏览器刷新 DM `/#/combat` 与玩家 `/#/player?simulation_join_code=D6A76S...`：DM 高级动作窗口、传奇/巢穴选项和玩家端先攻/地图/公开快照正常；两端新增控制台 `error/warn` 均为空。
- 截图：`/private/tmp/dnd-turn-end-reaction-window-dm-20260804.png`、`/private/tmp/dnd-turn-end-reaction-window-player-20260804.png`。
- 仍未完成：受到伤害、施法、进入范围等反应事件的自动开窗矩阵，以及复杂状态组合、三维遮挡和全职业 1–20 级运行时；不把本项的回合结束事件支持说成全部反应自动化。

## 2026-08-04 多重攻击逐击暂停与恢复（最新）

- 怪物多重攻击现在按绝对 `sequence_step` 写入；前一步只是 `previewed`（通常是等待玩家豁免）时，服务端拒绝后续击次，返回“previous player roll is confirmed”，不会提前扣血、消耗后续资源或推进回合。
- 怪物动作执行器遇到豁免型子动作会在当前击次停下，不再预先提交后续击次。玩家/DM 确认豁免后，前端从同一 `sequence_id` 的下一步恢复，后续击次使用 `action_cost=none`，最后一击才允许结束怪物回合；已确认击次不会重复执行。
- 新增后端回归 `test_multiattack_pauses_before_next_step_until_player_roll_is_confirmed`，覆盖“首击豁免 → 后续击次被拒绝 → 确认后继续 → HP 20→15”。
- 当前门禁：后端 `445 passed`（仅既有 Starlette/httpx 弃用警告）；前端 `39 files / 195 tests`；TypeScript、ESLint、生产构建、Ruff、`git diff --check` 全通过。
- 内置浏览器干净页面实际刷新 DM `/#/combat` 与玩家 `/#/player?simulation_join_code=D6A76S...`：两端加载正常，新的控制台 error/warn 均为空。当前模拟剧本没有普通多重攻击模板，只有传奇/巢穴/反应窗口，所以多重攻击 UI 的逐击暂停由 API/组件回归覆盖，不把当前页面冒充成多重攻击实战。
- 截图：`/private/tmp/dnd-multiattack-stability-dm-20260804.png`、`/private/tmp/dnd-multiattack-stability-player-20260804.png`。
- 本项不重做火球术、雷鸣波、基础复合伤害和召唤物生命周期；复杂多段/复合伤害、完整状态组合、三维遮挡、传奇/巢穴/反应自动触发矩阵和全职业 1–20 级运行时仍按既有边界处理。

## 2026-08-04 状态别名与来源生命周期收口（最新）

- 结构化状态积木现在通过统一规范名写入和移除状态。中文资料的“中毒”和英文积木的 `poisoned` 会共用同一个状态，不再产生两条重复状态记录。
- 结束结构化状态来源时，会保留 DM/角色原本已经存在的同一状态；只有最后一个结构化来源结束且状态不是外部已有时，才会移除状态。移除型状态积木也按规范名处理别名。
- 新增回归：预先存在“中毒”时再次施加 `poisoned` 不重复，结束该效果不删除原状态。
- 后端全量 `445 passed`（1 个既存 Starlette/httpx 弃用警告），定向状态测试、Ruff、`git diff --check` 全通过。
- 本项是复杂状态生命周期的一个收口，不代表所有状态组合、三维遮挡、怪物高级动作和职业 1–20 级运行时已经全部自动化。

## 2026-08-04 专注来源失活/死亡时即时清理召唤物（最新）

- 专注召唤生命周期现在明确监听 `source_unconscious`、`source_dead`、`source_inactive`。来源单位受到伤害降至 0 HP 时，在同一战斗事务中结束其全部专注效果并让关联召唤物立即离场，不再等到下一回合或下一次推进。
- 多个共享生命周期召唤物会整组清理；召唤物从 DM/玩家先攻投影中移除后，先攻游标会自动落到仍然有效的单位。
- DM 通过直接战斗单位编辑器把来源改成昏迷、死亡或失活时，也复用同一生命周期清理路径；来源清空专注字段，不会错误生成专注豁免请求。
- 新增回归覆盖：伤害归零清理多个专注召唤物、直接编辑来源状态即时清理、专注状态清空、先攻游标合法性和无专注提示。
- 浏览器已在真实 DM/玩家模拟战斗中验收：来源 HP `28 → 0` 后，两个召唤物从两端先攻轨道消失，来源显示昏迷，专注状态为空，`concentration_prompts: []`；两端控制台 error/warn 均为空。
- 浏览器截图：`/private/tmp/dnd-summon-lifecycle-final-dm-20260804.png`、`/private/tmp/dnd-summon-lifecycle-final-player-20260804.png`；修复前对照：`/private/tmp/dnd-summon-lifecycle-before-dm-20260804.png`、`/private/tmp/dnd-summon-lifecycle-before-player-20260804.png`。
- 最新门禁：后端 `444 passed`（1 个既存弃用警告）；前端 39 文件/195 tests、TypeScript、ESLint、生产构建、Ruff、`git diff --check` 全通过。
- 本项只收口“专注来源生命周期 → 召唤物清理”，不改变已经完成的火球术、雷鸣波、复合伤害、基础怪物 AI 和敌方召唤物 AI 边界。

## 2026-08-03 结构化反应事件执行校验（最新）

- 结构化反应事件已从“预览筛选”接入正式确认/执行链。`CombatActionCommand`、玩家豁免 prompt（含批量 prompt）和怪物区域动作都接受 `reaction_event`；非反应动作携带该字段会被拒绝。
- 服务端会按怪物快照中的 `action_name` 精确查找结构化 `reaction_event`。资料动作明确写出事件时，缺失事件或事件不匹配会在消耗反应、写入伤害和创建玩家豁免请求前拒绝；旧的未结构化动作继续兼容 DM 自由触发文字。
- action window 的 request/result/log 都保留 `reaction_event` 与 `reaction_trigger`。DM 高级动作面板会把选择器值传给直接攻击、单目标豁免和多目标豁免路径；后续玩家端日志可见同一结构化事件。
- 新增回归覆盖：匹配成功、缺失/错误事件不扣资源不写伤害、结构化 prompt 解析后仍保留事件、前端高级动作载荷包含事件。
- 浏览器真实验收：重启当前运行副本 8000 后，模拟剧本 DM 选择“离开近战威胁范围”、填写目标/攻击总值并执行；DM 与玩家公开日志都显示“反应触发……；结构化事件：离开近战威胁范围”，两端控制台 error/warn 均为空。
- 截图：`/private/tmp/dnd-reaction-structured-dm-log-20260803.png`、`/private/tmp/dnd-reaction-structured-player-log-20260803.png`；顶部页面截图：`/private/tmp/dnd-reaction-structured-dm-20260803.png`、`/private/tmp/dnd-reaction-structured-player-20260803.png`。
- 门禁：仓库根目录 `backend/.venv/bin/python -m pytest -ra backend/tests` 为 `437 passed`（1 个既有 Starlette/httpx 弃用警告）；Ruff、前端 TypeScript、ESLint、Vitest 39 文件/190 项、生产构建、`git diff --check` 全部通过。
- 代码提交：`2c0185a feat: enforce structured reaction events`。本项不改变火球术、雷鸣波、召唤物或复合伤害的既有完成边界。

边界：结构化事件现在会阻止错误事件被执行，但“何时发生事件”仍由 DM/游戏流程确认；DM 仍需确认真实触发、目标、攻击骰和伤害骰。全部反应/传奇/巢穴动作的自动触发矩阵、复杂状态组合、复杂三维遮挡和全职业 1–20 级运行时仍未全部完成。

## 2026-08-03 结构化怪物反应事件与模拟剧本兼容迁移（最新）

- 怪物资料解析现在只把明确写出的反应触发映射为关闭词表：离开近战范围 `leaves_reach`、进入近战范围 `enters_reach`、受到伤害 `takes_damage`、施法 `casts_spell`、回合结束 `turn_end`；没有明确事件的反应不会被猜测。
- `monster-ai/preview` 的 reaction 窗口接收结构化事件并过滤动作；DM 高级动作面板增加事件选择器和实际触发文本。模拟剧本的旧持久化反应动作如果已有明确文字触发，会在“重新载入剧本”时幂等迁移为结构化事件。
- 回归覆盖资料解析、事件筛选、API 预览、旧模拟动作迁移；代码与测试提交为 `4546b9f`。无关未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 保留未动。
- 浏览器实际验收：DM 选择“离开近战威胁范围”、填写实际触发和目标后，后端返回“借机熔击 · reaction”；玩家端加入同一模拟房间并显示相同先攻、地图和日志。DM/玩家控制台 error/warn 均为空。
- 截图：`/private/tmp/dnd-reaction-event-dm-current-20260803.png`、`/private/tmp/dnd-reaction-event-player-current-20260803.png`。
- 门禁：后端全量 `436 passed`（1 个既有 Starlette/httpx 弃用警告）、Ruff、前端 TypeScript、ESLint、Vitest 39 文件/190 项、生产构建、`git diff --check` 全部通过。

边界：本项完成的是“明确反应事件 → 可审计预览筛选 → 模拟旧数据迁移”。DM 仍需确认真实触发、目标、攻击骰和伤害骰；所有反应/传奇/巢穴动作的自动触发矩阵、复杂状态组合、复杂三维遮挡和全职业 1–20 级运行时仍未全部完成。

## 2026-08-03 复杂多段/复合伤害闭环（当前最新）

- 复合伤害现在必须显式提供逐段 `damage_components`；每段保留 `damage_type`、`damage_tags`、原始骰值和防御后结果。编译器、API schema、DM/玩家战斗提交路径都会拒绝把 `mixed/复合/多种` 当成具体伤害类型，也不会从总值猜分配。
- 战斗引擎按单次伤害事件逐段结算抗性、易伤、免疫、临时生命和条件性防御，再一次性写入 HP/专注/归零生命周期；不会因为一个复合技能有两段伤害而重复触发死亡豁免、专注中断或召唤物离场。
- 玩家房间公开日志保留逐段伤害、逐目标伤害和 `damage_tags`。DM/玩家界面显示“原始值→防御后值；合计”，并把摘要中的“实际扣除”和“原始报告”分开，避免把骰出的 13 点误读成 HP 实际扣除 9 点。
- 模拟剧本新增“元素裂解”（2d6 火焰 + 1d6 力场、2 环、60 尺），通过正式 Combat/PlayerRoom 接口验证：火焰 8 受抗性减半为 4，力场 5 保持 5，目标 HP 30→21；DM 和玩家端都看到相同逐段日志。
- 浏览器验收截图：`/private/tmp/dnd-compound-damage-dm-20260803.png`、`/private/tmp/dnd-compound-damage-player-20260803.png`；两端控制台 error/warn 均为 0。
- 当前门禁：后端全量 pytest 通过，Ruff、前端 TypeScript、ESLint、Vitest 39 文件/190 项、生产构建、`git diff --check` 通过。无关未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 保留未动。

边界：这次完成的是“明确逐段输入 → 逐类型防御 → 单事件写入 → 双端可审计显示”。复杂多段法术仍需要玩家/DM 提供攻击骰、各段伤害骰、目标和必要的 DM 裁定；复杂状态组合、三维遮挡、完整传奇/巢穴/反应触发矩阵和所有职业 1–20 级运行时不属于本次完成范围。

## 2026-08-01 核心规则执行波（当前最新）

这次用户要求执行的是“不含扩展包”的核心缺口。本波已经把若干原来只有字段/文字的内容接入真实运行时，并完成前后端门禁；扩展资料书继续保持独立开关，不混入核心完成率。

- 战斗动作：闪避、协助、准备、搜索、隐藏、撤离，以及使用物品、物件互动已进入战斗确认路径。它们会消费动作/反应/移动经济，校验状态和版本；使用物品会校验绑定角色拥有权并减少数量，物件互动会校验 `SceneObject` 版本并写回状态。擒抱/推撞仍要求 DM 给出明确结果，不猜检定或体型。
- 状态：倒地攻击优势/劣势、失能类动作限制、起身半速、回合末保存/清理、准备动作触发、专注中断、死亡豁免与稳定/濒死联动已有回归测试。掩体/视线的完整几何和全部官方状态持续条件仍未冒充完成。
- 法术：多目标/区域执行现在按 `target_ids` 逐目标处理豁免、半伤/无伤、友军/敌军关系、混合结果和实际 HP/状态事务；没有可靠几何或复杂分支时仍返回 DM 裁定，不默认 5 尺、1d6 或自动成功。传送、变形、创造物、反制/驱散等复杂法术仍是后续缺口。
- 怪物：资料解析保留动作类型、充能区间、多重攻击次数和传奇动作消耗；既有“怪物全自动”回合链仍负责选目标、寻路、攻击、结束回合，并在玩家豁免/检定时暂停队列、等待玩家端输入后恢复；`monster-ai/preview` 是额外的 DM 可审计预览，不替代这条运行链。本轮补上充能动作运行时门禁：初次充能可用，确认使用后服务端写入不可用；未重新掷充能骰时自动选择和预览都会跳过，豁免型充能动作在生成玩家请求时同样消耗。多重攻击拆分、传奇/巢穴动作、怪物反应和复杂 AI 策略仍未全部接入。
- 探索/社交：社交预览/确认会真实写入 NPC 态度与记忆，并推进世界时钟；旅行预览/确认现在会写入 TravelLeg、可见性受控的遭遇事件、当前位置和世界时钟，并支持幂等重放。Scene 页已增加可选遭遇标题、结果摘要和结果类型输入。追逐、陷阱、毒病感染、Downtime、士气/投降、环境危害仍未完成。
- 核心 1–20：升级确认新增了兼职开关与属性前置、专长前置、HP 成长、法师学法/准备法术约束、法术环级限制、职业选项数量和资源池更新，并沿用角色版本 CAS/幂等。全部职业特性效果的逐项运行时实现，以及 DM 修改和玩家创建完全共用同一入口，仍需继续收口。

本波已验证：后端 `backend/tests` 全量通过，Ruff 与 `git diff --check` 通过；前端 `npm run typecheck`、`npm run lint`、Vitest 36 文件/157 项、`npm run build` 通过。内置浏览器实际打开战斗页，看到“怪物全自动：关”入口且控制台错误为 0；运行副本的 8000 端口由本轮最新后端 PID 7852 提供服务。

当前不要把 `424 exact / 40 partial / 289 manual` 或任何 `exact` 统计当作“所有法术自动完成”；它只代表规则计划字段完整度。真正完成必须有确认接口、状态改变和回归测试。

## 2026-08-01 中断恢复后的最终核对（当前事实）

- 当前工作树已按最新源码重新通过前后端门禁：后端 `backend/tests` 全量通过；Ruff、`git diff --check` 通过；前端 `npm run typecheck`、`npm run lint`、`npm run test -- --run`（36 个文件 / 160 项）和 `npm run build` 通过。
- 从本地资料库重新统计后，753 条核心法术的规则计划是 `475 exact / 38 partial / 240 manual`。这只是“编译计划完整度”，不等于 475 条法术可以不问玩家/DM 自动完成；玩家给出的攻击骰、伤害骰、豁免结果和复杂分支仍是输入边界。
- 传送、变形、创造物、驱散现在有真正的规则积木和服务端执行入口：玩家明确提交目的地、形态/模板、数量/位置或效果 ID 后，服务端校验当前战斗/地图/目标并写入位置、战斗效果或 Scene/World 对象；缺少选择会拒绝，不使用默认 5 尺、1d6 或自动目标。玩家特殊法术现在统一走施法接口，不会误走普通攻击接口。
- 召唤物仍是实际 `Combatant(entity_type="companion")`，支持独立/共享先攻、数量、玩家控制边界、专注/持续时间离场、HP 归零离场、DM/玩家结束召唤和幂等。法师之手/隐形仆役等 `enters_combat=false` 效果只写非战斗积木，不凭空创建战斗单位；只有绑定完整伙伴模板的召唤才会加入先攻并可被玩家控制。
- 最新后端已重启在 `127.0.0.1:8000`，Vite 在 `127.0.0.1:5173`。内置浏览器实际检查 `http://127.0.0.1:5173/#/combat` 和 `http://127.0.0.1:5173/#/player`：DM 页显示现有战斗/法术积木和召唤模板空状态；玩家页显示“加入跑团房间”；两页控制台均无 error/warn。当前 SQLite 没有可绑定玩家房间，所以没有伪造“玩家已在战斗中”的截图。
- 未完成边界保持诚实：`RepeatBlock` 的所有状态/修正尚未全部接入回合 tick；多段/复合伤害、完整多目标区域、复杂状态生命周期、更多怪物动作和所有职业特性仍需继续扩展。不要把本交接文件里更早的 424/40/289 或 347/49/357 历史数字当成当前覆盖率。

## 2026-08-01 扩展内容包与核心战斗动作收口（最新）

本轮已把“资料库 → 可选内容包 → 资料/角色/玩家检索”接通，并完成一组核心战斗运行时：

- 新增六本本地资料书内容包：珊娜萨、塔莎、多元宇宙怪物、费资本、毕格比、万象无常书。开团页面可以逐本勾选，保存到 `campaign.enabled_content_packs`；未勾选的资料书不会进入该团的图鉴、玩家规则搜索或角色法术选项。
- 能安全识别的扩展法术、完整怪物属性块和魔法物品已进入原子图鉴，并沿用现有规则积木编译器；目录页、叙事页和职业/子职业未规范化页不会冒充完整自动规则。当前本地统计：珊娜萨 149、塔莎 57、多元宇宙怪物 249、费资本 16、毕格比 74、万象无常书 58 条可检索内容；其中待标准化内容会在管理页单独计数。
- 新增 `enabled_content_packs` 数据库迁移 `e3c6a8f2b917`。应用实际使用的根目录 `.env` 对应 `data/dnd_dm.db` 已迁移到 head；此前误迁到 `backend/data` 的副本不作为运行库。
- 核心战斗新增真实执行的疾走、起身、擒抱、推撞：会消耗动作/速度、更新倒地/擒抱状态、速度和网格位置；擒抱/推撞必须有 DM 明确结果，未提供数据时不猜体型、距离或检定。
- 非战斗检定确认会校验计划保存的角色版本；角色或熟练信息改变后，旧检定转为 `stale`，不会消耗资源或写入成功事件。

验证：后端全量测试、Ruff、`git diff --check` 通过；前端 TypeScript、ESLint、Vitest 36 文件/156 项、生产构建通过。重启项目根目录运行副本后，内置浏览器实际看到管理页六本资料书及数量，`/#/player` 显示“加入跑团房间”，控制台错误为 0。

前一阶段边界（已由后续核心规则执行波部分推进）：扩展职业/子职业仍只是带来源的待标准化资料，完整高等级车卡/升级路径和敌方召唤 AI 仍未完成；临时生命值已能在法术元数据中识别为 `HealBlock.temporary_hp=true`，但玩家友方施法的临时生命实际写入仍需单独接入战斗结算。

## 2026-08-01 本轮分类执行收口（最新）

本轮按用户指定的两类完成了“可安全自动化”的闭环：

- 战斗法术：`modifier`、`defense`、`condition`、`heal`、`repeat` 和 `move` 等积木不再只是展示。接受动作后，服务端会写入 `CombatEffect`，实际改变 AC/速度/优势劣势/抗性/免疫/状态/资源，并由回合推进器处理明确的持续伤害/治疗；雷鸣波已验证“豁免失败 → 伤害 → 推离 10 尺”。
- 玩家友方施法：新增 `/api/v1/player-room/me/combat/cast`，玩家可以选择自身或友方单位施放结构化治疗、增益、抗性和状态效果；服务端校验目标阵营、距离、当前回合、动作/反应经济、法术环阶和法术位，前端新增对应的友方目标与治疗提示。
- PR/探索法术：光亮/黑暗/侦测魔法/寻找陷阱/定位/开锁/闭锁/修复/通晓语言/传讯/动物沟通/物资类已继续沿用 DM 确认后执行的结构化路径；复杂传送、创造、变形、反制和多分支仍明确留给 DM。
- 重复效果统计已同步：明确的回合开始/结束伤害或治疗已经接入执行器，不再被旧 warning 误报；重复状态/修正等尚未支持逐次 tick 的计划仍保留未决原因。

最新本地官方法术基线仍为 753 条：`424 exact / 40 partial / 289 manual`。这是编译器计划覆盖率，不是“无需玩家掷骰”的数量；其中 292 条含必须 DM 裁定的文字效果，42 条重复计划仍含未接入回合执行器的效果，8 条伤害字段不安全，1 条升环基础环阶不足。

本轮验证：后端 `backend/tests` 全量通过；前端 TypeScript、ESLint、Vitest 156 项、生产构建通过；Ruff 与 `git diff --check` 通过。内置浏览器刷新 `5173/#/combat` 和 `5173/#/player` 均可加载，玩家页不再把 Vite HTML 当 JSON，控制台错误为 0。当前 SQLite 没有战役，因此没有伪造真实战斗中的友方施法截图；友方护盾实际执行由 `test_player_cast_applies_friendly_modifier_and_spends_slot` 覆盖。

## 2026-08-01 附件规则扩展资料核对（最新）

附件中的六本扩展书在 `data/generated-content/dnd5e_chm/json` 的原始记录中均存在，但尚未全部成为“开团时可勾选的内容包”：

| 资料书 | 本地原始记录 | 已识别的内容 | 当前系统状态 |
| --- | ---: | --- | --- |
| 珊娜萨的万事指南 | 298 | 97 条法术、20 个角色选项页、规则/物品/休整期内容 | 法术和角色选项大多仍标 `unknown`，默认官方图鉴不加载 |
| 塔莎的万事坩埚 | 113 | 25 条法术、19 条职业/子职业/奇械师记录、定制血统、物品和环境灾害 | 原文在库；Tasha 职业记录尚未接入默认车卡 |
| 魔邓肯巨献：多元宇宙的怪物 | 289 | 289 个怪物记录 | 原文在库，但 `officiality=unknown`，尚未进入默认官方怪物图鉴 |
| 费资本的巨龙宝库 | 72 | 8 条法术、龙类内容、1 条怪物、物品 | 原文在库；龙类新增内容尚未作为内容包开放 |
| 毕格比巨献：巨人之荣耀 | 167 | 大量巨人/图鉴页面、6 个物品分类页 | 大部分仍是 `content_type=unknown`，尚未拆成怪物/职业可选原子 |
| 万象无常书 | 191 | 5 条法术、卡牌法术/命运牌机制、怪物和物品 | 原文在库；卡牌子系统和新增内容尚未接入车卡/战斗 |

当前本地目录共 8,127 条 JSON 记录；默认 `OfficialCompendiumCatalog` 只收纳已标记官方且已原子化的内容，所以这六本书在默认官方图鉴中查询结果为 0，并不代表原文不存在，而是元数据和原子化尚未完成。现有 `enabled_rule_extensions` 主要是“兼职、变体负重、英雄点数、追逐、士气”等机制开关，还不是附件里的“启用某本资料书新增法术/职业”开关。

## 2026-08-02 规则积木审计与伤害防御链（继续中）

- “所有法术进入完整自动”尚未完成。当前官方法术原子为 753 条，编译器计划统计为 `exact 347 / partial 49 / manual 357`；这不是端到端自动施法覆盖率。上一阶段的 `390 / 4 / 359` 是未把新增重复效果安全降级前的历史指标。可靠的战斗自动化边界仍是玩家或 DM 提供最终骰值后，后端处理 HP、临时 HP、抗性、易伤、免疫和动作经济。
- 已完成伤害类型别名归一化：强酸/酸蚀→`acid`，黯蚀/暗蚀→`necrotic`，以及钝击、寒冷、火焰、力场、闪电、穿刺、毒素、心灵、光耀、挥砍、雷鸣等；不能再因为中英文/别名字符串不同而绕过防御。
- 新增 `DefenseBlock`，官方怪物资料目前有 53/1111 个原子解析出抗性、易伤或免疫。防御字段会落在怪物模板，实例化到场景/战斗单位时传入 `Combatant`；抗性减半向下取整、易伤翻倍、免疫归零，抗性与易伤同时存在时抵消。带条件的“非魔法武器”等暂不猜。
- 新增怪物实例防御字段迁移 `d2f4a7b9c1e3`；本地数据库已升级到该版本。规则计划前端现在会显示“抗性/易伤/免疫”积木。
- 安全门已补：未知距离不再转换成自身/0尺目标；玩家/DM 战斗动作没有明确伤害类型时不再默认 `untyped`/`physical`；敌方自动行动默认为关闭；0 点治疗不再清空死亡豁免轨。
- 新增/更新测试：`test_rule_blocks.py`、`test_combat_rules.py`、`test_compendium.py`；上述定向测试通过。仍需继续做全量门禁与浏览器刷新验收。
- 并行审计结论已汇总：兼职/变体负重/规则扩展目前多为配置和规则原子，尚未全部接入运行时；多目标复合事务、状态持续、借机攻击完整矩阵、掩体和召唤生命周期仍是后续大项。不要在最终回复中声称这些已完成。

## 2026-08-02 任务拆分执行：召唤先攻与法术安全解析

- 按用户授权并行拆分了三个子任务：Sol high 负责召唤运行时，Terra max 负责法术覆盖审计，Luna high 负责车卡/规则扩展审计。早期审计得到的 `753 = 390 exact + 4 partial + 359 manual` 已被当前更严格的重复效果审计替代；`exact` 仍不是端到端自动施法指标。
- 召唤运行时已接入 `SummonBlock.initiative_mode`：`independent` 才掷 d20，`shared_with_source` 复用来源单位先攻，`not_applicable` 在动作/资源消耗前拒绝加入战斗；保留玩家所有权、动作消耗、幂等和当前回合身份稳定。尚未完成多数量、持续时间/专注、来源先攻变更联动和敌方召唤物 AI。
- 法术编译器新增安全范围归一化：触碰/接触为 5 尺，1 里为 5,280 尺；特殊、视野或超出安全上限的范围保持未知，不再猜默认值。治疗解析会把明确的临时生命值标成 `HealBlock.temporary_hp=true`。
- 升级服务新增 `multiclassing` 战役扩展门禁：未开启时拒绝新增多职业，DM 明确覆盖时留下警告；玩家车卡 2024 核心校验已有，但 DM 管理/OCR 通用角色 CRUD 仍不是同一套规则车卡契约。
- 本轮定向测试：召唤/战斗/规则元数据/角色目录 24 项通过；规则积木与元数据 17 项通过；升级矩阵和规则扩展 14 项通过；Ruff 与 `git diff --check` 通过。后续需跑全量门禁并做真实浏览器召唤验收。

## 2026-08-02 玩家端开发入口请求拦截修复

- 根因：玩家页的专用请求使用同源 `/api/v1`，生产玩家网关 `8787` 上这是正确的；但开发入口 `5173` 没有 API 代理，浏览器请求会落到 Vite 的 SPA fallback 并拿到 `index.html`，于是出现 `Unexpected token '<'`。
- 修复：`frontend/vite.config.ts` 为开发服务器增加 `/api` → `http://127.0.0.1:8000` 代理；没有改变 `8787` 的隔离玩家网关，也没有把 DM API 暴露给玩家网关。
- 实际验收：内置浏览器刷新 `http://127.0.0.1:5173/#/player` 和 `http://127.0.0.1:8787/#/player` 均显示“加入跑团房间”，不再白屏；两页控制台错误均为 0。
- 命令行验收：`5173/api/v1/player-room/me` 返回后端 JSON `401`（未登录是预期），不再返回 HTML；保存截图：`/private/tmp/dnd-player-page-fixed.png`。
- 本轮门禁：后端定向 45 项、前端定向 43 项、TypeScript、ESLint 均通过。玩家真实入口仍应使用推进台列出的 `8787` 局域网地址；`5173` 仅用于本机开发验收。

## 2026-08-01 内置浏览器真实验收（本轮最终确认）

- 刷新运行中的 DM 战斗页后，唯一动作选择框实际显示：恶言相加 `1d6 psychic`、不谐低语 `3d6 psychic`、雷鸣波 `2d8 thunder`；没有重复法术条目。
- 实际选择“恶言相加”后，当前动作执行积木显示“执行：`1d6 psychic` 伤害”，并明确提示玩家命中后再掷 `1d6 psychic`，不再显示“伤害骰未记录”。页面 DOM 定向检查该警告数量为 0。
- DM 战斗地图实际刷新后不再逐格出现“旅店木地板”（计数为 0）；地图上保留网格和有意义的特殊地形标记，并可看到“战争迷雾：预览关闭”控制。
- 已输出 DM 当前回合操作台和战斗地图的内置浏览器截图作为验收证据。此前仅依据测试/接口就宣布完成是不准确的；以后涉及页面 UI 的修复必须完成真实浏览器检查后再报告完成。

## 2026-08-01 法术范围与豁免积木补全

- 复查发现上一轮只补了伤害骰，老战斗快照仍缺少范围、豁免和描述；前端缺字段时默认显示 `5尺`，导致所有法术看起来像近战动作。这一问题已修正。
- 新增旧角色法术结构化事实回填：恶言相加/不谐低语 `60尺`，法师之手 `30尺`，治愈真言 `60尺`，妖火 `60尺；20尺立方`，雷鸣波 `自身；15尺立方`；同时回填豁免属性、角色法术 DC、伤害类型、持续/专注和说明。
- 范围积木现在实际读取这些字段；雷鸣波与妖火按区域范围处理。单体豁免法术不再显示“请掷命中 d20”，改为目标豁免 DC 与伤害骰输入。
- 内置浏览器刷新后的实际验收：动作下拉框已显示上述不同距离；选择恶言相加后积木显示 `60尺`、`wisdom豁免 · DC 13`、`1d6 psychic伤害`；截图确认页面没有再把它当成 5 尺攻击。

## 2026-08-01 法术位与升环施法

- DM 和玩家战斗动作都按法术最低环阶筛选 `spell_slots_N`，显示每个环阶当前/最大法术位；施法时消耗对应环阶 1 个法术位。
- 已预留升环伤害：不谐低语每高一环增加 `1d6`，雷鸣波每高一环增加 `1d8`，治愈真言每高一环增加 `1d4`；法术动作、范围积木和玩家提交接口都会使用所选环阶。
- 玩家战斗请求新增 `slot_level`，服务端重新校验法术本环、对应法术位和资源不足，不能只靠前端伪造升环。
- 内置浏览器实际验收：选择不谐低语后显示“使用法术环阶：1环 · 1环法术位 · 可用 2/2”，并显示“当前施法：1环；消耗 1 个对应法术位”；动作积木显示 `spell_slots_1 × 1` 和 `3d6 psychic伤害`。

## 2026-08-01 伤害骰投影与 DM 战斗地板显示修复

- 修复老角色法术动作投影：没有 `source_record_id` 时严格按法术名称匹配 `KnownSpell`，不再把最后一个法术的伤害覆盖到全部动作。当前标准角色的恶言相加/不谐低语/雷鸣波分别显示 `1d6`/`3d6`/`2d8`，非伤害法术不再伪装成伤害技能。
- DM 战斗地图沿用推进台的通用地形标签过滤规则，不再在每个地板格重复显示“旅店”等通用标签；墙、门、吧台、房间等有意义的地形标记仍保留。
- 定向后端测试通过（28 项相关法术/玩家房间测试），前端 SceneMap 与 PlayerPage 测试通过（10 项）。

## 当前工作目录

- 运行副本：`/Users/inagi/codex/130 游戏/135-跑团助手 dnd`
- 当前分支：`main`
- 当前状态：本轮功能改动仍在工作树中，尚未提交；不要用 reset 或 checkout 覆盖用户改动。
- DM：`http://127.0.0.1:5173/#/game-table`
- 玩家网关：`http://127.0.0.1:8787/#/player`
- 后端：`8000`；玩家网关绑定 `0.0.0.0:8787`。
- 当前服务已按最新源码重启并复核在线：后端本轮重启 PID `7852`；Vite/玩家网关沿用本运行副本现有进程。需要重启时只针对本运行副本进程操作，不要碰 `/Users/inagi/codex/700-AI/local-dnd-dm-assistant` 的旧后端。

## 2026-07-31 继续验收：角色法术伤害骰自动同步

- 修复法术资产录入只保存 `metadata_json.damage`、却没有同步到角色战斗动作的问题；`damage`、`damage_type`、豁免、范围和资源字段现在会一并镜像。
- 对已经存在的角色，玩家安全快照和战斗动作读取会从 `KnownSpell` 元数据补齐缺失字段，无需玩家重建角色卡。
- 玩家端会把 `2d8 thunder` 显示为 `2d8 雷鸣伤害`；玩家只需按提示掷伤害骰并填写最终总值，不需要自行查询技能规则。
- 伤害骰专项后端 28 项、前端 152 项、Ruff、mypy、TypeScript、生产构建和 `git diff --check` 均通过。

## 2026-07-31 继续验收：战争迷雾攻击边界与运行副本恢复

- 修复 `PlayerRoomService.attack()` 中战争迷雾目标校验引用局部函数导致的 `NameError`；攻击接口现在在自身作用域安全解析战斗单位坐标。
- 玩家攻击和区域法术只允许选择当前角色可见格内的敌方怪物；不可见目标在服务端拒绝，避免仅靠前端隐藏造成越权攻击或泄露隐藏单位状态。
- 全量后端 245 项、前端 152 项、Ruff、严格 mypy、TypeScript、ESLint、production build 和 `git diff --check` 均通过。
- 8000 后端已重新启动并健康检查 200；8787 玩家网关仍为 PID `79722`，DM/玩家 SPA 入口均返回 200。

## 2026-07-31 继续验收：玩家端商店入口与安全购买

- 玩家页现在始终有“商店”页签；未绑定角色前不会显示，因为玩家会停留在房间加入/角色绑定流程。
- 玩家绑定角色后，快照只返回当前玩家房间、当前 Scene、公开可见商人关联的库存；其他 Scene、未公开 NPC、未归属的 DM 库存不会进入玩家 payload。
- 玩家端商店流程为“商店 → 预览购买 → 确认购买”。钱包 id/version、库存 id/version 和数量由服务端校验；购买后商品进入当前绑定角色的装备/消耗品资产。
- 新增玩家专用 `/api/v1/player-room/me/commerce/preview` 与 `/commerce/confirm`；服务端同时校验房间当前 Scene、商人公开参与者、绑定角色钱包和交易版本，不能借用同团其他角色钱包或其他 Scene 商品。
- DM 仍使用原有 `/campaigns/{campaign_id}/commerce/preview|confirm`，没有改变 DM 商城交易语义。
- 没有商店时，玩家页会明确提示 DM 在“商人与商店”中创建商店并绑定当前 Scene；DM 创建后玩家端随快照刷新出现入口。

## 已完成

- Scene 默认按大纲排序进入 Scene 1；玩家实时 Scene 同步带版本 CAS，旧请求不能把 Scene 1 写回 Scene 5；战斗页打开不再以最新战斗覆盖玩家 Scene。
- 玩家端装备预览按规则分类：消耗品显示“预览使用”，武器/护甲显示“预览装备”，法器/工具显示“预览持用”，普通物品不伪装成装备。
- 玩家端有“申请短休 · 1小时”和“申请长休 · 8小时”；申请只创建 pending 玩家行动，DM 拒绝或“批准并执行休息”后才结算。
- 玩家端当前角色快照会显示可用生命骰；短休申请可逐枚提交实际骰值，服务端会校验角色归属、面数和可用数量，DM 批准后短休才按生命骰回血并扣除骰池。
- 休息审批在单事务内原子认领申请、结算资源/世界时间、写 accepted、公开 Event 和 AuditLog；并发双击幂等。迁移头为 `b7c3d9e1f204`，唯一索引为 `uq_player_pending_rest_per_character`。
- opener 走通用副 DM 只询问链路，交付类型为 `read_aloud`；会生成供 DM 采用的可朗读草案，不自动推进 Scene、写权威事实或替玩家决定动作。

## 验收证据

- 浏览器 reload 后 DM 推进台稳定显示 Scene 1；玩家 `8787/#/player` 能打开“加入跑团房间”页面，项目级控制台错误为 0。
- 玩家入口显示“加入跑团房间”是正常未绑定状态；输入 DM 当前显示的 6 位房间码和玩家称呼后，才显示角色、行动和休息申请。
- 定向后端：`test_player_rooms_api.py`、`test_rests_api.py`、`test_rest_rules.py` 共 30 项通过，包含玩家短休生命骰实际回血。
- 定向前端：`PlayerPage.test.tsx`、`GameTablePage.test.ts` 共 14 项通过，包含短休申请携带骰值；本轮新增商店页签/购买测试，PlayerPage 定向 7 项通过。
- 当前全量门禁：后端全套通过（245 tests）、Ruff、严格 mypy；前端全套 151 tests、TypeScript、ESLint、production build；`git diff --check` 通过。
- 运行时验证：`/api/v1/health` 与玩家网关 health 均返回 200；DM `5173`、玩家 `8787` 的 SPA 入口均返回 200。标准团房间版本 `29805`，查询期间 `current_scene_id` 未继续增长。
- 测试副本必须用绝对源码路径：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/dnd-pycache \
PYTHONPATH='/Users/inagi/codex/130 游戏/135-跑团助手 dnd/backend/src' \
backend/.venv/bin/python -m pytest -q backend/tests
```

## 交接注意

- 运行副本本来没有交接文件；开发仓库的相关交接文件在 `/Users/inagi/codex/700-AI/local-dnd-dm-assistant/CODEX_HANDOFF.md`。
- 真实 LAN 玩家必须与 Mac 在同一可信局域网；访客 Wi-Fi、客户端隔离、VPN 或 macOS 防火墙会导致外部设备打不开。使用推进台动态列出的局域网地址，不要假定旧 IP 永远有效。
- 不要把 `127.0.0.1:5173` 或 `127.0.0.1:8000` 给玩家；玩家使用 `8787` 网关。
- 当前优先玩家地址是 `http://192.168.31.154:8787/#/player`（en0）；`192.168.2.61` 是另一张局域网网卡，`198.18.0.1` 是虚拟/VPN 地址不要用；`.local` 主机名依赖 mDNS，部分设备无法解析。多个地址是同一个玩家网关的不同网络入口，不是多个玩家页面。
- 继续工作前先读本文件、项目记忆 `/Users/inagi/Documents/100-ai agents/agent memory/agency/30-projects/local-dnd-dm-assistant.md`、当前 `git diff` 和全局记忆规则。

## 2026-08-01 战斗规则积木与借机攻击链

- 规则积木新增结构化移动/位移、反应触发和状态摘要；雷鸣波显示强制推开 10 尺，妖火显示针对目标攻击优势，不谐低语显示反应移动触发。
- 玩家移动离开敌对单位 5 尺近战威胁范围时，服务端创建 `opportunity_attack` 待 DM 请求；勾选“撤离（Disengage）”会消耗动作并跳过请求。
- DM 玩家行动面板显示敌人、目标和预期伤害表达式；填攻击总值与伤害总值后批准，才按 AC 写入普通伤害行动并消耗敌人反应。
- 内置浏览器刷新后实际选择雷鸣波，DOM 确认 `15尺立方`、`constitution豁免 · DC 13`、`2d8 thunder伤害`、`forced 10尺 · away`，并已输出截图。
- 本轮定向测试仍有既有工作树失败：法术元数据镜像的 `damage` 字段缺失、玩家移动测试的可见性断言失败；Ruff 与前端 TypeScript 通过，不能宣称全量门禁通过。

## 2026-08-01 雷鸣波地图范围显示修复

- 根因：规则积木的雷鸣波是 `mode=self / shape=cube / range_ft=0 / size_ft=15`；前端只识别圆形、锥形、直线，且备用解析没有把立方尺寸传入网格计算，导致地图没有施法范围或只有施法者单格。
- 修复：前端新增 `cube` 与 `originSelf` 目标模板；自身起点区域不再要求远程瞄准点，按 15 尺立方计算实际影响格；备用动作解析也正确提取 `15尺立方`。
- 视觉修复：紫色影响区域使用强制颜色层，避免被蓝色施法距离层覆盖；雷鸣波现在可同时看到蓝色施法范围与紫色实际影响范围。
- 浏览器验收：刷新 DM 战斗页，实际选择“雷鸣波 · 2d8 thunder · 自身；15尺立方”；DOM 显示“自身为区域起点”且目标范围状态更新，截图看到蓝色范围、紫色立方影响区和完整规则积木。
- 定向前端测试：`gridTargeting.test.ts` 与 `RuleBlockPlan.test.tsx` 共 16 项通过；TypeScript 与 `git diff --check` 通过。

## 2026-08-02 召唤单位与回合重复效果批次

- `CombatEngineService.add_summon()` 会创建新的 `Combatant(entity_type="companion")`，带有独立的 HP、AC、速度、动作、控制者、主人角色、来源单位和先攻模式；玩家召唤物会沿用玩家控制边界。
- 新增 DM 结束召唤物事务：将召唤单位标记为非活动、结束其关联效果、修正当前回合索引、写入 `combat_end_summon` 事务和 `end_summon` 战斗动作，并使用请求幂等键防止重复结束。
- 关联效果结束和专注失败会触发同一套召唤物离场处理；明确绑定召唤物的持续效果在回合推进到期时会自动结束并移除召唤物。普通状态效果仍只产生 DM 待确认提示。
- DM 战斗台先攻卡增加“结束召唤”入口；玩家端不拥有结束其他单位的权限。
- 资料解析新增明确“每回合开始/结束、每轮开始/结束”的 `RepeatBlock`。它只表达原文时点，并保留“重复效果尚未接入战斗回合执行器”的未决原因，不把这类法术标成完整自动。
- 本批验证：召唤持续时间、结束事务和规则积木定向测试通过；后端全量通过；前端 36 个测试文件、155 项通过；TypeScript、ESLint、生产构建、Ruff、`git diff --check` 通过。

## 2026-08-02 召唤数量与归零离场批次

- 召唤物受到伤害降到 0 HP 时现在自动标记 `is_active=false`、离开先攻顺序并修正当前回合索引；召唤物不创建死亡豁免，也不进入玩家角色的死亡轨。
- 伤害动作日志会记录 `summon_ended=true` 与“生命值降至0”，DM/玩家可以明确看到召唤物已离场。
- `CombatSummonCommand.count` 支持一次召唤 1–20 个独立 `Combatant`；每个单位有独立 ID、HP、网格位置和先攻。独立先攻逐个掷骰，共享来源先攻则共享先攻值；动作/资源只扣一次，幂等重放会返回整组单位。
- DM 战斗台和玩家召唤面板都增加数量输入；资料库中的动态数量表达式会显示给玩家/DM，实际数量由法术表或 DM 裁定后填写，不自动猜数量。
- 运行副本的 SQLite 原先未执行迁移，导致 `/campaigns` 返回 500、战斗台显示后端无响应；已对 `backend/data/dnd_dm.db` 执行 `alembic upgrade head`。浏览器复核 `5173/#/combat` 与 `5173/#/player` 均可打开，控制台错误为 0；当前数据库为空战役，未伪造先攻列表截图。
- 本批验证：后端全量通过；召唤/战斗/玩家房间定向通过；前端 36 个测试文件、155 项通过；TypeScript、ESLint、生产构建、Ruff、`git diff --check` 通过。

## 本轮连续执行收口（2026-08-01）

这次按“不要一波一波停下来”的要求，把规则积木、战斗执行、车卡/扩展和浏览器验收连成一条流水线完成；之后继续开发时不要把下面的已完成项当成待办重做。

- 法术规则计划已按安全升环逻辑重新编译：753 个官方法术当前为 `347 exact / 49 partial / 357 manual`。其中 104 个单一同骰型伤害/治疗法术有可验证的逐环增量。多段伤害、目标数分支、重复效果和召唤数量仍保留 DM 裁定，不能写成“所有法术完整自动”。
- 战斗执行补上半掩体遮挡的 `+2 AC`、`尺/英尺/ft/feet` 距离、立方/锥形区域的服务端校验；未知范围和伤害类型继续显示待裁定，不再用 5 尺或物理伤害兜底。
- 玩家车卡已接入标准数组、购点、4d6 去最低、背景起源属性加值、工具熟练、额外语言、起始装备选项；后端 `character_creation.py` 对这些输入做硬校验。规则扩展通过白名单、战役开关和 `rule` 原子/`RulePlan` 保存，并对未启用的兼职扩展拒绝运行时新增。
- 召唤物会创建实际的 `Combatant(entity_type="companion")`，有独立 HP/AC/动作/控制者/主人/来源/先攻；支持独立或共享来源先攻、1–20 个单位、专注/持续时间离场、HP 归零离场、DM 结束召唤和幂等。动态数量只展示资料库表达式，实际数量必须由 DM 或法术表确认。
- 本轮门禁已重新执行：后端 `backend/tests` 全量通过，Ruff、`git diff --check` 通过；前端 TypeScript、ESLint、Vitest 156 项、生产构建通过。
- 内置浏览器实际验收：`http://127.0.0.1:5173/#/player` 显示“加入跑团房间”，不再出现 HTML 当 JSON 的解析错误；`http://127.0.0.1:5173/#/combat` 显示 DM 战斗入口，控制台错误为 0。运行副本的 SQLite 当前没有战役，所以没有伪造先攻列表、召唤列表或战斗内规则积木截图。

证据截图：

- 玩家入口：[dnd-player-entry-final.png](/private/tmp/dnd-player-entry-final.png)
- DM 战斗入口：[dnd-dm-combat-final.png](/private/tmp/dnd-dm-combat-final.png)

下一阶段仍是明确的工程缺口：把 `RepeatBlock` 接入回合开始/结束执行器，补多段/复合伤害与完整多目标区域结算，补准备/疾走/闪避/协助/擒抱/推撞和更多怪物动作积木，并把兼职、高等级升级和启用的变体前置条件继续接入统一车卡契约。当前不应声称这些部分已经全部自动化。

## 2026-08-01 八类缺口整合执行与最终验收

本次按用户要求把此前列出的八类缺口连续执行并验收，不再把“字段存在”当成“功能完成”。当前真实状态如下：

1. 怪物战斗：怪物回合自动选目标、寻路、攻击、玩家豁免暂停/继续链已保留；本次补入多重攻击逐段执行、充能自动门禁、集中攻击/保护首领/控制/撤退/自适应策略、掩体与视线几何、半掩体 +2 AC、魔法抗性、传奇抗性、闪避、反应/传奇/巢穴动作窗口、锥形/直线/立方区域的逐目标结算。球体/圆柱/旋转三维几何及每一种怪物专属动作仍需结构化资料后才能自动化。
2. 战斗规则：`CombatEngineService.confirm_maneuver` 原本已有规则执行，本次新增玩家专用 `/api/v1/player-room/me/combat/maneuver`，服务器从当前回合注入真实角色或玩家召唤物 ID/版本；玩家界面实测出现疾走、闪避、协助、准备动作、搜索、隐藏、使用物品、擒抱、推撞、物件互动、撤离、起身。擒抱/推撞/搜索/隐藏/物件互动等不确定结果必须由 DM 明确结果和说明，不能由系统猜。
3. 法术：特殊法术的传送、变形、创造、驱散、多分支、区域和混合伤害已经有 RuleBlock 与对应执行路径；升环、法术位、豁免、范围、伤害段输入已进入玩家/DM 链路。当前 `allow_legacy=True` 的 753 条官方入口计划为 `475 exact / 38 partial / 240 manual`；默认不加载 legacy 的 2024/2025 入口为 392 条。这个数字是编译计划完整度，不是端到端全自动施法数；重复状态/修正 tick、部分多段/复杂分支仍保留明确未决。
4. 召唤物：召唤会创建真实 `Combatant`，写入先攻、HP、AC、速度、来源、控制者；支持独立/共享来源先攻、1–20 个单位、玩家控制、敌方召唤 AI 基础链、专注/持续时间结束、HP 归零离场、DM/玩家结束召唤和幂等。法师之手、隐形仆役等非战斗效果不会伪造战斗单位；没有完整伙伴模板时会明确提示。
5. 伤害/防御/状态：标准伤害类型、分段伤害、抗性/易伤/免疫、临时生命、基础状态和基础状态生命周期已进入原子结算；条件型“非魔法武器”、材质/来源/攻击类型防御、多段伤害的全部高级组合和完整倒地/中毒/束缚/魅惑/恐慌限制仍要求结构化规则后继续接入。
6. 车卡/升级：标准数组、购点、4d6 去最低、背景起源加值、工具熟练、语言、起始装备、子职业、专长前置、HP、法术准备/替换、法术位、资源池、多职业门禁已接入；1–20 级全部职业特性和扩展职业/子职业/专长的每个运行时效果尚未全部结构化。
7. 探索/社交/剧情：追逐、陷阱、毒药/疾病/感染、Downtime、NPC 士气/投降/撤退、环境危害已经有 preview→confirm→OperationTransaction 链路；社交关系的复杂叙事变化、全环境模拟和部分世界时钟细节仍以 DM 确认为边界。
8. 规则扩展：开团资料包开关、legacy 门禁、版本/官方性隔离、原子目录和 `RulePlan` 已接入。六本本地资料书安全识别的法术、怪物、物品可按团开启；职业/子职业/专长/叙事目录页中 `needs_normalization` 或 `dm_choice` 的记录不会伪装成完整自动车卡。

本轮最终门禁：后端 `backend/tests` 全量通过；Ruff、`git diff --check` 通过；前端 TypeScript、ESLint、36 个 Vitest 文件/160 项测试、生产构建通过。浏览器在真实玩家房间和 DM 战斗页复核，玩家标准动作选择器的 10 个核心选项可见，DM/玩家控制台 error/warn 均为 0。

验收截图：

- 玩家标准动作：[dnd-final-player-standard-actions-20260801.png](/private/tmp/dnd-final-player-standard-actions-20260801.png)
- DM 战斗页：[dnd-final-dm-standard-20260801.png](/private/tmp/dnd-final-dm-standard-20260801.png)

后续不要重新声称“所有法术已经完整自动”。应继续从未决边界推进：RepeatBlock 的状态/修正回合执行、多段/复合伤害和完整多目标区域、复杂状态生命周期、球体/圆柱几何、全部怪物专属动作，以及完整职业 1–20 级运行时特性。

## 2026-08-01 战斗主线强化：状态回合、攻击上下文、球形区域与怪物撤离

- `RepeatBlock` 的 condition/modifier/defense 子块已接入回合边界执行器。回合开始/结束触发时，条件与抗性/易伤/免疫会在被外部移除后恢复；数值 AC/速度修正只在仍处于原始基线时恢复，检测到其他效果改写会返回 `requires_dm_review`，不会重复叠加或覆盖 DM 裁定。
- 战斗状态别名与服务器攻击上下文补充目盲、耳聋、中毒、恐慌、束缚、魅惑、隐形、擒抱等；束缚/擒抱会阻止移动。攻击者/目标状态、麻痹/昏迷近距离自动重击条件会写入 `attack_contexts`，仍要求 DM 明确优势/劣势和条件性来源，不默认猜结算方式。
- 怪物区域动作新增服务端 `sphere` 几何，锚点作为球心，按权威网格单元距离判断覆盖范围；与锥形、直线、立方一样先校验目标集合，再逐目标结算豁免、伤害、防御和状态。
- 怪物 AI 新增可执行低血撤离：预览到 `disengage` 后，`POST /monster-ai/retreat/confirm` 复用战斗机动引擎，消耗动作、创建回合末结束的撤离状态并写审计/幂等记录；路径和出口仍由权威地图/DM 决定。
- 本轮定向和全量后端测试通过；Ruff、`git diff --check`、前端 TypeScript、ESLint、36 个 Vitest 文件/160 项、生产构建通过。浏览器真实打开 DM 战斗页，操作区截图见 `/private/tmp/dnd-combat-operation-panel-20260801.png`，控制台 error/warn 均为 0。

当前战斗主线仍未闭环：多属性伤害按段拆分、条件性抗性（非魔法/材质/来源）、复杂状态的来源与结束条件、怪物反应/传奇/巢穴动作的逐动作 UI，以及复杂三维区域。继续开发应从这些边界推进，不要把“字段存在”当成自动执行。

## 2026-08-01 战斗主线：混合伤害与条件性防御

- `CombatActionCommand` 新增 `damage_components`。当一次动作同时造成火焰、挥砍等多种伤害时，服务端逐段调用伤害结算；每段独立应用抗性、易伤、免疫和临时生命，结果同时保留每段明细与汇总，不再把混合伤害当成单一类型。
- `CombatActionCommand` 新增 `damage_tags`。目标快照中的 `conditional_damage_defenses` 只有在提交匹配来源标签（如 `nonmagical`）时才会生效；若伤害类型命中条件防御但缺少标签，预览/确认会暂停并要求 DM 标签或显式 override，避免把“非魔法武器抗性”错误地应用到法术或魔法武器。
- 新增后端回归：混合伤害段独立抗性/临时生命、条件性防御缺标签拒绝与标签命中；前端 API 类型同步。
- 本轮全量门禁通过：后端测试全套、Ruff、`git diff --check`；前端 TypeScript、ESLint、36 个 Vitest 文件/160 项、生产构建。刷新真实 DM 战斗页确认页面存在，控制台 error/warn 均为 0。

当前剩余战斗边界：条件防御资料的全面导入、复杂状态来源/结束条件、怪物反应/传奇/巢穴动作的完整 UI、复杂三维区域和更高阶多段效果；本轮没有把这些未完成内容标记成已自动化。

## 2026-08-01 战斗主线：0 HP 昏迷生命周期

- `CombatEngineService` 现在把 0 HP 与真实状态链绑定：普通伤害、怪物范围伤害和持续伤害把非召唤单位降到 0 HP 时幂等加入 `昏迷`；召唤物仍直接离场，不进入死亡豁免。
- `昏迷` 复用既有行动/移动限制和攻击上下文：不能继续执行动作，移动被阻止；对 5 尺内昏迷目标的自动重击条件会写入攻击上下文，但优势/劣势仍要求 DM 明确确认。
- 普通治疗和自然 20 的死亡豁免把 HP 从 0 恢复到正数时自动移除 `昏迷`，并重置死亡豁免成功/失败/稳定/死亡标记；结果写入 `condition_changes`，便于 DM/玩家界面显示实际状态变化。
- 回合持续伤害降到 0 HP 时现在也创建死亡豁免记录；不再只改 HP 而漏掉死亡轨。
- 回归测试覆盖普通伤害归零、治疗唤醒、自然 20 唤醒、持续伤害路径；后端全量 pytest、Ruff、`git diff --check` 通过，前端 TypeScript、ESLint、36 个 Vitest 文件/160 项、生产构建通过。
- 内置浏览器实际刷新 DM 战斗页，页面可用且 error/warn 均为空；验收截图：[dnd-combat-unconscious-lifecycle-20260801.png](/private/tmp/dnd-combat-unconscious-lifecycle-20260801.png)。

仍未宣称全部战斗规则完成：复杂状态的来源、持续时间、回合末豁免、移除条件和状态组合仍需继续结构化；复杂三维区域、怪物专属动作和职业 1–20 级运行时特性也仍是后续边界。

## 2026-08-02 DM 模拟战斗回归入口

- 新增 DM 导航“模拟战斗”页面：固定剧本为“元素熔炉：召唤与范围战斗演练”，创建独立的系统战役 `【系统】召唤物与法术战斗模拟`，但真实使用现有 `Scene`、`SceneGrid`、`Combat`、`Combatant`、`CombatEngine` 和 `PlayerRoom`，不是另一套假战斗。
- 固定剧本包含 5 级模拟奥术师、火焰箭/雷鸣波/火球术/治疗/召唤小火元素、熔火术士 AI、熔炉守卫 AI、真实地图障碍、抗性、先攻和玩家房间；玩家页面可自动加入并绑定模拟角色。
- “启动玩家页面”会生成带 `simulation_join_code` 的玩家链接并调用 `window.open`；玩家端链接既能首次加入，也能从已有其他玩家房间自动切换到模拟房间，然后自动绑定 `模拟玩家·奥术师`。页面展示真实法术环阶、范围、豁免、伤害积木和召唤模板。
- 模拟玩家召唤后会创建真实 `Combatant(entity_type="companion")`，加入先攻轨道、地图和玩家控制单位；模拟重置会清理动态召唤单位、战斗日志/效果/请求，并恢复 HP、动作、先攻和法术位资源，回到 3 个初始单位。
- 后端接口：`GET/POST /api/v1/simulations/current|prepare|reset`；回归测试在 `backend/tests/test_simulations.py` 覆盖准备、玩家加入/绑定、真实召唤、重置清理和资源恢复。
- 最终门禁：后端全量 `366 passed`；前端 36 个测试文件/160 项通过；TypeScript、ESLint、生产构建、Ruff、`git diff --check` 通过。内置浏览器 DM/玩家页面 error/warn 均为 0。
- 验收截图：DM 模拟入口 [dnd-simulation-dm-final-20260802.png](/private/tmp/dnd-simulation-dm-final-20260802.png)、玩家雷鸣波 [dnd-simulation-player-final-20260802.png](/private/tmp/dnd-simulation-player-final-20260802.png)、召唤物加入先攻 [dnd-simulation-player-summon-final-20260802.png](/private/tmp/dnd-simulation-player-summon-final-20260802.png)。

继续工作时先打开 DM 的“模拟战斗”，用“重置模拟战斗”恢复基线，再从“启动玩家页面”开始回归；不要把这套固定剧本的测试结果直接等同于所有真实战役内容均已自动化。

## 2026-08-02 火焰箭/区域瞄准/召唤落点回归修复

- 修复模拟剧本中火焰箭规则积木内部残留 `force` 的问题；现在描述、动作字段和 `damage` block 都是 `fire`，玩家端和 DM 端均显示“1d10 火焰伤害”。
- 修复火球术、雷鸣波把规则积木里的 `save` 忽略、错误显示为命中攻击的问题。玩家端现在从 `RulePlan` 读取豁免属性和 DC；火球术显示敏捷 DC 14，雷鸣波显示体质 DC 13，并按范围内目标数量提交玩家伤害骰。
- 修复旧版 `target + area_effect` 法术计划与新版 `target(mode=area)` 计划的兼容；火球术支持“先点瞄准落点，再预览影响范围”，本次浏览器实测落点 6,4，两个敌方目标进入结算。
- 修复雷鸣波的自我立方体方向：地图显示蓝色施法范围，点击方向后前端和后端共用同一方向几何；本次实测点 6,3，两个目标进入范围并完成两次豁免。后端不再把首个目标位置覆盖成区域瞄准点。
- 固定模拟敌人改到玩家附近的 5,4 / 7,4，确保模拟剧本能够实际覆盖雷鸣波方向与多目标结算；火球术仍能覆盖两个目标。
- 召唤选择现在要求先选完整伙伴模板，再点击蓝色空格落点；本次实测选择 6,6 后创建新的 `Combatant`，进入先攻（17），地图显示“小火元素”在 6,6，而不是默认塞到施法者旁边。
- SceneMap 增加蓝色瞄准范围图例，明确“点击蓝色格选择落点或方向”。
- 新增/更新前后端回归，覆盖旧区域计划转换、自我立方体方向、火焰箭伤害类型和召唤落点。

本轮门禁：后端全量 `366 passed`；前端 36 个测试文件、162 项通过；TypeScript、ESLint、`git diff --check` 通过。

实际浏览器证据：

- 火球术落点、范围与两目标豁免：[dnd-fireball-preview-fixed-20260802.png](/private/tmp/dnd-fireball-preview-fixed-20260802.png)
- 召唤模板、6,6 落点与可用按钮：[dnd-summon-placement-fixed-20260802.png](/private/tmp/dnd-summon-placement-fixed-20260802.png)

当前不要把“所有法术”宣称为完整自动；本次只修复上述模拟战斗回归和区域瞄准共通链路。复杂多段伤害、复杂状态生命周期、怪物专属动作和职业 1–20 级运行时规则仍按前文边界推进。

## 2026-08-02 长时战斗回归与模拟重置修复

- 按完整跑团顺序做了长时回归：模拟战斗准备、玩家加入/绑定、移动、疾走、火焰箭、火球术双目标逐目标豁免、雷鸣波方向/范围/伤害/推离、召唤物落点/先攻/玩家控制、怪物 AI 移动/选技/玩家豁免暂停/继续，以及休息、商店、探索、追逐、陷阱、Downtime、NPC 士气和规则检索测试。
- 战斗专用后端回归整组通过，包含战斗引擎、标准动作生命周期、召唤、怪物 AI、玩家移动/房间、模拟剧本；全量后端测试通过。前端 TypeScript、ESLint、36 个 Vitest 文件/162 项、生产构建通过；Ruff 和 `git diff --check` 通过。
- 深回归实际发现并修复模拟重置的专注残留：重置删除召唤 Combatant 和 CombatEffect 后，玩家 Combatant 的 `concentration` 之前没有恢复为空，导致下一轮会显示“仍在专注”但先攻里已经没有召唤物。现在重置明确清空专注字段，并由 `test_simulations.py` 固定断言；真实运行中的后端重启后通过 `POST /api/v1/simulations/reset` 验证三名初始单位的专注均为空、法术位全部恢复。
- 已保留火焰箭火焰伤害、火球术区域落点/逐目标豁免、雷鸣波强制推离和召唤落点的浏览器验收截图：`/private/tmp/dnd-fireball-preview-fixed-20260802.png`、`/private/tmp/dnd-summon-placement-fixed-20260802.png`、`/private/tmp/dnd-dm-combat-regression-fixed-20260802.png`。本轮后端重启后内置浏览器网络页出现 `ERR_NETWORK_IO_SUSPENDED`，因此没有把这次重置 API 验证冒充成新的浏览器截图。

长时回归仍不能推出“所有法术完整自动”。未决边界继续是复杂多段/复合伤害、完整状态来源与结束条件、怪物专属动作和反应/传奇/巢穴动作 UI、复杂三维区域、全部职业 1–20 级运行时特性。

## 2026-08-02 雷鸣波推离与模拟战斗 AI 卡死修复

- 这次反馈确认了“规则积木存在”不等于“执行链生效”：雷鸣波原先能显示 forced movement，但 DM 区域结算没有把该字段提交到后端；现已从统一规则积木读取推离距离/方向，并写入区域结算请求。
- 修复模拟剧本位置快照只存在嵌套 `snapshot_json`、战斗执行器读取顶层 `grid_position` 的问题；模拟准备与重置现在同步初始位置。雷鸣波失败豁免实测：熔火术士从 `(5,4)` 推到 `(3,6)`，移动 10 尺，HP `30→22`。
- 修复怪物自动回合在动作请求尚未真正启动前就锁定 `processedAutomaticTurn` 的问题；修复 AI 移动发生版本冲突时重复保存造成的假失败；怪物序列 ID 加入战斗版本，避免重置后旧幂等记录阻塞下一轮。
- 内置浏览器完整回归：熔火术士先移动并使用熔炉爆裂，玩家豁免确认后继续；熔炉守卫随后自动移动并使用熔岩重击，最后回到玩家回合。日志没有“移动保存失败”“version conflict”或“自动动作失败”。
- 门禁：后端全量测试通过；前端 36 个测试文件、163 项通过；TypeScript、ESLint、生产构建、Ruff、`git diff --check` 通过。前端测试环境使用绝对后端地址，浏览器仍使用同源 `/api/v1` 代理。

当前边界：这次已闭合雷鸣波强制推离和模拟剧本 AI 卡死链路；不能据此宣称所有法术、所有怪物专属动作或全部复杂状态已经完整自动化。

## 2026-08-02 怪物目标一致性与玩家端攻击范围同步修复

- 根因一：AI 移动规划只把 `entity_type="character"` 当作目标，但攻击控制台会把玩家控制的召唤物也纳入目标并优先选择低 HP 单位；结果是怪物移动到角色旁边，却等待攻击远处召唤物。`BattleGrid` 现在和攻击控制台共用玩家控制目标与标准目标选择，召唤物不会再造成“移动完成但动作不启动”。
- 根因二：玩家端原先只从 `pending_rolls` 推导敌方危险格，普通 AI 尚未创建豁免请求时看不到敌方动作范围。玩家房间战斗快照现在发布当前敌方的结构化 `active_action`；玩家端据此显示橙色可达范围、红色实际影响范围和动作伤害/类型，待豁免时仍以权威请求覆盖预览。
- 对锥形、直线、立方和视线约束补入 `planTargetingPath`，AI 不再只满足数值距离而忽略实际形状；若当前点不覆盖目标，会搜索同一规则模板下的合法位置。
- 浏览器真实验收：模拟战斗重置后，熔火术士自动生成敏捷豁免；玩家端显示“当前 AI 动作：熔炉爆裂 · 2d6 火焰伤害”、橙色范围和红色影响范围。提交豁免后，熔炉守卫从 `(7,4)` 移动到 `(6,3)` 并自动执行“熔岩重击”，随后回合继续推进，没有停在“正在等待怪物动作结算”。
- 本轮门禁：后端全量测试通过；前端 36 个测试文件/164 项通过；TypeScript、ESLint、生产构建、Ruff、`git diff --check` 通过。后端验收必须以 `PYTHONPATH=backend/src` 启动，避免误加载旧的已安装包。

当前边界不变：这次修复的是 AI 目标/动作状态收敛和玩家端共享预览，不代表所有法术、怪物专属动作或复杂状态已经完整自动化。

## 2026-08-02 玩家控制召唤物、特殊技能与 DM 自由行动闭环

- 模拟剧本的小火元素模板明确为 `controller="player"`、`disposition="ally"`；玩家召唤后创建的真实 `Combatant` 会加入先攻、地图和玩家控制单位，不会默认交给 AI。敌方召唤物/DM 控制单位仍走怪物 AI。
- 玩家端战斗操作拆成“移动”和“攻击 / 技能”两种模式：移动模式只允许点击绿色移动格，攻击/技能模式才允许选择目标、落点或方向，避免地图点击把移动和攻击混在一起。受控召唤物会显示在可控单位列表中，并沿用正式 CombatEngine。
- 模拟角色加入“魔法飞弹”特殊技能：`3d4+3 force`、120 尺、规则积木含 `auto_hit`，玩家端明确显示“特殊攻击 / 自动命中”，禁用 d20 命中输入，只要求伤害骰；升环仍由法术位选择器处理。修复旧模拟存档和初始 Combatant 快照漏掉该动作的问题，并把 `auto_hit` 纳入角色卡法术同步字段。
- DM 自由发挥输入已接入正式玩家掷骰链：DM 输入自然语言后，规则助手按关键词给出技能/属性、DC、调整值和可执行积木；选择效果目标并执行后，玩家端收到 d20 输入；玩家提交后服务端自动计算成功/失败，并把结构化状态/位移效果写入正确的效果目标。实测“玩家想要尝试撒泡尿滑倒怪物”→运动（力量）DC12→玩家提交 15→熔火术士获得 `prone`。
- 真实浏览器验收还确认：玩家端显示魔法飞弹的自动命中提示、火元素的玩家控制语义、移动/攻击模式切换、DM 自由行动输入、玩家骰点和目标倒地状态；旧标签页在后端重启后会保留断线画面，需重新打开玩家链接才能刷新，不能把旧画面当作接口状态。
- 回归测试新增魔法飞弹伤害类型/自动命中/积木、角色卡同步和召唤物 `controller/is_own/owner` 断言。
- 最终门禁：后端全量 `368 passed`；前端 36 个测试文件/164 项通过；TypeScript、ESLint、生产构建、`git diff --check` 通过。
- 玩家端实际验收截图：[dnd-player-control-magic-20260802.png](/private/tmp/dnd-player-control-magic-20260802.png)。

本轮闭合的是模拟剧本与玩家端控制/特殊技能/DM 自由行动的正式执行链，不代表所有法术或所有自然语言行动都能无 DM 裁定自动化。无明确规则的自由行动仍只能生成建议，必须由 DM 选择目标并确认执行；复杂多段伤害、状态生命周期、怪物高级动作和职业运行时特性仍按既有未决边界处理。

## 2026-08-02 复杂自由战斗长回归最终记录

- 使用 Luna xhigh 在同一正式模拟战斗框架中跑完第 1–15 轮复杂战斗：火球术、熔炉爆裂豁免、熔炉守卫移动/攻击、雷鸣波、玩家控制小火元素召唤/独立先攻/移动/攻击、治疗、魔法飞弹、火焰箭、敌人退场。
- 真实数据库动作日志为 `combat_actions` rowid `390–469`，共 80 条；完整时间线已保存到 `docs/artifacts/dnd-complex-battle-log-20260802.md`。最终状态：玩家 17/28 HP；熔火术士和熔炉守卫均 0 HP、离开先攻轨道；战斗保留 `active` 等 DM 确认结束。
- 实战确认 AI 普通攻击会继续推进，只有玩家豁免才产生 `player_roll_prompt`；没有发现“正在等待怪物动作结算”卡死、死敌重复行动或重复推进。召唤物真实创建为 `Combatant(entity_type="companion")`，rowid 398 加入先攻 19，rowid 400 移动，rowid 401/410/418 攻击。
- 本次雷鸣波两个目标都成功豁免，所以最终日志正确记录为伤害 0、没有伪造推离；失败豁免推离分支由现有定向测试 `test_player_compiled_forced_movement_is_applied_after_failed_save` 覆盖。死亡豁免此前在玩家归零的失败长流程中单独实测成功数 0→1→2，并确认第二次提交会推进回合。
- 全量回归第一遍发现 2 个旧接口契约回归：非角色单位归零后立即离开先攻时，`confirm` 返回的 `death_save` 变成了 `null`。已修复为仍保存/返回死亡豁免轨，但不让该非角色重新进入先攻；修复后后端全量 `369 passed`。
- 前端全量 `36 个测试文件 / 165 项` 通过；`npm run typecheck`、`npm run lint -- --no-fix`、`npm run build` 通过。重启 8000 后只读战斗接口返回 200，版本 340、第 15 轮、当前回合玩家。
- 内置浏览器复核 DM 页面存在第 15 轮、结束条件提示、火球术/战斗日志/地图和范围积木；截图：`/private/tmp/dnd-complex-battle-final-20260802.png`、`/private/tmp/dnd-complex-battle-grid-20260802.png`、`/private/tmp/dnd-complex-battle-log-view-20260802.png`。完整日志文件：`docs/artifacts/dnd-complex-battle-log-20260802.md`。

这次是一次长流程验收，不改变未完成边界：雷鸣波失败豁免分支虽已由定向测试证明可执行，但本次长流程恰好没有触发；复杂多段/复合伤害、完整状态来源与结束条件、怪物反应/传奇/巢穴动作 UI、复杂三维区域和全部职业 1–20 级运行时仍不能宣称完成。

## 2026-08-02 五项未自动化边界的本轮收口

- 复合伤害的区域豁免路径现在逐段应用 Evasion/反射型防御：火焰、力场等独立段不会因为被合并在一次区域动作里而绕过逐段减半；持续混合伤害也逐段消费条件性抗性/易伤/免疫，并保留每段应用的防御明细。
- 区域伤害结果现在为处于专注的目标保留专注检定 DC；专注确认接口可消费普通伤害、怪物区域动作和持续伤害 tick 的检定请求。缺少可解析持续伤害表达式时不再静默跳过，而是返回 DM review prompt。
- 前端球形/圆柱形预览的水平体积改为欧氏半径，与后端权威三维几何一致；移动/射程仍保留 5e 方格对角规则。新增回归覆盖球形角落目标不会被错误选中。
- 职业 1–20 级运行时注册表补充无甲防御、资源恢复、反应特性、武僧防御/重骰、确定性优势合同和猎人印记附伤 rider。缺少事件窗口、选项分支或统一条件求值器的特性继续标为 `partial`/`dm_only`，没有把文字字段冒充完整执行。
- DM/玩家界面刷新或轮询后会从持久化效果恢复 `until_save` 状态提示；高级动作 UI 明确显示传奇动作资源、巢穴窗口、反应触发事件和待玩家掷骰状态，不再把刷新后的状态伪造成新的掷骰请求。
- 最终门禁：后端全量 pytest、Ruff、前端 TypeScript、前端 37 个测试文件/181 项、生产构建和 `git diff --check` 全部通过；内置浏览器真实 DM/玩家页面控制台 error 均为空。DM 页面实际显示模拟战斗、雷鸣波/火球术范围规则积木、传奇/巢穴/反应动作窗口；玩家页面实际显示共享地图、标准战斗动作、雷鸣波/火球术/召唤/魔法飞弹等行动。

本轮仍不能宣称五项全部变成无 DM 的全自动规则：职业特性的事件型反应、复杂变形/召唤分支、完整状态组合与规则例外、所有高级动作的实际触发判定仍需继续扩展统一执行器；本轮交付的是可执行的共通结算、失败可见化和前后端验收闭环。
# 2026-08-02 当前继续验收：批量区域结算与职业运行时收口

本次没有把五项“仍未完全自动化”误报为全部完成，实际完成与边界如下：

- 新增 `POST /api/v1/campaigns/{campaign_id}/combats/{combat_id}/actions/confirm-batch`，DM 区域法术确认改为批量提交。服务端会在任何写入前预检目标版本、动作经济、条件防御和每个目标的权威三维区域/视线；第一项才消费动作，后续项使用 `action_cost=none`。新增接口回归测试覆盖双目标、混合伤害分段、动作只消费一次和批量结果日志。
- 职业运行时合同升级到 `1.2`。狂暴、动作如潮、狂暴抗性、等级缩放伤害、反射闪避和偏转攻击的已结构化部分接入现有职业特性消费器；增加执行器能力白名单，未支持的 partial 特性不会生成会失败的动作按钮。灵巧动作、稳定瞄准、直觉闪避、偏转攻击反击分支等仍明确保留 partial。
- 真实门禁：后端 `backend/tests` 全量通过；前端 39 个测试文件、185 项通过；TypeScript、ESLint、生产构建、Ruff、`git diff --check` 全通过。
- 浏览器实际验收：DM `http://127.0.0.1:5173/#/combat` 当前加载元素熔炉模拟战斗，先攻轨道含玩家、两名 AI 怪物和小火元素召唤物；页面显示火焰箭 `1d10/120尺`、雷鸣波 `2d8/自身15尺立方`、火球术 `8d6/150尺20尺球形`、魔法飞弹 `3d4+3/120尺`；控制台 error/warning 为 0。截图：`/private/tmp/dnd-status-20260802-full.png`。

仍不能称为五项全自动：所有职业/子职业 1–20 级特性的真实运行时闭环、复杂状态来源与组合、高级反应的实际减伤/重骰、复杂多段复合事务、完整球体/圆柱/旋转三维遮挡和传送/变形等复杂分支仍需要继续补执行器或 DM 明确输入。

# 2026-08-03 当前续接：战斗稳定性最终门禁与真实双端验收

- 当前源码路径显式运行后端全量 `421 passed`（仅 1 个 Starlette/httpx 弃用警告）；Ruff、`git diff --check`、前端 TypeScript、ESLint、Vitest 39 文件/189 项和生产构建全部通过。
- 真实浏览器重新从模拟剧本重置开始验收：玩家端选择火球术，先点 6,4 落点，再按 20 点伤害提交；范围内熔火术士/熔炉守卫分别按 DC14 敏捷豁免处理，前者扣 20，后者扣 10，法术位从 2/2 变为 1/2。
- DM 返回战斗辅助并开启“怪物全自动”后，熔火术士生成玩家端 `熔炉爆裂` 豁免请求；玩家提交 10 对 DC13 后实际扣 7 点火焰伤害并推进到熔炉守卫。熔炉守卫自动从 `(7,4)` 移到 `(6,3)` 并以 `熔岩重击` 自动攻击，流程继续推进，没有版本冲突或停在“等待怪物动作结算”。DM/玩家快照同时显示敌方橙色可达范围、红色影响范围。
- 验收中发现的两个旧标签问题已区分清楚：玩家旧会话失效会显示 `Failed to fetch`，不是战斗接口逻辑；切到模拟页时 DM 战斗辅助未挂载，不能驱动 AI，也不是 AI 引擎卡死。重新生成玩家会话、回到 DM 战斗辅助并开启自动模式后链路正常。5173 开发服务曾退出，已用当前项目重启后再验收。
- 可复用浏览器证据：`/private/tmp/dnd-dm-pending-save.jpg`、`/private/tmp/dnd-player-pending-save.jpg`、`/private/tmp/dnd-fireball-result-final.png`、`/private/tmp/dnd-summon-initiative.jpg`、`/private/tmp/dnd-dm-combat-regression-fixed-20260802.png`。复杂战斗日志仍在 `docs/artifacts/dnd-complex-battle-log-20260802.md`。

当前边界不变：复杂多段/复合事务的全部规则例外、完整状态来源/结束/组合、怪物反应/传奇/巢穴动作的所有触发判定、复杂三维遮挡、所有职业 1–20 级特性的完整运行时仍需 DM 或后续执行器；不能把规则字段或 `exact` 统计当成全部自动化。

## 2026-08-03 状态生命周期与直接状态入口统一

- `CombatEngineService` 统一状态组合和限制：昏迷推导失能/倒地，震慑/麻痹/石化推导失能；失能类状态禁用动作、附赠动作、反应；束缚/擒抱把速度与剩余移动设为 0；多来源叠加只在最后一个来源结束后恢复基线。
- 豁免与防御链已接入状态：震慑、麻痹、石化、昏迷时力量/敏捷豁免自动失败；束缚时敏捷豁免要求两个骰值并取劣势；石化对全部伤害抗性、对毒素免疫；0 HP 昏迷与恢复正 HP 清理链已接入。
- 浏览器验收发现 DM 快速“加状态”入口原先只改 `conditions`，会出现“昏迷但动作可用”。现已把所有 combatant 条件列表写入接到同一生命周期同步器，直接编辑和结构化效果不再分叉；移除条件也走同一恢复逻辑。
- 回归新增/更新覆盖状态叠加恢复、状态矩阵豁免/石化伤害、直接条件 PATCH 的限制/恢复。后端全量 `432 passed`（1 个既有 Starlette/httpx 弃用警告），Ruff、`git diff --check` 通过；前端本轮无源码变更，既有 TypeScript、ESLint、Vitest `39 文件/190 项`、生产构建通过。
- 内置浏览器真实验收：DM 通过“加状态”写入昏迷后显示“动作已用 · 附赠已用 · 反应已用”；移除后恢复三项可用；玩家端同一战斗卡显示“状态：昏迷”；随后重置模拟战斗恢复 HP、状态、资源和日志。控制台 error/warn 为 0。
- 截图：`/private/tmp/dnd-condition-lifecycle-dm-20260803.png`、`/private/tmp/dnd-condition-lifecycle-player-20260803.png`。
- `mypy backend/src` 仍有 13 个仓库既存错误，位于本次未改文件，未混入本轮修复。

当前边界保持诚实：复杂状态持续/来源/组合、怪物反应/传奇/巢穴动作的完整触发 UI、复杂三维遮挡、所有职业/子职业 1–20 级运行时和复杂多段复合规则仍未全部自动化。

## 2026-08-03 状态回合开始结束后的行动资源刷新

- 修复 `advance_turn` 的生命周期顺序缺口：回合开始先重置行动资源、再处理 `turn_start` 状态结束时，原先会让刚刚解除震慑/麻痹等限制的单位继续保持动作、附赠动作、反应不可用和 0 移动力一整回合。
- 新增 `_refresh_new_turn_resources` 共通刷新器，并在运行时状态、显式结束条件、回合/分钟到期等生命周期路径全部处理完后再次刷新当前单位；限制仍存在时继续保持禁止状态，限制解除后恢复速度上限和完整本回合资源。
- 回归测试：`test_turn_start_condition_expiry_refreshes_new_turn_resources`；验证状态在目标回合开始自动结束后，动作/附赠/反应均恢复、移动恢复到速度上限。原有后端全量测试、Ruff、`git diff --check` 均通过。
- 浏览器验收：DM 模拟战斗重置回第 1 轮且当前单位显示“动作可用 · 附赠可用 · 反应可用”；玩家端 `/player` 正常显示“加入跑团房间”；两端控制台 error/warn 均为 0。截图：`/private/tmp/dnd-condition-turn-start-dm-20260803.png`、`/private/tmp/dnd-condition-turn-start-player-20260803.png`。

本项仍不是所有状态规则闭环：复杂持续来源组合、传奇/巢穴/反应完整触发、复杂三维遮挡和全职业 1–20 级运行时仍在一级待办中。

## 2026-08-03 高级动作确认审计与双端验收

- 修复 `CombatEngineService` 在高级动作确认后丢失审计上下文的问题。传奇动作、巢穴动作和反应现在会把动作窗口写入 `result_json.action_window`，并在普通确认、单目标豁免、批量豁免和玩家最终豁免日志中保留；日志明确显示传奇消耗点数/动作池、巢穴先攻窗口或反应触发事件。
- 新增回归覆盖：传奇动作消耗与窗口、巢穴窗口、反应触发后的玩家豁免以及后续伤害确认；不会改变已有资源门禁或正式结算链。
- 代码与测试已拆分提交：`07633f3 fix: preserve advanced action audit windows`。未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 未加入提交。
- 当前源码门禁沿用本轮已通过结果：后端全量 421 passed（1 个既有 Starlette/httpx 弃用警告）、前端 39 文件/190 项、TypeScript、ESLint、生产构建、Ruff、`git diff --check` 均通过。
- 当前代码真实浏览器验收：DM/玩家同一模拟房间均显示“熔火术士·AI 对模拟玩家·奥术师使用「传奇熔击」；命中并造成 2 点 fire 伤害；传奇动作窗口（消耗 1 点；动作池 3）”；两端快照和日志一致，控制台 error/warn 均为空。
- 当前证据：DM 日志截图 [dnd-advanced-window-dm-log-current-20260803.png](/private/tmp/dnd-advanced-window-dm-log-current-20260803.png)，玩家日志截图 [dnd-advanced-window-player-log-current-20260803.png](/private/tmp/dnd-advanced-window-player-log-current-20260803.png)，完整视图 [dnd-advanced-window-dm-current-20260803.png](/private/tmp/dnd-advanced-window-dm-current-20260803.png) 与 [dnd-advanced-window-player-current-20260803.png](/private/tmp/dnd-advanced-window-player-current-20260803.png)。

本项闭合的是高级动作确认后的可追溯日志与双端一致性，不等于所有反应/传奇/巢穴动作触发条件、复杂状态组合、复杂三维遮挡或全职业 1–20 级运行时都已自动化；这些仍需后续执行器或 DM 确认。

## 2026-08-03 借机攻击触发动作筛选

- 修复玩家移动离开近战威胁范围时，旧逻辑直接取敌人第一个带伤害动作的问题。现在按结构化动作筛选：排除远程、区域、施法、传奇和巢穴动作；优先明确标记为反应/借机攻击的近战动作；旧资料没有 `range_ft` 时保留兼容回退。
- 借机攻击请求现在保留实际使用的动作名、动作类型、近战距离和触发文本；DM 确认后的战斗日志显示具体动作，不再把远程攻击或区域技能误报为借机攻击。
- 回归把“短弓在前、长剑在后”的混合动作表接入真实移动/请求/确认链，确认最终选中长剑、写入触发原因并正确消费反应。
- 后端全量通过；前端 TypeScript、ESLint、39 个测试文件/190 项、生产构建通过；Ruff 与 `git diff --check` 通过。代码提交：`fe35b0b fix: filter opportunity attack triggers`。
- 新后端重启后，DM/玩家模拟战斗页面均正常；两端控制台 error/warn 为空。截图：[dnd-opportunity-filter-dm-20260803.png](/private/tmp/dnd-opportunity-filter-dm-20260803.png)、[dnd-opportunity-filter-player-20260803.png](/private/tmp/dnd-opportunity-filter-player-20260803.png)。

本项闭合的是借机攻击候选动作选择与触发上下文，不等于所有怪物反应的事件矩阵、传奇/巢穴自动触发、复杂状态组合或全职业 1–20 级运行时已经完成。

## 2026-08-04 专注豁免持久化与战斗暂停

- 普通伤害、怪物区域伤害和持续伤害事件现在把专注豁免写成持久化 `concentration_check_prompt`；DM/玩家刷新后仍能恢复同一请求，未提交时服务端拒绝推进回合。
- 专注确认会关闭原请求并写入成功/失败日志；成功保留专注效果，失败结束相关效果和召唤物。玩家端自动结束回合与敌方自动推进也识别该暂停门禁；DM 页显示“专注豁免 · 战斗暂停”。
- 回归覆盖请求持久化、刷新后读取、未提交禁止推进和确认后 `confirmed` 状态。后端 `test_combat_engine.py` 定向测试通过；前端 39 个测试文件 / 190 项、TypeScript、ESLint 通过；`git diff --check` 通过。
- 内置浏览器真实验收：伤害确认后出现 DC 10 专注请求；刷新后请求仍显示；点击结束回合仍停在第 1 轮第 1 回合；输入 12 对抗 DC 10 后日志显示“专注检定成功，维持专注”。全新 DM 页面控制台 error/warn 为空。截图：`/private/tmp/dnd-concentration-paused.png`、`/private/tmp/dnd-concentration-success.png`。
- 代码提交：`e4468db fix: persist concentration checks during combat`。未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 未加入提交。

本项只收口专注请求的持久化和推进门禁；复杂状态组合、怪物反应/传奇/巢穴完整触发、复杂三维遮挡和全职业 1–20 级运行时仍未全部自动化。

## 2026-08-04 恐惧来源可见性与攻击上下文

- 恐慌/恐惧不再无条件给攻击者添加劣势。战斗引擎会读取结构化状态来源、双方网格位置和场景障碍：恐惧来源可见时真实加入攻击劣势；来源被遮挡时不添加劣势；缺少来源、位置、网格或障碍数据时保留 DM 裁定上下文，不擅自猜测。
- 新增回归覆盖可见来源与被墙遮挡来源两条路径，验证攻击上下文和最终攻击规则分别正确。
- 当前工作树验证：后端全量测试通过；`ruff check` 和 `git diff --check` 通过。未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 仍未纳入提交。

本项只收口恐惧状态的视线条件，不等于完整三维遮挡、所有状态组合或全部职业特性已经自动化。

## 2026-08-04 召唤动作的无伤害提示

- 浏览器双端验收发现：召唤小火元素没有伤害骰，却被玩家端显示成“伤害骰未记录”、DM 端显示成“伤害骰未明确”。
- 新增共用 `actionDamageLabel`：有明确伤害段时显示表达式；召唤、治疗、位移、状态和其他结构化非伤害积木显示“无直接伤害”；真正缺少攻击/伤害资料的未结构化动作仍保留“伤害骰未明确”并交给 DM 裁定。
- 玩家和 DM 两端动作选择器已统一使用该标签，复合伤害仍显示各段表达式，不改变结算接口。
- 回归：前端 `combatAutomation` 定向测试 17 项、TypeScript、ESLint 通过；内置浏览器实际看到玩家端“召唤小火元素 · 无直接伤害”和 DM 端同样提示，玩家/DM 页面新增错误均为空。

## 2026-08-04 敌方召唤物基础 AI 边界与双端行动预览

- 前端新增共用 `isEnemyAiControlledCombatant`：只有 `companion + controller=dm + disposition=enemy + enemy_ai_mode=basic` 的敌方召唤物进入自动移动、自动瞄准和自动回合链；玩家召唤物、DM 友方召唤物和 `dm_only` 敌方召唤物不会误入 AI。目标选择改按结构化阵营判断，避免把 DM 友方召唤物当成敌人目标。
- `CombatPage` 的 AI 移动/瞄准不再写死 `entity_type=monster`；`PlayerRoomService` 的玩家安全快照也对敌方基础 AI 召唤物投影 `active_action`，因此玩家端能看到与 DM 相同的当前技能、可达范围和影响范围。PlayerPage 同步识别该快照边界。
- DM 召唤面板新增“敌方召唤物 AI”选择：基础 AI / DM 手动，默认基础 AI；调用现有召唤接口传递 `enemy_ai_mode`，没有新增召唤或战斗执行器。
- 回归新增覆盖：前端 AI 边界与阵营目标 4 条断言；后端玩家快照边界和 `MonsterAIService` 敌方召唤物预览；原有召唤/怪物 AI/玩家房间测试保持通过。
- 真实浏览器验收：模拟战斗中选择“基础 AI”后加入小火元素，先攻卡显示“敌方召唤物”、动作卡显示“灼热爪击 · 1d6+2 · 5尺”；玩家端同一战斗显示该单位、共享地图和敌方当前行动的橙色可达范围/红色影响范围提示。两端新增 console error/warn 均为空。截图：`/private/tmp/dnd-enemy-summon-dm-20260804.png`、`/private/tmp/dnd-enemy-summon-player-20260804.png`。
- 最终门禁：后端全量 `442 passed`（1 个既有 Starlette/httpx 弃用警告）；前端 39 个测试文件 / `195 passed`，TypeScript、ESLint、生产构建、Ruff、`git diff --check` 全部通过。

本项完成的是敌方召唤物的 AI opt-in 边界、先攻后的可见性和双端当前行动投影；召唤物所有复杂模板、复杂召唤生命周期、敌方召唤物高级动作（传奇/巢穴/反应）完整触发和复杂状态组合仍不能宣称全自动。

## 2026-08-04 擒抱关系生命周期与位移解除

- 擒抱现在不是只写入一个中文状态字符串：效果保存 `source_incapacitated` 与 `target_out_of_reach` 结束谓词，并统一使用 `grappled` 的状态限制器；公开状态仍显示“擒抱”。被擒抱目标的速度和剩余移动归零，效果结束时恢复施加前的基线。
- 擒抱来源失能、昏迷、HP 归零或离开战斗时，效果在同一事务中自动结束；被擒抱目标被普通强制位移、玩家豁免后的位移、推撞或直接强制位移推到来源近战范围（默认 5 尺）外时，也自动结束。没有完整网格/位置数据时不猜测距离，交给 DM 裁定。
- 新增回归 `test_grapple_ends_when_grappler_becomes_unconscious`、`test_grapple_ends_when_forced_movement_leaves_reach`；定向擒抱/位移/状态测试 19 passed。
- 全量门禁：后端 `454 passed`（1 个既有 Starlette/httpx 弃用警告）；前端 39 个测试文件 / `196 passed`；TypeScript、ESLint、生产构建、Ruff、`git diff --check` 全通过。
- 内置浏览器真实验收：玩家端成功施加擒抱后，DM/玩家公开日志一致；来源改为昏迷后，目标两端均恢复 30 尺且擒抱解除；第二次擒抱被强制推离 10 尺后，目标地图位置同步为（4,1），两端状态均不再有擒抱。DM/玩家控制台 error/warn 均为空。
- 截图：[dnd-grapple-lifecycle-dm-20260804.png](/private/tmp/dnd-grapple-lifecycle-dm-20260804.png)、[dnd-grapple-lifecycle-player-20260804.png](/private/tmp/dnd-grapple-lifecycle-player-20260804.png)。
- 本项没有改变火球术、雷鸣波、复合伤害、召唤物生命周期或基础怪物 AI。复杂状态组合、复杂三维遮挡、怪物高级动作完整自动触发矩阵和全职业/子职业 1–20 级运行时仍未全部完成。

## 2026-08-05 伤害前反应窗口与直觉闪避

- 普通攻击命中且目标有结构化 `uncanny_dodge` 时，服务端现在在伤害、HP、死亡豁免、专注和状态事务之前创建持久化 `pre_damage` 窗口；攻击命中证据必须来自攻击总值、明确暴击或 DM override，不再用“动作类型是攻击”冒充命中。
- DM 和玩家端都能看到同一个暂停窗口。玩家可以选择“使用直觉闪避”或“不使用”：前者在抗性/易伤/免疫之前对每个伤害段向下取整减半并消费反应，后者正常落地完整伤害且反应保留。窗口版本、来源、攻击者/目标版本和请求幂等键均校验，重复提交不会重复扣血。
- 怪物自动攻击、怪物多重攻击序列、高级动作和自动推进在窗口未处理前都会停止；批量多目标确认遇到该窗口会拒绝，要求先单目标处理，避免部分目标已经扣血。
- 玩家房间快照投影 `kind: pre_damage`，只显示玩家自己或其召唤物可控单位的窗口；新增回归覆盖：窗口暂停、拒绝后完整扣血且反应仍可用、再次命中后接受减半、幂等重放，以及玩家快照显示/处理窗口。
- 最终门禁：后端全量 pytest 通过（退出码 0）；Ruff、前端 TypeScript、ESLint、Vitest 39 文件/202 项、生产构建和 `git diff --check` 全部通过。
- 本轮内置浏览器验收未完成：现有唯一 5173 玩家页被浏览器 URL 安全策略拦截，无法接管页面，因此没有伪造截图、控制台或双端实测结论。下一次应在浏览器允许访问本地页面后，实际验证 DM/玩家同窗、点击直觉闪避、HP 减半、反应消耗和 AI 继续推进。

本项只闭合“直觉闪避”这一种伤害前反应。偏转攻击的减伤骰/归零反击、复杂反应触发矩阵、完整传奇/巢穴动作触发、复杂状态组合、复杂三维遮挡和所有职业/子职业 1–20 级运行时仍未全部自动化。

## 2026-08-05 偏转攻击减伤骰执行

- `deflect_attacks` 已接入已有伤害前反应窗口：命中后先暂停，不扣 HP；玩家输入实际 d10 结果，服务端从冻结攻击伤害中加上敏捷调整值与职业等级后扣除，再进入正常的抗性/易伤/免疫、临时生命、HP、死亡与专注链。
- 仅允许结构化的钝击/穿刺/挥砍攻击触发“偏转攻击”；“拨挡能量”对应的 `eligible_damage_types=all` 可覆盖其他伤害类型。混合伤害按伤害段顺序分配减伤，避免绕过既有逐段防御。
- DM 与玩家端都显示偏转攻击窗口和 d10 输入框；减伤结果归零时日志会标记 `redirect_available`，但 Focus 消耗、反击攻击目标和反击骰仍暂停给 DM，不自动猜测。
- 回归覆盖：d10 + 敏捷调整值 + 职业等级、反应消费、实际 HP 变化、窗口元数据和归零反击边界；直觉闪避与原有玩家快照回归保持通过。
- 最终门禁：后端全量 pytest 通过（退出码 0）；Ruff、前端 TypeScript、ESLint、Vitest 39 文件/202 项、生产构建和 `git diff --check` 全通过。
- 浏览器仍未能验收：现有 5173 页面被内置浏览器 URL 安全策略拦截；没有把代码测试冒充浏览器结果，也没有生成虚假截图。

本项把偏转攻击从“完全阻塞”推进到“减伤分支可执行、归零后反击仍需 DM”。复杂反应触发矩阵、完整反击分支、复杂状态组合、复杂三维遮挡和所有职业/子职业 1–20 级运行时仍未全部自动化。

## 2026-08-05 先天术法与职业检定运行时

- `b5451d3 feat: execute innate sorcery runtime effect`：先天术法可由职业特性动作真实扣除 1 次资源，写入 `innate_sorcery`，持续 1 分钟（10 轮）后自动清理；激活期间只有明确标记为术士法术的攻击获得优势，法术豁免 DC 在玩家攻击/法术路径实际加 1；缺少状态或施法来源时不套用。
- `3e51a04 feat: resolve raging strength check advantage`：战斗玩家检定提示现在消费 `ability_check`/`skill_check` 的结构化条件优势；狂暴力量检定要求玩家报告两枚 d20，取高值，缺第二枚时暂停并报错，不猜骰。
- `572853a feat: execute reliable talent check floor`：非战斗技能检定真实识别可靠才能与技能熟练，玩家报告 d20 小于 10 时按 10 计算，并同时保留 `reported_raw_roll` 和实际 `raw_roll` 审计字段；非熟练检定不触发。
- 验证：每项均独立提交；后端全量测试通过，定向特性/生命周期回归通过，Ruff、compileall、`git diff --check` 通过。未修改前端，未重复前端构建；浏览器本地 URL 安全策略仍限制本轮后端-only 浏览器验收。
- 工作树中 `backend/tests/integrations/`、`backend/tests/ollama.py` 是用户原有未跟踪文件，未纳入提交。
# 2026-08-05 失败豁免后的职业特性即时重掷窗口

- 代码提交 `ee67f64`：玩家豁免第一次失败且目标拥有可用的结构化
  `feature_saving_throw_rerolls` 时，不再立即扣血或消耗资源，而是把动作保持为
  `previewed`，持久化 `awaiting_feature_reroll` 窗口、原始骰值、DC、特性来源和第二次骰值要求。
- 第二次确认必须显式传入 `use_feature_reroll=true` 和两枚豁免总值；运行时取较高值，成功后真实消耗
  一次重掷资格，再沿用原有伤害、状态和战斗日志事务。没有可用资格、缺失第二枚骰或未明确选择时不猜测，
  仍停在 DM/玩家输入边界。
- 玩家豁免面板支持显示“等待职业特性重掷”，并允许填写 `12,18`；打开窗口不会误报为已完成结算。
- 新增后端纯运行时和真实两阶段 API 回归，覆盖窗口持久化、HP 不变、取高值、资格消耗和最终推进。
- 验证：定向后端测试通过；后端全量 `511 passed`；前端 Vitest `39 文件 / 203 项`、TypeScript、ESLint、
  生产构建、Ruff、compileall、`git diff --check` 全部通过。仅有既有 Starlette/httpx 弃用警告。
- 当前工作树保留用户既有未跟踪文件 `backend/tests/integrations/` 和 `backend/tests/ollama.py`，未纳入本提交。
- 本轮未做浏览器实战验收；当前浏览器标签的本地 URL 仍受既有 URL 安全策略影响，不能用代码门禁冒充浏览器通过。
- 仍未完成：复杂状态组合其他例外、完整传奇/巢穴/反应触发矩阵、复杂三维规则边界、全职业/子职业 1–20 级运行时。

# 2026-08-05 狂暴提前结束活动快照闭环

- 代码提交 `9ed5898`：狂暴激活时现在在正确的持续状态分支写入
  `rage_activity` 快照；快照记录对应运行时效果、当前回合是否攻击敌对目标和是否实际受到伤害。
- 普通伤害、区域伤害和持续伤害在实际造成正伤害时记录 `damaged`；狂暴者的攻击确认记录
  `attacked`。推进到狂暴者下一次回合边界时，如果两者都没有发生，服务端真实结束狂暴并清理
  `raging`、运行时效果和活动快照；有任一活动则重置活动标记继续下一回合。
- 狂暴运行时合同由 `partial` 提升为 `full`，不再把该提前结束规则列为 DM 裁定边界。新增纯函数和真实
  API 回归覆盖激活快照、活动保活、无活动提前结束及快照清理。
- 验证：定向特性/战斗/动作生命周期测试通过；后端全量 pytest 通过；Ruff、compileall、
  `git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本切片未修改前端，未把后端门禁冒充浏览器验收。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不是新增缺口；固定范围仍只有 4 个大项。

# 2026-08-05 狂暴维持条件的敌对目标边界

- 代码提交 `87faf99`：狂暴者只有攻击不同阵营的敌对目标才会写入 `attacked=true`；攻击友军、
  自身或同阵营召唤物不能阻止下一回合的无活动提前结束。阵营读取沿用战斗快照的
  `disposition`，缺失时保持角色/召唤物为 ally、其他单位为 enemy 的既有保守规则。
- 新增运行时回归覆盖敌对目标、友军目标和自身目标三条边界；后端全量 pytest、Ruff、compileall、
  `git diff --check` 均通过。此次仍未修改前端，未把后端测试冒充浏览器验收。
- 这是狂暴生命周期同一子项的规则边界补全，不是新增大项；固定范围仍只有 4 个大项。

# 2026-08-05 圣武斩法术位与攻击附伤闭环

- 代码提交 `e8b4fc3`：圣武斩从仅有文字积木改为正式攻击附伤执行器。玩家在近战武器或徒手攻击
  命中后可勾选使用圣武斩，选择 1–5 环法术位并提交光耀伤害骰总值；服务端按环阶生成
  `2d8` 至 `5d8`，暴击时按双倍骰面校验，并通过既有逐段伤害链真实结算。
- 服务端拒绝远程/非近战攻击、缺失环阶、环阶超出 1–5、骰值越界、法术位不足和一次攻击多次
  圣武斩；确认成功后真实扣除对应 `spell_slots_N`，攻击日志保留 rider、环阶和资源键。
- 玩家端新增圣武斩勾选、法术位环阶选择、伤害骰输入和可用法术位提示；不选择时不消耗法术位。
- 验证：后端定向/全量 pytest 通过；前端 39 个测试文件、203 项通过；TypeScript、ESLint、生产构建、
  Ruff、compileall、`git diff --check` 全部通过。仅有既有 Starlette/httpx 弃用警告。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不是新增缺口；固定范围仍只有 4 个大项。
# 2026-08-05 武僧圆融自在失败豁免重掷闭环

- 代码提交 `607b03b`：武僧“圆融自在”从仅有结构化描述提升为可执行职业特性。它复用失败豁免重掷统一结算器，失败后打开即时重掷窗口，提交第二枚骰后以第二次报告值结算，并真实扣除 1 点 `focus`；资源不足、缺少角色资源上下文或重复消费仍 fail-closed。
- 运行时合同新增 `runtime_execution.consumer=saving_throw_resolution`，`automation_status=full`、`requires_dm_adjudication=false`；没有新造一套重掷逻辑，继续与“不屈”共用窗口、资源同步和审计字段。
- 新增回归覆盖：武僧运行时合同、失败豁免 5/18 取 18、Focus 1→0、特性 ID 与资源审计一致。
- 验证：定向特性测试 50 项通过；后端全量 `backend/.venv/bin/pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过。浏览器本轮只做了模拟战斗重置后的 DM/玩家同步检查；固定演练角色是法师，不暴露武僧特性控件，因此没有把浏览器基线冒充为该职业特性的 UI 验收。
- 这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不是新增第五个缺口。固定范围仍只有 4 个大项；高级三维战斗继续跳过。

# 2026-08-06 回气（Second Wind）生命恢复真实执行

- 代码提交 `c9496b9`：战士「回气」从仅有 `1d10+class_level` 描述提升为可执行职业特性。确认时服务端校验战士等级决定的合法治疗范围，真实恢复自身生命并消耗一次 `second_wind` 资源；本例 5 级、HP 10/20、报告 10 点后变为 20/20，资源 1→0。
- 复用现有职业特性动作确认链和效果白名单，新增 `healing` effect kind；运行时合同标为 `full`，不把缺失等级、资源或非法骰值猜成合法结果。
- 新增真实 API 回归覆盖 5 级范围 6–15、非法 5 点拒绝、合法恢复、资源扣除和审计结果。定向测试 2 项通过；后端全量 pytest 通过；Ruff、compileall、`git diff --check` 通过。
- 本轮只修改后端和测试，没有前端源码变化，未重复前端构建，也未做浏览器特性控件验收；不要把后端门禁说成浏览器验收。
- 用户原有未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 仍保留，未纳入提交。这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不新增缺口。

# 2026-08-06 不知疲倦短休减轻力竭真实执行

- 代码提交 `55aa01d`：游侠「不知疲倦」的第二个确定分支接入短休结算。只有角色特性注册表明确包含 `rest_effects: reduce_exhaustion` 时，完成短休才会真实将力竭降低 1 级；结果同步到预览、确认、条件记录和审计日志。
- 中断短休、没有该结构化特性、无效/缺失特性资源追踪信息时均不改变力竭；该分支不消耗不知疲倦的临时生命资源。通用短休解析器新增可复用的显式 `fatigue_reduction` 输入，长休逻辑保持不变。
- 运行时合同和职业资源条目从 `partial` 提升为 `full`。新增纯规则回归和真实 REST API 回归，覆盖 3→2、条件持久化、资源保持 1，以及中断不生效。
- 验证：定向回归通过；后端全量 pytest 通过；Ruff、compileall、`git diff --check` 全部通过。只改后端和测试，没有前端源码变化，未做浏览器特性控件验收。
- 用户原有未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 仍保留，未纳入提交。这仍是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不新增缺口。

# 2026-08-06 反迷惑唯一候选反应重骰

- 代码提交 `b0b9cd6`：吟游诗人「反迷惑」接入现有失败豁免重掷链。玩家豁免明确声明失败后会施加「魅惑」或「恐慌」时，服务端查找同阵营、30 尺内、未失能且仍有反应的唯一吟游诗人；命中条件后先打开重骰窗口，不先写入状态或伤害。
- 第二次确认使用两枚豁免总值取高，真实消耗该吟游诗人的反应，并同步 `feature_reroll_consumed`、反应单位和审计结果；没有权威位置、距离超过 30 尺、多个候选者或没有明确状态时不猜测，保持 DM 裁定。
- 新增运行时合同字段和真实 API 回归，覆盖窗口来源、优势取高、目标 HP 未提前扣除、反应消耗和多个既有重掷路径兼容。定向相关文件和后端全量 pytest 通过；Ruff、compileall、`git diff --check` 通过。
- 本轮只修改后端和测试，没有前端源码变化，未做浏览器特性控件验收。反迷惑仍保留一个明确边界：多个合格吟游诗人需要 DM 选择反应者；这不是已完成的“全部反应矩阵”。
- 用户原有未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 仍保留，未纳入提交。这仍是固定大项“传奇、巢穴、反应动作完整触发矩阵”与“职业/子职业 1–20 级运行时闭环”的交叉内部切片，不新增缺口。

# 2026-08-06 圣疗治疗分支真实执行

- 代码提交 `60f5945`：圣武士「圣疗」的资源池治疗分支接入现有职业特性动作执行器。服务端要求自身或同阵营目标；目标不是自身时必须有权威网格位置且距离不超过 5 尺，治疗量不能超过当前圣疗池，随后真实恢复 HP 并按治疗量扣除资源池。
- 新增 `healing` 运行时效果和审计结果；测试覆盖圣疗池 20→10、盟友 HP 5→15 以及接触距离边界的执行入口。中毒/疾病解除仍未自动猜测，保持 DM 选择，因此合同仍是 `partial`。
- 验证：定向回归通过；后端全量 pytest 通过；Ruff、compileall、`git diff --check` 通过。本轮只修改后端和测试，没有前端源码变化，未做浏览器特性控件验收。
- 用户原有未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 仍保留，未纳入提交。这仍是固定职业/子职业运行时闭环的内部切片，不新增缺口。

# 2026-08-06 反迷惑多候选反应者选择

- 代码提交 `64603a3`：失败豁免重骰命令新增可选 `feature_reroll_reactor_id`。当 30 尺内存在多名合格吟游诗人时，首次失败仍暂停并返回全部候选者；第二次确认必须指定其中一人，服务端重新校验其位置、阵营、状态和反应可用性。
- 选中的反应者取两骰高值并消耗反应，其他候选者不受影响；无效 ID、未确认重掷或过期反应会拒绝，不会扣伤害/状态资源。
- 定向反迷惑双候选回归、运行时合同回归和后端全量 pytest 通过；Ruff、compileall、`git diff --check` 通过。本轮只改后端 schema、执行器和测试，没有前端源码变化，未做浏览器验收。
- 反迷惑剩余唯一自动化边界是缺少权威网格位置时无法自动确认 30 尺距离，继续交给 DM；用户原有未跟踪文件仍未纳入提交。

# 2026-08-06 返本还元回合末状态移除真实执行

- 代码提交 `6d751ee`：武僧「返本还元」新增 `self_restoration` 运行时职业特性积木。回合末可从魅惑、恐慌、中毒中选择一个当前确实存在的状态，服务端白名单校验后真实移除状态，并结束同一目标上对应的结构化运行时效果、恢复状态限制字段。
- 玩家端新增状态选择入口；没有对应状态的选项不可用。非法状态、缺少状态、把选择字段用于其他特性都会 fail-closed；相同幂等请求重放不会重复执行。
- 运行时合同标记为 `full`，没有新增 DM 裁定边界。它只完成返本还元这一确定分支，不代表复杂状态组合与职业/子职业 1–20 级两个固定大项全部完成。
- 验证：返本还元定向 2 项通过；后端全量 pytest 通过；前端 Vitest `39 文件 / 203 项`、TypeScript、ESLint、生产构建、Ruff、compileall、`git diff --check` 全部通过。仅有既有 Starlette/httpx 弃用警告。
- 内置浏览器实际加载 DM 模拟战斗页，页面、地图、技能入口正常；控制台 error/warn 均为空。验收截图：`/private/tmp/dnd-self-restoration-browser-check-20260806.png`。当前模拟角色是法师，页面未暴露返本还元按钮，因此该职业特性的实际执行由后端 API 回归覆盖，没有把法师页面冒充特性控件验收。
- 用户原有未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 仍保留，未纳入提交。固定范围仍只有 4 个大项，高级三维战斗继续跳过。

# 2026-08-06 返本还元合同状态一致性修复

- 代码提交 `b48e9e4`：上一项已完成真实执行，但残留的 `end_turn_condition_removal` 防御条目仍为 `partial`，导致职业特性总合同可能错误显示为部分自动。现在该条目与实际状态选择/移除执行器一致标为 `full`，并明确不需要 DM 裁定。
- 新增合同回归，确认返本还元整体 `automation_status=full`、`requires_dm_adjudication=false` 且没有遗留原因。后端全量 pytest、Ruff、compileall、`git diff --check` 通过；未修改前端，沿用上一项已通过的前端门禁与浏览器页面基线。
- 这是上一项的收口修复，不新增缺口；固定范围仍只有 4 个大项，高级三维战斗继续跳过。

# 2026-08-06 吟游诗人万事通属性检定半熟练加值

- 代码提交 `2a1fe8d`：吟游诗人「万事通」从结构化描述接入玩家属性检定结算。属性检定请求新增显式 `ability_check_proficient`；明确为未熟练时，从角色 `feature_runtime.progression.proficiency_bonus` 取 `floor(PB / 2)`，真实加入最终检定总值并写入 `feature:万事通半熟练加值` 审计来源。
- 明确已熟练时不加万事通；字段缺失时拒绝结算而不是猜测；缺少权威熟练加值时拒绝结算；技能检定和豁免不能误用该字段。战役快照编译也会在存在权威熟练加值时把半熟练值展开到 `rule_modifiers`，没有权威值则保持不可执行。
- 运行时合同升级为 `full`，`runtime_execution.consumer=player_roll_resolution`，`requires_dm_adjudication=false`。新增回归覆盖未熟练 +2、已熟练不加、未知熟练状态、缺 PB 和 schema 边界。
- 验证：定向回归通过；后端全量 pytest 通过；Ruff、compileall、`git diff --check` 通过。浏览器验收未通过加载边界：5173/8000 HTTP 服务正常，但内置浏览器对 `/combat` 的导航、DOM 和控制台读取均超时，未生成或伪造截图。
- 用户原有未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 仍保留，未纳入提交。这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不新增缺口；固定范围仍只有 4 个大项，高级三维战斗继续跳过。

# 2026-08-06 光耀打击攻击附伤自动触发

- 代码提交 `cdc8ff6`：光耀打击的攻击附伤不再要求额外的手工 eligibility。攻击动作明确为武器攻击或徒手攻击时，自动进入已有攻击附伤/逐段伤害链；玩家或 DM 仍需提交 `1d8` 伤害骰结果，服务端校验骰值范围并按 `radiant` 伤害类型结算。
- 保留 `once_per_turn` 防重；非攻击动作不会触发；没有伤害骰输入时不猜测。运行时合同升级为 `full`，消费者为 `attack_damage_resolution`。
- 验证：光耀打击定向回归、合同回归和后端全量 pytest 通过；Ruff、compileall、`git diff --check` 通过。本项只修改后端运行时与测试，沿用前一项浏览器加载阻塞记录，未重复伪造浏览器验收或截图。
- 用户原有未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 仍保留，未纳入提交。这是固定大项“职业/子职业 1–20 级运行时闭环”的内部切片，不新增缺口；固定范围仍只有 4 个大项，高级三维战斗继续跳过。
# 2026-08-06 职业特性统一积木编译层

- 代码提交 `5589f7a`：建立统一 `ClassFeatureBlock` 合同，覆盖 `modifier`、`defense`、`resource`、`action`、`attack_rider` 五类职业特性积木；严格校验类型、来源、等级、自动化状态和 DM 边界，`full` 不允许携带 `requires_dm_adjudication=true`。
- `compile_feature_runtime_registry()` 现在批量生成 `feature_blocks` 和 `feature_block_schema_version`；块 ID 根据职业/等级/特性/类型/来源稳定生成，payload 保留既有 runtime 字段，不逐个技能另造结构。
- 战斗修正、职业防御、攻击附伤、职业动作投影和职业特性确认优先读取 canonical blocks；旧 `combat_start/actions/attack_riders/rule_modifiers` 保留兼容，非职业 legacy 修正不会被覆盖。缺失或非法 canonical block 会 fail-closed，并继续使用旧快照路径。
- 新增回归：五类积木批量生成、ID 稳定、完整自动化与 DM 边界校验、仅保留 canonical blocks 的战斗防御消费者；既有万事通、光耀打击和全职业运行时测试继续通过。
- 验证：后端全量 `pytest -q backend/tests` 通过，当前收集 `485` 项；定向规则/职业/战斗回归通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本轮没有前端改动，未宣称浏览器验收。
- 用户原有未跟踪文件 `backend/tests/integrations/`、`backend/tests/ollama.py` 和 `docs/superpowers/specs/2026-08-06-dnd-terrain-generation-takeover.md` 未纳入提交。
- 这一切片完成度：职业特性“统一积木编译与兼容消费层” `100%`；它属于固定大项“职业/子职业 1–20 级运行时闭环”，不新增第五个缺口。具体职业特性的未结构化分支、复杂反应触发仍按既有四大项边界处理。
# 2026-08-06 职业特性目标策略通用执行器

- 代码提交 `d8e3d2d`：职业动作积木新增通用 `target_policy` 执行器，支持 `self`、`ally_or_self`、`enemy`、`any` 模式、同阵营约束和结构化距离校验；执行器按积木字段工作，不按职业/技能名称分支。
- 吟游诗人激励积木现在声明同阵营、60 尺目标策略；确认时真实校验双方权威网格位置。超距、敌方目标、缺少/非法位置都会拒绝，资源和附赠动作不会被错误消费。其余职业动作可复用同一策略，不需要再造专用校验。
- 新增纯运行时回归覆盖同阵营、60 尺范围和 fail-closed 边界；既有吟游诗人激励 API 回归同步补充权威位置并通过。
- 验证：后端全量 `pytest -q backend/tests` 485 项通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本轮没有前端源码改动，因此未宣称浏览器验收。
- 本轮只提交后端四个任务相关文件。用户/其他任务的 `frontend/src/ui/sceneGridGenerator.ts`、对应测试、`backend/tests/integrations/`、`backend/tests/ollama.py` 和 terrain takeover 文档均未纳入提交。
- 这一切片完成度：职业特性“通用目标策略执行” `100%`；仍属于固定大项“职业/子职业 1–20 级运行时闭环”，不新增第五个缺口。
# 2026-08-06 职业状态生命周期共享积木规格

- 代码提交 `e67f771`：把职业特性状态积木的生命周期规格集中到 `FEATURE_CONDITION_RUNTIME_SPECS`，统一声明状态到运行时 effect 的映射、分钟/回合持续单位和回合边界；编译器门禁与战斗执行器共同消费，避免状态名和清理策略分散在特性分支中。
- 狂暴、先天术法、无懈可击、隐形、鲁莽攻击、稳定瞄准继续复用现有通用 runtime effect 生命周期：重复激活拒绝、状态所有权保留、回合/持续时间结束自动清理；非法或未注册状态积木 fail-closed。
- 没有新增第六类职业积木，仍复用 `action` 积木中的结构化状态效果；新增共享规格回归覆盖有效持续规格和未知状态拒绝。
- 验证：后端全量 `pytest -q backend/tests` 通过（当前 485 项）；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本轮只有后端改动，未宣称浏览器验收。
- 用户/其他任务的 `frontend/src/ui/sceneGridGenerator.ts`、对应测试、`backend/tests/integrations/`、`backend/tests/ollama.py` 和 terrain takeover 文档未纳入提交。
- 这一切片完成度：职业特性“共享状态生命周期规格与执行门禁” `100%`；仍属于固定大项“职业/子职业 1–20 级运行时闭环”，不新增第五个缺口。
# 2026-08-06 子职业动作进入统一职业积木 registry

- 代码提交 `2b38d5e`：升级预览/多职业资源重建现在把已校验的 `after_actions` 传入 `compile_feature_runtime_registry(actions=...)`；子职业动作不再只停留在角色 `actions` 字段，而会进入运行时 `actions` 和 canonical `feature_blocks`。
- 子职业动作继续使用通用 `action` 积木，不按子职业名称新增执行器。当前 `_subclass_action` 只有动作经济、资源和来源等可验证字段，因此保持 `partial`、`requires_dm_adjudication=true`，不会被 `feature_runtime_action_projections()` 投影成会失败的可执行按钮。
- 编译器现在同时读取顶层和嵌套 `runtime` 合同中的 `automation_status` / `requires_dm_adjudication`，避免嵌套合同被错误提升为 `full`。
- 新增真实升级 API 回归：子职业动作进入 runtime registry、进入 canonical action block、仍为 partial/DM 边界且不生成假按钮；多职业资源/法术位定向回归继续通过。
- 验证：后端全量 `pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本轮只改后端，没有新增浏览器验收声明或截图。
- 当前切片完成度：子职业动作的统一 registry/积木接入 `100%`；子职业动作的具体目标、检定、伤害和文本例外仍按积木状态保留 DM 裁定，不把它们误报为全职业效果已完成。固定范围仍是原四大项，高级三维战斗继续跳过。

# 2026-08-06 多职业运行时等级与法术位回归锁定

- 测试提交 `16879b3`：多职业升级回归现在同时断言运行时 registry 保留所有已拥有职业等级（战士 1 / 法师 2），以及共享施法者等级对应的一环法术位为 3 格；此前只断言资源表，未锁定快照/积木层。
- 验证：后端全量 `pytest -q backend/tests` 通过；Ruff、compileall、`git diff --check` 通过。没有修改前端，因此没有新增浏览器验收声明。
- 这是对既有多职业资源/法术位实现的验收加固，不新增缺口；职业/子职业四大项边界保持不变。

# 2026-08-06 子职业动作积木稳定身份

- 代码提交 `03b172f`：通用子职业动作积木现在携带稳定的 `id` 和 `feature_id`，格式为 `subclass_feature_action:<feature_id>`；不再依赖显示名称作为运行时绑定键。
- 重复升级预览会生成相同的 canonical action block ID，便于战斗快照、DM 审计和未来统一执行器追踪来源；动作仍保持 `partial`/DM 裁定，不代表具体子职业规则效果已自动执行。
- 验证：子职业动作定向回归通过；后端全量 `pytest -q backend/tests`、Ruff、compileall、`git diff --check` 全部通过。只改后端和测试，未新增浏览器验收声明。
- 这是职业特性积木基础设施加固，不新增缺口；固定四大项和高级三维战斗跳过范围不变。

# 2026-08-07 伤害前反应通用积木化

- 代码提交 `bcdc9af`：新增 `domain/pre_damage_intervention.py`，提供与特性 ID 无关的配置驱动伤害变换执行器，支持逐段倍率、总量顺序扣减、输入要求/骰值范围校验和 fail-closed。
- 直觉闪避、偏转攻击配置现在发布 `pre_damage_intervention` 合同；战斗候选扫描和确认结算读取合同，不再用 `uncanny_dodge` / `deflect_attacks` 决定真实伤害变换。旧快照字段仅作为兼容适配器；`feature_id` 仍保留在窗口/API/UI 投影中用于显示和选择绑定。
- 偏转攻击归零后的目标选择、Focus、敏捷豁免和反击伤害仍由 `deflect_redirect` 专用兼容适配器执行；本轮没有把它误报成通用 follow-up 积木。其窗口创建已改为依据配置存在 redirect 合同，而非特性 ID。
- 新增纯执行器回归：两个不同配置/不同显示身份复用同一执行器；既有直觉闪避、偏转减伤/归零反击、玩家 API 和 feature runtime 回归均通过。
- 验证：`pytest -q backend/tests`（项目根目录）全量通过；Ruff、compileall、`git diff --check` 通过。仅有既有 Starlette/httpx 弃用警告。本轮无前端源码变更，未做浏览器验收。
- 当前边界：通用积木真实改变伤害命令并保持既有结算顺序；玩家/DM 仍需选择反应、提交偏转骰和后续反击输入；AoE/持续伤害仍不触发 attack-only 伤害前窗口；多候选反应选择策略和 resolving 崩溃租约恢复仍是后续开放问题。用户未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 未纳入提交。

# 2026-08-07 伤害前反应选择与输入强化

- 代码提交 `a13d604`：伤害前窗口冻结全部合格候选，允许 API 显式选择任一候选；非法候选不会消费反应。相同 resolver 请求在窗口处于 resolving/resolved 时可幂等重放，降低响应丢失后的卡死风险；缺少公式实际引用的敏捷/等级权威数据时 fail-closed。
- 代码提交 `5094c71`：`CombatPreDamageReactionCommand` 增加通用 `inputs` 映射，`reduction_roll` 仅作为旧 API 兼容别名；执行器拒绝未声明输入、未知输入类型、未知取整方式和未知分段分配方式，并记录实际输入。新增真实 API fixture 使用第二个不同配置和 `ward_roll` 输入。
- 代码提交 `d317db4`：删除已废弃的直觉闪避/偏转攻击专用伤害 helper，源码中实际伤害变换仅剩通用执行器。
- 验证：伤害前相关整文件、后端全量 `pytest -q backend/tests`、Ruff、compileall、`git diff --check` 均通过；无前端改动，无浏览器验收声明。
- 边界更新：多候选已在后端窗口/API 支持，但玩家页面仍显示主候选，尚未做前端候选选择控件；偏转归零后的 follow-up 仍是明确隔离的专用适配器。用户未跟踪文件继续保留、未提交。

# 2026-08-07 玩家端伤害前候选选择

- 代码提交 `49dbd5c`：玩家房间投影现在安全暴露伤害前窗口的候选特性及其减伤输入要求；玩家页在多个候选时显示选择框，提交所选 `feature_id`，单候选旧行为保持不变。提示文案改为配置中性描述，不把任意配置误称为直觉闪避或偏转攻击。
- 验证：前端 Vitest `39 文件 / 204 项`、TypeScript、ESLint、生产构建全部通过；本地后端/前端启动后，浏览器实际加载 DM 首页和 `#/player` 玩家入口，后端状态正常，控制台 error/warn 为空。没有伪造具体反应窗口截图；当前数据库没有可直接投影的多候选玩家战斗窗口。
- 用户未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 仍未纳入提交。

# 2026-08-08 固定子职熟练批量接线第二批

- 继续复用 `65ed1ac` 的通用 `proficiencies` 合同和升级事务消费者，新增命流武者「操命本事」的洞悉、医药、草药工具固定熟练配置；没有新增特性 ID 执行分支。
- 刺客工具与操命本事均通过真实升级预览、确认和持久化 API 回归，证明同一执行器可被两个不同子职业复用。
- 499 条审计现在为 `full 163 / partial 244 / dm_only 92`，相对 `full 161` 基线真实净增 `+2`；当前完成率约 `32.7%`。预审状态更新为 `already_full 163`、`missing_runtime_contract 226`、`consumer_partial 50`、`needs_contract_review 14`、`manual_boundary 11`、`missing_source 35`。
- 仍未接入：附赠熟练、战争学者、钢铁意志等选择型熟练；含额外法术/动作/资源分支的特性不能因其中一条熟练字段而标 `full`。
- 定向测试已通过；随后必须继续跑全量后端 pytest、Ruff、compileall、`git diff --check`，代码与文档分开提交。用户未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 继续保留。

# 2026-08-07 自动化迁移工厂首批：固定子职工具熟练

- 代码提交 `65ed1ac`：新增迁移预审器 `scripts/plan-feature-automation-migrations.py`。它固定审计范围 499 条，区分 `already_full`、缺运行时合同、消费者不完整、人工边界、缺源码和待合同复核；预审候选不会自动改成 `full`。
- 新增通用 `proficiencies` 运行时合同与注册表消费。生产配置只声明工具种类、名称和 `grant` 操作；升级事务把固定、结构化的子职工具熟练写入角色权威 `proficiencies`，不按执行器中的特性 ID 分支。
- 首个真实使用者：游荡者·刺客「刺客工具」固定授予易容工具、毒药工具熟练。预览、确认和持久化升级 API 回归均验证状态真实写入；499 条审计从 `full 161 / partial 246 / dm_only 92` 变为 `full 162 / partial 245 / dm_only 92`，真实净增 `+1`。
- 当前迁移预审状态：`already_full 162`、`missing_runtime_contract 227`、`needs_contract_review 14`、`consumer_partial 50`、`manual_boundary 11`、`missing_source 35`。这些是执行准备状态，不是可承诺的新增 full 数量。
- 仍需玩家/DM 输入：选择型附赠熟练、战斗风格、武器精通和其他开放分支仍保持原边界；本批没有把选择字段或特性名称误报为完整效果。
- 验证：相关定向测试、`backend/.venv/bin/pytest -q backend/tests` 全量通过；Ruff、compileall、`git diff --check` 通过。文档与审计产物另行提交；用户未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 未纳入提交。本轮无前端源码变更。
# 2026-08-08 长执行：命流武者命中后伤害积木与治疗动作底座

- 代码已提交为 `e261197`；本交接文档与审计报告单独提交，必须保留的两个未跟踪测试路径未加入提交。
- 新增通用命中后伤害绑定：`post_hit_rider` 的 `@binding` 可绑定权威 `dN` 骰面或属性调整值；服务端只校验玩家/DM 提交的最终骰值范围，不替玩家掷骰。
- 新增通用命中后骑手资源提交回写：立即结算的骑手把声明的资源消费计划传回攻击流水线，在攻击确认后通过现有角色资源 CAS/幂等链扣除；旧骑手没有资源计划时行为不变。
- 真实生产配置：命流武者「夺命之手」接入每回合一次、徒手/武僧武器命中后、消耗 1 Focus、`武艺骰+感知调整值` 暗蚀附伤；动态武艺骰与感知值来自权威战斗快照。真实 API 回归覆盖命中、附伤、Focus `2→1`、目标 HP 变化。
- 新增通用 `attack_rider_overlays` / `action_overlays` 配置编译层，允许后续子职用 typed ID 叠加已有骑手或动作，不把子职 ID 写进执行器。
- 「予命之手」已接入普通魔法动作治疗动作底座（Focus、5 尺同阵营目标、武艺骰+感知调整值边界），但疾风连击免费替换仍 partial；「生死之触」已接入命中后中毒覆盖和予命之手状态解除选项，但因予命之手完整免费替换/解除链未完，整体保持 partial，未为了数字误报 full。
- 审计固定分母 499：`full 167→168`、`partial 241→240`、`dm_only 91`，本轮净增 `full +1`；`予命之手`与`生死之触`仍 partial。
- 验证：命流运行时单测、真实攻击 API、运行时/推进/审计定向测试、后端全量 pytest、Ruff、compileall、`git diff --check` 已通过（仅既有 Starlette/httpx 弃用警告）。未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 未加入提交。
# 2026-08-08 长执行续批：持久化命中后骑手伤害提交

- 追加代码尚未提交；上一批代码 `e261197` 已提交，文档提交 `a20027a` 已记录前一批状态。
- `resolve_post_hit_rider_request` 现在支持已验证的 `damage` 结果在同一事务内结算：读取骑手报告的伤害段、复用既有伤害防御/临时生命/0 HP 生命周期，随后再写入骑手效果、资源 CAS、角色快照版本与幂等审计。
- 这是通用持久化消费者，不识别震慑拳、夺命之手等特性 ID；新增回归把通用命中后豁免失败骑手配置为 `1d4` 毒素伤害并真实验证目标 HP `36→33`、中毒状态仍写入。
- 本续批没有误升审计状态；固定分母仍 `full 168 / partial 240 / dm_only 91`。`予命之手`普通治疗和「生死之触」覆盖仍因疾风连击免费替换/治疗状态分支保持 partial。
- 门禁：后端命中后/命流定向回归、运行时/审计定向回归、Ruff、compileall 已通过；需在提交前再跑后端全量 pytest 与 diff check。未跟踪测试目录和 `backend/tests/ollama.py` 保持不动。
- 本批全量后端 pytest、Ruff、compileall、`git diff --check` 已通过（仅既有 Starlette/httpx 弃用警告）。
# 2026-08-08 长执行续批：狂热者/妖精漫游者命中后附伤

- 新增两个生产配置使用者，共用持久化 `post_hit_rider` 消费者：狂热者道途「神性之怒」在狂暴期间每回合首次武器/徒手命中附加 `1d6 + ⌊野蛮人等级/2⌋`，每次由玩家选择光耀或暗蚀；妖精漫游者「哀惧灵袭」对武器命中目标每目标每回合附加 1d4 心灵伤害，游侠 11 级绑定为 d6。
- 骑手输入链新增权威等级绑定（`barbarian_level_half`、`dreadful_strikes_die`）和结构化伤害类型选择；绑定值从冻结战斗快照的 `progression.class_levels` 生成，持久化后续结算再次使用同一绑定，未知/缺失值 fail-closed。执行器不识别狂热者或妖精漫游者 ID。
- 真实通用状态行为：命中确认后生成可审计骑手窗口；玩家提交选择与伤害总值后，沿既有伤害防御、抗性、临时生命、0 HP 生命周期和幂等链结算。新增域回归覆盖动态骰面、伤害类型选择和一次/每目标频率；现有持久化骑手 API 回归继续覆盖 HP 写入与重放。
- 固定分母 499 的审计从 `full 168 / partial 240 / dm_only 91` 变为 `full 170 / partial 238 / dm_only 91`，本批真实净增 `full +2`；距离用户目标 `full≥223` 还差 53。预审 readiness 为 `already_full 170 / missing_runtime_contract 220 / consumer_partial 49 / needs_contract_review 14 / manual_boundary 11 / missing_source 35`，仍不是可直接承诺的新增数。
- 仍未自动化：其他骑手的资源/豁免/多分支组合、狂热者 14 级复生反应、魂刃撕裂心智、刺客致命袭杀等复杂特性；本批没有改动前端，也没有把 DM/选择边界误报为 full。
- 验证：后端全量 `backend/.venv/bin/pytest -q backend/tests`、Ruff、compileall、`git diff --check` 通过。未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 保持不动。
# 2026-08-08 长执行续批：核心职业子职选择授予合同

- 核心职业表中 12 条“获得子职/子职业”选择授予行接入通用 `advancement` contract：选择键为 `subclass`，消费者为现有 `advancement_service`，实际候选校验和 `Character.subclass_choices` 持久化沿用既有升级事务。
- 仅提升“选择/授予行”状态；明确排除“子职特性/子职业特性”占位行，具体 241 条子职效果仍由各自运行时积木独立审计，不会因为选择已持久化而误升。
- 固定分母 499 的审计从 `full 170 / partial 238 / dm_only 91` 变为 `full 182 / partial 238 / dm_only 79`，本批真实净增 `full +12`；距离用户目标 `full≥223` 还差 41。预审 readiness 为 `already_full 182 / missing_runtime_contract 208 / consumer_partial 49 / needs_contract_review 14 / manual_boundary 11 / missing_source 35`。
- 验证：升级/子职矩阵定向回归、后端全量 `backend/.venv/bin/pytest -q backend/tests`、Ruff、compileall、`git diff --check` 全部通过（仅既有 Starlette/httpx 弃用警告）。未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 保持不动。
# 2026-08-08 长执行续批：第三施法者、类型化熟练、20级属性与心灵防御

- 本轮代码提交（与交接文档分开）：`60140bc`、`68d16ef`、`5c9defc`、`d190a42`、`f3112e7`；对应文档提交：`98fab4e`、`98ba404`、`95538e5`、`1caf440`、`4164e11`。
- 固定分母 499 的最新严格审计：`full 189 / partial 233 / dm_only 77`。相对接管时 `full 182`，本轮真实净增 7；不能把配置候选数或选择持久化本身当成 full。
- 新增第三施法者 `施法` 子职合同：奥法骑士、诡术师的既有第三施法者法术位、准备法术校验和 `spell_economy_service` 消费被显式登记为 full；没有伪造法术列表。
- 新增类型化选择熟练合同：逸闻学院附赠熟练的三项技能写入 `Character.skills` 并进入真实技能检定；战斗大师战争学者使用 `skill:<名称>` 与 `tool:<名称>` 分组选择，写入技能/工具熟练；未知、重复、错误分组选项 fail-closed。
- 新增固定属性提升合同：野蛮人原初斗士、武僧天人合一在升级事务中真实应用 +4 与 25 上限，体质变化沿既有 HP 调整链计算；后续属性提升读取已持有的类型化属性上限。
- 新增心灵防御：心灵伤害抗性由权威伤害防御链消费；只有对抗/终止魅惑或恐慌的豁免才获得优势，普通豁免不会误加。
- 本轮定向测试、后端全量测试、Ruff、compileall、`git diff --check` 已通过；仅有既有 Starlette/httpx 弃用警告。`backend/tests/integrations/` 与 `backend/tests/ollama.py` 仍未跟踪、未纳入提交。
# 2026-08-08 长执行纠偏与受控法术授予批次

- 用户明确要求批量迁移以高吞吐推进，不能把“真实闭环”当成替代产出指标；后续交付批次硬门槛为审计固定分母 499 的 `full` 净增至少 25，未达到不结束批次、不把候选覆盖数报成完成数。
- 本批代码提交：`69eb4a3 feat: automate controlled spell grants`；文档提交：`a7faa6d docs: record controlled spell grant migration`。
- 真实新增 `full +10`：逸闻学院魔法探秘、塑能/幻术/防护/预言学者、魔契师六至九环玄奥秘法、四象武者掌控元素。受控选择已写入角色法术状态；秘法动作消费对应长休资源；四象法门写入感知施法属性；重放、越级、错来源/学派/环阶均 fail-closed。
- 当前固定审计：`full 199 / partial 223 / dm_only 77`，距离用户此前要求的 `full≥223` 还差 24；候选积木覆盖仍是重叠统计，不计入完成度。
- 门禁：定向升级选择测试 24 项、Ruff、compileall、`git diff --check` 已通过；全量后端 pytest 需取得明确退出摘要后才可宣称通过。用户未跟踪的 `backend/tests/integrations/`、`backend/tests/ollama.py` 保持原样、未加入提交。
- 下一批执行策略：并行预审多个同构簇，优先选择已有持久化消费者且可一次覆盖 10 条以上的职业/子职业特性；禁止为单条反应、复杂召唤、随机表和只落库特性新建孤立积木。只有真实配置、消费者、状态/资源/动作链、幂等和测试全部成立才升 `full`。
# 2026-08-08 条件防御与网格传送积木（严格复核后仅 +2）

- 代码提交：`fcf290f feat: add conditional defenses and grid feature teleports`；文档仍需单独提交。
- 新增通用 `required_conditions` 防御门禁：条件不全或合同非法时 fail-closed；伤害抗性和状态免疫都读取同一结构化条件。真实生产使用者为星辰结社「灿若繁星」：先由部分自动化的「星耀形态」权威动作消耗荒野变形、写入 10 分钟状态，再由伤害消费者给予钝击/穿刺/挥砍抗性。星耀形态的星座分支仍未实现，故它仍为 partial；灿若繁星规则本身完整，计 full。
- 新增通用网格传送：明确目的格、地图范围、距离、阻挡、占位均由权威地图校验，触发/动作重放继续复用既有幂等与资源链。真实完整使用者仅奥法骑士「奥能冲锋」（动作如潮后，30 尺内传送），计 full。
- 严格复核后主动降回 partial：魂刃「灵魂之刃」虽已能执行心灵传送，但同一特性还有未命中后的寻的斩击；诡术领域「诡诈换位」依赖尚未建模的召现分身实体与“创造/移动分身”触发；闪烁星座、风暴降生、四象遁术均缺权威前置激活状态。均不可计 full。
- 当前固定审计：`full 201 / partial 221 / dm_only 77`，相对上一已提交审计真实净增仅 `+2`，距离 `full≥223` 尚差 22。本切片不构成用户要求的高吞吐批次；必须继续累计实现，不得以此停工或汇报为阶段完成。
- 验证：feature blocks/runtime/runtime combat 定向 99 项通过；Full of Stars 激活→伤害端到端通过；Ruff 通过。全量后端门禁需要在下一完整累计批前重跑并取得退出摘要。未跟踪 `backend/tests/integrations/`、`backend/tests/ollama.py` 保持不变。
# 2026-08-08 长执行检查点：魔能掌控、灵能力量与战神祝福

- 当前固定审计总数 499，最新真实状态：`full 246 / partial 179 / dm_only 74`。本 Goal 起点为 `227/195/77`，真实净增 19；继续推进至安全候选耗尽或需要高风险基础系统，不因超过 223 停止。
- `魔能掌控`：复用 `秘法回流` 的一分钟仪式、使用权和契约法术位资源，将恢复公式覆盖为 `all_expended`。休息服务校验资源余额、公式、角色版本和幂等重放，恢复全部已消耗契约法术位；代码 `ce1becc`。
- `灵能力量`：灵能武士和魂刃各自绑定 `psionic_dice:<class>` 真实资源。等级表决定 d6/d8/d10/d12 与上限；短休恢复一枚、长休恢复全部；升级写入角色资源，运行时 registry 将资源交给既有灵能动作消费者。资源生产本身不代替其它灵能特性的附加效果；代码 `ce1becc`。
- `战神祝福`：感知调整值（至少1）次数、长休恢复、30尺可见/可听攻击检定目标、反应 +10。真实 `player-roll` 窗口消费资源与反应，检定成功/失败和相同幂等请求均由 CombatEngine 持久化；代码 `1f5fa37`。
- 当前已审计但保留 partial 的主要阻塞：其余掷骰干预候选带标记目标、随机奇偶、状态/光环、额外攻击或多模式；战斗大师“坚韧”缺战技骰池与每回合替代入口；荣耀“辉煌防御”缺反击攻击分支；越野/盲视/复杂移动缺权威感知与地形消费者。不得以配置、helper 或单分支升级。
- 本次代码提交与 docs/交接提交必须分离。完整门禁：`backend/.venv/bin/pytest -q backend/tests`、Ruff、compileall、`git diff --check`。必须保留且不得暂存/提交 `backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-09 现有 production_closed 消费者批量迁移 II

- 本批接管时实际基线为 `full 314 / partial 124 / dm_only 61`，收尾审计为
  `full 315 / partial 123 / dm_only 61`；固定分母仍为 499，真实净增 `+1`。
- 新增 `verified_mapping` FeatureSpec：
  - 圣武士·荣耀之誓·3「绝伦健将」：现有 bonus-action feature action 一次消费
    `channel_divinity`，同一事务持久化运动优势、特技优势和跳跃距离 `+10` 三个长休限时修正；
    资源 CAS、幂等重放、版本冲突和三项 modifier 快照写入均有真实 API 回归。
  - 战士·战斗大师·18「究极战技」：复用既有卓越骰表和角色资源存储，`6d12`，短休/长休恢复，
    升级/降级精确重建与 d12 profile 回归已覆盖。
- 为支持一个动作内的多个限时修正，`combat_service.confirm_feature_action` 现在按动作一次清理
  同源旧 modifier，再按效果独立生成稳定 ID；此前会被后一个效果覆盖的通用消费者缺陷已修复。
- 「坚韧 Relentless」明确保留 `partial`：现有资源表不等于每回合一次免费战技骰支付消费者，
  缺少权威支付窗口/CAS，禁止误报 full。
- Feature IR 当前 14 条正式映射，semantic parity 全部通过；本批新增映射仍是
  `verified_mapping`，生产 authority 继续是已验证的 typed runtime registry，直到直接 materializer
  parity 证明完成。完整批次证据见
  `reports/feature-ir-production-consumer-batch-II-2026-08-09.json`。
- 本轮无前端源码变化，不运行/宣称前端或浏览器门禁。必须保留且不得暂存/提交：
  `backend/tests/integrations/`、`backend/tests/ollama.py`。

# 2026-08-10 批量吞吐恢复与真实语料编译器（第一切片）

- 固定分母 499；实时审计从 `315/123/61` 变为 `317/121/61`，本切片真实净增 `+2`。
- 新增真实语料 cluster census：`scripts/feature-ir-semantic-cluster-census.py` +
  `reports/feature-ir-semantic-cluster-census-2026-08-10.json`。结论：121 条 partial
  中 119 个 exact 语义簇，最大簇仅 2 条；不存在任何 ≥8 条的真实同构簇。这是
  “为什么不能按关键词一次性收割 20+ 条”的客观证据。
- 新增批量装配层：`domain/feature_batch_declarations.py` 用声明表一次生成同形状
  特性的 typed runtime 配置，并注册进 `SUBCLASS_FEATURE_RUNTIME_CONFIGS`。
  本切片真实闭环 2 条：
  - 野蛮人·狂热者道途·14「神之狂暴」：长休资源附赠动作激活 `divine_rage` 条件，
    飞行移动模式与暗蚀/心灵/光耀抗性由现有 resolver 消费；E2E 覆盖激活、回合推进后
    飞行出现、幂等重放、版本冲突。
  - 吟游诗人·舞蹈学院·3「炫目舞步」：未着装护甲时 `10+Dex+Cha` 无甲防御公式与
    魅力检定优势由 world_service/player-roll resolver 消费。
- 引擎通用扩展：`FEATURE_CONDITION_RUNTIME_SPECS` 与 `_RUNTIME_STATE_CONDITIONS`
  增加 `divine_rage`；modifier resolver 支持 `while:<condition>` 通用谓词前缀。
- 未达到 20 条门槛：剩余 partial 依赖攻击骑手、多目标/光环、强制移动、召唤、目标信息、
  法术上下文等未接线机制。Goal 保持 active，本切片不关闭。
- 门禁：后端全量 pytest、Ruff、compileall、`git diff --check` 通过；报告生成器
  连续两次哈希一致。无前端改动，不运行前端门禁。规定未跟踪路径保持原样。

# 2026-08-10 批量吞吐恢复第二切片：狂暴激活触发器

- 实时审计从 `317/121/61` 变为 `318/120/61`，本切片真实净增 `+1`（累计 `+3`）。
- 新增通用 `after_rage_activation` 触发事件（`TRIGGER_EVENTS` + 战斗执行器
  `_apply_rage_activation_triggers`），配置驱动、无特性名分支，当前支持
  `grant_temporary_hp`（含 `class_level_source` 等级绑定）。
- 批量表新增「圣树活力」（野蛮人·世界树道途·3）：激活狂暴时获得等于野蛮人等级
  的临时生命。E2E 覆盖真实狂暴动作→条件生效→临时生命写入，以及重放/版本冲突。
- 三个真实闭环特性均来自同一批量装配层：神之狂暴、炫目舞步、圣树活力；
  完整证据见 `reports/feature-ir-production-consumer-batch-III-2026-08-10.json`
  与 census 报告。
- 仍未达到 20 条门槛；剩余 partial 仍需逐机制建设（多目标/光环、强制移动、
  召唤、目标信息、法术上下文、回合开始触发等）。Goal 保持 active。

# 2026-08-10 批量吞吐恢复第三切片：IR 条件门控被动缺口审计

- 目标要求"净增 full ≥20 且 ≥10 条 direct IR authority"。为把已闭合的
  registry 特性切到 FeatureSpec/materializer authority，本轮对 IR 做了原型验证：
- 神之狂暴（自启 buff：消耗资源 + 激活条件 + 门控飞行/抗性）无法用现有 IR
  operator 表达，精确 blocker：
  - `grant_resistance` / `grant_movement_mode` 的 contract 只接受
    `advancement_confirmed` trigger、`none` action economy、persistent duration；
    不支持 `explicit_activation` + `bonus_action` + `one_minute`。
  - movement materializer 丢弃 `applies_when`（无法把飞行门控到激活条件）。
  - resistance/movement resolver 不消费 `applies_when` 条件门控。
- 结论：要让"激活类 buff"成为 IR authority，需要新增 IR 能力（explicit 激活的
  条件门控被动），这是下一个机制轮的目标。当前已闭合的 3 条（神之狂暴、
  炫目舞步、圣树活力）继续由 registry authority 驱动并有 E2E 证据。
- 审计仍为 `318/120/61`（499 分母不变）。工作树只保留规定未跟踪路径。

# 2026-08-10 批量吞吐恢复第四切片：direct IR/materializer authority 落地

- 把已验证的批量特性切换到 FeatureSpec/materializer 权威，共 2 条：
  - 神之狂暴：`dnd2024.subclass.barbarian.zealot.divine-rage`（authored_ir），
    clause 含 `consume_resource` + `activate_condition` + `grant_resistance`×3 +
    `grant_movement_mode`，编译 full、审计 authority=compiler，E2E 走 IR 生成的
    feature_action（resource_key=divine_rage、effects=[activate_duration_condition]）。
  - 炫目舞步：`dnd2024.subclass.bard.college-of-dance.dance-virtuoso`（authored_ir），
    clause 含无甲防御公式 `10+Dex+Cha` + 魅力检定优势。
- 为此修复的通用 IR 缺口：
  - `grant_resistance`/`grant_movement_mode` 合同支持 `explicit_activation` +
    bonus action + 战斗时长 + `applies_when`。
  - `grant_passive_modifier` 支持 `formula`（无甲防御）。
  - materializer 把 `damage_type` 投影为运行时 `damage_types`、透传 `applies_when`。
  - `materialize_runtime_definition` 为 explicit 激活 clause 组装可执行
    `feature_action`（kind/resource_key/resource_cost/effects），并把
    `activate_condition` 投影为 `activate_duration_condition` 效果。
  - 抗性 resolver 消费 `applies_when` 条件门控（目标带条件才生效）。
- 圣树活力维持 registry authority（`after_rage_activation` 触发器暂未进 IR）。
- 审计 `318/120/61`；formal IR 16 条（authored 12 / verified 4），
  compiler_pilot 16。全量 pytest、Ruff、compileall、diff-check 通过。
- 相对目标的进度：净增 full 3/20、direct IR authority 2/10、≥8 条簇 0/1。

# 2026-08-10 批量吞吐恢复第五切片：目标信息读取与 IR 权威扩展

- 本切片把「猎人学识 Hunter's Lore」接入真实 Feature IR/materializer：
  `expose_authorized_target_information` 物化为只读 `feature_action`，
  通过角色快照 `current_hunters_mark_target_id` 绑定目标，并由战斗权威防御字段
  返回抗性、免疫和易伤。
- 真实 API 回归覆盖：非当前回合只读使用、目标版本校验、错误目标/缺失标记
  fail-closed、幂等重放、actor stale CAS；只读检查持久化审计结果但不递增
  actor/target combatant 版本。修复了只读动作在加载动作积木前引用未定义变量的顺序缺陷。
- 追加 7 条已有 production-closed 消费者的 authored IR/materializer authority：
  心灵防御、高效重击、操命本事、刺客工具、法术抗性，以及灵能武士/魂刃的
  灵能力量；`set_resource_profile` 现在保留短休恢复一枚、长休全恢复的自定义恢复事件。
  这些是 authority/证据扩展，不重复计入已有 full。
- 当前严格审计仍为 `full 320 / partial 118 / dm_only 61`，固定分母 499；
  formal IR 共 25（authored 21 / verified 4）。本切片真实新增 full 为 0，
  因而相对本 Goal 起点 `318/120/61` 的净增仍为 `+2`；不能把 IR authority
  扩展或已有 full 的重复映射冒充新增 full。
- semantic census 当前仍显示 partial 最大 exact 簇为 2，未达到 ≥8 条 partial
  同构簇。Goal 保持 active；下一步必须建设一个可复用且有真实 producer/consumer、
  多目标或反应窗口、CAS/幂等和 E2E 证据的新高扇出机制，不能靠 alias/配置升格。
- 门禁：本切片定向 pytest 已通过；完整后端 pytest、Ruff、compileall、git diff
  --check 仍需在提交前重跑。无前端源码变更，不运行/宣称前端或浏览器验收。

# 2026-08-10 统一 Content IR 批量 Workbench

本轮严格单线程执行，没有创建、调用、委托或等待子代理。唯一写入副本为本运行仓库；
`backend/tests/integrations/` 与 `backend/tests/ollama.py` 始终保持未跟踪、未暂存、未提交且
逐文件哈希不变。

## 真实基线

- 固定职业/子职业审计分母仍为 499：`full 328 / partial 110 / dm_only 61`。
- 原版 2024《玩家手册》法术：`411` 条 `spells` 记录，其中 `391` 条详情候选、20 条列表/规则页。
- 原版 2014《玩家手册》法术：`372` 条 `spells` 记录，其中 `361` 条详情候选、11 条列表/规则页。
- 全部本地法术记录为 1314 条；官方/第三方/unknown 为 `786 / 293 / 235`；
  版本为 `2024 / legacy / 2025 / unknown = 412 / 376 / 5 / 521`。
- 本轮没有改原版数据库、正式 feature/spell registry、campaign、character snapshot 或正式 audit 状态。

## 已实现

- `backend/src/dnd_dm_assistant/application/content_ir_workbench.py`
  - Feature Draft 与独立 Spell Draft；
  - 共用 source provenance、record ID、source/spec fingerprint、pack/namespace、ruleset、
    clause identity、compiler/capability registry、blocker、replay/idempotency 和 report schema；
  - Feature Draft 只允许进入现有 FeatureCompiler 的 authored/verified typed 路径；
  - SpellSpec 覆盖 attack/save、damage、healing、temporary HP、condition、area、duration、
    concentration、movement、summon/creation、resource、upcast、modifier 和 target selection；
  - 未知 Spell clause、未知字段、缺 typed 参数、source fingerprint 冲突均 fail-closed；
  - 详情正文二次边界截断，避免串入下一法术或 stat block。
- `backend/src/feature_workbench/`
  - `scan`、`extract`、`compile`、`dry-run`、`report`、`scan-all-official` 统一命令；
  - dry-run 只写 `/tmp/content-ir-workbench/<pack-id>/` 或调用方指定隔离目录；
  - 支持重复运行幂等、target ownership/conflict、source fingerprint conflict、重复 ID 拒绝、
    staging rollback 和 byte-identical report。
- `backend/tests/test_content_ir_batch_workbench.py`
  - 覆盖 2024/2014 分离、官方/第三方/unknown 隔离、索引排除、正文边界、Draft 不升 full、
    最小 typed Feature/Spell full、未知 clause、缺字段、重复 ID、fingerprint conflict、dry-run
    隔离、回滚、报告幂等和保护路径校验。

## 真实官方扩展包扫描

本地注册表自动发现 6 个官方扩展包，而不是只写死四本书。所有真实内容均为 source-backed
Draft，当前没有 authored typed IR，因此没有任何扩展包被误报为 full：

| pack_id | source_record_count | feature | spell | feat | other player option | draft | full/partial/manual/invalid |
|---|---:|---:|---:|---:|---:|---:|---|
| `xanathars-guide` | 325 | 25 | 95 | 1 | 20 | 141 | 0/0/141/0 |
| `tashas-cauldron` | 144 | 48 | 21 | 1 | 2 | 72 | 0/0/72/0 |
| `fizbans-treasury` | 113 | 2 | 7 | 1 | 5 | 15 | 0/0/15/0 |
| `book-of-many-things` | 195 | 0 | 3 | 1 | 3 | 7 | 0/0/7/0 |
| `bigbys-glory` | 177 | 1 | 0 | 1 | 6 | 8 | 0/0/8/0 |
| `mordenkainen-multiverse` | 316 | 0 | 0 | 0 | 0 | 0 | 0/0/0/0 |

机器可读真实结果：

- `/tmp/content-ir-workbench/all-official.json`
- `/tmp/content-ir-workbench/<pack-id>/source-inventory.json`
- `/tmp/content-ir-workbench/<pack-id>/drafts/`
- `/tmp/content-ir-workbench/<pack-id>/manifest.json`
- `/tmp/content-ir-workbench/<pack-id>/compile-result.json`
- `/tmp/content-ir-workbench/<pack-id>/dry-run-result.json`
- `/tmp/content-ir-workbench/<pack-id>/compiled-runtime-preview.json`
- `/tmp/content-ir-workbench/<pack-id>/report.json`

最大 blocker 仍是没有可信 authored Feature/Spell IR；官方来源和字段可读性都不等于 full。
当前真实 completion unlock ranking 为空/为 0，因为本轮没有 production-closed typed clause
成员；不能据此推荐新的底座。新扩展包只要提供符合闭集 schema 的 typed IR，即可自动进入
schema/source fingerprint/compiler/materializer/validator/dry-run/隔离导入链，但自然语言或
generated draft 仍不能直接声称 full。

## 验证

```text
PYTHONPATH=. backend/.venv/bin/pytest -q backend/tests
backend/.venv/bin/ruff check backend/src backend/tests
PYTHONPATH=. backend/.venv/bin/python -m compileall -q backend/src backend/tests
git diff --check
```

# 2026-08-11 Compile Full → Production Runtime Full 批量收口

- 本轮严格单线程执行；保护路径 `backend/tests/integrations/`、`backend/tests/ollama.py`
  仍保持未跟踪、未暂存、未提交。
- 基线 100 条 `compile_full=100 / runtime_preview_full=100 / production_runtime_full=20` 未被
  覆盖。新增 authored IR 独立位于 `data/content-ir/authored/batch-III/`：13 条，13/13 compile
  full，13/13 production full。
- 真实生产 API 批量收口：26 条 Spell + 5 条 Feature 全部 preview→confirm→replay 成功；新增
  production full=31，最终 production full=51；最终 Spell=41、Feature=10。
- 跨包最终 Spell 生产数：Core 26、Xanathar 8、Tasha 3、Fizban 2、Book of Many Things 2。
  正式 499 审计仍为 `328 full / 110 partial / 61 dm_only`。
- 新增闭集注册表 `backend/src/dnd_dm_assistant/application/content_ir_production_registry.py`。
  生产 dispatch 依赖 typed clause/schema，不依赖 content name；未知 schema/section/required
  field fail closed。
- Spell 入口接入真实 spell economy + combat engine：attack hit/miss、save full/half、奇数向下
  取整、区域几何、多目标 batch preflight、fixed dice bounds、upcast、healing cap、temporary
  HP replacement、condition、concentration、CAS、idempotency、rollback、snapshot audit 均有
  真实 API evidence。Feature 入口新增 timed movement modifier、condition removal、passive
  registry inspection、attack rider consumer。
- 逐条 blocker audit 与最多 4 个 major consumer unlock ranking：
  `reports/content-ir-production-blocker-audit-2026-08-11.json`、
  `reports/content-ir-production-unlock-ranking-2026-08-11.json`。
- 批量/跨包/隔离验证报告：
  `reports/content-ir-production-runtime-validation-II-2026-08-11.json`、
  `reports/content-ir-runtime-level-audit-II-2026-08-11.json`、
  `reports/content-ir-cross-pack-production-proof-2026-08-11.json`、
  `reports/content-ir-isolated-pack-dry-run-III-2026-08-11.json`。
- 验证脚本连续重复运行后，production results 与 closeout reports SHA-256 byte-identical；临时
  SQLite 销毁，正式 DB/registry/campaign/character 未污染。前端未修改，未运行浏览器；真实
  后端 API 入口验收已完成。
- 仍保持 compile-only 的内容不得自动升级，剩余 blocker 主要为自由 choice、召唤/创建、复杂
  movement、复杂 duration/concentration settlement、非标准多段 effect 与需 DM 裁定的目标/视线。

文档：`docs/content-ir-production-runtime-closeout-2026-08-11.md`。

四项均通过；真实官方扫描报告连续两次 hash 一致。

# 2026-08-11 真实 Typed IR 生产与批量 Full 收割 I

- 本轮严格单线程执行，没有创建、调用、委托或等待子代理。保护路径
  `backend/tests/integrations/`、`backend/tests/ollama.py` 保持未跟踪、未暂存、未提交，
  逐文件哈希不变。
- 职业/子职业正式 499 条审计没有变化：`full 328 / partial 110 / dm_only 61`，
  `actual_new_full=0`。法术统计独立维护。
- 真实 authored typed IR 共 30 条，compile `full=30`：
  - 2024 PHB 法术 12/12；
  - 官方扩展包法术 10/10：珊娜萨 5、塔莎 2、费资本 2、万象 1；
  - 塔莎官方扩展职业/子职业特性 8/8。
- 2024 PHB 法术实际基线仍为 411 records、391 detail candidates；2014 PHB 为
  372 records、361 detail candidates。未把未选中的 manual 条目计入本批失败。
- SpellSpec 已补齐 schema/version、pack version、source path/book/fingerprint、
  review status、reviewed fields、source evidence、clause boundaries、manual decisions、
  evidence 和 compiler fingerprint；闭集 clause validator 支持 target selection、
  attack roll、saving throw、damage、healing、temporary HP、area、condition、duration、
  concentration、movement 和 upcast。full 产生名称无关的 `spell-runtime-1` block。
- Workbench `compile_artifact_directory` 现在可直接消费 authored typed-only pack，也能
  编译混合 FeatureSpec + SpellSpec pack；塔莎根目录
  `data/content-ir/authored/official-packs/tashas-cauldron/manifest.json` 可直接得到
  10/10 full，子目录仍保持独立 pack。
- Feature IR 继续使用现有 production-closed capability、compiler、materializer 和
  validator；新增的通用补强只有熟练项 replacement choice 投影，没有新增底层 capability，
  没有新增 feature-name/spell-name runtime branch。
- 生成资产：
  `data/content-ir/authored/`。报告：
  `reports/content-ir-authored-batch-I-2026-08-11.json`、
  `reports/spell-ir-core-2024-golden-2026-08-11.json`、
  `reports/spell-ir-official-expansion-batch-2026-08-11.json`、
  `reports/feature-ir-official-expansion-batch-2026-08-11.json`、
  `reports/content-ir-completion-unlock-ranking-2026-08-11.json`、
  `reports/content-ir-isolated-pack-dry-run-2026-08-11.json`。
- 资产、编译结果、报告重复构建后 byte-identical；隔离 dry-run 首次成功、重复返回
  `idempotent_replay`，正式 database、registry、campaign、character snapshot 未写入。
- 门禁：后端全量 pytest 通过；`ruff check backend/src backend/tests`、受保护缓存避开的
  compileall、`git diff --check` 通过。没有前端源码变化，因此未运行前端门禁。
- 下一轮最高 completion-unlock 候选：继续从已覆盖的 saving throw + area + damage +
  upcast 同构法术，或 Tasha 固定 proficiency/choice 特性中筛选；不为复杂召唤、自由
  选择、多目标反应和强制移动系统硬建底层 capability。
# 2026-08-12 合并远程 main 的并行交接

- 本地 Round 1 提交在共同祖先 `2337f8a` 之后与 `origin/main` 分叉；已通过普通 merge 保留双方历史，不使用 force push 或 rebase。
- 远程 `origin/main` 的 `e58e62b` 线包含 Ollama handoff、campaign conversation、场景语义地图、商店和玩家/游戏桌 UI 更新；这些变更已进入本地 merge 待验收状态。
- 当前交接的规则平台重点仍是本地 Round 1 的 Tasha status layers 与 isolated Item registry；远程 UI/助手变更不应被当成 Tasha production 证据。
