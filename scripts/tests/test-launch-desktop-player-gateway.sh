#!/bin/bash
set -eu

repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
state_dir="$(mktemp -d "${TMPDIR:-/tmp}/dnd-dm-launch-gateway.XXXXXX")"
trap 'rm -rf "$state_dir"' EXIT INT TERM

mkdir -p "$state_dir/bin" "$state_dir/logs"

cat >"$state_dir/diagnose.sh" <<'EOF'
#!/bin/bash
exit 0
EOF
cat >"$state_dir/player-gateway.sh" <<'EOF'
#!/bin/bash
touch "$DND_TEST_GATEWAY_READY"
exit 0
EOF
cat >"$state_dir/bin/curl" <<'EOF'
#!/bin/bash
for argument in "$@"; do
  case "$argument" in
    http://127.0.0.1:8787/api/v1/health)
      [ -f "$DND_TEST_GATEWAY_READY" ] && exit 0
      exit 22
      ;;
  esac
done
printf '%s\n' '{"status":"ok"}'
exit 0
EOF
cat >"$state_dir/bin/open" <<'EOF'
#!/bin/bash
printf '%s\n' "$1" >"$DND_TEST_OPEN_LOG"
EOF
chmod +x "$state_dir/diagnose.sh" "$state_dir/player-gateway.sh" \
  "$state_dir/bin/curl" "$state_dir/bin/open"

DND_TEST_GATEWAY_READY="$state_dir/gateway.ready" \
DND_TEST_OPEN_LOG="$state_dir/open.log" \
DND_DM_LOG_DIR="$state_dir/logs" \
DND_DM_DIAGNOSE_SCRIPT="$state_dir/diagnose.sh" \
DND_DM_PLAYER_GATEWAY_SCRIPT="$state_dir/player-gateway.sh" \
PATH="$state_dir/bin:$PATH" \
  /bin/bash "$repo_dir/scripts/launch-desktop.sh" >"$state_dir/output.log" 2>&1

if [ ! -f "$state_dir/gateway.ready" ]; then
  echo "Desktop launcher did not start the missing player gateway" >&2
  exit 1
fi
if [ "$(sed -n '1p' "$state_dir/open.log")" != "http://127.0.0.1:5173/" ]; then
  echo "Desktop launcher did not preserve the loopback DM URL" >&2
  exit 1
fi
if ! grep -F "局域网玩家网关已就绪" "$state_dir/output.log" >/dev/null; then
  echo "Desktop launcher did not report player gateway readiness" >&2
  exit 1
fi

echo "Desktop launcher player-gateway regression passed."
