# Round XXXIV：巨灵宗主扩展法术列表 Character-Growth Consumer

## 选择与边界

Round XXXIII 基线为 Tasha `105 authored / 104 compile / 104 preview / 100 production / 2 compile-only`，项目为 `200 production / 35 compile-only / 111 unique compiled`。

本轮选择 source-complete 的 `content.tashas-cauldron.round2.feature.genie-expanded-spell-list`。它只覆盖巨灵宗主原文中的“将法术加入魔契师法术列表进行选择”边界，不把这些法术误写成已知或恒备法术。

`genie-bottled-respite` 继续 compile-only：器皿进入/离开、空间位置、器皿摧毁、停留时间和短休仍是复合 vessel boundary。`scribe-manifest-mind` 继续 compile-only：灵体物件移动、300 尺距离过期和长休/法术位再激活仍未闭合。

## 实现

- 新增 `configure_spell_list_expansion` typed operator。
- 新增 `advancement.spell_list_expansion` capability 与 materializer。
- 新增 `spell_list_expansions` runtime section，保存 common spells、按 `genie_type` 的四组选择项、`selection_mode=available_to_learn` 与完整 source provenance。
- 复用 `advancement_service.character_growth.v1` 的 preview → confirm → OperationTransaction → Character version CAS → replay 边界。
- 不新增 feature-name runtime branch；未知 section、错误 provenance、重复法术、未知选择表和非 `available_to_learn` 语义 fail-closed。

## 真实证据

Round XXXIV validator 通过：`preview / confirm / replay / character CAS / transaction / feature persistence` 全部成功，`spell_grants=0`，证明这是法术列表访问权而不是错误的法术授予。

结果：

- Tasha：`106 authored / 105 compile / 105 preview / 101 production / 2 compile-only`
- 项目：`201 production / 35 compile-only / 111 unique compiled`
- delta：Tasha production `+1`，项目 production `+1`，compile-only `0`，unique compiled `0`
- consumer：`advancement_service.character_growth.v1`
- `name_branch_count=0`
- formal database/registry 未写入
- 保护路径 fingerprint 未变化

证据入口：

- `scripts/validate-tashas-feature-production-consumer-round-XXXIV.py`
- `backend/tests/test_tashas_feature_production_consumer_round_XXXIV.py`
- `reports/tashas-feature-production-consumer-round-XXXIV-2026-08-13.json`
- `data/content-ir/compiled/production-runtime-results-XXXIV.json`
