# Feature Pack 导入就绪度（2026-08-09）

本轮新增 `FeaturePackManifest` 和本地版本化导入器。导入器不修改角色快照，只管理经过 IR 编译的特性定义。

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
legacy shadow parity: 30 selected full rows
compiler authority pilot: 10 rows
official audit: 310 full / 128 partial / 61 dm_only
```

## 当前限制

当前导入器已经具备 dry-run、apply、版本和幂等保护，但真实生产拓展包仍需要由可信来源提供 `authored_ir` 或 `verified_mapping`。非结构化 PDF/自然语言只能生成 draft，不能直接授予 full。下一步应继续增加通用 capability，并用扇出测试证明同一 capability 可以让多条 FeatureSpec 无需修改就从 partial 变成 full。
