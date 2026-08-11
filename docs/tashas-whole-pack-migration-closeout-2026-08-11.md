# 《塔莎的万事坩埚》整包迁移 I 收口（2026-08-11）

本轮建立了从真实 CHM generated-content 到 source record、Content Atom、Candidate、Review、Typed IR 运行时证据的可重复审计链。原始 source HTML/JSON、正式数据库、正式 registry 和 499 条职业审计均未被迁移脚本改写。

## 真实分母

- Source records：144 / 144 已扫描、已分类；未分类 0。
- Content atoms：625；玩家向 558；executable candidate 558。
- 类型：{"character_option": 15, "class_feature": 64, "companion_profile": 3, "directory": 10, "dm_tool": 7, "environment_rule": 22, "feat": 16, "infusion": 21, "invocation": 9, "magic_item": 103, "magic_tattoo": 36, "maneuver": 8, "narrative": 9, "puzzle": 15, "spell": 21, "subclass_feature": 266}。

## 转换与可用性

- Draft/Candidate/Review：558 / 558 / 558。
- Template match：28（5.02%）；game usable 另按 executable atom 分母报告。
- Authored/verified Typed IR：28；compile full 28；runtime preview full 28。
- Atom status：production_full 18，dm_assisted 1，game usable 19，compile-only 9，manual authoring 530，DM reference 57，non-instantiable 10。
- 现有 authored IR 中有 3 条 provenance 没有匹配到真实原子，已单列，未计入覆盖率。

## 真实阻塞

- Item IR 未实现：139 件物品/刺青仅完成完整 inventory；没有伪装成 production 或 DM-assisted。
- 角色成长全链路未被本轮 inventory 产物冒充完成：pack pin/legacy boundary 已验证，完整升级、降级、快照重建仍需 advancement importer/asset registration。
- 复杂召唤的既有 production evidence 使用正式 typed DM continuation，因此计入 dm_assisted，而不是把“请 DM 决定”文本当作可用。

## 保护与回归

- `backend/tests/integrations/` 与 `backend/tests/ollama.py` 的执行前指纹已记录；最终门禁会再次比较。
- 报告、atom index 和 pack manifest 由固定日期、稳定排序和 source fingerprint 生成，可连续运行并进行 byte-identical 比较。
- 新增 runtime consumer：0；新增 feature/spell/item name branch：0。

下一步应优先建设通用 ItemSpec + equipment/attunement/resource consumer，再处理奇械师注法、魔能祈唤、战技和复杂子职的 choice/resource/实体生命周期闭环；它们的 atom 分母已经在本轮固定。
