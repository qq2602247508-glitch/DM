# 特性自动化迁移预审报告

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
