# 特性自动化迁移预审报告

## 持续 Goal Round 22：Soulknife Psychic Teleportation Typed Feature Consumer（2026-08-12）

- Round XXII 已验收并推送：source-complete Psychic Teleportation 通过通用 `teleport` operator、`movement.teleport` capability 和既有 `combat_engine.feature_action.v1` 接入 authoritative grid；typed resource `psionic_dice` 单次消耗，距离为明确掷骰结果×10尺，目的地为可见未占据空间。
- 隔离 SQLite 已证明失败回滚、合法传送、资源/bonus action CAS、snapshot、OperationTransaction、preview→confirm→replay 与幂等；Tasha after 为 `85 production / 2 dm-assisted / 87 game usable / 7 compile-only`，项目 production full `185`，ItemSpec `47/40/40/40`。最终迁移产物在 evidence 对齐后连续两次 byte-identical。
- `ContentIRRuntimeRequest` 已保留目的地/掷骰字段；没有 feature-name branch。实现提交 `da93a60`、证据修正 `816a9dc` 已推送，receipt 单独记录。剩余 summon/entity、defense、communication、maneuver eligibility、vessel、spectral-object seam 继续 fail-closed。

## 持续 Goal Round 21：Psionic Sorcery Typed Spell-Context Consumer（2026-08-12）

- Round XXI 已验收并推送：source-complete Psionic Sorcery 的两个 typed clauses 已接入名称无关 `spell.context.v1`；非费用组件忽略、法术位→灵能点支付、actor snapshot、资源 CAS、preview/confirm/replay 与 rollback 均在真实隔离 SQLite 通过。
- Tasha after 为 `84 production / 2 dm-assisted / 86 game usable / 8 compile-only`，项目 production full `184`；ItemSpec 保持 `47/40/40/40`，formal 499 与正式数据库/registry 不变。
- 全量 backend pytest `902 passed`，Ruff、compileall、diff-check、validator 1/1 及连续三次 deterministic migration gates 通过；实现提交 `2066902` 已推送，receipt 单独记录。
- 下一步只继续剩余 summon/entity、defense、communication、maneuver eligibility、vessel、teleport destination、spectral-object seams；不增加名称分支，不迁移下一本扩展包。

## 持续 Goal Round 20：Sword Burst Generic Spell Consumer（2026-08-12）

- Round XX 已验收并推送：已把 Sword Burst 的 authored typed area、Dexterity save、force damage 和 cantrip progression 接入通用 `spell.cantrip_scaling.v1` + 既有 area/damage consumer；没有 spell-name dispatch。
- 隔离 SQLite 已完成等级 1/5/11/17 scaling、双目标 area damage、save-success、preview→confirm→replay、target CAS、OperationTransaction 与 downstream rollback；Tasha after 为 `83 production / 2 dm-assisted / 85 game usable / 9 compile-only`，项目 production full `183`。
- Summon、defense、communication、vessel、teleport、payment、spectral-object 等剩余 typed contracts 仍保持各自 blocker，不把单个子句或 isolated-only evidence 计为 full。实现提交 `c2823e5` 已推送；全量 backend pytest `899 passed`，Ruff、compileall、diff-check 和 deterministic migration gates 通过。

## 持续 Goal Round 3：Feature Production Consumer Evidence（2026-08-12）

- 12 条 Round 2 full Feature contracts 经过真实 API preview→confirm→幂等 replay；11 条进入 production evidence，1 条以 DM-confirmed typed reaction 记为 DM-assisted。
- Tasha status layers 达到 `registered_production_full=28`、`dm_assisted=2`、`game_usable=30`；formal 499 audit 未变，formal campaign/character/database 未写入。
- 通用入口支持 attack-hit rider intent、timed AC/die/ability modifier、typed `_or_` condition removal 和 DM reaction trigger/CAS；没有按名称 dispatch。
- 详见 `docs/tashas-feature-production-consumer-round-III-2026-08-12.md` 及 Round III evidence report/result。下一阶段优先 movement/sight/passive/choice 的 producer/consumer 事件链。

## 持续 Goal Round 2：Feature/Option Semantic Contract Batch I（2026-08-12）

- 64 条真实 Tasha Feature/Option atom 完成显式 reviewed/authored Typed IR；58 条 compile full，6 条 partial 保留真实 consumer/lifecycle/payment 边界。
- 隔离 runtime 已完成 58 条 apply/reload/幂等重放和 registry lookup；角色成长编译回路完成 58 grants→58 runtime contracts，`closed_loop=true`。这些结果不改变正式 production registry。
- 通用修复覆盖多 advancement/prepared-spell 合并、stable feature ID、typed authorized-information materializer/consumer；未按特性名称增加分支。
- Round 2 的正式 production 增量为 0；Tasha 正式基线仍为 17 production、1 DM-assisted、18 game usable。下一阶段必须补真实 production evidence 后才能登记正式 full。
- 详见 `docs/tashas-feature-option-contract-batch-I-2026-08-12.md` 及两份 2026-08-12 batch/runtime report。

## 持续 Goal Round 1：状态层与 Item isolated registry（2026-08-11）

- 已统一 Content IR 状态层：`source_identified`、`draft`、`candidate`、`reviewed`、`authored_typed_ir`、`compile_full`、`runtime_preview_full`、`isolated_runtime_validated`、`registered_production_full`、`dm_assisted`、`game_usable`。
- 塔莎 ItemSpec 现在通过独立 `ContentPackRuntimeRegistry` reload 验证；47 条中 41 条达到 isolated runtime validated，6 条仍保持手工/DM blocker。该结果不计入正式 production registry，避免把 isolated capability 冒充正式生产。
- 下一生产批次应选择 Feature/Option 的高扇出 semantic contract，而不是继续扩张 inventory 或 Candidate；目标为至少 30 reviewed、25 authored Typed IR、20 compile full。

## 2026-08-10 真实语料批量编译吞吐恢复（未达生产收割门槛）

- 当前严格审计仍为 `full 320 / partial 118 / dm_only 61`，固定分母 499。本阶段修复
  Spell Resistance typed defense 与 IR parity 回归，并新增真实 audit rows 批量编译入口：
  `backend/src/dnd_dm_assistant/application/feature_ir_batch_compiler.py`、
  `scripts/compile-feature-ir-batch.py`。
- 批量入口按稳定 feature ID、source/spec fingerprint、source trust 和显式 FeatureSpec
  编译；支持 preview/dry-run/replay 元数据、fingerprint conflict 与 rollback plan。
  没有 typed spec 的真实语料行只输出 partial，`generated_draft` 不得进入 full，且不改正式
  runtime_status。
- census 已补齐 producer/consumer/persistence/CAS/idempotency/materializer/validator/evidence
  等 authority 字段。当前 partial exact cluster 115 个，最大成员数 2；满足
  `production_closed + >=8` 的真实簇为 0。preview 报告显示 118 条 partial 全部
  `missing_typed_spec`，没有可安全 apply 的候选。
- 批次报告为 `reports/feature-ir-production-consumer-batch-V-2026-08-10.json`。本阶段
  `actual_new_full=0`、`direct_ir_authority_count=0`，因此 Goal 继续 active；下一步只能
  从真实语料中补齐可证明的参数化 typed specs，或建设缺失的 producer/consumer/持久化系统，
  不能用名称、粗标签、legacy parity 或 demo fanout 凑数。

## 2026-08-09 Feature IR 自动装配与拓展包导入基础

- 本轮将迁移策略从“逐条人工接线”推进到 Feature IR + Capability Catalog + FeatureCompiler +
  FeaturePackImporter。正式审计固定分母仍为 499，旧状态保持 `full 310 / partial 128 / dm_only 61`。
- `feature-ir-1` 为严格关闭 schema，FeatureSpec/Clause/Effect/Condition/Input/Resource/Target 均可
  确定性序列化；未知字段、schema、operator、重复 ID、不安全 namespace 和 pack/version 冲突 fail-closed。
- 当前 capability catalog 有 28 个 operator descriptor；它们记录真实 producer、consumer、持久化、
  CAS、幂等、输入/目标/持续时间支持和证据测试。只有 `production_closed` 可参与自动 full；施法上下文
  和目标信息能力显式保持 `production_partial`。
- FeatureCompiler 逐 clause 输出 full/partial/manual/invalid、unsupported clause、缺 producer/consumer、
  资源/输入/持久化/UI 需求和 fingerprint。`materialize_runtime_definition` 只投影现有 runtime contract，
  不复制战斗、施法或资源执行器。
- 499 条审计进入 shadow：正式 runtime_status 不变，额外输出 IR 是否存在、compiler_status、authority、
  clause 计数、unsupported clause、capability IDs、legacy adapter 和 fingerprint。30 条已有 full 完成
  shadow parity 试点，10 条进入 compiler authority 试点。
- FeaturePackImporter 支持 `--dry-run`、`--apply`、幂等重放、版本 fingerprint 冲突、namespace 校验和
  migration metadata。测试拓展包 24 条准确编译为 `18 full / 4 partial / 2 manual`，不计入 499。
- 扇出证明：6 条共享同一未注册 operator 的 FeatureSpec 在 capability 注册前全部 partial；注册一个
  production_closed capability 后，六条无需修改 spec 即全部 full。
- 报告：`reports/feature-capability-catalog-2026-08-09.json`、
  `reports/feature-ir-parity-2026-08-09.json`、
  `reports/feature-pack-readiness-2026-08-09.json`。架构和导入说明见
  `docs/feature-ir-architecture-2026-08-09.md`、`docs/feature-pack-import-readiness-2026-08-09.md`。
- 自然语言/generated draft 不得自动 full；需要新 producer、复杂状态、召唤、强制移动、法术书、额外
  回合或新 UI 的机制继续由 compiler 精确报告 blocker。

## 2026-08-09 现有 production_closed 消费者批量迁移 II

- 固定审计分母仍为 499。接管本批时实际基线为 `full 314 / partial 124 / dm_only 61`；
  收尾后为 `full 315 / partial 123 / dm_only 61`，真实净增 `+1`。
- 「绝伦健将 Peerless」与「究极战技 Ultimate Combat」新增 `verified_mapping` FeatureSpec，
  共享现有 `modifier.timed`、`resource.lifecycle.consume` 与 `resource.profile` 合同；
  IR 编译、严格参数校验、source trust、semantic parity 和生产回归均已记录。
- 「绝伦健将」真实 bonus action 只消费一次 `channel_divinity`，同一动作写入运动优势、特技优势、
  跳跃距离 `+10` 三个限时修正；消费者按动作一次清理、按效果独立持久化，避免同源效果互相覆盖。
  真实 API 回归覆盖资源 CAS、幂等重放、版本冲突和三个 modifier 的快照写入。
- 「究极战技」复用战斗大师卓越骰表、角色资源持久化、短休/长休恢复、升级/降级精确重建；
  18 级 profile 为 `6d12`，不创建新的攻击或战技支付系统。
- 「坚韧 Relentless」主动保留 `partial`：虽然已有卓越骰资源表，但当前没有每回合一次免费战技骰
  支付窗口、确认 CAS 和真实 maneuver payment consumer；不能因为配置存在而计 full。
- 本批没有新增前端代码或新 UI，因此未运行/宣称前端和浏览器验收。完整证据见
  `reports/feature-ir-production-consumer-batch-II-2026-08-09.json`。

## 2026-08-09 Feature IR 生产化硬化 I

- Operator 合同已从宽松 `Mapping` 收紧为 34 条 `OperatorContract`。空参数、未知字段、错误
  类型/enum、互斥字段和可执行 payload 都会 fail-closed；只有参数完整且组合受支持的 clause
  才能进入 full。
- production_closed capability 已移除 wildcard，并要求精确 producer/consumer/persistence/CAS/
  idempotency/materializer/evidence。当前 catalog 34 个 descriptor；施法上下文和目标情报仍是
  `production_partial`。
- Materializer Registry 输出真实 advancement/resource/feature_runtime/combat/spell/zero-HP
  合同，逐 section validator 通过。缺 materializer 或 validator 失败时不会登记 execution runtime。
- source trust 进入 full 判定：只允许 `authored_ir`、`verified_mapping`；generated draft 只生成
  partial 诊断和 migration plan。
- 十条正式 authored feature 已完成字段 parity 和生产 runtime 回归，稳定 ID 的 authority 才切换为
  compiler；正式 499 状态不变。
- 六条真实扇出使用 `modifier.passive.v2`，注册前六条 partial，注册后六条 full，两个真实 runtime
  projection 均有 evidence。演示包仍严格 18/4/2，且 18 条都有真实参数和 materializer。

## 2026-08-09 现有生产消费者收割 II

- 固定分母 499：`full 286 / partial 147 / dm_only 66` → `full 310 / partial 128 / dm_only 61`，
  严格审计得到真实 `full +24`。dm_only 的下降来自已有结构化消费者证据被纳入审计，不改变总条目。
- 本批优先复用现有生产链，未新建高风险攻击/召唤/复杂状态底座。新增或收口的消费簇包括移动/视线、
  语言与固定能力、先攻/回合开始、资源与目标状态、治疗/法术修改，以及角色卡/战斗快照中的跳跃和光照。
  代表性特性：越野、野性感官、盗贼黑话、德鲁伊语、联络宗主、恐惧伏击、水生亲和、兽之形貌、梁上君子、
  不灭哨卫、料敌机先、仇敌誓言、圣洁武器、生命门徒、神祝医者、极效治疗、强效塑能、强力戏法、序列意识。
- `compile_feature_runtime_registry` 现在对选择型 movement/modifier 进行资源选择匹配；战斗与角色卡消费权威
  blindsight、speed、jump、light、initiative、damage/healing 和资源/状态合同。错误选择、缺失权威快照、
  过期 timed modifier 和未知 operation 均 fail-closed，未用显示名称绕过合同。
- 当前矩阵预审重新生成的 readiness：`already_full 310`、`missing_runtime_contract 117`、
  `consumer_partial 28`、`needs_contract_review 6`、`manual_boundary 3`、`missing_source 35`。
  这些数字是下一批筛选状态，不是可直接承诺的新增 full 数量。
- 验证：后端全量 pytest、`ruff check backend/src backend/tests`、compileall、`git diff --check` 通过；
  前端未改动，不运行前端门禁/浏览器验收。全仓 scripts Ruff 仍保留既有 4 个 N999 与 1 个 EXE001。
- 本轮代码、测试/审计、文档/交接分离提交；必须保留且不得提交的未跟踪路径为
  `backend/tests/integrations/` 与 `backend/tests/ollama.py`。

## 2026-08-09 权威成长选项资产目录 II

- 固定审计 499 条：`276/154/69` → `286/147/66`，真实净增 full +10。新增 full 为
  5 条职业武器精通、3 条术士超魔法、圣武士/游侠两条战斗风格。
- 矩阵 schema v2 对武器精通与超魔法明确记录 authoritative catalog、stable asset ID、
  `grant_status=full`、`selected_asset_status=full`、`effect_status=separate_asset_contract`、
  输入、重复/替换策略、前置验证、持久化状态和真实 consumer。父授予行 full 不会传播给
  各武器精通词条或各超魔法的具体效果。
- 37 把 2024 武器与 10 个 2024 超魔法选项进入角色选项 API；武器精通选择验证
  职业分类/远近程/角色熟练，长休重配由通用资产 loadout 事务执行。超魔法按 2/10/17
  级累计授予，每个后续术士等级可替换一个。
- 圣武士/游侠特殊战斗风格的戏法替换使用受控旧/新资产选择器，仅允许替换
  相同来源特性授予的旧戏法，新戏法必须属于对应 0 环职业目录，确认后同步
  sheet spell、KnownSpell 与 PreparedSpell。
- 真实 API 覆盖武器权限/数量/长休重配/幂等，超魔法授予/替换/重复拒绝，戏法来源
  绑定替换与归一化法术状态。后端全量、前端 205 tests/typecheck/lint/build、Ruff、
  compileall、diff-check 均通过；隔离数据库的真实 DM 浏览器选择、预览、确认与角色卡
  回读通过，console error/warn 为 0。
- 法师记忆法术/法术精通/招牌法术需要新法术书与免槽位消耗合同，本批在完成主目标
  +10 后依高风险底层止损，未虚报理想 +13。

## 2026-08-09 批量迁移工厂检查点

固定审计从 `full 256 / partial 169 / dm_only 74` 变为
`full 268 / partial 157 / dm_only 74`，固定分母仍为 499，真实净增 `full +12`。

本轮把旧关键词预审器升级为可执行矩阵 schema v2。机器可读 JSON 由
`scripts/plan-feature-automation-migrations.py` 重复生成；可审阅摘要在
`docs/feature-automation-migration-matrix-2026-08-09.md`。每行现在携带稳定 ID、当前状态原因、
runtime sections、触发时点、所需/现有 producer 和 consumer、规范缺口类别、资源/动作经济/输入/
权威目标/状态需求、前置依赖、风险、复用簇、可执行性、阻塞原因和测试证据；输出按能力簇与特性
身份稳定排序。

### 已完成批次：`advancement_asset_grant:epic_boon`

- 12 个 2024 核心职业的 19 级「传奇恩惠」授予行共享一个 `selected_asset_grant` 合同。
- producer：`advancement_choice_requirements`。
- consumer：`advancement_service_and_feat_prerequisite_validator`。
- 服务端要求明确 `feat_choice`，从权威本地专长目录读取，强制类别为「传奇恩惠」并验证等级及其他
  前置；确认后写入角色 features，重复 idempotency key 返回同一升级记录，不重复授予。
- 职业授予行与所选资产明确分层：职业行在选择/验证/授予完成后为 full；所选具体 feat 是独立合同，
  当前仍为 dm_only。矩阵和 API 测试都验证该边界，未把具体恩惠效果冒充完成。
- 参数化测试一次覆盖 12 个职业；代表性战士 18→19 API 用例覆盖拒绝、预览、确认、持久化和重放。

### 止损与下一批

- `advancement_asset_grant:fighting_style` 有 4 条候选，但现有请求仍允许自由文本职业选项，缺权威
  战斗风格专长目录/类别校验；除已结构化的防御风格外，其余具体风格消费者也不完整。本轮止损，
  保持 partial。
- 19 条 `roll_intervention` consumer_partial 混有标记目标、状态激活、范围、随机奇偶、失败重骰与
  多模式，不能按共享 d20 窗口批量升级。
- 9 条 `attack_rider`、8 条 pre-damage、5 条 zero-HP，以及移动/状态/光环大簇都要求新的复合
  producer、持久化或玩家输入；单一子簇尚未证明能在低风险下解锁 5 条以上，因此不扩张平台。
- 下一轮优先建议先把战斗风格改为权威 feat 资产选择，并按具体风格消费者再聚类；只有能一次闭合
  至少 4～5 条时才执行。之后从矩阵筛选同构的纯状态免疫/抗性或简单资源恢复子簇。

### 验证与提交

- 后端全量 pytest、`ruff check backend/src backend/tests`、compileall、`git diff --check` 通过。
- 前端 204 tests、typecheck、lint、production build 通过。
- 无前端改动，不需要浏览器验收。
- 全仓 scripts Ruff 仍只有仓库既有 4 个 N999 与 1 个 EXE001。
- 提交：矩阵基础 `c55b80b`；运行时代码 `69eb54c`；测试与审计 `9ec638c`；文档随后单独提交。

## 2026-08-09 最终检查点（权威 Attack 动作序列与攻击槽替换）

实时固定审计：`full 254 / partial 171 / dm_only 74` →
`full 256 / partial 169 / dm_only 74`，分母仍为 499。新增 full：奥法骑士「战争魔法」与
「精通战争魔法」；指挥官奇袭已成为真实生产消费者，但父级「卓越战技」保持 partial。

- `attack_action_sequence` 在开始时冻结服务端攻击次数、替换策略、回合与 actor 版本，只支付一次
  action；槽位逐个持久化 resolution、replacement、target、resource transaction 与幂等键。
- 普通槽复用既有 CombatEngine/PlayerRoom 武器与徒手攻击，不复制命中、伤害、抗性、骑手、
  staged intervention 或 triggered attack 解析器。开放序列与旧 attack_roll_budget 不能叠加。
- 战争魔法消费 1 槽施放权威一动作法师戏法；精通战争魔法原子消费 2 槽施放权威已准备的一环/
  二环法师法术，并在同一事务消费真实法术位。非法来源、施法时间、环阶、准备状态、槽位不足和
  重复使用全部 fail-closed。
- 指挥官奇袭消费 1 槽 + 1 枚卓越骰后创建盟友 triggered_attack_window；四种所有权分离，盟友
  消费自己的反应并使用自己的真实攻击 profile。服务端仅在命中时追加实际卓越骰伤害；拒绝或
  失手仍保留已付资源，幂等重放不重复扣费或伤害。
- 回合结束自动将开放序列标为 expired；主动放弃标为 cancelled。Action Surge 继续复用既有
  extra_action_budget，可建立独立第二序列；旧单次 Attack 兼容，但不会静默获得 Extra Attack。
- DM/玩家 UI 均显示服务端槽位并支持开始、刷新恢复与放弃。真实浏览器验收确认双端同步，控制台
  无 error/warn。

验证：后端全量 pytest、Ruff backend/src+backend/tests、compileall、git diff --check；前端 204
tests、typecheck、lint、build 全部通过。全仓 scripts Ruff 仍为既有 4 个 N999 + 1 个 EXE001。

下一轮不应继续扩张本平台：剩余 partial 主要需要通用 maneuver_payment_policy 全入口迁移、攻击
骑手/强制移动/状态 producer 或目标信息读取等独立基础系统。

## 2026-08-09 最终检查点（分阶段攻击结算平台安全消费者耗尽）

实时审计固定总数仍为 `499`：`full 254 / partial 171 / dm_only 74`。本长执行从
`full 249 / partial 176 / dm_only 74` 净增 `full +5`。

- 分阶段攻击结算状态机：after_provisional_hit 与 before_attack_roll_resolution 两阶段，
  服务端重算命中/失手，支持 AC 加值、攻击减值、施加劣势，未知操作 fail-closed。
- 辉煌防御（AC 重判 + 同反应反击）、语出惊人（攻击/属性检定/伤害三分支）、如影随行
  （掷骰前双 d20 劣势 + 30 尺传送）、斗转星移（半伤 + 感知豁免心灵反伤）、防守战术
  （休息选择 + 两个 incoming 劣势源）全部真实闭环。
- 剩余候选依赖独立高风险基础系统：仇敌誓言标记、死亡豁免救援、目标信息读取、反应内移动、
  攻击次数替换；战争魔法/精通战争魔法与指挥官奇袭按指令明确不在本 Goal。

验证：后端全量 pytest、前端 204 tests/typecheck/lint/build、新增源码/测试 Ruff、compileall、
`git diff --check` 均通过；全量 Ruff 仍只命中仓库原有 scripts 的 N999/EXE001。

## 2026-08-09 检查点（防守战术休息选择与 incoming 劣势）

实时审计固定总数仍为 `499`：本切片前 `full 253 / partial 172 / dm_only 74`，本切片后
`full 254 / partial 171 / dm_only 74`。新增 full 为猎人「防守战术」。

- 休息选择持久化：短休/长休选择 escape_the_horde 或 multiattack_defense，校验并写入角色资源。
- 冲出重围：借机攻击且目标选中该选项时，权威攻击上下文附加劣势；普通攻击不受影响。
- 多重防御：命中后按回合记录攻击者，同攻击者本回合后续攻击附加劣势。
- 两个劣势分支都通过真实 `attack_roll_mode` 冲突校验证明生效，不是只改标签。

验证：防守战术 3 个 API 测试、全量后端 pytest、前端 204 tests/typecheck/lint/build、
新增源码/测试 Ruff、compileall、`git diff --check` 均通过。代码 `b27050b`、审计基线测试
`a5473da`、文档/交接随后单独提交。

## 2026-08-09 检查点（斗转星移减半与心灵反伤）

实时审计固定总数仍为 `499`：本切片前 `full 252 / partial 173 / dm_only 74`，本切片后
`full 253 / partial 172 / dm_only 74`。新增 full 为至高妖精宗主「斗转星移」。

- 魅惑免疫由 condition_immunity 消费者闭环；pre-damage 反应将最终伤害减半（floor）。
- 新增 `beguiling_reflection`：伤害结算后攻击者感知豁免（DC=8+熟练+魅力调整值），失败受到
  等同实际承受伤害的心灵伤害，走真实抗性/免疫结算；成功无反伤。窗口 CAS、版本、幂等和过期
  均持久化到 CombatAction。

验证：斗转星移 3 个 API 测试、全量后端 pytest、前端 204 tests/typecheck/lint/build、
新增源码/测试 Ruff、compileall、`git diff --check` 均通过。代码 `a22a0c2`、审计基线测试
`b5964ae`、文档/交接随后单独提交。

## 2026-08-09 检查点（如影随行掷骰前劣势与战后传送）

实时审计固定总数仍为 `499`：本切片前 `full 251 / partial 174 / dm_only 74`，本切片后
`full 252 / partial 173 / dm_only 74`。新增 full 为幽域追猎者「如影随行」，由真实 API 回归覆盖。

- 新增 `before_attack_roll_resolution` 分阶段输入链：攻击声明后暂停，受击单位接受则提交
  两个 d20 与总值，服务端取较低 d20 重算并继续；拒绝保持单 d20。
- 攻击结算后开放同一反应的 `attack_resolution_teleport` 窗口：30 尺可见未占用目的地校验，
  传送复用既有网格/传送结算器，不重复扣反应。
- 攻击决议窗口统一持久化 `phase=attack_resolution` 与 `intervention_phase`，兼容
  after-provisional-hit 与 before-roll 两阶段。

验证：如影随行 3 个 API 测试、全量后端 pytest、前端 204 tests/typecheck/lint/build、
新增源码/测试 Ruff、compileall、`git diff --check` 均通过。代码 `8a94e1c`、审计基线测试
`d589b86`、文档/交接随后单独提交。

## 2026-08-09 检查点（分阶段攻击结算与反应干预状态机）

实时审计固定总数仍为 `499`：本切片前 `full 249 / partial 176 / dm_only 74`，本切片后
`full 251 / partial 174 / dm_only 74`。新增 full 为荣耀之誓「辉煌防御」和逸闻学院「语出惊人」；
两者都由真实 API 回归覆盖，不是只写配置。

- 新增通用 `attack_resolution_intervention`：初步命中后冻结攻击提案（原始命令、初始 AC/掩体、
  攻击总值、上下文、目标/攻击者版本、候选干预），DM/玩家选择后服务端重算命中/失手并改写伤害命令。
  已支持 `add_to_target_ac`、`subtract_from_attack_total`、`impose_disadvantage`；未知操作 fail-closed。
- 辉煌防御：10 尺内可见自我/盟友被命中开窗；消耗反应与长休恢复的 `glorious_defense` 资源；AC 加值重判；
  变失手且攻击者在武器触及内时创建同一反应的反击窗口（不再重复扣反应/资源）。
- 语出惊人：攻击分支在初步命中后暂停并减值重判；属性/技能检定分支仅成功时对旁观者反应者开放、
  动态诗人骰面物化、失败不误开；伤害分支由附近可见 bard 打开 pre-damage 窗口按段减伤。
- pre-damage 与 roll-intervention 消费者支持旁观者反应者；资源、反应、攻击/AC/伤害重算、CAS 和
  幂等重放均走真实持久化事务。

验证：攻击决议/辉煌防御/语出惊人定向测试、全量后端 pytest、前端 204 tests/typecheck/lint/build、
新增源码/测试 Ruff、compileall、`git diff --check` 均通过；全量 Ruff 仍只命中仓库原有 scripts 的
N999/EXE001。代码 `f6c6e97`、审计基线测试 `8659e36`、文档/交接随后单独提交。

## 2026-08-09 检查点（事件驱动追加攻击窗口）

实时审计固定总数仍为 `499`：本切片前 `full 247 / partial 178 / dm_only 74`，本切片后
`full 249 / partial 176 / dm_only 74`。新增 full 仅为狂战士「报偿」和勇气学院「战斗魔法」；
战斗大师「反击」只作为已学习战技的生产 trigger 接入，父级复合特性仍保持 partial。

- 新增通用 `triggered_attack_window` 合同。执行器只读取封闭事件、目标政策、动作经济、资源、攻击
  profile、窗口生命周期和因果深度，不识别职业/子职业/特性名称。
- 真实生产链在权威 CombatAction 确认后派发：实际受伤、单动作结构化施法、敌方近战攻击未命中；
  窗口保存父动作 ID/版本、反应者、候选目标、合法武器/徒手动作、网格距离/视线、资源和过期轮次。
- 玩家面板可选择目标、真实动作、d20、攻击总值、伤害总值并复用普通攻击入口；DM/玩家均可放弃窗口。
  接受会消费 reaction/bonus action 和绑定资源，窗口、HP、资源、角色版本和动作幂等均走现有 CAS 事务。
- `报偿` 的完整规则（仅实际伤害、5 尺、近战武器/徒手、反应、真实攻击）已由真实 API 回归覆盖；
  `战斗魔法` 的生产 trigger 限定成功的一动作结构化法术，允许法术表中的武器攻击 profile。复仇之魂、
  辉煌防御和指挥官奇袭仍缺标记 producer、同一反应多阶段或攻击预算/盟友输入，明确保持 partial。

验证：追加攻击 2 个 API 测试、战技选择 registry 测试、全量后端测试以及前端 204 tests/typecheck/lint/build
通过；真实浏览器验收中 DM 模拟战斗页和玩家一次性入口均正常显示，两端控制台无 error/warn。仓库全量 Ruff
仍有原有脚本文件 N999/EXE001，新增源码/测试检查通过。代码 `65cd8ce`、审计基线测试 `4c8b0a3`、
文档/交接 `de7ec8f` 保持分离提交。

## 2026-08-08 检查点（战斗大师卓越骰与战技通用平台）

实时审计固定总数仍为 `499`：本切片前 `full 246 / partial 179 / dm_only 74`，切片后
`full 247 / partial 178 / dm_only 74`。唯一新增的 `full` 是战斗大师 10 级「精通战技」；
「卓越战技」父特性、料敌机先、坚韧和究极战技仍为 `partial`，没有把单一骰池分支冒充整条
复合特性完成。

- 新增通用卓越骰资源合同：按战士等级生产 `4d8 → 5d8 → 5d10 → 6d10 → 6d12`，短休和长休
  恢复，升级/降级/重复升级/快照重建使用 exact 上限和骰面语义，并写入真实角色资源状态。
- 新增战技选择与替换合同：3/7/10/15 级累计选择、重复/越级/未学习替换 fail-closed，选择结果
  持久化到运行时 registry；力量/敏捷豁免 DC 能力选择通过独立结构化输入保存，普通流程不使用
  DM override 默认值。
- 新增不识别职业名称的通用战技 `roll_intervention` 接线：伏击、领导风范、战术预估复用真实
  玩家 d20 检定入口，动态读取卓越骰面，CAS 扣除资源并以动作幂等键重放；只把这些完整闭环的
  三个战技消费者接通，未完成的攻击、反应、移动和状态分支继续保持 partial。
- 「精通战技」完整语义在现有资源/休息/升级消费者中闭环，因此升为 full；其他条目仍需新的
  反应攻击、攻击重骰、目标体型/物件、强制移动或 universal maneuver 消费基础，暂不扩张。

代码提交：`36ac2dc feat: add battle master superiority dice runtime`；审计基线测试修订：
`e7aa6e0 test: update battle master audit baseline`。本检查点文档与 `CODEX_HANDOFF.md`
另行提交。当前预审统计为 `already_full 247 / missing_runtime_contract 167 / consumer_partial 34 /
manual_boundary 10 / needs_contract_review 6 / missing_source 35`。

## 2026-08-08 检查点（魔能掌控、灵能力量与战神祝福）

当前固定审计为 `full 246 / partial 179 / dm_only 74`。本 Goal 从
`227/195/77` 开始，真实净增 `+19`；未因达到 223 停止。

- `魔能掌控`：覆盖秘法回流的完整分支。既有一分钟仪式、`magical_cunning` 使用权和契约魔法法术位资源继续由同一生产合同消费；该特性将恢复数量公式从“一半已消耗（向上取整）”覆盖为“全部已消耗”。休息服务在事务内校验公式、资源余额、角色版本和幂等键，重复确认返回同一恢复结果。
- `灵能力量`（灵能武士、魂刃）：运行时配置绑定实际的 `psionic_dice:<class>` 资源；等级表决定骰面与上限，短休恢复一枚、长休恢复全部。资源写入角色升级结果并进入统一运行时 registry，意念守护、心灵传送等独立消费者复用该池；本特性自身只负责资源生产与生命周期，不冒充其余灵能效果。
- `战神祝福`：感知调整值（至少1）次数，长休恢复；攻击检定后 30 尺可见/可听目标的反应窗口，+10 加值；玩家/DM 选择窗口、目标和反应，CombatEngine 原子扣减资源、消费反应、写入检定结果，并以动作幂等键重放。

代码提交分别为 `ce1becc feat: close psionic power and eldritch mastery` 与
`1f5fa37 feat: automate war gods blessing reaction`；本检查点文档与
`CODEX_HANDOFF.md` 另行提交。

### 当前安全边界

剩余 `roll_intervention` 的 20 个 `consumer_partial` 逐条复核后，仍混有
标记目标、范围/光环、随机奇偶、状态激活、额外攻击或多个模式；不能因为共享
`player_roll_resolution` 就升级。资源与状态候选中，战斗大师“坚韧”还缺真实战技骰池
生产者和每回合替代窗口，荣耀之誓“辉煌防御”还缺反击攻击分支，游侠“越野”还缺
垂直/游泳移动规则消费，均保持 `partial`。继续执行只有在补齐这些基础消费者、输入、
持久化和幂等链后才安全，不能用配置覆盖数凑 full。

## 历史检查点：真力注拳与月光飞步生命周期

此前审计为 `full 242 / partial 182 / dm_only 75`。武僧「真力注拳」的
最终伤害类型选择已接入玩家攻击生产入口；月光飞步的法术位重置、显式网格传送、
回合末状态和下一次攻击优势也已接入真实链。两者均覆盖结构化输入、资源 CAS、
状态持久化和幂等重放。

## 历史检查点：自然守御与战斗激励

- `自然守御`：长休地形四选一写入角色资源，伤害防御按选择映射抗性，条件免疫独立消费，中毒免疫和缺失选择均 fail-closed。
- `战斗激励`：防御/进攻两模式写入目标骰记录，玩家提交模式与骰值后由真实 AC/伤害入口消费，覆盖骰面校验、版本/CAS 和幂等。

## 历史检查点：元素亲和与战斗资源链

钢铁意志、专业预言、高阶防守战术、战争祭司、意念守护、凶蛮打击、邪魔体魄、
光耀之魂和元素亲和均已完成对应的选择、目标、资源、状态或攻击消费者；领域 helper、
配置覆盖数和单一分支不计入 full。每条特性只有全部分支完成才升级。

### D20 池审计边界

`roll_intervention` 共有 46 条，当前 26 条 full、20 条 `consumer_partial`。
预兆与高等预兆完整覆盖长休生成并持久化多枚 D20、检定前替换、目标可见性、
玩家/DM 输入、CAS 和幂等消费。混乱之潮、归复平衡、现世传说、专心炽志等
分别还带优势/劣势抵消、随机奇偶、失败重骰或其它状态/资源分支，不能共享预兆池
合同，继续保持 partial。

## 更早的批次结论

自然恢复、百折不挠、妖冶娴都、狂怒首击附伤、通用治疗骰池、攻击后触发与额外攻击
等批次均已按真实生产消费者、持久化、输入和幂等门禁验收。此前只实现领域
`roll_intervention` helper 的切片没有计入 full；这条规则继续有效。

这份报告只规划迁移，不修改运行时状态，也不把候选行直接升级为 `full`。

- 总条目：499
- 当前状态：`{'full': 246, 'dm_only': 74, 'partial': 179}`
- 预审状态：`{'already_full': 246, 'missing_source': 35, 'missing_runtime_contract': 168, 'consumer_partial': 34, 'manual_boundary': 10, 'needs_contract_review': 6}`

## 模板分组

| 模板 | 条目 | 已 full | 缺运行时合同 | 待合同复核 | 消费者不完整 | 人工边界 | 缺源码 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 掷骰干预 (`roll_intervention`) | 46 | 26 | 0 | 0 | 20 | 0 | 0 |
| 状态生命周期 (`state_lifecycle`) | 34 | 19 | 14 | 1 | 0 | 0 | 0 |
| 动作经济与触发条件 (`action_trigger`) | 34 | 22 | 11 | 0 | 0 | 1 | 0 |
| 通用被动/数值修正 (`passive_modifier`) | 79 | 30 | 13 | 0 | 0 | 1 | 35 |
| 成长授予/升级选择 (`progression_grant`) | 67 | 54 | 12 | 0 | 0 | 1 | 0 |
| 资源/恢复/频率 (`resource_lifecycle`) | 64 | 37 | 19 | 2 | 0 | 6 | 0 |
| 光环/范围被动 (`aura_passive`) | 48 | 5 | 42 | 1 | 0 | 0 | 0 |
| 伤害/治疗 (`damage_healing`) | 48 | 26 | 21 | 1 | 0 | 0 | 0 |
| 施法框架/法术修改 (`spell_capability`) | 7 | 3 | 0 | 0 | 4 | 0 | 0 |
| 命中后骑手 (`attack_rider`) | 13 | 3 | 0 | 0 | 10 | 0 | 0 |
| 0 HP/死亡生命周期 (`zero_hp_intervention`) | 8 | 3 | 5 | 0 | 0 | 0 | 0 |
| 目标/范围/豁免组合 (`target_save_status`) | 10 | 4 | 5 | 0 | 0 | 1 | 0 |
| 召唤/伙伴 (`summon_lifecycle`) | 13 | 7 | 6 | 0 | 0 | 0 | 0 |
| 伤害前/防御干预 (`pre_damage_intervention`) | 13 | 4 | 8 | 1 | 0 | 0 | 0 |
| 移动/位移 (`movement`) | 15 | 3 | 12 | 0 | 0 | 0 | 0 |

## 预审结论

- `missing_runtime_contract`：源码命中积木，但还没有真实运行时合同；不能仅靠字段改成 `full`。
- `needs_contract_review`：已有部分运行时结构，但仍需逐字段核对消费者、输入、资源和幂等。
- `consumer_partial`：执行器存在，但生产接线或安全闭环未完成。
- `manual_boundary`：包含选择、DM裁定或开放叙事，不能强行无人值守。
- 只有完成真实配置、消费者、状态写入、输入链和测试后，才允许从本报告中产生 `full` 增量。

## 下一批执行门槛

下一批必须从一个模板中选择一组条目，先生成配置和定向测试，再跑499条审计。预审数字是候选分组，不是承诺的新增 `full` 数量。

# 2026-08-09 成长资产选择与能力授予批次

本轮以固定 499 条审计从 `268/157/74` 推进到 `276/154/69`，full 净增 8。新增 full 为战士
「战斗风格」、勇士「额外战斗风格」、吟游诗人「魔法奥秘」、游侠「熟练探险家」、德鲁伊
「原初职能」、牧师「圣职」、法师「仪式学家」、勇气学院「战争训练」。圣武士和游侠的职业
「战斗风格」仍为 partial，因为职业专属两戏法分支的后续升级替换尚未闭合。

本批次扩展既有成长体系而未建立平行执行器：keyed 权威资产、替换、专精、语言、封闭分支与条件法术
授予都在 advancement preview/confirm 事务中校验并写入角色快照。战斗风格职业行只负责权威授予；
所选 feat 的具体效果保持自己的 runtime status。魔法奥秘复用普通吟游诗人法术目录/环阶/替换校验，
仪式学家与战争训练分别接入真实法术经济的未准备仪式和已装备熟练武器法器分支。

矩阵 schema v2 已增加权威 catalog、selected asset kind、grant/asset/effect 三层状态、duplicate / replacement
policy、前置校验、持久化目标和消费者证据。参数化测试固定 10 个稳定 feature ID、8 full 和 2 partial；
代表性 API 覆盖战斗风格、熟练探险家、原初职能、仪式与武器法器。前端通用选择器从后端目录呈现
战斗风格、封闭选项、语言、专精和戏法，并提交 `feature_choices_by_key`。

验证证据：后端全量 pytest、backend Ruff、compileall、diff check 通过；前端 205 tests、typecheck、
lint、production build 通过；隔离数据库的真实 DM 页面完成战斗风格选择、预览、确认、刷新持久化，
控制台 error/warn 为 0。代码职责提交为 `d997fad`、`7f79815`、`f24e2b6`、`14cd3d8`。

下一轮优先补通用 selected-cantrip replacement，使圣武士/游侠两条复合战斗风格达到 full；之后继续
扫描已有消费者的低风险 progression/passive grant 批次，不引入新的大型战斗状态机。

# 2026-08-10 目标信息读取与 IR 权威扩展检查点

当前严格审计为 `full 320 / partial 118 / dm_only 61`（固定 499）。本检查点没有新增
`full`，只完成 authority 和证据扩展：

- 「猎人学识 Hunter's Lore」由 authored Feature IR 编译并物化为只读目标信息动作；
  真实 combat API 使用猎人印记快照绑定目标，读取目标的抗性/免疫/易伤，覆盖离回合调用、
  目标/角色版本 CAS、幂等重放和缺失绑定 fail-closed。只读动作记录审计结果，不递增
  combatant 版本。
- 新增 7 条 authored IR 的已有 full 消费者映射：心灵防御、高效重击、操命本事、
  刺客工具、法术抗性，以及灵能武士/魂刃的灵能力量。`set_resource_profile` 现在允许
  显式短休/长休恢复事件，未改变既有资源消费者。
- formal IR 当前 25 条（authored 21、verified 4）；这些新增映射不重复计入已有 full，
  不把“compiler full”单独当作正式新增。
- 真实语义 census 仍显示 partial 最大 exact 簇为 2；下一轮必须先建设一个可复用的
  多目标/反应/状态或攻击后窗口 producer，再批量收割，不能用 source alias、配置存在或
  单分支 effect 抬高状态。

验证：Hunter's Lore 真实 API 与 IR/批量测试通过；提交前仍需运行后端全量 pytest、Ruff、
compileall、git diff check。无前端源码变更，不运行前端/浏览器门禁。
# 2026-08-10：Clause IR 先于平台的硬门槛

# 2026-08-10：166 条 Clause review schema 批次

# 2026-08-10：生产收割 VIII 与扩展包导入验收

本批不再等待全部 166 条 manual boundary，而是从现有 production_closed consumer 中选择
8 条能完整 authored 的特性，实际将审计从 `320/118/61` 推进到 `328/110/61`。每条新增
full 均由 direct authored Feature IR、compiler authority 和现有 materializer/runtime consumer
驱动。

扩展包自动化边界已经通过真实 fixture 验证：扩展包作者提供符合 `feature-ir-1` 的 typed
FeatureSpec，通用 importer 负责 schema/ruleset/namespace/source fingerprint 校验、compiler、
materialize、registry apply、reload、幂等、版本冲突、跨 pack feature_id 冲突、并发互斥和回滚。
导入 8 条使用不同 feature_name 的样例不需要核心代码或 feature-name 分支变化。

这不表示自然语言可以直接自动变成 full；扩展包仍必须提供 authored typed IR。自动化的是
导入、校验、编译、投影、注册和版本管理。

本批将 166 个 source review clause 变成 `feature-clause-reviewed-1` 记录，保留 source
fingerprint、审阅字段、缺失字段和具体 blocker。`reviewed_typed` 只表示记录通过了关闭式
review schema；它不表示可执行。当前 166 条均为 `manual_boundary`，source incomplete 为
0，executable clause 为 0。

Capability ranking 将 `review:manual_boundary` 的 occurrence count 与 completion unlock count
严格分离。它可以显示 166 条仍需要 authored contract，但 completion unlock 必须为 0；只有
明确的 producer/consumer/persistence/CAS/idempotency 等字段级合同才能成为后续平台候选。
因此 Batch VII 没有建设底座或新增 full，避免把审阅队列本身误报成可收割 capability。

在 Batch V 之后已确认，完整 feature 的 exact cluster 不能代表可复用的实现边界。Batch VI
新增 source-backed、非 executable 的 Feature Clause Corpus 和 capability unlock graph。它们的
选择规则是 `completion_unlock_count >= 8`，而不是关键词 occurrence。

当前报告显示 118 条 partial 均有完整定位源码，但其 166 个 source clause 尚未具备完整的
trigger / target / effect / producer / consumer / persistence / CAS / idempotency 合同。因此 typed
missing contract 为 0，不能诚实地选择任何生产底座，也不能因“saving throw 45 次”等频次升级
feature。下一迁移批次必须先提交人工审阅的 typed clause manifest；只有届时字段级相等、且 feature
其余 clause 都 production_closed 的成员才计入 completion unlock。
## 2026-08-11：Rules Kernel 与 3D 场景执行层收口

本轮将已有 compile-only 内容接入统一、版本化的 Rules Kernel 执行边界，而不是继续扩建按名字
分支的扫描器。去重后的基线为 `111 unique compiled / 60 compile-only / 51 production full`；
真实解锁 25 条（20 spell、5 feature），production full 达到 76，spell 达到 61，feature 达到
15；新增 authored IR 为 0。正式 499 条职业审计仍为 `328 full / 110 partial / 61 dm_only`。

迁移层现在固定为：

```text
typed content IR → Rules Kernel preview → Choice/DM window（必要时）
→ version/CAS confirm → domain transaction → Scene Delta → client projection
```

Rules Kernel、Scene Query/Delta、Spatial Authority、Choice window、DM adjudication、entity
lifecycle 和 movement 均有严格协议及真实 API/TestClient 验证。Spatial Authority 复用现有
SceneGrid/Combatant/SceneToken，不把 3D 客户端当作规则权威；未知自然语言对象或未闭合的目标/持续
时间语义仍必须停在 DM 裁定窗口。

剩余 compile-only 的主要 blocker 是 `adjudication.target_semantics=44`、
`duration.multi_phase=28`、`spatial.area=11`、`condition.composite=9` 和
`runtime.evidence_missing=5`。下一批先补这些字段级合同与证据，再按 fan-out 进行真实收割。

# 2026-08-10：Content IR Workbench / Spell IR 基线

- 已建立独立只读扫描器，统一识别 Feature Draft 与 Spell Draft，并按 source fingerprint
  输出确定性报告。
- 新增闭集 `SpellSpec`；未经过 authored typed clause 的官方正文不能成为 full。
- 当前扩展包导入瓶颈已从“是否能找到页面”明确为“缺 authored Feature/Spell IR”。
- 下一阶段应按 blocker fan-out 建设 Spell clause materializer，并先 authored 一批
  原版法术作为 golden corpus；每个新 clause 必须报告真实 completion unlock 数。

# 2026-08-10：统一内容 IR 批量转换与官方扩展包验证收口

本轮完成了从真实本地 CHM JSON 到隔离 Content IR Workbench 的统一生产转换链，保持正式 499
审计和所有生产运行时状态只读。

## 基线

- 职业/子职业固定分母 499：`full 328 / partial 110 / dm_only 61`。
- 2024 PHB 法术：总记录 411，详情候选 391。
- 2014 PHB 法术：总记录 372，详情候选 361。
- 全部法术真实记录 1314；official/third_party/unknown 为 786/293/235。

## 统一协议

Feature Draft/FeatureSpec 与 Spell Draft/SpellSpec 分开建模，但共用 source provenance、
source_record_id、source fingerprint、pack/namespace、ruleset、clause identity、compiler
fingerprint、capability registry、compiler status、blocker、dry-run/import result、report schema
以及 idempotency/replay 元数据。

边界固定为：

```text
raw HTML/JSON → Source Atom → Draft IR → Typed IR → Compiler
→ Materializer → Runtime Registry → full
```

没有 Typed IR 的内容只能保持 `partial`/`manual`；不把官方性、字段读取、legacy adapter 或关键字
命中当作执行证据。未知 Spell clause、缺 typed 参数、重复 ID 和 source fingerprint conflict
均 fail-closed。

## 扩展包真实扫描

本地注册表自动发现并分别扫描 6 个官方 pack：珊娜萨、塔莎、费资本、万象无常、毕格比以及多元宇宙
的怪物。当前 4 个重点扩展包的 draft 结果为：

- 珊娜萨：feature 25、spell 95、feat 1、other 20、draft 141；
- 塔莎：feature 48、spell 21、feat 1、other 2、draft 72；
- 费资本：feature 2、spell 7、feat 1、other 5、draft 15；
- 万象：feature 0、spell 3、feat 1、other 3、draft 7。

六个 pack 均为 `0 full`；mordenkainen pack 没有可识别玩家选项候选。真实产物统一写入
`/tmp/content-ir-workbench/<pack-id>/`，包含 source inventory、draft、typed IR 目录、manifest、
compile result、runtime preview、dry-run result 和 report。

## 下一步门槛

- 继续保持 completion unlock ranking 的真实证据门槛：当前所有 pack ranking 均为空/0。
- 下一块底座只能由 authored typed clause 的 production-closed capability fan-out 证明解锁；
  source-backed prose review 或 generated draft 不得作为候选成员。
- 首个 golden corpus 应优先覆盖具备完整 source boundary 和 authored clauses 的原版 2024/2014
  法术，并为每种新增 Spell clause 同时补 materializer、validator、runtime evidence 和负例。
