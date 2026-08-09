# 职业/子职业特性源码级审计

这份报告把源码描述解析状态与运行时执行状态分开统计。积木覆盖数允许重叠，一条特性可以使用多个积木；检测到积木不等于已有执行器。

- 总条目：499
- 核心职业：12 个，特性 258 条
- 子职业：56 个，显式等级特性 241 条
- 运行时状态：`{'full': 314, 'dm_only': 61, 'partial': 124}`
- 源码读取状态：`{'description_located': 415, 'structural_placeholder': 35, 'description_reused': 49}`

## 积木覆盖（允许重叠）

| 积木 | 源码候选 | full | partial | dm_only |
|---|---:|---:|---:|---:|
| 成长授予/升级选择 | 86 | 81 | 5 | 0 |
| 施法框架/法术修改 | 126 | 76 | 39 | 11 |
| 法术框架详细修改 | 1 | 0 | 0 | 1 |
| 法术选择/准备 | 58 | 51 | 6 | 1 |
| 动作经济 | 72 | 23 | 48 | 1 |
| 动作经济与触发条件 | 225 | 129 | 80 | 16 |
| 资源/恢复/频率 | 195 | 107 | 77 | 11 |
| 资源/恢复绑定 | 66 | 34 | 26 | 6 |
| 伤害/治疗 | 135 | 63 | 60 | 12 |
| 伤害前/防御干预 | 17 | 6 | 10 | 1 |
| 光环/范围被动 | 83 | 23 | 56 | 4 |
| 掷骰干预 | 49 | 29 | 20 | 0 |
| 命中后骑手 | 13 | 4 | 7 | 2 |
| 豁免/DC | 82 | 30 | 47 | 5 |
| 目标/范围/豁免组合 | 82 | 20 | 57 | 5 |
| 移动/位移 | 38 | 9 | 28 | 1 |
| 0 HP/死亡生命周期 | 8 | 4 | 3 | 1 |
| 状态生命周期 | 90 | 38 | 50 | 2 |
| 召唤/伙伴 | 19 | 8 | 10 | 1 |
| 创造物/世界状态 | 20 | 5 | 15 | 0 |
| 语言/开放叙事 | 1 | 1 | 0 | 0 |
| 多分支选择 | 6 | 3 | 2 | 1 |

## 需要优先复核的条目

| 范围 | 职业 | 子职业 | 等级 | 特性 | 源码状态 | 运行时 | 检测积木 |
|---|---|---|---:|---|---|---|---|
| core | 吟游诗人 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 吟游诗人 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 吟游诗人 | — | 9 | 专精 | description_reused | full | 成长授予/升级选择、动作经济与触发条件 |
| core | 吟游诗人 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 吟游诗人 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 吟游诗人 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 吟游诗人 | — | 20 | 创生圣言 | description_located | dm_only | 施法框架/法术修改、法术框架详细修改、法术选择/准备、动作经济与触发条件、光环/范围被动、目标/范围/豁免组合 |
| core | 圣武士 | — | 7 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 圣武士 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 圣武士 | — | 9 | 弃绝众敌 | description_located | dm_only | 资源/恢复/频率、资源/恢复绑定、伤害/治疗、光环/范围被动、豁免/DC、目标/范围/豁免组合、状态生命周期 |
| core | 圣武士 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 圣武士 | — | 15 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 圣武士 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 圣武士 | — | 20 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
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
| core | 术士 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 术士 | — | 7 | 术法化身 | description_located | dm_only | 资源/恢复/频率 |
| core | 术士 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 术士 | — | 10 | 超魔法 | description_reused | full | 动作经济与触发条件、资源/恢复/频率 |
| core | 术士 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 术士 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 术士 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 术士 | — | 17 | 超魔法 | description_reused | full | 动作经济与触发条件、资源/恢复/频率 |
| core | 术士 | — | 18 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 术士 | — | 20 | 奥术化神 | description_located | dm_only | 资源/恢复/频率 |
| core | 武僧 | — | 2 | 运转周天 | description_located | dm_only | 动作经济与触发条件、资源/恢复/频率、资源/恢复绑定、伤害/治疗 |
| core | 武僧 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 武僧 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 武僧 | — | 9 | 飞檐走壁 | description_located | dm_only | 未检测到 |
| core | 武僧 | — | 10 | 出神入化 | description_located | dm_only | 动作经济与触发条件、资源/恢复/频率、伤害/治疗、光环/范围被动、目标/范围/豁免组合 |
| core | 武僧 | — | 11 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 武僧 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 武僧 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 武僧 | — | 17 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 法师 | — | 5 | 记忆法术 | description_located | dm_only | 施法框架/法术修改、动作经济与触发条件、资源/恢复/频率 |
| core | 法师 | — | 6 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 法师 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 法师 | — | 10 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 法师 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 法师 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 法师 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 法师 | — | 18 | 法术精通 | description_located | dm_only | 施法框架/法术修改、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定 |
| core | 法师 | — | 20 | 招牌法术 | description_located | dm_only | 施法框架/法术修改、资源/恢复/频率、资源/恢复绑定 |
| core | 游侠 | — | 7 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 游侠 | — | 8 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 游侠 | — | 11 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 游侠 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 游侠 | — | 15 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 游侠 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
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
| core | 魔契师 | — | 10 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 魔契师 | — | 12 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 魔契师 | — | 13 | 玄奥秘法（七环） | description_reused | full | 施法框架/法术修改、法术选择/准备、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定 |
| core | 魔契师 | — | 14 | 子职特性 | structural_placeholder | dm_only | 未检测到 |
| core | 魔契师 | — | 15 | 玄奥秘法（八环） | description_reused | full | 施法框架/法术修改、法术选择/准备、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定 |
| core | 魔契师 | — | 16 | 属性值提升 | description_reused | full | 成长授予/升级选择 |
| core | 魔契师 | — | 17 | 玄奥秘法（九环） | description_reused | full | 施法框架/法术修改、法术选择/准备、动作经济与触发条件、资源/恢复/频率、资源/恢复绑定 |
