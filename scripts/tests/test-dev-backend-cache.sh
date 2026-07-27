#!/bin/bash
set -eu

repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
state_dir="$(mktemp -d "${TMPDIR:-/tmp}/dnd-dm-backend-cache.XXXXXX")"
trap 'rm -rf "$state_dir"' EXIT

mkdir -p "$state_dir/bin"
cat >"$state_dir/bin/alembic" <<'EOF'
#!/bin/bash
printf 'alembic|%s|%s\n' "${UV_CACHE_DIR:-UNSET}" "$*" >>"$DND_TEST_CACHE_LOG"
exit 0
EOF
cat >"$state_dir/bin/python" <<'EOF'
#!/bin/bash
printf 'python|%s|%s\n' "${UV_CACHE_DIR:-UNSET}" "$*" >>"$DND_TEST_CACHE_LOG"
exit 0
EOF
chmod +x "$state_dir/bin/alembic" "$state_dir/bin/python"

unset UV_CACHE_DIR
DND_TEST_CACHE_LOG="$state_dir/cache.log" \
DND_DM_BACKEND_ALEMBIC="$state_dir/bin/alembic" \
DND_DM_BACKEND_PYTHON="$state_dir/bin/python" \
  /bin/bash "$repo_dir/scripts/dev-backend.sh"

expected="/Users/inagi/codex/900-杂项/uv-cache"
if [ "$(wc -l <"$state_dir/cache.log" | tr -d ' ')" -ne 2 ]; then
  echo "Expected migration and backend commands to run" >&2
  exit 1
fi
if grep -Fv "|$expected|" "$state_dir/cache.log" >/dev/null; then
  echo "Backend launcher did not preserve the reusable writable uv cache" >&2
  exit 1
fi
if ! grep -F "alembic|$expected|-c backend/alembic.ini upgrade head" "$state_dir/cache.log" >/dev/null; then
  echo "Backend launcher did not run migrations" >&2
  exit 1
fi
if ! grep -F "python|$expected|-m dnd_dm_assistant" "$state_dir/cache.log" >/dev/null; then
  echo "Backend launcher did not start the application" >&2
  exit 1
fi

echo "Backend launcher cache regression passed."
