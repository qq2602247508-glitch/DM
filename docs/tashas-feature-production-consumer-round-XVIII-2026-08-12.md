# Tasha Feature Production Consumer Round XVIII

本轮完成一个平台核心增长：把 typed `roll_intervention` 接到真实玩家掷骰窗口，并恢复一个来源声明的 authored subclause atom。批次只有 2 条，因为这是共享 combat consumer、actor-side resource CAS 和 `attack_type` eligibility 的核心闭环，不把单条内容伪装成普通 8 条批次。

## 真实 evidence

- `content.tashas-cauldron.feature.battle-master.commanding-presence` 的 typed clause 物化为通用 `roll_intervention`：`ability_check`、魅力属性、威吓/表演/游说、卓越骰输入和 `superiority_dice` 资源绑定。
- `content.tashas-cauldron.feature.battle-master.precision-attack` 的 typed clause 物化为同一通用 consumer：`attack_declared`、`armor_class`、`weapon_attack` eligibility、卓越骰输入和资源 CAS；`spell_attack` 边界不会打开该窗口。
- `CombatEngineService` 的通用掷骰窗口现在扫描 target 与 actor 的 typed Feature Runtime，再扫描战斗内其它合法反应者；actor 自身的攻击不再被错误地当作目标特性解析。`attack_type` 进入 Player Roll prompt schema 和 resolver context，非 AC prompt fail closed。
- `feature_materializers.py` 只按 trigger/stat/applies_when/value_source/consume_resource 等 typed 字段投影，不按 Feature 名称分支。未满足完整语义形状的旧 `superiority_die` modifier（例如未接入的战术预估）继续落在原 typed combat modifier，不被误升级。
- atomizer 新增通用 `add_authored_subclause_atoms()`：只有 authored IR 明确声明 `source_subclause=true`、`source_content_kind`、source record identity 且未匹配现有 atom 时才生成稳定 atom。精准攻击因此不再被旧的显式退休规则吞掉；source records 仍为 144，source fingerprint 和 source record identity 保留。

## 隔离运行结果

- 临时迁移 SQLite 完成两个闭环：领导风范 `12+4=16`，卓越骰 `4→3`；精准攻击 `12+5=17`，卓越骰 `3→2`；两者均通过 preview/open → confirm → 幂等 replay、character version CAS、资源 transaction 和 typed consumer。
- 真实 API 边界验证：`weapon_attack` 打开精准攻击窗口；同一角色的 `spell_attack` 不打开窗口。Round XVIII report 的 `selected_count=2`、`production_runtime_full_count=2`、`all_preview_confirm_replay=true`、`character_cas_and_transaction=true`、`weapon_attack_only_boundary=true`、`name_branch_count=0`。
- 正式 registry/database/campaign/character 未写入；formal 499 仍为 `328 full / 110 partial / 61 dm_only`；ItemSpec 独立保持 `47 total / 40 compile / 40 isolated / 40 registered / 40 game usable`。

## 整包覆盖结果

- Tasha whole-pack：`525 atoms / 408 player-facing / 408 executable / 95 authored typed IR / 94 compile_full / 94 runtime_preview_full / 81 production_full / 2 dm_assisted / 83 game_usable / 11 compile-only / 314 manual_authoring / 107 DM reference`。
- 当前项目：`111 unique compiled / 35 compile-only / 181 production_full`。`game_usable = registered_production_full + dm_assisted` 的关系继续保持。
- Ambush 没有因共用卓越骰而被顺带提升：其来源同时要求敏捷（隐匿）和先攻，而当前 typed IR 还没有完整的双触发 eligibility，继续 fail closed。

## 证据与门禁

- Validator：`scripts/validate-tashas-feature-production-consumer-round-XVIII.py`。
- Test：`backend/tests/test_tashas_feature_production_consumer_round_XVIII.py`；既有 `test_feature_runtime_combat.py`、`test_combat_engine.py` 回归通过。
- Result/report：`data/content-ir/compiled/production-runtime-results-XX.json`、`reports/tashas-feature-production-consumer-round-XVIII-2026-08-12.json`。
- Whole-pack migration 连续运行两次，whole-pack report、coverage、atom QA、production report、isolated runtime registry/definitions/manifest 关键 SHA-256 完全一致。
- Round XVI character-growth validator、Round XVII rest validator、Feature contract batch validator 均通过；Ruff、compileall、`git diff --check` 通过。

下一轮继续已有 typed IR 的下一个通用语义簇；不为 Ambush 的双触发、不完整 entity/communication/teleport/random-table 或 DM-only 语义增加名称分支。
