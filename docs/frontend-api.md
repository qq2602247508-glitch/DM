# 前端 API 对接表与后端缺口记录

日期：2026-07-25。本文档以 `backend/src/dnd_dm_assistant/api/routes/*.py` 与
`api/schemas.py`、`domain/agent.py`、`domain/rag.py`、`domain/content.py` 为准，
是前端开发的权威依据。架构文档中列出但路由中不存在的端点，视为未实现。

## 1. 系统状态

| 前端需求 | 后端端点 | 状态 |
|---|---|---|
| 后端 + SQLite 状态 | `GET /api/v1/health` → `{status, database, environment}` | 可用 |
| Qdrant / 向量索引状态 | `GET /api/v1/knowledge/index/status` → `IndexStatus{available, state, reason, points_count, embedding_model, ...}` | 可用 |
| Ollama / 模型可用性 | `GET /runtime/models` | 可用：返回 Ollama、配置模型、安装状态和 Think 开关 |
| readiness 聚合 | `GET /readiness` | 可用：聚合 SQLite、索引和模型状态 |

## 2. 知识库（规则搜索 / 规则问答）

| 前端需求 | 后端端点 | 状态 |
|---|---|---|
| 规则关键词搜索 + 分类/版本/官方筛选 | `POST /api/v1/knowledge/search`，body=`SearchQuery{text, top_k, candidate_k, min_score, content_types[], editions[], source_books[], current_official, allow_unknown, allow_third_party}` → `{hits: SearchHit[]}` | 可用 |
| 规则问答（带引用、拒答） | `POST /api/v1/knowledge/answer`，body=`{question, search?}` → `GroundedAnswer{answer, abstained, reason, citations[]}` | 可用 |
| 结果详情 / 原文展开 | `GET /knowledge/documents/{record_id}` | 可用：返回校验后的完整 NormalizedEntity 原文与 provenance |
| 结果排序 | 无服务端排序参数 | 前端对 hits 客户端排序（相关度/名称/版本） |

枚举（`domain/content.py`）：
`ContentType = rules/classes/subclasses/spells/monsters/items/feats/backgrounds/conditions/actions/equipment/unknown`；
`Edition = 2014/2024/2025/legacy/mixed/unknown`；`Officiality = official/third_party/unknown`。

## 3. 战役与实体

| 前端需求 | 后端端点 | 状态 |
|---|---|---|
| 战役列表/创建/编辑/删除/切换 | `GET|POST /campaigns`，`GET|PATCH|DELETE /campaigns/{id}` | 可用（PATCH/DELETE 需 `If-Match` 或 body `version`） |
| 主控制台聚合 | `GET /campaigns/{id}/state?limit=` → `{campaign, characters[], npcs[], locations[], quests[], open_clues[], active_combats[], as_of}` | 可用 |
| 角色 CRUD | `/campaigns/{id}/characters` 嵌套 CRUD | 可用；字段仅 `name, class_name, level, hp, max_hp, inventory[], notes` |
| 角色条件 | `/characters/{id}/conditions` 嵌套 CRUD | 可用 |
| NPC CRUD | `/campaigns/{id}/npcs` | 可用；字段 `name, description, personality, relationship, secrets, known_information, location_id, status` |
| 地点 CRUD + 连接 | `/campaigns/{id}/locations` + `/locations/{id}/connections` | 可用 |
| 任务 CRUD | `/campaigns/{id}/quests`；字段 `name, description, status, notes` | 可用 |
| 线索 CRUD | `/campaigns/{id}/clues`；字段 `name, description, quest_id, discovered, discovered_at, source_event_id` | 可用 |
| 事件 | `/campaigns/{id}/events` 嵌套 CRUD | 可用 |
| 战斗 + 参战者 | `/campaigns/{id}/combats` + `/combats/{id}/combatants` | 可用；combatant 字段 `display_name, entity_type, entity_id, initiative, hp, max_hp, conditions[], is_active` |

结构化 D&D 扩展字段已经落库并接入前端：

- 角色：种族、AC、速度、六维属性、结构化装备。
- NPC：阵营、态度、目标、恐惧。
- 任务：主线/支线/个人/阵营、发布者、奖励。
- 线索：验证状态、DM 真相、玩家可见版本。
- 参战者：AC。

## 4. AI 助手与提案

| 前端需求 | 后端端点 | 状态 |
|---|---|---|
| 自然语言行动 → DM Hint | `POST /campaigns/{id}/assistant/turns`，body=`{action}` → `AgentResponse{dm_hint?, tool_results[], citations[], proposals[], abstained, errors[]}` | 可用（单次请求，无流式） |
| 显示 AI 是否读取战役状态 | 从 `tool_results[]` 中 `tool == "get_campaign_state"` 且 `ok` 推断 | 可用（真实数据） |
| 规则引用 | `AgentResponse.citations[]` / `dm_hint.citations[]`（`Citation{rule_name, source_title, section, heading_path[], content_type, edition, officiality, source_book, canonical_url, score}`） | 可用 |
| 不确定性 / 假设 | `dm_hint.uncertainties[]`、`dm_hint.assumptions[]` | 可用 |
| 模型不可用 | 503 + `errors[]` / HTTP detail | 可用，前端展示配置指导 |
| 待确认提案列表 | `GET /campaigns/{id}/change-proposals?status=pending` | 可用 |
| 提案历史 | 同上，`status=confirmed/rejected/conflict` 分别查询 | 可用（需 3 次请求合并） |
| 确认 / 拒绝 | `POST .../change-proposals/{pid}/confirm|reject` → `ProposalDecision{proposal, applied_entity, already_decided}`；版本冲突返回 409 | 可用 |
| 修改前/后对比 | 无 diff 端点 | 前端用真实当前实体（GET 对应实体）与 `payload` 做字段级对比 |
| 会话历史 | 无后端 sessions/messages 端点 | 前端按战役保存在本机浏览器，可显式清空；不作为战役事实来源 |
| SSE 流式输出 | 无 | 前端用 loading 态 + 完整响应 |

`StateChangeProposal` 字段：`id, campaign_id, tool_name, operation(create/update/delete), entity_type(character/npc/quest/event), entity_id, payload, expected_version, reason, status(pending/confirmed/rejected/conflict), created_by_model, request_id, created_at, updated_at, decided_at, version`。

## 5. 通用约定

- 错误信封：`{code, message, details, request_id}`。前端据此给出中文可读说明。
- 版本冲突：409；缺少版本：428；校验失败：422（`details` 为 pydantic 错误数组，可映射到表单字段）。
- 变更操作必须携带 `version`（body）或 `If-Match` 头；前端统一用 body `version`。
- 分页：list 返回 `{items, limit, offset}`，稳定 `created_at, id` 排序。
