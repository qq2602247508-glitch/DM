#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/Users/inagi/codex/900-杂项/uv-cache}"
python_bin="${DND_DM_BACKEND_PYTHON:-$repo_dir/backend/.venv/bin/python}"

if [ -x "$python_bin" ] && "$python_bin" -c "import alembic" >/dev/null 2>&1; then
  export PYTHONPATH="$repo_dir/backend/src${PYTHONPATH:+:$PYTHONPATH}"
  "$python_bin" -m alembic -c backend/alembic.ini upgrade head
  exec "$python_bin" -m dnd_dm_assistant
fi

echo "缺少 backend/.venv；请在联网时运行一次 ./scripts/setup.sh。" >&2
exit 1
