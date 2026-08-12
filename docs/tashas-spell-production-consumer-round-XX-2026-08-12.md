# Round XX：Sword Burst Generic Spell Consumer

当前状态：`accepted`；实现、隔离 evidence、全量门禁、提交与 push 已完成。

- 选中唯一仍具完整通用消费者覆盖的 compile-only spell：`tashas-cauldron:spell:eec6bd94eb83a351fb987de2`（剑刃爆发 / Sword Burst）。真实 source text 逐字段复核了自身 5 尺球形范围、敏捷豁免、失败 1d6 力场伤害、立即持续时间和 5/11/17 级戏法强化；source fingerprint、reviewed fields、manual decisions 和 source evidence 均保留。
- 新增名称无关的 `spell.cantrip_scaling.v1` registry descriptor。`ContentIRRuntimeService` 从已持久化角色等级消费 typed `upcast.progression`，再将解析后的伤害送入现有 `combat_engine.area_damage.v1` 与 `combat_engine.damage_heal.v1`；没有 Sword Burst/name dispatch。
- 真实临时 SQLite API evidence：角色等级 5 时两个范围目标各受到 8 点（2d6），角色等级 1/5/11/17 的输入边界分别为 1d6/2d6/3d6/4d6；成功豁免为 0 伤害。preview→confirm→replay、两个目标 CAS、OperationTransaction、target stale 409、下游失败后的 spell transaction rollback 全部通过。
- Round XX after：Tasha `525 atoms / 408 player-facing / 408 executable / 95 authored Typed IR / 94 compile full / 94 runtime preview full / 83 production full / 2 dm-assisted / 85 game usable / 9 compile-only / 314 manual / 107 DM reference`；项目 production full `183`；ItemSpec 保持 `47/40/40/40`（total/compile/isolated/registered/game usable）。
- 召唤术、智能壁垒、Oceanic Soul、Ambush、Bottled Respite、Psychic Teleportation、Psionic Sorcery、Manifest Mind 没有被本轮顺带提升：它们仍分别缺 summon entity/stat-block lifecycle、defense effect、双触发 eligibility、vessel/teleport/spectral object/payment 等完整通用消费者。
- 正式 database、formal registry、campaign/character、source corpus、3D 和永久保护路径均未写入；migration formal_apply 仍为 false，name branch count 为 0。

证据入口：

- `scripts/validate-tashas-spell-production-consumer-round-XX.py`
- `backend/tests/test_tashas_spell_production_consumer_round_XX.py`
- `reports/tashas-spell-production-consumer-round-XX-2026-08-12.json`
- `data/content-ir/compiled/production-runtime-results-XXII.json`
- `reports/tashas-whole-pack-report-2026-08-11.json`

提交：实现提交 `c2823e5` 已推送到 `origin/main`；receipt 将在独立文档提交中记录。全量后端 pytest `899 passed, 1 warning`、Ruff、compileall、diff-check、三次 migration byte-identical、正式 DB/registry 与保护路径 fingerprint 复核均通过。下一步继续下一个具备完整 generic consumer 的 typed semantic cluster，不为剩余复杂内容增加名称分支。
