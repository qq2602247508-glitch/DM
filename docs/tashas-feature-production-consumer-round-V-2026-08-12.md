# 《塔莎的万事坩埚》Feature Production Consumer Round V

日期：2026-08-12。本轮把 Round-II authored Feature IR 中的 advancement typed contract 接入真实角色成长消费者，在临时迁移 SQLite 上完成 8 条 production evidence。正式 campaign、character、database、formal registry 和 source corpus 没有写入。

## 证据结果

| 层级 | 结果 | 说明 |
| --- | ---: | --- |
| selected contracts | 8 | 固定熟练/语言、选择项、grant_spell |
| preview → confirm → replay | 8/8 | 每条均通过 character CAS、operation transaction 和幂等重放 |
| typed production evidence | 8 | `data/content-ir/compiled/production-runtime-results-VII.json` |
| typed consumer | 8/8 | `advancement_service.character_growth.v1` |
| choice lifecycle | 3 | Order Cleric、Skill Expert、Ranger Canny |
| grant_spell | 1 | Aberrant Mind psionic spell list，10 个 grant |
| Tasha registered production full | 44 | 36→44 |
| Tasha game usable | 46 | `registered_production_full + dm_assisted` |

## 覆盖合同

- Bladesinger、Peace Cleric、Rune Knight、Twilight Cleric：固定 weapon/armor/tool/skill/language grant。
- Order Cleric、Skill Expert、Ranger Canny：同一 typed advancement consumer 消费选择输入并写入 skills/proficiencies。
- Aberrant Mind Psionic Spell List：消费 10 个 typed `grant_spell`，保留 source feature、grant mode、casting ability 和稳定 source identity。

## 通用实现

- `ContentIRRuntimeRequest` 增加 `content_kind=advancement`，复用既有 content IR runtime preview/confirm 路由。
- `ContentIRRuntimeService` 对 feature ID、`automation_status=full`、`runtime_execution.status=ready`、typed sections 做 fail-closed 校验；不按 feature 名称分支。
- `advancement_service.character_growth.v1` 由 `advancement` / `proficiencies` / `prepared_spell_list` block 解析；固定与选择 grant 统一写入 character feature/proficiency/skill/spell snapshot。
- confirm 使用 `OperationTransaction`、character version CAS 和 idempotency key；失败不会把 preview 结果提升为 production。

## 边界与门禁

所有 evidence 使用临时迁移数据库，`formal_apply=false`、`formal_registry_written=false`、`formal_database_written=false`。正式 499 职业审计保持 `328 full / 110 partial / 61 dm_only`。数据库指纹为 `f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad`；两个受保护未跟踪测试路径保持原指纹。

Round V validator 与 whole-pack migration 均连续重跑；关键结果、报告、status layer 和 isolated runtime 文件 byte-identical。完整 backend pytest、Round V/历史 Tasha 定向回归、compileall、变更源 Ruff、`git diff --check` 均作为本轮门禁。

证据：`scripts/validate-tashas-feature-production-consumer-round-V.py`、`reports/tashas-feature-production-consumer-round-V-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-VII.json`。

下一轮继续处理剩余 vessel/entity、exhaustion、spectral object、teleport destination、psionic payment 和 ItemSpec lifecycle；未经过真实 producer/consumer/persistence/CAS/replay 的合同继续停在 isolated、compile-only 或 manual boundary。
