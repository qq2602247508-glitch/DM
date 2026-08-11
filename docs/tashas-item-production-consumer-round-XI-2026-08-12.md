# Tasha ItemSpec Production Consumer Round XI

本轮先复核 ItemSpec 内容质量，再扩展真实通用 equipment consumer evidence。

## 内容质量修复

- 原 parser 的自由 inline spell 抽取会把职业法器描述、法术书目录、状态名和“这道法术”误识别为 `granted_spell`，例如月镰/自然斗篷的“德鲁伊或游侠法术”、刺青的 Grappled/Restrained、以及法术书中的目录。
- `_explicit_spell_identities()` 现在只接受源文明确出现的 `施展*中文名**English Name*法术` 形态，并拒绝 generic/class/condition 候选；未解析的 spell clause 保持 manual/partial。真实明确的易容术 Disguise Self 仍被保留。
- 重建结果从 `41 compile_full` 收紧为 `37 compile_full`；这是删除误识别 executable claim，不是降低真实 content coverage。

## 真实 evidence

- 新选 8 条完整 ItemSpec：假肢、星卜编集、寰宇图纂、钟铃圣枝、奉献香炉、织心入门、灵肉圣契、异界行访录。
- 8/8 通过共享 equipment harness 的 create，以及 attune/equip、granted action、use charge 的 preview → confirm → 幂等 replay；16 个 operation transaction 均在临时迁移 SQLite 中持久化。
- ItemSpec catalog：`47 total / 37 compile_full / 37 isolated_runtime_validated / 16 registered_production_full / 16 game_usable`。Feature 的 Tasha status 仍独立为 `production_full=74`、`dm_assisted=2`、`game_usable=76`。
- 通用 consumer 仍为 `item.equipment_modifier.v1`、`item.attunement.v1`、`item.charge_resource.v1`、`item.granted_action.v1`，没有 item-name dispatch 或 name branch。

## 边界与证据

- `formal_apply=false`、`formal_registry_written=false`、`formal_database_written=false`；生产 evidence 仍来自临时隔离数据库，不写正式 campaign/character/database。
- Round XI report/result：`reports/tashas-item-production-consumer-round-XI-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-XIII.json`。
- Validator/test：`scripts/validate-tashas-item-production-consumer-round-XI.py`、`backend/tests/test_tashas_item_production_consumer_round_XI.py`；Round X shared harness 同步支持无动作 charge operation 与非武器默认装备槽。
