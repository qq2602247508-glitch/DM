#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
failed=0

check_file() {
  local label="$1"
  local path="$2"
  if [ -e "$path" ]; then
    echo "✓ $label"
  else
    echo "✗ $label：缺少 $path" >&2
    failed=1
  fi
}

check_file "后端 Python 环境" "$repo_dir/backend/.venv/bin/python"
check_file "Alembic 迁移工具" "$repo_dir/backend/.venv/bin/alembic"
check_file "前端依赖" "$repo_dir/frontend/node_modules"
check_file "前端入口" "$repo_dir/frontend/package.json"

if command -v sqlite3 >/dev/null 2>&1; then
  echo "✓ SQLite 工具"
else
  echo "△ 未找到 sqlite3 命令；应用仍可使用 Python 内置 SQLite" >&2
fi

if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "✓ Ollama 本地模型服务"
else
  echo "△ Ollama 当前未响应；规则库和手动 DM 功能仍可离线使用" >&2
fi

if [ "$failed" -ne 0 ]; then
  echo "启动前检查失败。请保留现有本地依赖，不要在离线状态执行安装。" >&2
  exit 1
fi

echo "启动前检查通过。"
