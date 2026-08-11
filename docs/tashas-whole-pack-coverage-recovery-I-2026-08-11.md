# 《塔莎的万事坩埚》整包覆盖恢复 I（2026-08-11）

本轮是覆盖恢复实施记录，不是把旧报告换名。脚本固定 source fingerprint、真实分母、隔离 pack 和 CAS/幂等运行时证据；正式数据库、正式 registry、真实 campaign/character 和原始 CHM source 均未写入。

## QA 与分母

- Source records：144/144；Content Atoms：524；玩家向 executable：407。
- 第一轮分母：625 atoms / 558 executable；本轮清理后：524 / 407；QA 删除/合并候选 115，结构检查全部通过。
- Item QA：magic item 36，magic tattoo 11；不存在 page heading/表格行冒充 item asset。

## ItemSpec 与运行时

- `item-ir-1` typed/reviewed：47/47；compile full：41；isolated runtime validated：41；registered production full：0；game usable：0；保留 DM 边界：6；name branch：0。
- 通用 consumer：equipment modifier、attunement/tattoo lifecycle、charge/recovery、granted action/spell、consumable、triggered effect；复用 EquipmentInstance、Attunement、RestService、Rules Kernel projection 和 transaction/CAS/idempotency。
- 隔离测试已覆盖同调、Item action charge、DM decision window、replay、rollback、短/长休 charge recovery；dawn 不被错误转换成 long rest。

## Feature/Option 与角色成长

- Feature/Option reviewed：339；typed 85；compile 85；production 41；DM-assisted 1。该批次仍未达到 120/100/80/50/10 硬阈值，保持 partial，不虚报覆盖。
- 新增 28 个 name-independent semantic/template interfaces，其中 item 相关 5 个达到保守 unlock gate；feature/option cluster 的未知合同字段仍阻断 unlock。
- 角色成长增加历史快照支撑的降级、不可变 pack pin、选择/资源/动作/休息重建和 CAS/幂等验证；整包 feature/option 资产不足以宣称 whole-pack production closed。

## Provenance / DM / 门禁

- Authored provenance：95 total；orphan 0；2 条工具熟练别名已协调，Precision Attack 已按 build recommendation source 明确退役。
- DM continuation contract 已实现并由隔离 API fixture 验证；本轮真正新增并记账的 DM-assisted 仍为 0，已有 DM-assisted 为 2；未把 pending/manual 条目冒充成完成。
- 下一阶段：逐字段收割 FeatureSpec/Option IR，优先选择/资源/触发/目标/持续时间/召唤实体生命周期；继续保持单线程、临时 DB/隔离 pack 和 fail-closed。
