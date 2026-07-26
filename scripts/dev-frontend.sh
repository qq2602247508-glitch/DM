#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

if [ ! -d "$repo_dir/frontend/node_modules" ]; then
  echo "缺少 frontend/node_modules；请在联网时运行一次 ./scripts/setup.sh。" >&2
  exit 1
fi

exec npm --prefix frontend run dev -- --host 127.0.0.1
