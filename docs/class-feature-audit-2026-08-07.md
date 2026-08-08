# 职业/子职业特性源码级审计

## 2026-08-08 长执行检查点（元素亲和）

- 固定分母 499；当前真实状态：`full 239 / partial 184 / dm_only 76`。
- 本长执行从 `full 227 / partial 195 / dm_only 77` 开始，已闭环预言师「预兆」与「高等预兆」，以及圣武士「信实坐骑」：长休提交真实 1–20 骰值，玩家在检定前选择单颗骰子替换；信实坐骑的寻获坐骑始终准备并使用独立长休恢复的免费施法资源。
- 随后完成游侠幽域追猎者「钢铁意志」、法师预言师「专业预言」和圣武士「高阶防守战术」；选择、槽位/资源 CAS、真实消费者、反应窗口、生命周期和幂等重放均已接通。
- 新增战争祭司：附赠动作触发一件玩家选择的近战武器攻击或徒手打击；5 尺敌对目标、感知调整值次数、短/长休恢复、战斗动作经济、攻击/伤害结算和资源 CAS 均由真实玩家攻击入口执行，重复请求不会二次扣除资源。
- 新增灵能武士「意念守护」：心灵伤害抗性由伤害防御解析器消费；玩家在自己回合开始提交魅惑/恐慌中的具体状态，服务端以共享灵能骰池原子扣除 1 枚并移除对应状态及其结构化效果；回合窗口、状态存在性、资源 CAS、幂等重放均有真实 API 测试。
- 新增野蛮人「凶蛮打击」：仅在狂暴、鲁莽攻击、力量武器/徒手攻击且结构化攻击模式确为优势时，玩家显式提交 `attack_rider_eligibility.brutal_strike=true` 放弃优势并提交 1d10 最终值；攻击骑手消费者校验范围、每回合一次和幂等使用，不满足优势条件则 fail-closed。
- 新增魔契师邪魔宗主「邪魔体魄」：短休或长休提交非力场伤害类型，选择持久化到角色资源 JSON；战斗伤害防御解析器优先读取该选择并只应用该类型抗性，缺失/非法选择 fail-closed，休息预览/确认与版本幂等测试覆盖。
- 新增魔契师天界宗主「光耀之魂」：光耀抗性由防御解析器消费；玩家在造成光耀/火焰法术伤害时显式指定一个目标并确认使用，攻击骑手只在该目标、每回合一次且真实法术伤害类型命中时加入魅力调整值，未命中条件不触发。
- 新增魔契师龙族术法「元素亲和」：升级服务要求玩家/DM 从五种元素伤害中选择一项并校验选项；选择绑定到角色运行时快照，抗性与法术伤害魅力加值骑手都只接受该类型，其他类型和缺失选择 fail-closed。
- 预兆骰池不由服务器伪造结果；长休必须由玩家/DM 提交完整骰池，逐颗骰子只能消费一次；未完成提交时长休会清空旧骰池。
- 仍未把只存在领域 helper、只落库或只覆盖单一分支的候选计入 full；复合反应、动态光环、召唤、随机表和地形选择继续保持 partial。
- 上述特性定向测试、Ruff、compileall、`git diff --check` 已通过；全量 pytest 仍是本 Goal 结束前门禁。

这份报告把源码描述解析状态与运行时执行状态分开统计。积木覆盖数允许重叠，一条特性可以使用多个积木；检测到积木不等于已有执行器。

- 总条目：499
- 核心职业：12 个，特性 258 条
- 子职业：56 个，显式等级特性 241 条
- 运行时状态：`{'full': 239, 'dm_only': 76, 'partial': 184}`
- 源码读取状态：`{'description_located': 415, 'structural_placeholder': 35, 'description_reused': 49}`

## 积木覆盖（允许重叠）

| 积木 | 源码候选 | full | partial | dm_only |
|---|---:|---:|---:|---:|
| 成长授予/升级选择 | 86 | 58 | 27 | 1 |
| 施法框架/法术修改 | 126 | 53 | 54 | 19 |
| 法术框架详细修改 | 1 | 0 | 0 | 1 |
| 法术选择/准备 | 58 | 40 | 11 | 7 |
| 动作经济 | 72 | 15 | 56 | 1 |
| 动作经济与触发条件 | 225 | 92 | 111 | 22 |
| 资源/恢复/频率 | 195 | 71 | 107 | 17 |
| 资源/恢复绑定 | 66 | 26 | 33 | 7 |
| 伤害/治疗 | 135 | 37 | 85 | 13 |
| 伤害前/防御干预 | 17 | 3 | 13 | 1 |
| 光环/范围被动 | 83 | 13 | 66 | 4 |
| 掷骰干预 | 49 | 27 | 22 | 0 |
| 命中后骑手 | 13 | 3 | 8 | 2 |
| 豁免/DC | 82 | 24 | 51 | 7 |
| 目标/范围/豁免组合 | 82 | 12 | 65 | 5 |
| 移动/位移 | 38 | 5 | 32 | 1 |
| 0 HP/死亡生命周期 | 8 | 3 | 4 | 1 |
| 状态生命周期 | 90 | 33 | 55 | 2 |
| 召唤/伙伴 | 19 | 7 | 11 | 1 |
| 创造物/世界状态 | 20 | 4 | 16 | 0 |
| 语言/开放叙事 | 1 | 0 | 0 | 1 |
| 多分支选择 | 6 | 0 | 4 | 2 |

## 需要优先复核的条目

| 范围 | 职业 | 子职业 | 等级 | 特性 | 源码状态 | 运行时 | 检测积木 |
|---|---|---|---:|---|---|---|---|
| core | 吟游诗人 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 吟游诗人 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 吟游诗人 | — | 9 | 专精 | description_reused | full | 成长授予/升级选择、动作经济与触发条件 |
| core | 吟游诗人 | — | 10 | 魔法奥秘 | description_located | dm_only | 施法框架/法术修改、法术选择/准备、动作经济与触发条件 |
| core | 吟游诗人 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 吟游诗人 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 吟游诗人 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 吟游诗人 | — | 20 | 创生圣言 | description_located | dm_only | 施法框架/法术修改、法术框架详细修改、法术选择/准备、动作经济与触发条件、光环/范围被动、目标/范围/豁免组合 |
| core | 圣武士 | — | 5 | 信实坐骑 | description_located | dm_only | 施法框架/法术修改、法术选择/准备、资源/恢复/频率 |
| core | 圣武士 | — | 7 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 圣武士 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 圣武士 | — | 9 | 弃绝众敌 | description_located | dm_only | 资源/恢复/频率、资源/恢复绑定、伤害/治疗、光环/范围被动、豁免/DC、目标/范围/豁免组合、状态生命周期 |
| core | 圣武士 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 圣武士 | — | 15 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 圣武士 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 圣武士 | — | 20 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 德鲁伊 | — | 1 | 德鲁伊语 | description_located | dm_only | 施法框架/法术修改、法术选择/准备、豁免/DC、语言/开放叙事 |
| core | 德鲁伊 | — | 1 | 原初职能 | description_located | dm_only | 施法框架/法术修改、法术选择/准备、多分支选择 |
| core | 德鲁伊 | — | 2 | 荒野伙伴 | description_located | dm_only | 施法框架/法术修改、动作经济、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定、召唤/伙伴 |
| core | 德鲁伊 | — | 5 | 荒野复苏 | description_located | dm_only | 施法框架/法术修改、资源/恢复/频率、资源/恢复绑定 |
| core | 德鲁伊 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 德鲁伊 | — | 7 | 元素之怒 | description_located | dm_only | 施法框架/法术修改、动作经济与触发条件、伤害/治疗、命中后骑手 |
| core | 德鲁伊 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 德鲁伊 | — | 10 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 德鲁伊 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 德鲁伊 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 德鲁伊 | — | 15 | 元素狂怒 | description_located | dm_only | 施法框架/法术修改、动作经济与触发条件、伤害/治疗 |
| core | 德鲁伊 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 德鲁伊 | — | 18 | 兽形施法 | description_located | dm_only | 施法框架/法术修改、资源/恢复/频率 |
| core | 战士 | — | 6 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 战士 | — | 7 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 战士 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 战士 | — | 9 | 战术主宰 | description_located | dm_only | 动作经济与触发条件、移动/位移 |
| core | 战士 | — | 10 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 战士 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 战士 | — | 13 | 不屈（两次） | description_reused | full | 动作经济与触发条件、资源/恢复/频率、掷骰干预、豁免/DC |
| core | 战士 | — | 14 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 战士 | — | 15 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 战士 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 战士 | — | 17 | 动作如潮（两次） | description_reused | full | 资源/恢复/频率 |
| core | 战士 | — | 17 | 不屈（三次） | description_reused | full | 动作经济与触发条件、资源/恢复/频率、掷骰干预、豁免/DC |
| core | 战士 | — | 18 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 术士 | — | 2 | 超魔法 | description_located | dm_only | 动作经济与触发条件、资源/恢复/频率 |
| core | 术士 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 术士 | — | 7 | 术法化身 | description_located | dm_only | 资源/恢复/频率 |
| core | 术士 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 术士 | — | 10 | 超魔法 | description_reused | dm_only | 动作经济与触发条件、资源/恢复/频率 |
| core | 术士 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 术士 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 术士 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 术士 | — | 17 | 超魔法 | description_reused | dm_only | 动作经济与触发条件、资源/恢复/频率 |
| core | 术士 | — | 18 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 术士 | — | 20 | 奥术化神 | description_located | dm_only | 资源/恢复/频率 |
| core | 武僧 | — | 2 | 运转周天 | description_located | dm_only | 动作经济与触发条件、资源/恢复/频率、资源/恢复绑定、伤害/治疗 |
| core | 武僧 | — | 6 | 真力注拳 | description_located | dm_only | 动作经济与触发条件、伤害/治疗 |
| core | 武僧 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 武僧 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 武僧 | — | 9 | 飞檐走壁 | description_located | dm_only | 未检测到 |
| core | 武僧 | — | 10 | 出神入化 | description_located | dm_only | 动作经济与触发条件、资源/恢复/频率、伤害/治疗、光环/范围被动、目标/范围/豁免组合 |
| core | 武僧 | — | 11 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 武僧 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 武僧 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 武僧 | — | 17 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 法师 | — | 1 | 仪式学家 | description_located | dm_only | 施法框架/法术修改 |
| core | 法师 | — | 5 | 记忆法术 | description_located | dm_only | 施法框架/法术修改、动作经济与触发条件、资源/恢复/频率 |
| core | 法师 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 法师 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 法师 | — | 10 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 法师 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 法师 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 法师 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 法师 | — | 18 | 法术精通 | description_located | dm_only | 施法框架/法术修改、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定 |
| core | 法师 | — | 20 | 招牌法术 | description_located | dm_only | 施法框架/法术修改、资源/恢复/频率、资源/恢复绑定 |
| core | 游侠 | — | 2 | 熟练探险家 | description_located | dm_only | 成长授予/升级选择 |
| core | 游侠 | — | 6 | 越野 | description_located | dm_only | 未检测到 |
| core | 游侠 | — | 7 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 游侠 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 游侠 | — | 11 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 游侠 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 游侠 | — | 15 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 游侠 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 游侠 | — | 18 | 野性感官 | description_located | dm_only | 未检测到 |
| core | 游荡者 | — | 1 | 盗贼黑话 | description_located | dm_only | 未检测到 |
| core | 游荡者 | — | 5 | 诡诈打击 | description_located | dm_only | 动作经济与触发条件、伤害/治疗、伤害前/防御干预、豁免/DC |
| core | 游荡者 | — | 6 | 专精 | description_reused | full | 成长授予/升级选择、动作经济与触发条件 |
| core | 游荡者 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 游荡者 | — | 9 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 游荡者 | — | 10 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 游荡者 | — | 11 | 进阶诡诈打击 | description_located | dm_only | 伤害/治疗 |
| core | 游荡者 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 游荡者 | — | 13 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 游荡者 | — | 14 | 凶狡打击 | description_located | dm_only | 伤害/治疗、豁免/DC、目标/范围/豁免组合、0 HP/死亡生命周期、状态生命周期 |
| core | 游荡者 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 游荡者 | — | 17 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 牧师 | — | 1 | 圣职 | description_located | dm_only | 施法框架/法术修改、法术选择/准备 |
| core | 牧师 | — | 5 | 灼净亡灵 | description_located | dm_only | 动作经济与触发条件、伤害/治疗、豁免/DC |
| core | 牧师 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 牧师 | — | 7 | 受祝击 | description_located | dm_only | 施法框架/法术修改、动作经济与触发条件、伤害/治疗、命中后骑手、多分支选择 |
| core | 牧师 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 牧师 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 牧师 | — | 14 | 精通受祝击 | description_located | dm_only | 施法框架/法术修改、动作经济与触发条件、伤害/治疗、光环/范围被动、目标/范围/豁免组合 |
| core | 牧师 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 牧师 | — | 17 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 野蛮人 | — | 3 | 原初学识 | description_located | dm_only | 动作经济与触发条件 |
| core | 野蛮人 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 野蛮人 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 野蛮人 | — | 10 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 野蛮人 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 野蛮人 | — | 13 | 强化凶蛮打击 | description_located | dm_only | 豁免/DC |
| core | 野蛮人 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 野蛮人 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 野蛮人 | — | 17 | 强化凶蛮打击 | description_located | dm_only | 动作经济与触发条件、伤害/治疗 |
| core | 魔契师 | — | 1 | 魔能祈唤 | description_located | dm_only | 动作经济与触发条件 |
| core | 魔契师 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 魔契师 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 魔契师 | — | 9 | 联络宗主 | description_located | dm_only | 施法框架/法术修改、法术选择/准备、资源/恢复/频率、豁免/DC |
| core | 魔契师 | — | 10 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 魔契师 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 魔契师 | — | 13 | 玄奥秘法（七环） | description_reused | full | 施法框架/法术修改、法术选择/准备、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定 |
| core | 魔契师 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 魔契师 | — | 15 | 玄奥秘法（八环） | description_reused | full | 施法框架/法术修改、法术选择/准备、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定 |
| core | 魔契师 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 魔契师 | — | 17 | 玄奥秘法（九环） | description_reused | full | 施法框架/法术修改、法术选择/准备、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定 |
| core | 魔契师 | — | 20 | 魔能掌控 | description_located | dm_only | 施法框架/法术修改、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定 |
