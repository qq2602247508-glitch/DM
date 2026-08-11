# Tasha ItemSpec Production Consumer Round XV

本轮为 ItemSpec 的 `granted_spell` 语义解锁：修复显式“施展”后 inline spell list
的 typed identity 提取，并把 `item.granted_spell.v1` 接入 equipment action preview 与
transaction snapshot。

## 语义修复

- 解析器同时支持单法术 `施展*中文**English*法术` 与列表式
  `施展以下/下列法术：*中文**English*，...`。
- 解析范围始终锚定在显式“施展”之后；“作为你施展德鲁伊和游侠法术的法器”和“你可以
  施展那道法术”等 generic prose 仍 fail closed，不会生成 spell identity。
- 3 个原本只有 `granted_spell` blocker 的条目解锁为 `compile_full`：鲁芭的灵魂塔罗卡、
  拉奥圣杖、伊格薇尔伏恶魔志。随机表、DM 选择、变量法术的 7 个 partial 条目保持边界。

## 真实运行时闭环

- `equipment_preview` 在 typed `granted_spell` clause 存在时生成
  `item_spell_cast.consumer_id=item.granted_spell.v1`、`grant_mode=item_cast` 和
  去重排序后的 spell identities；同一 typed snapshot 随 `equipment_use_action` 的
  OperationTransaction 返回，未按物品名称分支。
- 3/3 条通过 equipment create → attunement → action/charge → preview → confirm →
  idempotent replay；共 16 个 spell identities、2 条 charge lifecycle、6 个 operation
  transactions，CAS/state/typed consumer/name-branch gate 全通过。
- formal registry/database、campaign/character 和 source corpus 未写入；证据仍在
  isolated migrated SQLite 上运行。

## 状态与证据

- ItemSpec：`47 total / 40 compile_full / 40 isolated_runtime_validated /
  40 registered_production_full / 40 game_usable`。
- 项目 `current_project_production_full` 从 171 增至 174；Tasha Feature 独立维持
  `74 production_full / 2 dm_assisted / 76 game_usable`。
- Validator：`scripts/validate-tashas-item-production-consumer-round-XV.py`。
- Result/report/test：`data/content-ir/compiled/production-runtime-results-XVII.json`、
  `reports/tashas-item-production-consumer-round-XV-2026-08-12.json`、
  `backend/tests/test_tashas_item_production_consumer_round_XV.py`。
- Round XV validator 与 whole-pack migration 各运行两次且 byte-identical；Round X–XV
  定向测试 21 项、backend 全量 pytest 890 项、Ruff、compileall、`git diff --check`
  通过。

下一轮继续审阅剩余 7 个 partial ItemSpec；没有足够 typed source/consumer 的随机表、
DM 选择、变量法术和实体生命周期继续停留在 partial，不通过报告数字自动升级。
