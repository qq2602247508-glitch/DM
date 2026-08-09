# 特性自动化迁移预审报告

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
