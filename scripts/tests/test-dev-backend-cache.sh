#!/bin/bash
set -eu

repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
state_dir="$(mktemp -d "${TMPDIR:-/tmp}/dnd-dm-backend-cache.XXXXXX")"
trap 'rm -rf "$state_dir"' EXIT

mkdir -p "$state_dir/bin"
cat >"$state_dir/bin/uv" <<'EOF'
#!/bin/bash
printf '%s\n' "${UV_CACHE_DIR:-UNSET}" >>"$DND_TEST_CACHE_LOG"
exit 0
EOF
chmod +x "$state_dir/bin/uv"

unset UV_CACHE_DIR
DND_TEST_CACHE_LOG="$state_dir/cache.log" \
  PATH="$state_dir/bin:$PATH" \
  /bin/bash "$repo_dir/scripts/dev-backend.sh"

expected="/Users/inagi/codex/900-杂项/uv-cache"
if [ "$(wc -l <"$state_dir/cache.log" | tr -d ' ')" -ne 2 ]; then
  echo "Expected both uv commands to run" >&2
  exit 1
fi
if grep -Fvx "$expected" "$state_dir/cache.log" >/dev/null; then
  echo "Backend launcher did not use the reusable writable uv cache" >&2
  cat "$state_dir/cache.log" >&2
  exit 1
fi
