# Round XXII：Soulknife Psychic Teleportation Typed Feature Consumer

本轮已验收并推送。目标是把 `content.tashas-cauldron.round2.feature.soulknife-psychic-teleportation` 从 compile-only 的传送目的地边界接入现有名称无关 Feature Action consumer。

## Typed IR 与运行时

- authored Feature IR 复核了源文、source fingerprint、reviewed fields 和 `manual_decisions`，将源规则表达为 `consume_resource(psionic_dice, 1)` 与 `teleport(visible_unoccupied_space, movement_roll_total × 10 ft)` 两个 typed effects；`source_completeness=complete`，`unmodeled_source_terms=[]`。
- 新增通用 `teleport` OperatorContract、`movement.teleport` production-closed capability 和 materializer；物化结果为 bonus-action `feature_action`，由 `combat_engine.feature_action.v1` 消费。
- `ContentIRRuntimeRequest` 正式保留目的地行列和 movement roll；preview 输出最大距离与目的地，confirm 将字段传给既有权威网格传送实现。既有 consumer 负责地图边界、障碍、占用、距离、动作经济、资源 CAS、幂等和 OperationTransaction。

## 隔离证据

真实临时 SQLite 通过 `scripts/validate-tashas-feature-production-consumer-round-XXII.py` 验证：

- 被占据目的地确认失败后，`psionic_dice`、角色/战斗版本、网格快照和 bonus action 均保持不变，证明权威失败回滚。
- 合法目的地从 `(2,2)` 传送到 `(2,6)`，movement roll `2` 得 `20 ft` 上限，距离正好 `20 ft`；`psionic_dice` `3→2`，bonus action 消耗。
- preview→confirm→replay、runtime/combat transactions、consumer ID、formal registry/database unchanged、name branch 0 均通过。

## 门禁与边界

- Round XXII report/result：`reports/tashas-feature-production-consumer-round-XXII-2026-08-12.json`、`data/content-ir/compiled/production-runtime-results-XXIV.json`。
- 定向 pytest、完整 backend pytest `903 passed, 1 warning`、`backend/src` 与 `backend/tests` Ruff、compileall、`git diff --check` 通过。
- whole-pack migration 共 6 次运行成功；evidence 名称对齐后的最终两次关键迁移报告 SHA-256 byte-identical。after 为 Tasha `525/408/408/95/94/94/85/2/87/7/314/107`，项目 production full `185`，ItemSpec `47/40/40/40`。
- 实现提交 `da93a60` 与证据可追溯性修正 `816a9dc` 已推送到 `origin/main`；receipt 单独提交。正式 registry/database、原始 source corpus、3D 项目和两条永久保护路径均未写入。

本轮是 movement/feature-action platform-core exception，批次为 1；正常语义批次门槛仍为 8。剩余 summon/entity、defense、communication、maneuver eligibility、vessel 和 spectral-object seam 继续 fail-closed。
