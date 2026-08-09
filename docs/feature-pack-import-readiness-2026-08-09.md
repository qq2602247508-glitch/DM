# Feature Pack 导入就绪度（2026-08-09）

本轮新增 `FeaturePackManifest` 和本地版本化导入器。导入器不修改角色快照，只管理经过 IR 编译的特性定义。

## 生产化硬化 I 检查点

Manifest 现在显式声明 `source_trust`。`authored_ir`/`verified_mapping` 才能自动 full；
`generated_draft`、`unstructured_source` 或未声明信任会保留为 draft/partial，并从 execution
lookup 中排除。

`FeaturePackImporter --apply` 会把 full feature 物化成现有生产 runtime contract，并写入本地
`FeaturePackRegistry`。Registry 支持 reload、按 `namespace/feature_id/pack_version` 稳定查询、
角色 pack/version pin、重复 apply 幂等、同版本 fingerprint 冲突和版本更新 clause diff。
breaking update 只生成 migration plan，不静默修改已经 pin 的角色。

当前演示包 24 条仍为 `18 full / 4 partial / 2 manual`；18 条都有完整参数、materializer 和
validator 证据。生产扇出报告证明六条 FeatureSpec 在同一 capability 注册后无需修改 specs
即可 full，并进入两个真实 runtime projection。

## 命令

```bash
backend/.venv/bin/python scripts/import-feature-pack.py \
  backend/tests/fixtures/feature_packs/automation_demo_pack.json \
  --dry-run

backend/.venv/bin/python scripts/import-feature-pack.py \
  path/to/pack.json \
  --apply \
  --target-dir data/feature-packs/compiled
```

## 安全合同

- pack/schema/version/namespace/feature ID 严格校验；
- feature 的 pack/version/namespace 必须一致；
- 未知 IR 字段、operator 和 schema version fail-closed；
- 同一 pack/version 重复 apply 是幂等重放；
- 相同 pack/version 不允许不同 fingerprint 覆盖；
- 版本更新生成 migration plan，不静默改写已有角色冻结快照；
- partial 和 manual 可以导入，但不能被写成 full；
- 不执行任意 Python 或自然语言表达式；
- 导入顺序不影响编译结果和 fingerprint。

## 自动装配试点

测试包 `backend/tests/fixtures/feature_packs/automation_demo_pack.json` 共 24 条：

- 18 条由现有 `production_closed` capability 自动编译为 full；
- 4 条使用未知 operator，准确编译为 partial；
- 2 条声明人工裁定边界，准确编译为 manual。

该测试包不计入正式 499 条审计。当前机器报告：

```text
demo pack: 18 full / 4 partial / 2 manual
strict operator contracts: 34
formal semantic parity: 10/10 exact-or-equivalent
production fan-out: 6 partial -> 6 full
compiler authority: 10 authored features
official audit: 310 full / 128 partial / 61 dm_only
```

## 当前限制

当前导入器已经具备 dry-run、apply、reload、稳定 lookup、pin、版本和幂等保护。真实生产拓展包
仍需要由可信来源提供 `authored_ir` 或 `verified_mapping`；非结构化 PDF/自然语言只能生成 draft，
不能直接授予 full。新增 capability 必须同时补 contract、descriptor、materializer、validator、
真实 consumer evidence 和扇出回归。
