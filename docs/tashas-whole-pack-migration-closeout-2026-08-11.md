# 《塔莎的万事坩埚》整包迁移 I 收口（2026-08-11）

本轮建立了从真实 CHM generated-content 到 source record、Content Atom、Candidate、Review、Typed IR 运行时证据的可重复审计链，并把 ItemSpec、角色成长降级/pack pin 和 DM continuation 接入隔离验证。原始 source HTML/JSON、正式数据库、正式 registry 和 499 条职业审计均未被迁移脚本改写。

## 真实分母

- Source records：144 / 144 已扫描、已分类；未分类 0。
- Content atoms：524；玩家向 407；executable candidate 407。
- 类型：{"character_option": 15, "class_feature": 63, "companion_profile": 3, "directory": 10, "dm_tool": 7, "environment_rule": 22, "feat": 16, "infusion": 16, "invocation": 8, "magic_item": 36, "magic_tattoo": 11, "maneuver": 8, "narrative": 10, "puzzle": 15, "spell": 21, "subclass_feature": 263}。

## 转换与可用性

- Draft/Candidate/Review：407 / 407 / 407。
- Template match：93（22.85%）；game usable 另按 executable atom 分母报告。
- Authored/verified Typed IR：94；compile full 93；runtime preview full 93。
- Atom status：production_full 74，dm_assisted 2，game usable 76，compile-only 17，manual authoring 314，DM reference 107，non-instantiable 10。
- 现有 authored IR：95 条；匹配 94，别名协调 2，明确退役 1，孤儿 0。

## 真实阻塞

- ItemSpec：47 件物品/刺青均已 typed；compile full 37，isolated runtime validated 37，registered production full 24，game usable 24；剩余 10 个保留逐条 DM/人工语义边界。
- 角色成长：pack pin、升级、历史快照降级、选择/资源/快照重建和 CAS/幂等已有隔离闭环；整包 feature/option typed/production 阈值仍未达到，不宣称整包 production closed。
- 复杂召唤的既有 production evidence 使用正式 typed DM continuation，因此计入 dm_assisted，而不是把“请 DM 决定”文本当作可用。

## 保护与回归

- `backend/tests/integrations/` 与 `backend/tests/ollama.py` 的执行前指纹已记录；最终门禁会再次比较。
- 报告、atom index 和 pack manifest 由固定日期、稳定排序和 source fingerprint 生成，可连续运行并进行 byte-identical 比较。
- 新增 runtime consumer：0；新增 feature/spell/item name branch：0。

下一步应优先把剩余 feature/option manual atoms 逐字段审阅成 FeatureSpec，特别是奇械师注法、魔能祈唤、战技、选择/资源/实体生命周期；不得通过名称分支或把 manual boundary 改名为 production。
