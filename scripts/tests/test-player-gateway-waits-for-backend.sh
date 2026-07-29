#!/bin/bash
set -eu

repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
state_dir="$(mktemp -d "${TMPDIR:-/tmp}/dnd-dm-gateway-wait.XXXXXX")"
trap 'rm -rf "$state_dir"' EXIT INT TERM

mkdir -p "$state_dir/bin"

cat >"$state_dir/bin/curl" <<'EOF'
#!/bin/bash
count=0
[ ! -f "$DND_TEST_CURL_COUNT" ] || count="$(sed -n '1p' "$DND_TEST_CURL_COUNT")"
count=$((count + 1))
printf '%s\n' "$count" >"$DND_TEST_CURL_COUNT"
if [ "$count" -lt 3 ]; then
  exit 22
fi
touch "$DND_TEST_BACKEND_READY"
exit 0
EOF
cat >"$state_dir/bin/npm" <<'EOF'
#!/bin/bash
[ -f "$DND_TEST_BACKEND_READY" ] || exit 41
printf '%s\n' "$*" >"$DND_TEST_NPM_LOG"
exit 0
EOF
cat >"$state_dir/bin/python" <<'EOF'
#!/bin/bash
[ "$*" != "-c import alembic" ] || exit 0
[ -f "$DND_TEST_BACKEND_READY" ] || exit 43
printf '%s\n' "$*" >>"$DND_TEST_PYTHON_LOG"
exit 0
EOF
chmod +x "$state_dir/bin/curl" "$state_dir/bin/npm" \
  "$state_dir/bin/python"

DND_TEST_CURL_COUNT="$state_dir/curl-count" \
DND_TEST_BACKEND_READY="$state_dir/backend.ready" \
DND_TEST_NPM_LOG="$state_dir/npm.log" \
DND_TEST_PYTHON_LOG="$state_dir/python.log" \
DND_DM_GATEWAY_NPM="$state_dir/bin/npm" \
DND_DM_GATEWAY_PYTHON="$state_dir/bin/python" \
PATH="$state_dir/bin:$PATH" \
  /bin/bash "$repo_dir/scripts/player-gateway.sh" >"$state_dir/output.log" 2>&1

if [ "$(sed -n '1p' "$state_dir/curl-count")" -ne 3 ]; then
  echo "Player gateway did not wait for backend readiness" >&2
  exit 1
fi
if ! grep -F -- "--prefix frontend run build" "$state_dir/npm.log" >/dev/null; then
  echo "Player gateway did not build the frontend after backend readiness" >&2
  exit 1
fi
if ! grep -F -- "-m alembic -c backend/alembic.ini upgrade head" "$state_dir/python.log" >/dev/null; then
  echo "Player gateway did not verify migrations after backend readiness" >&2
  exit 1
fi
if ! grep -F -- "--host 0.0.0.0 --port 8787 --no-access-log" "$state_dir/python.log" >/dev/null; then
  echo "Player gateway did not bind the isolated LAN service correctly" >&2
  exit 1
fi

echo "Player gateway backend-readiness regression passed."
